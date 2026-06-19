"""Tests for hand-position segmentation (B pre-pass).

The segmentation module is tested in isolation — no pipeline, no Viterbi, no
scoring. Each test exercises the greedy maximal-span algorithm on a hand-
crafted list of NoteEvents and asserts the produced ``Position`` records.
"""
from __future__ import annotations

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.segmentation import Position, segment_into_positions


def _note(idx: int, fret_hint: int | None) -> NoteEvent:
    """Build a minimal NoteEvent with given fret_hint."""
    return NoteEvent(
        pitch=64,  # arbitrary
        onset=float(idx),
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=1,
        fret_hint=fret_hint,
    )


def _make(frets: list[int | None]) -> list[NoteEvent]:
    return [_note(i, f) for i, f in enumerate(frets)]


def test_empty_events_returns_empty() -> None:
    assert segment_into_positions([]) == []


def test_single_fretted_note_yields_one_position() -> None:
    positions = segment_into_positions(_make([5]))
    assert positions == [Position(start_idx=0, end_idx=0, anchor=5)]


def test_repeated_same_fret_one_position() -> None:
    positions = segment_into_positions(_make([5, 5, 5, 5]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=5)]


def test_ascending_run_within_four_frets_one_position() -> None:
    """[5, 6, 7, 8] is one natural hand position (index..pinky)."""
    positions = segment_into_positions(_make([5, 6, 7, 8]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=5)]


def test_zz_top_boogie_pattern_one_position() -> None:
    """[3, 5, 3, 5] (low/high boogie alternation) stays in position 3."""
    positions = segment_into_positions(_make([3, 5, 3, 5]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=3)]


def test_three_fret_span_fits() -> None:
    """[5, 8, 5, 8] has span 3 — fits in one position anchored at 5."""
    positions = segment_into_positions(_make([5, 8, 5, 8]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=5)]


def test_four_fret_jump_splits() -> None:
    """[5, 9] exceeds the 4-fret window: two positions.

    Known v0 limitation: a human might play this in one position with a
    one-fret stretch (PINKY on 9). The greedy algorithm doesn't model
    intentional stretches.
    """
    positions = segment_into_positions(_make([5, 9]))
    assert positions == [
        Position(start_idx=0, end_idx=0, anchor=5),
        Position(start_idx=1, end_idx=1, anchor=9),
    ]


def test_la_grange_measure_pattern_two_positions() -> None:
    """[5, 5, 3, 5, 5, 3, 8, 8, 6] → position [0..5] anchored 3, then [6..8] anchored 6.

    Models a typical ZZ Top La Grange measure where the riff stays low for
    a few beats then jumps to a higher voicing.
    """
    positions = segment_into_positions(_make([5, 5, 3, 5, 5, 3, 8, 8, 6]))
    assert positions == [
        Position(start_idx=0, end_idx=5, anchor=3),
        Position(start_idx=6, end_idx=8, anchor=6),
    ]


def test_open_strings_dont_anchor() -> None:
    """Open strings (fret=0) belong to the surrounding segment but don't change anchor."""
    positions = segment_into_positions(_make([0, 5, 5, 5]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=5)]


def test_open_string_between_anchoring_notes() -> None:
    """[5, 0, 5] — open string between two fretted notes stays in segment."""
    positions = segment_into_positions(_make([5, 0, 5]))
    assert positions == [Position(start_idx=0, end_idx=2, anchor=5)]


def test_open_string_at_segment_boundary() -> None:
    """[5, 0, 9] — open string sits at the boundary; assigned to the next segment."""
    positions = segment_into_positions(_make([5, 0, 9]))
    assert positions == [
        Position(start_idx=0, end_idx=0, anchor=5),
        Position(start_idx=1, end_idx=2, anchor=9),
    ]


def test_only_open_strings_no_positions() -> None:
    """All open strings → no positions, downstream falls back to old behaviour."""
    assert segment_into_positions(_make([0, 0, 0, 0])) == []


def test_unhinted_notes_dont_anchor() -> None:
    """Notes without fret_hint behave like open strings for segmentation."""
    positions = segment_into_positions(_make([None, 5, None, 8]))
    assert positions == [Position(start_idx=0, end_idx=3, anchor=5)]


def test_no_usable_hints_empty_result() -> None:
    """No fret_hints at all → empty segmentation."""
    assert segment_into_positions(_make([None, None, None])) == []


def test_long_run_breaks_into_natural_positions() -> None:
    """A 7-note ascending run [3,4,5,6,7,8,9] is split greedily.

    Greedy: notes 0..3 (frets 3..6) form one position anchored at 3.
    Note 4 (fret 7) extends span to 4 (3..7) which exceeds the limit, so a
    new segment starts. The first segment closes at the last note that fit.
    """
    positions = segment_into_positions(_make([3, 4, 5, 6, 7, 8, 9]))
    assert positions == [
        Position(start_idx=0, end_idx=3, anchor=3),
        Position(start_idx=4, end_idx=6, anchor=7),
    ]
