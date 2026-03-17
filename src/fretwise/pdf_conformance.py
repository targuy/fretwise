"""Shared PDF conformance reporting contract for CLI and web integrations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from enum import StrEnum


class ConformanceScope(StrEnum):
    """Scope of the reported issue count."""

    ENGINE = "engine"
    SHADOW = "shadow"


@dataclass(frozen=True)
class PdfConformanceReport:
    """Portable PDF conformance report payload."""

    engine: str
    issue_count: int
    scope: ConformanceScope
    shadow_engine: str | None = None
    shadow_failed: bool = False

    def to_dict(self) -> dict[str, object]:
        return {
            "engine": self.engine,
            "issue_count": max(0, int(self.issue_count)),
            "scope": self.scope.value,
            "shadow_engine": self.shadow_engine,
            "shadow_failed": bool(self.shadow_failed),
        }

    def to_header_value(self) -> str:
        """Serialize report for HTTP headers."""
        return json.dumps(self.to_dict(), separators=(",", ":"), ensure_ascii=True)


def core_pdf_conformance_report(issue_count: int) -> PdfConformanceReport:
    """Build report for direct core PDF export."""
    return PdfConformanceReport(
        engine="core",
        issue_count=max(0, int(issue_count)),
        scope=ConformanceScope.ENGINE,
    )


def legacy_shadow_pdf_conformance_report(
    shadow_issue_count: int, *, shadow_failed: bool
) -> PdfConformanceReport:
    """Build report for legacy PDF export shadowed by core checks."""
    return PdfConformanceReport(
        engine="legacy",
        issue_count=max(0, int(shadow_issue_count)),
        scope=ConformanceScope.SHADOW,
        shadow_engine="core",
        shadow_failed=shadow_failed,
    )

