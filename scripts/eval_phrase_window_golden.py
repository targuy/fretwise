"""Re-baseline a phrase_window shadow bundle on golden_set_v1.

Evaluation harness (NOT training) for the shadow fingering model. Loads the
human-validated golden cases, runs the bundle with FretWise's corrected
feature extractor, and reports per-note accuracy, exact-window-match rate,
pinky false-positive rate, and anchor accuracy — the same metrics
GuitarDataSet reports in ``phrase_window_fingering_{version}_metrics.json``,
so the numbers are directly comparable.

Usage:
    pixi run python scripts/eval_phrase_window_golden.py [--version v2]

Discipline: golden_set_v1 is ``training_allowed: false`` — eval only.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from fretwise.ml import LearnedPhraseWindowFingerer, PhraseNote

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS = REPO_ROOT / "data" / "models"
GOLDEN = MODELS / "golden_set_v1.jsonl"


def _case_notes(case: dict[str, Any]) -> list[PhraseNote]:
    """Build PhraseNotes from a golden case's ``expected`` block.

    Strings are converted from FretWise 1-based to internal 0-based; pitch is
    derived from the case tuning. Notes are treated as a sequential phrase
    window (onset = order), matching the model's melodic framing.
    """
    tuning = case["tuning"]  # [high_e, B, G, D, A, low_E] in FW 1-based order
    notes: list[PhraseNote] = []
    for entry in sorted(case["expected"], key=lambda e: e["order"]):
        string_num = entry["string_num"]
        fret = entry["fret"]
        notes.append(PhraseNote(
            string=string_num - 1,
            fret=fret,
            pitch=tuning[string_num - 1] + fret,
            onset=float(entry["order"]),
            duration=1.0,
        ))
    return notes


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--version",
        default="v1",
        help="phrase_window bundle version to evaluate (default: v1)",
    )
    args = parser.parse_args()
    version: str = args.version

    if not GOLDEN.exists():
        raise SystemExit(f"Golden set missing: {GOLDEN}")
    model = LearnedPhraseWindowFingerer.from_model_dir(MODELS, version=version)

    total = correct = 0
    exact_cases = 0
    n_cases = 0
    non_pinky_expected = pinky_false_pos = 0
    anchor_total = anchor_correct = 0

    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        n_cases += 1
        expected = sorted(case["expected"], key=lambda e: e["order"])
        notes = _case_notes(case)
        predictions = model.predict_sequence(notes)

        case_all_correct = True
        for entry, pred in zip(expected, predictions):
            exp_finger = entry["finger"]
            total += 1
            if pred.finger == exp_finger:
                correct += 1
            else:
                case_all_correct = False
            if exp_finger != "pinky":
                non_pinky_expected += 1
                if pred.finger == "pinky":
                    pinky_false_pos += 1
            exp_anchor = entry.get("anchor")
            if exp_anchor is not None:
                anchor_total += 1
                if pred.anchor == exp_anchor:
                    anchor_correct += 1
        if case_all_correct:
            exact_cases += 1

    def pct(num: int, den: int) -> float:
        return num / den if den else 0.0

    print(
        f"golden_set_v1 re-baseline of phrase_window_{version} "
        f"(corrected features) — {n_cases} cases"
    )
    print(f"  per_note_accuracy        : {pct(correct, total):.4f}  ({correct}/{total})")
    print(f"  exact_window_match_rate  : {pct(exact_cases, n_cases):.4f}  "
          f"({exact_cases}/{n_cases})")
    print(f"  pinky_false_positive_rate: {pct(pinky_false_pos, non_pinky_expected):.4f}  "
          f"({pinky_false_pos}/{non_pinky_expected})")
    print(f"  anchor_accuracy          : {pct(anchor_correct, anchor_total):.4f}  "
          f"({anchor_correct}/{anchor_total})")


if __name__ == "__main__":
    main()
