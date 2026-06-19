"""PDF tablature renderer — professional edition.

Produces an A4 PDF with clean, readable six-string guitar tablature:

Layout per system (top to bottom)
──────────────────────────────────
  TOP_PAD (4 pt)
  TEMPO LINE  –– "4/4  ·  120 BPM" in small grey, updated when tempo changes
  CHORD BELT  –– chord name in bold black above the stems
  STEM AREA   –– rhythm stems (lines), flags (8th/16th), beam bars
  STRING 1    ──────── high e  ← sys_y reference point
  STRING 2    ────────   B      spacing 10 pt
  …
  STRING 6    ──────── low E
  BOTTOM PAD (6 pt)

Note rendering
──────────────
  • White oval    – erases the string line behind the fret number
  • Fret number   – Helvetica-Bold 6 pt, centred in oval (black)
  • LH finger     – Helvetica-Bold 5 pt, SOUTH-WEST of oval (dark red)
                    right edge of char aligns with left edge of oval;
                    baseline at string_y - 5.5 pt so descender stays
                    3 pt clear of the next string line.
                    Omitted for open strings (fret == 0).
  • RH finger     – reserved for Phase 2, SOUTH-EAST of oval (dark blue)
                    left edge of char aligns with right edge of oval;
                    same Y baseline as LH for visual symmetry.
  • Minimum column step 17 pt enforced by forward-pass constraint

SW / SE finger placement diagram (string spacing = 10 pt)
──────────────────────────────────────────────────────────
  y + 3.5  ┌───────────┐
  y        │     5     │   fret number centred in oval
  y - 3.5  └───────────┘
              ↑           ↑
  y - 5.5   p·          ·p   LH at SW, RH at SE (same baseline)
  y - 7.0   (descender bottom — 3 pt above next string line)
  y - 10   ─────────────────  next string
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas

from fretwise.config import config
from fretwise.export.chord_diagram import draw_chord_diagram
from fretwise.models import Articulation, ChordDiagram, Finger, FingeringResult, SlideType
from fretwise.patterns.chord_recognition import recognize_chord

# ---------------------------------------------------------------------------
# Layout constants  (all in pt — 1 pt = 1/72 inch)
# ---------------------------------------------------------------------------

_PAGE_CFG = config().export.page
_TAB_CFG = config().export.pdf_tab

_PAGE_W: float = _PAGE_CFG.width_pt
_PAGE_H: float = _PAGE_CFG.height_pt
_MARGIN: float = _PAGE_CFG.margin_pt

# Left label column that carries "TAB" + string names
_TAB_LABEL_W: float = _TAB_CFG.tab_label_w_pt
_STRINGS_X0 = _MARGIN + _TAB_LABEL_W     # 62.5 pt from left edge

_NUM_STRINGS: int = _TAB_CFG.num_strings
_STRING_NAMES = ("e", "B", "G", "D", "A", "E")   # index 0 = string 1 = high e
_STRING_SPACING: float = _TAB_CFG.string_spacing_pt      # pts between adjacent strings
_STRINGS_HEIGHT = (_NUM_STRINGS - 1) * _STRING_SPACING   # 50 pt

# Rhythm notation (above sys_y = y of string 1)
_STEM_GAP: float = _TAB_CFG.stem_gap_pt      # gap between string-1 and stem base
_STEM_H: float = _TAB_CFG.stem_h_pt          # total stem height above string-1

# Text belt heights above sys_y
_CHORD_Y: float = _TAB_CFG.chord_y_pt        # chord-name baseline above sys_y
_TEMPO_Y: float = _TAB_CFG.tempo_y_pt        # tempo/timesig baseline above sys_y

# System vertical extents
_TOP_PAD: float = _TAB_CFG.top_pad_pt
_ABOVE_STRINGS = _TEMPO_Y + 7.0 + _TOP_PAD    # ~53 pt (was 44)
_BELOW_STRINGS: float = _TAB_CFG.below_strings_pt
_SYSTEM_H = _ABOVE_STRINGS + _STRINGS_HEIGHT + _BELOW_STRINGS   # ~109 pt (was 100)
_INTER_SYSTEM_GAP: float = _TAB_CFG.inter_system_gap_pt
_SYSTEM_PITCH = _SYSTEM_H + _INTER_SYSTEM_GAP   # ~117 pt  →  6 systems/page

# Note rendering
# With 10 pt string spacing:
#   oval ±3.5 pt, finger cap-top at string_y-3.65 (0.15 pt below oval bottom),
#   finger text bottom at string_y-7.7, gap to next string = 2.3 pt  ✓
_OVAL_H: float = _TAB_CFG.oval_h_pt          # oval covers string line (±3.5 pt from center)
_OVAL_W1: float = _TAB_CFG.oval_w_1digit_pt  # 1-digit fret
_OVAL_W2: float = _TAB_CFG.oval_w_2digit_pt  # 2-digit fret (10+)

_FRET_FONT = "Helvetica-Bold"
_FRET_FS: float = _TAB_CFG.fret_font_size_pt
# fret baseline = string_y - fret_fs*0.36  (centres the glyph vertically in oval)

# ── Left-hand (LH) finger annotation — south-west of note oval ──────────────
# drawRightString(x - oval_w/2, string_y + _LH_FINGER_Y, char)
#   → right edge of text aligns with left edge of oval  (SW corner)
#   → cap-top  ≈ string_y - 2.0  (below the string line, outside the oval)
#   → descender ≈ string_y - 7.0  (3 pt clear of the next string line) ✓
_LH_FINGER_FONT = "Helvetica-Bold"
_LH_FINGER_FS: float = _TAB_CFG.lh_finger_font_size_pt
_LH_FINGER_Y: float = _TAB_CFG.lh_finger_y_pt    # baseline offset from string_y
_LH_FINGER_COLOR = colors.Color(0.80, 0.05, 0.05)   # dark red

# ── Right-hand (RH) finger annotation — south-east of note oval ─────────────
# Reserved for Phase 2.  Mirror of LH:
#   drawString(x + oval_w/2, string_y + _RH_FINGER_Y, char)
#   → left edge of text aligns with right edge of oval  (SE corner)
_RH_FINGER_FONT = "Helvetica-Bold"
_RH_FINGER_FS: float = _TAB_CFG.rh_finger_font_size_pt
_RH_FINGER_Y: float = _TAB_CFG.rh_finger_y_pt    # same baseline as LH for visual symmetry
_RH_FINGER_COLOR = colors.Color(0.05, 0.05, 0.80)   # dark blue

# Column layout
_MIN_COL_STEP: float = _TAB_CFG.min_col_step_pt   # minimum x step between onset columns
_LEFT_PAD: float = _TAB_CFG.left_pad_pt           # padding inside measure left edge

_MNUM_Y: float = _TAB_CFG.measure_number_y_pt  # measure-number baseline above sys_y
_UNIT_W: float = _TAB_CFG.unit_w_pt            # pt per rhythmic unit for variable measure widths
_MIN_MEASURE_W: float = _TAB_CFG.min_measure_w_pt  # minimum measure width (whole-note measure)
_MAX_MEASURE_W: float = _TAB_CFG.max_measure_w_pt  # maximum measure width (very dense measure)

# Rest rendering — centred inside the staff
_REST_CENTER_Y: float = _TAB_CFG.rest_center_y_pt  # offset below sys_y: rest centre strings 3/4
_REST_DISC_R: float = _TAB_CFG.rest_disc_radius_pt     # radius of white disc around small rests
_REST_DISC_LW: float = _TAB_CFG.rest_disc_line_width_pt  # linewidth of the black ring on the disc

# Default / caps
_MPS_MIN: int = _TAB_CFG.measures_per_system_min
_MPS_MAX: int = _TAB_CFG.measures_per_system_max

# String-name / TAB-label geometry
_SNAME_X = _MARGIN + _TAB_CFG.sname_x_offset_pt  # x for string-name right edge
_TAB_X = _MARGIN + _TAB_CFG.tab_x_offset_pt      # x for "T/A/B" centre

# Colours
_COL_BLACK = colors.black
_COL_GREY = colors.Color(0.5, 0.5, 0.5)
_COL_LGREY = colors.Color(0.75, 0.75, 0.75)

# Finger character map
_FINGER_CHAR: dict[Finger, str] = {
    Finger.INDEX: "i",
    Finger.MIDDLE: "m",
    Finger.RING: "r",
    Finger.PINKY: "p",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_pdf_tab(
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
    """Render fingering results as a professional A4 PDF tablature file.

    Args:
        results: FingeringResult list from the optimisation pipeline.
        output_path: Destination PDF path (created or overwritten).
        title: Song title shown in the header block.
        artist: Artist / composer name.
        beats_per_measure: Numerator of the time signature (default 4.0).
        mode_label: Optional label below artist (e.g. "reference mode").
        instrument: Name of the instrument / track (e.g. "Electric Guitar").
        measures_per_system: Optional override for measures per system.
        section_markers: Optional mapping of 1-based measure number → section
            title (e.g. {1: "Intro", 9: "Verse 1"}).
        chord_diagrams: Optional list of ChordDiagram objects to render in a
            compact strip at the top of the first page (up to 12 diagrams).
    """
    c = rl_canvas.Canvas(str(output_path), pagesize=(_PAGE_W, _PAGE_H))
    _section_markers: dict[int, str] = section_markers or {}

    if not results:
        c.setFont("Helvetica", 12)
        c.setFillColor(_COL_BLACK)
        c.drawString(_MARGIN, _PAGE_H / 2, "(no notes)")
        c.save()
        return

    measures = _group_by_measure(results, beats_per_measure)
    first_song_measure = int(results[0].note_event.onset / beats_per_measure) + 1
    _available_w = _PAGE_W - _MARGIN - _STRINGS_X0

    forced_mps: int | None = None
    if measures_per_system is not None:
        forced_mps = max(_MPS_MIN, min(_MPS_MAX, measures_per_system))

    systems = _build_systems(measures, beats_per_measure, _available_w, forced_mps)

    # ── Page 1: rhythm legend (+ chord diagrams when present)
    legend_bottom = _draw_rhythm_legend(c, _PAGE_H - _MARGIN)
    if chord_diagrams:
        # Draw chord diagrams below the legend on the same page.
        _draw_chord_diagram_header(c, chord_diagrams, legend_bottom)
    c.showPage()

    current_top = _PAGE_H - _MARGIN

    # ── Title block on page 2 (first tab page)
    if title or artist or mode_label or instrument:
        current_top = _draw_title_block(c, title, artist, instrument, mode_label, current_top)

    # ── Render systems
    m_idx = 0
    first_system_on_page = True
    prev_tempo: float = -1.0

    for sys_idx, (sys_measures, measure_widths) in enumerate(systems):
        song_m_start = first_song_measure + m_idx
        m_idx += len(sys_measures)

        sys_tempo = _system_tempo(sys_measures, results[0].note_event.tempo)
        show_tempo = (sys_tempo != prev_tempo)

        sys_y = current_top - _ABOVE_STRINGS
        system_bottom = sys_y - _STRINGS_HEIGHT - _BELOW_STRINGS

        if system_bottom < _MARGIN:
            c.showPage()
            current_top = _PAGE_H - _MARGIN
            first_system_on_page = True
            sys_y = current_top - _ABOVE_STRINGS
            system_bottom = sys_y - _STRINGS_HEIGHT - _BELOW_STRINGS

        is_last = sys_idx == len(systems) - 1
        _draw_system(
            c, sys_measures, sys_y, song_m_start,
            beats_per_measure, measure_widths, sys_tempo, show_tempo,
            first_system_on_page, _section_markers, is_last,
        )
        prev_tempo = sys_tempo
        first_system_on_page = False
        current_top = system_bottom - _INTER_SYSTEM_GAP

    c.save()


# ---------------------------------------------------------------------------
# Page-level helpers
# ---------------------------------------------------------------------------


def _draw_title_block(
    c: rl_canvas.Canvas,
    title: str,
    artist: str,
    instrument: str,
    mode_label: str,
    top_y: float,
) -> float:
    """Draw title / artist block; return y immediately below it."""
    y = top_y - 8.0

    if title:
        c.setFont("Helvetica-Bold", 18)
        c.setFillColor(_COL_BLACK)
        c.drawString(_MARGIN, y - 18, title)
        y -= 24

    if artist:
        c.setFont("Helvetica", 12)
        c.setFillColor(_COL_BLACK)
        c.drawString(_MARGIN, y - 12, artist)
        y -= 17

    # Instrument + mode on same line
    parts = []
    if instrument:
        parts.append(instrument)
    if mode_label:
        parts.append(mode_label)
    if parts:
        c.setFont("Helvetica-Oblique", 8.5)
        c.setFillColor(_COL_GREY)
        c.drawString(_MARGIN, y - 8.5, "  ·  ".join(parts))
        c.setFillColor(_COL_BLACK)
        y -= 13

    # Separator
    c.setLineWidth(0.8)
    c.setStrokeColor(_COL_BLACK)
    c.line(_MARGIN, y - 4, _PAGE_W - _MARGIN, y - 4)
    return y - 12


# Chord diagram header constants (compact, first-page-only strip)
_CD_CELL_W: float = _TAB_CFG.chord_diagram_cell_w_pt   # small cell width for header diagrams
_CD_CELL_H: float = _TAB_CFG.chord_diagram_cell_h_pt   # small cell height
_CD_FRET_ROWS: int = _TAB_CFG.chord_diagram_fret_rows
_CD_MAX: int = _TAB_CFG.chord_diagram_max       # cap displayed diagrams
_CD_COLS: int = _TAB_CFG.chord_diagram_cols     # diagrams per row in the header strip


def _draw_chord_diagram_header(
    c: rl_canvas.Canvas,
    diagrams: list[ChordDiagram],
    top_y: float,
) -> float:
    """Draw a compact chord-diagram strip at the top of the first page.

    Uses small diagrams (cell_w=7, cell_h=7).  Shows up to _CD_MAX diagrams
    in 1–2 rows.  Adds a thin separator line below the strip.

    Args:
        c: ReportLab Canvas.
        diagrams: Chord diagrams to render.
        top_y: Y coordinate of the top of the available area.

    Returns:
        Y coordinate immediately below the rendered strip.
    """
    shown = diagrams[:_CD_MAX]
    if not shown:
        return top_y

    n_strings = 6  # assume standard
    box_w = (n_strings - 1) * _CD_CELL_W
    slot_w = box_w + 22.0   # per-diagram slot width (includes right margin)
    slot_h = 12.0 + 7.0 + _CD_FRET_ROWS * _CD_CELL_H + 4.0  # per-row height

    usable_w = _PAGE_W - 2 * _MARGIN
    cols_per_row = max(1, int(usable_w / slot_w))
    cols_per_row = min(cols_per_row, _CD_COLS)

    # Determine rows needed.
    rows = math.ceil(len(shown) / cols_per_row)
    total_strip_h = rows * slot_h + 8.0  # 8 pt bottom padding before separator

    # Place diagrams top-down.
    for i, diagram in enumerate(shown):
        row = i // cols_per_row
        col = i % cols_per_row
        dx = _MARGIN + col * slot_w + (slot_w - box_w) / 2
        # y = top of box for this diagram
        dy = top_y - 12.0 - row * slot_h
        draw_chord_diagram(c, diagram, dx, dy, cell_w=_CD_CELL_W, cell_h=_CD_CELL_H,
                           fret_rows=_CD_FRET_ROWS)

    # Separator line below the strip.
    sep_y = top_y - total_strip_h
    c.setLineWidth(0.5)
    c.setStrokeColor(_COL_LGREY)
    c.line(_MARGIN, sep_y, _PAGE_W - _MARGIN, sep_y)
    c.setStrokeColor(_COL_BLACK)

    return sep_y - 6.0


# ---------------------------------------------------------------------------
# System-level rendering
# ---------------------------------------------------------------------------


def _draw_system(
    c: rl_canvas.Canvas,
    sys_measures: list[list[FingeringResult]],
    sys_y: float,
    song_m_start: int,
    beats_per_measure: float,
    measure_widths: list[float],
    sys_tempo: float,
    show_tempo: bool,
    first_on_page: bool,
    section_markers: dict[int, str] | None = None,
    is_last_system: bool = False,
) -> None:
    """Draw one complete tab system.

    Args:
        sys_y: y-coordinate of string 1 (high e) in ReportLab coords.
    """
    strings_x1 = _PAGE_W - _MARGIN
    x_right = _STRINGS_X0 + sum(measure_widths)

    # ── TAB label + string names on the left
    _draw_tab_label(c, sys_y, first_on_page)

    # ── Six string lines
    c.setStrokeColor(_COL_BLACK)
    c.setLineWidth(0.4)
    for si in range(_NUM_STRINGS):
        sy = sys_y - si * _STRING_SPACING
        c.line(_STRINGS_X0, sy, x_right, sy)

    # ── Tempo / time-sig line
    if show_tempo:
        # Time signature in normal weight, then quarter-note symbol + BPM in oblique.
        ts_text = f"{int(beats_per_measure)}/4"
        bpm_text = f"\u2669 = {sys_tempo:.0f}"
        c.setFont("Helvetica", 7.5)
        c.setFillColor(_COL_GREY)
        ts_w = c.stringWidth(ts_text, "Helvetica", 7.5)
        c.drawString(_STRINGS_X0, sys_y + _TEMPO_Y, ts_text)
        c.setFont("Helvetica-Oblique", 7.5)
        c.drawString(_STRINGS_X0 + ts_w + 5, sys_y + _TEMPO_Y, bpm_text)
        c.setFillColor(_COL_BLACK)

    # ── Measures
    cumulative_x = [_STRINGS_X0]
    for w in measure_widths:
        cumulative_x.append(cumulative_x[-1] + w)

    for slot, measure_results in enumerate(sys_measures):
        x0 = cumulative_x[slot]
        x1 = cumulative_x[slot + 1]

        # Bar line (double for first measure of system)
        if slot == 0:
            c.setLineWidth(1.5)
            c.setStrokeColor(_COL_BLACK)
            c.line(x0, sys_y + 1, x0, sys_y - _STRINGS_HEIGHT - 1)
            c.setLineWidth(0.5)
            c.line(x0 + 2.5, sys_y + 1, x0 + 2.5, sys_y - _STRINGS_HEIGHT - 1)
        else:
            c.setLineWidth(0.5)
            c.setStrokeColor(_COL_BLACK)
            c.line(x0, sys_y + 1, x0, sys_y - _STRINGS_HEIGHT - 1)

        # Measure number (small grey, between chord belt and tempo line)
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawString(x0 + 3, sys_y + _MNUM_Y, str(song_m_start + slot))
        c.setFillColor(_COL_BLACK)

        # Section label (bold, above tempo line)
        if section_markers:
            section_title = section_markers.get(song_m_start + slot)
            if section_title:
                c.setFont("Helvetica-Bold", 7.5)
                c.setFillColor(colors.Color(0.15, 0.15, 0.55))  # dark blue
                c.drawString(x0 + 2, sys_y + _ABOVE_STRINGS - 4, section_title)
                c.setFillColor(_COL_BLACK)

        if measure_results:
            _draw_measure(c, measure_results, x0, x1, sys_y, beats_per_measure)

    # ── Right bar line (double + thick for final system, single otherwise)
    c.setStrokeColor(_COL_BLACK)
    if is_last_system:
        c.setLineWidth(0.5)
        c.line(x_right - 3.5, sys_y + 1, x_right - 3.5, sys_y - _STRINGS_HEIGHT - 1)
        c.setLineWidth(2.0)
        c.line(x_right, sys_y + 1, x_right, sys_y - _STRINGS_HEIGHT - 1)
    else:
        c.setLineWidth(0.5)
        c.line(x_right, sys_y + 1, x_right, sys_y - _STRINGS_HEIGHT - 1)


def _draw_tab_label(c: rl_canvas.Canvas, sys_y: float, first_on_page: bool) -> None:
    """Draw 'TAB' + string names + left bracket for one system."""
    mid_y = sys_y - _STRINGS_HEIGHT / 2

    # "TAB" stacked vertically
    c.setFont("Helvetica-Bold", 7.0)
    c.setFillColor(_COL_BLACK)
    for i, ch in enumerate("TAB"):
        c.drawCentredString(_TAB_X, mid_y + (1 - i) * 9.5, ch)

    # String names right-aligned just before STRINGS_X0
    c.setFont("Helvetica", 6.5)
    c.setFillColor(_COL_GREY)
    for si, name in enumerate(_STRING_NAMES):
        sy = sys_y - si * _STRING_SPACING
        c.drawRightString(_SNAME_X, sy - 2.5, name)
    c.setFillColor(_COL_BLACK)

    # Left bracket (thin vertical bar)
    c.setLineWidth(0.7)
    c.setStrokeColor(_COL_BLACK)
    c.line(_STRINGS_X0 - 2, sys_y + 1, _STRINGS_X0 - 2, sys_y - _STRINGS_HEIGHT - 1)


# ---------------------------------------------------------------------------
# Measure-level rendering
# ---------------------------------------------------------------------------


def _draw_measure(
    c: rl_canvas.Canvas,
    results: list[FingeringResult],
    x0: float,
    x1: float,
    sys_y: float,
    beats_per_measure: float,
) -> None:
    """Draw notes, stems, beams, chord names for one measure."""
    measure_w = x1 - x0
    measure_onset = (
        math.floor(results[0].note_event.onset / beats_per_measure) * beats_per_measure
    )

    # ── Group by onset
    onset_map: dict[float, list[FingeringResult]] = {}
    for r in results:
        key = round(r.note_event.onset, 6)
        onset_map.setdefault(key, []).append(r)
    sorted_onsets = sorted(onset_map.keys())

    # ── Constrained proportional x positions
    onset_x = _compute_onset_x(sorted_onsets, x0, measure_w, measure_onset, beats_per_measure)

    # ── Chord names by beat
    beat_groups: dict[int, list[float]] = {}
    for onset in sorted_onsets:
        beat = int(math.floor(onset - measure_onset))
        beat_groups.setdefault(beat, []).append(onset)

    prev_chord: str | None = None
    prev_chord_x_right: float = -999.0   # right edge of the last drawn chord name
    for beat in sorted(beat_groups):
        pitches = [r.note_event.pitch for o in beat_groups[beat] for r in onset_map[o]]
        chord = recognize_chord(pitches)
        if chord and chord != prev_chord:
            cx = onset_x[beat_groups[beat][0]]
            c.setFont("Helvetica-Bold", 6.5)
            chord_w = c.stringWidth(chord, "Helvetica-Bold", 6.5)
            # Skip if this chord name would overlap the previous one
            if cx - 2 > prev_chord_x_right + 2:
                c.setFillColor(_COL_BLACK)
                # Truncate if chord name overflows into the right margin of the measure
                max_w = (x0 + measure_w) - (cx - 2) - 3.0
                display_chord = chord
                if chord_w > max_w:
                    while c.stringWidth(display_chord + "\u2026", "Helvetica-Bold", 6.5) > max_w and len(display_chord) > 1:
                        display_chord = display_chord[:-1]
                    display_chord += "\u2026"
                    chord_w = c.stringWidth(display_chord, "Helvetica-Bold", 6.5)
                c.drawString(cx - 2, sys_y + _CHORD_Y, display_chord)
                prev_chord_x_right = cx - 2 + chord_w
                prev_chord = chord

    # ── Build stem info list
    stem_info: list[tuple[float, float, float]] = []   # (x, onset, min_duration)
    for onset in sorted_onsets:
        nx = onset_x[onset]
        dur = min(r.note_event.duration for r in onset_map[onset])
        stem_info.append((nx, onset, dur))

    # ── Compute rests first — needed for beat-aware beaming analysis
    rests = _compute_rests(sorted_onsets, onset_map, measure_onset, beats_per_measure)

    # ── Beaming analysis (beat-aware, rest-aware)
    beam_groups = _get_beam_groups(stem_info, beats_per_measure, measure_onset)
    beamed: set[float] = {onset for grp in beam_groups for _, onset, _ in grp}

    # ── Draw stems  (before notes so note ovals cover the stem base)
    # Convention (confirmed by Guitar Pro / standard tab publishers):
    #   • Whole  note (≥ 2 beats) : fret number enclosed in visible oval — NO stem
    #   • Half   note (≥ 1 beat)  : fret number enclosed in visible oval + stem (no flag)
    #   • Quarter note (≥ 0.5)    : fret number, white-bg oval (no stroke) + stem (no flag)
    #   • 8th   note (≥ 0.25)     : same + one flag OR single beam bar
    #   • 16th  note (< 0.25)     : same + two flags OR two beam bars
    # No notehead shape at the top of the stem — the fret-number oval IS the notehead.
    stem_bot = sys_y + _STEM_GAP
    stem_top = sys_y + _STEM_H
    c.setStrokeColor(_COL_BLACK)
    c.setFillColor(_COL_BLACK)
    for nx, onset, dur in stem_info:
        base_dur = _dotted_base(dur)
        if base_dur >= 4.0:
            continue          # whole note (or dotted whole): no stem
        c.setLineWidth(0.8)
        c.line(nx, stem_bot, nx, stem_top)
        if base_dur < 1.0 and onset not in beamed:   # unbeamed 8th / 16th / 32nd: draw flags
            for fi in range(_num_flags(dur)):
                _draw_flag(c, nx, stem_top - fi * 4.0)

    # ── Draw beams
    _draw_beams(c, beam_groups, stem_top)

    # ── Draw rests inside the staff (centred vertically, white disc for small values)
    for rest_onset, rest_dur in rests:
        rel = max(0.0, rest_onset - measure_onset)
        frac = min(rel / beats_per_measure, 0.97)
        rx = x0 + _LEFT_PAD + frac * (measure_w - _LEFT_PAD - 5.0)
        _draw_rest(c, rx, sys_y, rest_dur)

    # ── Per-measure rhythm checksum
    # Compute coverage = beats actually covered by note attacks + rest gaps.
    # Uses max(duration) per onset column (chord notes all share the same beat duration).
    # A mismatch > 0.1 beat indicates a GP-file quantisation oddity — shown in red.
    _draw_measure_checksum(
        c, sorted_onsets, onset_map, rests, measure_onset, beats_per_measure, x0, sys_y
    )

    # ── Let-ring lines  (before notes so ovals cover the line start)
    _draw_let_ring(c, onset_map, onset_x, x1, sys_y)

    # ── Draw notes  (on top of everything)
    for onset in sorted_onsets:
        nx = onset_x[onset]
        for r in onset_map[onset]:
            sy = sys_y - (r.state.string_num - 1) * _STRING_SPACING
            _draw_note(c, nx, sy, r)

    # ── Draw notation symbols (after notes so they appear on top)
    _draw_slide_lines(c, onset_map, onset_x, sys_y)
    _draw_slur_arcs(c, onset_map, onset_x, sys_y)
    _draw_pm_brackets(c, onset_map, onset_x, x0, x1, sys_y)


_LET_RING_COLOR = colors.Color(0.25, 0.25, 0.70)   # muted blue
_LET_RING_DASH = [2.5, 2.0]                          # on, off in pt


def _draw_let_ring(
    c: rl_canvas.Canvas,
    onset_map: dict[float, list[FingeringResult]],
    onset_x: dict[float, float],
    x_right: float,
    sys_y: float,
) -> None:
    """Draw dashed let-ring lines for each marked note.

    For each let-ring note, a thin dashed line runs from the note's oval right
    edge to the next onset on the same string (or the measure right edge).
    A tiny "l.r." label appears at the line's left end.
    """
    # Build per-string onset lists to find the next note on same string.
    string_onsets: dict[int, list[tuple[float, float]]] = {}  # string → [(onset, x)]
    for onset, results in onset_map.items():
        nx = onset_x[onset]
        for r in results:
            s = r.state.string_num
            string_onsets.setdefault(s, []).append((onset, nx))
    for s in string_onsets:
        string_onsets[s].sort()

    c.setStrokeColor(_LET_RING_COLOR)
    c.setFillColor(_LET_RING_COLOR)
    c.setLineWidth(0.5)
    c.setDash(_LET_RING_DASH)

    for onset in sorted(onset_map):
        nx = onset_x[onset]
        for r in onset_map[onset]:
            if not r.note_event.let_ring:
                continue
            s = r.state.string_num
            sy = sys_y - (s - 1) * _STRING_SPACING
            oval_w = _OVAL_W2 if r.state.fret >= 10 else _OVAL_W1
            line_x0 = nx + oval_w / 2 + 1.0

            # End of line: next note on the same string, or measure right edge.
            line_x1 = x_right - 2.0
            if s in string_onsets:
                for other_onset, other_x in string_onsets[s]:
                    if other_onset > onset + 1e-6:
                        line_x1 = min(other_x - oval_w / 2 - 1.0, x_right - 2.0)
                        break

            if line_x1 > line_x0 + 3.0:
                c.line(line_x0, sy, line_x1, sy)
                # "l.r." micro label
                c.setFont("Helvetica-Oblique", 4.0)
                c.drawString(line_x0 + 1.0, sy + 1.5, "l.r.")

    c.setDash([])   # restore solid line
    c.setStrokeColor(_COL_BLACK)
    c.setFillColor(_COL_BLACK)


def _compute_onset_x(
    sorted_onsets: list[float],
    x0: float,
    measure_w: float,
    measure_onset: float,
    beats_per_measure: float,
) -> dict[float, float]:
    """Proportional x positions with a forward-pass minimum-step guarantee.

    Notes are placed proportionally to their onset time within the measure.
    A forward-pass ensures consecutive columns are always ≥ _MIN_COL_STEP apart,
    preventing any horizontal overlaps regardless of note density.
    """
    usable_w = measure_w - _LEFT_PAD - 5.0
    onset_x: dict[float, float] = {}
    prev_x = x0 + _LEFT_PAD - _MIN_COL_STEP   # sentinel: allows first note at exactly x0+LEFT_PAD

    for onset in sorted_onsets:
        rel = max(0.0, onset - measure_onset)
        frac = min(rel / beats_per_measure, 0.97)
        prop_x = x0 + _LEFT_PAD + frac * usable_w
        x = max(prop_x, prev_x + _MIN_COL_STEP)
        onset_x[onset] = x
        prev_x = x

    return onset_x


# ---------------------------------------------------------------------------
# Rhythm helpers
# ---------------------------------------------------------------------------

# Standard undotted base values in beats.
_STANDARD_BASES: tuple[float, ...] = (8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625)


def _is_dotted(dur: float) -> bool:
    """Return True if *dur* matches a dotted note value (base × 1.5)."""
    return any(abs(dur - b * 1.5) < 0.01 for b in _STANDARD_BASES)


def _dotted_base(dur: float) -> float:
    """Return the undotted base duration for a dotted note, else *dur* unchanged."""
    for b in _STANDARD_BASES:
        if abs(dur - b * 1.5) < 0.01:
            return b
    return dur


def _num_flags(duration: float) -> int:
    """Number of stem flags for a given duration in beats.

    Dotted notes use the flag count of their undotted base (e.g. dotted eighth
    = 1 flag, same as a plain eighth).

    Quarter note (1.0 beat) and longer → 0 flags.
    Eighth note (0.5 beat)            → 1 flag.
    Sixteenth note (0.25 beat)        → 2 flags.
    Thirty-second note (0.125 beat)   → 3 flags.
    """
    base = _dotted_base(duration)  # no-op if not dotted
    if base >= 1.0:
        return 0
    if base >= 0.5:
        return 1
    if base >= 0.25:
        return 2
    return 3


def _draw_flag(c: rl_canvas.Canvas, x: float, y: float) -> None:
    """Draw a single flag curve starting at (x, y) sweeping down-right."""
    c.setLineWidth(0.7)
    c.setStrokeColor(_COL_BLACK)
    p = c.beginPath()
    p.moveTo(x, y)
    p.curveTo(x + 5.5, y - 2.0, x + 6.0, y - 5.0, x + 3.5, y - 8.5)
    c.drawPath(p, stroke=1, fill=0)


def _get_beam_groups(
    stem_info: list[tuple[float, float, float]],
    beats_per_measure: float,
    measure_onset: float,
) -> list[list[tuple[float, float, float]]]:
    """Return meter-aware beam groups for the notes in a measure.

    Each group is a list of ``(x, onset, duration)`` tuples for notes that
    should be connected by a primary beam bar.  A group requires ≥ 2 notes.

    Rules applied:
    - Only notes with ``duration < 1.0`` beat (shorter than a quarter note)
      can be beamed.
    - The base break is the **quarter-note beat** (``measure_onset + N``) and
      any **rest gap ≥ 1/32 beat (0.115 b)**.
    - In simple duple/quadruple meters (e.g. 4/4) a run made up entirely of
      on-grid eighth notes is then beamed by the **half-note unit** (4 eighths
      per group in 4/4), matching MuseScore.  Runs containing a sixteenth (or
      shorter), an off-grid/tuplet onset, or a rest gap stay per beat.
    - A group with a single note is dropped; the note keeps its flags.

    Args:
        stem_info: List of ``(x, onset, duration)`` sorted by onset.
        beats_per_measure: Time-signature numerator (e.g. 4.0 for 4/4); the
            PDF tab always renders an x/4 meter.
        measure_onset: Absolute beat onset of the first beat of this measure.

    Returns:
        List of beam groups; each group is a list of ``(x, onset, duration)``
        tuples with ≥ 2 entries.
    """
    # Quarter-beat boundaries within this measure (exclusive of measure start).
    beat_boundaries = frozenset(
        round(measure_onset + k, 9)
        for k in range(1, int(beats_per_measure + 0.5))
    )

    # First split at every quarter beat / rest gap, keeping singletons so the
    # half-bar merge can reason about adjacency.  ``gap_before[i]`` flags a rest
    # gap immediately before quarter-group ``i`` (which blocks any merge).
    quarter_groups: list[list[tuple[float, float, float]]] = []
    gap_before: list[bool] = []
    current: list[tuple[float, float, float]] = []
    for x, onset, dur in stem_info:
        if dur >= 1.0:
            # Quarter note or longer: not beamable — close the current group.
            if current:
                quarter_groups.append(current)
            current = []
            continue
        if not current:
            current.append((x, onset, dur))
            gap_before.append(False)
            continue
        _prev_x, prev_onset, prev_dur = current[-1]
        prev_end = prev_onset + prev_dur
        has_rest = (onset - prev_end) >= _TAB_CFG.rest_gap_threshold_beats
        crosses_beat = any(prev_onset < bb <= onset for bb in beat_boundaries)
        if has_rest or crosses_beat:
            quarter_groups.append(current)
            current = [(x, onset, dur)]
            gap_before.append(has_rest)
        else:
            current.append((x, onset, dur))
    if current:
        quarter_groups.append(current)

    merged = _merge_eighth_beam_groups_pdf(
        quarter_groups,
        gap_before=gap_before,
        measure_onset=measure_onset,
        beats_per_measure=beats_per_measure,
    )
    return [group for group in merged if len(group) >= 2]


def _eighth_beam_unit_pdf(beats_per_measure: float) -> float:
    """Return the quarter-beat span of one eighth-note beam group (x/4 meter).

    2.0 beams eighths by the half note (4/4, 8/4, …); 1.0 keeps the per-beat
    unit (e.g. 3/4) so the half-bar merge is a no-op.
    """
    num = int(beats_per_measure + 0.5)
    if num >= 4 and num % 2 == 0:
        return 2.0
    return 1.0


def _is_pure_eighth_on_grid_pdf(
    group: list[tuple[float, float, float]], *, measure_onset: float
) -> bool:
    """True if every note is an eighth (1 flag) sitting on the 0.5-beat grid."""
    for _x, onset, dur in group:
        if _num_flags(dur) != 1:
            return False
        rel = onset - measure_onset
        if abs(round(rel / 0.5) * 0.5 - rel) > 1e-6:
            return False
    return True


def _merge_eighth_beam_groups_pdf(
    quarter_groups: list[list[tuple[float, float, float]]],
    *,
    gap_before: list[bool],
    measure_onset: float,
    beats_per_measure: float,
) -> list[list[tuple[float, float, float]]]:
    """Merge adjacent per-beat groups into half-bar eighth-note beam groups.

    Two consecutive quarter groups merge when they fall in the same half-bar
    window, are contiguous (no rest gap between them), and both contain only
    on-grid eighth notes — reproducing MuseScore's 4-eighths-per-half-note
    grouping in 4/4 while leaving sixteenth/tuplet runs per beat.
    """
    unit = _eighth_beam_unit_pdf(beats_per_measure)
    if unit <= 1.0:
        return quarter_groups

    merged: list[list[tuple[float, float, float]]] = []
    for idx, group in enumerate(quarter_groups):
        if not merged:
            merged.append(list(group))
            continue
        prev = merged[-1]
        same_unit = (
            int((group[0][1] - measure_onset) // unit)
            == int((prev[0][1] - measure_onset) // unit)
        )
        contiguous = not (idx < len(gap_before) and gap_before[idx])
        if (
            same_unit
            and contiguous
            and _is_pure_eighth_on_grid_pdf(prev, measure_onset=measure_onset)
            and _is_pure_eighth_on_grid_pdf(group, measure_onset=measure_onset)
        ):
            prev.extend(group)
        else:
            merged.append(list(group))
    return merged


def _draw_beams(
    c: rl_canvas.Canvas,
    groups: list[list[tuple[float, float, float]]],
    beam_y: float,
) -> None:
    """Draw filled beam bars for each beam group.

    For each group:
    - A **primary beam** (8th-note bar) spans from the first to the last stem.
    - A **partial secondary beam** (16th-note bar) is drawn only over
      consecutive runs of notes with ``duration < 0.5`` (16th notes or
      shorter) within the group.  This correctly handles mixed groups that
      contain both eighth and sixteenth notes.

    Args:
        c: ReportLab canvas.
        groups: Beam groups as returned by :func:`_get_beam_groups`.
        beam_y: Y coordinate of the top of the primary beam bar.
    """
    if not groups:
        return
    BEAM_H = _TAB_CFG.beam_h_pt
    BEAM_GAP = _TAB_CFG.beam_gap_pt
    c.setFillColor(_COL_BLACK)

    for group in groups:
        if len(group) < 2:
            continue
        gx0 = group[0][0]
        gx1 = group[-1][0]

        # Primary beam (8th-note bar): full span of the group
        c.rect(gx0, beam_y - BEAM_H, gx1 - gx0, BEAM_H, fill=1, stroke=0)

        # Secondary beam (16th-note bar): partial, only over runs of dur < 0.5
        _draw_secondary_beam(c, group, beam_y, BEAM_H, BEAM_GAP)


def _draw_secondary_beam(
    c: rl_canvas.Canvas,
    group: list[tuple[float, float, float]],
    beam_y: float,
    beam_h: float,
    beam_gap: float,
) -> None:
    """Draw partial secondary beam segments for 16th-note runs within a group.

    Scans the group for consecutive sub-eighth notes (``duration < 0.5``).
    Each such run gets its own secondary bar at ``beam_y - beam_h - beam_gap``.
    A run of length 1 (isolated 16th inside a predominantly-eighth group) still
    gets a short partial bar spanning half the column step on each side.

    Args:
        c: ReportLab canvas.
        group: Beam group (list of ``(x, onset, duration)`` tuples).
        beam_y: Y of primary beam top edge.
        beam_h: Height of each beam bar.
        beam_gap: Vertical gap between primary and secondary bars.
    """
    y2_top = beam_y - beam_h - beam_gap
    run: list[float] = []   # x positions of current 16th-note run

    def flush() -> None:
        if not run:
            return
        if len(run) >= 2:
            c.rect(run[0], y2_top - beam_h, run[-1] - run[0], beam_h, fill=1, stroke=0)
        else:
            # Isolated 16th: draw a short stub (half min-col-step on each side)
            stub = _MIN_COL_STEP * 0.4
            c.rect(run[0] - stub, y2_top - beam_h, stub * 2, beam_h, fill=1, stroke=0)

    for x, _, dur in group:
        if dur < 0.5:
            run.append(x)
        else:
            flush()
            run = []
    flush()


# ---------------------------------------------------------------------------
# Rest computation and rendering
# ---------------------------------------------------------------------------

# Standard note values in descending order (beats), used for subdivision.
_REST_VALUES: tuple[float, ...] = (4.0, 2.0, 1.0, 0.5, 0.25, 0.125)


def _subdivide_rest(onset: float, duration: float) -> list[tuple[float, float]]:
    """Split *duration* beats into the largest standard values that fit.

    Returns a list of (onset, value) pairs in chronological order.
    """
    result: list[tuple[float, float]] = []
    cur = onset
    remaining = duration
    for val in _REST_VALUES:
        while remaining >= val - 0.01:
            result.append((cur, val))
            cur += val
            remaining = max(0.0, remaining - val)
    return result


def _compute_rests(
    sorted_onsets: list[float],
    onset_map: dict[float, list[FingeringResult]],
    measure_onset: float,
    beats_per_measure: float,
) -> list[tuple[float, float]]:
    """Compute rests needed to fill the gaps inside a measure.

    For each gap between consecutive note onsets (or between the last note
    and the measure end) that is ≥ 1/32nd note (0.125 beats), subdivide
    the gap into standard rest values.

    Returns a list of (onset, duration) pairs sorted by onset.
    """
    rests: list[tuple[float, float]] = []
    cur = measure_onset

    for onset in sorted_onsets:
        gap = onset - cur
        if gap >= _TAB_CFG.rest_gap_threshold_beats:  # ~1/32, tolerates float drift
            rests.extend(_subdivide_rest(cur, gap))
        # Advance cursor to end of this beat (use longest note at this onset)
        max_dur = max(r.note_event.duration for r in onset_map[onset])
        cur = max(cur, onset + max_dur)

    # Gap between last note end and measure end
    measure_end = measure_onset + beats_per_measure
    if cur < measure_end - 0.05:
        rests.extend(_subdivide_rest(cur, measure_end - cur))

    return rests


def _draw_rest(c: rl_canvas.Canvas, rx: float, sys_y: float, duration: float) -> None:
    """Draw one rest symbol centred at the staff vertical midpoint.

    The rest centre is ``sys_y - _REST_CENTER_Y``, placing it exactly between
    strings 3 (G) and 4 (D) regardless of note density above or below.

    Rendering strategy
    ------------------
    - **Pause (≥ 4 beats)** and **demi-pause (≥ 2 beats)**: horizontal filled
      rectangles.  Their shape does not overlap string lines at the centre
      position so no disc is needed.
    - **Soupir, ½ soupir, ¼ soupir, ⅛ soupir** (< 2 beats): a white disc
      with a black ring is drawn first to erase the string lines behind the
      symbol; the rest glyph is then drawn inside the disc.

    Args:
        c: ReportLab canvas.
        rx: Horizontal centre of the rest symbol.
        sys_y: Y-coordinate of string 1 — the system reference line.
        duration: Duration in beats (4.0 = whole, 2.0 = half, 1.0 = quarter…).
    """
    ref = sys_y - _REST_CENTER_Y      # vertical centre of the staff

    c.setFillColor(_COL_BLACK)
    c.setStrokeColor(_COL_BLACK)

    if duration >= 4.0:
        # Pause: filled rect hanging below a ledger line — no disc needed
        c.setLineWidth(0.4)
        c.line(rx - 5.5, ref, rx + 5.5, ref)
        c.rect(rx - 4, ref - 3.5, 8, 3, fill=1, stroke=0)

    elif duration >= 2.0:
        # Demi-pause: filled rect sitting on a ledger line — no disc needed
        c.setLineWidth(0.4)
        c.line(rx - 5.5, ref - 3.5, rx + 5.5, ref - 3.5)
        c.rect(rx - 4, ref - 3.5, 8, 3, fill=1, stroke=0)

    else:
        # Small rest symbols: draw white disc first to erase string lines
        c.setFillColor(colors.white)
        c.setStrokeColor(_COL_BLACK)
        c.setLineWidth(_REST_DISC_LW)
        c.circle(rx, ref, _REST_DISC_R, fill=1, stroke=1)
        c.setFillColor(_COL_BLACK)
        c.setStrokeColor(_COL_BLACK)

        if duration >= 1.0:
            # Soupir (quarter rest): squiggly path centred at ref
            c.setLineWidth(0.8)
            yt = ref + 4.0
            yb = ref - 4.5
            p = c.beginPath()
            p.moveTo(rx - 2.0, yt)
            p.lineTo(rx + 2.5, yt - 2.5)
            p.curveTo(rx + 4.0, yt - 3.5, rx - 3.5, yt - 6.0, rx + 0.5, yt - 7.0)
            p.curveTo(rx + 2.5, yt - 8.0, rx - 1.0, yb + 1.5, rx + 0.5, yb)
            c.drawPath(p, stroke=1, fill=0)

        elif duration >= 0.5:
            # Demi-soupir (eighth rest): diagonal stem + one filled dot
            c.setLineWidth(0.8)
            yt = ref + 3.0
            yb = ref - 3.5
            c.line(rx - 1.5, yb, rx + 1.5, yt - 2.0)
            c.setLineWidth(0.0)
            c.circle(rx + 2.5, yt - 1.0, 1.5, fill=1, stroke=0)

        elif duration >= 0.25:
            # Quart de soupir (16th rest): diagonal stem + two stacked dots
            c.setLineWidth(0.8)
            yt = ref + 3.5
            yb = ref - 3.5
            c.line(rx - 1.5, yb, rx + 2.0, yt - 2.0)
            c.setLineWidth(0.0)
            c.circle(rx + 2.5, yt - 1.0, 1.4, fill=1, stroke=0)
            c.circle(rx + 0.5, ref - 0.5, 1.4, fill=1, stroke=0)

        else:
            # Huitième de soupir (32nd rest): diagonal stem + three dots
            c.setLineWidth(0.8)
            yt = ref + 3.5
            yb = ref - 4.0
            c.line(rx - 1.5, yb, rx + 2.0, yt - 2.0)
            c.setLineWidth(0.0)
            c.circle(rx + 2.5, yt - 1.0, 1.3, fill=1, stroke=0)
            c.circle(rx + 0.5, ref - 0.5, 1.3, fill=1, stroke=0)
            c.circle(rx - 1.0, ref - 2.0, 1.3, fill=1, stroke=0)

    c.setStrokeColor(_COL_BLACK)
    c.setFillColor(_COL_BLACK)


def _draw_measure_checksum(
    c: rl_canvas.Canvas,
    sorted_onsets: list[float],
    onset_map: dict[float, list[FingeringResult]],
    rests: list[tuple[float, float]],
    measure_onset: float,
    beats_per_measure: float,
    x0: float,
    sys_y: float,
) -> None:
    """Draw a small red checksum label above the measure when rhythm is inconsistent.

    The checksum is the total time covered by note attacks (one beat per onset
    column, using the max duration at that onset) plus explicit rests computed
    by ``_compute_rests``.  If this deviates from ``beats_per_measure`` by more
    than 0.1 beat, a red "Σ=X.XX" label is drawn just above the measure.

    This visually flags measures where the source GP file has quantisation
    oddities (beats overflowing the time signature), making QA easy.
    """
    # Compute onset-based coverage: advance a cursor through all note attacks.
    # For each onset column, advance the cursor by the max duration at that onset
    # (chord notes share one beat, so we must not sum all notes).
    # Gaps between note attacks are already covered by ``_compute_rests``, so
    # total_coverage = (furthest cursor position) - measure_onset.
    cur = measure_onset
    for onset in sorted_onsets:
        cur = max(cur, onset)          # skip forward if there's a gap (rest fills it)
        max_dur = max(r.note_event.duration for r in onset_map[onset])
        cur = max(cur, onset + max_dur)

    total_coverage = cur - measure_onset

    delta = total_coverage - beats_per_measure
    if abs(delta) > _TAB_CFG.checksum_tolerance_beats:
        c.setFillColor(colors.red)
        c.setFont("Helvetica", 4.0)
        label = f"\u03a3={total_coverage:.2f}"
        c.drawString(x0 + 2, sys_y + _ABOVE_STRINGS - 2, label)
        c.setFillColor(_COL_BLACK)


# ---------------------------------------------------------------------------
# Rhythm legend
# ---------------------------------------------------------------------------

_LEGEND_NOTE_VALUES: tuple[tuple[str, float], ...] = (
    ("Whole", 4.0),
    ("Half", 2.0),
    ("Quarter", 1.0),
    ("8th", 0.5),
    ("16th", 0.25),
    ("32nd", 0.125),
)


def _draw_rhythm_legend(c: rl_canvas.Canvas, top_y: float) -> float:
    """Draw a compact rhythm legend on a dedicated legend page.

    Shows all standard note values (stems + ovals in tab style) and their
    corresponding rest symbols, with French labels.  Returns the y coordinate
    immediately below the legend.

    Args:
        c: ReportLab canvas (current page).
        top_y: Y coordinate of the top of the available area.

    Returns:
        Y coordinate immediately below the rendered legend block.
    """
    # ── Section title
    title_y = top_y - 8.0
    c.setFont("Helvetica-Bold", 11)
    c.setFillColor(_COL_BLACK)
    c.drawString(_MARGIN, title_y - 11, "Légende des symboles rythmiques")
    c.setLineWidth(0.5)
    c.setStrokeColor(_COL_LGREY)
    c.line(_MARGIN, title_y - 15, _PAGE_W - _MARGIN, title_y - 15)
    c.setStrokeColor(_COL_BLACK)
    y = title_y - 22

    # ── French labels for note values
    _LABEL_FR: dict[str, str] = {
        "Whole": "Ronde",
        "Half": "Blanche",
        "Quarter": "Noire",
        "8th": "Croche",
        "16th": "D. croche",
        "32nd": "T. croche",
    }
    _LABEL_REST_FR: dict[str, str] = {
        "Whole": "Pause",
        "Half": "Demi-pause",
        "Quarter": "Soupir",
        "8th": "½ soupir",
        "16th": "¼ soupir",
        "32nd": "⅛ soupir",
    }

    # ── Layout: two rows (note values / rest symbols), 6 columns each
    col_w = (_PAGE_W - 2 * _MARGIN) / len(_LEGEND_NOTE_VALUES)

    # Column headers
    c.setFont("Helvetica-Bold", 6.0)
    c.setFillColor(_COL_GREY)
    c.drawString(_MARGIN, y, "Valeurs de note :")
    y -= 4

    # Stem + note symbol row (mini tab representation)
    MINI_SYS_Y = y - 4        # "string 1" reference for mini tab
    MINI_STEM_BOT = MINI_SYS_Y + _STEM_GAP
    MINI_STEM_TOP = MINI_SYS_Y + _STEM_H
    MINI_OVAL_H = _OVAL_H
    MINI_OVAL_W = _OVAL_W1
    MINI_FRET_LABEL = "5"     # representative fret number inside oval

    c.setStrokeColor(_COL_BLACK)
    c.setFillColor(_COL_BLACK)

    for col_idx, (name, dur) in enumerate(_LEGEND_NOTE_VALUES):
        cx = _MARGIN + col_w * col_idx + col_w / 2

        # ── Draw a short mock string line
        c.setLineWidth(0.3)
        c.setStrokeColor(_COL_LGREY)
        c.line(cx - MINI_OVAL_W / 2 - 3, MINI_SYS_Y, cx + MINI_OVAL_W / 2 + 3, MINI_SYS_Y)
        c.setStrokeColor(_COL_BLACK)

        # ── Stem (not for whole notes)
        if dur < 4.0:
            c.setLineWidth(0.8)
            c.line(cx, MINI_STEM_BOT, cx, MINI_STEM_TOP)
            # Flags (unbeamed eighths and shorter)
            if dur < 1.0:
                for fi in range(_num_flags(dur)):
                    _draw_flag(c, cx, MINI_STEM_TOP - fi * 4.0)

        # ── Oval (visible stroke for half/whole)
        is_open = dur >= 2.0
        c.setFillColor(colors.white)
        if is_open:
            c.setStrokeColor(_COL_BLACK)
            c.setLineWidth(0.6)
            c.ellipse(
                cx - MINI_OVAL_W / 2, MINI_SYS_Y - MINI_OVAL_H / 2,
                cx + MINI_OVAL_W / 2, MINI_SYS_Y + MINI_OVAL_H / 2,
                fill=1, stroke=1,
            )
        else:
            c.setStrokeColor(colors.white)
            c.ellipse(
                cx - MINI_OVAL_W / 2, MINI_SYS_Y - MINI_OVAL_H / 2,
                cx + MINI_OVAL_W / 2, MINI_SYS_Y + MINI_OVAL_H / 2,
                fill=1, stroke=0,
            )

        # ── Fret number
        c.setFillColor(_COL_BLACK)
        c.setFont(_FRET_FONT, _FRET_FS)
        c.drawCentredString(cx, MINI_SYS_Y - _FRET_FS * 0.36, MINI_FRET_LABEL)

        # ── French label below
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawCentredString(cx, MINI_SYS_Y - MINI_OVAL_H / 2 - 7, _LABEL_FR[name])

        c.setFillColor(_COL_BLACK)

    # ── Dotted notes row (half·, quarter·, eighth·)
    _DOTTED_LEGEND: tuple[tuple[str, float], ...] = (
        ("Blanche pointee", 3.0),
        ("Noire pointee", 1.5),
        ("Croche pointee", 0.75),
    )
    DOTTED_SYS_Y = MINI_SYS_Y - MINI_OVAL_H / 2 - 28

    c.setFont("Helvetica-Bold", 6.0)
    c.setFillColor(_COL_GREY)
    c.drawString(_MARGIN, DOTTED_SYS_Y + _STEM_H + 4, "Notes pointees (duree x 1.5) :")
    c.setFillColor(_COL_BLACK)

    dotted_col_w = (_PAGE_W - 2 * _MARGIN) / len(_DOTTED_LEGEND)
    for col_idx, (label, dur) in enumerate(_DOTTED_LEGEND):
        cx = _MARGIN + dotted_col_w * col_idx + dotted_col_w / 2
        base = _dotted_base(dur)

        # string line
        c.setLineWidth(0.3)
        c.setStrokeColor(_COL_LGREY)
        c.line(cx - MINI_OVAL_W / 2 - 3, DOTTED_SYS_Y, cx + MINI_OVAL_W / 2 + 7, DOTTED_SYS_Y)
        c.setStrokeColor(_COL_BLACK)

        # stem
        if base < 4.0:
            c.setLineWidth(0.8)
            c.line(cx, DOTTED_SYS_Y + _STEM_GAP, cx, DOTTED_SYS_Y + _STEM_H)
            if base < 1.0:
                for fi in range(_num_flags(dur)):
                    _draw_flag(c, cx, DOTTED_SYS_Y + _STEM_H - fi * 4.0)

        # oval
        is_open = base >= 2.0
        c.setFillColor(colors.white)
        if is_open:
            c.setStrokeColor(_COL_BLACK)
            c.setLineWidth(0.6)
            c.ellipse(cx - MINI_OVAL_W / 2, DOTTED_SYS_Y - MINI_OVAL_H / 2,
                      cx + MINI_OVAL_W / 2, DOTTED_SYS_Y + MINI_OVAL_H / 2, fill=1, stroke=1)
        else:
            c.setStrokeColor(colors.white)
            c.ellipse(cx - MINI_OVAL_W / 2, DOTTED_SYS_Y - MINI_OVAL_H / 2,
                      cx + MINI_OVAL_W / 2, DOTTED_SYS_Y + MINI_OVAL_H / 2, fill=1, stroke=0)

        # fret number
        c.setFillColor(_COL_BLACK)
        c.setFont(_FRET_FONT, _FRET_FS)
        c.drawCentredString(cx, DOTTED_SYS_Y - _FRET_FS * 0.36, MINI_FRET_LABEL)

        # augmentation dot
        c.circle(cx + MINI_OVAL_W / 2 + 2.5, DOTTED_SYS_Y, 1.3, fill=1, stroke=0)

        # label
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawCentredString(cx, DOTTED_SYS_Y - MINI_OVAL_H / 2 - 7, label.replace("pointee", "pt."))
        c.setFillColor(_COL_BLACK)

    # ── Rest symbols row
    # REST_ROW_Y is the visual centre of each rest symbol in the legend.
    # We pass (REST_ROW_Y + _REST_CENTER_Y) as sys_y so that
    # _draw_rest places the symbol at sys_y - _REST_CENTER_Y = REST_ROW_Y.
    REST_ROW_Y = DOTTED_SYS_Y - MINI_OVAL_H / 2 - 28
    _REST_LEGEND_SYS_Y = REST_ROW_Y + _REST_CENTER_Y

    c.setFont("Helvetica-Bold", 6.0)
    c.setFillColor(_COL_GREY)
    c.drawString(_MARGIN, REST_ROW_Y + _REST_DISC_R + 6, "Silences correspondants :")
    c.setFillColor(_COL_BLACK)

    for col_idx, (name, dur) in enumerate(_LEGEND_NOTE_VALUES):
        cx = _MARGIN + col_w * col_idx + col_w / 2
        _draw_rest(c, cx, _REST_LEGEND_SYS_Y, dur)

        # ── French label below the disc / symbol
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawCentredString(cx, REST_ROW_Y - _REST_DISC_R - 5, _LABEL_REST_FR[name])
        c.setFillColor(_COL_BLACK)

    # ── Additional notation symbols row
    NOTATIONS_Y = REST_ROW_Y - _REST_DISC_R - 20

    c.setFont("Helvetica-Bold", 6.0)
    c.setFillColor(_COL_GREY)
    c.drawString(_MARGIN, NOTATIONS_Y + 4, "Symboles de notation :")
    c.setFillColor(_COL_BLACK)

    notation_items = [
        ("H", _HP_COLOR, "Hammer-on"),
        ("P", _HP_COLOR, "Pull-off"),
        ("T", colors.Color(0.05, 0.05, 0.80), "Tapping"),
        (">", _COL_BLACK, "Accent"),
        (">>", _COL_BLACK, "Accent fort"),
        ("!", colors.red, "Accord impossible"),
    ]

    icon_col_w = (_PAGE_W - 2 * _MARGIN) / len(notation_items)
    for i, (symbol, col, label) in enumerate(notation_items):
        ix = _MARGIN + icon_col_w * i + icon_col_w / 2
        iy = NOTATIONS_Y - 6
        c.setFillColor(col)
        c.setFont("Helvetica-Bold", 8.0)
        c.drawCentredString(ix, iy, symbol)
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawCentredString(ix, iy - 8, label)
        c.setFillColor(_COL_BLACK)

    # ── Checksum note
    bottom_y = NOTATIONS_Y - 24
    c.setFont("Helvetica-Oblique", 6.0)
    c.setFillColor(_COL_GREY)
    c.drawString(_MARGIN, bottom_y,
                 "\u03a3=X.XX en rouge au-dessus d'une mesure = anomalie rythmique du fichier source (quantification GP)")
    c.setFillColor(_COL_BLACK)

    return bottom_y - 8


# ---------------------------------------------------------------------------
# Note rendering
# ---------------------------------------------------------------------------


_BEND_COLOR = colors.Color(0.80, 0.05, 0.05)       # dark red (same as LH finger)
_TAPPING_COLOR = colors.Color(0.05, 0.05, 0.80)    # dark blue
_VIBRATO_COLOR = colors.Color(0.15, 0.45, 0.15)    # dark green
_PM_COLOR = colors.Color(0.30, 0.30, 0.30)         # dark grey
_HP_COLOR = colors.Color(0.30, 0.30, 0.30)         # dark grey for H/P labels
_HARMONIC_STROKE = colors.Color(0.0, 0.0, 0.0)     # black


def _draw_note(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    r: FingeringResult,
) -> None:
    """Draw one note at string position (x, y).

    Rendering order:
    1.  Oval (or diamond for harmonic, 'x' for muted).
        • Half/whole note  → oval with visible black stroke (open notehead).
        • Quarter or less  → plain white oval, no stroke (background clearance only).
    2.  Fret number  — Helvetica-Bold 6 pt, centred in oval, black.
    3.  LH finger    — Helvetica-Bold 5 pt, SOUTH-WEST of oval, dark red.
                       Omitted for open strings (fret == 0) and muted notes.
    4.  Notation overlays: bend, tapping T, accent >, vibrato.
    """
    fret = r.state.fret
    finger = r.state.finger
    ne = r.note_event

    oval_w = _OVAL_W2 if fret >= 10 else _OVAL_W1

    # ── Muted note: draw 'x' instead of oval + number
    if getattr(ne, "muted", False):
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.white)
        c.ellipse(
            x - oval_w / 2, y - _OVAL_H / 2,
            x + oval_w / 2, y + _OVAL_H / 2,
            fill=1, stroke=0,
        )
        c.setFillColor(_COL_BLACK)
        c.setFont("Helvetica-Bold", 7.0)
        c.drawCentredString(x, y - 7.0 * 0.36, "x")
        return

    # ── Natural harmonic: diamond shape instead of oval
    if getattr(ne, "harmonic_type", None) is not None:
        _draw_harmonic_note(c, x, y, fret, finger, ne)
        return

    # 1. Oval around fret number.
    # Convention: visible oval stroke = half note or whole note (open notehead).
    #             invisible (white-on-white) oval = quarter note or shorter (background only).
    dur = ne.duration
    # Open notehead (visible oval stroke) for half note and longer.
    # Use the undotted base so a dotted quarter (1.5) stays filled,
    # and a dotted half (3.0) gets an open oval.
    is_open_notehead = _dotted_base(dur) >= 2.0
    c.setFillColor(colors.white)
    if is_open_notehead:
        c.setStrokeColor(_COL_BLACK)
        c.setLineWidth(0.6)
        c.ellipse(
            x - oval_w / 2, y - _OVAL_H / 2,
            x + oval_w / 2, y + _OVAL_H / 2,
            fill=1, stroke=1,
        )
    else:
        c.setStrokeColor(colors.white)
        c.ellipse(
            x - oval_w / 2, y - _OVAL_H / 2,
            x + oval_w / 2, y + _OVAL_H / 2,
            fill=1, stroke=0,
        )

    # 2. Fret number — centred vertically in oval
    c.setFillColor(_COL_BLACK)
    c.setFont(_FRET_FONT, _FRET_FS)
    c.drawCentredString(x, y - _FRET_FS * 0.36, str(fret))

    # 2a. Augmentation dot — small filled circle to the right of the oval
    if _is_dotted(dur):
        dot_x = x + oval_w / 2 + 2.5
        c.setFillColor(_COL_BLACK)
        c.circle(dot_x, y, 1.3, fill=1, stroke=0)

    # 3. LH finger annotation — south-west of oval, fretted notes only.
    #    Collision check (RENDER-08): if the annotation bottom would overlap
    #    the oval of the next string below, shift the annotation 3.5 pt to the left.
    if fret > 0 and finger in _FINGER_CHAR:
        c.setFillColor(_LH_FINGER_COLOR)
        c.setFont(_LH_FINGER_FONT, _LH_FINGER_FS)
        annot_x = x - oval_w / 2
        annot_bottom = y + _LH_FINGER_Y - 2.0          # bottom of descender
        next_string_oval_top = (y - _STRING_SPACING) + _OVAL_H / 2  # top of oval on next string
        if annot_bottom < next_string_oval_top + 2.0:
            annot_x -= 3.5                              # shift left to avoid overlap
        c.drawRightString(annot_x, y + _LH_FINGER_Y, _FINGER_CHAR[finger])
        c.setFillColor(_COL_BLACK)

    # 4. Notation overlays
    # ── Bend arrow
    bend_value = getattr(ne, "bend_value", None)
    bend_type = getattr(ne, "bend_type", None)
    if bend_value is not None:
        _draw_bend(c, x, y, oval_w, bend_value, bend_type)

    # ── Tapping marker
    if getattr(ne, "tapping", False):
        c.setFillColor(_TAPPING_COLOR)
        c.setFont("Helvetica-Bold", 6.0)
        c.drawCentredString(x, y + _OVAL_H / 2 + 2.5, "T")
        c.setFillColor(_COL_BLACK)

    # ── Accent marks
    accent = getattr(ne, "accent", False)
    accent_strong = getattr(ne, "accent_strong", False)
    if accent_strong:
        c.setFillColor(_COL_BLACK)
        c.setFont("Helvetica", 6.0)
        c.drawCentredString(x, y + _OVAL_H / 2 + 2.5, ">>")
        c.setFillColor(_COL_BLACK)
    elif accent:
        c.setFillColor(_COL_BLACK)
        c.setFont("Helvetica", 6.0)
        c.drawCentredString(x, y + _OVAL_H / 2 + 2.5, ">")
        c.setFillColor(_COL_BLACK)

    # ── Vibrato wavy line
    articulation = getattr(ne, "articulation", None)
    vibrato_wide = getattr(ne, "vibrato_wide", False)
    if articulation in (Articulation.VIBRATO, Articulation.WIDE_VIBRATO) or vibrato_wide:
        _draw_vibrato(c, x, y, oval_w, wide=vibrato_wide or articulation == Articulation.WIDE_VIBRATO)


def _draw_harmonic_note(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    fret: int,
    finger: Finger,
    ne: object,
) -> None:
    """Draw a harmonic note: diamond shape + fret number inside."""
    # Diamond: 4-point polygon centred at (x, y)
    d_half_w = 5.5
    d_half_h = 3.5
    # White fill to erase string line
    c.setFillColor(colors.white)
    p = c.beginPath()
    p.moveTo(x, y + d_half_h)
    p.lineTo(x + d_half_w, y)
    p.lineTo(x, y - d_half_h)
    p.lineTo(x - d_half_w, y)
    p.close()
    c.drawPath(p, fill=1, stroke=0)

    # Black outline
    c.setStrokeColor(_HARMONIC_STROKE)
    c.setLineWidth(0.5)
    p2 = c.beginPath()
    p2.moveTo(x, y + d_half_h)
    p2.lineTo(x + d_half_w, y)
    p2.lineTo(x, y - d_half_h)
    p2.lineTo(x - d_half_w, y)
    p2.close()
    c.drawPath(p2, fill=0, stroke=1)
    c.setLineWidth(0.4)

    # Fret number inside diamond
    c.setFillColor(_COL_BLACK)
    c.setFont(_FRET_FONT, _FRET_FS)
    c.drawCentredString(x, y - _FRET_FS * 0.36, str(fret))

    # LH finger below — with collision check (same rule as _draw_note)
    oval_w = _OVAL_W2 if fret >= 10 else _OVAL_W1
    if fret > 0 and finger in _FINGER_CHAR:
        c.setFillColor(_LH_FINGER_COLOR)
        c.setFont(_LH_FINGER_FONT, _LH_FINGER_FS)
        annot_x = x - oval_w / 2
        annot_bottom = y + _LH_FINGER_Y - 2.0
        next_oval_top = (y - _STRING_SPACING) + _OVAL_H / 2
        if annot_bottom < next_oval_top + 2.0:
            annot_x -= 3.5
        c.drawRightString(annot_x, y + _LH_FINGER_Y, _FINGER_CHAR[finger])
        c.setFillColor(_COL_BLACK)


def _draw_bend(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    oval_w: float,
    bend_value: float,
    bend_type: str | None,
) -> None:
    """Draw a bend arrow above a note oval."""
    # Bend label
    if bend_value >= 1.75:
        label = "2"
    elif bend_value >= 1.25:
        label = "1\u00bd"
    elif bend_value >= 0.75:
        label = "1"
    else:
        label = "\u00bd"

    arrow_base_y = y + _OVAL_H / 2 + 1.0
    arrow_tip_y = arrow_base_y + 9.0
    arrow_x_offset = 4.0

    # For pre-bend: show label in parentheses, no upward arrow needed
    if bend_type in ("pre_bend", "pre_bend_release"):
        label = f"({label})"
        c.setFillColor(_BEND_COLOR)
        c.setFont("Helvetica-Bold", 4.8)
        c.drawCentredString(x, arrow_tip_y, label)
        c.setFillColor(_COL_BLACK)
        return

    # Draw curved arrow line
    c.setStrokeColor(_BEND_COLOR)
    c.setLineWidth(0.7)
    p = c.beginPath()
    p.moveTo(x, arrow_base_y)
    p.curveTo(x, arrow_base_y + 4.0, x + arrow_x_offset, arrow_tip_y - 3.0,
              x + arrow_x_offset, arrow_tip_y)
    c.drawPath(p, stroke=1, fill=0)

    # Arrow tip (small filled triangle)
    c.setFillColor(_BEND_COLOR)
    tip_x = x + arrow_x_offset
    tip_y = arrow_tip_y
    c.beginPath()
    p2 = c.beginPath()
    p2.moveTo(tip_x, tip_y)
    p2.lineTo(tip_x - 2.0, tip_y - 3.5)
    p2.lineTo(tip_x + 2.0, tip_y - 3.5)
    p2.close()
    c.drawPath(p2, fill=1, stroke=0)

    # Label above arrow tip
    c.setFont("Helvetica-Bold", 4.8)
    c.drawCentredString(tip_x, tip_y + 1.5, label)
    c.setFillColor(_COL_BLACK)
    c.setStrokeColor(_COL_BLACK)


def _draw_vibrato(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    oval_w: float,
    wide: bool = False,
) -> None:
    """Draw a vibrato wavy line to the right of the note oval."""
    amplitude = 2.5 if wide else 1.5
    wave_w = 3.5   # width of each half-cycle
    num_cycles = 4
    start_x = x + oval_w / 2 + 2.0
    wave_y = y + 1.0  # 1 pt above string line

    c.setStrokeColor(_VIBRATO_COLOR)
    c.setLineWidth(0.6)
    p = c.beginPath()
    p.moveTo(start_x, wave_y)
    cx = start_x
    up = True
    for _ in range(num_cycles * 2):
        ctrl_x = cx + wave_w / 2
        end_x = cx + wave_w
        ctrl_y = wave_y + (amplitude if up else -amplitude)
        p.curveTo(ctrl_x - wave_w / 4, ctrl_y, ctrl_x + wave_w / 4, ctrl_y, end_x, wave_y)
        cx = end_x
        up = not up
    c.drawPath(p, stroke=1, fill=0)
    c.setStrokeColor(_COL_BLACK)
    c.setLineWidth(0.4)


def _draw_slide_lines(
    c: rl_canvas.Canvas,
    onset_map: dict[float, list[FingeringResult]],
    onset_x: dict[float, float],
    sys_y: float,
) -> None:
    """Draw diagonal slide lines between consecutive notes with slide articulation."""
    sorted_onsets = sorted(onset_map.keys())

    # Build per-string list of (onset, x, r) for easy lookup
    string_notes: dict[int, list[tuple[float, float, FingeringResult]]] = {}
    for onset in sorted_onsets:
        nx = onset_x[onset]
        for r in onset_map[onset]:
            s = r.state.string_num
            string_notes.setdefault(s, []).append((onset, nx, r))

    c.setStrokeColor(_COL_BLACK)
    c.setLineWidth(0.7)

    for s, notes in string_notes.items():
        sy = sys_y - (s - 1) * _STRING_SPACING
        for i, (onset, nx, r) in enumerate(notes):
            ne = r.note_event
            slide_type = getattr(ne, "slide_type", None)
            articulation = getattr(ne, "articulation", None)

            if slide_type is None and articulation != Articulation.SLIDE:
                continue

            oval_w = _OVAL_W2 if r.state.fret >= 10 else _OVAL_W1
            src_x = nx + oval_w / 2 + 1.0

            # slide_in types: draw short line from above/below INTO the note
            if slide_type in (SlideType.SLIDE_IN_ABOVE, SlideType.SLIDE_IN_BELOW):
                direction = 1 if slide_type == SlideType.SLIDE_IN_ABOVE else -1
                c.setDash([2.0, 1.5])
                p = c.beginPath()
                p.moveTo(nx - oval_w / 2 - 8.0, sy + direction * 5.0)
                p.lineTo(nx - oval_w / 2 - 1.0, sy)
                c.drawPath(p, stroke=1, fill=0)
                c.setDash([])
                continue

            # slide_out types: draw short line from note going up/down
            if slide_type in (SlideType.SLIDE_OUT_UP, SlideType.SLIDE_OUT_DOWN):
                direction = 1 if slide_type == SlideType.SLIDE_OUT_UP else -1
                c.setDash([2.0, 1.5])
                p = c.beginPath()
                p.moveTo(src_x, sy)
                p.lineTo(src_x + 8.0, sy + direction * 5.0)
                c.drawPath(p, stroke=1, fill=0)
                c.setDash([])
                continue

            # Legato/shift slides: draw diagonal line to next note on same string
            if i + 1 < len(notes):
                next_onset, next_nx, next_r = notes[i + 1]
                next_oval_w = _OVAL_W2 if next_r.state.fret >= 10 else _OVAL_W1
                dst_x = next_nx - next_oval_w / 2 - 1.0

                # Direction: upward (/) or downward (\) based on fret change
                src_fret = r.state.fret
                dst_fret = next_r.state.fret
                if src_fret < dst_fret:
                    # ascending: line goes up
                    src_y = sy - 1.5
                    dst_y = sy + 1.5
                elif src_fret > dst_fret:
                    # descending: line goes down
                    src_y = sy + 1.5
                    dst_y = sy - 1.5
                else:
                    src_y = sy
                    dst_y = sy

                if dst_x > src_x + 2.0:
                    p = c.beginPath()
                    p.moveTo(src_x, src_y)
                    p.lineTo(dst_x, dst_y)
                    c.drawPath(p, stroke=1, fill=0)

    c.setStrokeColor(_COL_BLACK)
    c.setLineWidth(0.4)
    c.setDash([])


def _draw_slur_arcs(
    c: rl_canvas.Canvas,
    onset_map: dict[float, list[FingeringResult]],
    onset_x: dict[float, float],
    sys_y: float,
) -> None:
    """Draw H/P arcs between consecutive hammer-on / pull-off notes."""
    sorted_onsets = sorted(onset_map.keys())

    # Build per-string list of (onset, x, r)
    string_notes: dict[int, list[tuple[float, float, FingeringResult]]] = {}
    for onset in sorted_onsets:
        nx = onset_x[onset]
        for r in onset_map[onset]:
            s = r.state.string_num
            string_notes.setdefault(s, []).append((onset, nx, r))

    c.setStrokeColor(_HP_COLOR)
    c.setLineWidth(0.7)

    for s, notes in string_notes.items():
        sy = sys_y - (s - 1) * _STRING_SPACING
        for i, (onset, nx, r) in enumerate(notes):
            articulation = getattr(r.note_event, "articulation", None)
            if articulation not in (Articulation.HAMMER_ON, Articulation.PULL_OFF):
                continue
            label = "H" if articulation == Articulation.HAMMER_ON else "P"

            if i + 1 < len(notes):
                next_onset, next_nx, next_r = notes[i + 1]
                oval_w = _OVAL_W2 if r.state.fret >= 10 else _OVAL_W1
                next_oval_w = _OVAL_W2 if next_r.state.fret >= 10 else _OVAL_W1

                arc_x0 = nx + oval_w / 2
                arc_x1 = next_nx - next_oval_w / 2
                arc_mid_x = (arc_x0 + arc_x1) / 2
                arc_top_y = sy + 6.0  # arc bows above the string

                if arc_x1 > arc_x0 + 3.0:
                    p = c.beginPath()
                    p.moveTo(arc_x0, sy)
                    p.curveTo(arc_x0 + (arc_x1 - arc_x0) * 0.25, arc_top_y,
                              arc_x1 - (arc_x1 - arc_x0) * 0.25, arc_top_y,
                              arc_x1, sy)
                    c.drawPath(p, stroke=1, fill=0)

                    # Label at arc midpoint
                    c.setFillColor(_HP_COLOR)
                    c.setFont("Helvetica", 4.0)
                    c.drawCentredString(arc_mid_x, arc_top_y - 0.5, label)
                    c.setFillColor(_COL_BLACK)

    c.setStrokeColor(_COL_BLACK)
    c.setLineWidth(0.4)


def _draw_pm_brackets(
    c: rl_canvas.Canvas,
    onset_map: dict[float, list[FingeringResult]],
    onset_x: dict[float, float],
    x0: float,
    x1: float,
    sys_y: float,
) -> None:
    """Draw P.M.-- brackets below string 6 for palm-muted notes."""
    # Find runs of palm-muted notes on string 6 (lowest)
    string6_y = sys_y - (_NUM_STRINGS - 1) * _STRING_SPACING
    pm_y = string6_y - 5.0  # 5 pt below string 6

    # Gather all pm note x positions
    pm_xs: list[float] = []
    sorted_onsets = sorted(onset_map.keys())
    for onset in sorted_onsets:
        for r in onset_map[onset]:
            if getattr(r.note_event, "palm_muted", False):
                pm_xs.append(onset_x[onset])

    if not pm_xs:
        return

    pm_start = min(pm_xs)
    pm_end = max(pm_xs)

    c.setStrokeColor(_PM_COLOR)
    c.setFillColor(_PM_COLOR)
    c.setLineWidth(0.6)
    c.setFont("Helvetica", 5.0)
    label = "P.M."
    label_w = c.stringWidth(label, "Helvetica", 5.0)
    c.drawString(pm_start - 1.0, pm_y - 1.5, label)

    # Dashed line after "P.M."
    dash_x0 = pm_start + label_w + 1.0
    dash_x1 = pm_end + 4.0
    if dash_x1 > dash_x0:
        c.setDash([2.5, 1.5])
        c.line(dash_x0, pm_y, dash_x1, pm_y)
        c.setDash([])

    c.setStrokeColor(_COL_BLACK)
    c.setFillColor(_COL_BLACK)
    c.setLineWidth(0.4)


# ---------------------------------------------------------------------------
# Measure grouping and density utilities
# ---------------------------------------------------------------------------


def _group_by_measure(
    results: list[FingeringResult],
    beats_per_measure: float,
) -> list[list[FingeringResult]]:
    """Group results into per-measure lists (offset by first measure in song)."""
    if not results:
        return []
    first_m = int(results[0].note_event.onset / beats_per_measure)
    last_m = int(results[-1].note_event.onset / beats_per_measure)
    count = last_m - first_m + 1
    buckets: list[list[FingeringResult]] = [[] for _ in range(count)]
    for r in results:
        idx = int(r.note_event.onset / beats_per_measure) - first_m
        buckets[idx].append(r)
    return buckets


def _calc_mps(measures: list[list[FingeringResult]]) -> int:
    """Choose measures-per-system for clean column layout.

    Uses the 75th-percentile unique-onset count (not the absolute max) so
    that a single unusually dense measure does not force all systems to be
    too sparse.  The _MIN_COL_STEP forward-pass guarantee in _compute_onset_x
    handles the rare denser measures gracefully.

    Formula: req_w = p75_onsets × MIN_COL_STEP + 2 × LEFT_PAD
             mps   = floor(strings_w / req_w), clamped to [MPS_MIN, MPS_MAX]
    """
    non_empty = [m for m in measures if m]
    if not non_empty:
        return 3

    counts = sorted(
        len({round(r.note_event.onset, 4) for r in m})
        for m in non_empty
    )
    p75_idx = int(len(counts) * 0.75)
    p75_cols = counts[min(p75_idx, len(counts) - 1)]

    req_w = max(p75_cols * _MIN_COL_STEP + 2 * _LEFT_PAD, 60.0)
    strings_w = _PAGE_W - _MARGIN - _STRINGS_X0    # ≈ 504 pt
    raw = int(strings_w / req_w)
    return max(_MPS_MIN, min(_MPS_MAX, raw))


def _measure_w_raw(results: list[FingeringResult], beats_per_measure: float) -> float:
    """Compute raw measure width from rhythmic density.

    Sums 1/duration for every rhythmic event (notes + rest gaps) and converts
    to points using _UNIT_W.  Larger = denser = wider measure.
    """
    if not results:
        return _MIN_MEASURE_W

    measure_onset = (
        math.floor(results[0].note_event.onset / beats_per_measure) * beats_per_measure
    )

    # Minimum duration per unique onset column (= notated rhythm value)
    onset_min_dur: dict[float, float] = {}
    for r in results:
        key = round(r.note_event.onset, 6)
        onset_min_dur[key] = min(onset_min_dur.get(key, 999.0), r.note_event.duration)

    sorted_onsets = sorted(onset_min_dur.keys())
    units = 0.0
    prev_end = measure_onset

    for onset in sorted_onsets:
        dur = onset_min_dur[onset]
        gap = onset - prev_end
        if gap >= _TAB_CFG.rest_gap_threshold_beats:  # rest gap >= 1/32 beat
            units += 1.0 / max(gap, 0.125)
        units += 1.0 / max(dur, 0.125)
        prev_end = onset + dur

    # Rest at end of measure
    end_gap = (measure_onset + beats_per_measure) - prev_end
    if end_gap >= _TAB_CFG.rest_gap_threshold_beats:
        units += 1.0 / max(end_gap, 0.125)

    if units == 0.0:
        units = 1.0 / beats_per_measure

    return _LEFT_PAD + units * _UNIT_W + 5.0


def _normalize_measure_widths(raw_widths: list[float], available_w: float) -> list[float]:
    """Scale measure widths proportionally to fill available_w.

    Iteratively scales all unclamped widths, clamping outliers to [MIN, MAX].
    Excess/deficit from clamped measures is redistributed to remaining ones.
    """
    widths = list(raw_widths)
    clamped = [False] * len(widths)

    for _ in range(len(widths)):
        free = [i for i in range(len(widths)) if not clamped[i]]
        if not free:
            break
        total_free = sum(widths[i] for i in free)
        total_fixed = sum(widths[i] for i in range(len(widths)) if clamped[i])
        target = available_w - total_fixed
        if total_free <= 0.0:
            break
        scale = target / total_free
        changed = False
        for i in free:
            scaled = widths[i] * scale
            clamped_val = max(_MIN_MEASURE_W, min(_MAX_MEASURE_W, scaled))
            if abs(clamped_val - scaled) > 0.5:
                widths[i] = clamped_val
                clamped[i] = True
                changed = True
            else:
                widths[i] = scaled
        if not changed:
            break

    return widths


def _build_systems(
    measures: list[list[FingeringResult]],
    beats_per_measure: float,
    available_w: float,
    forced_mps: int | None = None,
) -> list[tuple[list[list[FingeringResult]], list[float]]]:
    """Group measures into systems with proportional measure widths.

    Returns a list of (sys_measures, normalized_widths) pairs, one per system.

    When forced_mps is given, each system has exactly that many measures
    (last system may have fewer).  Otherwise a greedy algorithm packs measures
    until the system would exceed available_w.
    """
    if not measures:
        return []

    raw_widths = [_measure_w_raw(m, beats_per_measure) for m in measures]
    systems: list[tuple[list[list[FingeringResult]], list[float]]] = []
    i = 0

    while i < len(measures):
        if forced_mps is not None:
            chunk = measures[i : i + forced_mps]
            raw_chunk = raw_widths[i : i + forced_mps]
            i += len(chunk)
        else:
            chunk = []
            raw_chunk = []
            total = 0.0
            while i < len(measures):
                w = raw_widths[i]
                if chunk and total + w > available_w * 1.05:
                    break
                chunk.append(measures[i])
                raw_chunk.append(w)
                total += w
                i += 1

        norm = _normalize_measure_widths(raw_chunk, available_w)
        systems.append((chunk, norm))

    return systems


def _system_tempo(
    sys_measures: list[list[FingeringResult]],
    fallback: float,
) -> float:
    """Return the tempo of the first note in the system."""
    for m in sys_measures:
        if m:
            return m[0].note_event.tempo
    return fallback
