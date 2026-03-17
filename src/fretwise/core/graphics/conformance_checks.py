"""Conformance checks for render scenes against notation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fretwise.core.graphics.notation_policy import NotationPolicy, RepresentationMode
from fretwise.core.scene import RenderScene

_HYBRID_ALIGNMENT_X_TOLERANCE = 1.5


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
    if (
        mode == RepresentationMode.STANDARD_TAB
        and policy.metadata.get("standard_tab_alignment_required") == "true"
    ):
        issues.extend(_check_hybrid_alignment(scene))
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


def _check_hybrid_alignment(scene: RenderScene) -> list[ConformanceIssue]:
    issues: list[ConformanceIssue] = []

    for page_index, page in enumerate(scene.document_scene.pages):
        for system_index, system in enumerate(page.systems):
            for staff_index, staff in enumerate(system.staves):
                tab_positions: dict[str, float] = {}
                standard_positions: dict[str, float] = {}

                for layer in staff.layer_groups:
                    for text in layer.text_instances:
                        if text.metadata.get("kind") != "note":
                            continue
                        event_id = text.metadata.get("event_id")
                        if event_id is None:
                            continue
                        tab_positions[str(event_id)] = text.x

                    for glyph in layer.glyph_instances:
                        if glyph.glyph_id != "notehead":
                            continue
                        event_id = glyph.metadata.get("event_id")
                        if event_id is None:
                            continue
                        standard_positions[str(event_id)] = glyph.x

                all_event_ids = set(tab_positions) | set(standard_positions)
                for event_id in sorted(all_event_ids):
                    if event_id not in tab_positions:
                        issues.append(
                            ConformanceIssue(
                                code="CONF-101",
                                severity=ConformanceSeverity.HIGH,
                                message="Hybrid mode note is missing tablature anchor.",
                                symbol_id="tab_digit",
                                context={
                                    "event_id": event_id,
                                    "page_index": page_index,
                                    "system_index": system_index,
                                    "staff_index": staff_index,
                                },
                            )
                        )
                        continue
                    if event_id not in standard_positions:
                        issues.append(
                            ConformanceIssue(
                                code="CONF-102",
                                severity=ConformanceSeverity.HIGH,
                                message="Hybrid mode note is missing standard-note anchor.",
                                symbol_id="notehead",
                                context={
                                    "event_id": event_id,
                                    "page_index": page_index,
                                    "system_index": system_index,
                                    "staff_index": staff_index,
                                },
                            )
                        )
                        continue

                    tab_x = tab_positions[event_id]
                    standard_x = standard_positions[event_id]
                    delta = abs(tab_x - standard_x)
                    if delta > _HYBRID_ALIGNMENT_X_TOLERANCE:
                        issues.append(
                            ConformanceIssue(
                                code="CONF-103",
                                severity=ConformanceSeverity.MEDIUM,
                                message="Hybrid mode note anchors are not horizontally aligned.",
                                symbol_id="standard_tab_alignment",
                                context={
                                    "event_id": event_id,
                                    "tab_x": tab_x,
                                    "standard_x": standard_x,
                                    "delta_x": delta,
                                    "tolerance": _HYBRID_ALIGNMENT_X_TOLERANCE,
                                    "page_index": page_index,
                                    "system_index": system_index,
                                    "staff_index": staff_index,
                                },
                            )
                        )
    return issues
