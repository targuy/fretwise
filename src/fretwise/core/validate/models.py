"""Validation models for notation-core hardening."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any


class ValidationLevel(StrEnum):
    """Validation layer identifier."""

    SYNTAX = "syntax"
    STRUCTURE = "structure"
    NOTATION = "notation"
    MUSICAL = "musical"
    INSTRUMENTAL = "instrumental"


class ValidationSeverity(StrEnum):
    """Issue severity scale."""

    FATAL = "fatal"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ValidationIssue:
    """One traceable validation issue."""

    code: str
    level: ValidationLevel
    severity: ValidationSeverity
    message: str
    note_index: int | None = None
    context: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Serialize issue to a stable dict."""
        data = asdict(self)
        data["level"] = self.level.value
        data["severity"] = self.severity.value
        return data


@dataclass
class ValidationReport:
    """Diffable validation report for one score."""

    source_path: str
    source_format: str
    checked_notes: int
    issues: list[ValidationIssue] = field(default_factory=list)

    def add(self, issue: ValidationIssue) -> None:
        """Append one issue."""
        self.issues.append(issue)

    def by_level(self, level: ValidationLevel) -> list[ValidationIssue]:
        """Return all issues for one validation level."""
        return [issue for issue in self.issues if issue.level == level]

    def has_fatal(self) -> bool:
        """Return True when at least one fatal issue exists."""
        return any(issue.severity == ValidationSeverity.FATAL for issue in self.issues)

    def severity_counts(self) -> dict[str, int]:
        """Return issue counts by severity string."""
        result = {severity.value: 0 for severity in ValidationSeverity}
        for issue in self.issues:
            result[issue.severity.value] += 1
        return result

    def to_dict(self) -> dict[str, Any]:
        """Serialize report to a stable dict."""
        issues = [issue.to_dict() for issue in self.issues]
        return {
            "source_path": self.source_path,
            "source_format": self.source_format,
            "checked_notes": self.checked_notes,
            "summary": {
                "total_issues": len(issues),
                "fatal": self.severity_counts()["fatal"],
                "high": self.severity_counts()["high"],
                "medium": self.severity_counts()["medium"],
                "low": self.severity_counts()["low"],
            },
            "issues": issues,
        }
