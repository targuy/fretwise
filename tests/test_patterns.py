"""Tests for fretwise.patterns — PatternMatcher (Sprint 1 stub)."""

from __future__ import annotations

from fretwise.models import Finger, FingeringState, NoteEvent
from fretwise.patterns import PatternMatcher


def _note(pitch: int = 60) -> NoteEvent:
    return NoteEvent(pitch=pitch, onset=0.0, duration=1.0, tempo=120.0)


def _state(string_num: int = 3, fret: int = 5) -> FingeringState:
    return FingeringState(
        string_num=string_num, fret=fret, finger=Finger.INDEX, hand_position=fret
    )


class TestPatternMatcherStub:
    def setup_method(self) -> None:
        self.matcher = PatternMatcher()

    def test_returns_same_state_lists_unchanged(self) -> None:
        notes = [_note(60), _note(62)]
        states = [[_state(3, 5)], [_state(3, 7), _state(2, 8)]]
        result = self.matcher.apply(notes, states)
        assert result is states  # same object (stub returns input unchanged)

    def test_empty_sequence(self) -> None:
        result = self.matcher.apply([], [])
        assert result == []

    def test_single_note(self) -> None:
        notes = [_note()]
        state_list = [[_state()]]
        result = self.matcher.apply(notes, state_list)
        assert result == state_list

    def test_does_not_modify_states(self) -> None:
        notes = [_note()]
        original = [[_state(3, 5), _state(2, 10)]]
        result = self.matcher.apply(notes, original)
        assert len(result[0]) == 2
