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
    *, pitch: int, onset: float, string_hint: int | None = None, fret_hint: int | None = None
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


def test_default_notation_policy_symbol_rules() -> None:
    policy = default_notation_policy()
    assert policy.is_allowed(RepresentationMode.TAB, "tab_lines")
    assert policy.is_allowed(RepresentationMode.STANDARD, "staff_lines")
    assert policy.is_allowed(RepresentationMode.TAB_RHYTHM, "tab_digit")
    assert not policy.is_allowed(RepresentationMode.STANDARD, "tab_digit")
    assert not policy.is_allowed(RepresentationMode.STANDARD, "tab_lines")
    assert not policy.is_allowed(RepresentationMode.TAB, "staff_lines")


def test_default_reference_glyph_set_has_expected_glyphs() -> None:
    glyphs = default_reference_glyph_set()
    assert "clef_treble" in glyphs
    assert "rest_quarter" in glyphs
    assert "tab_digit_0" in glyphs


def test_default_recipe_catalog_has_expected_recipes() -> None:
    recipes = default_recipe_catalog()
    assert "tab_lines" in recipes
    assert "tie_arc" in recipes
    assert "beam_group" in recipes
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
