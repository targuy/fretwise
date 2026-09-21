"""Real movement cannot disappear inside a segment or through an open string."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

import pytest

from fretwise.generator import StateGenerator
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import (
    CostFunction,
    CostWeights,
    cost_position_shift,
    cost_position_shift_segment_aware,
    cost_stretch,
)


def _state(fret: int, finger: Finger, hp: int, string: int = 3) -> FingeringState:
    return FingeringState(string_num=string, fret=fret, finger=finger, hand_position=hp)


def _note() -> NoteEvent:
    return NoteEvent(pitch=64, onset=.25, duration=.25, tempo=120)


@pytest.mark.parametrize("anchors", [(2, 2), (2, 3)])
def test_segment_anchor_cannot_hide_larger_actual_open_shift(anchors: tuple[int, int]) -> None:
    fretted = _state(4, Finger.INDEX, 4)
    opened = _state(0, Finger.OPEN, 1, string=1)
    # Three frets in 0.125 s, discounted to 35% while an open string sounds.
    expected = .35 * 3 / .125
    assert cost_position_shift(fretted, opened, _note()) == pytest.approx(expected)
    assert cost_position_shift_segment_aware(
        fretted, opened, _note(), *anchors,
    ) == pytest.approx(expected)


def test_open_string_cannot_split_shift_into_two_free_tolerated_steps() -> None:
    before = _state(4, Finger.INDEX, 3)
    during = _state(0, Finger.OPEN, 2, string=1)
    after = _state(2, Finger.MIDDLE, 1, string=2)
    incoming = cost_position_shift(before, during, _note())
    outgoing = cost_position_shift(during, after, _note())
    assert incoming == pytest.approx(.35 / .125)
    assert outgoing == pytest.approx(.35 / .125)
    assert incoming + outgoing == pytest.approx(.35 * 2 / .125)


def test_fretted_offset_tolerance_is_preserved() -> None:
    before = _state(5, Finger.INDEX, 5)
    after = _state(7, Finger.MIDDLE, 6)
    assert cost_position_shift(before, after, _note()) == 0
    assert cost_position_shift_segment_aware(before, after, _note(), 5, 5) == 0


def test_initial_stretch_is_charged_with_injected_mechanical_weight() -> None:
    stretched = _state(4, Finger.RING, 1)
    natural = _state(4, Finger.RING, 2)
    zero = CostFunction(weights=CostWeights(alpha=0))
    doubled = CostFunction(weights=CostWeights(alpha=2))
    assert zero.emission_cost(stretched) == zero.emission_cost(natural)
    assert doubled.emission_cost(stretched) - doubled.emission_cost(natural) == pytest.approx(
        2 * cost_stretch(stretched, stretched),
    )
    cost = CostFunction()
    assert cost.emission_cost(_state(4, Finger.PINKY, 1)) < cost.emission_cost(stretched)
    assert cost.emission_cost(_state(0, Finger.OPEN, 8)) == 0


def _africa_notes(*, let_ring: bool = False, transpose: int = 0) -> list[NoteEvent]:
    """Synthetic 18-note rhythm/string/fret reproduction; no private GP fixture."""
    notes = []
    for index in range(18):
        string, fret, pitch = ((3, 4, 59), (1, 0, 64), (2, 2, 61))[index % 3]
        if fret:
            fret += transpose
            pitch += transpose
        notes.append(NoteEvent(
            pitch=pitch, onset=19.25 + index * .25,
            duration=.25 if index < 17 else .5, tempo=120,
            string_hint=string, fret_hint=fret,
            measure_index=5 if index < 3 else 6,
            palm_muted=not let_ring, let_ring=let_ring,
        ))
    return notes


class _RecordingOptimizer(ViterbiOptimizer):
    """Capture M5's path before later resolvers can mask an initial-cost defect."""

    def solve(
        self, notes: list[NoteEvent], state_lists: list[list[FingeringState]],
    ) -> list[FingeringResult]:
        results = super().solve(notes, state_lists)
        self.initial_states = [replace(result.state) for result in results]
        return results


def _player_model() -> object:
    from fretwise.ml import LearnedPlayerCost

    models = Path(os.environ.get("FRETWISE_TEST_MODEL_DIR", "data/models"))
    model = models / "transition_cost_v3.onnx"
    spec = models / "transition_cost_v3_spec.json"
    if not model.is_file() or not spec.is_file():
        pytest.skip("Optional learned transition-cost bundle not available")
    pytest.importorskip("onnxruntime")
    return LearnedPlayerCost(str(model), str(spec))


@pytest.mark.parametrize("learned", [False, True])
@pytest.mark.parametrize("let_ring", [False, True])
def test_africa_pattern_starts_in_same_natural_hand_shape_as_repetitions(
    learned: bool, let_ring: bool,
) -> None:
    events = _africa_notes(let_ring=let_ring)
    cost = CostFunction(
        weights=CostWeights.performance(),
        player_cost_model=_player_model() if learned else None,
    )
    optimizer = _RecordingOptimizer(cost)
    results, stats = run_pipeline(events, StateGenerator(), optimizer, PatternMatcher())

    # Both natural shapes are admissible. The active learned cost prefers hp1;
    # pure reference biomechanics prefers ring/index at hp2, without a shift.
    expected = (
        [Finger.PINKY, Finger.OPEN, Finger.MIDDLE] if learned
        else [Finger.RING, Finger.OPEN, Finger.INDEX]
    ) * 6
    expected_hp = 1 if learned else 2
    assert [state.finger for state in optimizer.initial_states] == expected
    assert [result.state.finger for result in results] == expected
    assert {state.hand_position for state in optimizer.initial_states} == {expected_hp}
    assert {result.state.hand_position for result in results} == {expected_hp}
    assert [result.note_event for result in results] == events
    assert [(result.state.string_num, result.state.fret) for result in results] == [
        (note.string_hint, note.fret_hint) for note in events
    ]
    assert stats["hard_constraint_violations"] == 0
    assert stats["hand_plan_search_failed"] == 0
    assert stats["dropped"] == 0


def test_open_strings_retain_high_hand_position_instead_of_resetting_to_one() -> None:
    events = _africa_notes(transpose=6)
    results, stats = run_pipeline(
        events, StateGenerator(), ViterbiOptimizer(CostFunction()), PatternMatcher(),
    )
    positions = {result.state.hand_position for result in results}
    assert len(positions) == 1
    assert next(iter(positions)) > 1
    assert stats["hard_constraint_violations"] == 0


def test_open_strings_still_allow_a_required_real_shift() -> None:
    notes = [replace(_note(), onset=i * .25) for i in range(3)]
    before = _state(4, Finger.PINKY, 1)
    after = _state(12, Finger.INDEX, 12)
    choices = [[before], [_state(0, Finger.OPEN, hp) for hp in range(1, 13)], [after]]
    cost = CostFunction()
    optimizer = ViterbiOptimizer(cost)
    optimizer.set_segment_anchors([2, 2, 2])
    results = optimizer.solve(notes, choices)
    optimizer.clear_segment_anchors()
    assert results[0].state == before
    assert results[-1].state == after
    middle = results[1].state
    movement = cost_position_shift(before, middle, notes[1])
    movement += cost_position_shift(middle, after, notes[2])
    assert movement == pytest.approx(.35 * 11 / .125)
