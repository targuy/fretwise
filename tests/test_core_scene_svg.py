"""Tests for RenderScene builder, SVG backend, and core pipeline."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_svg
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.scene import canonical_to_render_scene
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


def test_canonical_to_render_scene_builds_tab_lines_and_note_text() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    completed_score = run_core_pipeline_from_raw(raw_score).completed_score
    canonical_score = completed_to_canonical_score(completed_score)
    scene = canonical_to_render_scene(canonical_score)

    assert scene.document_scene.pages
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    assert len(staff.layer_groups) == 2
    assert staff.layer_groups[0].recipe_instances[0].recipe_id == "tab_lines"
    assert any(text.metadata.get("kind") == "note" for text in staff.layer_groups[1].text_instances)


def test_render_scene_to_svg_outputs_svg_document() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    result = run_core_pipeline_from_raw(raw_score)
    svg = render_scene_to_svg(result.render_scene)

    assert svg.startswith('<svg xmlns="http://www.w3.org/2000/svg"')
    assert "<line " in svg
    assert "<text " in svg
    assert "song" in svg


def test_run_core_pipeline_from_raw_end_to_end() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=1.0, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score)

    assert result.validation_report.checked_notes == 2
    assert result.decision_outcome.action.value == "accept"
    assert result.canonical_score.tracks
    assert "<svg" in result.svg
