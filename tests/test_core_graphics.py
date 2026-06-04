"""Tests for graphics policy, recipe catalog, and conformance checks."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.graphics import (
    RepresentationMode,
    check_scene_conformance,
    default_notation_policy,
    default_recipe_catalog,
    default_reference_glyph_set,
)
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    duration: float = 1.0,
    string_hint: int | None = None,
    fret_hint: int | None = None,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=string_hint,
        fret_hint=fret_hint,
    )


def test_default_notation_policy_symbol_rules() -> None:
    policy = default_notation_policy()
    assert policy.is_allowed(RepresentationMode.TAB, "tab_lines")
    assert policy.is_allowed(RepresentationMode.STANDARD, "staff_lines")
    assert policy.is_allowed(RepresentationMode.STANDARD, "accidental_sharp")
    assert policy.is_allowed(RepresentationMode.STANDARD, "accidental_flat")
    assert policy.is_allowed(RepresentationMode.STANDARD, "stem_line")
    assert policy.is_allowed(RepresentationMode.STANDARD, "flag_stack")
    assert policy.is_allowed(RepresentationMode.STANDARD, "beam_group")
    assert policy.is_allowed(RepresentationMode.STANDARD, "tie_arc")
    assert policy.is_allowed(RepresentationMode.STANDARD, "slur_arc")
    assert policy.is_allowed(RepresentationMode.STANDARD, "ledger_line")
    assert policy.is_allowed(RepresentationMode.TAB, "barline")
    assert policy.is_allowed(RepresentationMode.TAB, "let_ring_span")
    assert policy.is_allowed(RepresentationMode.TAB, "palm_mute_span")
    assert policy.is_allowed(RepresentationMode.TAB_RHYTHM, "tab_digit")
    assert not policy.is_allowed(RepresentationMode.STANDARD, "tab_digit")
    assert not policy.is_allowed(RepresentationMode.STANDARD, "tab_lines")
    assert not policy.is_allowed(RepresentationMode.TAB, "stem_line")
    assert not policy.is_allowed(RepresentationMode.TAB, "tie_arc")
    assert not policy.is_allowed(RepresentationMode.TAB, "accidental_sharp")
    assert not policy.is_allowed(RepresentationMode.TAB, "flag_stack")
    assert not policy.is_allowed(RepresentationMode.TAB, "staff_lines")


def test_default_reference_glyph_set_has_expected_glyphs() -> None:
    glyphs = default_reference_glyph_set()
    assert "clef_treble" in glyphs
    assert "rest_quarter" in glyphs
    assert "tab_digit_0" in glyphs


def test_render_glyph_clef_branches_on_metadata_clef() -> None:
    from fretwise.core.backends.svg import _render_glyph

    treble = _render_glyph("clef", x=0.0, y=0.0, size=20.0, metadata={"clef": "treble"})
    bass = _render_glyph("clef", x=0.0, y=0.0, size=20.0, metadata={"clef": "bass"})
    perc = _render_glyph("clef", x=0.0, y=0.0, size=20.0, metadata={"clef": "percussion"})

    # Treble and bass draw distinct Unicode musical symbols.
    assert "\U0001D11E" in treble and "fw-clef-treble" in treble
    assert "\U0001D122" in bass and "fw-clef-bass" in bass
    assert "\U0001D11E" not in bass and "\U0001D122" not in treble
    # Percussion draws a font-free neutral clef: two <rect> bars, not a font
    # glyph (the Unicode drum-clef char is missing from common browser fonts).
    assert "fw-clef-percussion" in perc
    assert perc.count("<rect") == 2
    assert "\U0001D125" not in perc and "\U0001D11E" not in perc


def test_render_glyph_clef_defaults_to_treble_without_metadata() -> None:
    from fretwise.core.backends.svg import _render_glyph

    rendered = _render_glyph("clef", x=0.0, y=0.0, size=20.0, metadata={})
    assert "\U0001D11E" in rendered
    assert "fw-clef-treble" in rendered


def test_default_recipe_catalog_has_expected_recipes() -> None:
    recipes = default_recipe_catalog()
    assert "tab_lines" in recipes
    assert "tie_arc" in recipes
    assert "beam_group" in recipes
    assert "flag_stack" in recipes
    assert "barline" in recipes
    assert "ledger_line" in recipes
    assert "bend_curve" in recipes


def test_scene_conformance_accepts_tab_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene
    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.TAB,
        policy=default_notation_policy(),
    )
    assert issues == []


def test_scene_conformance_flags_tab_symbols_in_standard_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(raw_score).render_scene
    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD,
        policy=default_notation_policy(),
    )
    symbols = {issue.symbol_id for issue in issues}
    assert "tab_lines" in symbols
    assert "tab_digit" in symbols


def test_pipeline_exposes_conformance_issues_for_standard_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD,
    )

    assert result.conformance_issues == []


def test_pipeline_standard_tablature_mode_is_conformant() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )

    assert result.conformance_issues == []


def test_pipeline_standard_mode_dotted_values_are_conformant() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("dotted-song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=1.5, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=2.0, duration=1.75, string_hint=1, fret_hint=2),
        ],
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD,
    )

    assert result.conformance_issues == []


def test_scene_conformance_flags_missing_standard_anchor_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    notes_layer.glyph_instances = []

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-102" for issue in issues)


def test_scene_conformance_flags_horizontal_misalignment_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    notes_layer.glyph_instances[0] = replace(
        notes_layer.glyph_instances[0],
        x=notes_layer.glyph_instances[0].x + 5.0,
    )

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-103" for issue in issues)


def test_scene_conformance_flags_missing_tab_plane_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    staff_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[0]
    staff_layer.recipe_instances = [
        recipe for recipe in staff_layer.recipe_instances if recipe.recipe_id != "tab_lines"
    ]

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-105" for issue in issues)


def test_scene_conformance_flags_plane_overlap_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    staff_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[0]
    tab_idx = next(
        idx
        for idx, recipe in enumerate(staff_layer.recipe_instances)
        if recipe.recipe_id == "tab_lines"
    )
    tab_recipe = staff_layer.recipe_instances[tab_idx]
    tab_params = dict(tab_recipe.params)
    tab_params["y"] = 70.0
    staff_layer.recipe_instances[tab_idx] = replace(tab_recipe, params=tab_params)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-106" for issue in issues)


def test_scene_conformance_flags_tab_anchor_outside_plane_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    note_idx = next(
        idx
        for idx, text in enumerate(notes_layer.text_instances)
        if text.metadata.get("kind") == "note"
    )
    notes_layer.text_instances[note_idx] = replace(notes_layer.text_instances[note_idx], y=72.0)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-108" for issue in issues)


def test_scene_conformance_flags_tab_string_row_mismatch_in_hybrid_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    note_idx = next(
        idx
        for idx, text in enumerate(notes_layer.text_instances)
        if text.metadata.get("kind") == "note"
    )
    note = notes_layer.text_instances[note_idx]
    metadata = dict(note.metadata)
    metadata["tab_string"] = "6"
    notes_layer.text_instances[note_idx] = replace(note, metadata=metadata)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD_TAB,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-109" for issue in issues)


def test_scene_conformance_flags_invalid_stem_direction_in_standard_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    stem_idx = next(
        idx
        for idx, recipe in enumerate(notes_layer.recipe_instances)
        if recipe.recipe_id == "stem_line"
    )
    stem = notes_layer.recipe_instances[stem_idx]
    metadata = dict(stem.metadata)
    metadata["direction"] = "sideways"
    notes_layer.recipe_instances[stem_idx] = replace(stem, metadata=metadata)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-201" for issue in issues)


def test_scene_conformance_flags_invalid_stem_geometry_in_standard_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    stem_idx = next(
        idx
        for idx, recipe in enumerate(notes_layer.recipe_instances)
        if recipe.recipe_id == "stem_line"
    )
    stem = notes_layer.recipe_instances[stem_idx]
    params = dict(stem.params)
    y0 = float(params.get("y0", 0.0))
    direction = str(stem.metadata.get("direction", "up"))
    # Force an invalid geometry whatever the current stem direction is.
    params["y1"] = y0 + 5.0 if direction == "up" else y0 - 5.0
    notes_layer.recipe_instances[stem_idx] = replace(stem, params=params)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-202" for issue in issues)


def test_scene_conformance_flags_invalid_beam_direction_in_standard_mode() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, duration=0.5, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=0.5, duration=0.5, string_hint=1, fret_hint=2),
        ],
    )
    scene = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD,
    ).render_scene

    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    beam_idx = next(
        idx
        for idx, recipe in enumerate(notes_layer.recipe_instances)
        if recipe.recipe_id == "beam_group"
    )
    beam = notes_layer.recipe_instances[beam_idx]
    params = dict(beam.params)
    params["direction"] = "sideways"
    notes_layer.recipe_instances[beam_idx] = replace(beam, params=params)

    issues = check_scene_conformance(
        scene,
        mode=RepresentationMode.STANDARD,
        policy=default_notation_policy(),
    )

    assert any(issue.code == "CONF-203" for issue in issues)
