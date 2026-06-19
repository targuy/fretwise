"""Tests for B integration — segment-aware position shift cost.

Verifies the segment-aware variant of cost_position_shift produces the
expected behaviour at the unit, scoring-layer and pipeline-layer levels.
"""
from __future__ import annotations

from fretwise.generator import StateGenerator
from fretwise.models import Articulation, Dynamic, Finger, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import _anchors_from_segments, run_pipeline
from fretwise.scoring import (
    CostFunction,
    CostWeights,
    compute_mechanical_cost,
    cost_position_shift_segment_aware,
)
from fretwise.segmentation import Position


def _note(idx: int, fret_hint: int | None = None) -> NoteEvent:
    return NoteEvent(
        pitch=64 + (fret_hint or 0),
        onset=float(idx),
        duration=0.5,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=1,
        fret_hint=fret_hint,
    )


def _state(fret: int, finger: Finger) -> FingeringState:
    offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    if finger == Finger.OPEN:
        return FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
    return FingeringState(
        string_num=1,
        fret=fret,
        finger=finger,
        hand_position=max(1, fret - offsets[finger]),
    )


# ---------------------------------------------------------------------------
# cost_position_shift_segment_aware
# ---------------------------------------------------------------------------


def test_intra_segment_is_zero() -> None:
    """Same anchor on both sides → free transition, regardless of state hp."""
    s1 = _state(5, Finger.INDEX)   # hp=5
    s2 = _state(8, Finger.PINKY)   # hp=5 too (5 = 8-3)
    note = _note(1, 8)
    cost = cost_position_shift_segment_aware(s1, s2, note, anchor_prev=5, anchor_curr=5)
    assert cost == 0.0


def test_intra_segment_is_zero_even_when_hp_differs() -> None:
    """Even with hp delta on the state, same segment anchor → 0 cost."""
    s1 = _state(5, Finger.INDEX)   # hp=5
    s2 = _state(7, Finger.MIDDLE)  # hp=6 (offset 1)
    note = _note(1, 7)
    cost = cost_position_shift_segment_aware(s1, s2, note, anchor_prev=5, anchor_curr=5)
    assert cost == 0.0


def test_cross_segment_pays_anchor_delta() -> None:
    """Different anchors → cost = |delta| × tempo_factor."""
    s1 = _state(5, Finger.INDEX)
    s2 = _state(10, Finger.INDEX)
    note = _note(1, 10)
    # duration=0.5 beats, tempo=120 → 0.25 s, tempo_factor=4.0
    # anchor delta = 5, cost = 5 * 4.0 = 20.0
    cost = cost_position_shift_segment_aware(s1, s2, note, anchor_prev=5, anchor_curr=10)
    assert cost == 20.0


def test_open_transition_gets_discount() -> None:
    """Open string transition crosses segments at 0.35× factor."""
    s1 = _state(5, Finger.INDEX)
    s2 = _state(0, Finger.OPEN)
    note = _note(1, 0)
    cost = cost_position_shift_segment_aware(s1, s2, note, anchor_prev=5, anchor_curr=10)
    # delta = 5, tempo_factor = 4.0, open → 0.35 × 5 × 4.0 = 7.0
    assert cost == 7.0


# ---------------------------------------------------------------------------
# compute_mechanical_cost — wiring
# ---------------------------------------------------------------------------


def test_compute_mechanical_uses_segment_aware_when_anchors_provided() -> None:
    """When both anchors are passed, the segment-aware shift is used."""
    s1 = _state(5, Finger.INDEX)
    s2 = _state(7, Finger.MIDDLE)  # hp=6 → would cost something with per-state shift
    note = _note(1, 7)

    cost_with_seg = compute_mechanical_cost(
        s1, s2, note,
        segment_anchor_prev=5, segment_anchor_curr=5,
    )
    cost_without_seg = compute_mechanical_cost(s1, s2, note)
    # Segment-aware should have zero shift component; without should pay the
    # per-state shift (after A' tolerance of 1).
    assert cost_with_seg <= cost_without_seg


def test_compute_mechanical_falls_back_when_only_one_anchor() -> None:
    """A single None anchor disables segment-aware; uses per-state shift."""
    s1 = _state(5, Finger.INDEX)
    s2 = _state(7, Finger.MIDDLE)
    note = _note(1, 7)

    cost_fallback = compute_mechanical_cost(s1, s2, note, segment_anchor_curr=5)
    cost_no_segment = compute_mechanical_cost(s1, s2, note)
    assert cost_fallback == cost_no_segment


# ---------------------------------------------------------------------------
# CostFunction.transition_cost — index plumbing
# ---------------------------------------------------------------------------


def test_cost_function_without_anchors_ignores_index() -> None:
    """No set_segment_anchors → behaviour matches previous (A' tolerance)."""
    cf = CostFunction(weights=CostWeights.performance())
    s1 = _state(5, Finger.INDEX)
    s2 = _state(7, Finger.RING)
    note = _note(1, 7)
    cost_no_idx = cf.transition_cost(s1, s2, note)
    cost_with_idx = cf.transition_cost(s1, s2, note, index=5)
    assert cost_no_idx == cost_with_idx


def test_cost_function_with_anchors_uses_segment_aware() -> None:
    """set_segment_anchors activates segment-aware shift at the given index."""
    cf = CostFunction(weights=CostWeights.performance())
    cf.set_segment_anchors([5, 5, 5, 5])
    s1 = _state(5, Finger.INDEX)
    s2 = _state(7, Finger.RING)
    note = _note(2, 7)
    cost_segment = cf.transition_cost(s1, s2, note, index=2)
    # Same segment (anchor 5 → anchor 5): the position-shift contribution is 0.
    # Compare to the no-anchor case.
    cf.clear_segment_anchors()
    cost_fallback = cf.transition_cost(s1, s2, note, index=2)
    assert cost_segment <= cost_fallback


def test_cost_function_index_zero_falls_back_to_no_segment() -> None:
    """At index 0 (first note), there's no previous → no segment-aware lookup."""
    cf = CostFunction(weights=CostWeights.performance())
    cf.set_segment_anchors([5, 5])
    s1 = _state(5, Finger.INDEX)
    s2 = _state(7, Finger.RING)
    note = _note(0, 7)
    # index=0 → no previous anchor available → uses fallback
    cost_idx_zero = cf.transition_cost(s1, s2, note, index=0)
    cf.clear_segment_anchors()
    cost_baseline = cf.transition_cost(s1, s2, note, index=0)
    assert cost_idx_zero == cost_baseline


# ---------------------------------------------------------------------------
# Pipeline integration
# ---------------------------------------------------------------------------


def test_anchors_from_segments_covers_segment_range() -> None:
    positions = [
        Position(start_idx=0, end_idx=2, anchor=5),
        Position(start_idx=3, end_idx=5, anchor=9),
    ]
    anchors = _anchors_from_segments(positions, n_notes=6)
    assert anchors == [5, 5, 5, 9, 9, 9]


def test_anchors_from_segments_leaves_gaps_as_none() -> None:
    """Notes not in any position get None — fallback to A'."""
    positions = [Position(start_idx=1, end_idx=2, anchor=5)]
    anchors = _anchors_from_segments(positions, n_notes=5)
    assert anchors == [None, 5, 5, None, None]


def test_pipeline_activates_segment_anchors_for_voice_with_hints() -> None:
    """End-to-end: pipeline computes segments and activates them per voice."""
    notes = [_note(i, fret_hint=5 + i) for i in range(4)]  # [5,6,7,8] one position
    cost_fn = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    gen = StateGenerator()
    results, _ = run_pipeline(notes, gen, optimizer, pattern_matcher=matcher)
    assert len(results) == 4
    # Pipeline clears anchors after solve to keep cost_fn stateless across runs
    assert cost_fn._segment_anchors is None
