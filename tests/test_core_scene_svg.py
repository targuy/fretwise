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
    voice_hint: int = 0,
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
        voice_hint=voice_hint,
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


def test_canonical_to_render_scene_standard_contains_secondary_beam_for_mixed_group() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=0.5, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=0.5, duration=0.25, string_hint=1, fret_hint=2),
            _note(pitch=67, onset=0.75, duration=0.25, string_hint=1, fret_hint=3),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    beam_recipes = [
        recipe
        for recipe in staff.layer_groups[1].recipe_instances
        if recipe.recipe_id == "beam_group"
    ]
    levels = {int(recipe.params.get("level", 1)) for recipe in beam_recipes}
    svg = render_scene_to_svg(result.render_scene)

    assert 1 in levels
    assert 2 in levels
    assert svg.count("<rect ") >= 2


def test_canonical_to_render_scene_standard_uses_voice_aware_stem_direction() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=2, fret_hint=5),
            _note(pitch=52, onset=1.0, duration=1.0, voice_hint=1, string_hint=5, fret_hint=3),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    stem_recipes = [
        recipe
        for recipe in staff.layer_groups[1].recipe_instances
        if recipe.recipe_id == "stem_line"
    ]
    directions = {str(recipe.metadata.get("direction", "up")) for recipe in stem_recipes}

    assert "up" in directions
    assert "down" in directions


def test_canonical_to_render_scene_standard_contains_flag_for_unbeamed_note() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=0.5, string_hint=1, fret_hint=0)],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[1].recipe_instances]
    svg = render_scene_to_svg(result.render_scene)

    assert "flag_stack" in recipe_ids
    assert svg.count("<path ") >= 1


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


def test_canonical_to_render_scene_standard_down_voice_tie_curves_upward() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=55, onset=0.0, duration=0.5, voice_hint=1, string_hint=4, fret_hint=5),
            _note(pitch=55, onset=0.5, duration=0.5, voice_hint=1, string_hint=4, fret_hint=5),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    tie_recipes = [
        recipe for recipe in staff.layer_groups[1].recipe_instances if recipe.recipe_id == "tie_arc"
    ]

    assert tie_recipes
    assert float(tie_recipes[0].params.get("curvature", 0.0)) < 0.0


def test_canonical_to_render_scene_standard_does_not_connect_across_voices() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(
                pitch=64,
                onset=0.0,
                duration=1.0,
                articulation=Articulation.LEGATO,
                voice_hint=0,
                string_hint=1,
                fret_hint=0,
            ),
            _note(
                pitch=67,
                onset=1.0,
                duration=1.0,
                voice_hint=1,
                string_hint=2,
                fret_hint=3,
            ),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for r in staff.layer_groups[1].recipe_instances]

    assert "tie_arc" not in recipe_ids
    assert "slur_arc" not in recipe_ids


def test_canonical_to_render_scene_standard_adapts_tie_profile_for_long_span() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=55, onset=0.0, duration=2.0, voice_hint=1, string_hint=4, fret_hint=5),
            _note(pitch=55, onset=2.0, duration=1.0, voice_hint=1, string_hint=4, fret_hint=5),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    tie_recipes = [
        recipe for recipe in staff.layer_groups[1].recipe_instances if recipe.recipe_id == "tie_arc"
    ]

    assert tie_recipes
    assert float(tie_recipes[0].params.get("curvature", 0.0)) < -8.0
    assert tie_recipes[0].metadata.get("voice_number") == "1"


def test_canonical_to_render_scene_standard_contains_accidental_glyph() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=61, onset=0.0, duration=1.0, string_hint=2, fret_hint=2)],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    note_glyph_ids = [g.glyph_id for g in staff.layer_groups[1].glyph_instances]
    svg = render_scene_to_svg(result.render_scene)

    assert "accidental_sharp" in note_glyph_ids
    assert "♯" in svg


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


def test_canonical_to_render_scene_standard_places_rests_by_voice() -> None:
    score = Score(
        score_id="s2",
        title="voice-rests",
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
                                                        event_id="r-up",
                                                        onset=0.0,
                                                        duration=1.0,
                                                        voice=0,
                                                    )
                                                ],
                                            ),
                                            Voice(
                                                number=1,
                                                events=[
                                                    RestEvent(
                                                        event_id="r-down",
                                                        onset=1.0,
                                                        duration=1.0,
                                                        voice=1,
                                                    )
                                                ],
                                            ),
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

    scene = canonical_to_render_scene(score, mode=RepresentationMode.STANDARD.value)
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    rests = {
        str(glyph.metadata.get("event_id")): glyph
        for glyph in staff.layer_groups[1].glyph_instances
        if glyph.glyph_id == "rest"
    }

    assert "r-up" in rests
    assert "r-down" in rests
    assert rests["r-up"].y < rests["r-down"].y
    assert rests["r-up"].metadata.get("voice_number") == "0"
    assert rests["r-down"].metadata.get("voice_number") == "1"


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
