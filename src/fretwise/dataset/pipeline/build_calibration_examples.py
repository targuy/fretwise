"""Build calibration examples for FretWise Phase 3 integration testing.

Creates 3 real examples from X_transitions matching FretWise's spec:
  (a) Trivial: same string, adjacent fret (e.g., fret 2->3)
  (b) Chord onset with barre: open position -> fret 1 barre chord
  (c) Long position shift: >3 fret jump

Each example includes full features, model probabilities, and predicted cost.
Cost definition: -log(p[ground_truth_finger]) (Viterbi path cost convention).

Saves to shared dir as transition_cost_v2_calibration.json
"""

import json
import math

import numpy as np

from fretwise.dataset._mldeps import optional_import
from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR

xgb = optional_import("xgboost")

PHASE3_DIR = PROCESSED_DIR / "phase3"
DROP_FEATURES = {"curr_finger", "position_inferred"}
FINGER_NAMES = {0: "open", 1: "index", 2: "middle", 3: "ring", 4: "pinky"}


def load_data():
    X_raw = np.load(PHASE3_DIR / "X_transitions.npy")
    y_raw = np.load(PHASE3_DIR / "y_transitions.npy")
    sources_raw = np.load(PHASE3_DIR / "sources.npy")
    with open(PHASE3_DIR / "feature_names.json") as f:
        raw_names = json.load(f)

    # Filter invalid rows
    position_cols = ["prev_string", "curr_string", "prev_fret", "curr_fret"]
    col_indices = [raw_names.index(c) for c in position_cols]
    valid_mask = np.ones(X_raw.shape[0], dtype=bool)
    for idx in col_indices:
        col = X_raw[:, idx]
        valid_mask &= col >= 0
        if np.issubdtype(col.dtype, np.floating):
            valid_mask &= ~np.isnan(col)
    X_filt = X_raw[valid_mask]
    y_filt = y_raw[valid_mask]
    sources_filt = sources_raw[valid_mask]

    # Drop features
    keep_cols = [i for i, name in enumerate(raw_names) if name not in DROP_FEATURES]
    X_clean = X_filt[:, keep_cols]
    clean_names = [raw_names[i] for i in keep_cols]
    return X_clean, y_filt, sources_filt, clean_names


def row_to_dict(row, feature_names):
    return {name: round(float(row[j]), 4) for j, name in enumerate(feature_names)}


def find_example(X, y, feature_names, condition_fn, label):
    """Find first row matching condition_fn(feature_dict)."""
    for i in range(len(y)):
        fdict = row_to_dict(X[i], feature_names)
        if condition_fn(fdict):
            return i, fdict, int(y[i])
    raise ValueError(f"No example found for: {label}")


def build_example(label, description, idx, fdict, y_true, model, feature_names, X, source):
    """Build one calibration example with model predictions."""
    row = X[idx:idx+1].astype(np.float32)
    dmat = xgb.DMatrix(row, feature_names=feature_names)
    probs = model.predict(dmat)[0]
    predicted_finger = int(np.argmax(probs))

    # Cost = -log(p[ground_truth]) -- Viterbi convention
    p_true = float(probs[y_true])
    cost = -math.log(max(p_true, 1e-10))

    source_name = "classclef" if source == 1 else "gaps"
    string_conv = "0=high_E" if source == 1 else "0=low_E"

    return {
        "label": label,
        "source": source_name,
        "string_convention": string_conv,
        "description": description,
        "prev_state": {
            "string": int(fdict["prev_string"]),
            "fret": int(fdict["prev_fret"]),
            "finger": FINGER_NAMES.get(int(fdict["prev_finger"]), "unknown"),
            "midi": int(fdict["prev_midi"]),
        },
        "curr_state": {
            "string": int(fdict["curr_string"]),
            "fret": int(fdict["curr_fret"]),
            "midi": int(fdict["curr_midi"]),
            "ground_truth_finger": FINGER_NAMES[y_true],
        },
        "features_expected": fdict,
        "model_output": {
            "probabilities": {FINGER_NAMES[k]: round(float(probs[k]), 6) for k in range(5)},
            "predicted_finger": FINGER_NAMES[predicted_finger],
            "ground_truth_finger": FINGER_NAMES[y_true],
            "predicted_cost": round(cost, 4),
            "cost_definition": "-log(p[ground_truth_finger])",
        },
    }


def main():
    X, y, sources, feature_names = load_data()
    print(f"Loaded {len(y)} transitions, {len(feature_names)} features")

    model = xgb.Booster()
    model.load_model(str(PHASE3_DIR / "xgb_transition_cost_v2.json"))

    examples = []

    # (a) Trivial: same string, adjacent fret, finger 1->2 (index->middle)
    idx_a, fd_a, y_a = find_example(X, y, feature_names, lambda d: (
        d["same_string"] == 1 and
        d["fret_distance"] == 1 and
        d["prev_fret"] >= 1 and d["prev_fret"] <= 5 and
        d["prev_finger"] == 1 and
        d["curr_fret"] >= 2 and d["curr_fret"] <= 6
    ), "trivial_adjacent")
    examples.append(build_example(
        "trivial_adjacent_fret",
        f"Same string, fret {int(fd_a['prev_fret'])}->{int(fd_a['curr_fret'])}, "
        f"index->{FINGER_NAMES[y_a]}",
        idx_a, fd_a, y_a, model, feature_names, X, sources[idx_a]
    ))
    print(f"(a) trivial: row {idx_a}, prev_fret={fd_a['prev_fret']}, "
          f"curr_fret={fd_a['curr_fret']}, finger={FINGER_NAMES[y_a]}")

    # (b) Chord onset with barre: open string -> fret 1 (barre position)
    idx_b, fd_b, y_b = find_example(X, y, feature_names, lambda d: (
        d["prev_is_open"] == 1 and
        d["curr_fret"] == 1 and
        d["curr_is_open"] == 0 and
        d["curr_string"] >= 4  # strings 4-5 = A,low_E (bass), typical for barre root
    ), "barre_onset")
    examples.append(build_example(
        "chord_onset_barre",
        f"Open string -> fret 1 barre (string {int(fd_b['curr_string'])}), "
        f"finger={FINGER_NAMES[y_b]}",
        idx_b, fd_b, y_b, model, feature_names, X, sources[idx_b]
    ))
    print(f"(b) barre: row {idx_b}, prev_fret={fd_b['prev_fret']}, "
          f"curr_fret={fd_b['curr_fret']}, string={fd_b['curr_string']}")

    # (c) Long position shift: >3 fret jump
    idx_c, fd_c, y_c = find_example(X, y, feature_names, lambda d: (
        d["fret_distance_abs"] > 3 and
        d["prev_fret"] >= 1 and
        d["curr_fret"] >= 5 and
        d["prev_finger"] > 0  # not open string
    ), "long_shift")
    examples.append(build_example(
        "long_position_shift",
        f"Fret {int(fd_c['prev_fret'])}->{int(fd_c['curr_fret'])} "
        f"(jump={int(fd_c['fret_distance_abs'])}), finger={FINGER_NAMES[y_c]}",
        idx_c, fd_c, y_c, model, feature_names, X, sources[idx_c]
    ))
    print(f"(c) long shift: row {idx_c}, prev_fret={fd_c['prev_fret']}, "
          f"curr_fret={fd_c['curr_fret']}, jump={fd_c['fret_distance_abs']}")

    # Output
    output = {
        "model_version": "v2",
        "model_file": "xgb_transition_cost_v2.json",
        "onnx_file": "transition_cost_v2.onnx",
        "n_features": len(feature_names),
        "feature_order": feature_names,
        "cost_definition": "-log(p[ground_truth_finger]) -- Viterbi path cost (sum of neg log-probs)",
        "note": "features_expected extracted from real training data row, not fabricated",
        "string_convention_warning": "Mixed convention in training data. ClassClef: 0=high_E. GAPS: 0=low_E. Each example's source and convention are tagged.",
        "context_fields_not_in_model": [
            "onset_prev", "onset_curr", "tempo", "articulation_curr",
            "techniques_curr", "is_chord_member_curr", "chord_size_curr",
            "time_to_next_note"
        ],
        "examples": examples,
    }

    out_path = HANDOFF_DIR / "transition_cost_v2_calibration.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    print(f"\nCalibration saved: {out_path}")


if __name__ == "__main__":
    main()
