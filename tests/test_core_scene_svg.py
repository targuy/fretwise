"""Tests for RenderScene builder, SVG backend, and core pipeline."""

from __future__ import annotations

from pathlib import Path

import fretwise.core.scene.builders as scene_builders

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
from fretwise.core.canonical import (
    NoteEvent as CanonicalNoteEvent,
)
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.scene import (
    DocumentScene,
    LayerGroup,
    PageScene,
    RenderScene,
    StaffScene,
    SystemScene,
    canonical_to_render_scene,
)
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
    strum_direction: str | None = None,
    note_step: str | None = None,
    note_accidental: str | None = None,
    note_octave: int | None = None,
    is_tie_dest: bool = False,
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
        strum_direction=strum_direction,
        note_step=note_step,
        note_accidental=note_accidental,
        note_octave=note_octave,
        is_tie_dest=is_tie_dest,
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


def test_canonical_to_render_scene_renders_all_systems_for_long_score() -> None:
    events = [
        _note(
            pitch=64 + (measure_idx % 5),
            onset=float(measure_idx * 4),
            string_hint=1,
            fret_hint=measure_idx % 7,
        )
        for measure_idx in range(20)
    ]
    raw_score = legacy_parse_to_raw_score(
        Path("long-song.gp"),
        source_format="gpif",
        events=events,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    page = result.render_scene.document_scene.pages[0]
    assert len(page.systems) >= 2

    ys = [system.y for system in page.systems]
    assert ys == sorted(ys)

    measure_labels = 0
    for system in page.systems:
        staff = system.staves[0]
        measure_labels += sum(
            1 for text in staff.layer_groups[1].text_instances
            if text.metadata.get("kind") == "measure_number"
        )
    assert measure_labels == len(events)


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


def test_svg_tab_note_text_exposes_core_overlay_metadata() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=0.5, string_hint=2, fret_hint=5)],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    svg = render_scene_to_svg(result.render_scene)

    assert 'class="fw-tab-note"' in svg
    assert 'data-tab-string="2"' in svg
    assert 'data-onset="0.000000"' in svg


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
    assert "<polygon " in svg


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
    assert svg.count("<polygon ") >= 2


def test_canonical_to_render_scene_standard_uses_voice_aware_stem_direction() -> None:
    # Both voices at the SAME onset: polyphonic rule forces Voice 0 up / Voice 1 down
    # regardless of pitch height.  Notes at different onsets use pitch-based direction.
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=2, fret_hint=5),
            _note(pitch=52, onset=0.0, duration=1.0, voice_hint=1, string_hint=5, fret_hint=3),
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


def test_canonical_to_render_scene_standard_sets_stem_direction_from_pitch_height() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("stem-pitch-height.gp"),
        source_format="gpif",
        events=[
            _note(pitch=79, onset=0.0, duration=1.0, voice_hint=0, string_hint=1, fret_hint=15),
            _note(pitch=57, onset=1.0, duration=1.0, voice_hint=0, string_hint=6, fret_hint=0),
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


def test_canonical_to_render_scene_standard_two_voices_force_outward_stems() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("stem-two-voices.gp"),
        source_format="gpif",
        events=[
            _note(pitch=79, onset=0.0, duration=1.0, voice_hint=0, string_hint=1, fret_hint=15),
            _note(pitch=55, onset=0.0, duration=1.0, voice_hint=1, string_hint=5, fret_hint=3),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    same_onset_stems = [
        recipe
        for recipe in staff.layer_groups[1].recipe_instances
        if recipe.recipe_id == "stem_line" and abs(float(recipe.metadata.get("onset", 1.0))) < 1e-6
    ]
    directions = {str(recipe.metadata.get("direction", "up")) for recipe in same_onset_stems}

    assert directions == {"up", "down"}


def test_canonical_to_render_scene_standard_uses_constant_unbeamed_stem_length() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("stem-constant-length.gp"),
        source_format="gpif",
        events=[
            _note(pitch=79, onset=0.0, duration=1.0, voice_hint=0, string_hint=1, fret_hint=15),
            _note(pitch=57, onset=1.0, duration=1.0, voice_hint=0, string_hint=6, fret_hint=0),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    staff_lines = next(
        recipe for recipe in staff.layer_groups[0].recipe_instances if recipe.recipe_id == "staff_lines"
    )
    staff_y = float(staff_lines.params.get("y", 0.0))
    spacing = float(staff_lines.params.get("spacing", 8.0))
    stem_top = staff_y - spacing
    stem_bottom = staff_y + 5.0 * spacing
    expected_length = float(staff_lines.params.get("spacing", 8.0)) * 3.5
    stems = [
        recipe
        for recipe in staff.layer_groups[1].recipe_instances
        if recipe.recipe_id == "stem_line"
    ]
    lengths = [
        abs(float(stem.params.get("y1", 0.0)) - float(stem.params.get("y0", 0.0)))
        for stem in stems
    ]

    assert len(lengths) >= 2
    for stem in stems:
        y0 = float(stem.params.get("y0", 0.0))
        y1 = float(stem.params.get("y1", 0.0))
        length = abs(y1 - y0)
        if abs(length - expected_length) < 0.1:
            continue
        # When a stem cannot keep the canonical 3.5-space length because it
        # is capped by the outer staff boundary, the endpoint sits on that cap.
        assert length < expected_length
        assert abs(y1 - stem_top) < 0.1 or abs(y1 - stem_bottom) < 0.1


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
            # Tie destination: same pitch as previous note, explicitly marked
            _note(pitch=66, onset=1.0, duration=0.5, string_hint=1, fret_hint=2, is_tie_dest=True),
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
            _note(pitch=55, onset=0.5, duration=0.5, voice_hint=1, string_hint=4, fret_hint=5,
                  is_tie_dest=True),
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
            _note(pitch=55, onset=2.0, duration=1.0, voice_hint=1, string_hint=4, fret_hint=5,
                  is_tie_dest=True),
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
    assert "♯" not in svg
    assert "<path " in svg


def test_canonical_to_render_scene_standard_prefers_note_spelling_accidental_hint() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(
                pitch=61,
                onset=0.0,
                duration=1.0,
                string_hint=2,
                fret_hint=2,
                note_step="D",
                note_accidental="flat",
                note_octave=5,
            )
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    note_glyph_ids = [g.glyph_id for g in staff.layer_groups[1].glyph_instances]

    assert "accidental_flat" in note_glyph_ids
    assert "accidental_sharp" not in note_glyph_ids


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


def test_canonical_to_render_scene_tablature_rhythm_emits_rhythm_recipes() -> None:
    score = Score(
        score_id="s-tab-rhythm",
        title="tab-rhythm",
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
                                                    CanonicalNoteEvent(
                                                        event_id="n1",
                                                        onset=0.0,
                                                        duration=0.5,
                                                        voice=0,
                                                        pitch_notated=64,
                                                        pitch_sounding=64,
                                                    ),
                                                    CanonicalNoteEvent(
                                                        event_id="n2",
                                                        onset=0.5,
                                                        duration=0.5,
                                                        voice=0,
                                                        pitch_notated=66,
                                                        pitch_sounding=66,
                                                    ),
                                                    RestEvent(
                                                        event_id="r1",
                                                        onset=1.0,
                                                        duration=0.5,
                                                        voice=0,
                                                    ),
                                                    CanonicalNoteEvent(
                                                        event_id="n3",
                                                        onset=1.5,
                                                        duration=0.5,
                                                        voice=0,
                                                        pitch_notated=67,
                                                        pitch_sounding=67,
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
        ],
    )

    scene = canonical_to_render_scene(score, mode=RepresentationMode.TAB_RHYTHM.value)
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [recipe.recipe_id for recipe in staff.layer_groups[1].recipe_instances]
    note_texts = [
        text.text
        for text in staff.layer_groups[1].text_instances
        if text.metadata.get("kind") == "note"
    ]
    rests = [glyph for glyph in staff.layer_groups[1].glyph_instances if glyph.glyph_id == "rest"]

    assert "stem_line" in recipe_ids
    assert "beam_group" in recipe_ids
    assert "flag_stack" in recipe_ids
    assert note_texts
    assert len(rests) == 1
    assert rests[0].metadata.get("mode") == "tablature_rhythm"


def test_canonical_to_render_scene_tablature_rhythm_anchors_time_signature_on_tab_plane() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("tab-rhythm-layout.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=0.5, string_hint=2, fret_hint=5)],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.TAB_RHYTHM,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    staff_layer = staff.layer_groups[0]
    time_signature = next(g for g in staff_layer.glyph_instances if g.glyph_id == "time_signature")
    tab_lines = next(r for r in staff_layer.recipe_instances if r.recipe_id == "tab_lines")
    tab_y = float(tab_lines.params.get("y", 0.0))
    tab_spacing = float(tab_lines.params.get("spacing", 10.0))

    assert abs(time_signature.y - (tab_y + 2.0 * tab_spacing)) < 0.01
    assert not any(text.metadata.get("kind") == "string_label" for text in staff_layer.text_instances)


def test_tuplet_brackets_are_mode_specific_between_standard_and_tab_rhythm_builders() -> None:
    standard_layer = LayerGroup(layer_id="standard")
    tab_rhythm_layer = LayerGroup(layer_id="tab-rhythm")
    tuplet_by_onset = {
        0.0: (3, 2),
        round(1.0 / 3.0, 6): (3, 2),
        round(2.0 / 3.0, 6): (3, 2),
    }

    scene_builders._append_standard_rhythm(
        standard_layer,
        measure_number=1,
        beats_per_measure=4,
        time_denominator=4,
        events=[
            (100.0, 0.0, 1.0 / 3.0, 60.0, "up"),
            (120.0, 1.0 / 3.0, 1.0 / 3.0, 58.0, "up"),
            (140.0, 2.0 / 3.0, 1.0 / 3.0, 56.0, "up"),
        ],
        stem_top_y=20.0,
        stem_bottom_y=100.0,
        staff_spacing=8.0,
        stem_offset=3.3,
        tuplet_by_onset=tuplet_by_onset,
    )
    scene_builders._append_tablature_rhythm(
        tab_rhythm_layer,
        measure_number=1,
        beats_per_measure=4,
        time_denominator=4,
        events=[
            (100.0, 0.0, 1.0 / 3.0, 96.0),
            (120.0, 1.0 / 3.0, 1.0 / 3.0, 96.0),
            (140.0, 2.0 / 3.0, 1.0 / 3.0, 96.0),
        ],
        tab_rhythm_beam_y=70.0,
        tuplet_by_onset=tuplet_by_onset,
    )

    standard_tuplets = [r for r in standard_layer.recipe_instances if r.recipe_id == "tuplet_bracket"]
    tab_rhythm_tuplets = [r for r in tab_rhythm_layer.recipe_instances if r.recipe_id == "tuplet_bracket"]
    tab_rhythm_beams = [r for r in tab_rhythm_layer.recipe_instances if r.recipe_id == "beam_group"]
    tab_rhythm_stems = [r for r in tab_rhythm_layer.recipe_instances if r.recipe_id == "stem_line"]

    assert len(standard_tuplets) == 1
    assert len(tab_rhythm_tuplets) == 1
    assert standard_tuplets[0].metadata.get("style") == "standard"
    assert tab_rhythm_tuplets[0].metadata.get("style") == "tablature_rhythm"
    assert tab_rhythm_tuplets[0].params.get("direction") == "down"
    # Bracket Y is below the beam (beam_y + 8), not above it
    assert float(tab_rhythm_tuplets[0].params.get("y", 999.0)) > 70.0
    assert tab_rhythm_beams
    assert float(tab_rhythm_beams[0].params.get("thickness", 0.0)) > 2.5
    assert tab_rhythm_stems
    assert float(tab_rhythm_stems[0].params.get("width", 0.0)) > 0.8


def test_svg_tuplet_brackets_use_distinct_styles_for_standard_tab_and_tab_rhythm() -> None:
    standard_layer = LayerGroup(
        layer_id="standard",
        recipe_instances=[
            scene_builders.RecipeInstance(
                recipe_id="tuplet_bracket",
                params={
                    "x0": 20.0,
                    "x1": 60.0,
                    "y": 30.0,
                    "number": 3,
                    "direction": "up",
                    "style": "standard",
                },
                metadata={"style": "standard"},
            )
        ],
    )
    tab_rhythm_layer = LayerGroup(
        layer_id="tab-rhythm",
        recipe_instances=[
            scene_builders.RecipeInstance(
                recipe_id="tuplet_bracket",
                params={
                    "x0": 20.0,
                    "x1": 60.0,
                    "y": 30.0,
                    "number": 3,
                    "direction": "up",
                    "style": "tablature_rhythm",
                },
                metadata={"style": "tablature_rhythm"},
            )
        ],
    )

    standard_svg = render_scene_to_svg(
        RenderScene(
            document_scene=DocumentScene(
                title="standard",
                pages=[
                    PageScene(
                        page_number=1,
                        width=120.0,
                        height=80.0,
                        systems=[
                            SystemScene(
                                system_id="sys1",
                                x=0.0,
                                y=0.0,
                                width=120.0,
                                height=80.0,
                                staves=[
                                    StaffScene(
                                        staff_id="st1",
                                        x=0.0,
                                        y=0.0,
                                        width=120.0,
                                        height=80.0,
                                        layer_groups=[standard_layer],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        )
    )
    tab_rhythm_svg = render_scene_to_svg(
        RenderScene(
            document_scene=DocumentScene(
                title="tab-rhythm",
                pages=[
                    PageScene(
                        page_number=1,
                        width=120.0,
                        height=80.0,
                        systems=[
                            SystemScene(
                                system_id="sys1",
                                x=0.0,
                                y=0.0,
                                width=120.0,
                                height=80.0,
                                staves=[
                                    StaffScene(
                                        staff_id="st1",
                                        x=0.0,
                                        y=0.0,
                                        width=120.0,
                                        height=80.0,
                                        layer_groups=[tab_rhythm_layer],
                                    )
                                ],
                            )
                        ],
                    )
                ],
            )
        )
    )

    assert 'font-size="8"' in standard_svg
    assert 'font-weight="bold"' not in standard_svg
    assert 'font-size="10"' in tab_rhythm_svg
    assert 'font-weight="bold"' in tab_rhythm_svg


def test_canonical_to_render_scene_standard_tab_uses_tab_letters_without_string_names() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("standard-tab-layout.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=1.0, string_hint=3, fret_hint=7)],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    staff_layer = staff.layer_groups[0]
    tab_labels = [t for t in staff_layer.text_instances if t.metadata.get("kind") == "tab_label"]

    assert [t.text for t in tab_labels] == ["T", "A", "B"]
    assert not any(text.metadata.get("kind") == "string_label" for text in staff_layer.text_instances)


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
    assert ">3</text>" in svg
    assert ">4</text>" in svg
    rest_glyphs = [g for g in staff.layer_groups[1].glyph_instances if g.glyph_id == "rest"]
    assert rest_glyphs
    assert rest_glyphs[0].metadata.get("rest_kind") == "quarter"


def test_canonical_to_render_scene_standard_marks_measure_rest_as_whole_symbol() -> None:
    score = Score(
        score_id="s-rest-measure",
        title="measure-rest",
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
                                                        event_id="r-full",
                                                        onset=0.0,
                                                        duration=3.0,
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

    scene = canonical_to_render_scene(score, mode=RepresentationMode.STANDARD.value)
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    rests = [g for g in staff.layer_groups[1].glyph_instances if g.glyph_id == "rest"]

    assert len(rests) == 1
    assert rests[0].metadata.get("rest_kind") == "whole"
    assert rests[0].metadata.get("is_measure_rest") == "true"


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


def test_canonical_to_render_scene_standard_groups_chord_stems_by_onset() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("chord-stems.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=0.5, string_hint=1, fret_hint=0),
            _note(pitch=52, onset=0.0, duration=0.5, string_hint=5, fret_hint=3),
            _note(pitch=66, onset=0.5, duration=0.5, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    stem_recipes = [
        recipe
        for recipe in staff.layer_groups[1].recipe_instances
        if recipe.recipe_id == "stem_line"
    ]

    assert len(stem_recipes) == 2


def test_canonical_to_render_scene_standard_draws_chord_names_from_markers() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("chord-marker.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=1.0, string_hint=2, fret_hint=2)],
        chord_markers={"0.000000": "A5"},
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    chord_labels = [
        text
        for text in staff.layer_groups[1].text_instances
        if text.metadata.get("kind") == "chord_name"
    ]

    assert len(chord_labels) == 1
    assert chord_labels[0].text == "A5"


def test_canonical_to_render_scene_standard_tab_draws_strum_direction_marker() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("strum-marker.gp"),
        source_format="gpif",
        events=[
            _note(
                pitch=64,
                onset=0.0,
                duration=1.0,
                string_hint=2,
                fret_hint=2,
                strum_direction="down",
            )
        ],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    strum_marks = [
        text
        for text in staff.layer_groups[1].text_instances
        if text.metadata.get("kind") == "strum_direction"
    ]

    assert len(strum_marks) == 1
    assert strum_marks[0].text == "↓"
    assert strum_marks[0].metadata.get("direction") == "down"


def test_canonical_to_render_scene_standard_displaces_colliding_chord_noteheads() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("chord-collision-offset.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=2, fret_hint=2),
            _note(pitch=65, onset=0.0, duration=1.0, voice_hint=0, string_hint=3, fret_hint=3),
            _note(pitch=67, onset=1.0, duration=1.0, voice_hint=0, string_hint=2, fret_hint=5),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    notes_layer = staff.layer_groups[1]
    chord_noteheads = [
        glyph
        for glyph in notes_layer.glyph_instances
        if glyph.glyph_id == "notehead" and abs(float(glyph.metadata.get("onset", 9.0))) < 1e-6
    ]
    xs = [glyph.x for glyph in chord_noteheads]
    stem = next(
        recipe
        for recipe in notes_layer.recipe_instances
        if recipe.recipe_id == "stem_line" and abs(float(recipe.metadata.get("onset", 9.0))) < 1e-6
    )
    stem_x = float(stem.params.get("x", 0.0))
    stem_direction = str(stem.metadata.get("direction", "up"))

    assert len(chord_noteheads) == 2
    assert (max(xs) - min(xs)) > 2.0
    # The stem is anchored to the un-displaced notehead (the canonical beat x).
    # Displaced noteheads (2nd-interval avoidance) sit on the OPPOSITE side of
    # the stem from the regular noteheads, so the stem x falls BETWEEN the two
    # notehead x positions regardless of stem direction.
    assert min(xs) < stem_x < max(xs)


def test_canonical_to_render_scene_standard_stacks_dense_unisons_without_agglomeration() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("dense-unison-stack.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=2, fret_hint=2),
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=3, fret_hint=7),
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=4, fret_hint=12),
            _note(pitch=64, onset=0.0, duration=1.0, voice_hint=0, string_hint=5, fret_hint=17),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    noteheads = [
        glyph
        for glyph in staff.layer_groups[1].glyph_instances
        if glyph.glyph_id == "notehead" and abs(float(glyph.metadata.get("onset", 9.0))) < 1e-6
    ]

    assert len(noteheads) == 1


def test_canonical_to_render_scene_standard_marks_notehead_fill_by_duration() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("notehead-fill.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=2.0, string_hint=2, fret_hint=5),
            _note(pitch=66, onset=2.0, duration=1.0, string_hint=2, fret_hint=7),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    noteheads = [g for g in staff.layer_groups[1].glyph_instances if g.glyph_id == "notehead"]
    by_event = {str(g.metadata.get("event_id")): g for g in noteheads}

    assert by_event["n0"].metadata.get("filled") is False
    assert by_event["n1"].metadata.get("filled") is True


def test_canonical_to_render_scene_standard_marks_dotted_and_double_dotted_noteheads() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("dotted-notes.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.5, string_hint=2, fret_hint=5),
            _note(pitch=66, onset=2.0, duration=1.75, string_hint=2, fret_hint=7),
        ],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    noteheads = [g for g in staff.layer_groups[1].glyph_instances if g.glyph_id == "notehead"]
    by_event = {str(g.metadata.get("event_id")): g for g in noteheads}

    assert by_event["n0"].metadata.get("dot_count") == 1
    assert by_event["n1"].metadata.get("dot_count") == 2


def test_canonical_to_render_scene_standard_marks_dotted_rests() -> None:
    score = Score(
        score_id="s-dotted-rests",
        title="dotted-rests",
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
                                                        event_id="r-dot",
                                                        onset=0.0,
                                                        duration=1.5,
                                                        voice=0,
                                                    ),
                                                    RestEvent(
                                                        event_id="r-double-dot",
                                                        onset=2.0,
                                                        duration=1.75,
                                                        voice=0,
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
        ],
    )

    scene = canonical_to_render_scene(score, mode=RepresentationMode.STANDARD.value)
    staff = scene.document_scene.pages[0].systems[0].staves[0]
    rests = {
        str(glyph.metadata.get("event_id")): glyph
        for glyph in staff.layer_groups[1].glyph_instances
        if glyph.glyph_id == "rest"
    }

    assert rests["r-dot"].metadata.get("dot_count") == 1
    assert rests["r-double-dot"].metadata.get("dot_count") == 2
    assert rests["r-dot"].metadata.get("rest_kind") == "quarter"
    assert rests["r-double-dot"].metadata.get("rest_kind") == "quarter"


def test_canonical_to_render_scene_adds_measure_barlines() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("barlines.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=4.0, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    staff_layer = staff.layer_groups[0]
    barlines = [recipe for recipe in staff_layer.recipe_instances if recipe.recipe_id == "barline"]

    assert len(barlines) >= 1


def test_canonical_to_render_scene_standard_attaches_up_stem_on_notehead_right_side() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("stem-up.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, duration=0.5, voice_hint=0, string_hint=2, fret_hint=5)],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    notes_layer = staff.layer_groups[1]
    notehead = next(g for g in notes_layer.glyph_instances if g.glyph_id == "notehead")
    stem = next(r for r in notes_layer.recipe_instances if r.recipe_id == "stem_line")
    stem_direction = str(stem.metadata.get("direction", "up"))

    if stem_direction == "up":
        assert stem.params["x"] > notehead.x
    else:
        assert stem.params["x"] < notehead.x


def test_canonical_to_render_scene_standard_attaches_down_stem_on_notehead_left_side() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("stem-down.gp"),
        source_format="gpif",
        events=[_note(pitch=52, onset=0.0, duration=0.5, voice_hint=1, string_hint=5, fret_hint=3)],
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.STANDARD)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    notes_layer = staff.layer_groups[1]
    notehead = next(g for g in notes_layer.glyph_instances if g.glyph_id == "notehead")
    stem = next(r for r in notes_layer.recipe_instances if r.recipe_id == "stem_line")

    assert stem.params["x"] < notehead.x


def test_canonical_to_render_scene_standard_tab_shows_rests_without_tab_digits() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("rests-standard-tab.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=0.5, string_hint=2, fret_hint=5),
            _note(pitch=66, onset=2.0, duration=0.5, string_hint=2, fret_hint=7),
        ],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    notes_layer = staff.layer_groups[1]
    rests = [g for g in notes_layer.glyph_instances if g.glyph_id == "rest"]
    tab_note_texts = [t for t in notes_layer.text_instances if t.metadata.get("kind") == "note"]

    assert rests
    assert all(not str(t.metadata.get("event_id", "")).startswith("r-") for t in tab_note_texts)


def test_canonical_to_render_scene_tablature_rhythm_emits_tuplet_bracket() -> None:
    """Three triplet-8th notes in one beat must produce exactly one tuplet_bracket."""
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=60, onset=0.0, duration=1 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=0,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=62, onset=1 / 3, duration=1 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=2,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=64, onset=2 / 3, duration=1 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=4,
                tuplet_actual=3, tuplet_normal=2,
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("tablature_rhythm"),
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for lg in staff.layer_groups for r in lg.recipe_instances]
    tuplet_recipes = [
        r
        for lg in staff.layer_groups
        for r in lg.recipe_instances
        if r.recipe_id == "tuplet_bracket"
    ]

    assert "tuplet_bracket" in recipe_ids, "Expected at least one tuplet_bracket recipe"
    assert len(tuplet_recipes) == 1, f"Expected 1 bracket for 3 triplet notes, got {len(tuplet_recipes)}"
    bracket = tuplet_recipes[0]
    assert bracket.params["number"] == 3


def test_canonical_to_render_scene_tab_slide_connects_across_measures() -> None:
    """A slide at the end of measure 1 must connect to the first note of measure 2."""
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=57, onset=0.0, duration=1.0,
                tempo=120.0, articulation=Articulation.SLIDE, dynamic=Dynamic.MF,
                string_hint=4, fret_hint=7,
                slide_type="shift",
            ),
            NoteEvent(
                pitch=60, onset=4.0, duration=1.0,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=4, fret_hint=10,
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("tablature_rhythm"),
    )
    slide_recipes = [
        r
        for p in result.render_scene.document_scene.pages
        for s in p.systems
        for st in s.staves
        for lg in st.layer_groups
        for r in lg.recipe_instances
        if r.recipe_id == "tab_slide_line"
    ]
    assert len(slide_recipes) == 1, (
        f"Expected 1 cross-measure slide line, got {len(slide_recipes)}"
    )


def test_canonical_to_render_scene_standard_uses_diamond_notehead_for_harmonics() -> None:
    """A note with harmonic_type='natural' must render a diamond (notehead_harmonic) glyph."""
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=76, onset=0.0, duration=1.0,
                tempo=120.0, articulation=Articulation.HARMONIC, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=12,
                harmonic_type="natural",
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("standard_tablature"),
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    glyph_ids = [g.glyph_id for lg in staff.layer_groups for g in lg.glyph_instances]

    assert "notehead_harmonic" in glyph_ids, (
        f"Expected 'notehead_harmonic' glyph for harmonic note, found: {set(glyph_ids)}"
    )

    svg = render_scene_to_svg(result.render_scene)
    assert 'class="fw-notehead-harmonic"' in svg


def test_canonical_to_render_scene_tablature_rhythm_emits_bracket_for_triplet_quarters() -> None:
    """Three triplet quarter notes (dur=2/3) must produce exactly one tuplet_bracket.

    These notes don't enter short_stems (base_dur==1.0 not < 1.0) so they never
    form a beam group.  The standalone bracket emitter must catch them.
    """
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=60, onset=0.0, duration=2 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=0,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=62, onset=2 / 3, duration=2 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=2,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=64, onset=4 / 3, duration=2 / 3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=4,
                tuplet_actual=3, tuplet_normal=2,
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("tablature_rhythm"),
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    tuplet_recipes = [
        r
        for lg in staff.layer_groups
        for r in lg.recipe_instances
        if r.recipe_id == "tuplet_bracket"
    ]
    assert len(tuplet_recipes) == 1, (
        f"Expected 1 tuplet_bracket for 3 triplet quarter notes, got {len(tuplet_recipes)}"
    )
    assert tuplet_recipes[0].params["number"] == 3


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
