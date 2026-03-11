"""Tests for fretwise.models — NoteEvent, FingeringState, FingeringResult."""

from __future__ import annotations

import pytest

from fretwise.models import (
    Articulation,
    Dynamic,
    Finger,
    FingeringResult,
    FingeringState,
    NoteEvent,
)

# ---------------------------------------------------------------------------
# NoteEvent
# ---------------------------------------------------------------------------


class TestNoteEvent:
    def test_required_fields(self) -> None:
        note = NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0)
        assert note.pitch == 60
        assert note.onset == 0.0
        assert note.duration == 1.0
        assert note.tempo == 120.0

    def test_default_articulation_is_normal(self) -> None:
        note = NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0)
        assert note.articulation == Articulation.NORMAL

    def test_default_dynamic_is_mf(self) -> None:
        note = NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0)
        assert note.dynamic == Dynamic.MF

    def test_default_hints_are_none(self) -> None:
        note = NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0)
        assert note.string_hint is None
        assert note.fret_hint is None

    def test_explicit_articulation(self) -> None:
        note = NoteEvent(
            pitch=60, onset=0.0, duration=1.0, tempo=120.0,
            articulation=Articulation.HAMMER_ON,
        )
        assert note.articulation == Articulation.HAMMER_ON

    def test_string_and_fret_hints(self) -> None:
        note = NoteEvent(
            pitch=64, onset=2.0, duration=0.5, tempo=120.0,
            string_hint=1, fret_hint=0,
        )
        assert note.string_hint == 1
        assert note.fret_hint == 0

    @pytest.mark.parametrize("pitch", [0, 64, 127])
    def test_valid_pitch_range(self, pitch: int) -> None:
        note = NoteEvent(pitch=pitch, onset=0.0, duration=1.0, tempo=120.0)
        assert note.pitch == pitch


# ---------------------------------------------------------------------------
# FingeringState
# ---------------------------------------------------------------------------


class TestFingeringState:
    def test_all_fields(self) -> None:
        state = FingeringState(
            string_num=1, fret=5, finger=Finger.INDEX, hand_position=5
        )
        assert state.string_num == 1
        assert state.fret == 5
        assert state.finger == Finger.INDEX
        assert state.hand_position == 5

    def test_open_string_state(self) -> None:
        state = FingeringState(
            string_num=6, fret=0, finger=Finger.OPEN, hand_position=1
        )
        assert state.fret == 0
        assert state.finger == Finger.OPEN

    @pytest.mark.parametrize(
        "string_num, fret, finger, hand_position",
        [
            (1, 0, Finger.OPEN, 1),
            (3, 7, Finger.RING, 5),
            (6, 12, Finger.PINKY, 9),
        ],
    )
    def test_various_states(
        self,
        string_num: int,
        fret: int,
        finger: Finger,
        hand_position: int,
    ) -> None:
        state = FingeringState(
            string_num=string_num,
            fret=fret,
            finger=finger,
            hand_position=hand_position,
        )
        assert state.string_num == string_num
        assert state.fret == fret
        assert state.finger == finger
        assert state.hand_position == hand_position


# ---------------------------------------------------------------------------
# FingeringResult
# ---------------------------------------------------------------------------


class TestFingeringResult:
    def _make_note(self) -> NoteEvent:
        return NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0)

    def _make_state(self) -> FingeringState:
        return FingeringState(string_num=3, fret=5, finger=Finger.MIDDLE, hand_position=4)

    def test_required_fields(self) -> None:
        note = self._make_note()
        state = self._make_state()
        result = FingeringResult(note_id=0, note_event=note, state=state, cost=2.5)
        assert result.note_id == 0
        assert result.note_event is note
        assert result.state is state
        assert result.cost == 2.5

    def test_default_alternatives_empty(self) -> None:
        result = FingeringResult(
            note_id=0,
            note_event=self._make_note(),
            state=self._make_state(),
            cost=1.0,
        )
        assert result.alternatives == []

    def test_alternatives_not_shared_between_instances(self) -> None:
        r1 = FingeringResult(
            note_id=0, note_event=self._make_note(), state=self._make_state(), cost=1.0
        )
        r2 = FingeringResult(
            note_id=1, note_event=self._make_note(), state=self._make_state(), cost=2.0
        )
        alt_state = FingeringState(string_num=2, fret=5, finger=Finger.INDEX, hand_position=5)
        r1.alternatives.append((alt_state, 3.0))
        assert r2.alternatives == []

    def test_with_alternatives(self) -> None:
        state = self._make_state()
        alt = FingeringState(string_num=2, fret=5, finger=Finger.INDEX, hand_position=5)
        result = FingeringResult(
            note_id=0,
            note_event=self._make_note(),
            state=state,
            cost=1.0,
            alternatives=[(alt, 2.0)],
        )
        assert len(result.alternatives) == 1
        assert result.alternatives[0][1] == 2.0


# ---------------------------------------------------------------------------
# Enum values
# ---------------------------------------------------------------------------


class TestEnums:
    def test_articulation_values(self) -> None:
        assert Articulation.NORMAL.value == "normal"
        assert Articulation.HAMMER_ON.value == "hammer_on"
        assert Articulation.PULL_OFF.value == "pull_off"
        assert Articulation.BEND.value == "bend"
        assert Articulation.VIBRATO.value == "vibrato"
        assert Articulation.SLIDE.value == "slide"

    def test_dynamic_values(self) -> None:
        assert Dynamic.PP.value == "pp"
        assert Dynamic.MF.value == "mf"
        assert Dynamic.FF.value == "ff"

    def test_finger_values(self) -> None:
        assert Finger.OPEN.value == "open"
        assert Finger.INDEX.value == "index"
        assert Finger.MIDDLE.value == "middle"
        assert Finger.RING.value == "ring"
        assert Finger.PINKY.value == "pinky"
