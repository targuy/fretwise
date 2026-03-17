"""Decision pipeline: ValidationReport -> DecisionOutcome."""

from __future__ import annotations

from fretwise.core.decision.models import DecisionAction, DecisionOutcome, DecisionPolicy
from fretwise.core.ingest import CorrectedCandidateScore
from fretwise.core.validate import ValidationReport


def decide_from_validation(
    validation_report: ValidationReport,
    policy: DecisionPolicy | None = None,
    *,
    corrected_candidate_score: CorrectedCandidateScore | None = None,
) -> DecisionOutcome:
    """Apply policy arbitration to validation results."""
    effective_policy = policy or DecisionPolicy()
    issue_counts = validation_report.severity_counts()
    reasons: list[str] = []

    fatal_count = issue_counts["fatal"]
    high_count = issue_counts["high"]
    medium_count = issue_counts["medium"]
    low_count = issue_counts["low"]

    action = DecisionAction.ACCEPT

    if fatal_count > 0:
        action = DecisionAction.REJECT
        reasons.append(f"{fatal_count} fatal issue(s) detected.")
    elif high_count > effective_policy.max_high_for_accept:
        if effective_policy.require_review_when_high:
            action = DecisionAction.REVIEW_REQUIRED
            reasons.append(
                f"{high_count} high issue(s) exceed policy threshold "
                f"{effective_policy.max_high_for_accept}."
            )
        else:
            action = DecisionAction.REJECT
            reasons.append(f"{high_count} high issue(s) exceed reject threshold.")
    elif (
        effective_policy.allow_auto_correct_safe
        and corrected_candidate_score is not None
        and high_count == 0
        and medium_count <= effective_policy.max_medium_for_auto_correct
    ):
        action = DecisionAction.AUTO_CORRECT_SAFE
        reasons.append(
            "Corrected candidate accepted under explicit safe auto-correct policy."
        )
    elif medium_count > 0 or low_count > 0:
        action = DecisionAction.ACCEPT_WITH_WARNINGS
        reasons.append(
            f"{medium_count} medium / {low_count} low issue(s) accepted with warnings."
        )
    else:
        reasons.append("No blocking validation issues.")

    return DecisionOutcome(
        action=action,
        policy_id=effective_policy.policy_id,
        issue_counts=issue_counts,
        reasons=reasons,
        corrected_candidate_score=corrected_candidate_score
        if action == DecisionAction.AUTO_CORRECT_SAFE
        else None,
    )
