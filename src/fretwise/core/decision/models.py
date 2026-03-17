"""Decision policy and outcome models."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fretwise.core.ingest import CorrectedCandidateScore


class DecisionAction(StrEnum):
    """Allowed decision actions."""

    ACCEPT = "accept"
    ACCEPT_WITH_WARNINGS = "accept_with_warnings"
    AUTO_CORRECT_SAFE = "auto_correct_safe"
    REJECT = "reject"
    REVIEW_REQUIRED = "review_required"


@dataclass(frozen=True)
class DecisionPolicy:
    """Policy thresholds used by the decision stage."""

    policy_id: str = "default"
    max_high_for_accept: int = 0
    require_review_when_high: bool = True
    allow_auto_correct_safe: bool = False
    max_medium_for_auto_correct: int = 0


@dataclass
class DecisionOutcome:
    """Traceable outcome of policy arbitration."""

    action: DecisionAction
    policy_id: str
    issue_counts: dict[str, int]
    reasons: list[str] = field(default_factory=list)
    corrected_candidate_score: CorrectedCandidateScore | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize outcome to a stable dict."""
        return {
            "action": self.action.value,
            "policy_id": self.policy_id,
            "issue_counts": dict(self.issue_counts),
            "reasons": list(self.reasons),
            "has_corrected_candidate": self.corrected_candidate_score is not None,
        }
