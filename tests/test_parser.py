"""Tests for fretwise.parser — GuitarProAdapter."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fretwise.models import Articulation, Dynamic
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.guitarpro_adapter import (
    GuitarProAdapter,
    _duration_in_beats,
    _get_articulation,
    _open_string_pitches,
)

# ---------------------------------------------------------------------------
# GuitarProAdapter.supports()
# ---------------------------------------------------------------------------


class TestSupports:
    def setup_method(self) -> None:
        self.adapter = GuitarProAdapter()

    @pytest.mark.parametrize("ext", [".gp3", ".gp4", ".gp5", ".GP5", ".GP3"])
    def test_supported_extensions(self, ext: str) -> None:
        assert self.adapter.supports(Path(f"song{ext}"))

    @pytest.mark.parametrize("ext", [".gpx", ".xml", ".mxl", ".mid", ".txt", ""])
    def test_unsupported_extensions(self, ext: str) -> None:
        assert not self.adapter.supports(Path(f"song{ext}"))


# ---------------------------------------------------------------------------
# GuitarProAdapter.parse() — error paths
# ---------------------------------------------------------------------------


class TestParseErrors:
    def setup_method(self) -> None:
        self.adapter = GuitarProAdapter()

    def test_unsupported_format_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "song.gpx"
        f.touch()
        with pytest.raises(UnsupportedFormatError):
            self.adapter.parse(f)

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="not found"):
            self.adapter.parse(tmp_path / "nonexistent.gp5")

    def test_corrupt_file_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.gp5"
        f.write_bytes(b"not a guitarpro file")
        with pytest.raises(ParseError):
            self.adapter.parse(f)


# ---------------------------------------------------------------------------
# GuitarProAdapter.parse() — happy path (mocked song)
# ---------------------------------------------------------------------------


def _make_mock_note(
    string: int,
    fret: int,
    note_type_value: int = 1,
    hammer: bool = False,
    pull_off: bool = False,
    slides: list[int] | None = None,
    vibrato: bool = False,
    bend: object | None = None,
) -> MagicMock:
    """Build a mock guitarpro Note."""
    note = MagicMock()
    note.string = string
    note.value = fret
    note.type = MagicMock(value=note_type_value)
    note.effect.hammer = hammer
    note.effect.pullOff = pull_off
    note.effect.slides = slides or []
    note.effect.vibrato = vibrato
    note.effect.bend = bend
    return note


def _make_mock_beat(
    notes: list[MagicMock],
    duration_value: int = 4,
    dotted: bool = False,
    double_dotted: bool = False,
    tuplet_enters: int = 1,
    tuplet_times: int = 1,
) -> MagicMock:
    """Build a mock guitarpro Beat."""
    beat = MagicMock()
    beat.notes = notes
    beat.duration.value = duration_value
    beat.duration.isDotted = dotted
    beat.duration.isDoubleDotted = double_dotted
    beat.duration.tuplet.enters = tuplet_enters
    beat.duration.tuplet.times = tuplet_times
    return beat


def _make_mock_song(
    tempo: int = 120,
    beats_per_measure: list[list[MagicMock]] | None = None,
    open_pitches: list[int] | None = None,
) -> MagicMock:
    """Build a minimal mock guitarpro Song with one guitar track."""
    song = MagicMock()
    song.tempo = tempo

    track = MagicMock()
    track.isPercussionTrack = False

    # String tuning
    if open_pitches is None:
        open_pitches = [64, 59, 55, 50, 45, 40]
    mock_strings = []
    for idx, pitch in enumerate(open_pitches, start=1):
        s = MagicMock()
        s.number = idx
        s.value = pitch
        mock_strings.append(s)
    track.strings = mock_strings

    # Measures
    if beats_per_measure is None:
        beats_per_measure = []

    measures = []
    for beats in beats_per_measure:
        measure = MagicMock()
        measure.header.tempo.value = tempo
        voice = MagicMock()
        voice.beats = beats
        measure.voices = [voice]
        measures.append(measure)

    track.measures = measures
    song.tracks = [track]
    return song


class TestParseMockedSong:
    def setup_method(self) -> None:
        self.adapter = GuitarProAdapter()

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_single_note(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        """A single quarter note on string 3, fret 5 → MIDI 60 (G3 + 5)."""
        note = _make_mock_note(string=3, fret=5)
        beat = _make_mock_beat([note])
        song = _make_mock_song(tempo=120, beats_per_measure=[[beat]])
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)

        assert len(events) == 1
        assert events[0].pitch == 55 + 5  # G3 (55) + 5 = 60 = C4
        assert events[0].onset == 0.0
        assert events[0].duration == 1.0  # quarter note = 1 beat
        assert events[0].tempo == 120.0
        assert events[0].string_hint == 3
        assert events[0].fret_hint == 5
        assert events[0].articulation == Articulation.NORMAL
        assert events[0].dynamic == Dynamic.MF

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_two_notes_onset_sequential(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        """Two quarter notes should have onsets 0.0 and 1.0."""
        note1 = _make_mock_note(string=1, fret=0)
        note2 = _make_mock_note(string=2, fret=0)
        beat1 = _make_mock_beat([note1])
        beat2 = _make_mock_beat([note2])
        song = _make_mock_song(beats_per_measure=[[beat1, beat2]])
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)

        assert len(events) == 2
        assert events[0].onset == pytest.approx(0.0)
        assert events[1].onset == pytest.approx(1.0)

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_rest_note_is_skipped(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        """Notes with type.value != 1 (rests, tied) are excluded."""
        rest = _make_mock_note(string=1, fret=0, note_type_value=0)
        tied = _make_mock_note(string=2, fret=3, note_type_value=2)
        normal = _make_mock_note(string=3, fret=5)
        beat = _make_mock_beat([rest, tied, normal])
        song = _make_mock_song(beats_per_measure=[[beat]])
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)
        assert len(events) == 1
        assert events[0].string_hint == 3

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_hammer_on_articulation(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        note = _make_mock_note(string=2, fret=3, hammer=True)
        beat = _make_mock_beat([note])
        song = _make_mock_song(beats_per_measure=[[beat]])
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)
        assert events[0].articulation == Articulation.HAMMER_ON

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_extracts_beat_strum_direction(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        note = _make_mock_note(string=2, fret=3)
        beat = _make_mock_beat([note])
        beat.effect.stroke.down = 1
        beat.effect.stroke.up = 0
        song = _make_mock_song(beats_per_measure=[[beat]])
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)
        assert events[0].strum_direction == "down"

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_no_guitar_track_returns_empty(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        song = MagicMock()
        song.tempo = 120
        perc = MagicMock()
        perc.isPercussionTrack = True
        song.tracks = [perc]
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)
        assert events == []

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_advances_measure_by_longest_voice(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        """When voice 0 is shorter, next measure onset must still advance to full bar."""
        song = MagicMock()
        song.tempo = 120
        track = MagicMock()
        track.isPercussionTrack = False
        track.strings = []

        m1 = MagicMock()
        m1.header.tempo.value = 120
        m1.header.timeSignature.numerator = 4
        m1.header.timeSignature.denominator.value = 4
        v0_m1 = MagicMock()
        v1_m1 = MagicMock()
        v0_m1.beats = [_make_mock_beat([_make_mock_note(string=1, fret=0)])]
        v1_m1.beats = [
            _make_mock_beat([_make_mock_note(string=2, fret=0)]),
            _make_mock_beat([_make_mock_note(string=3, fret=0)]),
            _make_mock_beat([_make_mock_note(string=4, fret=0)]),
            _make_mock_beat([_make_mock_note(string=5, fret=0)]),
        ]
        m1.voices = [v0_m1, v1_m1]

        m2 = MagicMock()
        m2.header.tempo.value = 120
        m2.header.timeSignature.numerator = 4
        m2.header.timeSignature.denominator.value = 4
        v0_m2 = MagicMock()
        v0_m2.beats = [_make_mock_beat([_make_mock_note(string=1, fret=5)])]
        m2.voices = [v0_m2]

        track.measures = [m1, m2]
        song.tracks = [track]
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        events = self.adapter.parse(gp_file)
        onsets = sorted({round(event.onset, 6) for event in events})
        assert 0.0 in onsets
        assert 4.0 in onsets

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_keeps_chord_marker_measure_alignment_with_short_voice0(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        """Chord markers should not drift when voice 0 has fewer beats than another voice."""
        song = MagicMock()
        song.tempo = 120
        track = MagicMock()
        track.isPercussionTrack = False
        track.strings = []

        m1 = MagicMock()
        m1.header.tempo.value = 120
        m1.header.timeSignature.numerator = 4
        m1.header.timeSignature.denominator.value = 4
        beat_m1 = _make_mock_beat([_make_mock_note(string=1, fret=0)])
        beat_m1.effect.chord = None
        v0_m1 = MagicMock()
        v0_m1.beats = [beat_m1]
        v1_m1 = MagicMock()
        v1_m1.beats = [
            _make_mock_beat([_make_mock_note(string=2, fret=0)]),
            _make_mock_beat([_make_mock_note(string=3, fret=0)]),
            _make_mock_beat([_make_mock_note(string=4, fret=0)]),
            _make_mock_beat([_make_mock_note(string=5, fret=0)]),
        ]
        m1.voices = [v0_m1, v1_m1]

        m2 = MagicMock()
        m2.header.tempo.value = 120
        m2.header.timeSignature.numerator = 4
        m2.header.timeSignature.denominator.value = 4
        beat_m2 = _make_mock_beat([_make_mock_note(string=1, fret=5)])
        beat_m2.effect.chord.name = "A5"
        v0_m2 = MagicMock()
        v0_m2.beats = [beat_m2]
        m2.voices = [v0_m2]

        track.measures = [m1, m2]
        song.tracks = [track]
        mock_parse.return_value = song

        gp_file = tmp_path / "test.gp5"
        gp_file.touch()

        _events = self.adapter.parse(gp_file)
        assert self.adapter.chord_markers.get("4.000000") == "A5"


# ---------------------------------------------------------------------------
# _duration_in_beats (pure function)
# ---------------------------------------------------------------------------


class TestDurationInBeats:
    def _make_duration(
        self,
        value: int,
        dotted: bool = False,
        double_dotted: bool = False,
        t_enters: int = 1,
        t_times: int = 1,
    ) -> MagicMock:
        d = MagicMock()
        d.value = value
        d.isDotted = dotted
        d.isDoubleDotted = double_dotted
        d.tuplet.enters = t_enters
        d.tuplet.times = t_times
        return d

    @pytest.mark.parametrize(
        "note_value, expected_beats",
        [
            (1, 4.0),   # whole note
            (2, 2.0),   # half note
            (4, 1.0),   # quarter note
            (8, 0.5),   # eighth note
            (16, 0.25), # sixteenth note
            (32, 0.125),
        ],
    )
    def test_plain_durations(self, note_value: int, expected_beats: float) -> None:
        d = self._make_duration(note_value)
        assert _duration_in_beats(d) == pytest.approx(expected_beats)

    def test_dotted_quarter(self) -> None:
        d = self._make_duration(4, dotted=True)
        assert _duration_in_beats(d) == pytest.approx(1.5)

    def test_double_dotted_quarter(self) -> None:
        d = self._make_duration(4, double_dotted=True)
        assert _duration_in_beats(d) == pytest.approx(1.75)

    def test_triplet_eighth(self) -> None:
        # Triplet: 3 notes in the time of 2 → each note = 2/3 of an eighth
        d = self._make_duration(8, t_enters=3, t_times=2)
        expected = 0.5 * 2 / 3
        assert _duration_in_beats(d) == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _get_articulation (pure function)
# ---------------------------------------------------------------------------


class TestGetArticulation:
    def _make_note_effect(
        self,
        hammer: bool = False,
        pull_off: bool = False,
        slides: list[int] | None = None,
        vibrato: bool = False,
        bend: object | None = None,
    ) -> MagicMock:
        note = MagicMock()
        note.effect.hammer = hammer
        note.effect.pullOff = pull_off
        note.effect.slides = slides or []
        note.effect.vibrato = vibrato
        note.effect.bend = bend
        return note

    def test_no_effect_returns_normal(self) -> None:
        note = self._make_note_effect()
        assert _get_articulation(note) == Articulation.NORMAL

    def test_hammer_on(self) -> None:
        note = self._make_note_effect(hammer=True)
        assert _get_articulation(note) == Articulation.HAMMER_ON

    def test_pull_off(self) -> None:
        note = self._make_note_effect(pull_off=True)
        assert _get_articulation(note) == Articulation.PULL_OFF

    def test_slide(self) -> None:
        note = self._make_note_effect(slides=[1])
        assert _get_articulation(note) == Articulation.SLIDE

    def test_vibrato(self) -> None:
        note = self._make_note_effect(vibrato=True)
        assert _get_articulation(note) == Articulation.VIBRATO

    def test_bend(self) -> None:
        note = self._make_note_effect(bend=object())
        assert _get_articulation(note) == Articulation.BEND

    def test_hammer_takes_priority_over_vibrato(self) -> None:
        note = self._make_note_effect(hammer=True, vibrato=True)
        assert _get_articulation(note) == Articulation.HAMMER_ON


# ---------------------------------------------------------------------------
# _open_string_pitches (pure function)
# ---------------------------------------------------------------------------


class TestOpenStringPitches:
    def test_standard_tuning_from_track_strings(self) -> None:
        track = MagicMock()
        expected = [64, 59, 55, 50, 45, 40]
        mock_strings = []
        for idx, pitch in enumerate(expected, start=1):
            s = MagicMock()
            s.number = idx
            s.value = pitch
            mock_strings.append(s)
        track.strings = mock_strings
        assert _open_string_pitches(track) == expected

    def test_fallback_to_standard_tuning_when_empty(self) -> None:
        from fretwise.parser.guitarpro_adapter import _STANDARD_TUNING

        track = MagicMock()
        track.strings = []
        assert _open_string_pitches(track) == _STANDARD_TUNING

    def test_strings_sorted_by_number(self) -> None:
        """Strings may arrive out of order from the file; they must be sorted."""
        track = MagicMock()
        # Provide strings in reverse order
        pitches = {6: 40, 5: 45, 4: 50, 3: 55, 2: 59, 1: 64}
        mock_strings = []
        for num, pitch in pitches.items():
            s = MagicMock()
            s.number = num
            s.value = pitch
            mock_strings.append(s)
        track.strings = mock_strings
        result = _open_string_pitches(track)
        assert result == [64, 59, 55, 50, 45, 40]
