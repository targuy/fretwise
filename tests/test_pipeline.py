"""Tests for fretwise.pipeline — voice-aware pipeline orchestration."""

from __future__ import annotations

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.pipeline import split_by_voice


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
