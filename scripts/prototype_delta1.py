"""Prototype δ.1 — alternative finger assignment.

Compares the current `_natural_finger_assignment` (greedy, prefers natural
offsets) against a candidate (enumerate all combos, pick min(max_rank,
total_stretch)) on synthetic chord shapes derived from the patterns
GuitarDataSet identified as problematic.

Not integrated into the pipeline yet. Pure stdout output for analysis.
"""
from __future__ import annotations

import sys
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.models import Finger
from fretwise.scoring import _FRETTED_FINGERS, _natural_finger_assignment


# R-C4 max fret gap per rank diff (mirror of scoring/__init__.py).
_MAX_FINGER_PAIR_SPAN = {
    (0, 1): 2,  # INDEX – MIDDLE
    (0, 2): 3,  # INDEX – RING
    (0, 3): 4,  # INDEX – PINKY
    (1, 2): 2,  # MIDDLE – RING
    (1, 3): 3,  # MIDDLE – PINKY
    (2, 3): 2,  # RING – PINKY
}


def _alternative_finger_assignment(frets: list[int]) -> list[Finger] | None:
    """Enumerate-and-score finger assignments.

    Restricted to n ≥ 3: 2-note chords already have 0% error in the
    GuitarDataSet baseline, so keeping the current (natural) assignment
    avoids regressions on power chords (INDEX+RING) and similar 2-note
    idioms. The compression heuristic targets the 3-note sus4/maj7
    skip-gap patterns specifically.

    Constraints (for n ≥ 3):
      - frets must be sorted ascending
      - assignment combo is monotone (R-C3 implicit)
      - each finger's stretch from its natural offset (hp = frets[0]) ≤ 1
      - all finger-pair span limits respected (R-C4)

    Scoring (lower = better, lexicographic):
      - max rank used (prefer fewer high-rank fingers)
      - total stretch magnitude (tiebreak)
    """
    n = len(frets)
    if n == 0 or n > 4:
        return None
    if n < 3:
        return _natural_finger_assignment(frets)

    hp = frets[0]
    natural_offsets = [f - hp for f in frets]

    best: tuple[int, ...] | None = None
    best_score: tuple[int, int] | None = None

    for combo in combinations(range(4), n):
        # Stretch constraint
        stretches = [abs(o - nat) for o, nat in zip(combo, natural_offsets)]
        if max(stretches) > 1:
            continue
        # R-C4 pair span limits
        valid = True
        for i in range(n):
            for j in range(i + 1, n):
                rank_diff = combo[j] - combo[i]
                max_gap = _MAX_FINGER_PAIR_SPAN.get((combo[i], combo[j]), rank_diff + 1)
                if frets[j] - frets[i] > max_gap:
                    valid = False
                    break
            if not valid:
                break
        if not valid:
            continue

        max_rank = combo[-1]  # sorted, max is last
        total_stretch = sum(stretches)
        score = (max_rank, total_stretch)

        if best_score is None or score < best_score:
            best_score = score
            best = combo

    if best is None:
        return None
    return [_FRETTED_FINGERS[o] for o in best]


def _format_fingers(fingers: list[Finger] | None) -> str:
    if fingers is None:
        return "(invalid)"
    return ", ".join(f.name[:3] for f in fingers)


SYNTHETIC_CASES = [
    # (label, frets, expected_human_intuition)
    ("single note F=5",            [5],          "INX (forced — hp=5)"),
    ("2-note compact [F,F+1]",     [5, 6],       "INX, MID (natural)"),
    ("2-note skip-gap [F,F+2]",    [5, 7],       "INX, MID (compress) preferred over INX, RING"),
    ("2-note skip-gap [F,F+3]",    [5, 8],       "INX, RING (compress) preferred over INX, PINKY"),
    ("3-note sus4 [F,F+2,F+3]",    [5, 7, 8],    "INX, MID, RING (compress)  — the dominant MR error pattern"),
    ("3-note maj7 [F,F+1,F+3]",    [5, 6, 8],    "INX, MID, RING — compress PINKY"),
    ("3-note natural [F,F+1,F+2]", [5, 6, 7],    "INX, MID, RING (no skip)"),
    ("3-note  [F,F+1,F+4]",        [5, 6, 9],    "INX, MID, PINKY — F+4 too far for RING"),
    ("4-note natural",             [5, 6, 7, 8], "INX, MID, RING, PINKY"),
    ("4-note skip-gap [F,F+1,F+2,F+4]", [5, 6, 7, 9], "INX, MID, RING, PINKY (stretch on PINKY)"),
    ("barre triad [F,F,F]",        [5, 5, 5],    "INX (barre) — but algo wants distinct fingers"),
    ("low octave shape [F,F,F+2]", [5, 5, 7],    "INX, INX(barre)/MID, RING"),
    # Realistic chord voicings (Asus4-like)
    ("Asus4 frets 2-2-3 from hp=2", [2, 2, 3],   "INX, INX, MID  (barre) or INX, MID, RING"),
    ("Amaj7 frets 1-2-2 from hp=1", [1, 2, 2],   "INX, MID, RING  (compress)"),
    ("Bdim frets 2-3-4 from hp=2",  [2, 3, 4],   "INX, MID, RING (natural)"),
]


def main() -> None:
    print(f"\n{'CASE':<40} {'FRETS':<20} {'CURRENT':<25} {'δ.1':<25} {'DIFF':<5}")
    print("-" * 130)
    differs = 0
    for label, frets, intuition in SYNTHETIC_CASES:
        sorted_frets = sorted(frets)
        cur = _natural_finger_assignment(sorted_frets)
        alt = _alternative_finger_assignment(sorted_frets)
        diff = "DIFF" if cur != alt else ""
        if cur != alt:
            differs += 1
        print(f"{label:<40} {str(sorted_frets):<20} "
              f"{_format_fingers(cur):<25} {_format_fingers(alt):<25} {diff:<5}")
        if cur != alt:
            print(f"  → human intuition: {intuition}")
    print(f"\nδ.1 differs from current on {differs}/{len(SYNTHETIC_CASES)} cases")


if __name__ == "__main__":
    main()
