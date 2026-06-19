"""Empirical validation of Phase 2 ChordFingerClassifier on real files.

For each test file: runs the pipeline twice (once without classifier, once
with) and compares the per-onset chord-finger assignments. Reports the
diff count and a sample of changes.

Usage:
    PYTHONIOENCODING=utf-8 python scripts/validate_phase2_active.py
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.generator import StateGenerator
from fretwise.ml import LearnedChordFingerClassifier
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

PARTITIONS = Path(__file__).parents[1] / "partitions"
MODEL_DIR = Path(__file__).parents[1] / "data" / "models"

TEST_FILES = [
    "Bb King-The Thrill Is Gone-12-26-2025.gp",
    "Steppenwolf-Born To Be Wild-10-15-2025.gp",
    "Django Reinhardt-Nuages-05-30-2025.gp",
    "Cream-Sunshine Of Your Love-12-26-2025.gp",
    "ZZ Top-La Grange-02-25-2026.gp",
    "The Beatles-Yesterday-01-22-2026.gp",
    "Dire Straits-Sultans Of Swing-12-16-2025.gp",
]


def _solve(path: Path, classifier=None):
    adapter = get_adapter(path)
    events = adapter.parse(path)
    if not events:
        return []
    gen = StateGenerator()
    cost = CostFunction(weights=CostWeights.performance())
    opt = ViterbiOptimizer(cost)
    matcher = PatternMatcher()
    results, _ = run_pipeline(
        events, gen, opt, pattern_matcher=matcher,
        chord_finger_classifier=classifier,
    )
    return results


def main() -> None:
    classifier = LearnedChordFingerClassifier(
        str(MODEL_DIR / "finger_classifier.onnx"),
        str(MODEL_DIR / "finger_classifier_spec.json"),
    )
    print(f"Loaded ONNX classifier from {MODEL_DIR}\n")

    for fname in TEST_FILES:
        path = PARTITIONS / fname
        if not path.exists():
            print(f"SKIP {fname}: not found")
            continue

        results_no_ml = _solve(path)
        results_ml = _solve(path, classifier=classifier)

        if len(results_no_ml) != len(results_ml):
            print(f"!!! {fname}: result count differs ({len(results_no_ml)} vs {len(results_ml)})")
            continue

        # Compare finger fields per note
        diffs: list[tuple[float, int, int, str, str]] = []
        for r_a, r_b in zip(results_no_ml, results_ml):
            if r_a.state.finger != r_b.state.finger:
                diffs.append((
                    r_a.note_event.onset,
                    r_a.state.string_num,
                    r_a.state.fret,
                    r_a.state.finger.name,
                    r_b.state.finger.name,
                ))

        # Count finger distribution change
        c_no_ml = Counter(r.state.finger.name for r in results_no_ml)
        c_ml = Counter(r.state.finger.name for r in results_ml)
        n = len(results_ml)

        # Count how many chord onsets (≥2 simultaneous fretted notes)
        chord_count: dict[float, int] = defaultdict(int)
        for r in results_ml:
            if r.state.fret > 0:
                chord_count[round(r.note_event.onset, 4)] += 1
        n_chord_onsets = sum(1 for c in chord_count.values() if c >= 2)

        print(f"=== {fname} ===")
        print(f"  {n} notes total, {n_chord_onsets} chord onsets (≥2 fretted simultaneously)")
        print(f"  Diffs: {len(diffs)} ({100*len(diffs)/max(n,1):.1f}%)")
        for finger in ("INDEX", "MIDDLE", "RING", "PINKY"):
            a = c_no_ml.get(finger, 0)
            b = c_ml.get(finger, 0)
            delta = b - a
            sign = "+" if delta > 0 else ""
            print(f"    {finger:<7} {a:>4} -> {b:>4}  ({sign}{delta})")
        if diffs[:5]:
            print(f"  Sample diffs:")
            for onset, s, f, no_ml, ml in diffs[:5]:
                print(f"    onset={onset:.2f} string={s} fret={f}  {no_ml} -> {ml}")
        print()


if __name__ == "__main__":
    main()
