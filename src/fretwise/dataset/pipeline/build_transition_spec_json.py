"""Build transition_cost_v2_spec.json for FretWise cross-validation.

Loads a real transition from the training data, runs it through the model,
and produces a spec file with feature names, descriptions, and a test case.
"""

import json

import numpy as np

from fretwise.dataset._mldeps import optional_import
from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR

xgb = optional_import("xgboost")

PHASE3_DIR = PROCESSED_DIR / "phase3"
SPEC_PATH = HANDOFF_DIR / "transition_cost_v2_spec.json"

FEATURE_DESCRIPTIONS = {
    "curr_fret": "Fret number of current note (0=open, 1-24)",
    "curr_is_high_fret": "1 if current fret >= 7, else 0",
    "curr_is_open": "1 if current note is open string (fret 0), else 0",
    "curr_midi": "MIDI pitch of current note (0-127)",
    "curr_string": "String number of current note (1=high E, 6=low E)",
    "curr_string_group": "Binary string group: 0 if string<=2 (bass), 1 if string>=3 (treble)",
    "fret_distance": "Signed fret difference: curr_fret - prev_fret",
    "fret_distance_abs": "Absolute fret distance between notes",
    "interval_abs": "Absolute interval in semitones",
    "interval_direction": "Interval direction: -1=descending, 0=unison, 1=ascending (sign of curr_midi - prev_midi)",
    "interval_semitones": "Signed interval in semitones (curr_midi - prev_midi)",
    "position_shift": "Binary flag: 1 if abs(curr_fret - prev_fret) > 4, else 0",
    "prev_finger": "Finger used for previous note (0=open/thumb, 1=index, 2=middle, 3=ring, 4=pinky)",
    "prev_finger_is_index": "1 if previous finger was index (1), else 0",
    "prev_finger_is_open": "1 if previous finger was open/thumb (0), else 0",
    "prev_finger_is_pinky": "1 if previous finger was pinky (4), else 0",
    "prev_fret": "Fret number of previous note (0=open, 1-24)",
    "prev_is_high_fret": "1 if previous fret >= 7, else 0",
    "prev_is_open": "1 if previous note is open string, else 0",
    "prev_midi": "MIDI pitch of previous note (0-127)",
    "prev_string": "String number of previous note (1=high E, 6=low E)",
    "prev_string_group": "Binary string group of previous note: 0 if string<=2 (bass), 1 if string>=3 (treble)",
    "same_fret": "1 if both notes on the same fret, else 0",
    "same_string": "1 if both notes on the same string, else 0",
    "string_distance": "Signed string difference: curr_string - prev_string",
    "string_distance_abs": "Absolute string distance between notes",
}

FINGER_NAMES = {0: "open/thumb", 1: "index", 2: "middle", 3: "ring", 4: "pinky"}


def load_v2_features():
    with open(PHASE3_DIR / "training_report_v2.json") as f:
        report = json.load(f)
    return report["feature_names"], report


def load_filtered_data():
    """Reproduce the exact filtering from train_transition_cost_v2.py."""
    X_raw = np.load(PHASE3_DIR / "X_transitions.npy")
    y_raw = np.load(PHASE3_DIR / "y_transitions.npy")
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

    # Drop curr_finger and position_inferred
    drop_features = {"curr_finger", "position_inferred"}
    keep_cols = [i for i, name in enumerate(raw_names) if name not in drop_features]
    X_clean = X_filt[:, keep_cols]
    clean_names = [raw_names[i] for i in keep_cols]

    return X_clean, y_filt, clean_names


def pick_test_case(X, y, feature_names):
    """Pick a non-trivial test case (non-open string, interesting transition)."""
    # Find a row where prev and curr are fretted (not open), different strings
    for i in range(len(y)):
        row = X[i]
        fdict = {name: float(row[j]) for j, name in enumerate(feature_names)}
        if (fdict["prev_fret"] > 0 and fdict["curr_fret"] > 0
                and fdict["same_string"] == 0 and fdict["prev_finger"] > 0):
            return i, row, fdict
    # Fallback: first row
    row = X[0]
    fdict = {name: float(row[j]) for j, name in enumerate(feature_names)}
    return 0, row, fdict


def main():
    feature_names, report = load_v2_features()
    X, y, clean_names = load_filtered_data()

    # Verify feature order matches
    assert clean_names == feature_names, (
        f"Feature order mismatch!\n  report: {feature_names}\n  computed: {clean_names}"
    )

    # Pick test case
    idx, row, fdict = pick_test_case(X, y, feature_names)
    test_label = int(y[idx])

    # Run model to get predictions
    model = xgb.Booster()
    model.load_model(str(PHASE3_DIR / "xgb_transition_cost_v2.json"))

    dmat = xgb.DMatrix(row.reshape(1, -1).astype(np.float32), feature_names=feature_names)
    probs = model.predict(dmat)[0]
    predicted_finger = int(np.argmax(probs))

    print(f"Test case row {idx}:")
    print(f"  prev: string={fdict['prev_string']:.0f} fret={fdict['prev_fret']:.0f} "
          f"finger={FINGER_NAMES.get(int(fdict['prev_finger']), '?')} midi={fdict['prev_midi']:.0f}")
    print(f"  curr: string={fdict['curr_string']:.0f} fret={fdict['curr_fret']:.0f} "
          f"midi={fdict['curr_midi']:.0f}")
    print(f"  Ground truth finger: {test_label} ({FINGER_NAMES[test_label]})")
    print(f"  Predicted finger:    {predicted_finger} ({FINGER_NAMES[predicted_finger]})")
    print(f"  Probabilities: {[round(float(p), 6) for p in probs]}")

    # Build spec
    spec = {
        "model_file": "transition_cost_v2.onnx",
        "model_info": {
            "version": "v2",
            "objective": "multi:softprob",
            "n_classes": 5,
            "class_labels": FINGER_NAMES,
            "n_features": len(feature_names),
            "cv_5fold_accuracy": report["cv_5fold_mean"],
            "classclef_val_accuracy": report["classclef_accuracy"],
            "gaps_holdout_accuracy": report["gaps_holdout_accuracy"],
            "training_samples": report["training_samples"],
            "best_rounds": report["best_rounds"],
        },
        "feature_names": feature_names,
        "feature_descriptions": {
            name: FEATURE_DESCRIPTIONS.get(name, "undocumented")
            for name in feature_names
        },
        "test_case": {
            "description": (
                f"Transition from string {fdict['prev_string']:.0f} fret {fdict['prev_fret']:.0f} "
                f"({FINGER_NAMES.get(int(fdict['prev_finger']), '?')}) "
                f"to string {fdict['curr_string']:.0f} fret {fdict['curr_fret']:.0f}"
            ),
            "input": {name: round(float(fdict[name]), 4) for name in feature_names},
            "expected_output": {
                "ground_truth_finger": test_label,
                "predicted_finger": predicted_finger,
                "probabilities": [round(float(p), 6) for p in probs],
            },
        },
    }

    with open(SPEC_PATH, "w") as f:
        json.dump(spec, f, indent=2)
    print(f"\nSpec saved: {SPEC_PATH}")


if __name__ == "__main__":
    main()
