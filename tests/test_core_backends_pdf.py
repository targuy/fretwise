"""Tests for RenderScene PDF backend and backend contracts."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import (
    render_scene_to_pdf_bytes,
    render_scene_to_pdf_file,
    render_scene_to_svg,
)
from fretwise.core.canonical import (
    Measure,
    RestEvent,
    Score,
    Staff,
    StaffGroup,
    TimeSignature,
    Track,
    Voice,
)
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.registries import build_default_registries
from fretwise.core.scene import canonical_to_render_scene
from fretwise.models import Articulation, Dynamic
from fretwise.models import NoteEvent as LegacyNoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    string_hint: int | None = None,
    fret_hint: int | None = None,
) -> LegacyNoteEvent:
    return LegacyNoteEvent(
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


def test_render_scene_backends_draw_rest_as_vector_mark() -> None:
    score = Score(
        score_id="s-rest",
        title="quiet-song",
        tracks=[
            Track(
                track_id="t1",
                name="Track 1",
                staff_groups=[
                    StaffGroup(
                        group_id="g1",
                        staves=[
                            Staff(
                                staff_id="st1",
                                clef="treble",
                                measures=[
                                    Measure(
                                        number=1,
                                        time_signature=TimeSignature(numerator=4, denominator=4),
                                        voices=[
                                            Voice(
                                                number=0,
                                                events=[
                                                    RestEvent(
                                                        event_id="r1",
                                                        onset=0.0,
                                                        duration=1.0,
                                                        voice=0,
                                                    )
                                                ],
                                            )
                                        ],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        ],
    )

    scene = canonical_to_render_scene(score, mode=RepresentationMode.TAB_RHYTHM.value)
    svg = render_scene_to_svg(scene)
    pdf = render_scene_to_pdf_bytes(scene)

    assert "<path " in svg or "<rect " in svg
    assert "rest</text>" not in svg
    assert b"rest" not in pdf
