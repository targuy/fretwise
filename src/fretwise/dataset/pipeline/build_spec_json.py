"""Build transition_cost_v2_spec.json for FretWise integration.

Includes:
- feature_names (ordered, v2: 26 features without curr_finger/position_inferred)
- feature_types (all float32)
- feature_ranges (min/max from training data)
- feature_dependency (prev_state / curr_state / pair / context)
- output spec (softmax, 5 classes)

Saves to shared dir.
"""

import json

import numpy as np

from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR

PHASE3_DIR = PROCESSED_DIR / "phase3"
DROP_FEATURES = {"curr_finger", "position_inferred"}

# Feature dependency classification
DEPENDENCY_MAP = {
    "curr_fret": "curr_state",
    "curr_is_high_fret": "curr_state",
    "curr_is_open": "curr_state",
    "curr_midi": "curr_state",
    "curr_string": "curr_state",
    "curr_string_group": "curr_state",
    "prev_finger": "prev_state",
    "prev_finger_is_index": "prev_state",
    "prev_finger_is_open": "prev_state",
    "prev_finger_is_pinky": "prev_state",
    "prev_fret": "prev_state",
    "prev_is_high_fret": "prev_state",
    "prev_is_open": "prev_state",
    "prev_midi": "prev_state",
    "prev_string": "prev_state",
    "prev_string_group": "prev_state",
    "fret_distance": "pair",
    "fret_distance_abs": "pair",
    "interval_abs": "pair",
    "interval_direction": "pair",
    "interval_semitones": "pair",
    "position_shift": "pair",
    "same_fret": "pair",
    "same_string": "pair",
    "string_distance": "pair",
    "string_distance_abs": "pair",
}


def load_filtered_data():
    X_raw = np.load(PHASE3_DIR / "X_transitions.npy")
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

    # Drop features
    keep_cols = [i for i, name in enumerate(raw_names) if name not in DROP_FEATURES]
    X_clean = X_filt[:, keep_cols]
    clean_names = [raw_names[i] for i in keep_cols]
    return X_clean, clean_names


def main():
    X, feature_names = load_filtered_data()
    print(f"Loaded {X.shape[0]} rows, {len(feature_names)} features")

    # Compute ranges
    feature_ranges = {}
    for j, name in enumerate(feature_names):
        col = X[:, j]
        feature_ranges[name] = {
            "min": round(float(np.nanmin(col)), 4),
            "max": round(float(np.nanmax(col)), 4),
        }

    # Build spec
    spec = {
        "model_file": "transition_cost_v2.onnx",
        "fallback_model_file": "xgb_transition_cost_v2.json",
        "feature_names": feature_names,
        "feature_types": {name: "float32" for name in feature_names},
        "feature_ranges": feature_ranges,
        "feature_dependency": {name: DEPENDENCY_MAP[name] for name in feature_names},
        "string_convention": {
            "indexing": "0-based",
            "range": [0, 5],
            "mapping": "0=high_E (thinnest, avg MIDI 68), 1=B, 2=G, 3=D, 4=A, 5=low_E (thickest, avg MIDI 55)",
            "string_group": "0-2 = treble (group 0), 3-5 = bass (group 1)",
            "note": "Same direction as GPIF: 0=high E, 5=low E. FW 1-based (1-6): subtract 1.",
        },
        "context_fields_not_used": [
            "tempo", "articulation", "techniques", "is_chord_member",
            "chord_size", "time_to_next_note", "onset_time"
        ],
        "output": {
            "type": "softmax",
            "classes": [0, 1, 2, 3, 4],
            "class_names": ["open", "index", "middle", "ring", "pinky"],
        },
    }

    out_path = HANDOFF_DIR / "transition_cost_v2_spec.json"
    with open(out_path, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"Spec saved: {out_path}")

    # Print summary
    deps = {}
    for name in feature_names:
        dep = DEPENDENCY_MAP[name]
        deps.setdefault(dep, []).append(name)
    for dep, names in sorted(deps.items()):
        print(f"  {dep}: {len(names)} features")


if __name__ == "__main__":
    main()
