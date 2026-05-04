"""Centralized layout rules for page/system/measure placement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutRules:
    """Layout constants and thresholds."""

    page_width: float = 1200.0
    page_height: float = 380.0
    margin_x: float = 60.0
    margin_y: float = 72.0
    content_width: float = 1080.0
    system_height: float = 168.0
    system_gap: float = 14.0
    staff_height: float = 168.0
    measure_min_width: float = 120.0
    measure_max_width: float = 480.0
    measure_lr_pad: float = 20.0
    row_top: float = 88.0
    row_spacing: float = 10.0
    # Proportional spacing: each beat occupies space_per_beat pt horizontally.
    # When a gap between consecutive onsets would fall below min_note_width, the
    # measure widens so every onset has at least min_note_width pt allocated.
    space_per_beat: float = 32.0
    min_note_width: float = 14.0
    min_event_spacing: float = 14.0
    system_leading_inset: float = 52.0
    standard_staff_spacing: float = 8.0
    tab_staff_spacing: float = 10.0
    standard_tab_gap: float = 40.0
    notehead_rx: float = 3.9
    notehead_ry: float = 2.8
    notehead_rotation_deg: float = -20.0
    notehead_stroke_width: float = 0.8
    stem_notehead_dx: float = 3.3
    rest_block_width: float = 8.0
    rest_block_height: float = 3.0


def default_layout_rules() -> LayoutRules:
    """Return the default layout rule set."""
    return LayoutRules()


def raw_measure_width(
    onset_beat_positions: list[float],
    beats_per_measure: int,
    rules: LayoutRules,
) -> float:
    """Compute measure width from gap-based proportional onset spacing.

    For each onset the allocated horizontal space is::

        max(min_note_width, space_per_beat * gap_to_next_onset_in_beats)

    where the last onset's gap extends to the measure end.

    Fundamental invariant: any combination of note values that fills the
    measure completely produces the same width.  A whole note, four quarter
    notes, a half note plus two quarters all give identical widths.  A
    measure widens only when rhythmic density would push individual gaps
    below ``min_note_width`` (typically 16th notes and shorter).
    """
    if not onset_beat_positions:
        return rules.measure_min_width
    positions = sorted(set(onset_beat_positions))
    beats = max(1, beats_per_measure)
    total_usable = 0.0
    for i, pos in enumerate(positions):
        next_pos = positions[i + 1] if i < len(positions) - 1 else float(beats)
        gap_beats = max(0.0, next_pos - pos)
        ideal = rules.space_per_beat * gap_beats
        total_usable += max(rules.min_note_width, ideal)
    return min(
        rules.measure_max_width,
        max(rules.measure_min_width, total_usable + 2.0 * rules.measure_lr_pad),
    )


def event_anchor_x(
    *,
    onset_in_measure: float,
    beats_per_measure: int,
    measure_width: float,
    rules: LayoutRules,
) -> float:
    """Compute event anchor x inside a measure frame."""
    beats = max(1, beats_per_measure)
    frac = onset_in_measure / beats
    usable_w = max(20.0, measure_width - rules.measure_lr_pad * 2)
    return rules.measure_lr_pad + frac * usable_w


def string_row_y(*, string_num: int, rules: LayoutRules) -> float:
    """Return y anchor for one tablature string row."""
    s = max(1, min(6, string_num))
    return rules.row_top + (s - 1) * rules.row_spacing + 4.0


# Maps chromatic pitch class (0–11, C=0) to diatonic step within the octave (C=0…B=6).
# Sharps/flats collapse onto the lower diatonic step (e.g. C#→C=0, D#→D=1).
_CHROMATIC_TO_DIATONIC: tuple[int, ...] = (0, 0, 1, 1, 2, 3, 3, 4, 4, 5, 5, 6)


def pitch_to_staff_y(
    pitch_midi: int,
    *,
    staff_y_origin: float,
    staff_spacing: float,
    clef: str = "treble",
) -> float:
    """Return SVG y-coordinate for a MIDI pitch on a standard staff.

    Treble clef reference: E4 (MIDI 64) = bottom line (line index 0).
    Each diatonic step = staff_spacing / 2 vertically.
    Y decreases as pitch rises (SVG origin at top).

    Args:
        pitch_midi: MIDI pitch number (0–127).
        staff_y_origin: SVG y of the top (5th) staff line.
        staff_spacing: Distance in SVG units between adjacent staff lines.
        clef: Only ``"treble"`` is supported; other values fall back to treble.

    Returns:
        SVG y-coordinate for the notehead centre.  Ledger-line notes are
        placed correctly above/below the staff; the function never raises.
    """
    del clef  # Only treble implemented; bass clef reserved for future work.
    # MIDI octave: C4=60 → octave = pitch_midi // 12 - 1.
    octave = pitch_midi // 12 - 1
    diatonic_in_octave = _CHROMATIC_TO_DIATONIC[pitch_midi % 12]
    # Diatonic steps above E4 (bottom line, step 0 in the treble clef staff).
    # E4 sits at diatonic position 2 in its octave (C=0, D=1, E=2…).
    staff_steps = (octave - 4) * 7 + (diatonic_in_octave - 2)
    # Bottom line = staff_y_origin + 4 * staff_spacing.  Each step upward
    # subtracts half a staff_spacing (SVG y increases downward).
    return staff_y_origin + 4.0 * staff_spacing - staff_steps * (staff_spacing / 2.0)
