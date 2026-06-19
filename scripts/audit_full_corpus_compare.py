"""Audit comparatif tol=0 vs tol=1 sur le corpus partitions/ (~1500 fichiers).

Patch dynamiquement la constante de tolérance, run la pipeline sur chaque
fichier, agrège les distributions. Catch les exceptions pour ne pas s'arrêter
sur les fichiers qui déclenchent un bug pré-existant (résolveurs chord).

Usage: python scripts/audit_full_corpus_compare.py [path]
"""
from __future__ import annotations

import sys
import time
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise import scoring
from fretwise.scoring import CostFunction, CostWeights


def _run_with_tolerance(events, tolerance: int) -> Counter:
    """Run the pipeline with a given hp-shift tolerance, return finger counts."""
    original_fn = scoring.cost_position_shift

    def patched_cost_position_shift(s1, s2, note):
        from fretwise.models import Finger
        open_transition = (
            s1.finger == Finger.OPEN
            or s2.finger == Finger.OPEN
            or s1.fret == 0
            or s2.fret == 0
        )
        raw_shift = abs(s2.hand_position - s1.hand_position)
        shift = max(0, raw_shift - tolerance)
        if shift == 0:
            return 0.0
        seconds = note.duration * 60.0 / max(note.tempo, 1.0)
        tempo_factor = 1.0 / max(seconds, 0.1)
        if open_transition:
            return 0.35 * shift * tempo_factor
        return shift * tempo_factor

    scoring.cost_position_shift = patched_cost_position_shift

    try:
        gen = StateGenerator()
        cost = CostFunction(weights=CostWeights.performance())
        opt = ViterbiOptimizer(cost)
        matcher = PatternMatcher()
        results, _ = run_pipeline(events, gen, opt, pattern_matcher=matcher)
    finally:
        scoring.cost_position_shift = original_fn

    counter: Counter = Counter()
    for r in results:
        counter[r.state.finger.name] += 1
    return counter


def main() -> None:
    corpus_path = Path(sys.argv[1] if len(sys.argv) > 1 else "partitions")
    files = sorted(corpus_path.glob("*.gp*"))
    print(f"Corpus: {len(files)} fichiers de {corpus_path}")

    totals = {0: Counter(), 1: Counter()}
    ok_count = 0
    fail_count = 0
    skip_count = 0
    t0 = time.time()

    for i, path in enumerate(files):
        if i > 0 and i % 100 == 0:
            elapsed = time.time() - t0
            eta = elapsed / i * (len(files) - i)
            print(
                f"[{i}/{len(files)}]  ok={ok_count}  fail={fail_count}  skip={skip_count}"
                f"  elapsed={elapsed:.0f}s  eta={eta:.0f}s",
                flush=True,
            )

        try:
            adapter = get_adapter(path)
            events = adapter.parse(path)
        except Exception:
            skip_count += 1
            continue

        if not events:
            skip_count += 1
            continue

        # Run pipeline twice with different tolerances. Catch all errors so
        # one buggy file doesn't kill the audit.
        try:
            counter_0 = _run_with_tolerance(events, 0)
        except Exception:
            fail_count += 1
            continue

        try:
            counter_1 = _run_with_tolerance(events, 1)
        except Exception:
            fail_count += 1
            continue

        for k, v in counter_0.items():
            totals[0][k] += v
        for k, v in counter_1.items():
            totals[1][k] += v
        ok_count += 1

    elapsed = time.time() - t0
    print(f"\n{'=' * 60}")
    print(f"Processed: ok={ok_count}  fail={fail_count}  skip={skip_count}  "
          f"({elapsed:.0f}s total)")

    fingers = ["OPEN", "INDEX", "MIDDLE", "RING", "PINKY"]
    for tol in (0, 1):
        total = sum(totals[tol].values())
        if total == 0:
            continue
        print(f"\nTolerance = {tol}   total notes = {total}")
        for finger in fingers:
            count = totals[tol].get(finger, 0)
            pct = 100 * count / total
            bar = "#" * int(pct / 2)
            print(f"  {finger:<8} {count:7d}  {pct:5.1f}%  {bar}")
        rp = totals[tol].get("RING", 0) + totals[tol].get("PINKY", 0)
        im = totals[tol].get("INDEX", 0) + totals[tol].get("MIDDLE", 0)
        print(f"  -> INDEX+MIDDLE: {100 * im / total:.2f}%   "
              f"RING+PINKY: {100 * rp / total:.2f}%   "
              f"Ratio RP/IM = {rp / max(im, 1):.4f}")

    print(f"\n{'=' * 60}")
    print("DELTA (tol=1 vs tol=0):")
    total_0 = sum(totals[0].values())
    total_1 = sum(totals[1].values())
    for finger in fingers:
        pct_0 = 100 * totals[0].get(finger, 0) / max(total_0, 1)
        pct_1 = 100 * totals[1].get(finger, 0) / max(total_1, 1)
        delta = pct_1 - pct_0
        sign = "+" if delta >= 0 else ""
        print(f"  {finger:<8}  {pct_0:5.2f}% -> {pct_1:5.2f}%  ({sign}{delta:+.2f} pp)")

    rp_0 = totals[0].get("RING", 0) + totals[0].get("PINKY", 0)
    im_0 = totals[0].get("INDEX", 0) + totals[0].get("MIDDLE", 0)
    rp_1 = totals[1].get("RING", 0) + totals[1].get("PINKY", 0)
    im_1 = totals[1].get("INDEX", 0) + totals[1].get("MIDDLE", 0)
    ratio_0 = rp_0 / max(im_0, 1)
    ratio_1 = rp_1 / max(im_1, 1)
    print(f"\n  Ratio RP/IM: {ratio_0:.4f} -> {ratio_1:.4f}  "
          f"(delta {ratio_1 - ratio_0:+.4f}, {100 * (ratio_1 - ratio_0) / ratio_0:+.2f}%)")


if __name__ == "__main__":
    main()
