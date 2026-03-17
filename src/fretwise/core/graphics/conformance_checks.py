"""Conformance checks for render scenes against notation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fretwise.core.graphics.notation_policy import NotationPolicy, RepresentationMode
from fretwise.core.scene import RenderScene


class ConformanceSeverity(StrEnum):
    """Severity level for conformance violations."""

    FATAL = "fatal"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass(frozen=True)
class ConformanceIssue:
    """One policy conformance issue."""

    code: str
    severity: ConformanceSeverity
    message: str
    symbol_id: str
    context: dict[str, Any] = field(default_factory=dict)


def check_scene_conformance(
    scene: RenderScene,
    *,
    mode: RepresentationMode,
    policy: NotationPolicy,
) -> list[ConformanceIssue]:
    """Validate that render scene symbol usage complies with policy."""
    issues: list[ConformanceIssue] = []

    for page in scene.document_scene.pages:
        for system in page.systems:
            for staff in system.staves:
                for layer in staff.layer_groups:
                    for recipe in layer.recipe_instances:
                        _maybe_add_issue(
                            issues,
                            policy=policy,
                            mode=mode,
                            symbol_id=recipe.recipe_id,
                            context={"recipe_id": recipe.recipe_id},
                        )
                    for text in layer.text_instances:
                        symbol_id = _text_symbol_id(text.metadata)
                        if symbol_id is None:
                            continue
                        _maybe_add_issue(
                            issues,
                            policy=policy,
                            mode=mode,
                            symbol_id=symbol_id,
                            context={"kind": text.metadata.get("kind"), "text": text.text},
                        )
                    for glyph in layer.glyph_instances:
                        _maybe_add_issue(
                            issues,
                            policy=policy,
                            mode=mode,
                            symbol_id=glyph.glyph_id,
                            context={"glyph_id": glyph.glyph_id},
                        )
    return issues


def _text_symbol_id(metadata: dict[str, Any]) -> str | None:
    kind = str(metadata.get("kind", ""))
    if kind == "note":
        return "tab_digit"
    if kind == "measure_number":
        return "measure_number"
    return None


def _maybe_add_issue(
    issues: list[ConformanceIssue],
    *,
    policy: NotationPolicy,
    mode: RepresentationMode,
    symbol_id: str,
    context: dict[str, Any],
) -> None:
    if policy.is_allowed(mode, symbol_id):
        return
    severity = ConformanceSeverity.HIGH
    if symbol_id in {"measure_number"}:
        severity = ConformanceSeverity.LOW
    issues.append(
        ConformanceIssue(
            code="CONF-001",
            severity=severity,
            message=f"Symbol '{symbol_id}' is not allowed in mode '{mode.value}'.",
            symbol_id=symbol_id,
            context=context,
        )
    )

