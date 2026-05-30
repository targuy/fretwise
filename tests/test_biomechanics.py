"""Tests for pure biomechanical fingering validation."""

from __future__ import annotations

from fretwise.biomechanics import (
    BiomechanicalRuleConfig,
    BiomechanicalSeverity,
    validate_fingering_results,
)
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent


def _result(
    note_id: int = 0,
    *,
    pitch: int = 60,
    onset: float = 0.0,
    duration: float = 1.0,
    string_num: int = 3,
    fret: int = 5,
    finger: Finger = Finger.INDEX,
    hand_position: int = 5,
    measure: int = 1,
    voice: int = 0,
    slide_type: str | None = None,
    muted: bool = False,
) -> FingeringResult:
    note = NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        measure_index=measure,
        voice_hint=voice,
        slide_type=slide_type,
        muted=muted,
    )
    state = FingeringState(
        string_num=string_num,
        fret=fret,
        finger=finger,
        hand_position=hand_position,
    )
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=1.0)


def _codes(results: list[FingeringResult]) -> set[str]:
    return {v.code for v in validate_fingering_results(results).violations}


def test_clean_single_note_has_no_violations() -> None:
    report = validate_fingering_results([_result()])

    assert report.is_clean
    assert report.checked_notes == 1
    assert report.fatal_count == 0


def test_state_pitch_mismatch_is_reported() -> None:
    result = _result(pitch=61, string_num=3, fret=5)

    report = validate_fingering_results([result])

    assert [v.code for v in report.violations] == ["BIO-STATE-003"]
    assert report.violations[0].severity == BiomechanicalSeverity.HIGH


def test_open_string_with_fretting_finger_is_fatal() -> None:
    result = _result(pitch=64, string_num=1, fret=0, finger=Finger.INDEX)

    assert "BIO-STATE-004" in _codes([result])


def test_fretted_note_with_open_finger_is_fatal() -> None:
    result = _result(finger=Finger.OPEN)

    assert "BIO-STATE-005" in _codes([result])


def test_fret_below_hand_position_is_fatal() -> None:
    result = _result(fret=5, hand_position=7)

    assert "BIO-STATE-007" in _codes([result])


def test_natural_hand_position_check_is_opt_in() -> None:
    result = _result(fret=7, finger=Finger.RING, hand_position=7, pitch=62)

    default_report = validate_fingering_results([result])
    strict_report = validate_fingering_results(
        [result],
        config=BiomechanicalRuleConfig(enforce_natural_hand_position=True),
    )

    assert "BIO-STATE-008" not in {v.code for v in default_report.violations}
    assert "BIO-STATE-008" in {v.code for v in strict_report.violations}


def test_same_string_different_frets_in_chord_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60)
    second = _result(1, onset=0.0, string_num=3, fret=7, pitch=62, finger=Finger.RING)

    assert "BIO-CHORD-001" in _codes([first, second])


def test_same_onset_in_different_measures_is_not_one_chord() -> None:
    first = _result(0, onset=120.0, measure=30, string_num=4, fret=5, pitch=55)
    second = _result(1, onset=120.0, measure=31, string_num=4, fret=2, pitch=52)

    assert "BIO-CHORD-001" not in _codes([first, second])


def test_duplicate_non_barre_finger_in_chord_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=4, fret=7, pitch=57, finger=Finger.INDEX)

    assert "BIO-CHORD-002" in _codes([first, second])


def test_index_barre_same_fret_contiguous_strings_is_allowed() -> None:
    first = _result(0, onset=0.0, string_num=2, fret=1, pitch=60, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=3, fret=1, pitch=56, finger=Finger.INDEX)

    assert "BIO-CHORD-002" not in _codes([first, second])


def test_index_full_barre_same_fret_non_contiguous_strings_is_allowed() -> None:
    first = _result(0, onset=0.0, string_num=1, fret=3, pitch=67, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=2, fret=3, pitch=62, finger=Finger.INDEX)
    third = _result(2, onset=0.0, string_num=6, fret=3, pitch=43, finger=Finger.INDEX)

    assert "BIO-CHORD-002" not in _codes([first, second, third])


def test_two_note_non_contiguous_index_barre_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=2, fret=6, pitch=65, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=4, fret=6, pitch=56, finger=Finger.INDEX)

    assert "BIO-CHORD-002" in _codes([first, second])


def test_wide_two_note_index_barre_is_allowed() -> None:
    first = _result(0, onset=0.0, string_num=1, fret=5, pitch=69, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=5, fret=5, pitch=50, finger=Finger.INDEX)

    assert "BIO-CHORD-002" not in _codes([first, second])


def test_crossed_finger_order_in_chord_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60, finger=Finger.RING)
    second = _result(1, onset=0.0, string_num=4, fret=7, pitch=57, finger=Finger.INDEX)

    assert "BIO-CHORD-003" in _codes([first, second])


def test_chord_total_span_limit_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=1, pitch=56, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=4, fret=7, pitch=57, finger=Finger.PINKY)

    assert "BIO-CHORD-004" in _codes([first, second])


def test_muted_note_does_not_count_toward_chord_span() -> None:
    low_muted = _result(0, onset=0.0, string_num=2, fret=1, pitch=60, muted=True)
    high = _result(1, onset=0.0, string_num=1, fret=15, pitch=79, finger=Finger.PINKY)

    assert "BIO-CHORD-004" not in _codes([low_muted, high])


def test_chord_pair_span_limit_is_fatal() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60, finger=Finger.INDEX)
    second = _result(1, onset=0.0, string_num=4, fret=8, pitch=58, finger=Finger.MIDDLE)

    assert "BIO-CHORD-005" in _codes([first, second])


def test_high_position_pair_span_allows_smaller_fret_spacing() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=12, pitch=67, finger=Finger.RING)
    second = _result(1, onset=0.0, string_num=1, fret=15, pitch=79, finger=Finger.PINKY)

    assert "BIO-CHORD-005" not in _codes([first, second])


def test_chord_divergent_hand_positions_are_medium() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60, hand_position=5)
    second = _result(
        1,
        onset=0.0,
        string_num=4,
        fret=7,
        pitch=57,
        finger=Finger.RING,
        hand_position=6,
    )

    report = validate_fingering_results([first, second])

    violation = next(v for v in report.violations if v.code == "BIO-CHORD-006")
    assert violation.severity == BiomechanicalSeverity.MEDIUM


def test_same_finger_overlap_on_incompatible_positions_is_fatal() -> None:
    first = _result(0, onset=0.0, duration=2.0, string_num=3, fret=5, pitch=60)
    second = _result(1, onset=1.0, string_num=4, fret=7, pitch=57, finger=Finger.INDEX)

    assert "BIO-TRANS-002" in _codes([first, second])


def test_same_string_rearticulation_is_not_overlap() -> None:
    first = _result(0, onset=0.0, duration=2.0, string_num=5, fret=7, pitch=52)
    second = _result(1, onset=1.0, string_num=5, fret=8, pitch=53, finger=Finger.INDEX)

    assert "BIO-TRANS-002" not in _codes([first, second])


def test_overlapping_index_barre_same_fret_is_allowed() -> None:
    first = _result(0, onset=0.0, duration=2.0, string_num=3, fret=5, pitch=60)
    second = _result(1, onset=1.0, string_num=4, fret=5, pitch=55, finger=Finger.INDEX)

    assert "BIO-TRANS-002" not in _codes([first, second])


def test_same_finger_overlap_with_slide_is_allowed() -> None:
    first = _result(
        0,
        onset=0.0,
        duration=2.0,
        string_num=3,
        fret=5,
        pitch=60,
        slide_type="shift",
    )
    second = _result(1, onset=1.0, string_num=3, fret=7, pitch=62, finger=Finger.INDEX)

    assert "BIO-TRANS-002" not in _codes([first, second])


def test_extreme_shift_is_medium() -> None:
    first = _result(0, onset=0.0, string_num=3, fret=5, pitch=60, hand_position=5)
    second = _result(
        1,
        onset=0.25,
        string_num=3,
        fret=15,
        pitch=70,
        finger=Finger.INDEX,
        hand_position=15,
    )

    report = validate_fingering_results([first, second])

    violation = next(v for v in report.violations if v.code == "BIO-TRANS-001")
    assert violation.severity == BiomechanicalSeverity.MEDIUM


def test_validator_does_not_mutate_input() -> None:
    result = _result(note_id=3, hand_position=7)
    before = result.state.hand_position

    validate_fingering_results([result])

    assert result.state.hand_position == before
    assert result.note_id == 3