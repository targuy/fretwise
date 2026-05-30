"""Tests for fretwise.core.notation_utils — diatonic helpers and staff-Y placement."""

from __future__ import annotations

import pytest

from fretwise.core.notation_utils import (
    diatonic_step_from_metadata,
    diatonic_step_from_name,
    diatonic_step_index,
    standard_note_y,
)

# Reference: each octave has 7 diatonic steps; E4 has absolute index 4*7+2 = 30.
_E4_INDEX = 30


class TestDiatonicStepIndex:
    @pytest.mark.parametrize(
        "pitch, expected",
        [
            (60, 4 * 7 + 0),   # C4 → 28
            (62, 4 * 7 + 1),   # D4 → 29
            (64, 4 * 7 + 2),   # E4 → 30
            (65, 4 * 7 + 3),   # F4 → 31
            (67, 4 * 7 + 4),   # G4 → 32
            (69, 4 * 7 + 5),   # A4 → 33
            (71, 4 * 7 + 6),   # B4 → 34
            (72, 5 * 7 + 0),   # C5 → 35
        ],
    )
    def test_natural_pitches(self, pitch: int, expected: int) -> None:
        assert diatonic_step_index(pitch) == expected

    @pytest.mark.parametrize(
        "natural, accidental",
        [
            (60, 61),  # C4 vs C#4 — same diatonic step
            (62, 63),  # D4 vs D#4 / Eb4
            (65, 66),  # F4 vs F#4
            (69, 70),  # A4 vs Bb4
        ],
    )
    def test_accidentals_collapse_to_lower_neighbour(
        self, natural: int, accidental: int
    ) -> None:
        assert diatonic_step_index(natural) == diatonic_step_index(accidental)

    def test_octave_boundary(self) -> None:
        # B3 (59) → 3*7 + 6 = 27; C4 (60) → 4*7 = 28
        assert diatonic_step_index(59) == 27
        assert diatonic_step_index(60) == 28


class TestDiatonicStepFromName:
    def test_e4_matches_pitch64(self) -> None:
        assert diatonic_step_from_name("E", 4) == _E4_INDEX

    def test_case_insensitive(self) -> None:
        assert diatonic_step_from_name("e", 4) == diatonic_step_from_name("E", 4)

    def test_invalid_letter_raises(self) -> None:
        with pytest.raises(KeyError):
            diatonic_step_from_name("H", 4)

    @pytest.mark.parametrize(
        "step, octave, expected",
        [
            ("C", 4, 28),
            ("F", 4, 31),
            ("B", 3, 27),
            ("C", 5, 35),
        ],
    )
    def test_known_pairs(self, step: str, octave: int, expected: int) -> None:
        assert diatonic_step_from_name(step, octave) == expected


class TestDiatonicStepFromMetadata:
    def test_uses_metadata_when_present(self) -> None:
        # Bb4 spelled with pitch_step=B, pitch_octave=4 → diatonic step of B4.
        # Without the spelling we'd collapse Bb (MIDI 70) to A.
        meta = {"pitch_step": "B", "pitch_octave": "4"}
        assert diatonic_step_from_metadata(meta, fallback_pitch=70) == diatonic_step_from_name("B", 4)

    def test_falls_back_when_step_missing(self) -> None:
        assert diatonic_step_from_metadata({}, fallback_pitch=64) == diatonic_step_index(64)

    def test_falls_back_on_bad_octave(self) -> None:
        meta = {"pitch_step": "E", "pitch_octave": "not_a_number"}
        assert diatonic_step_from_metadata(meta, fallback_pitch=60) == diatonic_step_index(60)

    def test_falls_back_on_bad_step_letter(self) -> None:
        meta = {"pitch_step": "X", "pitch_octave": "4"}
        assert diatonic_step_from_metadata(meta, fallback_pitch=64) == diatonic_step_index(64)


class TestStandardNoteY:
    """E4 sits on the bottom line (staff_y_origin + 4 * staff_spacing)."""

    def test_e4_is_on_bottom_line(self) -> None:
        y = standard_note_y(64, staff_y_origin=10.0, staff_spacing=4.0)
        assert y == pytest.approx(10.0 + 4 * 4.0)  # 26.0

    def test_one_step_up_subtracts_half_spacing(self) -> None:
        # F4 (65) is the next diatonic step above E4 — half a staff-space higher.
        y_e4 = standard_note_y(64, staff_y_origin=10.0, staff_spacing=4.0)
        y_f4 = standard_note_y(65, staff_y_origin=10.0, staff_spacing=4.0)
        assert y_f4 == pytest.approx(y_e4 - 2.0)

    def test_octave_up_subtracts_seven_half_spaces(self) -> None:
        y_e4 = standard_note_y(64, staff_y_origin=0.0, staff_spacing=4.0)
        y_e5 = standard_note_y(76, staff_y_origin=0.0, staff_spacing=4.0)
        # Seven diatonic steps × 2.0 (half-spacing) = 14.0
        assert y_e4 - y_e5 == pytest.approx(14.0)

    def test_explicit_step_overrides_pitch(self) -> None:
        # Bb spelled as B: should use B (one step higher than A).
        y_with_spelling = standard_note_y(
            70, staff_y_origin=0.0, staff_spacing=4.0, step="B", octave=4
        )
        y_without = standard_note_y(70, staff_y_origin=0.0, staff_spacing=4.0)
        # B is higher than A (which Bb collapses to) → smaller Y.
        assert y_with_spelling < y_without

    def test_bad_explicit_step_falls_back_to_pitch(self) -> None:
        y_with_bad = standard_note_y(
            64, staff_y_origin=0.0, staff_spacing=4.0, step="H", octave=4
        )
        y_pitch_only = standard_note_y(64, staff_y_origin=0.0, staff_spacing=4.0)
        assert y_with_bad == pytest.approx(y_pitch_only)

    def test_c4_is_one_ledger_below(self) -> None:
        # C4 is 2 diatonic steps below E4 → one whole space (= 2 half-spaces) below the bottom line.
        y_e4 = standard_note_y(64, staff_y_origin=0.0, staff_spacing=4.0)
        y_c4 = standard_note_y(60, staff_y_origin=0.0, staff_spacing=4.0)
        assert y_c4 - y_e4 == pytest.approx(4.0)  # one full staff_spacing
