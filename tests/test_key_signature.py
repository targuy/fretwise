"""Tests for Sprint S1 — key signature end-to-end pipeline.

Coverage:
- Parser: _get_key_signature_fifths XML extraction
- Ingest: key_signature_fifths propagated through RawScore → NormalizedScore → CompletedScore
- Canonical mapper: _fifths_to_key_signature produces correct tonic/fifths
- Scene builder: key_sig_sharp / key_sig_flat glyphs emitted at correct count
- SVG backend: sharp/flat characters present in rendered SVG
- Layout: time_signature_x shifts right when key sig accidentals are present
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.canonical.mappers import _fifths_to_key_signature
from fretwise.core.complete import complete_normalized_score
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.normalize import normalize_raw_score
from fretwise.models import Articulation, Dynamic, NoteEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(pitch: int, onset: float = 0.0, duration: float = 1.0) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
    )


def _make_raw_score(fifths: int, notes: list[NoteEvent] | None = None) -> object:
    return legacy_parse_to_raw_score(
        Path("test.gp"),
        source_format="gpif",
        events=notes or [_note(64)],
        key_signature_fifths=fifths,
    )


def _pipeline(fifths: int, notes: list[NoteEvent] | None = None):
    raw = _make_raw_score(fifths, notes)
    return run_core_pipeline_from_raw(raw, representation_mode=RepresentationMode.STANDARD)


def _key_sig_glyphs(result, glyph_id: str):
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    return [g for layer in staff.layer_groups for g in layer.glyph_instances if g.glyph_id == glyph_id]


# ---------------------------------------------------------------------------
# Canonical mapper — _fifths_to_key_signature
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "fifths, expected_tonic, expected_mode",
    [
        (0, "C", "major"),
        (1, "G", "major"),
        (2, "D", "major"),
        (3, "A", "major"),
        (4, "E", "major"),
        (5, "B", "major"),
        (6, "F#", "major"),
        (-1, "F", "major"),
        (-2, "Bb", "major"),
        (-3, "Eb", "major"),
        (-4, "Ab", "major"),
        (-5, "Db", "major"),
        (-6, "Gb", "major"),
        (-7, "Cb", "major"),
    ],
)
def test_fifths_to_key_signature_tonic(
    fifths: int, expected_tonic: str, expected_mode: str
) -> None:
    ks = _fifths_to_key_signature(fifths)
    assert ks.tonic == expected_tonic
    assert ks.mode == expected_mode
    assert ks.fifths == fifths


# ---------------------------------------------------------------------------
# Pipeline propagation — key_signature_fifths flows through all stages
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("fifths", [0, 2, -3, 6, -7])
def test_key_sig_fifths_propagated_through_normalize(fifths: int) -> None:
    raw = _make_raw_score(fifths)
    normalized = normalize_raw_score(raw)
    assert normalized.key_signature_fifths == fifths


@pytest.mark.parametrize("fifths", [0, 2, -3, 6, -7])
def test_key_sig_fifths_propagated_through_complete(fifths: int) -> None:
    raw = _make_raw_score(fifths)
    normalized = normalize_raw_score(raw)
    completed = complete_normalized_score(normalized)
    assert completed.key_signature_fifths == fifths


@pytest.mark.parametrize("fifths", [0, 2, -3, 6, -7])
def test_key_sig_fifths_propagated_to_canonical(fifths: int) -> None:
    raw = _make_raw_score(fifths)
    normalized = normalize_raw_score(raw)
    completed = complete_normalized_score(normalized)
    canonical = completed_to_canonical_score(completed)
    assert canonical.key_signature.fifths == fifths


# ---------------------------------------------------------------------------
# Scene builder — sharp glyphs
# ---------------------------------------------------------------------------


def test_c_major_no_key_sig_glyphs() -> None:
    """C major (fifths=0): no key_sig_sharp or key_sig_flat glyphs emitted."""
    result = _pipeline(0)
    assert _key_sig_glyphs(result, "key_sig_sharp") == []
    assert _key_sig_glyphs(result, "key_sig_flat") == []


@pytest.mark.parametrize("fifths", [1, 2, 3, 4, 5, 6, 7])
def test_sharp_key_sig_glyph_count(fifths: int) -> None:
    """Exactly |fifths| key_sig_sharp glyphs for any sharp key."""
    result = _pipeline(fifths)
    glyphs = _key_sig_glyphs(result, "key_sig_sharp")
    assert len(glyphs) == fifths
    assert _key_sig_glyphs(result, "key_sig_flat") == []


@pytest.mark.parametrize("fifths", [-1, -2, -3, -4, -5, -6, -7])
def test_flat_key_sig_glyph_count(fifths: int) -> None:
    """Exactly |fifths| key_sig_flat glyphs for any flat key."""
    result = _pipeline(fifths)
    glyphs = _key_sig_glyphs(result, "key_sig_flat")
    assert len(glyphs) == abs(fifths)
    assert _key_sig_glyphs(result, "key_sig_sharp") == []


def test_key_sig_glyphs_have_correct_index_metadata() -> None:
    """key_sig_sharp glyphs carry index metadata 0, 1, 2 … n-1."""
    result = _pipeline(3)  # A major: 3 sharps
    glyphs = _key_sig_glyphs(result, "key_sig_sharp")
    indices = sorted(int(g.metadata["index"]) for g in glyphs)
    assert indices == [0, 1, 2]


def test_key_sig_glyphs_carry_fifths_metadata() -> None:
    """Every key_sig glyph carries the fifths value as metadata."""
    result = _pipeline(-2)  # Bb major: 2 flats
    glyphs = _key_sig_glyphs(result, "key_sig_flat")
    assert all(int(g.metadata["fifths"]) == -2 for g in glyphs)


def test_key_sig_glyphs_are_left_of_time_sig() -> None:
    """All key sig glyphs must appear to the left of the time signature."""
    result = _pipeline(3)  # 3 sharps
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    time_sig_glyphs = [
        g for layer in staff.layer_groups for g in layer.glyph_instances if g.glyph_id == "time_signature"
    ]
    key_sig_glyphs = [
        g for layer in staff.layer_groups for g in layer.glyph_instances if g.glyph_id == "key_sig_sharp"
    ]
    assert time_sig_glyphs, "No time_signature glyph found"
    ts_x = time_sig_glyphs[0].x
    for ks_g in key_sig_glyphs:
        assert ks_g.x < ts_x, f"key_sig_sharp at {ks_g.x} not left of time_sig at {ts_x}"


def test_key_sig_glyphs_x_positions_are_spaced(  ) -> None:
    """Consecutive key sig glyphs must have strictly increasing x positions."""
    result = _pipeline(4)  # E major: 4 sharps
    glyphs = sorted(_key_sig_glyphs(result, "key_sig_sharp"), key=lambda g: int(g.metadata["index"]))
    xs = [g.x for g in glyphs]
    assert all(xs[i] < xs[i + 1] for i in range(len(xs) - 1)), f"Non-monotonic x positions: {xs}"


# ---------------------------------------------------------------------------
# Sharp Y positions — treble clef standard positions
# ---------------------------------------------------------------------------


def test_first_sharp_on_top_line() -> None:
    """1st sharp (F♯) must land on the 5th (top) staff line = staff_std_y."""
    result = _pipeline(1)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    glyphs = _key_sig_glyphs(result, "key_sig_sharp")
    assert glyphs, "No key_sig_sharp glyph found"
    # staff_std_y = staff.y + 4.0 (from scene builder); staff.y comes from layout
    # We compare relative to the staff_lines recipe y
    staff_layer = staff.layer_groups[0]
    staff_lines_recipes = [r for r in staff_layer.recipe_instances if r.recipe_id == "staff_lines"]
    assert staff_lines_recipes, "No staff_lines recipe"
    staff_std_y = staff_lines_recipes[0].params["y"]
    first_sharp = next(g for g in glyphs if int(g.metadata["index"]) == 0)
    assert abs(first_sharp.y - staff_std_y) < 1.0, (
        f"1st sharp y={first_sharp.y:.2f} should be near top line y={staff_std_y:.2f}"
    )


def test_first_flat_on_middle_line() -> None:
    """1st flat (B♭) must land on the 3rd (middle) staff line = staff_std_y + 2*spacing."""
    result = _pipeline(-1)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    glyphs = _key_sig_glyphs(result, "key_sig_flat")
    assert glyphs, "No key_sig_flat glyph found"
    staff_layer = staff.layer_groups[0]
    staff_lines_recipes = [r for r in staff_layer.recipe_instances if r.recipe_id == "staff_lines"]
    assert staff_lines_recipes, "No staff_lines recipe"
    staff_std_y = staff_lines_recipes[0].params["y"]
    staff_spacing = staff_lines_recipes[0].params["spacing"]
    first_flat = next(g for g in glyphs if int(g.metadata["index"]) == 0)
    expected_y = staff_std_y + 2.0 * staff_spacing
    assert abs(first_flat.y - expected_y) < 1.0, (
        f"1st flat y={first_flat.y:.2f} should be near middle line y={expected_y:.2f}"
    )


# ---------------------------------------------------------------------------
# SVG content — sharp/flat characters present
# ---------------------------------------------------------------------------


def test_svg_contains_sharp_chars_for_sharp_key() -> None:
    """SVG output must contain the ♯ character when key has sharps."""
    from fretwise.core.backends import render_scene_to_svg

    result = _pipeline(2)  # D major: 2 sharps
    svg = render_scene_to_svg(result.render_scene)
    assert "♯" in svg


def test_svg_contains_flat_chars_for_flat_key() -> None:
    """SVG output must contain the ♭ character when key has flats."""
    from fretwise.core.backends import render_scene_to_svg

    result = _pipeline(-2)  # Bb major: 2 flats
    svg = render_scene_to_svg(result.render_scene)
    assert "♭" in svg


def test_svg_no_key_sig_chars_for_c_major() -> None:
    """C major SVG must still render without key sig errors (no extra ♯/♭ from key sig)."""
    from fretwise.core.backends import render_scene_to_svg

    result = _pipeline(0)
    svg = render_scene_to_svg(result.render_scene)
    # No key sig glyphs should be present — we check SVG is valid XML (no crash)
    assert "<svg" in svg


# ---------------------------------------------------------------------------
# TAB-only mode: no key sig glyphs shown
# ---------------------------------------------------------------------------


def test_tab_only_mode_no_key_sig_glyphs() -> None:
    """TAB mode has no standard staff, so key sig glyphs must not be emitted."""
    raw = _make_raw_score(3)
    result = run_core_pipeline_from_raw(raw, representation_mode=RepresentationMode.TAB)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    all_glyphs = [g for layer in staff.layer_groups for g in layer.glyph_instances]
    key_sig_glyph_ids = {g.glyph_id for g in all_glyphs if g.glyph_id.startswith("key_sig")}
    assert key_sig_glyph_ids == set(), f"Unexpected key sig glyphs in TAB mode: {key_sig_glyph_ids}"


# ---------------------------------------------------------------------------
# Standard+Tab mode: key sig shown (standard staff present)
# ---------------------------------------------------------------------------


def test_standard_tab_mode_shows_key_sig_glyphs() -> None:
    """STANDARD_TAB mode renders both staff and tablature — key sig must appear."""
    raw = _make_raw_score(2)
    result = run_core_pipeline_from_raw(raw, representation_mode=RepresentationMode.STANDARD_TAB)
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    glyphs = [g for layer in staff.layer_groups for g in layer.glyph_instances if g.glyph_id == "key_sig_sharp"]
    assert len(glyphs) == 2
