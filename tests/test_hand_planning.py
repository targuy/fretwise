"""Autonomous musical regressions from the September 2026 Notion studies."""

from __future__ import annotations

from dataclasses import replace

import pytest

from fretwise.biomechanics import validate_fingering_results
from fretwise.generator import GeneratorConfig, StateGenerator
from fretwise.hand_planning import plan_hand_configurations
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.pipeline import run_pipeline_with_guard_report
from fretwise.scoring import CostFunction

_TUNING = (64, 59, 55, 50, 45, 40)


def _note(
    string: int, fret: int, onset: float = 0.0, duration: float = 1.0,
    *, voice: int = 0, finger: Finger | None = None, let_ring: bool = False,
) -> NoteEvent:
    return NoteEvent(
        pitch=_TUNING[string - 1] + fret, onset=onset, duration=duration, tempo=120,
        string_hint=string, fret_hint=fret, voice_hint=voice,
        source_finger=finger, let_ring=let_ring,
    )


def _result(note_id: int, note: NoteEvent, finger: Finger) -> FingeringResult:
    return FingeringResult(
        note_id, note,
        FingeringState(note.string_hint or 1, note.fret_hint or 0, finger, 1), 0.0,
    )


def test_generator_accepts_e_major_ring_at_second_fret() -> None:
    states = StateGenerator().states_for(_note(4, 2))
    assert any(state.finger == Finger.RING and state.hand_position == 1 for state in states)


def test_e_major_source_fingers_survive_all_pipeline_heuristics() -> None:
    notes = [
        _note(6, 0), _note(5, 2, finger=Finger.MIDDLE),
        _note(4, 2, finger=Finger.RING), _note(3, 1, finger=Finger.INDEX),
        _note(2, 0), _note(1, 0),
    ]
    payload = run_pipeline_with_guard_report(
        notes, StateGenerator(GeneratorConfig(source_finger_policy="lock")),
        ViterbiOptimizer(CostFunction()),
    )
    assert payload.biomechanical_report.fatal_count == 0
    assert [result.state.finger for result in payload.results] == [
        Finger.OPEN, Finger.MIDDLE, Finger.RING, Finger.INDEX, Finger.OPEN, Finger.OPEN,
    ]


def test_invalid_source_position_does_not_silently_rearrange() -> None:
    assert StateGenerator().states_for(_note(2, 30)) == []


def test_rearrangement_is_explicit_and_preserves_pitch() -> None:
    note = _note(2, 5)
    faithful = StateGenerator().states_for(note)
    rearranged = StateGenerator(GeneratorConfig(position_mode="rearrange")).states_for(note)
    assert {(state.string_num, state.fret) for state in faithful} == {(2, 5)}
    assert len({(state.string_num, state.fret) for state in rearranged}) > 1
    assert all(_TUNING[state.string_num - 1] + state.fret == note.pitch for state in rearranged)


def test_source_annotation_is_preference_by_default_and_lock_on_request() -> None:
    note = _note(3, 5, finger=Finger.RING)
    preferred = StateGenerator().states_for(note)
    locked = StateGenerator(GeneratorConfig(source_finger_policy="lock")).states_for(note)
    assert preferred[0].finger == Finger.RING
    assert any(state.finger == Finger.INDEX for state in preferred)
    assert all(state.finger == Finger.RING for state in locked)


def test_sustain_validator_checks_a_held_note_across_intervening_attacks() -> None:
    results = [
        _result(0, _note(4, 2, duration=4, voice=1), Finger.RING),
        _result(1, _note(2, 1, onset=1), Finger.INDEX),
        _result(2, _note(1, 3, onset=2), Finger.RING),
    ]
    report = validate_fingering_results(results)
    assert any(v.code == "BIO-TRANS-002" and v.note_ids == (0, 2) for v in report.violations)


def test_joint_planner_repairs_sustain_without_moving_positions() -> None:
    notes = [_note(4, 2, duration=4, voice=1), _note(2, 1, 1), _note(1, 3, 2)]
    results = [_result(i, note, f) for i, (note, f) in enumerate(zip(
        notes, (Finger.RING, Finger.INDEX, Finger.RING),
    ))]
    generator = StateGenerator()
    candidates = {id(note): generator.states_for(note) for note in notes}
    planned = plan_hand_configurations(results, candidates, CostFunction())
    assert planned.status == "valid"
    assert planned.changed_notes > 0
    assert validate_fingering_results(planned.results).fatal_count == 0
    assert [(r.state.string_num, r.state.fret) for r in planned.results] == [(4, 2), (2, 1), (1, 3)]
    for alternative in planned.alternatives:
        assert len(alternative) == len(notes)
        candidate_results = [replace(r, state=s) for r, s in zip(results, alternative)]
        assert validate_fingering_results(candidate_results).fatal_count == 0


def test_conflicting_source_locks_remain_visible_and_never_rewritten() -> None:
    notes = [
        _note(4, 2, duration=4, voice=1, finger=Finger.INDEX),
        _note(1, 3, onset=2, finger=Finger.INDEX),
    ]
    payload = run_pipeline_with_guard_report(
        notes, StateGenerator(GeneratorConfig(source_finger_policy="lock")),
        ViterbiOptimizer(CostFunction()),
    )
    assert len(payload.results) == len(notes)
    assert all(result.state.finger == Finger.INDEX for result in payload.results)
    assert payload.stats["hand_plan_search_failed"] == 1
    assert payload.biomechanical_report.fatal_count > 0


def test_let_ring_extends_past_notated_duration_until_rearticulation() -> None:
    results = [
        _result(0, _note(4, 2, duration=0.25, voice=1, let_ring=True), Finger.RING),
        _result(1, _note(1, 3, onset=2), Finger.RING),
    ]
    assert "BIO-TRANS-002" in {v.code for v in validate_fingering_results(results).violations}
    results.insert(1, _result(2, _note(4, 0, onset=1, voice=1), Finger.OPEN))
    assert "BIO-TRANS-002" not in {
        v.code for v in validate_fingering_results(results).violations
    }


def test_barre_preserves_sounding_open_string_inside_its_span() -> None:
    results = [
        _result(0, _note(1, 1), Finger.INDEX),
        _result(1, _note(2, 0), Finger.OPEN),
        _result(2, _note(3, 1), Finger.INDEX),
    ]
    assert "BIO-CONTACT-002" in {v.code for v in validate_fingering_results(results).violations}


def test_barre_may_pass_behind_higher_note() -> None:
    results = [
        _result(0, _note(1, 1), Finger.INDEX),
        _result(1, _note(2, 2), Finger.MIDDLE),
        _result(2, _note(3, 1), Finger.INDEX),
    ]
    assert validate_fingering_results(results).fatal_count == 0


def test_different_voices_cannot_sustain_two_pitches_on_same_string() -> None:
    results = [
        _result(0, _note(1, 3, duration=4, voice=1), Finger.RING),
        _result(1, _note(1, 1, onset=1), Finger.INDEX),
    ]
    assert "BIO-SUSTAIN-001" in {v.code for v in validate_fingering_results(results).violations}


def test_cross_voice_unison_keeps_both_source_identities_and_durations() -> None:
    notes = [_note(2, 1, duration=4, voice=1), _note(2, 1, duration=1)]
    notes[0].source_note_id, notes[1].source_note_id = "held", "short"
    payload = run_pipeline_with_guard_report(
        notes, StateGenerator(), ViterbiOptimizer(CostFunction()),
    )
    assert {r.note_event.source_note_id for r in payload.results} == {"held", "short"}
    assert {r.note_event.duration for r in payload.results} == {1, 4}
    assert payload.biomechanical_report.fatal_count == 0


def test_shared_cross_voice_unison_accepts_a_non_index_finger() -> None:
    results = [
        _result(0, _note(3, 3, duration=4, voice=1), Finger.RING),
        _result(1, _note(3, 3), Finger.RING),
    ]
    assert validate_fingering_results(results).fatal_count == 0


def test_non_adjacent_released_note_does_not_report_sustain_conflict() -> None:
    results = [
        _result(0, _note(4, 2, duration=2, voice=1), Finger.RING),
        _result(1, _note(2, 1, onset=1), Finger.INDEX),
        _result(2, _note(1, 3, onset=2), Finger.RING),
    ]
    assert "BIO-TRANS-002" not in {v.code for v in validate_fingering_results(results).violations}


def test_unplayable_pitch_without_source_position_is_not_dropped() -> None:
    with pytest.raises(ValueError, match="source note was not discarded"):
        run_pipeline_with_guard_report(
            [NoteEvent(120, 0, 1, 120)], StateGenerator(), ViterbiOptimizer(CostFunction()),
        )


def test_pipeline_costs_match_final_states_and_obsolete_alternatives_are_cleared() -> None:
    notes = [_note(4, 2, finger=Finger.RING), _note(2, 1, onset=1, finger=Finger.INDEX)]
    cost = CostFunction()
    payload = run_pipeline_with_guard_report(
        notes, StateGenerator(GeneratorConfig(source_finger_policy="lock")), ViterbiOptimizer(cost),
    )
    first, second = payload.results
    expected = cost.emission_cost(first.state) + cost.transition_cost(
        first.state, second.state, second.note_event,
    )
    assert second.cost == pytest.approx(expected)
    assert first.alternatives == second.alternatives == []


def test_tie_continuation_keeps_contact_across_measure_boundary() -> None:
    first = _note(3, 5, finger=Finger.MIDDLE)
    first.measure_index = 1
    continuation = replace(first, onset=1, is_tie_dest=True, measure_index=2, source_finger=None)
    results = [_result(0, first, Finger.MIDDLE), _result(1, continuation, Finger.INDEX)]
    assert "BIO-TIE-001" in {v.code for v in validate_fingering_results(results).violations}
    generator = StateGenerator(GeneratorConfig(source_finger_policy="lock"))
    candidates = {id(note): generator.states_for(note) for note in (first, continuation)}
    planned = plan_hand_configurations(results, candidates, CostFunction())
    assert planned.status == "valid"
    assert all(result.state.finger == Finger.MIDDLE for result in planned.results)
