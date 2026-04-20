#!/usr/bin/env python3
"""Détecte les mesures où RING+PINKY > seuil et les compare à une estimation humaine.

Usage: python scripts/audit_ring_pinky_measures.py [--threshold 0.6]
Seuil par défaut : 60% des notes dans la mesure jouées avec RING ou PINKY.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
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

_RP = {Finger.RING, Finger.PINKY}


def audit_file(path: Path, threshold: float) -> list[dict]:
    try:
        adapter = get_adapter(path)
        events = adapter.parse(path)
    except Exception as exc:
        print(f"  SKIP {path.name}: {exc}")
        return []

    if not events:
        return []

    beats_pm = float(getattr(adapter, "beats_per_measure", 4.0))
    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(events, generator, optimizer, pattern_matcher=matcher)

    by_measure: dict[int, list] = defaultdict(list)
    for r in results:
        m_idx = int(r.note_event.onset // beats_pm)
        by_measure[m_idx].append(r)

    flagged = []
    for m_idx in sorted(by_measure):
        notes = by_measure[m_idx]
        total = len(notes)
        if total == 0:
            continue
        rp_count = sum(1 for r in notes if r.state.finger in _RP)
        rp_pct = rp_count / total
        if rp_pct >= threshold:
            frets = [r.state.fret for r in notes]
            fingers = [r.state.finger.name for r in notes]
            flagged.append({
                "measure": m_idx + 1,
                "total_notes": total,
                "rp_pct": rp_pct,
                "frets": frets,
                "fingers": fingers,
            })

    return flagged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="Fraction de RING/PINKY pour signaler une mesure (défaut: 0.6)")
    args = parser.parse_args()

    files = sorted(FIXTURES.glob("*.gp*"))
    total_flagged = 0

    for path in files:
        flagged = audit_file(path, args.threshold)
        if flagged:
            print(f"\n{path.stem}  ({len(flagged)} mesure(s) > {args.threshold*100:.0f}% RP)")
            for m in flagged[:10]:
                print(
                    f"  Mesure {m['measure']:3d} : "
                    f"{m['rp_pct']*100:.0f}% RP "
                    f"({m['total_notes']} notes) "
                    f"frets={m['frets']} "
                    f"fingers={m['fingers']}"
                )
            total_flagged += len(flagged)

    print(f"\n{'=' * 60}")
    print(f"Mesures > {args.threshold*100:.0f}% RING/PINKY : {total_flagged}")
    print("(Verifier manuellement si un guitariste humain utiliserait INDEX/MIDDLE)")


if __name__ == "__main__":
    main()
