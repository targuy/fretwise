"""Tests for fretwise.cli — Click commands."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from fretwise.cli import main


def _make_mock_note(string: int, fret: int, note_type_value: int = 1) -> MagicMock:
    note = MagicMock()
    note.string = string
    note.value = fret
    note.type = MagicMock(value=note_type_value)
    note.effect.hammer = False
    note.effect.pullOff = False
    note.effect.slides = []
    note.effect.vibrato = False
    note.effect.bend = None
    return note


def _make_mock_beat(notes: list[MagicMock], duration_value: int = 4) -> MagicMock:
    beat = MagicMock()
    beat.notes = notes
    beat.duration.value = duration_value
    beat.duration.isDotted = False
    beat.duration.isDoubleDotted = False
    beat.duration.tuplet.enters = 1
    beat.duration.tuplet.times = 1
    return beat


def _make_mock_song(
    tempo: int = 120,
    note_specs: list[tuple[int, int]] | None = None,
) -> MagicMock:
    if note_specs is None:
        note_specs = [(3, 5)]
    song = MagicMock()
    song.tempo = tempo
    track = MagicMock()
    track.isPercussionTrack = False
    open_pitches = [64, 59, 55, 50, 45, 40]
    mock_strings = []
    for idx, pitch in enumerate(open_pitches, start=1):
        s = MagicMock()
        s.number = idx
        s.value = pitch
        mock_strings.append(s)
    track.strings = mock_strings
    beats = [_make_mock_beat([_make_mock_note(s, f)]) for s, f in note_specs]
    measure = MagicMock()
    measure.header.tempo.value = tempo
    voice = MagicMock()
    voice.beats = beats
    measure.voices = [voice]
    track.measures = [measure]
    song.tracks = [track]
    return song


class TestParseCommand:
    def test_parse_unsupported_format(self, tmp_path: Path) -> None:
        runner = CliRunner()
        f = tmp_path / "song.gpx"
        f.touch()
        result = runner.invoke(main, ["parse", str(f)])
        assert result.exit_code == 1
        assert "Error" in result.output or "Error" in (result.stderr or "")

    def test_parse_missing_file(self, tmp_path: Path) -> None:
        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(tmp_path / "missing.gp5")])
        # Click validates existence before invoking the command
        assert result.exit_code != 0

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_displays_notes(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(1, 0), (2, 3)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(gp_file)])
        assert result.exit_code == 0
        assert "Parsed 2 note(s)" in result.output
        assert "[0000]" in result.output
        assert "[0001]" in result.output

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_verbose(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        mock_parse.return_value = _make_mock_song()
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["parse", "--verbose", str(gp_file)])
        assert result.exit_code == 0
        assert "bpm" in result.output

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_parse_empty_song(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        song = MagicMock()
        song.tempo = 120
        song.tracks = []
        mock_parse.return_value = song
        gp_file = tmp_path / "empty.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["parse", str(gp_file)])
        assert result.exit_code == 0
        assert "No notes found" in result.output


class TestSolveCommand:
    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_outputs_json_to_stdout(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(3, 5)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["solve", str(gp_file)])
        assert result.exit_code == 0
        assert '"note_id"' in result.output
        assert '"pitch"' in result.output
        assert '"finger"' in result.output

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_writes_json_file(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(3, 5), (2, 3)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()
        out_file = tmp_path / "out.json"

        runner = CliRunner()
        result = runner.invoke(main, ["solve", str(gp_file), "--output", str(out_file)])
        assert result.exit_code == 0
        assert out_file.exists()
        content = out_file.read_text(encoding="utf-8")
        assert '"note_id"' in content

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_performance_mode(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        mock_parse.return_value = _make_mock_song()
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["solve", str(gp_file), "--mode", "performance"])
        assert result.exit_code == 0

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_verbose(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        mock_parse.return_value = _make_mock_song()
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["solve", str(gp_file), "--verbose"])
        assert result.exit_code == 0

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_unsupported_output_format(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        mock_parse.return_value = _make_mock_song()
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(
            main, ["solve", str(gp_file), "--output", str(tmp_path / "out.gp5")]
        )
        assert result.exit_code == 1

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_empty_song(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        song = MagicMock()
        song.tempo = 120
        song.tracks = []
        mock_parse.return_value = song
        gp_file = tmp_path / "empty.gp5"
        gp_file.touch()

        runner = CliRunner()
        result = runner.invoke(main, ["solve", str(gp_file)])
        assert result.exit_code == 0
        assert "No notes found" in result.output
