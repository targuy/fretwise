#!/usr/bin/env python3
"""Audit de la distribution des doigts sur l'ensemble du corpus GP.

Usage: python scripts/audit_finger_distribution.py
Sortie: tableau de distribution par fichier + total corpus.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.generator import StateGenerator
from fretwise.models import Finger
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"
CORPUS_TOTAL: Counter[str] = Counter()
CORPUS_NOTES = 0


def audit_file(path: Path) -> None:
    global CORPUS_NOTES
    try:
        adapter = get_adapter(path)
        events = adapter.parse(path)
    except Exception as exc:
        print(f"  SKIP {path.name}: {exc}")
        return

    if not events:
        return

    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(events, generator, optimizer, pattern_matcher=matcher)

    counter: Counter[str] = Counter()
    for r in results:
        # Extract finger name from Finger enum
        finger_name = r.state.finger.value.upper()
        counter[finger_name] += 1

    total = sum(counter.values())
    CORPUS_NOTES += total
    for k, v in counter.items():
        CORPUS_TOTAL[k] += v

    print(f"\n{path.stem}")
    print(f"  Total notes : {total}")
    for finger in ["OPEN", "INDEX", "MIDDLE", "RING", "PINKY"]:
        count = counter.get(finger, 0)
        pct = 100 * count / total if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {finger:<8} {count:5d}  {pct:5.1f}%  {bar}")

    ring_pinky = counter.get("RING", 0) + counter.get("PINKY", 0)
    idx_mid    = counter.get("INDEX", 0) + counter.get("MIDDLE", 0)
    rp_pct = 100 * ring_pinky / total if total else 0
    im_pct = 100 * idx_mid / total if total else 0
    print(f"  -> INDEX+MIDDLE: {im_pct:.1f}%   RING+PINKY: {rp_pct:.1f}%")


def main() -> None:
    files = sorted(FIXTURES.glob("*.gp*"))
    if not files:
        print(f"No GP files found in {FIXTURES}")
        return

    print(f"Corpus: {len(files)} fichiers\n{'=' * 60}")
    for f in files:
        audit_file(f)

    print(f"\n{'=' * 60}")
    print(f"TOTAL CORPUS ({CORPUS_NOTES} notes)")
    total = sum(CORPUS_TOTAL.values())
    for finger in ["OPEN", "INDEX", "MIDDLE", "RING", "PINKY"]:
        count = CORPUS_TOTAL.get(finger, 0)
        pct = 100 * count / total if total else 0
        bar = "#" * int(pct / 2)
        print(f"  {finger:<8} {count:6d}  {pct:5.1f}%  {bar}")

    ring_pinky = CORPUS_TOTAL.get("RING", 0) + CORPUS_TOTAL.get("PINKY", 0)
    idx_mid    = CORPUS_TOTAL.get("INDEX", 0) + CORPUS_TOTAL.get("MIDDLE", 0)
    print(f"\n  INDEX+MIDDLE : {100 * idx_mid  / total:.1f}%")
    print(f"  RING+PINKY   : {100 * ring_pinky / total:.1f}%")
    print(f"\n  Ratio RP/IM  : {ring_pinky / max(idx_mid, 1):.3f}  (humain attendu: ~0.5-0.7)")


if __name__ == "__main__":
    main()
