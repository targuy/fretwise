"""Hand-position segmentation (B pre-pass for Viterbi).

Splits a sequence of NoteEvents into ``Position`` records — contiguous spans of
notes that can be played within one 4-fret hand window. The anchor of a
position is the fret where the index finger would rest; the hand covers frets
``[anchor, anchor + 3]``.

This module is the structural cure for Viterbi-1's myopia: instead of letting
note-by-note optimisation decide hand position implicitly (and producing the
F4 "sur-anticipation" pathology), a position becomes a first-class concept the
downstream scoring layer can respect.

The module exposes only pure functions: it does not depend on the rest of the
pipeline and produces no side effects. Integration (rewiring
``cost_position_shift`` to be segment-aware) is intentionally kept separate so
the segmentation behaviour can be validated in isolation first.

Algorithm (v0 greedy maximal-span):
  - Walk the notes left to right.
  - Track ``(min_fret, max_fret)`` in the current segment.
  - When a new fret would push ``max - min > 3``, close the current segment
    (anchor = min_fret) and start a new one.
  - Open strings (fret 0) are part of the segment they fall in but never
    constrain or anchor it.
  - Notes without ``fret_hint`` (free-exploration mode, e.g. MIDI without tab)
    are also ignored for anchoring; they ride along with the surrounding
    segment.
  - If no note in the sequence has a usable fret_hint, the segmentation is
    empty — downstream scoring should fall back to its pre-B behaviour.

Known limitations of v0 (documented for follow-up):
  - Greedy. ``[5, 6, 7, 8, 9]`` produces two segments ``[5-8]`` and ``[9]``
    instead of one position with a one-fret stretch, which a human might
    prefer. A v1 could enumerate candidate anchors per maximal-span window
    and score them by intra-position cost; this is the classical
    CAGED-positioning problem.
"""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.models import NoteEvent

# Maximum span of frets in a single hand position: 4 frets = index..pinky.
_POSITION_SPAN = 3


@dataclass(frozen=True)
class Position:
    """A contiguous span of notes playable within one hand position.

    Attributes:
        start_idx: Index of the first note in the span (inclusive).
        end_idx: Index of the last note in the span (inclusive).
        anchor: Fret where the index finger rests. The hand covers
            ``[anchor, anchor + 3]``. ``anchor`` is the lowest fretted note
            in the segment.
    """

    start_idx: int
    end_idx: int
    anchor: int


def segment_into_positions(events: list[NoteEvent]) -> list[Position]:
    """Greedy maximal-span segmentation of a note sequence.

    Args:
        events: List of ``NoteEvent`` in temporal order.

    Returns:
        List of ``Position`` records covering ``events``. Empty when ``events``
        is empty or when no event has a usable ``fret_hint``.
    """
    if not events:
        return []

    positions: list[Position] = []
    seg_start = 0
    seg_min: int | None = None
    seg_max: int | None = None
    last_anchoring_idx: int | None = None

    for i, e in enumerate(events):
        fret = e.fret_hint
        if fret is None or fret == 0:
            continue

        if seg_min is None:
            seg_min = fret
            seg_max = fret
            seg_start = (
                i if not positions and last_anchoring_idx is None else seg_start
            )
            last_anchoring_idx = i
            continue

        new_min = min(seg_min, fret)
        new_max = max(seg_max if seg_max is not None else fret, fret)

        if new_max - new_min <= _POSITION_SPAN:
            seg_min = new_min
            seg_max = new_max
            last_anchoring_idx = i
        else:
            # Close the current segment at the last anchoring (fretted) note —
            # any open / unhinted notes that followed roll into the next segment.
            end_idx = last_anchoring_idx if last_anchoring_idx is not None else i - 1
            positions.append(Position(start_idx=seg_start, end_idx=end_idx, anchor=seg_min))
            seg_start = end_idx + 1
            seg_min = fret
            seg_max = fret
            last_anchoring_idx = i

    if seg_min is not None:
        end_idx = last_anchoring_idx if last_anchoring_idx is not None else len(events) - 1
        positions.append(Position(start_idx=seg_start, end_idx=end_idx, anchor=seg_min))

    if positions:
        # Extend the final segment to cover any trailing open/unhinted notes.
        last = positions[-1]
        if last.end_idx < len(events) - 1:
            positions[-1] = Position(
                start_idx=last.start_idx,
                end_idx=len(events) - 1,
                anchor=last.anchor,
            )
        # Extend the first segment to cover any leading open/unhinted notes.
        first = positions[0]
        if first.start_idx > 0:
            positions[0] = Position(
                start_idx=0,
                end_idx=first.end_idx,
                anchor=first.anchor,
            )

    return positions
