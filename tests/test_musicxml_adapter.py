"""Tests for fretwise.parser.musicxml_adapter — MusicXmlAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import pytest

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.musicxml_adapter import (
    MusicXmlAdapter,
    _m21_dynamic_to_dynamic,
)


# ---------------------------------------------------------------------------
# MusicXmlAdapter.supports()
# ---------------------------------------------------------------------------


class TestMusicXmlSupports:
    def setup_method(self) -> None:
        self.adapter = MusicXmlAdapter()

    @pytest.mark.parametrize("ext", [".xml", ".mxl", ".musicxml", ".XML", ".MXL"])
    def test_supported_extensions(self, ext: str) -> None:
        assert self.adapter.supports(Path(f"song{ext}"))

    @pytest.mark.parametrize("ext", [".gp5", ".gp", ".mid", ".txt", ""])
    def test_unsupported_extensions(self, ext: str) -> None:
        assert not self.adapter.supports(Path(f"song{ext}"))


# ---------------------------------------------------------------------------
# MusicXmlAdapter.parse() — error paths
# ---------------------------------------------------------------------------


class TestMusicXmlParseErrors:
    def setup_method(self) -> None:
        self.adapter = MusicXmlAdapter()

    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "song.gp5"
        f.touch()
        with pytest.raises(UnsupportedFormatError):
            self.adapter.parse(f)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="not found"):
            self.adapter.parse(tmp_path / "nonexistent.xml")


# ---------------------------------------------------------------------------
# MusicXmlAdapter.parse() — happy path via music21 mock
# ---------------------------------------------------------------------------


def _make_m21_note(
    midi_pitch: int = 60,
    offset: float = 0.0,
    quarter_length: float = 1.0,
    velocity: int | None = None,
    tie_type: str | None = None,
) -> MagicMock:
    """Build a mock music21 Note."""
    note = MagicMock()
    note.pitch.midi = midi_pitch
    note.offset = offset
    note.quarterLength = quarter_length
    note.articulations = []
    note.expressions = []

    vol = MagicMock()
    vol.velocity = velocity
    note.volume = vol

    if tie_type:
        tie = MagicMock()
        tie.type = tie_type
        note.tie = tie
    else:
        note.tie = None

    return note


def _make_m21_chord(
    midi_pitches: list[int],
    offset: float = 0.0,
    quarter_length: float = 1.0,
) -> MagicMock:
    """Build a mock music21 Chord."""
    import music21  # type: ignore[import-untyped]

    chord = MagicMock(spec=music21.chord.Chord)
    chord.offset = offset
    chord.quarterLength = quarter_length
    notes = []
    for p in midi_pitches:
        n = _make_m21_note(p, offset, quarter_length)
        notes.append(n)
    chord.__iter__ = MagicMock(return_value=iter(notes))
    return chord


class TestMusicXmlParseMocked:
    def setup_method(self) -> None:
        self.adapter = MusicXmlAdapter()

    @patch("fretwise.parser.musicxml_adapter._safe_import_music21")
    def test_parse_single_note(self, mock_import: MagicMock, tmp_path: Path) -> None:
        """A single C4 (MIDI 60) quarter note at onset 0."""
        import music21  # type: ignore[import-untyped]

        note = _make_m21_note(midi_pitch=60, offset=0.0, quarter_length=1.0)
        type(note).offset = PropertyMock(return_value=0.0)

        # Build a mock Part with flatten().notesAndRests returning [note]
        part = MagicMock()
        part.partName = "Classical Guitar"

        # Set up getInstruments to return an instrument with guitar program
        inst = MagicMock()
        inst.midiProgram = 25
        part.getInstruments = MagicMock(return_value=[inst])

        flat = MagicMock()
        flat.notesAndRests = [note]
        part.flatten = MagicMock(return_value=flat)
        part.recurse = MagicMock(return_value=[])

        # Make note look like a Note (not a Rest or Chord)
        note.__class__ = music21.note.Note

        # Tempo context
        tempo_mark = MagicMock()
        tempo_mark.number = 120.0
        note.getContextByClass = MagicMock(return_value=tempo_mark)

        # Build mock score
        score = MagicMock()
        score.parts = [part]

        m21_module = MagicMock()
        m21_module.converter.parse = MagicMock(return_value=score)
        m21_module.note.Note = music21.note.Note
        m21_module.note.Rest = music21.note.Rest
        m21_module.chord.Chord = music21.chord.Chord
        m21_module.tempo.MetronomeMark = music21.tempo.MetronomeMark
        m21_module.expressions.RehearsalMark = music21.expressions.RehearsalMark
        m21_module.stream.Measure = music21.stream.Measure
        m21_module.articulations.Staccato = music21.articulations.Staccato
        m21_module.articulations.Accent = music21.articulations.Accent
        m21_module.articulations.StrongAccent = music21.articulations.StrongAccent
        mock_import.return_value = m21_module

        f = tmp_path / "test.xml"
        f.touch()

        events = self.adapter.parse(f)

        assert len(events) == 1
        assert events[0].pitch == 60
        assert events[0].onset == 0.0
        assert events[0].duration == 1.0
        assert events[0].tempo == 120.0
        assert events[0].string_hint is None
        assert events[0].fret_hint is None
        assert self.adapter.track_name == "Classical Guitar"


# ---------------------------------------------------------------------------
# MusicXML with real music21 (integration)
# ---------------------------------------------------------------------------


class TestMusicXmlIntegration:
    """Integration tests that create real MusicXML via music21."""

    def setup_method(self) -> None:
        self.adapter = MusicXmlAdapter()

    def test_parse_simple_musicxml_file(self, tmp_path: Path) -> None:
        """Create a minimal MusicXML file with music21 and parse it."""
        import music21  # type: ignore[import-untyped]

        s = music21.stream.Score()
        p = music21.stream.Part()
        p.partName = "Guitar"

        inst = music21.instrument.ElectricGuitar()
        p.insert(0, inst)

        m = music21.stream.Measure(number=1)
        m.insert(0, music21.tempo.MetronomeMark(number=100))

        # C4, E4, G4 as quarter notes
        for pitch in [60, 64, 67]:
            n = music21.note.Note(pitch)
            n.quarterLength = 1.0
            m.append(n)

        # One quarter rest to fill the measure
        r = music21.note.Rest()
        r.quarterLength = 1.0
        m.append(r)

        p.append(m)
        s.insert(0, p)

        xml_path = tmp_path / "test_guitar.xml"
        s.write("musicxml", fp=str(xml_path))

        events = self.adapter.parse(xml_path)

        assert len(events) == 3
        pitches = [e.pitch for e in events]
        assert 60 in pitches
        assert 64 in pitches
        assert 67 in pitches
        assert all(e.string_hint is None for e in events)
        assert all(e.fret_hint is None for e in events)
        assert all(e.tempo == 100.0 for e in events)

    def test_parse_chord_musicxml(self, tmp_path: Path) -> None:
        """Chords should produce multiple NoteEvents at the same onset."""
        import music21  # type: ignore[import-untyped]

        s = music21.stream.Score()
        p = music21.stream.Part()
        p.partName = "Acoustic Guitar"

        m = music21.stream.Measure(number=1)
        c = music21.chord.Chord([60, 64, 67])  # C major
        c.quarterLength = 4.0  # whole note
        m.append(c)

        p.append(m)
        s.insert(0, p)

        xml_path = tmp_path / "test_chord.xml"
        s.write("musicxml", fp=str(xml_path))

        events = self.adapter.parse(xml_path)

        assert len(events) == 3
        # All at same onset
        onsets = {e.onset for e in events}
        assert len(onsets) == 1
        # All same duration
        assert all(e.duration == 4.0 for e in events)

    def test_parse_tied_notes_no_duplicates(self, tmp_path: Path) -> None:
        """Tied continuation notes should be skipped."""
        import music21  # type: ignore[import-untyped]

        s = music21.stream.Score()
        p = music21.stream.Part()

        m1 = music21.stream.Measure(number=1)
        n1 = music21.note.Note(64)
        n1.quarterLength = 4.0
        n1.tie = music21.tie.Tie("start")
        m1.append(n1)

        m2 = music21.stream.Measure(number=2)
        n2 = music21.note.Note(64)
        n2.quarterLength = 4.0
        n2.tie = music21.tie.Tie("stop")
        m2.append(n2)

        p.append(m1)
        p.append(m2)
        s.insert(0, p)

        xml_path = tmp_path / "test_tie.xml"
        s.write("musicxml", fp=str(xml_path))

        events = self.adapter.parse(xml_path)

        # Should have only the first note (start), not the continuation (stop)
        assert len(events) == 1
        assert events[0].pitch == 64

    def test_parse_mxl_compressed(self, tmp_path: Path) -> None:
        """Compressed .mxl files should also work."""
        import music21  # type: ignore[import-untyped]

        s = music21.stream.Score()
        p = music21.stream.Part()
        m = music21.stream.Measure(number=1)
        n = music21.note.Note(60)
        n.quarterLength = 1.0
        m.append(n)
        p.append(m)
        s.insert(0, p)

        mxl_path = tmp_path / "test.mxl"
        s.write("mxl", fp=str(mxl_path))

        events = self.adapter.parse(mxl_path)
        assert len(events) >= 1
        assert events[0].pitch == 60

    def test_empty_part_returns_empty(self, tmp_path: Path) -> None:
        """A score with only rests returns an empty list."""
        import music21  # type: ignore[import-untyped]

        s = music21.stream.Score()
        p = music21.stream.Part()
        m = music21.stream.Measure(number=1)
        r = music21.note.Rest()
        r.quarterLength = 4.0
        m.append(r)
        p.append(m)
        s.insert(0, p)

        xml_path = tmp_path / "test_empty.xml"
        s.write("musicxml", fp=str(xml_path))

        events = self.adapter.parse(xml_path)
        assert events == []


# ---------------------------------------------------------------------------
# Dynamic mapping
# ---------------------------------------------------------------------------


class TestM21DynamicMapping:
    @pytest.mark.parametrize(
        "velocity, expected",
        [
            (None, Dynamic.MF),
            (10, Dynamic.PP),
            (40, Dynamic.P),
            (60, Dynamic.MP),
            (80, Dynamic.MF),
            (100, Dynamic.F),
            (120, Dynamic.FF),
        ],
    )
    def test_velocity_mapping(self, velocity: int | None, expected: Dynamic) -> None:
        assert _m21_dynamic_to_dynamic(velocity) == expected


# ---------------------------------------------------------------------------
# get_adapter integration
# ---------------------------------------------------------------------------


class TestGetAdapterMusicXml:
    def test_get_adapter_xml(self) -> None:
        from fretwise.parser import get_adapter
        adapter = get_adapter(Path("song.xml"))
        assert isinstance(adapter, MusicXmlAdapter)

    def test_get_adapter_mxl(self) -> None:
        from fretwise.parser import get_adapter
        adapter = get_adapter(Path("song.mxl"))
        assert isinstance(adapter, MusicXmlAdapter)

    def test_get_adapter_musicxml(self) -> None:
        from fretwise.parser import get_adapter
        adapter = get_adapter(Path("song.musicxml"))
        assert isinstance(adapter, MusicXmlAdapter)
