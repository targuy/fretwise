"""Tests for notation-core validation layer."""

from __future__ import annotations

from fretwise.core.ingest import CompletedScore
from fretwise.core.validate import (
    ValidationLevel,
    ValidationSeverity,
    validate_completed_score,
)
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    duration: float = 1.0,
    tempo: float = 120.0,
    string_hint: int | None = None,
    fret_hint: int | None = None,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=tempo,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=string_hint,
        fret_hint=fret_hint,
        voice_hint=0,
    )


def _completed_score(notes: list[NoteEvent]) -> CompletedScore:
    return CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=notes,
        beats_per_measure=4.0,
    )


def test_validate_completed_score_clean_payload_has_no_issues() -> None:
    score = _completed_score(
        [
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=1.0, string_hint=1, fret_hint=2),
        ]
    )
    report = validate_completed_score(score)

    assert report.checked_notes == 2
    assert report.issues == []
    assert report.has_fatal() is False
    assert report.severity_counts()["fatal"] == 0


def test_validate_completed_score_detects_syntax_and_notation_fatal() -> None:
    score = CompletedScore(
        source_path="",
        source_format="",
        notes=[_note(pitch=64, onset=0.0)],
        beats_per_measure=0.0,
    )
    report = validate_completed_score(score)

    fatal_codes = {
        issue.code
        for issue in report.issues
        if issue.severity == ValidationSeverity.FATAL
    }
    assert "SYN-001" in fatal_codes
    assert "NOT-001" in fatal_codes
    assert report.has_fatal() is True


def test_validate_completed_score_detects_structure_and_instrumental_issues() -> None:
    score = _completed_score(
        [
            _note(pitch=64, onset=1.0, duration=1.0, string_hint=1, fret_hint=0),
            _note(pitch=64, onset=0.5, duration=-0.5, string_hint=9, fret_hint=0),
            _note(pitch=64, onset=2.0, duration=1.0, string_hint=2, fret_hint=0),
            _note(pitch=64, onset=3.0, duration=1.0, fret_hint=3),
        ]
    )
    report = validate_completed_score(score)

    codes = {issue.code for issue in report.issues}
    assert "STR-001" in codes
    assert "STR-002" in codes
    assert "INS-001" in codes
    assert "INS-003" in codes
    assert "INS-004" in codes


def test_validation_report_to_dict_contains_summary() -> None:
    score = _completed_score([_note(pitch=200, onset=0.0)])
    report = validate_completed_score(score)
    payload = report.to_dict()

    assert payload["source_path"] == "song.gp"
    assert payload["source_format"] == "gpif"
    assert payload["summary"]["total_issues"] >= 1
    assert isinstance(payload["issues"], list)
    assert payload["issues"][0]["level"] in {level.value for level in ValidationLevel}
