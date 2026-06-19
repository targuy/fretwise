"""P0-B failing tests for pitch_to_staff_y().

These tests are intentionally RED — pitch_to_staff_y does not exist yet.
They define the expected contract so the implementation can be written TDD-style.

Musical reference (treble clef, staff_y_origin = y of top line = F5):
    F5 (MIDI 77) → staff_y_origin + 0                   (5th line, top)
    D5 (MIDI 74) → staff_y_origin + 1 * staff_spacing   (4th line)
    B4 (MIDI 71) → staff_y_origin + 2 * staff_spacing   (3rd line, middle)
    G4 (MIDI 67) → staff_y_origin + 3 * staff_spacing   (2nd line)
    E4 (MIDI 64) → staff_y_origin + 4 * staff_spacing   (1st line, bottom)
    C4 (MIDI 60) → staff_y_origin + 5 * staff_spacing   (1st ledger below)
    A4 (MIDI 69) → staff_y_origin + 2.5 * staff_spacing (2nd space)
    E5 (MIDI 76) → staff_y_origin + 0.5 * staff_spacing (space above 4th line)

Every diatonic step = staff_spacing / 2 vertically.
Y increases downward (SVG convention), so higher pitches have lower Y values.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# P0-B-01 — Import guard: function must exist at this path.
# This import WILL fail (ImportError) until pitch_to_staff_y is implemented.
# ---------------------------------------------------------------------------
from fretwise.core.layout.rules import pitch_to_staff_y  # type: ignore[attr-defined]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ORIGIN = 100.0      # arbitrary staff_y_origin for all tests
SPACING = 8.0       # arbitrary staff_spacing for all tests


def _y(pitch_midi: int, *, origin: float = ORIGIN, spacing: float = SPACING) -> float:
    """Shorthand: call with default treble clef."""
    return pitch_to_staff_y(
        pitch_midi,
        staff_y_origin=origin,
        staff_spacing=spacing,
    )


# ---------------------------------------------------------------------------
# P0-B-02 — Default clef is "treble"
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_default_clef_is_treble() -> None:
    """Calling without clef= must behave identically to clef='treble'."""
    y_default = pitch_to_staff_y(71, staff_y_origin=ORIGIN, staff_spacing=SPACING)
    y_explicit = pitch_to_staff_y(71, staff_y_origin=ORIGIN, staff_spacing=SPACING, clef="treble")
    assert y_default == y_explicit


# ---------------------------------------------------------------------------
# P0-B-03 — Staff line anchors (treble clef, five reference pitches)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pitch_midi, expected_offset_in_spacings",
    [
        (77, 0.0),    # F5 — top (5th) line
        (74, 1.0),    # D5 — 4th line
        (71, 2.0),    # B4 — middle (3rd) line
        (67, 3.0),    # G4 — 2nd line
        (64, 4.0),    # E4 — bottom (1st) line
    ],
    ids=["F5_top_line", "D5_4th_line", "B4_middle_line", "G4_2nd_line", "E4_bottom_line"],
)
def test_pitch_to_staff_y_line_anchors(pitch_midi: int, expected_offset_in_spacings: float) -> None:
    """Each staff line pitch maps to an exact multiple of staff_spacing from origin."""
    expected_y = ORIGIN + expected_offset_in_spacings * SPACING
    assert _y(pitch_midi) == pytest.approx(expected_y, abs=1e-9)


# ---------------------------------------------------------------------------
# P0-B-04 — Space positions (between lines)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "pitch_midi, expected_offset_in_spacings",
    [
        (69, 2.5),    # A4 — 2nd space (between G4 line and B4 line)
        (76, 0.5),    # E5 — space above 4th line (between D5 and F5)
        (65, 3.5),    # F4 — 1st space (between E4 line and G4 line)
        (62, 4.5),    # D4 — space below 1st line (between C4 ledger and E4)
    ],
    ids=["A4_2nd_space", "E5_space_above_4th", "F4_1st_space", "D4_below_bottom"],
)
def test_pitch_to_staff_y_space_positions(pitch_midi: int, expected_offset_in_spacings: float) -> None:
    """Notes in spaces sit at half-integer multiples of staff_spacing."""
    expected_y = ORIGIN + expected_offset_in_spacings * SPACING
    assert _y(pitch_midi) == pytest.approx(expected_y, abs=1e-9)


# ---------------------------------------------------------------------------
# P0-B-05 — C4 (middle C): 1st ledger line below staff
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_middle_c_below_staff() -> None:
    """C4 (MIDI 60) sits on the 1st ledger line below, 5 spacings from origin."""
    expected_y = ORIGIN + 5.0 * SPACING
    assert _y(60) == pytest.approx(expected_y, abs=1e-9)


# ---------------------------------------------------------------------------
# P0-B-06 — Y ordering: higher pitches have smaller Y (SVG downward axis)
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_monotone_y_decreases_with_pitch() -> None:
    """For ascending pitches, Y must strictly decrease (higher note = lower Y in SVG)."""
    pitches = [60, 62, 64, 65, 67, 69, 71, 72, 74, 76, 77]  # C4 … F5
    ys = [_y(p) for p in pitches]
    for i in range(len(ys) - 1):
        assert ys[i] > ys[i + 1], (
            f"Expected y({pitches[i]})={ys[i]} > y({pitches[i+1]})={ys[i+1]}"
        )


# ---------------------------------------------------------------------------
# P0-B-07 — E4 < G4 < B4 in Y (SVG: E4_y > G4_y > B4_y)
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_relative_order_e4_g4_b4() -> None:
    """E4 has largest Y, B4 has smallest — lower pitch sits lower on the page."""
    y_e4 = _y(64)
    y_g4 = _y(67)
    y_b4 = _y(71)
    assert y_e4 > y_g4 > y_b4


# ---------------------------------------------------------------------------
# P0-B-08 — staff_y_origin is honoured
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_origin_shifts_all_values() -> None:
    """Changing staff_y_origin shifts all returned Y values by the same delta."""
    origin_a = 50.0
    origin_b = 200.0
    delta = origin_b - origin_a
    for pitch in [60, 64, 67, 71, 74, 77]:
        ya = pitch_to_staff_y(pitch, staff_y_origin=origin_a, staff_spacing=SPACING)
        yb = pitch_to_staff_y(pitch, staff_y_origin=origin_b, staff_spacing=SPACING)
        assert yb == pytest.approx(ya + delta, abs=1e-9), f"pitch={pitch}"


# ---------------------------------------------------------------------------
# P0-B-09 — staff_spacing is honoured
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_spacing_scales_offsets() -> None:
    """Doubling staff_spacing doubles the Y offset from staff_y_origin."""
    spacing_a = 6.0
    spacing_b = 12.0
    # F5 is at origin (offset 0), so use B4 (offset 2*spacing) as a non-trivial case.
    y_b4_a = pitch_to_staff_y(71, staff_y_origin=ORIGIN, staff_spacing=spacing_a)
    y_b4_b = pitch_to_staff_y(71, staff_y_origin=ORIGIN, staff_spacing=spacing_b)
    offset_a = y_b4_a - ORIGIN
    offset_b = y_b4_b - ORIGIN
    assert offset_b == pytest.approx(offset_a * 2.0, abs=1e-9)


# ---------------------------------------------------------------------------
# P0-B-10 — Out-of-staff: low guitar note E2 (MIDI 40)
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_e2_low_guitar_below_staff() -> None:
    """E2 (low guitar string, MIDI 40) sits far below the staff.

    Diatonic steps below F5=MIDI 77:
    F5(77)->E5(76)->D5(74)->C5(72)->B4(71)->A4(69)->G4(67)->F4(65)->E4(64)->
    D4(62)->C4(60)->B3(59)->A3(57)->G3(55)->F3(53)->E3(52)->D3(50)->C3(48)->
    B2(47)->A2(45)->G2(43)->F2(41)->E2(40)
    = 22 diatonic steps below F5

    Expected Y = staff_y_origin + 22 * (staff_spacing / 2)
               = staff_y_origin + 11 * staff_spacing
    """
    expected_y = ORIGIN + 11.0 * SPACING
    assert _y(40) == pytest.approx(expected_y, abs=1e-9)


# ---------------------------------------------------------------------------
# P0-B-11 — Out-of-staff: E2 is below C4 (both below staff)
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_e2_below_c4() -> None:
    """E2 (MIDI 40) sits below C4 (MIDI 60) on the staff."""
    assert _y(40) > _y(60)


# ---------------------------------------------------------------------------
# P0-B-12 — Diatonic step size is always staff_spacing / 2
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_diatonic_step_equals_half_spacing() -> None:
    """Each adjacent pair of diatonic notes (white keys) is staff_spacing/2 apart."""
    half = SPACING / 2.0
    # Adjacent white-key pairs in treble range: (C,D), (D,E), (E,F), (F,G), (G,A), (A,B)
    pairs = [(60, 62), (62, 64), (64, 65), (65, 67), (67, 69), (69, 71)]
    for lower_midi, upper_midi in pairs:
        y_lower = _y(lower_midi)
        y_upper = _y(upper_midi)
        diff = y_lower - y_upper  # positive because lower pitch → higher Y
        assert diff == pytest.approx(half, abs=1e-9), (
            f"Step from MIDI {lower_midi} to {upper_midi}: expected {half}, got {diff}"
        )


# ---------------------------------------------------------------------------
# P0-B-13 — Chromatic pitches collapse to their lower diatonic step
#           (Bb4=MIDI 70 has pitch class 10 → same diatonic step as A4=MIDI 69
#           because _CHROMATIC_TO_DIATONIC maps both 9 and 10 to step 5).
#           This is musically correct: without an explicit accidental marker,
#           the notehead sits at the diatonic slot of its base name.
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_chromatic_collapses_to_lower_diatonic() -> None:
    """Bb4 (MIDI 70) maps to the same staff Y as A4 (MIDI 69).

    The implementation collapses accidentals to the lower diatonic step,
    which is musically correct: the accidental is drawn as a symbol,
    but the notehead sits at the diatonic slot.
    """
    y_a4 = _y(69)    # A4 — diatonic step 5 in octave 4
    y_bb4 = _y(70)   # Bb4/A#4 — same diatonic slot as A4
    assert y_bb4 == pytest.approx(y_a4, abs=1e-9), (
        f"Bb4 (MIDI 70) should map to same Y as A4 (MIDI 69): got {y_bb4} vs {y_a4}"
    )


# ---------------------------------------------------------------------------
# P0-B-14 — High-register note: A5 (MIDI 81) sits above the staff
# ---------------------------------------------------------------------------

def test_pitch_to_staff_y_a5_above_staff() -> None:
    """A5 (MIDI 81) sits 2 diatonic steps above F5 (top line), i.e. 1 spacing above origin.

    Diatonic steps above F5 (top line at staff_y_origin):
      F5 → G5 → A5  = 2 steps = 2 * (staff_spacing / 2) = 1 * staff_spacing

    Expected y = staff_y_origin - 1 * staff_spacing  (above the top line).
    """
    expected_y = ORIGIN - 1.0 * SPACING
    assert _y(81) == pytest.approx(expected_y, abs=1e-9)
