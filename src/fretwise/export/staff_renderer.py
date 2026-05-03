"""Standard music notation renderer (treble clef staff).

Renders FingeringResult sequences as traditional sheet music on a 5-line
staff with treble clef, noteheads, stems, beams, accidentals, bar lines,
time signature, and key signature.

Architecture
------------
This module mirrors the structure of ``pdf_tab.py`` — same page dimensions,
same measure-grouping utilities, same system-based layout — so that the
combined renderer can stack staff + tab systems with aligned columns.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib.units import mm  # type: ignore[import-untyped]
from reportlab.pdfgen import canvas as rl_canvas  # type: ignore[import-untyped]

from fretwise.models import Finger, FingeringResult

# ---------------------------------------------------------------------------
# Layout constants (pt — 1 pt = 1/72 inch)
# ---------------------------------------------------------------------------

_PAGE_W = 595.0
_PAGE_H = 842.0
_MARGIN = 28.5

# Staff geometry
_NUM_LINES = 5
_STAFF_SPACING = 8.0          # distance between adjacent staff lines (pt)
_STAFF_HEIGHT = (_NUM_LINES - 1) * _STAFF_SPACING  # 32 pt

# Clef / label column
_CLEF_W = 34.0
_NOTES_X0 = _MARGIN + _CLEF_W  # 62.5 pt — matches tab _STRINGS_X0

# Stem
# Minimum stem length measured from the notehead *closest* to the stem tip:
# 3.5 staff spaces = 3.5 × _STAFF_SPACING = 28 pt.
# For a single note this is the full stem length from its own center.
# For chords, the stem is extended so the farthest note from the tip still
# has at least this clearance.
_MIN_STEM_CLEARANCE = 3.5 * _STAFF_SPACING   # 28.0 pt
_STEM_UP_THRESHOLD = 71       # MIDI B4 — stems up below, stems down above

# Notehead
_NH_RX = 4.5                  # notehead ellipse horizontal radius
_NH_RY = 3.2                  # notehead ellipse vertical radius

# System extents — base values; will be overridden per-system by
# _compute_system_extents() to handle notes with many ledger lines.
_ABOVE_STAFF_BASE = 32.0      # room for ledger lines / stems above top line
_BELOW_STAFF_BASE = 24.0      # room for ledger below + dynamics
# Export the old names as aliases so combined_renderer keeps working.
_ABOVE_STAFF = _ABOVE_STAFF_BASE
_BELOW_STAFF = _BELOW_STAFF_BASE
_SYSTEM_H = _ABOVE_STAFF_BASE + _STAFF_HEIGHT + _BELOW_STAFF_BASE  # ~88 pt
_INTER_SYSTEM_GAP = 10.0
_SYSTEM_PITCH = _SYSTEM_H + _INTER_SYSTEM_GAP

# Extra padding added on top of the actual ledger-line extent (pt)
_LEDGER_PAD = 14.0

# Accidental glyphs (Unicode)
_SHARP = "♯"
_FLAT = "♭"
_NATURAL = "♮"

# Beam
_BEAM_H = 3.0
_BEAM_GAP = 3.0

# Colours
_COL_BLACK = (0, 0, 0)

# MIDI → staff position mapping
# Middle C (MIDI 60) = C4 = one ledger line below treble staff.
# Staff line 1 (bottom) = E4 = MIDI 64.  Each staff position = 1 semitone step
# mapped through the diatonic scale.
#
# We use the standard mapping: position 0 = middle C (C4), each +1 = next
# diatonic step.  Staff bottom line = E4 = position 2.

_PITCH_CLASS_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# Map pitch class (0–11) to diatonic step within the octave (C=0, D=1, E=2, F=3, G=4, A=5, B=6)
# and accidental offset.
_PC_TO_DIATONIC: dict[int, tuple[int, int]] = {
    0: (0, 0),   # C
    1: (0, 1),   # C# → C+sharp
    2: (1, 0),   # D
    3: (1, 1),   # D# → D+sharp
    4: (2, 0),   # E
    5: (3, 0),   # F
    6: (3, 1),   # F# → F+sharp
    7: (4, 0),   # G
    8: (4, 1),   # G# → G+sharp
    9: (5, 0),   # A
    10: (5, 1),  # A# → A+sharp
    11: (6, 0),  # B
}

# How many diatonic steps per octave
_DIATONIC_PER_OCTAVE = 7

# Finger → annotation letter (left of notehead)
_FINGER_LETTER: dict[str, str] = {
    Finger.INDEX: "I",
    Finger.MIDDLE: "M",
    Finger.RING: "R",
    Finger.PINKY: "P",
}


def _midi_to_staff_pos(midi: int) -> tuple[int, int]:
    """Convert MIDI pitch to (diatonic_position, accidental).

    Position 0 = C4 (middle C).  Each +1 = one diatonic step up.
    Accidental: 0 = natural, 1 = sharp.

    Returns:
        (staff_position, accidental)
    """
    octave = midi // 12 - 1   # MIDI 60 = C4 → octave 4
    pc = midi % 12
    diatonic_step, accidental = _PC_TO_DIATONIC[pc]
    # C4 = position 0.  Each octave = 7 diatonic steps.
    position = (octave - 4) * _DIATONIC_PER_OCTAVE + diatonic_step
    return position, accidental


def _staff_pos_to_y(staff_y: float, position: int) -> float:
    """Convert diatonic position to y coordinate on the page.

    Args:
        staff_y: y of the bottom staff line (line 1 = E4 = position 2).
        position: Diatonic position (0 = C4).

    Returns:
        y coordinate in points.
    """
    # Bottom line (E4) = position 2.  Each staff position = half a line spacing.
    half_space = _STAFF_SPACING / 2.0
    return staff_y + (position - 2) * half_space


def _num_flags(duration: float) -> int:
    """Return the number of flags for a given beat duration."""
    if duration >= 1.0:
        return 0        # quarter or longer
    if duration >= 0.5:
        return 1        # eighth
    if duration >= 0.25:
        return 2        # sixteenth
    return 3            # thirty-second


def _is_filled(duration: float) -> bool:
    """Return True if the notehead should be filled (quarter note or shorter)."""
    return duration < 2.0


def _has_stem(duration: float) -> bool:
    """Return True if the note has a stem (everything except whole notes)."""
    return duration < 4.0


# ---------------------------------------------------------------------------
# Per-system extent computation (Issue B)
# ---------------------------------------------------------------------------


def _position_ledger_extent_above(position: int) -> int:
    """Return the highest (largest) diatonic position due to ledger lines above staff.

    Ledger positions above the staff start at 12, 14, 16, …
    The topmost ledger line drawn for *position* is at least *position* itself
    (rounded up to the nearest even ledger-line position ≥ 12).
    """
    if position < 12:
        return 11  # top staff line is position 10 (F5); stems can push to 11
    return position


def _position_ledger_extent_below(position: int) -> int:
    """Return the lowest (smallest) diatonic position due to ledger lines below staff.

    Ledger positions below the staff are 0, -2, -4, …
    The bottommost ledger line drawn for *position* is at most *position* itself
    (rounded down to the nearest even ledger position ≤ 0).
    """
    if position > 0:
        return 1  # bottom staff line is position 2 (E4)
    return position


def _compute_system_extents(
    sys_measures: list[list[FingeringResult]],
    staff_y: float,
) -> tuple[float, float]:
    """Compute the maximum extent above and below the staff for a system.

    Considers both noteheads (including ledger lines) and stems.

    Returns:
        (above_staff, below_staff) — padding in pts required above/below the
        five staff lines to contain all noteheads and stems without clipping.
        Values are at least (_ABOVE_STAFF_BASE, _BELOW_STAFF_BASE).
    """
    max_above = _ABOVE_STAFF_BASE
    max_below = _BELOW_STAFF_BASE

    for measure in sys_measures:
        # Group by onset to handle chord stem lengths
        onset_groups: dict[float, list[FingeringResult]] = {}
        for r in measure:
            k = round(r.note_event.onset, 6)
            onset_groups.setdefault(k, []).append(r)

        for group in onset_groups.values():
            if not group:
                continue
            pitches = [r.note_event.pitch for r in group]
            stem_up = min(pitches) < _STEM_UP_THRESHOLD

            for r in group:
                ne = r.note_event
                pos, _ = _midi_to_staff_pos(ne.pitch)
                note_y = _staff_pos_to_y(staff_y, pos)

                # Ledger-line extent
                if pos < 2:
                    # Notes below the staff — need space below
                    eff_pos = _position_ledger_extent_below(pos)
                    eff_y = _staff_pos_to_y(staff_y, eff_pos)
                    dist_below = staff_y - eff_y + _NH_RY + _LEDGER_PAD
                    max_below = max(max_below, dist_below)
                if pos > 10:
                    # Notes above the staff — need space above
                    eff_pos = _position_ledger_extent_above(pos)
                    eff_y = _staff_pos_to_y(staff_y, eff_pos)
                    dist_above = eff_y - (staff_y + _STAFF_HEIGHT) + _NH_RY + _LEDGER_PAD
                    max_above = max(max_above, dist_above)

            # Stem extent for this onset group
            if _has_stem(group[0].note_event.duration):
                positions = [_midi_to_staff_pos(r.note_event.pitch)[0] for r in group]
                ys = [_staff_pos_to_y(staff_y, p) for p in positions]
                if stem_up:
                    # Stem goes up from the highest note.
                    # Farthest note from stem tip = lowest note in chord.
                    stem_base_y = max(ys)   # highest pitch = largest y-value for stem start
                    lowest_y = min(ys)
                    # stem tip must be at least _MIN_STEM_CLEARANCE above lowest_y
                    stem_tip_y = lowest_y + _MIN_STEM_CLEARANCE
                    stem_tip_y = max(stem_tip_y, stem_base_y + _MIN_STEM_CLEARANCE)
                    if stem_tip_y > staff_y + _STAFF_HEIGHT:
                        dist_above = stem_tip_y - (staff_y + _STAFF_HEIGHT) + _LEDGER_PAD
                        max_above = max(max_above, dist_above)
                else:
                    # Stem goes down from the lowest note.
                    stem_base_y = min(ys)
                    highest_y = max(ys)
                    stem_tip_y = highest_y - _MIN_STEM_CLEARANCE
                    stem_tip_y = min(stem_tip_y, stem_base_y - _MIN_STEM_CLEARANCE)
                    if stem_tip_y < staff_y:
                        dist_below = staff_y - stem_tip_y + _LEDGER_PAD
                        max_below = max(max_below, dist_below)

    return max_above, max_below


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def render_staff_pdf(
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
    """Render standard music notation to a PDF file.

    Args:
        results: FingeringResult list (sorted by onset).
        output_path: Where to write the PDF.
        title: Song title for header.
        artist: Artist name for header.
        beats_per_measure: Time signature numerator.
        mode_label: e.g. "reference mode".
        instrument: Instrument name.
        measures_per_system: Force N measures per system (None=auto).
        section_markers: {1-based measure → label}.
    """
    c = rl_canvas.Canvas(str(output_path), pagesize=(_PAGE_W, _PAGE_H))

    if not results:
        c.setFont("Helvetica", 12)
        c.drawString(_MARGIN, _PAGE_H / 2, "(no notes)")
        c.save()
        return

    available_w = _PAGE_W - _MARGIN - _NOTES_X0
    measures = _group_by_measure(results, beats_per_measure)
    systems = _build_systems(measures, beats_per_measure, available_w, measures_per_system)

    # Page 1: title
    current_top = _PAGE_H - _MARGIN
    if title or artist:
        current_top = _draw_title_block(c, title, artist, instrument, mode_label, current_top)

    song_m_idx = 0

    for sys_measures, sys_mwidths in systems:
        # Compute per-system extents using a representative staff_y.
        # We use a temporary staff_y=0 to get relative extents.
        above, below = _compute_system_extents(sys_measures, 0.0)
        # Clamp to at least base values
        above = max(above, _ABOVE_STAFF_BASE)
        below = max(below, _BELOW_STAFF_BASE)
        system_h = above + _STAFF_HEIGHT + below
        needed = system_h + _INTER_SYSTEM_GAP

        if current_top - needed < _MARGIN + 30:
            c.showPage()
            current_top = _PAGE_H - _MARGIN

        staff_bottom_y = current_top - above - _STAFF_HEIGHT
        _draw_system(
            c, sys_measures, staff_bottom_y, song_m_idx,
            beats_per_measure, sys_mwidths, section_markers,
        )
        current_top -= needed
        song_m_idx += len(sys_measures)

    c.save()


# ---------------------------------------------------------------------------
# Drawing helpers
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


def _draw_system(
    c: rl_canvas.Canvas,
    sys_measures: list[list[FingeringResult]],
    staff_y: float,
    song_m_start: int,
    beats_per_measure: float,
    measure_widths: list[float],
    section_markers: dict[int, str] | None,
) -> None:
    """Draw one complete staff system (clef + 5 lines + notes + barlines)."""
    # Draw 5 staff lines
    x0 = _NOTES_X0
    x_end = _PAGE_W - _MARGIN

    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.5)
    for i in range(_NUM_LINES):
        y = staff_y + i * _STAFF_SPACING
        c.line(x0 - _CLEF_W + 4, y, x_end, y)

    # Draw treble clef
    _draw_treble_clef(c, _MARGIN + 4, staff_y)

    # Time signature (first system only)
    if song_m_start == 0:
        _draw_time_signature(c, _MARGIN + 22, staff_y, int(beats_per_measure), 4)

    # Draw measures
    measure_x = x0
    for m_idx, (m_results, m_width) in enumerate(zip(sys_measures, measure_widths)):
        abs_m = song_m_start + m_idx + 1

        # Section marker
        if section_markers and abs_m in section_markers:
            c.setFont("Helvetica-Bold", 7)
            c.drawString(measure_x + 2, staff_y + _STAFF_HEIGHT + 12,
                         section_markers[abs_m])

        # Measure number
        c.setFont("Helvetica", 5)
        c.setFillColorRGB(0.5, 0.5, 0.5)
        c.drawString(measure_x + 1, staff_y + _STAFF_HEIGHT + 4, str(abs_m))
        c.setFillColorRGB(0, 0, 0)

        _draw_measure_notes(c, m_results, measure_x, m_width, staff_y, beats_per_measure)

        # Barline at end
        bar_x = measure_x + m_width
        c.setLineWidth(0.7)
        c.line(bar_x, staff_y, bar_x, staff_y + _STAFF_HEIGHT)

        measure_x += m_width

    # Final barline (double)
    c.setLineWidth(1.5)
    c.line(x_end, staff_y, x_end, staff_y + _STAFF_HEIGHT)
    c.setLineWidth(0.7)
    c.line(x_end - 3, staff_y, x_end - 3, staff_y + _STAFF_HEIGHT)


def _draw_treble_clef(c: rl_canvas.Canvas, x: float, staff_y: float) -> None:
    """Draw a treble clef symbol at (x, staff_y).

    Uses the Unicode treble clef glyph at appropriate size.
    The clef sits with its curl around the G line (line 2 = G4).
    """
    # Position: centre the glyph around line 2 (G4)
    g_line_y = staff_y + _STAFF_SPACING  # line 2
    c.setFont("Helvetica", 32)
    c.setFillColorRGB(0, 0, 0)
    # Unicode treble clef: 𝄞
    c.drawString(x, g_line_y - 14, "\U0001D11E")


def _draw_time_signature(
    c: rl_canvas.Canvas,
    x: float,
    staff_y: float,
    numerator: int,
    denominator: int,
) -> None:
    """Draw time signature (stacked numerator/denominator)."""
    mid_y = staff_y + _STAFF_HEIGHT / 2
    c.setFont("Helvetica-Bold", 12)
    c.drawCentredString(x, mid_y + 2, str(numerator))
    c.drawCentredString(x, mid_y - 12, str(denominator))


def _compute_chord_stem_tip(
    note_ys: list[float],
    stem_up: bool,
) -> float:
    """Compute the stem tip y-coordinate for a chord.

    The stem tip must be at least _MIN_STEM_CLEARANCE away from the notehead
    farthest from the tip.  For stem-up chords the farthest note is the
    lowest (smallest y); for stem-down chords it is the highest (largest y).

    Args:
        note_ys: Y positions of all noteheads in the chord.
        stem_up: True if the stem points upward.

    Returns:
        Y coordinate of the stem tip.
    """
    if stem_up:
        # Stem base at highest notehead; tip above lowest notehead.
        stem_base = max(note_ys)
        farthest = min(note_ys)
        min_tip = farthest + _MIN_STEM_CLEARANCE
        # Also enforce minimum length from stem base
        min_tip_from_base = stem_base + _MIN_STEM_CLEARANCE
        return max(min_tip, min_tip_from_base)
    else:
        # Stem base at lowest notehead; tip below highest notehead.
        stem_base = min(note_ys)
        farthest = max(note_ys)
        max_tip = farthest - _MIN_STEM_CLEARANCE
        min_tip_from_base = stem_base - _MIN_STEM_CLEARANCE
        return min(max_tip, min_tip_from_base)


def _draw_measure_notes(
    c: rl_canvas.Canvas,
    results: list[FingeringResult],
    x0: float,
    measure_w: float,
    staff_y: float,
    beats_per_measure: float,
) -> None:
    """Draw all notes within a single measure."""
    if not results:
        # Draw whole rest
        _draw_rest(c, x0 + measure_w / 2 - 4, staff_y, 4.0)
        return

    # Compute x positions proportionally
    measure_onset = results[0].note_event.onset
    # Floor to measure boundary
    measure_onset = (measure_onset // beats_per_measure) * beats_per_measure

    pad = 8.0  # left/right padding within measure
    usable_w = measure_w - 2 * pad

    # Group notes by onset (chords share the same x and a single stem)
    onset_groups: dict[float, list[FingeringResult]] = {}
    for r in results:
        k = round(r.note_event.onset, 6)
        onset_groups.setdefault(k, []).append(r)

    for _onset_key, group in sorted(onset_groups.items()):
        ne0 = group[0].note_event
        beat_in_measure = ne0.onset - measure_onset
        frac = beat_in_measure / beats_per_measure if beats_per_measure > 0 else 0
        note_x = x0 + pad + frac * usable_w

        # Determine stem direction from the lowest pitch in the group (majority rule)
        pitches = [r.note_event.pitch for r in group]
        stem_up = min(pitches) < _STEM_UP_THRESHOLD

        # Collect y positions for all notes in this chord
        note_ys: list[float] = []
        for r in group:
            pos, _ = _midi_to_staff_pos(r.note_event.pitch)
            note_ys.append(_staff_pos_to_y(staff_y, pos))

        # Draw each notehead (and its ledger lines, accidentals, finger annotation)
        for r in group:
            ne = r.note_event
            pos, accidental = _midi_to_staff_pos(ne.pitch)
            note_y = _staff_pos_to_y(staff_y, pos)

            # Ledger lines
            _draw_ledger_lines(c, note_x, staff_y, pos)

            # Accidental
            if accidental:
                c.setFont("Helvetica", 9)
                c.setFillColorRGB(0, 0, 0)
                c.drawString(note_x - _NH_RX - 7, note_y - 3, _SHARP)

            # Notehead
            filled = _is_filled(ne.duration)
            _draw_notehead(c, note_x, note_y, filled)

            # Issue C — finger annotation: small red letter to the left of notehead
            finger_letter = _FINGER_LETTER.get(r.state.finger, "")
            if finger_letter:
                c.saveState()
                c.setFont("Helvetica", 6)
                c.setFillColorRGB(0.8, 0.0, 0.0)
                c.drawString(note_x - _NH_RX - 6, note_y - 2, finger_letter)
                c.restoreState()

        # Draw a single shared stem for the chord (Issue A)
        if _has_stem(ne0.duration):
            stem_tip_y = _compute_chord_stem_tip(note_ys, stem_up)
            _draw_chord_stem(c, note_x, note_ys, stem_up, stem_tip_y)

            # Flags (only for unbeamed notes; only drawn once at the stem tip)
            n_flags = _num_flags(ne0.duration)
            if n_flags > 0:
                if stem_up:
                    flag_x = note_x + _NH_RX
                    flag_y = stem_tip_y
                else:
                    flag_x = note_x - _NH_RX
                    flag_y = stem_tip_y
                for i in range(n_flags):
                    _draw_flag_symbol(c, flag_x, flag_y, stem_up, i)


def _draw_notehead(c: rl_canvas.Canvas, x: float, y: float, filled: bool) -> None:
    """Draw an elliptical notehead at (x, y)."""
    c.saveState()
    c.setLineWidth(0.8)
    if filled:
        c.setFillColorRGB(0, 0, 0)
        c.ellipse(x - _NH_RX, y - _NH_RY, x + _NH_RX, y + _NH_RY,
                  stroke=0, fill=1)
    else:
        c.setFillColorRGB(1, 1, 1)
        c.setStrokeColorRGB(0, 0, 0)
        c.ellipse(x - _NH_RX, y - _NH_RY, x + _NH_RX, y + _NH_RY,
                  stroke=1, fill=1)
    c.restoreState()


def _draw_chord_stem(
    c: rl_canvas.Canvas,
    note_x: float,
    note_ys: list[float],
    stem_up: bool,
    stem_tip_y: float,
) -> None:
    """Draw a single stem shared by all noteheads in a chord.

    For a stem-up chord, the stem runs from the highest notehead y upward
    to stem_tip_y.  For stem-down, from the lowest notehead y downward.

    Args:
        note_x: X position of the noteheads.
        note_ys: Y positions of all noteheads in the chord.
        stem_up: True if stem points up.
        stem_tip_y: Pre-computed y coordinate of the stem tip.
    """
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    if stem_up:
        stem_x = note_x + _NH_RX
        stem_base_y = max(note_ys)  # highest note (stem attaches at top of notehead)
        c.line(stem_x, stem_base_y, stem_x, stem_tip_y)
    else:
        stem_x = note_x - _NH_RX
        stem_base_y = min(note_ys)  # lowest note (stem attaches at bottom of notehead)
        c.line(stem_x, stem_base_y, stem_x, stem_tip_y)


def _draw_stem(c: rl_canvas.Canvas, x: float, y: float, stem_up: bool) -> None:
    """Draw a vertical stem from a single notehead (legacy helper).

    For single notes the stem length is at least _MIN_STEM_CLEARANCE.
    """
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.8)
    if stem_up:
        stem_x = x + _NH_RX
        c.line(stem_x, y, stem_x, y + _MIN_STEM_CLEARANCE)
    else:
        stem_x = x - _NH_RX
        c.line(stem_x, y, stem_x, y - _MIN_STEM_CLEARANCE)


def _draw_ledger_lines(
    c: rl_canvas.Canvas,
    x: float,
    staff_y: float,
    position: int,
) -> None:
    """Draw ledger lines for notes above or below the staff."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setLineWidth(0.6)
    ledger_w = _NH_RX + 3

    # Middle C (position 0) needs one ledger below
    # Bottom line is position 2 (E4), top line is position 10 (F5).
    # Ledger lines at position 0 (C4), -2 (A3), etc.
    # and position 12 (A5), 14 (C6), etc.

    # Below staff: position 0, -2, -4, ...
    if position <= 0:
        pos = 0
        while pos >= position:
            ly = _staff_pos_to_y(staff_y, pos)
            c.line(x - ledger_w, ly, x + ledger_w, ly)
            pos -= 2

    # Above staff: position 12, 14, 16, ...
    if position >= 12:
        pos = 12
        while pos <= position:
            ly = _staff_pos_to_y(staff_y, pos)
            c.line(x - ledger_w, ly, x + ledger_w, ly)
            pos += 2


def _draw_flag_symbol(
    c: rl_canvas.Canvas,
    x: float,
    y: float,
    stem_up: bool,
    flag_index: int,
) -> None:
    """Draw a flag (eighth/sixteenth/32nd note flag)."""
    c.setStrokeColorRGB(0, 0, 0)
    c.setFillColorRGB(0, 0, 0)
    c.setLineWidth(0.8)

    offset = flag_index * 5
    if stem_up:
        fy = y - offset
        # Small curved flag going right and down
        p = c.beginPath()
        p.moveTo(x, fy)
        p.curveTo(x + 7, fy - 3, x + 7, fy - 8, x + 2, fy - 12)
        c.drawPath(p, stroke=1, fill=0)
    else:
        fy = y + offset
        p = c.beginPath()
        p.moveTo(x, fy)
        p.curveTo(x - 7, fy + 3, x - 7, fy + 8, x - 2, fy + 12)
        c.drawPath(p, stroke=1, fill=0)


def _draw_rest(c: rl_canvas.Canvas, x: float, staff_y: float, duration: float) -> None:
    """Draw a rest symbol on the staff."""
    mid_y = staff_y + _STAFF_HEIGHT / 2

    c.setFillColorRGB(0, 0, 0)
    c.setStrokeColorRGB(0, 0, 0)

    if duration >= 4.0:
        # Whole rest: filled rectangle hanging from line 4
        ry = staff_y + 3 * _STAFF_SPACING
        c.rect(x, ry - 4, 8, 4, fill=1, stroke=0)
    elif duration >= 2.0:
        # Half rest: filled rectangle sitting on line 3
        ry = staff_y + 2 * _STAFF_SPACING
        c.rect(x, ry, 8, 4, fill=1, stroke=0)
    elif duration >= 1.0:
        # Quarter rest: squiggle approximation
        c.setFont("Helvetica", 18)
        c.drawString(x - 2, mid_y - 7, "\U0001D13D")
    elif duration >= 0.5:
        # Eighth rest
        c.setFont("Helvetica", 14)
        c.drawString(x - 1, mid_y - 4, "\U0001D13E")
    else:
        # Sixteenth rest
        c.setFont("Helvetica", 14)
        c.drawString(x - 1, mid_y - 4, "\U0001D13F")


# ---------------------------------------------------------------------------
# Grouping utilities (mirrored from pdf_tab.py for alignment)
# ---------------------------------------------------------------------------


def _group_by_measure(
    results: list[FingeringResult],
    beats_per_measure: float,
) -> list[list[FingeringResult]]:
    """Group results into measures by onset."""
    if not results:
        return []

    measures: list[list[FingeringResult]] = []
    current_measure: list[FingeringResult] = []
    current_m_start = 0.0

    for r in results:
        while r.note_event.onset >= current_m_start + beats_per_measure - 0.001:
            measures.append(current_measure)
            current_measure = []
            current_m_start += beats_per_measure
        current_measure.append(r)

    if current_measure:
        measures.append(current_measure)

    return measures


def _build_systems(
    measures: list[list[FingeringResult]],
    beats_per_measure: float,
    available_w: float,
    forced_mps: int | None,
) -> list[tuple[list[list[FingeringResult]], list[float]]]:
    """Pack measures into systems, returning (measures, widths) per system."""
    if not measures:
        return []

    n = len(measures)

    if forced_mps is not None and forced_mps > 0:
        mps = forced_mps
    else:
        mps = max(2, min(6, int(available_w / 90)))

    systems: list[tuple[list[list[FingeringResult]], list[float]]] = []
    i = 0
    while i < n:
        chunk = measures[i: i + mps]
        even_w = available_w / len(chunk)
        widths = [even_w] * len(chunk)
        systems.append((chunk, widths))
        i += len(chunk)

    return systems
