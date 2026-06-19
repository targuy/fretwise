"""Tests for fretwise.cli — Click commands."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from click.testing import CliRunner

from fretwise.cli import _infer_source_format, main
from fretwise.core.graphics import RepresentationMode


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

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_pdf_core_engine_writes_pdf(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(1, 0), (1, 2)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()
        out_file = tmp_path / "out_core.pdf"

        runner = CliRunner()
        result = runner.invoke(
            main,
            [
                "solve",
                str(gp_file),
                "--output",
                str(out_file),
                "--pdf-engine",
                "core",
            ],
        )
        assert result.exit_code == 0
        assert out_file.exists()
        assert out_file.read_bytes().startswith(b"%PDF-")

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_pdf_core_engine_passes_representation_mode(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(1, 0), (1, 2)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()
        out_file = tmp_path / "out_core_mode.pdf"

        fake_core_result = MagicMock()
        fake_core_result.render_scene = object()
        fake_core_result.conformance_issues = []

        def _fake_render_scene(_scene: object, output_path: Path) -> None:
            output_path.write_bytes(b"%PDF-1.4\n%mode-test\n")

        runner = CliRunner()
        with (
            patch("fretwise.cli._run_core_pipeline_for_events", return_value=fake_core_result)
            as run_core,
            patch("fretwise.cli.render_scene_to_pdf_file", side_effect=_fake_render_scene),
        ):
            result = runner.invoke(
                main,
                [
                    "solve",
                    str(gp_file),
                    "--output",
                    str(out_file),
                    "--pdf-engine",
                    "core",
                    "--representation-mode",
                    "tablature_rhythm",
                ],
            )

        assert result.exit_code == 0
        assert out_file.exists()
        assert out_file.read_bytes().startswith(b"%PDF-")
        assert run_core.call_count == 1
        assert (
            run_core.call_args.kwargs["representation_mode"]
            == RepresentationMode.TAB_RHYTHM
        )

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_solve_pdf_legacy_reports_shadow_core_conformance(
        self,
        mock_parse: MagicMock,
        tmp_path: Path,
    ) -> None:
        mock_parse.return_value = _make_mock_song(note_specs=[(1, 0), (1, 2)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()
        out_file = tmp_path / "out_legacy.pdf"

        def _fake_render_pdf_tab(
            _results: list[object],
            output_path: Path,
            **_kwargs: object,
        ) -> None:
            output_path.write_bytes(b"%PDF-1.4\n%shadow-test\n")

        runner = CliRunner()
        with (
            patch("fretwise.cli._shadow_core_conformance_outcome", return_value=(2, False)),
            patch("fretwise.cli.render_pdf_tab", side_effect=_fake_render_pdf_tab),
        ):
            result = runner.invoke(
                main,
                [
                    "solve",
                    str(gp_file),
                    "--output",
                    str(out_file),
                    "--pdf-engine",
                    "legacy",
                ],
            )
        assert result.exit_code == 0
        assert out_file.exists()
        assert out_file.read_bytes().startswith(b"%PDF-")
        assert "Legacy PDF shadow core conformance issues: 2" in result.output


class TestFingerCommand:
    def test_finger_writes_default_gp_output(self, tmp_path: Path) -> None:
        gp_file = tmp_path / "song.gp"
        gp_file.touch()
        fake_adapter = MagicMock()
        fake_adapter.parse.return_value = [object()]
        fake_report = SimpleNamespace(fatal_count=0, high_count=0, by_measure=lambda: {})
        fake_payload = SimpleNamespace(results=[object()], biomechanical_report=fake_report)

        runner = CliRunner()
        with (
            patch("fretwise.cli.get_adapter", return_value=fake_adapter),
            patch("fretwise.cli._guarded_pipeline_result", return_value=(fake_payload, None)),
            patch("fretwise.cli.fingerings_by_source_id", return_value={"1": "I"}),
            patch("fretwise.cli.write_gp_with_fingerings", return_value=b"GPIF"),
        ):
            result = runner.invoke(main, ["finger", str(gp_file)])

        out_file = tmp_path / "song_fingered.gp"
        assert result.exit_code == 0
        assert out_file.read_bytes() == b"GPIF"
        assert "GP written" in result.output

    def test_finger_blocks_fatal_guard_report(self, tmp_path: Path) -> None:
        gp_file = tmp_path / "song.gp"
        gp_file.touch()
        fake_adapter = MagicMock()
        fake_adapter.parse.return_value = [object()]
        fake_report = SimpleNamespace(
            fatal_count=1,
            high_count=0,
            by_measure=lambda: {12: [object()]},
        )
        fake_payload = SimpleNamespace(results=[object()], biomechanical_report=fake_report)

        runner = CliRunner()
        with (
            patch("fretwise.cli.get_adapter", return_value=fake_adapter),
            patch("fretwise.cli._guarded_pipeline_result", return_value=(fake_payload, None)),
            patch("fretwise.cli.write_gp_with_fingerings") as writer,
        ):
            result = runner.invoke(main, ["finger", str(gp_file)])

        assert result.exit_code == 1
        assert "biomechanical guard failed" in result.output
        assert "measures=12" in result.output
        writer.assert_not_called()


class TestCliHelpers:
    def test_infer_source_format(self) -> None:
        assert _infer_source_format(Path("a.gp")) == "gpif"
        assert _infer_source_format(Path("a.gp5")) == "gp5"
        assert _infer_source_format(Path("a.xml")) == "musicxml"
        assert _infer_source_format(Path("a.mxl")) == "musicxml"
        assert _infer_source_format(Path("a.mid")) == "mid"
