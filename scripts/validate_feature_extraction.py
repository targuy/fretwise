"""Validate fretwise.ml.extract_chord_features against GuitarDataSet's
reference calibration JSON.

Loads test cases from
``handoff-FretWise-GuitarDataset/GuitarDataset-feature-calibration.json``
and compares the 24-feature vectors per note.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.ml import ChordNote, extract_chord_features

CALIB_PATH = Path(
    "E:/DocumentsBenoit/pythonProject/handoff-FretWise-GuitarDataset/"
    "GuitarDataset-feature-calibration.json"
)


def main() -> None:
    calib = json.loads(CALIB_PATH.read_text(encoding="utf-8"))
    feature_order = calib["feature_order"]
    print(f"Loaded {len(calib['test_cases'])} test cases\n")

    all_match = True
    for case in calib["test_cases"]:
        name = case["chord_name"]
        strings = case["strings"]
        is_barre_chord = case.get("is_barre", False)

        fretted_string_nums = [
            6 - i for i, f in enumerate(strings) if f is not None and f > 0
        ]
        fretted_frets = [f for f in strings if f is not None and f > 0]
        n_open = sum(1 for f in strings if f == 0)

        min_fret = min(fretted_frets)
        same_min_count = fretted_frets.count(min_fret)
        chord_notes = [
            ChordNote(
                string=sn,
                fret=fr,
                pitch=0,  # not used in feature extraction
                is_barre_candidate=is_barre_chord and fr == min_fret and same_min_count >= 2,
            )
            for sn, fr in zip(fretted_string_nums, fretted_frets)
        ]

        my_features = extract_chord_features(chord_notes, n_open=n_open)

        gds_notes_by_string = {n["string_num"]: n["features_array"] for n in case["notes"]}
        print(f"=== {name} ===")
        for mine, note in zip(my_features, chord_notes):
            expected = gds_notes_by_string[note.string]
            mismatches = [
                (feature_order[i], mine[i], expected[i])
                for i in range(24)
                if mine[i] != expected[i]
            ]
            if not mismatches:
                print(f"  string={note.string} fret={note.fret}: MATCH")
            else:
                all_match = False
                print(f"  string={note.string} fret={note.fret}: MISMATCH")
                for fname, m, e in mismatches:
                    print(f"    {fname}: mine={m}  expected={e}")
        print()

    print("=" * 50)
    print("ALL FEATURES MATCH" if all_match else "MISMATCHES DETECTED")


if __name__ == "__main__":
    main()
