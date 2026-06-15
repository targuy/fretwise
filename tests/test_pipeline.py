"""Tests for fretwise.pipeline — voice-aware pipeline orchestration."""

from __future__ import annotations

from fretwise.models import (
    Articulation,
    Dynamic,
    Finger,
    FingeringResult,
    FingeringState,
    NoteEvent,
)
from fretwise.pipeline import run_pipeline_with_guard_report, split_by_voice


def _note(pitch: int, onset: float, voice: int | None = None) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=voice,
    )


class TestSplitByVoice:
    def test_split_by_voice_single_voice(self) -> None:
        events = [_note(60, 0.0, 0), _note(62, 1.0, 0), _note(64, 2.0, 0)]
        result = split_by_voice(events)
        assert set(result.keys()) == {0}
        assert len(result[0]) == 3

    def test_split_by_voice_two_voices(self) -> None:
        events = [_note(60, 0.0, 0), _note(55, 0.0, 1), _note(62, 1.0, 0)]
        result = split_by_voice(events)
        assert set(result.keys()) == {0, 1}
        assert len(result[0]) == 2
        assert len(result[1]) == 1

    def test_split_by_voice_none_goes_to_zero(self) -> None:
        events = [_note(60, 0.0, None), _note(62, 1.0, 0)]
        result = split_by_voice(events)
        assert set(result.keys()) == {0}
        assert len(result[0]) == 2

    def test_split_by_voice_empty(self) -> None:
        assert split_by_voice([]) == {}

    def test_split_by_voice_preserves_order(self) -> None:
        events = [_note(60, 0.0, 1), _note(62, 1.0, 1), _note(55, 0.0, 0)]
        result = split_by_voice(events)
        assert result[1][0].pitch == 60
        assert result[1][1].pitch == 62
        assert result[0][0].pitch == 55


class _StubGenerator:
    def states_for_sequence(self, notes: list[NoteEvent]) -> list[list[FingeringState]]:
        return [[FingeringState(3, 5, Finger.INDEX, 5)] for _ in notes]


class _StubOptimizer:
    cost_fn = None  # public API expected by pipeline

    def set_segment_anchors(self, anchors: list) -> None:  # noqa: ANN001
        pass

    def clear_segment_anchors(self) -> None:
        pass

    def solve(
        self,
        events: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[FingeringResult]:
        return [
            FingeringResult(
                note_id=index,
                note_event=event,
                state=state_lists[index][0],
                cost=0.0,
            )
            for index, event in enumerate(events)
        ]


class _ChordGenerator:
    def states_for_sequence(self, notes: list[NoteEvent]) -> list[list[FingeringState]]:
        return [
            [FingeringState(1, 3, Finger.RING, 1)],
            [FingeringState(2, 3, Finger.RING, 1)],
        ]


class _BadChordOptimizer:
    cost_fn = None  # public API expected by pipeline

    def set_segment_anchors(self, anchors: list) -> None:  # noqa: ANN001
        pass

    def clear_segment_anchors(self) -> None:
        pass

    def solve(
        self,
        events: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[FingeringResult]:
        return [
            FingeringResult(
                note_id=index,
                note_event=event,
                state=state_lists[index][0],
                cost=0.0,
            )
            for index, event in enumerate(events)
        ]


def test_run_pipeline_with_guard_report_preserves_results_and_stats() -> None:
    events = [_note(60, 0.0, 0)]

    payload = run_pipeline_with_guard_report(
        events,
        _StubGenerator(),  # type: ignore[arg-type]
        _StubOptimizer(),  # type: ignore[arg-type]
    )

    assert len(payload.results) == 1
    assert payload.stats["parsed"] == 1
    assert payload.biomechanical_report.checked_notes == 1
    assert payload.biomechanical_report.is_clean


def test_run_pipeline_final_chord_guards_repair_duplicate_finger() -> None:
    events = [
        _note(67, 0.0, 0),  # string 1, fret 3
        _note(62, 0.0, 0),  # string 2, fret 3
    ]

    payload = run_pipeline_with_guard_report(
        events,
        _ChordGenerator(),  # type: ignore[arg-type]
        _BadChordOptimizer(),  # type: ignore[arg-type]
    )

    assert [result.state.finger for result in payload.results] == [Finger.INDEX, Finger.INDEX]
    assert payload.biomechanical_report.is_clean
