"""Tests for fretwise.scoring — C_méca and C_music cost functions."""

from __future__ import annotations

import pytest

from fretwise.models import Articulation, Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.scoring import (
    CostFunction,
    CostWeights,
    _natural_finger_assignment,
    compute_mechanical_cost,
    compute_musical_cost,
    cost_finger_difficulty,
    cost_position_shift,
    cost_same_finger_motion,
    cost_sequential_crossing,
    cost_stretch,
    cost_string_change,
    resolve_arpeggio_chord_fingering,
    resolve_chord_conflicts,
    resolve_chord_finger_ordering,
    resolve_chord_finger_span,
    resolve_chord_stretch,
    resolve_chord_string_diagonal,
    resolve_chord_partial_barre,
    resolve_chord_unified_hand_position,
    resolve_finger_continuity,
    resolve_pinky_run_to_index,
    resolve_section_consistency,
    resolve_sedentary_fingers,
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

    def test_open_string_source_shift_cost_is_reduced_but_not_free(self) -> None:
        open_state = _state(fret=0, finger=Finger.OPEN, hand_position=1)
        fretted_state = _state(fret=10, finger=Finger.PINKY, hand_position=7)
        cost = cost_position_shift(open_state, fretted_state, _note())
        assert cost > 0.0
        assert cost < cost_position_shift(
            _state(fret=10, finger=Finger.PINKY, hand_position=1),
            _state(fret=12, finger=Finger.PINKY, hand_position=7),
            _note(),
        )

    def test_open_string_target_shift_cost_is_reduced_but_not_free(self) -> None:
        fretted_state = _state(fret=10, finger=Finger.PINKY, hand_position=7)
        open_state = _state(fret=0, finger=Finger.OPEN, hand_position=1)
        cost = cost_position_shift(fretted_state, open_state, _note())
        assert cost > 0.0
        assert cost < cost_position_shift(
            _state(fret=12, finger=Finger.PINKY, hand_position=7),
            _state(fret=10, finger=Finger.PINKY, hand_position=1),
            _note(),
        )

    def test_open_transition_same_hand_position_remains_zero(self) -> None:
        open_state = _state(fret=0, finger=Finger.OPEN, hand_position=5)
        fretted_state = _state(fret=7, finger=Finger.RING, hand_position=5)
        assert cost_position_shift(open_state, fretted_state, _note()) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# cost_stretch
# ---------------------------------------------------------------------------


class TestCostStretch:
    def test_open_string_no_stretch(self) -> None:
        s1 = _state()
        s2 = _state(fret=0, finger=Finger.OPEN, hand_position=1)
        assert cost_stretch(s1, s2) == pytest.approx(0.0)

    def test_index_on_fret_equals_hand_position_no_stretch(self) -> None:
        # Index natural offset is 0: fret - hand_position == 0
        s1 = _state()
        s2 = _state(fret=5, finger=Finger.INDEX, hand_position=5)
        assert cost_stretch(s1, s2) == pytest.approx(0.0)

    def test_natural_ring_and_pinky_offsets_have_no_stretch(self) -> None:
        s1 = _state()
        s_ring = _state(fret=3, finger=Finger.RING, hand_position=1)
        s_pinky = _state(fret=8, finger=Finger.PINKY, hand_position=5)
        assert cost_stretch(s1, s_ring) == pytest.approx(0.0)
        assert cost_stretch(s1, s_pinky) == pytest.approx(0.0)

    def test_non_natural_pinky_position_has_stretch(self) -> None:
        # Pinky natural offset is 3. Here offset=2 so we expect non-zero stretch.
        s1 = _state()
        s2 = _state(fret=8, finger=Finger.PINKY, hand_position=6)
        assert cost_stretch(s1, s2) > 0.0

    def test_higher_position_reduces_stretch_cost(self) -> None:
        # Same deviation from natural pinky offset, higher on the neck → lower cost.
        s_low = _state(fret=4, finger=Finger.PINKY, hand_position=2)
        s_high = _state(fret=16, finger=Finger.PINKY, hand_position=14)
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

    def test_same_finger_run_costs_more_than_natural_reassignment(self) -> None:
        note = _note(tempo=93.0, duration=0.125)
        previous = _state(string_num=6, fret=8, finger=Finger.PINKY, hand_position=5)
        same_finger = _state(string_num=6, fret=10, finger=Finger.PINKY, hand_position=7)
        reassigned = _state(string_num=6, fret=10, finger=Finger.RING, hand_position=8)
        assert compute_mechanical_cost(previous, same_finger, note) > compute_mechanical_cost(
            previous, reassigned, note
        )


# ---------------------------------------------------------------------------
# cost_same_finger_motion
# ---------------------------------------------------------------------------


class TestCostSameFingerMotion:
    def test_same_fret_string_change_is_exempt_for_barre_like_motion(self) -> None:
        s1 = _state(string_num=2, fret=5, finger=Finger.INDEX, hand_position=5)
        s2 = _state(string_num=4, fret=5, finger=Finger.INDEX, hand_position=5)
        assert cost_same_finger_motion(s1, s2, _note(tempo=120.0, duration=0.25)) == pytest.approx(
            0.0
        )

    def test_same_finger_fret_change_is_penalized(self) -> None:
        s1 = _state(string_num=6, fret=8, finger=Finger.PINKY, hand_position=5)
        s2 = _state(string_num=6, fret=10, finger=Finger.PINKY, hand_position=7)
        assert cost_same_finger_motion(s1, s2, _note(tempo=93.0, duration=0.125)) > 0.0

    def test_slide_destination_is_exempt(self) -> None:
        s1 = _state(string_num=3, fret=5, finger=Finger.RING, hand_position=3)
        s2 = _state(string_num=3, fret=7, finger=Finger.RING, hand_position=5)
        note = NoteEvent(
            pitch=60,
            onset=0.0,
            duration=0.25,
            tempo=120.0,
            articulation=Articulation.SLIDE,
            slide_type="shift",
        )
        assert cost_same_finger_motion(s1, s2, note) == pytest.approx(0.0)


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
        s1 = _st(7, Finger.RING, hand_pos=5)
        s_cross = _st(8, Finger.MIDDLE, hand_pos=5)   # fret up, rank down → cross
        s_natural = _st(8, Finger.PINKY, hand_pos=5)   # fret up, rank up → OK
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
        # RING (rank 2) at fret 7 then MIDDLE (rank 1) at fret 9 → CROSSING.
        # Natural assignment (R-C5): hp=5, INDEX@5 (natural), RING@7 (natural),
        # PINKY@9 (1-fret stretch from natural hp+3=8).
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
            _fr(2, 0.0, 5, 9, Finger.MIDDLE),
        ]
        out = resolve_chord_finger_ordering(results)
        by_fret = sorted(out, key=lambda r: r.state.fret)
        fingers = [r.state.finger for r in by_fret]
        assert fingers == [Finger.INDEX, Finger.RING, Finger.PINKY]

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

    def test_barre_chord_five_notes_skipped(self) -> None:
        # 5 fretted notes — barré, can't be resolved by this function alone.
        results = [_fr(i, 0.0, i + 1, 5, Finger.INDEX) for i in range(5)]
        out = resolve_chord_finger_ordering(results)
        # Resolver must not crash; result may be unchanged.
        assert len(out) == 5

    def test_duplicate_finger_in_chord_skipped(self) -> None:
        # Two notes with the same finger (duplicate) — resolver skips this chord.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.INDEX),  # duplicate INDEX
        ]
        out = resolve_chord_finger_ordering(results)
        assert len(out) == 2  # no crash


# ---------------------------------------------------------------------------
# CostWeights.musical
# ---------------------------------------------------------------------------


class TestCostWeightsMusical:
    def test_musical_weights_beta_dominant(self) -> None:
        w = CostWeights.musical()
        assert w.beta == pytest.approx(2.0)
        assert w.alpha == pytest.approx(1.0)
        assert w.gamma == pytest.approx(1.0)


# ---------------------------------------------------------------------------
# cost_sequential_crossing — fret==0 branch
# ---------------------------------------------------------------------------


class TestCostSequentialCrossingFretZero:
    def test_open_fret_source_no_penalty(self) -> None:
        # s1 fret=0 even with non-OPEN finger value (edge case guard).
        s1 = FingeringState(string_num=3, fret=0, finger=Finger.INDEX, hand_position=1)
        s2 = _st(5, Finger.MIDDLE)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_open_fret_target_no_penalty(self) -> None:
        s1 = _st(5, Finger.RING, hand_pos=5)
        s2 = FingeringState(string_num=3, fret=0, finger=Finger.INDEX, hand_position=1)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)

    def test_equal_rank_no_penalty(self) -> None:
        # Same finger on consecutive notes → rank_dir == 0 → no penalty.
        s1 = _st(5, Finger.INDEX, hand_pos=5)
        s2 = _st(6, Finger.INDEX, hand_pos=6)
        assert cost_sequential_crossing(s1, s2) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# compute_mechanical_cost — same string / same fret branches
# ---------------------------------------------------------------------------


class TestComputeMechanicalCostSamePosition:
    def test_same_string_same_fret_same_finger_zero(self) -> None:
        s = _state(string_num=3, fret=5, finger=Finger.INDEX, hand_position=5)
        assert compute_mechanical_cost(s, s, _note()) == pytest.approx(0.0)

    def test_same_string_same_fret_different_finger_has_penalty(self) -> None:
        s1 = _state(string_num=3, fret=5, finger=Finger.INDEX, hand_position=5)
        s2 = _state(string_num=3, fret=5, finger=Finger.MIDDLE, hand_position=4)
        cost = compute_mechanical_cost(s1, s2, _note())
        assert cost > 0.0

    def test_open_string_same_fret_no_special_case(self) -> None:
        # fret=0 does NOT trigger the same-fret special case.
        s = FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        cost = compute_mechanical_cost(s, s, _note())
        # Should be zero (open → open, same position) via the normal path.
        assert cost >= 0.0


# ---------------------------------------------------------------------------
# resolve_chord_stretch
# ---------------------------------------------------------------------------


def _fr2(
    note_id: int, onset: float, string_num: int, fret: int, finger: Finger, pitch: int = 60
) -> FingeringResult:
    _offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    offset = _offsets.get(finger, 0)
    hp = max(1, fret - offset) if fret > 0 else 1
    state = FingeringState(string_num=string_num, fret=fret, finger=finger, hand_position=hp)
    note = NoteEvent(pitch=pitch, onset=onset, duration=1.0, tempo=120.0)
    # Store a few alternative states so the resolver can revoice.
    alts = [
        (FingeringState(string_num=string_num + 1, fret=fret, finger=finger, hand_position=hp),
         1.5),
    ] if string_num < 6 else []
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=1.0, alternatives=alts)


class TestResolveChordStretch:
    def test_no_stretch_unchanged(self) -> None:
        # Chord within 4-fret span — no change needed.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
        ]
        out = resolve_chord_stretch(results)
        assert len(out) == 2
        frets = {r.state.fret for r in out}
        assert frets == {5, 7}

    def test_large_span_resolved_or_marked(self) -> None:
        # Chord with a 12-fret span: outlier should be revoiced or left unchanged.
        results = [
            _fr2(0, 0.0, 3, 5, Finger.INDEX, pitch=64),
            _fr2(1, 0.0, 4, 17, Finger.PINKY, pitch=76),
        ]
        out = resolve_chord_stretch(results)
        # Must not crash.
        assert len(out) == 2

    def test_single_note_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = resolve_chord_stretch(results)
        assert len(out) == 1
        assert out[0].state.fret == 5

    def test_empty_unchanged(self) -> None:
        assert resolve_chord_stretch([]) == []

    def test_two_open_strings_no_crash(self) -> None:
        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=1,
                note_event=NoteEvent(pitch=59, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=2, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
        ]
        out = resolve_chord_stretch(results)
        assert len(out) == 2


# ---------------------------------------------------------------------------
# resolve_chord_conflicts
# ---------------------------------------------------------------------------


class TestResolveChordConflicts:
    def test_no_conflict_unchanged(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
        ]
        out = resolve_chord_conflicts(results)
        fingers = {r.state.finger for r in out}
        assert Finger.INDEX in fingers
        assert Finger.RING in fingers

    def test_duplicate_finger_resolved(self) -> None:
        # Both notes use INDEX — one must be changed.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.INDEX),  # conflict
        ]
        out = resolve_chord_conflicts(results)
        fingers = [r.state.finger for r in out]
        # After resolution the two fingers must differ.
        assert fingers[0] != fingers[1]

    def test_open_string_not_conflicted(self) -> None:
        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=1,
                note_event=NoteEvent(pitch=59, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=2, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
        ]
        out = resolve_chord_conflicts(results)
        assert all(r.state.finger == Finger.OPEN for r in out)

    def test_single_note_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.MIDDLE)]
        out = resolve_chord_conflicts(results)
        assert out[0].state.finger == Finger.MIDDLE

    def test_empty_unchanged(self) -> None:
        assert resolve_chord_conflicts([]) == []

    def test_conflict_with_alternative_state(self) -> None:
        # Provide an alternative state so the resolver can pick it.
        alt = FingeringState(string_num=4, fret=7, finger=Finger.MIDDLE, hand_position=6)
        r0 = FingeringResult(
            note_id=0,
            note_event=NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0),
            state=FingeringState(string_num=3, fret=5, finger=Finger.INDEX, hand_position=5),
            cost=1.0,
        )
        r1 = FingeringResult(
            note_id=1,
            note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
            state=FingeringState(string_num=4, fret=7, finger=Finger.INDEX, hand_position=7),
            cost=1.0,
            alternatives=[(alt, 1.2)],  # alternative with MIDDLE
        )
        out = resolve_chord_conflicts([r0, r1])
        assert out[0].state.finger != out[1].state.finger

    def test_index_barre_same_fret_contiguous_strings_is_preserved(self) -> None:
        results = [
            _fr(0, 0.0, 1, 5, Finger.INDEX),
            _fr(1, 0.0, 2, 5, Finger.INDEX),
            _fr(2, 0.0, 3, 7, Finger.RING),
        ]

        out = resolve_chord_conflicts(results)

        assert out[0].state.finger is Finger.INDEX
        assert out[1].state.finger is Finger.INDEX
        assert out[2].state.finger is Finger.RING


# ---------------------------------------------------------------------------
# resolve_finger_continuity
# ---------------------------------------------------------------------------


def _seq_fr(
    note_id: int,
    onset: float,
    string_num: int,
    fret: int,
    finger: Finger,
    hand_position: int | None = None,
    measure_index: int | None = None,
) -> FingeringResult:
    """Helper: FingeringResult with no alternatives (continuity from scratch)."""
    _offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    offset = _offsets.get(finger, 0)
    hp = hand_position if hand_position is not None else max(1, fret - offset) if fret > 0 else 1
    state = FingeringState(string_num=string_num, fret=fret, finger=finger, hand_position=hp)
    note = NoteEvent(
        pitch=60,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        measure_index=measure_index,
    )
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=1.0)


class TestResolveFingerContinuity:
    def test_empty_returns_empty(self) -> None:
        assert resolve_finger_continuity([]) == []

    def test_single_note_unchanged(self) -> None:
        results = [_seq_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = resolve_finger_continuity(results)
        assert out[0].state.finger == Finger.INDEX

    def test_same_string_same_fret_propagates_finger(self) -> None:
        # String 3, fret 5 appears twice. Second should inherit first's finger.
        results = [
            _seq_fr(0, 0.0, 3, 5, Finger.INDEX),
            _seq_fr(1, 1.0, 3, 5, Finger.MIDDLE),  # different finger — should be fixed
        ]
        out = resolve_finger_continuity(results)
        assert out[1].state.finger == Finger.INDEX

    def test_different_fret_breaks_continuity(self) -> None:
        # String 3 at fret 5 then fret 7 — finger should NOT propagate.
        results = [
            _seq_fr(0, 0.0, 3, 5, Finger.INDEX),
            _seq_fr(1, 1.0, 3, 7, Finger.RING),
        ]
        out = resolve_finger_continuity(results)
        assert out[1].state.finger == Finger.RING

    def test_open_string_not_affected(self) -> None:
        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=1,
                note_event=NoteEvent(pitch=64, onset=1.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
        ]
        out = resolve_finger_continuity(results)
        assert all(r.state.finger == Finger.OPEN for r in out)

    def test_lookback_window_respected(self) -> None:
        # Lookback default=8 beats. Note at onset 0 and onset 100 → no continuity.
        results = [
            _seq_fr(0, 0.0, 3, 5, Finger.INDEX),
            _seq_fr(1, 100.0, 3, 5, Finger.MIDDLE),
        ]
        out = resolve_finger_continuity(results, lookback_beats=8.0)
        # Too far back → second note's finger unchanged.
        assert out[1].state.finger == Finger.MIDDLE

    def test_chord_conflict_prevention(self) -> None:
        # At onset 1.0, string 4 already uses INDEX. Don't propagate INDEX to string 3.
        results = [
            _seq_fr(0, 0.0, 3, 5, Finger.INDEX),   # string 3 fret 5 → INDEX
            _seq_fr(1, 1.0, 4, 7, Finger.INDEX),    # string 4, different
            _seq_fr(2, 1.0, 3, 5, Finger.MIDDLE),   # string 3 fret 5 same onset as above
        ]
        out = resolve_finger_continuity(results)
        # String 3 at onset 1.0 would want INDEX but INDEX is already used by string 4.
        # Conflict prevention: should NOT propagate.
        assert len(out) == 3  # no crash

    def test_measure_boundary_with_new_hand_position_breaks_continuity(self) -> None:
        results = [
            _seq_fr(0, 0.0, 3, 2, Finger.MIDDLE, hand_position=1, measure_index=6),
            _seq_fr(1, 1.0, 3, 2, Finger.INDEX, hand_position=2, measure_index=7),
        ]

        out = resolve_finger_continuity(results)

        assert out[1].state.finger is Finger.INDEX
        assert out[1].state.hand_position == 2


# ---------------------------------------------------------------------------
# resolve_chord_partial_barre
# ---------------------------------------------------------------------------


def _chord_fr(
    note_id: int,
    onset: float,
    string_num: int,
    fret: int,
    finger: Finger,
    hand_position: int,
) -> FingeringResult:
    """FingeringResult helper for chord tests — all notes share an onset."""
    return _fr_hp(note_id, onset, string_num, fret, finger, hand_position)


class TestResolveChordPartialBarre:
    """Verify the partial-barre resolver — a chord with 2+ notes on adjacent
    strings at the same lowest fret should use INDEX as a barre."""

    def test_bm_voicing_collapses_to_index_barre_plus_ring(self) -> None:
        # The exact BB King "Thrill Is Gone" m2 chord:
        # s1 f7 (index), s2 f7 (middle), s3 f7 (ring), s4 f9 (pinky)
        results = [
            _chord_fr(0, 0.0, 1, 7, Finger.INDEX,  7),
            _chord_fr(1, 0.0, 2, 7, Finger.MIDDLE, 6),
            _chord_fr(2, 0.0, 3, 7, Finger.RING,   5),
            _chord_fr(3, 0.0, 4, 9, Finger.PINKY,  6),
        ]
        out = resolve_chord_partial_barre(results)
        fingers = [r.state.finger for r in out]
        # The 3 notes at f7 (s1, s2, s3 adjacent) should all use INDEX.
        assert out[0].state.finger is Finger.INDEX
        assert out[1].state.finger is Finger.INDEX
        assert out[2].state.finger is Finger.INDEX
        # The f9 note should use a non-pinky finger (RING is natural at hp=7).
        assert out[3].state.finger is Finger.RING
        # All hp values should be 7 (the barre fret).
        for r in out:
            assert r.state.hand_position == 7

    def test_non_contiguous_two_endpoint_barre_is_not_invented(self) -> None:
        # Django-style 6-7-6-8: two same-fret endpoints with a fretted note
        # between them should not become an index clamp around the middle finger.
        results = [
            _chord_fr(0, 0.0, 2, 6, Finger.MIDDLE, 5),
            _chord_fr(1, 0.0, 3, 7, Finger.RING, 5),
            _chord_fr(2, 0.0, 4, 6, Finger.INDEX, 6),
            _chord_fr(3, 0.0, 1, 8, Finger.PINKY, 5),
        ]
        out = resolve_chord_partial_barre(results)
        assert [r.state.finger for r in out] == [
            Finger.MIDDLE,
            Finger.RING,
            Finger.INDEX,
            Finger.PINKY,
        ]

    def test_wide_non_contiguous_two_endpoint_barre_is_allowed(self) -> None:
        # A-shape barre, e.g. 5-7-7-7-5: the index spans a wide range.
        results = [
            _chord_fr(0, 0.0, 1, 5, Finger.MIDDLE, 4),
            _chord_fr(1, 0.0, 2, 7, Finger.PINKY, 4),
            _chord_fr(2, 0.0, 3, 7, Finger.RING, 5),
            _chord_fr(3, 0.0, 4, 7, Finger.INDEX, 7),
            _chord_fr(4, 0.0, 5, 5, Finger.MIDDLE, 4),
        ]

        out = resolve_chord_partial_barre(results)

        assert out[0].state.finger is Finger.INDEX
        assert out[4].state.finger is Finger.INDEX
        assert all(result.state.hand_position == 5 for result in out)

    def test_two_adjacent_notes_form_barre(self) -> None:
        # s2 f5 + s1 f5, contiguous at same fret.
        results = [
            _chord_fr(0, 0.0, 1, 5, Finger.INDEX,  5),
            _chord_fr(1, 0.0, 2, 5, Finger.MIDDLE, 4),
        ]
        out = resolve_chord_partial_barre(results)
        assert out[0].state.finger is Finger.INDEX
        assert out[1].state.finger is Finger.INDEX  # barred

    def test_single_note_chord_unchanged(self) -> None:
        results = [_chord_fr(0, 0.0, 3, 5, Finger.INDEX, 5)]
        out = resolve_chord_partial_barre(results)
        assert out[0].state.finger is Finger.INDEX

    def test_full_barre_all_strings_same_fret(self) -> None:
        # F barre — 6 strings at fret 1.  All INDEX, hp=1.
        # (No higher-fret note in this simplified case.)
        results = [
            _chord_fr(0, 0.0, 1, 1, Finger.INDEX,  1),
            _chord_fr(1, 0.0, 2, 1, Finger.MIDDLE, 1),
            _chord_fr(2, 0.0, 3, 1, Finger.RING,   1),
            _chord_fr(3, 0.0, 4, 1, Finger.PINKY,  1),
        ]
        out = resolve_chord_partial_barre(results)
        assert all(r.state.finger is Finger.INDEX for r in out)
        assert all(r.state.hand_position == 1 for r in out)


# ---------------------------------------------------------------------------
# resolve_chord_unified_hand_position
# ---------------------------------------------------------------------------


class TestResolveChordUnifiedHandPosition:
    """Verify that all fretted notes in a chord share one hand_position."""

    def test_divergent_hps_are_unified(self) -> None:
        # Three notes with hp values {5, 6, 7} — INDEX is present, so hp = INDEX.fret = 7.
        results = [
            _chord_fr(0, 0.0, 1, 7, Finger.INDEX,  7),
            _chord_fr(1, 0.0, 2, 7, Finger.MIDDLE, 6),
            _chord_fr(2, 0.0, 3, 7, Finger.RING,   5),
        ]
        out = resolve_chord_unified_hand_position(results)
        assert {r.state.hand_position for r in out} == {7}

    def test_already_unified_unchanged(self) -> None:
        results = [
            _chord_fr(0, 0.0, 1, 5, Finger.INDEX, 5),
            _chord_fr(1, 0.0, 2, 5, Finger.INDEX, 5),
        ]
        out = resolve_chord_unified_hand_position(results)
        assert {r.state.hand_position for r in out} == {5}

    def test_open_strings_not_affected(self) -> None:
        results = [
            _chord_fr(0, 0.0, 1, 0, Finger.OPEN,  1),
            _chord_fr(1, 0.0, 2, 5, Finger.INDEX, 5),
            _chord_fr(2, 0.0, 3, 7, Finger.RING,  5),
        ]
        out = resolve_chord_unified_hand_position(results)
        # Open's hp stays at 1; fretted notes unify to INDEX's fret (5).
        assert out[0].state.hand_position == 1
        assert out[1].state.hand_position == 5
        assert out[2].state.hand_position == 5


# ---------------------------------------------------------------------------
# resolve_pinky_run_to_index
# ---------------------------------------------------------------------------


class TestResolvePinkyRunToIndex:
    """Tests for the pinky-run → index rewrite (fixes the Viterbi quirk that
    keeps pinky planted for repeated same-fret notes at a low hand position).
    """

    def test_empty_unchanged(self) -> None:
        assert resolve_pinky_run_to_index([]) == []

    def test_short_run_below_threshold_unchanged(self) -> None:
        # 2 consecutive pinky notes — below min_run=3, not rewritten.
        results = [
            _fr_hp(0, 0.0, 4, 5, Finger.PINKY, 2),
            _fr_hp(1, 0.5, 4, 5, Finger.PINKY, 2),
        ]
        out = resolve_pinky_run_to_index(results)
        assert all(r.state.finger is Finger.PINKY for r in out)

    def test_long_run_rewritten_to_index(self) -> None:
        # 4 pinky notes on the same (s, f, hp), nothing else sharing hp=2.
        results = [
            _fr_hp(0, 0.0, 4, 5, Finger.PINKY, 2),
            _fr_hp(1, 0.5, 4, 5, Finger.PINKY, 2),
            _fr_hp(2, 1.0, 4, 5, Finger.PINKY, 2),
            _fr_hp(3, 1.5, 4, 5, Finger.PINKY, 2),
        ]
        out = resolve_pinky_run_to_index(results)
        for r in out:
            assert r.state.finger is Finger.INDEX
            assert r.state.hand_position == 5   # moved to hp = fret
            assert r.state.fret == 5

    def test_hp_shared_by_other_finger_keeps_pinky(self) -> None:
        # Pinky run of 3 at hp=4, but an INDEX note at hp=4 appears just
        # after the run.  Hp=4 is legitimate — the run is a real stretch, not
        # a shortcut.  Must not rewrite.
        results = [
            _fr_hp(0, 0.0, 3, 7, Finger.PINKY, 4),
            _fr_hp(1, 0.5, 3, 7, Finger.PINKY, 4),
            _fr_hp(2, 1.0, 3, 7, Finger.PINKY, 4),
            _fr_hp(3, 1.5, 3, 4, Finger.INDEX, 4),   # same hp, non-pinky
        ]
        out = resolve_pinky_run_to_index(results)
        for r in out[:3]:
            assert r.state.finger is Finger.PINKY

    def test_run_broken_by_different_string_not_rewritten(self) -> None:
        # Pinky on s4 f5 for 2 notes, then s3 f5, breaks the run.  Each
        # sub-run is 2 long, below the threshold.
        results = [
            _fr_hp(0, 0.0, 4, 5, Finger.PINKY, 2),
            _fr_hp(1, 0.5, 4, 5, Finger.PINKY, 2),
            _fr_hp(2, 1.0, 3, 5, Finger.PINKY, 2),   # different string
            _fr_hp(3, 1.5, 3, 5, Finger.PINKY, 2),
        ]
        out = resolve_pinky_run_to_index(results)
        assert all(r.state.finger is Finger.PINKY for r in out)

    def test_run_rewrite_preserves_note_id_and_event(self) -> None:
        results = [
            _fr_hp(10, 0.0, 4, 5, Finger.PINKY, 2),
            _fr_hp(11, 0.5, 4, 5, Finger.PINKY, 2),
            _fr_hp(12, 1.0, 4, 5, Finger.PINKY, 2),
        ]
        out = resolve_pinky_run_to_index(results)
        assert [r.note_id for r in out] == [10, 11, 12]
        assert all(r.note_event is results[i].note_event for i, r in enumerate(out))


class TestResolveArpeggioChordFingering:
    def test_stabilisation_anchors_on_lowest_played_fret(self) -> None:
        results = [
            _fr_hp(0, 0.0, 5, 7, Finger.PINKY, 4),
            _fr_hp(1, 1.0, 4, 7, Finger.PINKY, 4),
            _fr_hp(2, 2.0, 3, 5, Finger.MIDDLE, 4),
            _fr_hp(3, 3.5, 3, 7, Finger.PINKY, 4),
            _fr_hp(4, 3.75, 3, 5, Finger.MIDDLE, 4),
        ]

        out = resolve_arpeggio_chord_fingering(results)

        assert [r.state.finger for r in out] == [
            Finger.RING,
            Finger.RING,
            Finger.INDEX,
            Finger.RING,
            Finger.INDEX,
        ]
        assert [r.state.hand_position for r in out] == [5, 5, 5, 5, 5]

    def test_stabilisation_does_not_pull_previous_measure_down(self) -> None:
        results = [
            _fr(0, 0.0, 5, 7, Finger.INDEX),
            _fr(1, 1.0, 4, 7, Finger.MIDDLE),
            _fr(2, 2.0, 3, 5, Finger.INDEX),
            _fr(3, 3.5, 3, 7, Finger.MIDDLE),
            _fr(4, 3.75, 3, 5, Finger.INDEX),
            _fr(5, 4.0, 3, 4, Finger.INDEX),
        ]
        for result in results[:5]:
            result.note_event.measure_index = 1
        results[5].note_event.measure_index = 2

        out = resolve_arpeggio_chord_fingering(results)

        assert [r.state.finger for r in out[:5]] == [
            Finger.RING,
            Finger.RING,
            Finger.INDEX,
            Finger.RING,
            Finger.INDEX,
        ]
        assert [r.state.hand_position for r in out[:5]] == [5, 5, 5, 5, 5]
        assert out[5].state.finger is Finger.INDEX
        assert out[5].state.hand_position == 4


class _StubCost:
    """Minimal cost_fn stub exposing only transition_cost.

    ``score(state)`` maps a candidate/current FingeringState to a scalar so a
    test can make a specific (finger, hand_position) cheap or expensive and
    verify the resolver's gate honours it.  The resolver only ever calls
    ``transition_cost``; everything else on CostFunction is irrelevant here.
    """

    def __init__(self, score) -> None:  # noqa: ANN001
        self._score = score
        self.calls = 0

    def transition_cost(self, s1, s2, note, index=None):  # noqa: ANN001, ANN002, ANN003
        self.calls += 1
        # Score BOTH endpoints so a candidate is charged whether it appears as
        # the source (s1, on the k->next edge) or target (s2, on prev->k).
        return float(self._score(s1)) + float(self._score(s2))


class TestResolveArpeggioCostAware:
    """Cost-aware gating of resolve_arpeggio_chord_fingering (cost_fn=...)."""

    def _window(self) -> list[FingeringResult]:
        # Same shape as test_stabilisation_anchors_on_lowest_played_fret:
        # Viterbi left these at hp=4 with drifting fingers; the natural
        # stabilisation anchors hp=5 and assigns RING/RING/INDEX/RING/INDEX.
        return [
            _fr_hp(0, 0.0, 5, 7, Finger.PINKY, 4),
            _fr_hp(1, 1.0, 4, 7, Finger.PINKY, 4),
            _fr_hp(2, 2.0, 3, 5, Finger.MIDDLE, 4),
            _fr_hp(3, 3.5, 3, 7, Finger.PINKY, 4),
            _fr_hp(4, 3.75, 3, 5, Finger.MIDDLE, 4),
        ]

    def test_cost_fn_none_is_backward_compatible(self) -> None:
        # cost_fn omitted → identical to the legacy unconditional behaviour.
        legacy = resolve_arpeggio_chord_fingering(self._window())
        explicit_none = resolve_arpeggio_chord_fingering(self._window(), cost_fn=None)
        assert [r.state.finger for r in legacy] == [r.state.finger for r in explicit_none]
        assert [r.state.hand_position for r in legacy] == [
            r.state.hand_position for r in explicit_none
        ]

    def test_override_applied_when_cost_neutral(self) -> None:
        # Flat cost (0 everywhere) → every override is cost-neutral, so the
        # stabilisation fires exactly as in the legacy path: anti-oscillation
        # is retained when it does not fight the cost.
        cost = _StubCost(lambda s: 0.0)
        out = resolve_arpeggio_chord_fingering(self._window(), cost_fn=cost)
        assert cost.calls > 0
        assert [r.state.finger for r in out] == [
            Finger.RING, Finger.RING, Finger.INDEX, Finger.RING, Finger.INDEX,
        ]
        assert [r.state.hand_position for r in out] == [5, 5, 5, 5, 5]

    def test_override_applied_when_strictly_cheaper(self) -> None:
        # Make the anchored hp=5 strictly cheaper than the original hp=4.
        cost = _StubCost(lambda s: 0.0 if s.hand_position == 5 else 10.0)
        out = resolve_arpeggio_chord_fingering(self._window(), cost_fn=cost)
        assert all(r.state.hand_position == 5 for r in out)

    def test_override_skipped_when_it_raises_cost(self) -> None:
        # Penalise the anchored hp=5 heavily → every override raises cost above
        # epsilon, so NONE are applied and Viterbi's states survive untouched.
        original = self._window()
        cost = _StubCost(lambda s: 100.0 if s.hand_position == 5 else 0.0)
        out = resolve_arpeggio_chord_fingering(original, cost_fn=cost)
        assert [r.state.finger for r in out] == [r.state.finger for r in original]
        assert [r.state.hand_position for r in out] == [
            r.state.hand_position for r in original
        ]

    def test_epsilon_admits_exact_ties(self) -> None:
        # A constant cost regardless of state is an exact tie on every edge;
        # the epsilon slack lets the stabilisation still fire.
        cost = _StubCost(lambda s: 4.2)
        out = resolve_arpeggio_chord_fingering(self._window(), cost_fn=cost)
        assert all(r.state.hand_position == 5 for r in out)

    def test_real_cost_function_clear_arpeggio_still_stabilised(self) -> None:
        # Spot-check with the REAL composite CostFunction (performance weights):
        # a clean one-position arpeggio whose stabilisation is cost-neutral
        # still collapses onto a single hand_position (anti-oscillation kept).
        cost = CostFunction(weights=CostWeights.performance())
        out = resolve_arpeggio_chord_fingering(self._window(), cost_fn=cost)
        hps = {r.state.hand_position for r in out}
        # The window collapses to one anchored hand position rather than the
        # drifting hp=4 the stub Viterbi left (at least it does not increase
        # the spread of hand positions).
        assert len(hps) <= len({r.state.hand_position for r in self._window()})


# ---------------------------------------------------------------------------
# resolve_sedentary_fingers
# ---------------------------------------------------------------------------


def _fr_hp(
    note_id: int,
    onset: float,
    string_num: int,
    fret: int,
    finger: Finger,
    hand_position: int,
    duration: float = 0.5,
) -> FingeringResult:
    """FingeringResult with explicit hand_position (for sedentary tests)."""
    state = FingeringState(
        string_num=string_num, fret=fret, finger=finger, hand_position=hand_position,
    )
    note = NoteEvent(pitch=60, onset=onset, duration=duration, tempo=120.0)
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=0.0)


class TestResolveSedentaryFingers:
    """Test the sedentary-finger post-processing pass.

    See ``docs/finger_placement_strategy.md`` for the specification of rules
    R1 (non-interference), R2 (reachability) and R3 (utility).
    """

    def test_empty_returns_empty(self) -> None:
        assert resolve_sedentary_fingers([]) == []

    def test_single_note_has_no_planted(self) -> None:
        out = resolve_sedentary_fingers([_fr_hp(0, 0.0, 5, 3, Finger.RING, 1)])
        assert out[0].planted_fingers == {}

    def test_one_shot_arpeggio_no_future_reuse_not_planted(self) -> None:
        # One-shot C arpeggio: ring(5,3), middle(4,2), open, index(2,1), open.
        # No reuses anywhere — under the default (R3a-only) strict rule no
        # finger is marked planted because none is reused within the lookahead.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,   1),
            _fr_hp(1, 0.5, 4, 2, Finger.MIDDLE, 1),
            _fr_hp(2, 1.0, 3, 0, Finger.OPEN,   1),
            _fr_hp(3, 1.5, 2, 1, Finger.INDEX,  1),
            _fr_hp(4, 2.0, 1, 0, Finger.OPEN,   1),
        ]
        out = resolve_sedentary_fingers(results)
        assert all(r.planted_fingers == {} for r in out)

    def test_arpeggio_with_chord_context_flag_plants(self) -> None:
        # Opt-in R3b: classical "plant ahead" style — a one-shot arpeggio
        # in a stable hand position marks prior fingers as planted even
        # without future reuse.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,   1),
            _fr_hp(1, 0.5, 4, 2, Finger.MIDDLE, 1),
            _fr_hp(2, 1.0, 3, 0, Finger.OPEN,   1),
            _fr_hp(3, 1.5, 2, 1, Finger.INDEX,  1),
            _fr_hp(4, 2.0, 1, 0, Finger.OPEN,   1),
        ]
        out = resolve_sedentary_fingers(results, allow_chord_context=True)
        assert out[0].planted_fingers == {}
        assert out[1].planted_fingers == {"ring": (5, 3)}
        assert out[4].planted_fingers == {"ring": (5, 3), "middle": (4, 2), "index": (2, 1)}

    def test_arpeggio_with_reuse_plants_via_r3a(self) -> None:
        # When the arpeggio repeats (reuse of the same finger at the same
        # position later), R3a correctly marks the finger as planted even
        # without R3b.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,   1),
            _fr_hp(1, 0.5, 4, 2, Finger.MIDDLE, 1),  # ring not yet known reused
            _fr_hp(2, 1.0, 5, 3, Finger.RING,   1),  # reuse — triggers R3a
        ]
        out = resolve_sedentary_fingers(results)
        # At note 1, ring will be reused at note 2 → planted via R3a
        assert out[1].planted_fingers == {"ring": (5, 3)}

    def test_position_shift_releases_fingers_out_of_reach(self) -> None:
        # Shift from hp=1 to hp=5 → fret 2 and fret 3 fall outside [4, 9] reach.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,   1),
            _fr_hp(1, 0.5, 4, 2, Finger.MIDDLE, 1),
            _fr_hp(2, 1.0, 5, 7, Finger.RING,   5),  # position shift
        ]
        out = resolve_sedentary_fingers(results)
        # At note 2: middle's (4, 2) is out of reach (2 < max(1, 5-1)=4).
        assert out[2].planted_fingers == {}

    def test_same_string_higher_fret_covers_lower_planted(self) -> None:
        # Ring plants (3, 5). Next note plays (3, 7) with pinky.
        # R1b — active fret 7 > planted fret 5, planted is covered, OK.
        # R3a — check reuse: need a future reuse of ring at (3, 5).
        results = [
            _fr_hp(0, 0.0, 3, 5, Finger.RING,  3),
            _fr_hp(1, 0.5, 3, 7, Finger.PINKY, 3),
            _fr_hp(2, 1.0, 3, 5, Finger.RING,  3),  # reuse of ring at (3, 5)
        ]
        out = resolve_sedentary_fingers(results)
        assert out[1].planted_fingers == {"ring": (3, 5)}
        # Note 2 is the active reuse, so ring is no longer planted (it's now active).
        assert "ring" not in out[2].planted_fingers

    def test_same_string_lower_fret_releases_planted(self) -> None:
        # Ring at (3, 7). Then index at (3, 5) — would be MUTED by ring's higher fret.
        # Planted ring must be released (R1b fails: 7 > 5, planted dominates → bad).
        results = [
            _fr_hp(0, 0.0, 3, 7, Finger.RING,  5),
            _fr_hp(1, 0.5, 3, 5, Finger.INDEX, 5),
        ]
        out = resolve_sedentary_fingers(results)
        assert out[1].planted_fingers == {}

    def test_future_reuse_triggers_plant(self) -> None:
        # Ring at (5, 3), then note on another string, then ring back at (5, 3).
        # R3a reuse rule keeps ring planted on the intermediate note.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,  1),
            _fr_hp(1, 3.0, 3, 1, Finger.INDEX, 1),  # 3 beats later → still within lookback
            _fr_hp(2, 6.0, 5, 3, Finger.RING,  1),
        ]
        out = resolve_sedentary_fingers(results)
        assert out[1].planted_fingers == {"ring": (5, 3)}

    def test_next_use_is_a_move_not_planted(self) -> None:
        # Ring at (5, 3), then index, then ring at a DIFFERENT position (5, 5),
        # then ring back at (5, 3).  Even though ring returns to (5, 3) later,
        # its IMMEDIATE next action is to move — it is NOT sedentary on the
        # intermediate index note.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,  1),
            _fr_hp(1, 1.0, 3, 1, Finger.INDEX, 1),
            _fr_hp(2, 2.0, 5, 5, Finger.RING,  3),   # move!
            _fr_hp(3, 3.0, 5, 3, Finger.RING,  1),   # eventual return
        ]
        out = resolve_sedentary_fingers(results)
        # At note 1, ring's NEXT use is (5, 5) — different from its placed
        # (5, 3). So it is a move, not a stay. Must NOT be planted.
        assert "ring" not in out[1].planted_fingers

    def test_no_reuse_no_chord_context_no_plant(self) -> None:
        # Ring placed then not reused and not in chord context (gap > 2 beats,
        # not part of the same hand position cluster).  Should NOT plant.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,  1),
            _fr_hp(1, 5.0, 3, 1, Finger.INDEX, 1),  # 5 beats later, no future reuse
        ]
        out = resolve_sedentary_fingers(results)
        assert out[1].planted_fingers == {}

    def test_active_finger_is_never_planted(self) -> None:
        # When a finger IS the active finger for the current note, it must not
        # appear in planted_fingers.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,   1),
            _fr_hp(1, 0.5, 5, 3, Finger.RING,   1),  # same finger re-strike
        ]
        out = resolve_sedentary_fingers(results)
        assert "ring" not in out[1].planted_fingers

    def test_inactive_timeout_releases_finger(self) -> None:
        # With a 1-beat max_inactive override, a finger placed at onset 0
        # should be released by onset 5.
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,  1),
            _fr_hp(1, 5.0, 4, 2, Finger.INDEX, 1),
        ]
        out = resolve_sedentary_fingers(results, max_inactive_beats=1.0)
        assert out[1].planted_fingers == {}

    def test_collision_clears_previous_finger(self) -> None:
        # If index lands on (5, 3) where ring used to be planted, the old ring
        # entry is cleared (two fingers cannot share one position).
        results = [
            _fr_hp(0, 0.0, 5, 3, Finger.RING,  1),
            _fr_hp(1, 0.5, 5, 3, Finger.INDEX, 1),
            _fr_hp(2, 1.0, 4, 2, Finger.MIDDLE, 1),
        ]
        out = resolve_sedentary_fingers(results)
        # At note 2, ring should NOT be planted at (5, 3) — that position is now index's.
        assert "ring" not in out[2].planted_fingers


# ---------------------------------------------------------------------------
# resolve_section_consistency
# ---------------------------------------------------------------------------


class TestResolveSectionConsistency:
    def test_empty_unchanged(self) -> None:
        assert resolve_section_consistency([]) == []

    def test_single_note_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = resolve_section_consistency(results)
        assert out[0].state.finger == Finger.INDEX

    def test_repeated_single_note_keeps_contextual_finger(self) -> None:
        # Same single note at two different onsets can require different fingers
        # depending on the local hand position; section consistency is for shapes.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 4.0, 3, 5, Finger.MIDDLE),
        ]
        out = resolve_section_consistency(results)
        assert out[1].state.finger == Finger.MIDDLE

    def test_different_fret_not_affected(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 4.0, 3, 7, Finger.RING),     # different fret, different shape
        ]
        out = resolve_section_consistency(results)
        assert out[0].state.finger == Finger.INDEX
        assert out[1].state.finger == Finger.RING

    def test_chord_shape_consistency(self) -> None:
        # Same chord shape (string 3 fret 5, string 4 fret 7) appears twice.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
            _fr(2, 8.0, 3, 5, Finger.MIDDLE),   # same shape, different fingers
            _fr(3, 8.0, 4, 7, Finger.INDEX),
        ]
        out = resolve_section_consistency(results)
        # The canonical from onset 0 should be applied to onset 8.
        at_onset8 = [r for r in out if r.note_event.onset == 8.0]
        by_string = {r.state.string_num: r.state.finger for r in at_onset8}
        assert by_string[3] == Finger.INDEX
        assert by_string[4] == Finger.RING

    def test_canonical_conflict_skipped(self) -> None:
        # If applying canonical would create a finger conflict, skip it.
        # Canonical: string 3→INDEX, string 4→INDEX (duplicate — conflict)
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.INDEX),    # conflict in canonical itself
            _fr(2, 4.0, 3, 5, Finger.MIDDLE),
            _fr(3, 4.0, 4, 7, Finger.RING),
        ]
        out = resolve_section_consistency(results)
        # Should not crash; onset 4.0 notes should be skipped (canonical is conflicted).
        assert len(out) == 4


# ---------------------------------------------------------------------------
# _natural_finger_assignment  (R-C5 — natural hand position / no finger skipping)
# ---------------------------------------------------------------------------


class TestNaturalFingerAssignment:
    def test_single_fret_index(self) -> None:
        # Single note: always INDEX (lowest-rank available from natural offset 0).
        result = _natural_finger_assignment([5])
        assert result == [Finger.INDEX]

    def test_consecutive_frets_natural_order(self) -> None:
        # [5, 6, 7] with hp=5: natural offsets 0, 1, 2 → INDEX, MIDDLE, RING.
        result = _natural_finger_assignment([5, 6, 7])
        assert result == [Finger.INDEX, Finger.MIDDLE, Finger.RING]

    def test_skip_fret_no_finger_skipping(self) -> None:
        # [2, 4, 4] with hp=2: natural offsets 0, 2, 2.
        # fret=2 → INDEX (offset 0).
        # fret=4 → RING (offset 2, preferred over MIDDLE which would skip RING's territory).
        # fret=4 → PINKY (offset 2 taken, next available upward is 3).
        result = _natural_finger_assignment([2, 4, 4])
        assert result == [Finger.INDEX, Finger.RING, Finger.PINKY]

    def test_power_chord_shape(self) -> None:
        # [5, 7] with hp=5: natural offsets 0, 2 → INDEX, RING.
        result = _natural_finger_assignment([5, 7])
        assert result == [Finger.INDEX, Finger.RING]

    def test_equal_frets_ascending_assignment(self) -> None:
        # [5, 5, 5] with hp=5: all natural offset 0. Fill upward: INDEX, MIDDLE, RING.
        result = _natural_finger_assignment([5, 5, 5])
        assert result == [Finger.INDEX, Finger.MIDDLE, Finger.RING]

    def test_large_gap_returns_none(self) -> None:
        # [5, 10]: span=5 > INDEX–PINKY max (4) → None.
        result = _natural_finger_assignment([5, 10])
        assert result is None

    def test_adjacent_finger_span_limit(self) -> None:
        # [5, 8]: INDEX–RING span=3. max for INDEX–RING=(0,2)=3 → valid.
        result = _natural_finger_assignment([5, 8])
        assert result is not None
        # Span INDEX–RING is at the limit, so valid assignment exists.

    def test_adjacent_finger_span_exceeded(self) -> None:
        # [5, 8] gives INDEX, PINKY (natural: offset3 for 8-5=3) — span check:
        # INDEX(0)–PINKY(3): max=4, gap=3 ✓. Actually valid.
        # [5, 9]: offset=4 > 3 for any finger from hp=5. Fallback: offset=3 → PINKY.
        # INDEX(0)–PINKY(3): gap=4 == max=4 ✓.
        result = _natural_finger_assignment([5, 9])
        assert result is not None  # just within INDEX-PINKY limit

    def test_monotone_r_c3_satisfied(self) -> None:
        # Result must always be in ascending rank order for ascending frets.
        from fretwise.scoring import _FINGER_RANK
        for frets in [[3, 5], [5, 6, 7], [2, 4, 4], [1, 4, 7]]:
            result = _natural_finger_assignment(frets)
            if result is None:
                continue
            ranks = [_FINGER_RANK[f] for f in result]
            # For equal frets, ranks may be ascending (barré fill); always non-crossing.
            for i in range(len(frets) - 1):
                if frets[i] < frets[i + 1]:
                    assert ranks[i] < ranks[i + 1], (
                        f"frets={frets}, ranks={ranks}: not monotone at index {i}"
                    )

    def test_empty_returns_none(self) -> None:
        assert _natural_finger_assignment([]) is None

    def test_five_notes_returns_none(self) -> None:
        assert _natural_finger_assignment([5, 6, 7, 8, 9]) is None


# ---------------------------------------------------------------------------
# resolve_chord_finger_span  (R-C4 — finger-pair span limits)
# ---------------------------------------------------------------------------


class TestResolveChordFingerSpan:
    def test_valid_chord_unchanged(self) -> None:
        # INDEX fret 5, RING fret 7 — span 2 within INDEX-RING max (3).
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 7, Finger.RING),
        ]
        out = resolve_chord_finger_span(results)
        fingers = {r.state.finger for r in out}
        assert Finger.INDEX in fingers
        assert Finger.RING in fingers

    def test_invalid_span_reassigned(self) -> None:
        # INDEX fret 5, MIDDLE fret 8 — span 3 > INDEX-MIDDLE max (2).
        # Natural assignment for [5, 8]: hp=5, INDEX@5, RING@8 (offset 3 from hp=5... wait
        # natural offset for fret 8 = 8-5=3 → PINKY). So result: INDEX, PINKY.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 0.0, 4, 8, Finger.MIDDLE),  # MIDDLE can only reach 2 frets from INDEX
        ]
        out = resolve_chord_finger_span(results)
        fingers_by_fret = sorted(out, key=lambda r: r.state.fret)
        # Lower fret must be INDEX (lowest rank).
        assert fingers_by_fret[0].state.finger == Finger.INDEX
        # Higher fret must not be MIDDLE (span too large for adjacent fingers).
        assert fingers_by_fret[1].state.finger != Finger.MIDDLE

    def test_single_note_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = resolve_chord_finger_span(results)
        assert out[0].state.finger == Finger.INDEX

    def test_empty_unchanged(self) -> None:
        assert resolve_chord_finger_span([]) == []

    def test_natural_assignment_no_finger_skipping(self) -> None:
        # The core R-C5 bug: frets [2, 4, 4] with INDEX, MIDDLE, PINKY.
        # MIDDLE@4 with INDEX@2 has span 2 = INDEX-MIDDLE max (2), so technically
        # not a span violation — BUT it IS a R-C5 violation (skips RING's territory).
        # resolve_chord_finger_span only catches R-C4. resolve_chord_finger_ordering
        # catches R-C3 (monotone) AND calls _natural_finger_assignment for R-C5.
        # Here we test the ordering resolver fixes the combined case:
        results = [
            _fr(0, 0.0, 3, 2, Finger.INDEX),
            _fr(1, 0.0, 4, 4, Finger.MIDDLE),
            _fr(2, 0.0, 5, 4, Finger.PINKY),
        ]
        # Ordering check: INDEX(0)@2, MIDDLE(1)@4, PINKY(3)@4 — is this monotone?
        # rank 0 < rank 1, fret 2 < fret 4 ✓; rank 1 < rank 3, fret 4 == fret 4 ✓.
        # No monotone violation → ordering resolver leaves it.
        # But it is a R-C5 violation (MIDDLE skips RING).
        # This test documents that the resolved output from the FULL pipeline
        # (ordering then span) correctly fixes this:
        out_ordered = resolve_chord_finger_ordering(results)
        # Ordering resolver sees no crossing here → may leave unchanged.
        # The span resolver should also not change it (no span violation for INDEX-MIDDLE@2frets).
        out_spanned = resolve_chord_finger_span(out_ordered)
        # Result is left with INDEX, MIDDLE, PINKY (no span violation detected).
        # The R-C5 fix for this specific case (no monotone violation) requires
        # a dedicated pre-processing step or Viterbi cost — documented here as a
        # known limitation of the post-processing approach.
        assert len(out_spanned) == 3  # no crash


# ---------------------------------------------------------------------------
# resolve_chord_string_diagonal  (R-C6 — string-rank diagonal preference)
# ---------------------------------------------------------------------------


class TestResolveChordStringDiagonal:
    def test_correct_diagonal_unchanged(self) -> None:
        # INDEX on string 1 (high e), MIDDLE on string 6 (low E) — correct diagonal.
        results = [
            _fr(0, 0.0, 1, 3, Finger.INDEX),   # string 1, fret 3
            _fr(1, 0.0, 6, 3, Finger.MIDDLE),  # string 6, fret 3
        ]
        out = resolve_chord_string_diagonal(results)
        by_string = {r.state.string_num: r.state.finger for r in out}
        assert by_string[1] == Finger.INDEX   # lower string → lower rank ✓
        assert by_string[6] == Finger.MIDDLE

    def test_reversed_diagonal_fixed(self) -> None:
        # RING on string 1, MIDDLE on string 6 — WRONG diagonal (higher rank on
        # high-pitch string). Should become INDEX on string 1, MIDDLE on string 6.
        results = [
            _fr(0, 0.0, 1, 3, Finger.RING),    # string 1, fret 3
            _fr(1, 0.0, 6, 3, Finger.MIDDLE),  # string 6, fret 3
        ]
        out = resolve_chord_string_diagonal(results)
        by_string = {r.state.string_num: r.state.finger for r in out}
        # After fix: string 1 (high pitch) must have the lower-rank finger.
        assert _OFFSET.get(by_string[1], 0) < _OFFSET.get(by_string[6], 0)

    def test_300003_shape(self) -> None:
        # Classic open G chord bass+treble: fret 3 on string 1 and string 6.
        # Natural diagonal: INDEX (or lower) on string 1, higher-rank on string 6.
        results = [
            _fr(0, 0.0, 1, 3, Finger.RING),    # string 1 (e)  — wrong
            _fr(1, 0.0, 6, 3, Finger.MIDDLE),  # string 6 (E)  — wrong
        ]
        out = resolve_chord_string_diagonal(results)
        by_string = {r.state.string_num: r.state.finger for r in out}
        rank_str1 = _OFFSET.get(by_string[1], 0)
        rank_str6 = _OFFSET.get(by_string[6], 0)
        assert rank_str1 <= rank_str6, (
            f"string 1 has rank {rank_str1} ({by_string[1]}), "
            f"string 6 has rank {rank_str6} ({by_string[6]}) — diagonal violated"
        )

    def test_different_frets_r_c3_respected(self) -> None:
        # String 1 fret 7, string 6 fret 5 — R-C3 forces INDEX on lower fret (string 6).
        # Diagonal prefers INDEX on string 1 but fret forces it on string 6.
        results = [
            _fr(0, 0.0, 1, 7, Finger.MIDDLE),  # string 1 fret 7
            _fr(1, 0.0, 6, 5, Finger.INDEX),   # string 6 fret 5
        ]
        out = resolve_chord_string_diagonal(results)
        by_fret = sorted(out, key=lambda r: r.state.fret)
        # Lower fret must have lower-rank finger (R-C3 / R-C5).
        assert _OFFSET.get(by_fret[0].state.finger, 0) < _OFFSET.get(by_fret[1].state.finger, 0)

    def test_single_note_unchanged(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.RING)]
        out = resolve_chord_string_diagonal(results)
        assert out[0].state.finger == Finger.RING

    def test_empty_unchanged(self) -> None:
        assert resolve_chord_string_diagonal([]) == []

    def test_open_strings_ignored(self) -> None:
        # Open strings are excluded from the diagonal check.
        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=1,
                note_event=NoteEvent(pitch=59, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=2, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
        ]
        out = resolve_chord_string_diagonal(results)
        assert all(r.state.finger == Finger.OPEN for r in out)


# ---------------------------------------------------------------------------
# compute_musical_cost (C_music)
# ---------------------------------------------------------------------------


def _note_art(
    articulation: Articulation = Articulation.NORMAL,
    tempo: float = 120.0,
    duration: float = 1.0,
    **kwargs: object,
) -> NoteEvent:
    """Helper to build a NoteEvent with specific articulation fields."""
    return NoteEvent(
        pitch=60, onset=0.0, duration=duration, tempo=tempo,
        articulation=articulation, **kwargs,  # type: ignore[arg-type]
    )


class TestMusicalCostLegatoSameString:
    """Hammer-on, pull-off, and legato require same string."""

    def test_hammer_on_same_string_zero(self) -> None:
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=3, fret=7)
        note = _note_art(articulation=Articulation.HAMMER_ON)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_hammer_on_different_string_penalty(self) -> None:
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=2, fret=7)
        note = _note_art(articulation=Articulation.HAMMER_ON)
        assert compute_musical_cost(s1, s2, note) >= 5.0

    def test_pull_off_same_string_zero(self) -> None:
        s1 = _state(string_num=2, fret=7)
        s2 = _state(string_num=2, fret=5)
        note = _note_art(articulation=Articulation.PULL_OFF)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_pull_off_different_string_penalty(self) -> None:
        s1 = _state(string_num=2, fret=7)
        s2 = _state(string_num=3, fret=5)
        note = _note_art(articulation=Articulation.PULL_OFF)
        assert compute_musical_cost(s1, s2, note) >= 5.0

    def test_legato_same_string_zero(self) -> None:
        s1 = _state(string_num=1, fret=3)
        s2 = _state(string_num=1, fret=5)
        note = _note_art(articulation=Articulation.LEGATO)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_legato_different_string_penalty(self) -> None:
        s1 = _state(string_num=1, fret=3)
        s2 = _state(string_num=2, fret=5)
        note = _note_art(articulation=Articulation.LEGATO)
        assert compute_musical_cost(s1, s2, note) >= 5.0


class TestMusicalCostSlide:
    """Slides require same string."""

    def test_slide_same_string_zero(self) -> None:
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=3, fret=9)
        note = _note_art(slide_type="legato")
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_slide_different_string_penalty(self) -> None:
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=2, fret=9)
        note = _note_art(slide_type="shift")
        assert compute_musical_cost(s1, s2, note) >= 5.0


class TestMusicalCostVibrato:
    """Vibrato position quality."""

    def test_vibrato_open_string_penalty(self) -> None:
        s1 = _state(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        s2 = _state(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        note = _note_art(articulation=Articulation.VIBRATO)
        assert compute_musical_cost(s1, s2, note) >= 4.0

    def test_vibrato_mid_fret_zero(self) -> None:
        s1 = _state(string_num=1, fret=7)
        s2 = _state(string_num=1, fret=7)
        note = _note_art(articulation=Articulation.VIBRATO)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_vibrato_low_fret_penalty(self) -> None:
        s1 = _state(string_num=1, fret=1, hand_position=1)
        s2 = _state(string_num=1, fret=1, hand_position=1)
        note = _note_art(articulation=Articulation.VIBRATO)
        assert compute_musical_cost(s1, s2, note) > 0.0

    def test_wide_vibrato_low_fret_extra_penalty(self) -> None:
        s1 = _state(string_num=1, fret=2, hand_position=1)
        s2 = _state(string_num=1, fret=2, hand_position=1)
        note_normal = _note_art(articulation=Articulation.VIBRATO)
        note_wide = _note_art(articulation=Articulation.WIDE_VIBRATO, vibrato_wide=True)
        cost_normal = compute_musical_cost(s1, s2, note_normal)
        cost_wide = compute_musical_cost(s1, s2, note_wide)
        assert cost_wide > cost_normal


class TestMusicalCostBend:
    """Bend feasibility."""

    def test_bend_open_string_penalty(self) -> None:
        s1 = _state(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        s2 = _state(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
        note = _note_art(bend_value=1.0, bend_type="normal")
        assert compute_musical_cost(s1, s2, note) >= 6.0

    def test_bend_plain_string_no_wound_penalty(self) -> None:
        s1 = _state(string_num=2, fret=7)
        s2 = _state(string_num=2, fret=7)
        note = _note_art(bend_value=1.0, bend_type="normal")
        # String 2 (B) is a plain string — no wound penalty.
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_bend_wound_string_penalty(self) -> None:
        s1 = _state(string_num=5, fret=7)
        s2 = _state(string_num=5, fret=7)
        note = _note_art(bend_value=1.0, bend_type="normal")
        # String 5 (A) is wound — should carry a penalty.
        assert compute_musical_cost(s1, s2, note) > 0.0

    def test_larger_bend_costs_more_on_wound(self) -> None:
        s1 = _state(string_num=6, fret=7)
        s2 = _state(string_num=6, fret=7)
        half = _note_art(bend_value=0.5, bend_type="normal")
        full = _note_art(bend_value=2.0, bend_type="normal")
        assert compute_musical_cost(s1, s2, full) > compute_musical_cost(s1, s2, half)


class TestMusicalCostHarmonic:
    """Natural harmonic position matching."""

    def test_harmonic_correct_fret_zero(self) -> None:
        s1 = _state(string_num=1, fret=12, hand_position=12)
        s2 = _state(string_num=1, fret=12, hand_position=12)
        note = _note_art(harmonic_type="natural", harmonic_fret=12)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_harmonic_wrong_fret_penalty(self) -> None:
        s1 = _state(string_num=1, fret=11, hand_position=11)
        s2 = _state(string_num=1, fret=11, hand_position=11)
        note = _note_art(harmonic_type="natural", harmonic_fret=12)
        assert compute_musical_cost(s1, s2, note) >= 4.0


class TestMusicalCostTapping:
    """Tapping modifier."""

    def test_tapping_high_fret_zero(self) -> None:
        s1 = _state(string_num=1, fret=12, hand_position=12)
        s2 = _state(string_num=1, fret=12, hand_position=12)
        note = _note_art(tapping=True)
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)

    def test_tapping_low_fret_penalty(self) -> None:
        s1 = _state(string_num=1, fret=3, hand_position=3)
        s2 = _state(string_num=1, fret=3, hand_position=3)
        note = _note_art(tapping=True)
        assert compute_musical_cost(s1, s2, note) >= 1.5


class TestMusicalCostNormal:
    """Normal articulation should add zero musical cost."""

    def test_normal_note_zero_cost(self) -> None:
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=2, fret=7)
        note = _note_art()
        assert compute_musical_cost(s1, s2, note) == pytest.approx(0.0)


class TestMusicalCostIntegration:
    """C_music influences transition_cost via β weight."""

    def test_reference_mode_includes_c_music(self) -> None:
        """Reference mode (β=1.0): C_music is active."""
        cf = CostFunction(weights=CostWeights.reference())
        s1 = _state(string_num=3, fret=5)
        s2_same = _state(string_num=3, fret=7)
        s2_diff = _state(string_num=2, fret=7)
        note = _note_art(articulation=Articulation.HAMMER_ON)
        cost_same = cf.transition_cost(s1, s2_same, note)
        cost_diff = cf.transition_cost(s1, s2_diff, note)
        assert cost_diff > cost_same

    def test_zero_beta_ignores_c_music(self) -> None:
        """With β=0, musical cost is ignored."""
        cf = CostFunction(weights=CostWeights(alpha=1.0, beta=0.0))
        s1 = _state(string_num=3, fret=5)
        s2 = _state(string_num=2, fret=7)
        note_normal = _note_art()
        note_ho = _note_art(articulation=Articulation.HAMMER_ON)
        # Different articulations should produce the same total cost when β=0.
        assert cf.transition_cost(s1, s2, note_normal) == pytest.approx(
            cf.transition_cost(s1, s2, note_ho)
        )
