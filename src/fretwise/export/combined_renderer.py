"""Combined staff + tab renderer.

Renders each system as a 5-line treble-clef staff stacked above the
6-string guitar tab, both sharing identical measure layout and note
x-positions.  This is the standard music-publishing format familiar
from guitar songbooks.

Architecture
------------
Delegates to ``staff_renderer`` (standard notation) and ``pdf_tab``
(tablature) drawing helpers, sharing the same grouping / packing logic
so columns are perfectly aligned vertically.
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas  # type: ignore[import-untyped]

from fretwise.export.pdf_tab import (
    _MARGIN,
    _PAGE_H,
    _PAGE_W,
    _STRINGS_HEIGHT,
    _STRINGS_X0,
    _SYSTEM_H as _TAB_SYSTEM_H,
    _INTER_SYSTEM_GAP,
    _TAB_LABEL_W,
    _STRING_SPACING,
    _NUM_STRINGS,
    _STRING_NAMES,
    _build_systems as _tab_build_systems,
    _group_by_measure as _tab_group_by_measure,
    _draw_system as _tab_draw_system,
    _system_tempo,
)
from fretwise.export.staff_renderer import (
    _STAFF_HEIGHT,
    _STAFF_SPACING,
    _ABOVE_STAFF,
    _BELOW_STAFF,
    _NOTES_X0,
    _draw_system as _staff_draw_system,
)
from fretwise.models import ChordDiagram, FingeringResult

# -- Combined system dimensions -----------------------------------------------
# Staff portion (above) + gap + tab portion (below)

_STAFF_TAB_GAP = 8.0               # gap between bottom staff ledger line and tab top

# The combined system height:
#   staff above-pad + staff-lines + staff below-pad
#   + gap
#   + tab above-strings + tab strings + tab below-strings
# We compute it to know how many systems fit per page.

_COMBINED_SYSTEM_H = (
    _ABOVE_STAFF + _STAFF_HEIGHT + _BELOW_STAFF
    + _STAFF_TAB_GAP
    + _TAB_SYSTEM_H
)
_COMBINED_PITCH = _COMBINED_SYSTEM_H + _INTER_SYSTEM_GAP


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_combined_pdf(
    results: list[FingeringResult],
    output_path: Path,
    title: str = "",
    artist: str = "",
    beats_per_measure: float = 4.0,
    mode_label: str = "",
    instrument: str = "",
    measures_per_system: int | None = None,
    section_markers: dict[int, str] | None = None,
    chord_diagrams: list[ChordDiagram] | None = None,
) -> None:
    """Render combined standard notation + tab PDF.

    Args:
        results: FingeringResult list from the optimisation pipeline.
        output_path: Destination PDF path.
        title: Song title for header.
        artist: Artist / composer name.
        beats_per_measure: Time signature numerator.
        mode_label: e.g. "reference mode".
        instrument: Instrument name.
        measures_per_system: Force N measures per system (None=auto).
        section_markers: Optional mapping of 1-based measure → section label.
        chord_diagrams: Reserved for future use.
    """
    c = rl_canvas.Canvas(str(output_path), pagesize=(_PAGE_W, _PAGE_H))

    if not results:
        c.setFont("Helvetica", 12)
        c.drawString(_MARGIN, _PAGE_H / 2, "(no notes)")
        c.save()
        return

    # Use the tab module's grouping to get aligned measures / widths
    measures = _tab_group_by_measure(results, beats_per_measure)
    available_w = _PAGE_W - _MARGIN - _STRINGS_X0
    first_song_measure = int(results[0].note_event.onset / beats_per_measure) + 1

    from fretwise.export.pdf_tab import _MPS_MIN, _MPS_MAX

    forced_mps: int | None = None
    if measures_per_system is not None:
        forced_mps = max(_MPS_MIN, min(_MPS_MAX, measures_per_system))

    systems = _tab_build_systems(measures, beats_per_measure, available_w, forced_mps)

    # Title block
    current_top = _PAGE_H - _MARGIN
    if title or artist:
        current_top = _draw_title_block(c, title, artist, instrument, mode_label, current_top)

    m_idx = 0
    prev_tempo: float = -1.0
    first_system_on_page = True

    for sys_idx, (sys_measures, measure_widths) in enumerate(systems):
        song_m_start = first_song_measure + m_idx
        m_idx += len(sys_measures)

        # Check space for combined system
        system_bottom = current_top - _COMBINED_SYSTEM_H
        if system_bottom < _MARGIN:
            c.showPage()
            current_top = _PAGE_H - _MARGIN
            first_system_on_page = True
            system_bottom = current_top - _COMBINED_SYSTEM_H

        # ── Staff portion ──
        staff_bottom_y = current_top - _ABOVE_STAFF - _STAFF_HEIGHT
        _staff_draw_system(
            c, sys_measures, staff_bottom_y, (song_m_start - 1),
            beats_per_measure, measure_widths, section_markers,
        )

        # ── Tab portion (below staff + gap) ──
        # sys_y for pdf_tab is the y of string 1 (topmost string)
        tab_top = staff_bottom_y - _BELOW_STAFF - _STAFF_TAB_GAP
        # pdf_tab._draw_system expects sys_y = y of string-1
        from fretwise.export.pdf_tab import _ABOVE_STRINGS

        sys_y = tab_top - _ABOVE_STRINGS + _STRINGS_HEIGHT
        # Actually, sys_y in pdf_tab is "y of string 1 (high-e)".
        # String 1 is at the top of the tab system area.
        sys_y = tab_top

        sys_tempo = _system_tempo(sys_measures, results[0].note_event.tempo)
        show_tempo = (sys_tempo != prev_tempo)
        is_last = sys_idx == len(systems) - 1

        _tab_draw_system(
            c, sys_measures, sys_y, song_m_start,
            beats_per_measure, measure_widths, sys_tempo, show_tempo,
            first_system_on_page, section_markers or {}, is_last,
        )

        prev_tempo = sys_tempo
        first_system_on_page = False
        current_top = system_bottom - _INTER_SYSTEM_GAP

    c.save()


# ---------------------------------------------------------------------------
# Title helpers
# ---------------------------------------------------------------------------


def _draw_title_block(
    c: rl_canvas.Canvas,
    title: str,
    artist: str,
    instrument: str,
    mode_label: str,
    top_y: float,
) -> float:
    """Draw title and subtitle, return new top_y."""
    y = top_y
    if title:
        c.setFont("Helvetica-Bold", 16)
        c.drawCentredString(_PAGE_W / 2, y - 16, title)
        y -= 22
    if artist:
        c.setFont("Helvetica", 10)
        c.drawCentredString(_PAGE_W / 2, y - 10, artist)
        y -= 14
    sub_parts = [s for s in [instrument, mode_label] if s]
    if sub_parts:
        c.setFont("Helvetica-Oblique", 8)
        c.drawCentredString(_PAGE_W / 2, y - 10, " — ".join(sub_parts))
        y -= 14
    return y - 6
