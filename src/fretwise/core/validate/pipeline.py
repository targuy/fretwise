"""Validation pipeline: CompletedScore -> ValidationReport."""

from __future__ import annotations

from fretwise.core.ingest import CompletedScore
from fretwise.core.validate.models import (
    ValidationIssue,
    ValidationLevel,
    ValidationReport,
    ValidationSeverity,
)

_STANDARD_TUNING: dict[int, int] = {
    1: 64,  # E4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40,  # E2
}


def validate_completed_score(completed_score: CompletedScore) -> ValidationReport:
    """Run the five-level validation stack on a completed score."""
    report = ValidationReport(
        source_path=completed_score.source_path,
        source_format=completed_score.source_format,
        checked_notes=len(completed_score.notes),
    )
    _validate_syntax(completed_score, report)
    _validate_structure(completed_score, report)
    _validate_notation(completed_score, report)
    _validate_musical(completed_score, report)
    _validate_instrumental(completed_score, report)
    return report


def _validate_syntax(completed_score: CompletedScore, report: ValidationReport) -> None:
    if not completed_score.source_format.strip():
        report.add(
            ValidationIssue(
                code="SYN-001",
                level=ValidationLevel.SYNTAX,
                severity=ValidationSeverity.FATAL,
                message="source_format is empty.",
            )
        )
    if not completed_score.source_path.strip():
        report.add(
            ValidationIssue(
                code="SYN-002",
                level=ValidationLevel.SYNTAX,
                severity=ValidationSeverity.HIGH,
                message="source_path is empty.",
            )
        )


def _validate_structure(completed_score: CompletedScore, report: ValidationReport) -> None:
    previous_onset: float | None = None
    for note_index, note in enumerate(completed_score.notes):
        if note.duration <= 0:
            report.add(
                ValidationIssue(
                    code="STR-001",
                    level=ValidationLevel.STRUCTURE,
                    severity=ValidationSeverity.HIGH,
                    message="Note duration must be > 0.",
                    note_index=note_index,
                    context={"duration": note.duration},
                )
            )
        if previous_onset is not None and note.onset < previous_onset:
            report.add(
                ValidationIssue(
                    code="STR-002",
                    level=ValidationLevel.STRUCTURE,
                    severity=ValidationSeverity.MEDIUM,
                    message="Notes are not sorted by onset.",
                    note_index=note_index,
                    context={"previous_onset": previous_onset, "onset": note.onset},
                )
            )
        previous_onset = note.onset


def _validate_notation(completed_score: CompletedScore, report: ValidationReport) -> None:
    if completed_score.beats_per_measure <= 0:
        report.add(
            ValidationIssue(
                code="NOT-001",
                level=ValidationLevel.NOTATION,
                severity=ValidationSeverity.FATAL,
                message="beats_per_measure must be > 0.",
                context={"beats_per_measure": completed_score.beats_per_measure},
            )
        )


def _validate_musical(completed_score: CompletedScore, report: ValidationReport) -> None:
    for note_index, note in enumerate(completed_score.notes):
        if note.pitch < 0 or note.pitch > 127:
            report.add(
                ValidationIssue(
                    code="MUS-001",
                    level=ValidationLevel.MUSICAL,
                    severity=ValidationSeverity.HIGH,
                    message="MIDI pitch out of range [0, 127].",
                    note_index=note_index,
                    context={"pitch": note.pitch},
                )
            )
        if note.tempo <= 0:
            report.add(
                ValidationIssue(
                    code="MUS-002",
                    level=ValidationLevel.MUSICAL,
                    severity=ValidationSeverity.MEDIUM,
                    message="Tempo must be > 0.",
                    note_index=note_index,
                    context={"tempo": note.tempo},
                )
            )


def _validate_instrumental(completed_score: CompletedScore, report: ValidationReport) -> None:
    for note_index, note in enumerate(completed_score.notes):
        has_string = note.string_hint is not None
        has_fret = note.fret_hint is not None

        if has_string and has_fret:
            assert note.string_hint is not None
            assert note.fret_hint is not None
            if note.string_hint not in _STANDARD_TUNING:
                report.add(
                    ValidationIssue(
                        code="INS-001",
                        level=ValidationLevel.INSTRUMENTAL,
                        severity=ValidationSeverity.HIGH,
                        message="string_hint must be in [1, 6].",
                        note_index=note_index,
                        context={"string_hint": note.string_hint},
                    )
                )
                continue
            if note.fret_hint < 0:
                report.add(
                    ValidationIssue(
                        code="INS-002",
                        level=ValidationLevel.INSTRUMENTAL,
                        severity=ValidationSeverity.HIGH,
                        message="fret_hint must be >= 0.",
                        note_index=note_index,
                        context={"fret_hint": note.fret_hint},
                    )
                )
                continue

            expected_pitch = _STANDARD_TUNING[note.string_hint] + note.fret_hint
            if expected_pitch != note.pitch:
                report.add(
                    ValidationIssue(
                        code="INS-003",
                        level=ValidationLevel.INSTRUMENTAL,
                        severity=ValidationSeverity.MEDIUM,
                        message="pitch != string_hint + fret_hint under standard tuning.",
                        note_index=note_index,
                        context={
                            "pitch": note.pitch,
                            "string_hint": note.string_hint,
                            "fret_hint": note.fret_hint,
                            "expected_pitch": expected_pitch,
                        },
                    )
                )
            continue

        if has_string != has_fret:
            report.add(
                ValidationIssue(
                    code="INS-004",
                    level=ValidationLevel.INSTRUMENTAL,
                    severity=ValidationSeverity.LOW,
                    message="Partial tab hint (string without fret or fret without string).",
                    note_index=note_index,
                    context={"string_hint": note.string_hint, "fret_hint": note.fret_hint},
                )
            )
