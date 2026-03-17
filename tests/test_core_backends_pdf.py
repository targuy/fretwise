"""Tests for RenderScene PDF backend and backend contracts."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import (
    render_scene_to_pdf_bytes,
    render_scene_to_pdf_file,
    render_scene_to_svg,
)
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.registries import build_default_registries
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    string_hint: int | None = None,
    fret_hint: int | None = None,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=string_hint,
        fret_hint=fret_hint,
    )


def test_render_scene_to_pdf_bytes_outputs_pdf_document() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene
    pdf_bytes = render_scene_to_pdf_bytes(scene)

    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/Type /Page" in pdf_bytes
    assert len(pdf_bytes) > 500


def test_render_scene_to_pdf_file_writes_output(tmp_path: Path) -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene
    output = tmp_path / "scene.pdf"
    render_scene_to_pdf_file(scene, output)

    assert output.exists()
    content = output.read_bytes()
    assert content.startswith(b"%PDF-")
    assert b"/Type /Page" in content


def test_default_output_backend_registry_exposes_svg_and_pdf() -> None:
    registries = build_default_registries()
    output_backends = registries["output_backends"]
    assert output_backends.has("svg")
    assert output_backends.has("pdf")

    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene

    svg = output_backends.get("svg")(scene)
    pdf = output_backends.get("pdf")(scene)
    assert isinstance(svg, str)
    assert isinstance(pdf, bytes)
    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert pdf.startswith(b"%PDF-")


def test_svg_and_pdf_backends_share_same_scene_input() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=1.0, string_hint=1, fret_hint=2),
        ],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene

    svg = render_scene_to_svg(scene)
    pdf = render_scene_to_pdf_bytes(scene)
    assert "song" in svg
    assert svg.count("<text ") >= 2
    assert pdf.startswith(b"%PDF-")

