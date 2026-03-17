"""Tests for notation-core decision layer."""

from __future__ import annotations

from fretwise.core.decision import (
    DecisionAction,
    DecisionPolicy,
    decide_from_validation,
)
from fretwise.core.ingest import CompletedScore, CorrectedCandidateScore
from fretwise.core.validate import (
    ValidationIssue,
    ValidationLevel,
    ValidationReport,
    ValidationSeverity,
)


def _empty_report() -> ValidationReport:
    return ValidationReport(
        source_path="song.gp",
        source_format="gpif",
        checked_notes=1,
    )


def test_decide_from_validation_accept_on_clean_report() -> None:
    outcome = decide_from_validation(_empty_report())
    assert outcome.action == DecisionAction.ACCEPT
    assert outcome.issue_counts["fatal"] == 0


def test_decide_from_validation_reject_on_fatal() -> None:
    report = _empty_report()
    report.add(
        ValidationIssue(
            code="SYN-001",
            level=ValidationLevel.SYNTAX,
            severity=ValidationSeverity.FATAL,
            message="fatal",
        )
    )
    outcome = decide_from_validation(report)
    assert outcome.action == DecisionAction.REJECT
    assert "fatal" in outcome.reasons[0].lower()


def test_decide_from_validation_review_required_on_high() -> None:
    report = _empty_report()
    report.add(
        ValidationIssue(
            code="INS-001",
            level=ValidationLevel.INSTRUMENTAL,
            severity=ValidationSeverity.HIGH,
            message="high",
        )
    )
    outcome = decide_from_validation(report)
    assert outcome.action == DecisionAction.REVIEW_REQUIRED


def test_decide_from_validation_accept_with_warnings_on_medium_low() -> None:
    report = _empty_report()
    report.add(
        ValidationIssue(
            code="INS-004",
            level=ValidationLevel.INSTRUMENTAL,
            severity=ValidationSeverity.LOW,
            message="low",
        )
    )
    outcome = decide_from_validation(report)
    assert outcome.action == DecisionAction.ACCEPT_WITH_WARNINGS


def test_decide_from_validation_auto_correct_safe_requires_policy_and_candidate() -> None:
    report = _empty_report()
    base_score = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[],
    )
    candidate = CorrectedCandidateScore(
        policy_id="safe",
        base_score=base_score,
        corrected_notes=[],
    )
    policy = DecisionPolicy(
        policy_id="safe",
        allow_auto_correct_safe=True,
        max_medium_for_auto_correct=1,
    )
    outcome = decide_from_validation(
        report,
        policy,
        corrected_candidate_score=candidate,
    )
    assert outcome.action == DecisionAction.AUTO_CORRECT_SAFE
    assert outcome.corrected_candidate_score is not None


def test_decision_outcome_to_dict() -> None:
    outcome = decide_from_validation(_empty_report())
    payload = outcome.to_dict()
    assert payload["action"] == "accept"
    assert payload["policy_id"] == "default"
    assert payload["has_corrected_candidate"] is False
