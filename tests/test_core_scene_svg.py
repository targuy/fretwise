"""Tests for RenderScene builder, SVG backend, and core pipeline."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_svg
from fretwise.core.canonical import (
    KeySignature,
    Measure,
    RestEvent,
    Score,
    Staff,
    StaffGroup,
    TempoMark,
    TimeSignature,
    Track,
    Voice,
    completed_to_canonical_score,
)
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.scene import canonical_to_render_scene
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    duration: float = 1.0,
    articulation: Articulation = Articulation.NORMAL,
    string_hint: int | None = None,
    fret_hint: int | None = None,
    let_ring: bool = False,
    palm_muted: bool = False,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        articulation=articulation,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=string_hint,
        fret_hint=fret_hint,
        let_ring=let_ring,
        palm_muted=palm_muted,
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


def test_canonical_to_render_scene_standard_tablature_has_both_planes() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    completed_score = run_core_pipeline_from_raw(raw_score).completed_score
    canonical_score = completed_to_canonical_score(completed_score)
    scene = canonical_to_render_scene(canonical_score, mode=RepresentationMode.STANDARD_TAB.value)

    staff = scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[0].recipe_instances]
    assert "staff_lines" in recipe_ids
    assert "tab_lines" in recipe_ids
    assert any(g.glyph_id == "notehead" for g in staff.layer_groups[1].glyph_instances)
    assert any(t.metadata.get("kind") == "note" for t in staff.layer_groups[1].text_instances)
    staff_glyph_ids = {g.glyph_id for g in staff.layer_groups[0].glyph_instances}
    assert "clef" in staff_glyph_ids
    assert "time_signature" in staff_glyph_ids


def test_canonical_to_render_scene_standard_contains_stems_and_beams() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=0.5, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=0.5, duration=0.5, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[1].recipe_instances]
    svg = render_scene_to_svg(result.render_scene)

    assert "stem_line" in recipe_ids
    assert "beam_group" in recipe_ids
    assert "<rect " in svg


def test_canonical_to_render_scene_standard_contains_tie_and_slur_arcs() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(
                pitch=64,
                onset=0.0,
                duration=0.5,
                articulation=Articulation.LEGATO,
                string_hint=1,
                fret_hint=0,
            ),
            _note(pitch=66, onset=0.5, duration=0.5, string_hint=1, fret_hint=2),
            _note(pitch=66, onset=1.0, duration=0.5, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[1].recipe_instances]
    svg = render_scene_to_svg(result.render_scene)

    assert "slur_arc" in recipe_ids
    assert "tie_arc" in recipe_ids
    assert "<path " in svg


def test_canonical_to_render_scene_tab_contains_technique_spans() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(
                pitch=64,
                onset=0.0,
                duration=1.0,
                string_hint=1,
                fret_hint=0,
                let_ring=True,
                palm_muted=True,
            ),
            _note(pitch=66, onset=1.0, duration=1.0, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[1].recipe_instances]
    svg = render_scene_to_svg(result.render_scene)

    assert "let_ring_span" in recipe_ids
    assert "palm_mute_span" in recipe_ids
    assert "L.R." in svg
    assert "P.M." in svg


def test_canonical_to_render_scene_standard_renders_header_and_rest_glyphs() -> None:
    score = Score(
        score_id="s1",
        title="rest-song",
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
                                        time_signature=TimeSignature(numerator=3, denominator=4),
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
        tempo_marks=[TempoMark(onset=0.0, bpm=90.0)],
        key_signature=KeySignature(),
    )

    scene = canonical_to_render_scene(score, mode=RepresentationMode.STANDARD.value)
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    staff_glyph_ids = {g.glyph_id for g in staff.layer_groups[0].glyph_instances}
    notes_glyph_ids = {g.glyph_id for g in staff.layer_groups[1].glyph_instances}
    svg = render_scene_to_svg(scene)

    assert "clef" in staff_glyph_ids
    assert "time_signature" in staff_glyph_ids
    assert "rest" in notes_glyph_ids
    assert "3/4" in svg


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
    assert result.conformance_issues == []
    assert "<svg" in result.svg
