"""Visual snapshot regression tests for Standard + Standard+Tab rendering.

These tests render SVG to PNG using PyMuPDF (no libcairo required) and compare
against baseline snapshots stored in tests/snapshots/.

Usage
-----
First run — generate baselines::

    pytest tests/test_visual_standard_tab.py --update-snapshots -v

Subsequent runs — regression check::

    pytest tests/test_visual_standard_tab.py -v

Run with ``-m visual`` to target only these tests, or ``-m "not visual"`` to
skip the heavier snapshot tests in CI if desired.

Snapshot location:  tests/snapshots/<name>.png
Diff output:        tests/snapshots/<name>_diff.png  (only on failure)
"""

from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.models import Articulation, Dynamic, NoteEvent

# conftest provides: render_svg_to_image, assert_visual_match, update_snapshots
from tests.conftest import render_svg_to_image, assert_visual_match


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(
    pitch: int,
    onset: float,
    duration: float = 1.0,
    *,
    voice_hint: int = 0,
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
        voice_hint=voice_hint,
        string_hint=string_hint,
        fret_hint=fret_hint,
    )


def _render_svg(
    events: list[NoteEvent],
    *,
    mode: RepresentationMode = RepresentationMode.STANDARD_TAB,
    beats_per_measure: float = 4.0,
) -> str:
    raw_score = legacy_parse_to_raw_score(
        Path("test_song.gp"),
        source_format="gpif",
        events=events,
        beats_per_measure=beats_per_measure,
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=mode)
    return result.svg


# ---------------------------------------------------------------------------
# Visual snapshot tests — Standard+Tab mode
# ---------------------------------------------------------------------------


@pytest.mark.visual
def test_visual_single_quarter_note_standard_tab(update_snapshots: bool) -> None:
    """Single E4 quarter note in STANDARD_TAB mode — baseline smoke test."""
    svg = _render_svg(
        [_note(64, 0.0, 1.0, string_hint=1, fret_hint=0)],
        mode=RepresentationMode.STANDARD_TAB,
    )
    img = render_svg_to_image(svg)
    assert_visual_match(img, "single_quarter_standard_tab", update=update_snapshots)


@pytest.mark.visual
def test_visual_four_quarter_notes_standard_tab(update_snapshots: bool) -> None:
    """Four quarter notes (beat 0–3) in STANDARD_TAB — verifies barline spacing."""
    events = [
        _note(64, 0.0, 1.0, string_hint=1, fret_hint=0),
        _note(67, 1.0, 1.0, string_hint=2, fret_hint=3),
        _note(71, 2.0, 1.0, string_hint=2, fret_hint=7),
        _note(69, 3.0, 1.0, string_hint=2, fret_hint=5),
    ]
    svg = _render_svg(events, mode=RepresentationMode.STANDARD_TAB)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "four_quarters_standard_tab", update=update_snapshots)


@pytest.mark.visual
def test_visual_mixed_durations_standard_tab(update_snapshots: bool) -> None:
    """Whole + half + quarter in STANDARD_TAB — verifies proportional spacing."""
    events = [
        _note(64, 0.0, 4.0),   # whole note — one measure
        _note(67, 4.0, 2.0),   # half note
        _note(71, 6.0, 2.0),   # half note
        _note(69, 8.0, 1.0),   # quarter
        _note(64, 9.0, 1.0),
        _note(67, 10.0, 1.0),
        _note(71, 11.0, 1.0),
    ]
    svg = _render_svg(events, mode=RepresentationMode.STANDARD_TAB)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "mixed_durations_standard_tab", update=update_snapshots)


@pytest.mark.visual
def test_visual_eighth_notes_standard_tab(update_snapshots: bool) -> None:
    """Eight eighth notes in STANDARD_TAB — verifies beaming and tab grid."""
    events = [_note(64 + i % 5, i * 0.5, 0.5, string_hint=1, fret_hint=i % 7) for i in range(8)]
    svg = _render_svg(events, mode=RepresentationMode.STANDARD_TAB)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "eight_eighths_standard_tab", update=update_snapshots)


@pytest.mark.visual
def test_visual_multiline_standard_tab(update_snapshots: bool) -> None:
    """20 quarter notes — should wrap to multiple system lines."""
    events = [_note(60 + (i % 7) * 2, float(i * 4)) for i in range(20)]
    svg = _render_svg(events, mode=RepresentationMode.STANDARD_TAB)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "multiline_standard_tab", update=update_snapshots)


# ---------------------------------------------------------------------------
# Visual snapshot tests — Standard (notation only) mode
# ---------------------------------------------------------------------------


@pytest.mark.visual
def test_visual_single_quarter_standard(update_snapshots: bool) -> None:
    """Single E4 in STANDARD mode — verifies clef, time sig, notehead."""
    svg = _render_svg([_note(64, 0.0, 1.0)], mode=RepresentationMode.STANDARD)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "single_quarter_standard", update=update_snapshots)


@pytest.mark.visual
def test_visual_whole_note_standard(update_snapshots: bool) -> None:
    """Single whole note — open notehead, no stem."""
    svg = _render_svg([_note(64, 0.0, 4.0)], mode=RepresentationMode.STANDARD)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "whole_note_standard", update=update_snapshots)


@pytest.mark.visual
def test_visual_ledger_line_notes_standard(update_snapshots: bool) -> None:
    """High (A5) and low (B3) notes in STANDARD — verifies ledger line positions."""
    events = [_note(81, 0.0, 1.0), _note(59, 1.0, 1.0), _note(64, 2.0, 1.0)]
    svg = _render_svg(events, mode=RepresentationMode.STANDARD)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "ledger_lines_standard", update=update_snapshots)


# ---------------------------------------------------------------------------
# Visual snapshot tests — TAB-only mode
# ---------------------------------------------------------------------------


@pytest.mark.visual
def test_visual_tab_only_mode(update_snapshots: bool) -> None:
    """Four notes in TAB-only mode — no staff, only tablature grid."""
    events = [
        _note(64, 0.0, 1.0, string_hint=1, fret_hint=0),
        _note(67, 1.0, 1.0, string_hint=2, fret_hint=3),
        _note(71, 2.0, 1.0, string_hint=3, fret_hint=9),
        _note(69, 3.0, 1.0, string_hint=2, fret_hint=5),
    ]
    svg = _render_svg(events, mode=RepresentationMode.TAB)
    img = render_svg_to_image(svg)
    assert_visual_match(img, "four_notes_tab_only", update=update_snapshots)


# ---------------------------------------------------------------------------
# Visual snapshot tests — Highway to Hell GP fixture (integration)
# ---------------------------------------------------------------------------


_HWY_FIXTURE = Path(__file__).parent.parent / "AC_DC-Highway To Hell-12-22-2025.gp"


@pytest.mark.visual
@pytest.mark.skipif(not _HWY_FIXTURE.exists(), reason="Highway to Hell fixture not available")
def test_visual_highway_to_hell_tab(update_snapshots: bool) -> None:
    """Full-pipeline render of Highway to Hell in TAB mode.

    This is the primary fixture-level integration snapshot.  The test parses
    the real .gp file and renders TAB.  Any change to the parser, layout, or
    scene engine will be caught here.
    """
    from fretwise.parser.gpif_adapter import GpifAdapter

    adapter = GpifAdapter()
    note_events = adapter.parse(_HWY_FIXTURE)

    # Use timing info from the file: assume 4/4 unless overridden.
    raw_score = legacy_parse_to_raw_score(
        _HWY_FIXTURE,
        source_format="gpif",
        events=note_events,
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode.TAB)
    img = render_svg_to_image(result.svg)
    assert_visual_match(img, "highway_to_hell_tab", threshold=0.95, update=update_snapshots)


@pytest.mark.visual
@pytest.mark.skipif(not _HWY_FIXTURE.exists(), reason="Highway to Hell fixture not available")
def test_visual_highway_to_hell_standard_tab(update_snapshots: bool) -> None:
    """Full-pipeline render of Highway to Hell in STANDARD_TAB mode.

    This is the most demanding snapshot — it covers clef, time sig, noteheads,
    stems, beams, barlines, and tab grid simultaneously.
    """
    from fretwise.parser.gpif_adapter import GpifAdapter

    adapter = GpifAdapter()
    note_events = adapter.parse(_HWY_FIXTURE)

    raw_score = legacy_parse_to_raw_score(
        _HWY_FIXTURE,
        source_format="gpif",
        events=note_events,
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    img = render_svg_to_image(result.svg)
    assert_visual_match(
        img,
        "highway_to_hell_standard_tab",
        threshold=0.95,
        update=update_snapshots,
    )
