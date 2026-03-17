"""Tests for fretwise.parser.midi_adapter — MidiAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from fretwise.models import Articulation, Dynamic
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.midi_adapter import (
    MidiAdapter,
    _seconds_to_beats,
    _tempo_at_time,
    _velocity_to_dynamic,
)


# ---------------------------------------------------------------------------
# MidiAdapter.supports()
# ---------------------------------------------------------------------------


class TestMidiSupports:
    def setup_method(self) -> None:
        self.adapter = MidiAdapter()

    @pytest.mark.parametrize("ext", [".mid", ".midi", ".MID", ".MIDI"])
    def test_supported_extensions(self, ext: str) -> None:
        assert self.adapter.supports(Path(f"song{ext}"))

    @pytest.mark.parametrize("ext", [".gp5", ".gp", ".xml", ".txt", ""])
    def test_unsupported_extensions(self, ext: str) -> None:
        assert not self.adapter.supports(Path(f"song{ext}"))


# ---------------------------------------------------------------------------
# MidiAdapter.parse() — error paths
# ---------------------------------------------------------------------------


class TestMidiParseErrors:
    def setup_method(self) -> None:
        self.adapter = MidiAdapter()

    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "song.xml"
        f.touch()
        with pytest.raises(UnsupportedFormatError):
            self.adapter.parse(f)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="not found"):
            self.adapter.parse(tmp_path / "nonexistent.mid")


# ---------------------------------------------------------------------------
# MIDI integration tests (creates real MIDI files via pretty_midi)
# ---------------------------------------------------------------------------


class TestMidiIntegration:
    """Integration tests that create real MIDI files via pretty_midi."""

    def setup_method(self) -> None:
        self.adapter = MidiAdapter()

    def test_parse_single_note(self, tmp_path: Path) -> None:
        """A single C4 (MIDI 60) at 120BPM."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Electric Guitar")
        # Quarter note at beat 0: 0.0s to 0.5s at 120BPM
        guitar.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)

        assert len(events) == 1
        assert events[0].pitch == 60
        assert events[0].onset == pytest.approx(0.0, abs=0.01)
        assert events[0].duration == pytest.approx(1.0, abs=0.1)  # ~1 beat at 120BPM
        assert events[0].tempo == pytest.approx(120.0, abs=1.0)
        assert events[0].string_hint is None
        assert events[0].fret_hint is None
        assert events[0].articulation == Articulation.NORMAL
        assert self.adapter.track_name == "Electric Guitar"

    def test_parse_multiple_notes_sequential(self, tmp_path: Path) -> None:
        """Three sequential quarter notes at 120BPM."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        # 120BPM = 0.5s per beat
        for i, pitch in enumerate([60, 64, 67]):
            start = i * 0.5
            guitar.notes.append(
                pretty_midi.Note(velocity=80, pitch=pitch, start=start, end=start + 0.5)
            )
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_seq.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)

        assert len(events) == 3
        pitches = [e.pitch for e in events]
        assert pitches == [60, 64, 67]
        # Onsets should be approximately 0, 1, 2 beats
        assert events[0].onset == pytest.approx(0.0, abs=0.05)
        assert events[1].onset == pytest.approx(1.0, abs=0.1)
        assert events[2].onset == pytest.approx(2.0, abs=0.1)

    def test_parse_chord_simultaneous(self, tmp_path: Path) -> None:
        """Simultaneous notes (chord) produce multiple events at same onset."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        for pitch in [60, 64, 67]:
            guitar.notes.append(
                pretty_midi.Note(velocity=80, pitch=pitch, start=0.0, end=1.0)
            )
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_chord.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)

        assert len(events) == 3
        onsets = {e.onset for e in events}
        assert len(onsets) == 1  # all at same onset

    def test_velocity_mapped_to_dynamic(self, tmp_path: Path) -> None:
        """Velocity values should map to Dynamic enum."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        # pp velocity
        guitar.notes.append(pretty_midi.Note(velocity=20, pitch=60, start=0.0, end=0.5))
        # ff velocity
        guitar.notes.append(pretty_midi.Note(velocity=120, pitch=64, start=0.5, end=1.0))
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_vel.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)

        assert len(events) == 2
        dynamics = {e.pitch: e.dynamic for e in events}
        assert dynamics[60] == Dynamic.PP
        assert dynamics[64] == Dynamic.FF

    def test_guitar_program_selection(self, tmp_path: Path) -> None:
        """Guitar instrument (program 25) should be selected over piano."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        piano = pretty_midi.Instrument(program=0, name="Piano")
        piano.notes.append(pretty_midi.Note(velocity=80, pitch=48, start=0.0, end=1.0))
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        guitar.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
        pm.instruments.append(piano)
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_select.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)

        # Should have the guitar note (pitch 60), not the piano note (48)
        assert len(events) == 1
        assert events[0].pitch == 60
        assert self.adapter.track_name == "Guitar"

    def test_empty_instrument_returns_empty(self, tmp_path: Path) -> None:
        """An instrument with no notes returns empty."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        # No notes added
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_empty.mid"
        pm.write(str(mid_path))

        events = self.adapter.parse(mid_path)
        assert events == []

    def test_section_markers_always_empty(self, tmp_path: Path) -> None:
        """MIDI has no rehearsal marks — section_markers is always {}."""
        import pretty_midi  # type: ignore[import-untyped]

        pm = pretty_midi.PrettyMIDI(initial_tempo=120.0)
        guitar = pretty_midi.Instrument(program=25, name="Guitar")
        guitar.notes.append(pretty_midi.Note(velocity=80, pitch=60, start=0.0, end=0.5))
        pm.instruments.append(guitar)

        mid_path = tmp_path / "test_markers.mid"
        pm.write(str(mid_path))

        self.adapter.parse(mid_path)
        assert self.adapter.section_markers == {}


# ---------------------------------------------------------------------------
# Pure function tests
# ---------------------------------------------------------------------------


class TestVelocityToDynamic:
    @pytest.mark.parametrize(
        "velocity, expected",
        [
            (10, Dynamic.PP),
            (40, Dynamic.P),
            (60, Dynamic.MP),
            (80, Dynamic.MF),
            (100, Dynamic.F),
            (120, Dynamic.FF),
        ],
    )
    def test_velocity_mapping(self, velocity: int, expected: Dynamic) -> None:
        assert _velocity_to_dynamic(velocity) == expected


class TestTempoAtTime:
    def test_single_tempo(self) -> None:
        assert _tempo_at_time(5.0, [0.0], [120.0]) == 120.0

    def test_tempo_change(self) -> None:
        # Changes from 120 to 140 at t=2.0
        assert _tempo_at_time(1.0, [0.0, 2.0], [120.0, 140.0]) == 120.0
        assert _tempo_at_time(3.0, [0.0, 2.0], [120.0, 140.0]) == 140.0


class TestSecondsToBeats:
    def test_constant_tempo(self) -> None:
        # At 120BPM: 1 second = 2 beats
        result = _seconds_to_beats(1.0, [0.0], [120.0])
        assert result == pytest.approx(2.0)

    def test_zero_time(self) -> None:
        assert _seconds_to_beats(0.0, [0.0], [120.0]) == 0.0

    def test_tempo_change(self) -> None:
        # 120BPM for 1 second (= 2 beats), then 60BPM for 1 second (= 1 beat)
        result = _seconds_to_beats(2.0, [0.0, 1.0], [120.0, 60.0])
        assert result == pytest.approx(3.0)


# ---------------------------------------------------------------------------
# get_adapter integration
# ---------------------------------------------------------------------------


class TestGetAdapterMidi:
    def test_get_adapter_mid(self) -> None:
        from fretwise.parser import get_adapter
        adapter = get_adapter(Path("song.mid"))
        assert isinstance(adapter, MidiAdapter)

    def test_get_adapter_midi(self) -> None:
        from fretwise.parser import get_adapter
        adapter = get_adapter(Path("song.midi"))
        assert isinstance(adapter, MidiAdapter)
