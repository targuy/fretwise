"""Tests for ``fretwise.review.flag_fingerings`` — pure ranking (no ONNX)."""
from __future__ import annotations

from fretwise.biomechanics import (
    BiomechanicalReport,
    BiomechanicalSeverity,
    BiomechanicalViolation,
)
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.review import Severity, flag_fingerings


def _result(
    note_id: int,
    measure: int,
    *,
    string: int = 3,
    fret: int = 5,
    finger: Finger = Finger.INDEX,
    hand_position: int = 5,
    onset: float | None = None,
) -> FingeringResult:
    event = NoteEvent(
        pitch=60,
        onset=float(note_id) if onset is None else onset,
        duration=0.5,
        tempo=120.0,
        measure_index=measure,
        voice_hint=0,
    )
    state = FingeringState(
        string_num=string, fret=fret, finger=finger, hand_position=hand_position,
    )
    return FingeringResult(note_id=note_id, note_event=event, state=state,
                           cost=float(note_id), alternatives=[])


def test_flag_empty_results_returns_empty_report() -> None:
    report = flag_fingerings([])
    assert report.items == []
    assert report.counts == {"impossible": 0, "suspect": 0, "high_cost": 0}


def test_flag_maps_fatal_violation_to_impossible() -> None:
    results = [_result(0, measure=3)]
    biomech = BiomechanicalReport(
        checked_notes=1,
        violations=(
            BiomechanicalViolation(
                code="BIO-STATE-007",
                severity=BiomechanicalSeverity.FATAL,
                message="Fretted note below hand position.",
                note_ids=(0,),
                measure_index=3,
                onset=0.0,
            ),
        ),
    )
    report = flag_fingerings(results, biomech_report=biomech)
    assert report.counts["impossible"] == 1
    assert report.items[0].severity is Severity.IMPOSSIBLE
    assert report.items[0].measure_index == 3
    assert report.items[0].current  # serialized current fingering present


def test_flag_high_severity_violation_maps_to_suspect() -> None:
    results = [_result(0, measure=2)]
    biomech = BiomechanicalReport(
        checked_notes=1,
        violations=(
            BiomechanicalViolation(
                code="BIO-TRANS-001",
                severity=BiomechanicalSeverity.HIGH,
                message="Extreme hand shift.",
                note_ids=(0,),
                measure_index=2,
                onset=0.0,
            ),
        ),
    )
    report = flag_fingerings(results, biomech_report=biomech)
    assert report.counts["suspect"] == 1
    assert report.items[0].severity is Severity.SUSPECT


def test_flag_cost_outlier_marked_high_cost() -> None:
    # Ten cheap, identical notes then one with a large position jump.
    results = [_result(i, measure=i + 1) for i in range(10)]
    results.append(
        _result(10, measure=11, string=1, fret=19, finger=Finger.PINKY,
                hand_position=16),
    )
    clean = BiomechanicalReport(checked_notes=len(results), violations=())
    report = flag_fingerings(results, biomech_report=clean)
    assert report.counts["high_cost"] >= 1
    assert any(it.measure_index == 11 for it in report.items)


def test_flag_orders_impossible_before_high_cost() -> None:
    results = [_result(i, measure=i + 1) for i in range(10)]
    results.append(
        _result(10, measure=11, string=1, fret=19, finger=Finger.PINKY,
                hand_position=16),
    )
    biomech = BiomechanicalReport(
        checked_notes=len(results),
        violations=(
            BiomechanicalViolation(
                code="BIO-CHORD-002",
                severity=BiomechanicalSeverity.FATAL,
                message="Duplicate finger.",
                note_ids=(0,),
                measure_index=1,
                onset=0.0,
            ),
        ),
    )
    report = flag_fingerings(results, biomech_report=biomech)
    assert report.items[0].severity is Severity.IMPOSSIBLE
    # The impossible item ranks ahead of every high-cost one.
    sevs = [it.severity for it in report.items]
    assert sevs.index(Severity.IMPOSSIBLE) < sevs.index(Severity.HIGH_COST)
