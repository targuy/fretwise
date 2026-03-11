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

String spacing is 10 pt: compact yet leaves 2.3 pt below each finger
annotation before the next string line. Both fret number and finger
label are horizontally centred on the note column x.

Note rendering
──────────────
  • White oval  – erases the string line behind the fret number
  • Fret number – Helvetica-Bold 6 pt, centred in oval (black)
  • Finger char – Helvetica 4.5 pt, centred BELOW oval (dark red)
                  omitted for open strings (fret == 0)
  • Minimum column step 17 pt enforced by forward-pass constraint
"""

from __future__ import annotations

import math
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas as rl_canvas

from fretwise.models import Finger, FingeringResult
from fretwise.patterns.chord_recognition import recognize_chord

# ---------------------------------------------------------------------------
# Layout constants  (all in pt — 1 pt = 1/72 inch)
# ---------------------------------------------------------------------------

_PAGE_W = 595.0
_PAGE_H = 842.0
_MARGIN = 28.5

# Left label column that carries "TAB" + string names
_TAB_LABEL_W = 34.0
_STRINGS_X0 = _MARGIN + _TAB_LABEL_W     # 62.5 pt from left edge

_NUM_STRINGS = 6
_STRING_NAMES = ("e", "B", "G", "D", "A", "E")   # index 0 = string 1 = high e
_STRING_SPACING = 10.0                            # pts between adjacent strings
_STRINGS_HEIGHT = (_NUM_STRINGS - 1) * _STRING_SPACING   # 50 pt

# Rhythm notation (above sys_y = y of string 1)
_STEM_GAP = 2.5      # gap between string-1 and stem base
_STEM_H = 11.0       # total stem height above string-1

# Text belt heights above sys_y
_CHORD_Y = 24.0      # chord-name baseline above sys_y
_TEMPO_Y = 33.0      # tempo/timesig baseline above sys_y

# System vertical extents
_TOP_PAD = 4.0
_ABOVE_STRINGS = _TEMPO_Y + 7.0 + _TOP_PAD    # ~44 pt
_BELOW_STRINGS = 6.0
_SYSTEM_H = _ABOVE_STRINGS + _STRINGS_HEIGHT + _BELOW_STRINGS   # ~100 pt
_INTER_SYSTEM_GAP = 10.0
_SYSTEM_PITCH = _SYSTEM_H + _INTER_SYSTEM_GAP   # ~110 pt  →  7 systems/page

# Note rendering
# With 10 pt string spacing:
#   oval ±3.5 pt, finger cap-top at string_y-3.65 (0.15 pt below oval bottom),
#   finger text bottom at string_y-7.7, gap to next string = 2.3 pt  ✓
_OVAL_H = 7.0        # oval covers string line (±3.5 pt from center)
_OVAL_W1 = 10.0      # 1-digit fret
_OVAL_W2 = 13.5      # 2-digit fret (10+)

_FRET_FONT = "Helvetica-Bold"
_FRET_FS = 6.0
# fret baseline = string_y - fret_fs*0.36  (centres the glyph vertically in oval)

_FINGER_FONT = "Helvetica"
_FINGER_FS = 4.5
_FINGER_Y = -6.8     # finger baseline = string_y + this
# cap-top ≈ string_y-3.65 (0.15 pt below oval-bottom string_y-3.5)
# text-bottom ≈ string_y-7.7  →  gap to next string line = 2.3 pt

_FINGER_COLOR = colors.Color(0.80, 0.05, 0.05)   # dark red

# Column layout
_MIN_COL_STEP = 17.0   # minimum x step between consecutive onset columns
_LEFT_PAD = 9.0        # padding inside measure left edge

# Default / caps
_MPS_MIN, _MPS_MAX = 2, 6

# String-name / TAB-label geometry
_SNAME_X = _MARGIN + 26.0      # x for string-name right edge (just before STRINGS_X0)
_TAB_X = _MARGIN + 8.0         # x for "T/A/B" centre

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
        section_markers: Optional mapping of 1-based measure number → section
            title (e.g. {1: "Intro", 9: "Verse 1"}).
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
    mps = measures_per_system if measures_per_system is not None else _calc_mps(measures)
    mps = max(_MPS_MIN, min(_MPS_MAX, mps))
    first_song_measure = int(results[0].note_event.onset / beats_per_measure) + 1

    current_top = _PAGE_H - _MARGIN

    # ── Title block on page 1
    if title or artist or mode_label or instrument:
        current_top = _draw_title_block(c, title, artist, instrument, mode_label, current_top)

    # ── Render systems
    m_idx = 0
    first_system_on_page = True
    prev_tempo: float = -1.0

    while m_idx < len(measures):
        sys_measures = measures[m_idx : m_idx + mps]
        song_m_start = first_song_measure + m_idx
        m_idx += len(sys_measures)

        # Representative tempo for this system (first note's tempo)
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

        is_last = m_idx >= len(measures)
        _draw_system(
            c, sys_measures, sys_y, song_m_start,
            beats_per_measure, mps, sys_tempo, show_tempo,
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


# ---------------------------------------------------------------------------
# System-level rendering
# ---------------------------------------------------------------------------


def _draw_system(
    c: rl_canvas.Canvas,
    sys_measures: list[list[FingeringResult]],
    sys_y: float,
    song_m_start: int,
    beats_per_measure: float,
    mps: int,
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
    n = len(sys_measures)
    strings_x1 = _PAGE_W - _MARGIN
    measure_w = (strings_x1 - _STRINGS_X0) / mps
    x_right = _STRINGS_X0 + n * measure_w

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
    for slot, measure_results in enumerate(sys_measures):
        x0 = _STRINGS_X0 + slot * measure_w
        x1 = x0 + measure_w

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

        # Measure number (small grey above stem area)
        c.setFont("Helvetica", 5.5)
        c.setFillColor(_COL_GREY)
        c.drawString(x0 + 3, sys_y + _STEM_H + 1, str(song_m_start + slot))
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
    for beat in sorted(beat_groups):
        pitches = [r.note_event.pitch for o in beat_groups[beat] for r in onset_map[o]]
        chord = recognize_chord(pitches)
        if chord and chord != prev_chord:
            cx = onset_x[beat_groups[beat][0]]
            c.setFont("Helvetica-Bold", 7.0)
            c.setFillColor(_COL_BLACK)
            c.drawString(cx - 2, sys_y + _CHORD_Y, chord)
            prev_chord = chord

    # ── Build stem info list
    stem_info: list[tuple[float, float, float]] = []   # (x, onset, min_duration)
    for onset in sorted_onsets:
        nx = onset_x[onset]
        dur = min(r.note_event.duration for r in onset_map[onset])
        stem_info.append((nx, onset, dur))

    # ── Beaming analysis
    beamed = _get_beamed_onsets(stem_info)

    # ── Draw stems  (before notes so ovals cover them)
    stem_bot = sys_y + _STEM_GAP
    stem_top = sys_y + _STEM_H
    c.setStrokeColor(_COL_BLACK)
    for nx, onset, dur in stem_info:
        c.setLineWidth(0.8)
        c.line(nx, stem_bot, nx, stem_top)
        if onset not in beamed:
            for fi in range(_num_flags(dur)):
                _draw_flag(c, nx, stem_top - fi * 4.0)

    # ── Draw beams
    _draw_beams(c, stem_info, beamed, stem_top)

    # ── Let-ring lines  (before notes so ovals cover the line start)
    _draw_let_ring(c, onset_map, onset_x, x1, sys_y)

    # ── Draw notes  (on top of everything)
    for onset in sorted_onsets:
        nx = onset_x[onset]
        for r in onset_map[onset]:
            sy = sys_y - (r.state.string_num - 1) * _STRING_SPACING
            _draw_note(c, nx, sy, r.state.fret, r.state.finger)


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


def _num_flags(duration: float) -> int:
    """Number of stem flags for a given duration in beats."""
    if duration >= 0.5:
        return 0    # quarter note or longer — no flags
    if duration >= 0.25:
        return 1    # 8th note
    if duration >= 0.125:
        return 2    # 16th note
    return 3        # 32nd note or shorter


def _draw_flag(c: rl_canvas.Canvas, x: float, y: float) -> None:
    """Draw a single flag curve starting at (x, y) sweeping down-right."""
    c.setLineWidth(0.7)
    c.setStrokeColor(_COL_BLACK)
    p = c.beginPath()
    p.moveTo(x, y)
    p.curveTo(x + 5.5, y - 2.0, x + 6.0, y - 5.0, x + 3.5, y - 8.5)
    c.drawPath(p, stroke=1, fill=0)


def _get_beamed_onsets(
    stem_info: list[tuple[float, float, float]],
) -> set[float]:
    """Return onset values that belong to a beam group (≥2 consecutive beamable notes).

    Notes with duration < 0.5 beats (8th note threshold) can be beamed.
    """
    beamed: set[float] = set()
    i = 0
    while i < len(stem_info):
        _, onset_i, dur_i = stem_info[i]
        if dur_i >= 0.5:
            i += 1
            continue
        group = [onset_i]
        j = i + 1
        while j < len(stem_info):
            _, onset_j, dur_j = stem_info[j]
            if dur_j >= 0.5:
                break
            group.append(onset_j)
            j += 1
        if len(group) >= 2:
            beamed.update(group)
        i = max(i + 1, j)
    return beamed


def _draw_beams(
    c: rl_canvas.Canvas,
    stem_info: list[tuple[float, float, float]],
    beamed: set[float],
    beam_y: float,
) -> None:
    """Draw filled beam bars connecting groups of beamed stems."""
    if not beamed:
        return
    BEAM_H = 2.5
    BEAM_GAP = 3.0
    c.setFillColor(_COL_BLACK)

    i = 0
    while i < len(stem_info):
        x_i, onset_i, _ = stem_info[i]
        if onset_i not in beamed:
            i += 1
            continue
        j = i + 1
        while j < len(stem_info) and stem_info[j][1] in beamed:
            j += 1
        group = [(stem_info[k][0], stem_info[k][2]) for k in range(i, j)]
        if len(group) >= 2:
            gx0, gx1 = group[0][0], group[-1][0]
            # Primary beam (8th note)
            c.rect(gx0, beam_y - BEAM_H, gx1 - gx0, BEAM_H, fill=1, stroke=0)
            # Secondary beam (16th note) if all notes qualify
            if all(d < 0.25 for _, d in group):
                c.rect(
                    gx0, beam_y - BEAM_H - BEAM_GAP - BEAM_H,
                    gx1 - gx0, BEAM_H, fill=1, stroke=0,
                )
        i = j


# ---------------------------------------------------------------------------
# Note rendering
# ---------------------------------------------------------------------------


def _draw_note(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    fret: int,
    finger: Finger,
) -> None:
    """Draw one note at string position (x, y).

    Rendering order:
    1.  White oval  — erases the string line behind the fret number.
    2.  Fret number — Helvetica-Bold 6 pt, centred in oval, black.
    3.  Finger char — Helvetica 4.8 pt, centred BELOW oval, dark red.
                      Omitted for open strings (fret == 0).
    """
    oval_w = _OVAL_W2 if fret >= 10 else _OVAL_W1

    # 1. White oval
    c.setFillColor(colors.white)
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

    # 3. Finger annotation — below oval, only for fretted notes
    if fret > 0 and finger in _FINGER_CHAR:
        c.setFillColor(_FINGER_COLOR)
        c.setFont(_FINGER_FONT, _FINGER_FS)
        c.drawCentredString(x, y + _FINGER_Y, _FINGER_CHAR[finger])
        c.setFillColor(_COL_BLACK)


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


def _system_tempo(
    sys_measures: list[list[FingeringResult]],
    fallback: float,
) -> float:
    """Return the tempo of the first note in the system."""
    for m in sys_measures:
        if m:
            return m[0].note_event.tempo
    return fallback
