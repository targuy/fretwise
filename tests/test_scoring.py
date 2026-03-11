"""Tests for fretwise.scoring — C_méca cost functions."""

from __future__ import annotations

import pytest

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.scoring import (
    CostFunction,
    CostWeights,
    compute_mechanical_cost,
    cost_finger_difficulty,
    cost_position_shift,
    cost_sequential_crossing,
    cost_stretch,
    cost_string_change,
    resolve_chord_finger_ordering,
)


def _note(tempo: float = 120.0, duration: float = 1.0) -> NoteEvent:
    return NoteEvent(pitch=60, onset=0.0, duration=duration, tempo=tempo)


def _state(
    string_num: int = 3,
    fret: int = 5,
    finger: Finger = Finger.INDEX,
    hand_position: int = 5,
) -> FingeringState:
    return FingeringState(
        string_num=string_num, fret=fret, finger=finger, hand_position=hand_position
    )


# ---------------------------------------------------------------------------
# cost_position_shift
# ---------------------------------------------------------------------------


class TestCostPositionShift:
    def test_no_shift_returns_zero(self) -> None:
        s1 = _state(hand_position=5)
        s2 = _state(hand_position=5)
        assert cost_position_shift(s1, s2, _note()) == pytest.approx(0.0)

    def test_shift_is_positive(self) -> None:
        s1 = _state(hand_position=1)
        s2 = _state(hand_position=5)
        assert cost_position_shift(s1, s2, _note()) > 0.0

    def test_larger_shift_costs_more(self) -> None:
        s1 = _state(hand_position=1)
        s2_far = _state(hand_position=10)
        s2_near = _state(hand_position=3)
        note = _note()
        assert cost_position_shift(s1, s2_far, note) > cost_position_shift(s1, s2_near, note)

    def test_faster_tempo_costs_more(self) -> None:
        s1 = _state(hand_position=1)
        s2 = _state(hand_position=5)
        slow_note = _note(tempo=60.0)
        fast_note = _note(tempo=240.0)
        assert cost_position_shift(s1, s2, fast_note) > cost_position_shift(s1, s2, slow_note)

    def test_shift_is_symmetric(self) -> None:
        s1 = _state(hand_position=3)
        s2 = _state(hand_position=7)
        note = _note()
        assert cost_position_shift(s1, s2, note) == pytest.approx(
            cost_position_shift(s2, s1, note)
        )


# ---------------------------------------------------------------------------
# cost_stretch
# ---------------------------------------------------------------------------


class TestCostStretch:
    def test_open_string_no_stretch(self) -> None:
        s1 = _state()
        s2 = _state(fret=0, finger=Finger.OPEN, hand_position=1)
        assert cost_stretch(s1, s2) == pytest.approx(0.0)

    def test_index_on_fret_equals_hand_position_no_stretch(self) -> None:
        # Index plays fret 5, hand_position = 5 → stretch = 0
        s1 = _state()
        s2 = _state(fret=5, finger=Finger.INDEX, hand_position=5)
        assert cost_stretch(s1, s2) == pytest.approx(0.0)

    def test_pinky_extends_stretch(self) -> None:
        # Pinky plays fret 8, hand_position = 5 → stretch = 3
        s1 = _state()
        s2 = _state(fret=8, finger=Finger.PINKY, hand_position=5)
        assert cost_stretch(s1, s2) > 0.0

    def test_higher_position_reduces_stretch_cost(self) -> None:
        # Same finger offset but higher on the neck → lower cost
        s_low = _state(fret=4, finger=Finger.PINKY, hand_position=1)
        s_high = _state(fret=16, finger=Finger.PINKY, hand_position=13)
        assert cost_stretch(None, s_low) > cost_stretch(None, s_high)  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# cost_string_change
# ---------------------------------------------------------------------------


class TestCostStringChange:
    def test_same_string_zero(self) -> None:
        s1 = _state(string_num=3)
        s2 = _state(string_num=3)
        assert cost_string_change(s1, s2) == pytest.approx(0.0)

    def test_adjacent_string(self) -> None:
        s1 = _state(string_num=3)
        s2 = _state(string_num=4)
        assert cost_string_change(s1, s2) == pytest.approx(1.0)

    def test_large_jump(self) -> None:
        s1 = _state(string_num=1)
        s2 = _state(string_num=6)
        assert cost_string_change(s1, s2) == pytest.approx(5.0)

    def test_symmetric(self) -> None:
        s1 = _state(string_num=2)
        s2 = _state(string_num=5)
        assert cost_string_change(s1, s2) == cost_string_change(s2, s1)


# ---------------------------------------------------------------------------
# cost_finger_difficulty
# ---------------------------------------------------------------------------


class TestCostFingerDifficulty:
    def test_open_is_easiest(self) -> None:
        s = _state(fret=0, finger=Finger.OPEN)
        assert cost_finger_difficulty(s) == pytest.approx(0.0)

    def test_index_is_easiest_fretted(self) -> None:
        assert cost_finger_difficulty(_state(finger=Finger.INDEX)) < cost_finger_difficulty(
            _state(finger=Finger.MIDDLE)
        )

    def test_pinky_hardest(self) -> None:
        s_index = _state(finger=Finger.INDEX)
        s_pinky = _state(finger=Finger.PINKY)
        assert cost_finger_difficulty(s_pinky) > cost_finger_difficulty(s_index)

    def test_order(self) -> None:
        costs = [
            cost_finger_difficulty(_state(finger=f))
            for f in [Finger.OPEN, Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY]
        ]
        assert costs == sorted(costs)


# ---------------------------------------------------------------------------
# compute_mechanical_cost
# ---------------------------------------------------------------------------


class TestComputeMechanicalCost:
    def test_same_state_low_cost(self) -> None:
        s = _state()
        cost = compute_mechanical_cost(s, s, _note())
        # No shift, no stretch (index at hand_position), no string change.
        # Only finger difficulty remains.
        assert cost < 3.0  # sanity bound

    def test_large_shift_high_cost(self) -> None:
        s1 = _state(string_num=1, fret=1, finger=Finger.INDEX, hand_position=1)
        s2 = _state(string_num=6, fret=20, finger=Finger.PINKY, hand_position=17)
        cost = compute_mechanical_cost(s1, s2, _note(tempo=200.0, duration=0.25))
        assert cost > 5.0  # should be clearly expensive


# ---------------------------------------------------------------------------
# CostFunction
# ---------------------------------------------------------------------------


class TestCostFunction:
    def test_transition_cost_non_negative(self) -> None:
        cf = CostFunction()
        s1 = _state()
        s2 = _state(string_num=2, hand_position=3)
        cost = cf.transition_cost(s1, s2, _note())
        assert cost >= 0.0

    def test_emission_cost_non_negative(self) -> None:
        cf = CostFunction()
        assert cf.emission_cost(_state()) >= 0.0

    def test_emission_cost_open_is_zero(self) -> None:
        cf = CostFunction()
        assert cf.emission_cost(_state(fret=0, finger=Finger.OPEN)) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# CostWeights presets
# ---------------------------------------------------------------------------


class TestCostWeights:
    def test_reference_weights(self) -> None:
        w = CostWeights.reference()
        assert w.alpha == pytest.approx(1.0)
        assert w.beta == pytest.approx(1.0)
        assert w.gamma == pytest.approx(0.0)
        assert w.delta == pytest.approx(0.0)

    def test_performance_weights(self) -> None:
        w = CostWeights.performance()
        assert w.gamma > w.beta  # player cost dominates

    def test_learning_weights(self) -> None:
        w = CostWeights.learning()
        assert w.delta > 0.0  # pedagogical cost activated


# ---------------------------------------------------------------------------
# cost_sequential_crossing
# ---------------------------------------------------------------------------


def _st(fret: int, finger: Finger, hand_pos: int | None = None) -> FingeringState:
    hp = hand_pos if hand_pos is not None else max(1, fret - _OFFSET[finger])
    return FingeringState(string_num=3, fret=fret, finger=finger, hand_position=hp)


_OFFSET = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}


class TestCostSequentialCrossing:
    def test_natural_ascending_no_penalty(self) -> None:
        # INDEX fret 5 → MIDDLE fret 6: natural ascending order — no penalty.
        s1 = _st(5, Finger.INDEX)
        s2 = _st(6, Finger.MIDDLE)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_natural_descending_no_penalty(self) -> None:
        # RING fret 7 → MIDDLE fret 6: natural descending order — no penalty.
        s1 = _st(7, Finger.RING, hand_pos=5)
        s2 = _st(6, Finger.MIDDLE, hand_pos=5)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_crossing_ascending_fret_lower_finger_penalised(self) -> None:
        # INDEX fret 7 → RING fret 9: ascending fret but RING > INDEX — OK, no cross.
        # RING fret 7 → MIDDLE fret 9: ascending fret, MIDDLE < RING → CROSSING.
        s1 = _st(7, Finger.RING, hand_pos=5)
        s2 = _st(9, Finger.MIDDLE, hand_pos=8)
        # hand_pos shift = 3 > _SHIFT_EXEMPT_THRESHOLD(1) → exempt
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_crossing_same_position_penalised(self) -> None:
        # RING fret 7 (hp=5) → MIDDLE fret 8 (hp=7): ascending fret, MIDDLE < RING rank
        # position shift = |7-5| = 2 > 1 → exempt. Let's force small shift.
        # INDEX fret 5 (hp=5) → RING fret 4 (hp=2): descending fret, RING > INDEX → CROSS
        s1 = _st(5, Finger.INDEX, hand_pos=5)
        s2 = _st(4, Finger.RING, hand_pos=5)  # shift = 0, fret goes down, rank goes up
        assert cost_sequential_crossing(s1, s2) > 0.0

    def test_open_string_no_penalty(self) -> None:
        s1 = FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        s2 = _st(5, Finger.INDEX)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_same_fret_no_penalty(self) -> None:
        # Unison / re-articulation: no direction to check.
        s1 = _st(5, Finger.INDEX)
        s2 = _st(5, Finger.MIDDLE)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_large_shift_exempt(self) -> None:
        # PINKY fret 12 → INDEX fret 5: massive position shift, any finger order OK.
        s1 = _st(12, Finger.PINKY, hand_pos=9)
        s2 = _st(5, Finger.INDEX, hand_pos=5)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_included_in_mechanical_cost(self) -> None:
        # Verify the penalty propagates through compute_mechanical_cost.
        note = _note()
        # Crossing in same position: should cost more than natural order.
        s1 = _st(5, Finger.INDEX, hand_pos=5)
        s_cross = _st(4, Finger.RING, hand_pos=5)   # fret down, rank up → cross
        s_natural = _st(4, Finger.INDEX, hand_pos=4)   # fret down, same rank → OK
        cost_cross = compute_mechanical_cost(s1, s_cross, note)
        cost_natural = compute_mechanical_cost(s1, s_natural, note)
        assert cost_cross > cost_natural


# ---------------------------------------------------------------------------
# resolve_chord_finger_ordering
# ---------------------------------------------------------------------------


def _fr(note_id: int, onset: float, string_num: int, fret: int, finger: Finger) -> FingeringResult:
    offset = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}.get(finger, 0)
    state = FingeringState(
        string_num=string_num, fret=fret, finger=finger,
        hand_position=max(1, fret - offset),
    )
    note = NoteEvent(pitch=60, onset=onset, duration=1.0, tempo=120.0)
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=1.0)


class TestResolveChordFingerOrdering:
    def test_valid_chord_unchanged(self) -> None:
        # INDEX fret 5, MIDDLE fret 6, RING fret 7 — already monotone.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 6, Finger.MIDDLE),
            _fr(2, 0.0, 5, 7, Finger.RING),
        ]
        out = resolve_chord_finger_ordering(results)
        assert [r.state.finger for r in out] == [Finger.INDEX, Finger.MIDDLE, Finger.RING]

    def test_crossing_irm_fixed(self) -> None:
        # Reported bug: INDEX fret 5, RING fret 7, MIDDLE fret 9.
        # RING (rank 2) at fret 7 < MIDDLE (rank 1) at fret 9 → CROSSING.
        # After fix: fret 5→INDEX, fret 7→MIDDLE, fret 9→RING.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
            _fr(2, 0.0, 5, 9, Finger.MIDDLE),
        ]
        out = resolve_chord_finger_ordering(results)
        by_fret = sorted(out, key=lambda r: r.state.fret)
        fingers = [r.state.finger for r in by_fret]
        assert fingers == [Finger.INDEX, Finger.MIDDLE, Finger.RING]

    def test_crossing_two_notes_fixed(self) -> None:
        # RING fret 5, INDEX fret 7 — RING (rank 2) at lower fret than INDEX (rank 0) is OK
        # but INDEX (rank 0) at higher fret than RING (rank 2) IS a crossing.
        results = [
            _fr(0, 0.0, 3, 5, Finger.RING),
            _fr(1, 0.0, 4, 7, Finger.INDEX),
        ]
        out = resolve_chord_finger_ordering(results)
        low_fret = min(out, key=lambda r: r.state.fret)
        high_fret = max(out, key=lambda r: r.state.fret)
        # After fix: lower fret must have lower-rank finger.
        assert _OFFSET.get(low_fret.state.finger, 0) <= _OFFSET.get(high_fret.state.finger, 0)

    def test_open_string_not_touched(self) -> None:
        # Open string + INDEX fret 5 + RING fret 7 — open string ignored.
        open_note = FingeringResult(
            note_id=0,
            note_event=NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0),
            state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
            cost=0.0,
        )
        results = [
            open_note,
            _fr(1, 0.0, 3, 5, Finger.INDEX),
            _fr(2, 0.0, 4, 7, Finger.RING),
        ]
        out = resolve_chord_finger_ordering(results)
        assert out[0].state.finger == Finger.OPEN  # untouched
        fretted = [r for r in out if r.state.fret > 0]
        by_fret = sorted(fretted, key=lambda r: r.state.fret)
        # INDEX at lower fret, RING at higher fret — valid.
        assert by_fret[0].state.finger == Finger.INDEX
        assert by_fret[1].state.finger == Finger.RING

    def test_equal_fret_barre_unchanged(self) -> None:
        # Two notes at fret 5 (partial barré) — ordering within equal frets is unconstrained.
        results = [
            _fr(0, 0.0, 3, 5, Finger.RING),
            _fr(1, 0.0, 4, 5, Finger.INDEX),
        ]
        out = resolve_chord_finger_ordering(results)
        frets = {r.state.fret for r in out}
        assert frets == {5}  # frets unchanged

    def test_single_note_chord_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.RING)]
        out = resolve_chord_finger_ordering(results)
        assert out[0].state.finger == Finger.RING
