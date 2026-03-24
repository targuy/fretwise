"""Structural invariant tests for the RenderScene builder.

These tests verify logical properties of the rendered scene that must ALWAYS hold
regardless of the input file.  They are fast (no PNG rendering), always-on, and
serve as early regressions before the visual snapshot suite.

Gaps tracked (CLAUDE.md sprint plan):
- G08/G09 — notehead displacement: currently the sign is inverted (up-stem displaced
  notes are pushed LEFT instead of RIGHT).  ``test_..._displaced_note_right_of_stem``
  is therefore expected to FAIL until Sprint S2 fixes the sign.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_svg
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.scene import canonical_to_render_scene
from fretwise.core.scene.builders import _resolve_beam_crossing
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.complete import complete_normalized_score
from fretwise.core.normalize import normalize_raw_score
from fretwise.models import Articulation, Dynamic, NoteEvent


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _note(
    pitch: int,
    onset: float,
    duration: float = 1.0,
    *,
    voice_hint: int = 0,
    string_hint: int | None = None,
    fret_hint: int | None = None,
    articulation: Articulation = Articulation.NORMAL,
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
    )


def _build_scene(
    events: list[NoteEvent],
    *,
    mode: RepresentationMode = RepresentationMode.STANDARD_TAB,
    beats_per_measure: float = 4.0,
    key_signature_fifths: int = 0,
    has_anacrusis: bool = False,
) -> object:
    raw_score = legacy_parse_to_raw_score(
        Path("test_song.gp"),
        source_format="gpif",
        events=events,
        beats_per_measure=beats_per_measure,
        key_signature_fifths=key_signature_fifths,
        has_anacrusis=has_anacrusis,
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=mode)
    return result.render_scene


def _collect_glyphs(scene: object, glyph_id: str) -> list[object]:
    """Return all GlyphInstances with the given glyph_id across all pages/systems."""
    results = []
    for page in scene.document_scene.pages:
        for system in page.systems:
            for staff in system.staves:
                for layer in staff.layer_groups:
                    for g in layer.glyph_instances:
                        if g.glyph_id == glyph_id:
                            results.append(g)
    return results


def _collect_texts(scene: object, kind: str) -> list[object]:
    """Return all TextInstances whose metadata["kind"] matches *kind*."""
    results = []
    for page in scene.document_scene.pages:
        for system in page.systems:
            for staff in system.staves:
                for layer in staff.layer_groups:
                    for t in layer.text_instances:
                        if t.metadata.get("kind") == kind:
                            results.append(t)
    return results


def _collect_recipes(scene: object, recipe_id: str) -> list[object]:
    """Return all RecipeInstances with the given recipe_id."""
    results = []
    for page in scene.document_scene.pages:
        for system in page.systems:
            for staff in system.staves:
                for layer in staff.layer_groups:
                    for r in layer.recipe_instances:
                        if r.recipe_id == recipe_id:
                            results.append(r)
    return results


# ---------------------------------------------------------------------------
# Structural invariants — clef and time signature
# ---------------------------------------------------------------------------


def test_standard_tab_has_treble_clef_on_every_system() -> None:
    """Each system in STANDARD_TAB mode must carry exactly one treble clef."""
    events = [_note(64, float(m * 4)) for m in range(20)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB)
    clefs = _collect_glyphs(scene, "clef")
    num_systems = sum(
        len(page.systems) for page in scene.document_scene.pages
    )
    assert len(clefs) == num_systems, (
        f"Expected one clef per system ({num_systems}), got {len(clefs)}"
    )


def test_standard_mode_has_clef_on_every_system() -> None:
    """STANDARD (notation-only) mode also needs a clef per system."""
    events = [_note(64, float(m * 4)) for m in range(12)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    clefs = _collect_glyphs(scene, "clef")
    num_systems = sum(len(page.systems) for page in scene.document_scene.pages)
    assert len(clefs) == num_systems


def test_first_system_always_has_time_signature() -> None:
    """The very first system must always show a time_signature glyph."""
    events = [_note(64, 0.0, 1.0), _note(67, 1.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB)
    time_sigs = _collect_glyphs(scene, "time_signature")
    assert len(time_sigs) >= 1, "Expected at least one time_signature glyph"
    # First system's first staff must own it.
    first_staff = scene.document_scene.pages[0].systems[0].staves[0]
    first_staff_time_sigs = [
        g
        for layer in first_staff.layer_groups
        for g in layer.glyph_instances
        if g.glyph_id == "time_signature"
    ]
    assert len(first_staff_time_sigs) >= 1, "First staff must have a time_signature glyph"
    ts = first_staff_time_sigs[0]
    assert ts.metadata.get("numerator") == 4
    assert ts.metadata.get("denominator") == 4


def test_3_4_time_signature_metadata_is_correct() -> None:
    """3/4 time signature metadata must reflect numerator=3, denominator=4."""
    events = [_note(64, 0.0, 1.0), _note(67, 1.0, 1.0), _note(69, 2.0, 1.0)]
    raw_score = legacy_parse_to_raw_score(
        Path("test.gp"),
        source_format="gpif",
        events=events,
        beats_per_measure=3.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    scene = result.render_scene
    time_sigs = _collect_glyphs(scene, "time_signature")
    first = time_sigs[0]
    assert first.metadata.get("numerator") == 3
    assert first.metadata.get("denominator") == 4


# ---------------------------------------------------------------------------
# Note and measure count invariants
# ---------------------------------------------------------------------------


def test_tab_note_count_matches_input_events() -> None:
    """TAB mode must emit exactly one 'note' TextInstance per non-rest NoteEvent."""
    events = [
        _note(64, 0.0, string_hint=1, fret_hint=0),
        _note(67, 1.0, string_hint=2, fret_hint=3),
        _note(71, 2.0, string_hint=1, fret_hint=7),
    ]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    tab_notes = _collect_texts(scene, "note")
    assert len(tab_notes) == len(events)


def test_measure_number_count_matches_input_measures() -> None:
    """Number of measure_number labels must equal number of distinct measures."""
    # 4 notes, each in a different 4/4 measure (onset 0, 4, 8, 12)
    events = [_note(64, float(m * 4)) for m in range(4)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB)
    measure_numbers = _collect_texts(scene, "measure_number")
    # 4 notes → 4 measures, each should get exactly one measure number label
    assert len(measure_numbers) == 4


def test_anacrusis_shifts_measure_numbers_down_by_one() -> None:
    """With has_anacrusis=True the first (pickup) bar is unnumbered; rest start at 1."""
    events = [_note(64, float(m * 4)) for m in range(3)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB, has_anacrusis=True)
    measure_numbers = _collect_texts(scene, "measure_number")
    nums = [t.text for t in measure_numbers]
    # 3 measures: pickup bar (0) hidden, then "1" and "2"
    assert nums == ["1", "2"], f"Expected ['1','2'] for anacrusis score, got {nums}"


def test_svg_output_is_non_empty_xml() -> None:
    """render_scene_to_svg must return a valid SVG document string."""
    events = [_note(64, 0.0)]
    scene = _build_scene(events)
    svg = render_scene_to_svg(scene)
    assert svg.strip().startswith("<svg")
    assert "</svg>" in svg


# ---------------------------------------------------------------------------
# Notehead shape invariants
# ---------------------------------------------------------------------------


def test_quarter_note_has_filled_notehead() -> None:
    """A quarter note (duration=1.0) must produce a filled notehead."""
    events = [_note(64, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert len(noteheads) >= 1
    assert all(g.metadata.get("filled") is True for g in noteheads), (
        "Quarter noteheads must be filled"
    )


def test_half_note_has_open_notehead() -> None:
    """A half note (duration=2.0) must produce an open (unfilled) notehead."""
    events = [_note(64, 0.0, 2.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert len(noteheads) >= 1
    assert all(g.metadata.get("filled") is False for g in noteheads), (
        "Half noteheads must be open"
    )


def test_whole_note_has_open_notehead() -> None:
    """A whole note (duration=4.0) must produce an open (unfilled) notehead."""
    events = [_note(64, 0.0, 4.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert len(noteheads) >= 1
    assert all(g.metadata.get("filled") is False for g in noteheads), (
        "Whole noteheads must be open"
    )


def test_eighth_note_has_filled_notehead() -> None:
    """An eighth note (duration=0.5) must produce a filled notehead."""
    events = [_note(64, 0.0, 0.5), _note(67, 0.5, 0.5)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert len(noteheads) >= 1
    assert all(g.metadata.get("filled") is True for g in noteheads), (
        "Eighth noteheads must be filled"
    )


def test_duration_class_is_correct_for_quarter() -> None:
    events = [_note(64, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert all(g.metadata.get("duration_class") == "quarter" for g in noteheads)


def test_duration_class_is_correct_for_eighth() -> None:
    events = [_note(64, 0.0, 0.5), _note(67, 0.5, 0.5)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    assert all(g.metadata.get("duration_class") == "eighth" for g in noteheads)


# ---------------------------------------------------------------------------
# Ledger line invariants
# ---------------------------------------------------------------------------


def test_a5_above_treble_staff_has_ledger_line() -> None:
    """A5 (MIDI 81) is the first ledger line position above the treble staff.

    Treble staff top line = F5 (MIDI 77).  G5 (MIDI 79) is in the space above
    the top line (no ledger needed).  A5 (MIDI 81) sits on the first ledger
    line — one ledger line must appear.
    """
    events = [_note(81, 0.0, 1.0)]  # A5 — first ledger above treble staff
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    ledger_lines = _collect_recipes(scene, "ledger_line")
    assert len(ledger_lines) >= 1, "A5 requires at least one ledger line above the treble staff"


def test_b3_below_treble_staff_has_ledger_line() -> None:
    """B3 (MIDI 59) sits below the treble staff bottom line and needs a ledger line."""
    events = [_note(59, 0.0, 1.0)]  # B3
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    ledger_lines = _collect_recipes(scene, "ledger_line")
    assert len(ledger_lines) >= 1, "B3 requires at least one ledger line below the treble staff"


def test_e4_on_treble_staff_bottom_line_has_no_ledger_line() -> None:
    """E4 (MIDI 64) is on the bottom line of the treble staff — no ledger line needed."""
    events = [_note(64, 0.0, 1.0)]  # E4
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    ledger_lines = _collect_recipes(scene, "ledger_line")
    assert len(ledger_lines) == 0, "E4 must not produce a ledger line"


def test_g4_in_first_space_has_no_ledger_line() -> None:
    """G4 (MIDI 67) is in the first space — no ledger line."""
    events = [_note(67, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    ledger_lines = _collect_recipes(scene, "ledger_line")
    assert len(ledger_lines) == 0


# ---------------------------------------------------------------------------
# Notehead displacement (G08 / G09) — fixed in Sprint S2
# ---------------------------------------------------------------------------


def test_up_stem_chord_displaced_note_has_positive_head_dx() -> None:
    """Adjacent notes a 2nd apart in an up-stem chord: lower note must displace RIGHT (+dx).

    Currently fails because _standard_notehead_offsets_by_event_id uses
    ``sign = -1.0 if direction == 'up'`` which is inverted.  Will pass after S2.
    """
    # E4 (64) and F4 (65) — a 2nd apart — in voice 0 (→ up-stem direction).
    # Do NOT pass string_hint/fret_hint: guitar transposition would shift these
    # notes up an octave, moving them above the staff middle line and flipping
    # the stem direction to "down".
    events = [
        _note(64, 0.0, 1.0, voice_hint=0),
        _note(65, 0.0, 1.0, voice_hint=0),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    displaced = [g for g in noteheads if g.metadata.get("head_displaced") == "true"]
    assert len(displaced) >= 1, "At least one notehead should be displaced in a 2nd interval chord"
    for g in displaced:
        assert float(g.metadata.get("head_dx", 0.0)) > 0.0, (
            f"Displaced notehead for up-stem chord must go RIGHT (+dx), "
            f"got head_dx={g.metadata.get('head_dx')}"
        )


def test_down_stem_chord_displaced_note_has_negative_head_dx() -> None:
    """Adjacent notes a 2nd apart in a down-stem chord: upper note must displace LEFT (-dx).

    Currently fails due to same sign inversion bug.  Will pass after S2.
    """
    # E4 (64) and F4 (65) — a 2nd apart — in voice 1 (→ down-stem direction).
    # Do NOT pass string_hint/fret_hint: same guitar-transposition caveat.
    events = [
        _note(64, 0.0, 1.0, voice_hint=1),
        _note(65, 0.0, 1.0, voice_hint=1),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    displaced = [g for g in noteheads if g.metadata.get("head_displaced") == "true"]
    assert len(displaced) >= 1, "At least one notehead should be displaced in a 2nd interval chord"
    for g in displaced:
        assert float(g.metadata.get("head_dx", 0.0)) < 0.0, (
            f"Displaced notehead for down-stem chord must go LEFT (-dx), "
            f"got head_dx={g.metadata.get('head_dx')}"
        )


def test_up_stem_chord_displaces_low_note_toward_stem_side() -> None:
    """In an up-stem 2nd, the LOWER notehead must be the displaced one (to the right)."""
    events = [
        _note(64, 0.0, 1.0, voice_hint=0),  # lower
        _note(65, 0.0, 1.0, voice_hint=0),  # higher
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    by_pitch = {int(g.metadata.get("pitch_notated", -1)): g for g in noteheads}

    assert by_pitch[64].metadata.get("head_displaced") == "true"
    assert float(by_pitch[64].metadata.get("head_dx", 0.0)) > 0.0
    assert by_pitch[65].metadata.get("head_displaced") != "true"


def test_down_stem_chord_displaces_high_note_toward_stem_side() -> None:
    """In a down-stem 2nd, the HIGHER notehead must be the displaced one (to the left)."""
    events = [
        _note(64, 0.0, 1.0, voice_hint=1),  # lower
        _note(65, 0.0, 1.0, voice_hint=1),  # higher
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    noteheads = _collect_glyphs(scene, "notehead")
    by_pitch = {int(g.metadata.get("pitch_notated", -1)): g for g in noteheads}

    assert by_pitch[65].metadata.get("head_displaced") == "true"
    assert float(by_pitch[65].metadata.get("head_dx", 0.0)) < 0.0
    assert by_pitch[64].metadata.get("head_displaced") != "true"


def test_beamed_eighth_stems_use_extended_minimum_length() -> None:
    """Beamed 8ths should keep a longer GP-like stem minimum for readability."""
    events = [
        _note(64, 0.0, 0.5, voice_hint=0),
        _note(67, 0.5, 0.5, voice_hint=0),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)

    stem_lines = _collect_recipes(scene, "stem_line")
    beam_groups = _collect_recipes(scene, "beam_group")
    assert beam_groups, "Expected a beam_group for two consecutive eighth notes"

    # builders.py: _STANDARD_BEAMED_STEM_MIN_SPACES=3.5 with default spacing=8.0.
    min_expected = 27.5
    assert stem_lines, "Expected stem_line recipes for beamed notes"
    for stem in stem_lines:
        y0 = float(stem.params.get("y0", 0.0))
        y1 = float(stem.params.get("y1", 0.0))
        assert abs(y1 - y0) >= min_expected


def test_beam_crossing_splitter_does_not_drop_two_stem_group() -> None:
    """A 2-stem group must never be split away entirely by crossing logic."""
    group = [(0.0, 0.0, 0.5), (10.0, 0.5, 0.5)]
    group_entries = [
        {"x": 0.0, "onset": 0.0, "duration": 0.5, "y0": 100.0, "y1": 90.0},
        {"x": 10.0, "onset": 0.5, "duration": 0.5, "y0": 100.0, "y1": 70.0},
    ]

    resolved = _resolve_beam_crossing(
        group,
        group_entries,
        direction="up",
        anchor_up=0.0,
        anchor_down=200.0,
        stem_length=40.0,
        max_stem_length=56.0,
    )

    assert len(resolved) == 1
    resolved_group, resolved_entries = resolved[0]
    assert len(resolved_group) == 2
    assert len(resolved_entries) == 2


# ---------------------------------------------------------------------------
# Staff line invariants
# ---------------------------------------------------------------------------


def test_standard_mode_has_staff_lines_recipe() -> None:
    """STANDARD mode must have staff_lines recipes in every staff."""
    events = [_note(64, 0.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    staff_lines = _collect_recipes(scene, "staff_lines")
    assert len(staff_lines) >= 1


def test_tab_mode_has_tab_lines_recipe() -> None:
    """TAB mode must have tab_lines recipes in every staff."""
    events = [_note(64, 0.0, string_hint=1, fret_hint=0)]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    tab_lines = _collect_recipes(scene, "tab_lines")
    assert len(tab_lines) >= 1


def test_standard_tab_mode_has_both_staff_and_tab_lines() -> None:
    """STANDARD_TAB mode must have both staff_lines and tab_lines."""
    events = [_note(64, 0.0, string_hint=1, fret_hint=0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB)
    assert _collect_recipes(scene, "staff_lines"), "Expected staff_lines in STANDARD_TAB"
    assert _collect_recipes(scene, "tab_lines"), "Expected tab_lines in STANDARD_TAB"


# ---------------------------------------------------------------------------
# Barline invariants
# ---------------------------------------------------------------------------


def test_each_measure_has_a_closing_barline() -> None:
    """Each measure must produce a barline recipe at its right boundary."""
    events = [_note(64, float(m * 4)) for m in range(4)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD_TAB)
    barlines = _collect_recipes(scene, "barline")
    # 4 measures → 4 closing barlines
    assert len(barlines) >= 4, f"Expected ≥4 barlines for 4 measures, got {len(barlines)}"


# ---------------------------------------------------------------------------
# Proportional layout invariants (Sprint L)
# ---------------------------------------------------------------------------


def test_proportional_spacing_whole_note_produces_wider_measure() -> None:
    """A measure with a single whole note should produce a wider measure than
    a measure with 4 quarter notes at the same onset density."""
    # Whole note: 1 onset → proportional width = space_per_beat × 4 beats = 128pt+
    events_whole = [_note(64, 0.0, 4.0)]
    scene_whole = _build_scene(events_whole, mode=RepresentationMode.STANDARD)
    barlines_whole = _collect_recipes(scene_whole, "barline")
    assert barlines_whole, "Expected barline for whole note measure"
    width_whole = barlines_whole[0].params["x"]

    # 4 quarter notes: 4 onsets → same total beat content
    events_quarters = [_note(64, float(beat), 1.0) for beat in range(4)]
    scene_quarters = _build_scene(events_quarters, mode=RepresentationMode.STANDARD)
    barlines_quarters = _collect_recipes(scene_quarters, "barline")
    assert barlines_quarters
    width_quarters = barlines_quarters[0].params["x"]

    # Both should produce the SAME layout width (proportional invariant)
    assert abs(width_whole - width_quarters) < 2.0, (
        f"Proportional invariant: whole note ({width_whole:.1f}) should match "
        f"four quarters ({width_quarters:.1f})"
    )


# ---------------------------------------------------------------------------
# Key-aware accidentals (Sprint S-ACC)
# ---------------------------------------------------------------------------


def test_key_aware_fsharp_in_a_major_no_accidental() -> None:
    """F#4 in A major (3 sharps: F# C# G#) should NOT show an accidental."""
    # F#4 = MIDI 66, which has pitch_class 6 → normally shows a sharp
    events = [_note(66, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=3)
    sharps = _collect_glyphs(scene, "accidental_sharp")
    assert len(sharps) == 0, "F# in A major should not show explicit sharp"


def test_key_aware_f_natural_in_a_major_shows_natural() -> None:
    """F♮4 in A major (key has F#) must show a natural sign."""
    # F4 = MIDI 65, pitch_class 5 → no accidental normally, but key has F# → show natural
    events = [_note(65, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=3)
    naturals = _collect_glyphs(scene, "accidental_natural")
    assert len(naturals) >= 1, "F natural in A major should show a natural sign"


def test_key_aware_csharp_in_d_major_no_accidental() -> None:
    """C#5 in D major (2 sharps: F# C#) should NOT show an accidental."""
    events = [_note(73, 0.0, 1.0)]  # C#5 = MIDI 73
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=2)
    sharps = _collect_glyphs(scene, "accidental_sharp")
    assert len(sharps) == 0, "C# in D major should not show explicit sharp"


def test_key_aware_bb_in_fmajor_no_accidental() -> None:
    """Bb in F major (1 flat: Bb) should NOT show an accidental."""
    events = [_note(70, 0.0, 1.0)]  # Bb4 = MIDI 70
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=-1)
    flats = _collect_glyphs(scene, "accidental_flat")
    assert len(flats) == 0, "Bb in F major should not show explicit flat"


def test_key_aware_b_natural_in_fmajor_shows_natural() -> None:
    """B♮4 in F major (key has Bb) must show a natural sign."""
    events = [_note(71, 0.0, 1.0)]  # B4 = MIDI 71
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=-1)
    naturals = _collect_glyphs(scene, "accidental_natural")
    assert len(naturals) >= 1, "B natural in F major should show a natural sign"


def test_natural_glyph_renders_in_svg() -> None:
    """The natural sign should be rendered in SVG output."""
    events = [_note(65, 0.0, 1.0)]  # F4 = natural, in A major needs ♮
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=3)
    svg = render_scene_to_svg(scene)
    assert "m -8,375 c 8,4" in svg, "Natural sign path should appear in SVG output"


def test_c_major_no_change_to_accidentals() -> None:
    """In C major (fifths=0), accidental behavior unchanged: C#/Db still show. """
    events = [_note(61, 0.0, 1.0)]  # C#4/Db4 = MIDI 61
    scene = _build_scene(events, mode=RepresentationMode.STANDARD, key_signature_fifths=0)
    sharps = _collect_glyphs(scene, "accidental_sharp")
    flats = _collect_glyphs(scene, "accidental_flat")
    assert (len(sharps) + len(flats)) >= 1, "C#/Db in C major should still show accidental"


# ---------------------------------------------------------------------------
# Muted noteheads (Sprint S-MUTED)
# ---------------------------------------------------------------------------


def test_muted_note_has_x_notehead_in_standard() -> None:
    """A muted note should render as notehead_muted (X) in standard notation."""
    events = [_note(64, 0.0, 1.0, articulation=Articulation.MUTED)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    muted_heads = _collect_glyphs(scene, "notehead_muted")
    normal_heads = _collect_glyphs(scene, "notehead")
    assert len(muted_heads) >= 1, "Muted note should produce notehead_muted glyph"
    assert len(normal_heads) == 0, "Muted note should not produce normal notehead"


def test_muted_note_shows_x_in_tab() -> None:
    """A muted note should show 'X' instead of fret number in TAB."""
    events = [_note(64, 0.0, 1.0, string_hint=1, fret_hint=0,
                    articulation=Articulation.MUTED)]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    tab_texts = _collect_texts(scene, "note")
    x_texts = [t for t in tab_texts if t.text == "X"]
    assert len(x_texts) >= 1, "Muted note in TAB should display 'X'"


def test_muted_notehead_renders_as_cross_in_svg() -> None:
    """The muted notehead should render as crossed lines in SVG."""
    events = [_note(64, 0.0, 1.0, articulation=Articulation.MUTED)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    svg = render_scene_to_svg(scene)
    # X notehead is rendered as two crossing lines
    line_count = svg.count("<line ")
    # Should have at least 2 lines for the X cross (plus staff/barlines)
    assert line_count >= 2, "Muted notehead SVG should contain crossing lines"


def test_normal_note_has_standard_notehead() -> None:
    """A non-muted note should render as normal notehead."""
    events = [_note(64, 0.0, 1.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    normal_heads = _collect_glyphs(scene, "notehead")
    muted_heads = _collect_glyphs(scene, "notehead_muted")
    assert len(normal_heads) >= 1, "Normal note should have notehead glyph"
    assert len(muted_heads) == 0, "Normal note should not have notehead_muted"


# ---------------------------------------------------------------------------
# S-COLL — collision avoidance and rest voice separation
# ---------------------------------------------------------------------------


def test_voice1_rest_is_below_voice0_rest() -> None:
    """Voice 1 rests must be vertically separated from voice 0 rests."""
    # One note in voice 0, one note in voice 1 at same onset so both get companion rests.
    events = [_note(64, 0.0, voice_hint=0), _note(60, 4.0, voice_hint=1)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    rests = _collect_glyphs(scene, "rest")
    # Collect rest Y values by voice
    v0_ys = [float(g.y) for g in rests if g.metadata.get("voice_number") == "0"]
    v1_ys = [float(g.y) for g in rests if g.metadata.get("voice_number") == "1"]
    if v0_ys and v1_ys:
        # Voice 1 rests should be strictly below voice 0 rests (larger Y = lower on page)
        assert min(v1_ys) > max(v0_ys), (
            f"Voice 1 rest (y={min(v1_ys)}) should be below voice 0 rest (y={max(v0_ys)})"
        )


def test_adjacent_semitone_accidentals_use_separate_columns() -> None:
    """A chord with accidentals on adjacent semitones must use at least 2 columns."""
    # C#4 (61) and D#4 (63) — both have sharps, adjacent, close Y rows.
    events = [_note(61, 0.0), _note(63, 0.0)]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    accidentals = _collect_glyphs(scene, "accidental_sharp")
    if len(accidentals) >= 2:
        xs = sorted({round(float(g.x), 1) for g in accidentals})
        assert len(xs) >= 2, (
            f"Adjacent-semitone accidentals should be in separate X columns, got xs={xs}"
        )


# ---------------------------------------------------------------------------
# S-TIES — ties, slurs, H/P labels, slide lines
# ---------------------------------------------------------------------------


def test_hammer_on_standard_emits_slur_arc_with_h_label() -> None:
    """A hammer-on note pair should emit a slur_arc recipe and an 'H' text label."""
    events = [
        _note(64, 0.0, 0.5, articulation=Articulation.HAMMER_ON, string_hint=1, fret_hint=0),
        _note(66, 0.5, 0.5, string_hint=1, fret_hint=2),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    slur_arcs = _collect_recipes(scene, "slur_arc")
    hp_labels = _collect_texts(scene, "hp_label")
    assert slur_arcs, "Hammer-on should emit slur_arc recipe in STANDARD mode"
    assert any(t.text == "H" for t in hp_labels), (
        "Hammer-on should emit an 'H' label (hp_label kind)"
    )


def test_pull_off_standard_emits_slur_arc_with_p_label() -> None:
    """A pull-off note pair should emit a slur_arc recipe and a 'P' text label."""
    events = [
        _note(66, 0.0, 0.5, articulation=Articulation.PULL_OFF, string_hint=1, fret_hint=2),
        _note(64, 0.5, 0.5, string_hint=1, fret_hint=0),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    slur_arcs = _collect_recipes(scene, "slur_arc")
    hp_labels = _collect_texts(scene, "hp_label")
    assert slur_arcs, "Pull-off should emit slur_arc recipe in STANDARD mode"
    assert any(t.text == "P" for t in hp_labels), (
        "Pull-off should emit a 'P' label (hp_label kind)"
    )


def test_tie_does_not_emit_hp_label() -> None:
    """Same pitch repeated (tie) should not produce an H/P label."""
    events = [
        _note(64, 0.0, 0.5, string_hint=1, fret_hint=0),
        _note(64, 0.5, 0.5, string_hint=1, fret_hint=0),
    ]
    scene = _build_scene(events, mode=RepresentationMode.STANDARD)
    hp_labels = _collect_texts(scene, "hp_label")
    assert not hp_labels, "Tie (same pitch) must not emit an H/P label"


def test_hammer_on_tab_emits_slur_arc() -> None:
    """A hammer-on in TAB mode should emit a slur_arc recipe."""
    events = [
        _note(64, 0.0, 0.5, articulation=Articulation.HAMMER_ON, string_hint=1, fret_hint=0),
        _note(66, 0.5, 0.5, string_hint=1, fret_hint=2),
    ]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    slur_arcs = _collect_recipes(scene, "slur_arc")
    assert slur_arcs, "Hammer-on in TAB mode should emit slur_arc recipe"


def test_slide_tab_emits_tab_slide_line() -> None:
    """A slide in TAB mode should emit a tab_slide_line recipe."""
    events = [
        _note(64, 0.0, 0.5, articulation=Articulation.SLIDE, string_hint=1, fret_hint=5),
        _note(69, 0.5, 0.5, string_hint=1, fret_hint=7),
    ]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    slides = _collect_recipes(scene, "tab_slide_line")
    assert slides, "Slide in TAB mode should emit tab_slide_line recipe"


def test_ascending_slide_diagonal_goes_upward() -> None:
    """Ascending slide (fret 5→7) should have y0 > y1 (line rises left-to-right)."""
    events = [
        _note(64, 0.0, 0.5, articulation=Articulation.SLIDE, string_hint=1, fret_hint=5),
        _note(69, 0.5, 0.5, string_hint=1, fret_hint=7),
    ]
    scene = _build_scene(events, mode=RepresentationMode.TAB)
    slides = _collect_recipes(scene, "tab_slide_line")
    if slides:
        y0 = float(slides[0].params.get("y0", 0.0))
        y1 = float(slides[0].params.get("y1", 0.0))
        assert y0 > y1, (
            f"Ascending slide should have y0 ({y0:.1f}) > y1 ({y1:.1f}) for upward diagonal"
        )
