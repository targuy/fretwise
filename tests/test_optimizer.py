"""Tests for fretwise.optimizer — ViterbiOptimizer."""

from __future__ import annotations

import math
from unittest.mock import MagicMock

import pytest

from fretwise.models import Finger, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.scoring import CostFunction


def _note(pitch: int = 60, onset: float = 0.0) -> NoteEvent:
    return NoteEvent(pitch=pitch, onset=onset, duration=1.0, tempo=120.0)


def _state(string_num: int = 3, fret: int = 5, hand_position: int = 5) -> FingeringState:
    return FingeringState(
        string_num=string_num,
        fret=fret,
        finger=Finger.INDEX,
        hand_position=hand_position,
    )


def _make_optimizer() -> ViterbiOptimizer:
    return ViterbiOptimizer(CostFunction())


class TestViterbiOptimizerEdgeCases:
    def test_empty_sequence_returns_empty(self) -> None:
        opt = _make_optimizer()
        assert opt.solve([], []) == []

    def test_notes_and_states_length_mismatch_raises(self) -> None:
        opt = _make_optimizer()
        with pytest.raises(ValueError, match="same length"):
            opt.solve([_note()], [])

    def test_empty_state_list_raises(self) -> None:
        opt = _make_optimizer()
        with pytest.raises(ValueError, match="empty"):
            opt.solve([_note()], [[]])

    def test_single_note_single_state(self) -> None:
        opt = _make_optimizer()
        state = _state()
        results = opt.solve([_note()], [[state]])
        assert len(results) == 1
        assert results[0].state is state
        assert results[0].note_id == 0
        assert results[0].cost >= 0.0

    def test_single_note_multiple_states(self) -> None:
        opt = _make_optimizer()
        states = [_state(fret=5, hand_position=5), _state(fret=7, hand_position=7)]
        results = opt.solve([_note()], [states])
        assert len(results) == 1
        assert results[0].state in states


class TestViterbiOptimizerCorrectness:
    def test_two_notes_returns_two_results(self) -> None:
        opt = _make_optimizer()
        notes = [_note(onset=0.0), _note(onset=1.0)]
        state_lists = [[_state()], [_state()]]
        results = opt.solve(notes, state_lists)
        assert len(results) == 2

    def test_note_ids_sequential(self) -> None:
        opt = _make_optimizer()
        n = 5
        notes = [_note(onset=float(i)) for i in range(n)]
        state_lists = [[_state()]] * n
        results = opt.solve(notes, state_lists)
        assert [r.note_id for r in results] == list(range(n))

    def test_prefers_no_shift_path(self) -> None:
        """Viterbi should prefer a sequence with no position shift."""
        opt = _make_optimizer()
        notes = [_note(onset=0.0), _note(onset=1.0)]

        # State A: hand_position=5, State B: hand_position=12
        state_a = FingeringState(string_num=3, fret=5, finger=Finger.INDEX, hand_position=5)
        state_b = FingeringState(string_num=3, fret=12, finger=Finger.INDEX, hand_position=12)

        # Both notes can be played at position 5 or position 12.
        # If note 1 is played at position 5, note 2 at position 5 → no shift.
        # If note 1 is played at position 5, note 2 at position 12 → large shift.
        # The optimizer should prefer the consistent position.
        state_lists = [[state_a, state_b], [state_a, state_b]]
        results = opt.solve(notes, state_lists)
        # Both notes should be at the same hand position.
        assert results[0].state.hand_position == results[1].state.hand_position

    def test_alternatives_sorted_by_cost(self) -> None:
        """Alternatives must be sorted ascending by cost."""
        opt = _make_optimizer()
        notes = [_note()]
        states = [
            _state(fret=1, hand_position=1),
            _state(fret=10, hand_position=10),
            _state(fret=20, hand_position=20),
        ]
        results = opt.solve(notes, [states])
        if results[0].alternatives:
            costs = [c for _, c in results[0].alternatives]
            assert costs == sorted(costs)

    def test_result_cost_is_finite(self) -> None:
        opt = _make_optimizer()
        notes = [_note(onset=float(i)) for i in range(3)]
        state_lists = [
            [_state(hand_position=5)],
            [_state(hand_position=5)],
            [_state(hand_position=5)],
        ]
        results = opt.solve(notes, state_lists)
        for r in results:
            assert math.isfinite(r.cost)

    def test_longer_sequence(self) -> None:
        """Viterbi should handle a longer sequence without errors."""
        opt = _make_optimizer()
        n = 50
        notes = [_note(pitch=60 + i % 12, onset=float(i)) for i in range(n)]
        # Provide 3 state options per note
        state_lists = [
            [
                _state(fret=i % 5 + 1, hand_position=i % 5 + 1),
                _state(string_num=2, fret=i % 7 + 1, hand_position=i % 7 + 1),
                _state(string_num=4, fret=i % 3 + 1, hand_position=i % 3 + 1),
            ]
            for i in range(n)
        ]
        results = opt.solve(notes, state_lists)
        assert len(results) == n
        for r in results:
            assert math.isfinite(r.cost)
            assert r.cost >= 0.0


class TestViterbiOptimizerWithMockCost:
    """Use a mock cost function to verify exact path selection."""

    def test_selects_minimum_cost_path(self) -> None:
        """Given a controlled cost matrix, verify the path chosen is optimal."""
        # Two notes, two states each.
        # State layout:
        #   note 0: state_A (emission=0), state_B (emission=10)
        #   note 1: state_C, state_D
        # Transition costs:
        #   A→C = 1, A→D = 100
        #   B→C = 100, B→D = 1
        # Optimal path: A→C with total cost 0+1=1

        state_a = _state(fret=1, hand_position=1)
        state_b = _state(fret=10, hand_position=10)
        state_c = _state(fret=2, hand_position=2)
        state_d = _state(fret=20, hand_position=20)

        mock_cost = MagicMock()
        mock_cost.emission_cost.side_effect = lambda s: (
            0.0 if s is state_a else 10.0
        )

        def transition(s1: FingeringState, s2: FingeringState, note: NoteEvent) -> float:
            if s1 is state_a and s2 is state_c:
                return 1.0
            if s1 is state_a and s2 is state_d:
                return 100.0
            if s1 is state_b and s2 is state_c:
                return 100.0
            if s1 is state_b and s2 is state_d:
                return 1.0
            return 50.0

        mock_cost.transition_cost.side_effect = transition

        opt = ViterbiOptimizer(mock_cost)
        notes = [_note(onset=0.0), _note(onset=1.0)]
        state_lists = [[state_a, state_b], [state_c, state_d]]
        results = opt.solve(notes, state_lists)

        assert results[0].state is state_a
        assert results[1].state is state_c
        assert results[1].cost == pytest.approx(1.0)
