"""Centralized layout rules for page/system/measure placement."""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.config import config as _config
from fretwise.core.notation_utils import (
    percussion_note_y as _notation_percussion_note_y,
)
from fretwise.core.notation_utils import (
    standard_note_y as _notation_standard_note_y,
)

# Tunable layout-rule defaults are sourced from the centralized config
# (src/fretwise/config/defaults.yaml -> layout.rules). Values mirror the prior
# inline literals exactly; this is a refactor, not a tuning change.
_RULES_CFG = _config().layout.rules


@dataclass(frozen=True)
class LayoutRules:
    """Layout constants and thresholds."""

    page_width: float = _RULES_CFG.page_width
    page_height: float = _RULES_CFG.page_height
    margin_x: float = _RULES_CFG.margin_x
    margin_y: float = _RULES_CFG.margin_y
    content_width: float = _RULES_CFG.content_width
    system_height: float = _RULES_CFG.system_height
    system_gap: float = _RULES_CFG.system_gap
    staff_height: float = _RULES_CFG.staff_height
    measure_min_width: float = _RULES_CFG.measure_min_width
    measure_max_width: float = _RULES_CFG.measure_max_width
    measure_lr_pad: float = _RULES_CFG.measure_lr_pad
    row_top: float = _RULES_CFG.row_top
    row_spacing: float = _RULES_CFG.row_spacing
    # Proportional spacing: each beat occupies space_per_beat pt horizontally.
    # When a gap between consecutive onsets would fall below min_note_width, the
    # measure widens so every onset has at least min_note_width pt allocated.
    space_per_beat: float = _RULES_CFG.space_per_beat
    min_note_width: float = _RULES_CFG.min_note_width
    min_event_spacing: float = _RULES_CFG.min_event_spacing
    # Standard-notation-specific spacing overrides.  Modes that include a
    # standard staff (stems, accidentals, ties) require more horizontal room
    # than pure TAB.  canonical_to_page_layout() replaces space_per_beat /
    # min_note_width / measure_min_width with these values when has_standard().
    standard_space_per_beat: float = _RULES_CFG.standard_space_per_beat
    standard_min_note_width: float = _RULES_CFG.standard_min_note_width
    standard_measure_min_width: float = _RULES_CFG.standard_measure_min_width
    system_leading_inset: float = _RULES_CFG.system_leading_inset
    standard_staff_spacing: float = _RULES_CFG.standard_staff_spacing
    tab_staff_spacing: float = _RULES_CFG.tab_staff_spacing
    standard_tab_gap: float = _RULES_CFG.standard_tab_gap
    notehead_rx: float = _RULES_CFG.notehead_rx
    notehead_ry: float = _RULES_CFG.notehead_ry
    notehead_rotation_deg: float = _RULES_CFG.notehead_rotation_deg
    notehead_stroke_width: float = _RULES_CFG.notehead_stroke_width
    stem_notehead_dx: float = _RULES_CFG.stem_notehead_dx
    rest_block_width: float = _RULES_CFG.rest_block_width
    rest_block_height: float = _RULES_CFG.rest_block_height


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


def pitch_to_staff_y(
    pitch_midi: int,
    *,
    staff_y_origin: float,
    staff_spacing: float,
    clef: str = "treble",
) -> float:
    """Return SVG y-coordinate for a MIDI pitch on a standard staff.

    Clef references (bottom line, line index 0):
        treble → E4 (MIDI 64), bass → G2 (MIDI 43).
    Each diatonic step = staff_spacing / 2 vertically.
    Y decreases as pitch rises (SVG origin at top).

    For ``clef == "percussion"`` the pitch is *not* placed diatonically (GM drum
    keys would explode into ledger lines); a fixed percussion slot is used
    instead — see :func:`fretwise.core.notation_utils.percussion_note_y`.

    Args:
        pitch_midi: MIDI pitch number (0–127).
        staff_y_origin: SVG y of the top (5th) staff line.
        staff_spacing: Distance in SVG units between adjacent staff lines.
        clef: ``"treble"`` (default), ``"bass"`` or ``"percussion"``.

    Returns:
        SVG y-coordinate for the notehead centre.  Ledger-line notes are
        placed correctly above/below the staff; the function never raises.
    """
    if clef == "percussion":
        return _notation_percussion_note_y(
            pitch_midi,
            staff_y_origin=staff_y_origin,
            staff_spacing=staff_spacing,
        )
    return _notation_standard_note_y(
        pitch_midi,
        staff_y_origin=staff_y_origin,
        staff_spacing=staff_spacing,
        clef=clef,
    )
