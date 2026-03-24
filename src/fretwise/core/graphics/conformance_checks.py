"""Conformance checks for render scenes against notation policy."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fretwise.core.graphics.notation_policy import NotationPolicy, RepresentationMode
from fretwise.core.scene import RenderScene

_HYBRID_ALIGNMENT_X_TOLERANCE = 1.5
_HYBRID_ALIGNMENT_Y_TOLERANCE = 2.0
_HYBRID_MIN_PLANE_GAP = 4.0


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
    issues.extend(_check_rhythm_recipe_consistency(scene))
    issues.extend(_check_duration_dot_consistency(scene))
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
                staff_frame = _recipe_frame(staff, "staff_lines")
                tab_frame = _recipe_frame(staff, "tab_lines")
                if staff_frame is None:
                    issues.append(
                        ConformanceIssue(
                            code="CONF-104",
                            severity=ConformanceSeverity.HIGH,
                            message="Hybrid mode is missing standard staff lines.",
                            symbol_id="staff_lines",
                            context={
                                "page_index": page_index,
                                "system_index": system_index,
                                "staff_index": staff_index,
                            },
                        )
                    )
                if tab_frame is None:
                    issues.append(
                        ConformanceIssue(
                            code="CONF-105",
                            severity=ConformanceSeverity.HIGH,
                            message="Hybrid mode is missing tablature lines.",
                            symbol_id="tab_lines",
                            context={
                                "page_index": page_index,
                                "system_index": system_index,
                                "staff_index": staff_index,
                            },
                        )
                    )
                if staff_frame is not None and tab_frame is not None:
                    _, staff_bottom, _ = staff_frame
                    tab_top, _, _ = tab_frame
                    if staff_bottom + _HYBRID_MIN_PLANE_GAP > tab_top:
                        issues.append(
                            ConformanceIssue(
                                code="CONF-106",
                                severity=ConformanceSeverity.MEDIUM,
                                message="Hybrid standard/tab planes overlap vertically.",
                                symbol_id="standard_tab_planes",
                                context={
                                    "staff_bottom": staff_bottom,
                                    "tab_top": tab_top,
                                    "min_gap": _HYBRID_MIN_PLANE_GAP,
                                    "page_index": page_index,
                                    "system_index": system_index,
                                    "staff_index": staff_index,
                                },
                            )
                        )

                tab_positions: dict[str, tuple[float, float, int | None, float | None, int | None]] = {}
                standard_positions: dict[str, tuple[float, float, bool, float]] = {}
                standard_by_signature: dict[tuple[float, int], tuple[float, float, bool, float]] = {}

                for layer in staff.layer_groups:
                    for text in layer.text_instances:
                        if text.metadata.get("kind") != "note":
                            continue
                        event_id = text.metadata.get("event_id")
                        if event_id is None:
                            continue
                        tab_positions[str(event_id)] = (
                            text.x,
                            text.y,
                            _safe_int(text.metadata.get("tab_string")),
                            _safe_float(text.metadata.get("onset")),
                            _safe_int(text.metadata.get("pitch_notated")),
                        )

                    for glyph in layer.glyph_instances:
                        if glyph.glyph_id != "notehead":
                            continue
                        event_id = glyph.metadata.get("event_id")
                        if event_id is None:
                            continue
                        displaced = str(glyph.metadata.get("head_displaced", "")).lower() == "true"
                        head_dx = _safe_float(glyph.metadata.get("head_dx")) or 0.0
                        standard_entry = (glyph.x, glyph.y, displaced, head_dx)
                        standard_positions[str(event_id)] = standard_entry
                        onset = _safe_float(glyph.metadata.get("onset"))
                        pitch = _safe_int(glyph.metadata.get("pitch_notated"))
                        if onset is not None and pitch is not None:
                            signature = (round(onset, 6), pitch)
                            standard_by_signature.setdefault(signature, standard_entry)

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
                    tab_x, tab_y, tab_string, tab_onset, tab_pitch = tab_positions[event_id]
                    standard_entry = standard_positions.get(event_id)
                    if standard_entry is None and tab_onset is not None and tab_pitch is not None:
                        standard_entry = standard_by_signature.get((round(tab_onset, 6), tab_pitch))
                    if standard_entry is None:
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

                    standard_x, standard_y, head_displaced, head_dx = standard_entry
                    delta = abs(tab_x - standard_x)
                    x_tolerance = _HYBRID_ALIGNMENT_X_TOLERANCE
                    if head_displaced:
                        x_tolerance = max(x_tolerance, abs(head_dx) + 1.5)
                    if delta > x_tolerance:
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
                                    "tolerance": x_tolerance,
                                    "head_displaced": head_displaced,
                                    "head_dx": head_dx,
                                    "page_index": page_index,
                                    "system_index": system_index,
                                    "staff_index": staff_index,
                                },
                            )
                        )
                    if staff_frame is not None:
                        staff_top, staff_bottom, staff_spacing = staff_frame
                        ledger_margin = max(0.0, 7.0 * staff_spacing)
                        if not (
                            staff_top - ledger_margin - _HYBRID_ALIGNMENT_Y_TOLERANCE
                            <= standard_y
                            <= staff_bottom + ledger_margin + _HYBRID_ALIGNMENT_Y_TOLERANCE
                        ):
                            issues.append(
                                ConformanceIssue(
                                    code="CONF-107",
                                    severity=ConformanceSeverity.MEDIUM,
                                    message="Standard notehead is outside standard staff plane.",
                                    symbol_id="notehead",
                                    context={
                                        "event_id": event_id,
                                        "notehead_y": standard_y,
                                        "staff_top": staff_top,
                                        "staff_bottom": staff_bottom,
                                        "ledger_margin": ledger_margin,
                                        "tolerance": _HYBRID_ALIGNMENT_Y_TOLERANCE,
                                        "page_index": page_index,
                                        "system_index": system_index,
                                        "staff_index": staff_index,
                                    },
                                )
                            )
                    if tab_frame is not None:
                        tab_top, tab_bottom, tab_spacing = tab_frame
                        if not (
                            tab_top - _HYBRID_ALIGNMENT_Y_TOLERANCE
                            <= tab_y
                            <= tab_bottom + 4.0 + _HYBRID_ALIGNMENT_Y_TOLERANCE
                        ):
                            issues.append(
                                ConformanceIssue(
                                    code="CONF-108",
                                    severity=ConformanceSeverity.MEDIUM,
                                    message="Tab anchor is outside tablature plane.",
                                    symbol_id="tab_digit",
                                    context={
                                        "event_id": event_id,
                                        "tab_y": tab_y,
                                        "tab_top": tab_top,
                                        "tab_bottom": tab_bottom,
                                        "tolerance": _HYBRID_ALIGNMENT_Y_TOLERANCE,
                                        "page_index": page_index,
                                        "system_index": system_index,
                                        "staff_index": staff_index,
                                    },
                                )
                            )
                        if tab_string is not None:
                            string_num = max(1, min(6, tab_string))
                            expected_y = tab_top + (string_num - 1) * tab_spacing
                            if abs(tab_y - expected_y) > _HYBRID_ALIGNMENT_Y_TOLERANCE:
                                issues.append(
                                ConformanceIssue(
                                    code="CONF-109",
                                    severity=ConformanceSeverity.MEDIUM,
                                    message=(
                                        "Tab anchor is not aligned with declared string row."
                                    ),
                                    symbol_id="tab_digit",
                                    context={
                                            "event_id": event_id,
                                            "tab_string": string_num,
                                            "tab_y": tab_y,
                                            "expected_y": expected_y,
                                            "tolerance": _HYBRID_ALIGNMENT_Y_TOLERANCE,
                                            "page_index": page_index,
                                            "system_index": system_index,
                                            "staff_index": staff_index,
                                        },
                                    )
                                )
    return issues


def _check_rhythm_recipe_consistency(scene: RenderScene) -> list[ConformanceIssue]:
    issues: list[ConformanceIssue] = []

    for page_index, page in enumerate(scene.document_scene.pages):
        for system_index, system in enumerate(page.systems):
            for staff_index, staff in enumerate(system.staves):
                for layer in staff.layer_groups:
                    for recipe in layer.recipe_instances:
                        if recipe.recipe_id == "stem_line":
                            direction = str(
                                recipe.metadata.get(
                                    "direction",
                                    recipe.params.get("direction", ""),
                                )
                            )
                            if direction not in {"up", "down"}:
                                issues.append(
                                    ConformanceIssue(
                                        code="CONF-201",
                                        severity=ConformanceSeverity.HIGH,
                                        message="Stem recipe has invalid direction metadata.",
                                        symbol_id="stem_line",
                                        context={
                                            "direction": direction,
                                            "page_index": page_index,
                                            "system_index": system_index,
                                            "staff_index": staff_index,
                                        },
                                    )
                                )
                                continue

                            y0 = _safe_float(recipe.params.get("y0"))
                            y1 = _safe_float(recipe.params.get("y1"))
                            if y0 is None or y1 is None:
                                continue
                            if direction == "up" and y1 >= y0:
                                issues.append(
                                    ConformanceIssue(
                                        code="CONF-202",
                                        severity=ConformanceSeverity.MEDIUM,
                                        message="Up-stem geometry does not point upward.",
                                        symbol_id="stem_line",
                                        context={
                                            "direction": direction,
                                            "y0": y0,
                                            "y1": y1,
                                            "page_index": page_index,
                                            "system_index": system_index,
                                            "staff_index": staff_index,
                                        },
                                    )
                                )
                            if direction == "down" and y1 <= y0:
                                issues.append(
                                    ConformanceIssue(
                                        code="CONF-202",
                                        severity=ConformanceSeverity.MEDIUM,
                                        message="Down-stem geometry does not point downward.",
                                        symbol_id="stem_line",
                                        context={
                                            "direction": direction,
                                            "y0": y0,
                                            "y1": y1,
                                            "page_index": page_index,
                                            "system_index": system_index,
                                            "staff_index": staff_index,
                                        },
                                    )
                                )

                        if recipe.recipe_id in {"beam_group", "flag_stack"}:
                            direction = str(recipe.params.get("direction", ""))
                            if direction not in {"up", "down"}:
                                issues.append(
                                    ConformanceIssue(
                                        code="CONF-203",
                                        severity=ConformanceSeverity.HIGH,
                                        message=(
                                            f"{recipe.recipe_id} recipe has invalid direction "
                                            "parameter."
                                        ),
                                        symbol_id=recipe.recipe_id,
                                        context={
                                            "direction": direction,
                                            "page_index": page_index,
                                            "system_index": system_index,
                                            "staff_index": staff_index,
                                        },
                                    )
                                )
                                continue
                            if recipe.recipe_id == "beam_group":
                                level = _safe_int(recipe.params.get("level"))
                                if level is None or level < 1:
                                    issues.append(
                                        ConformanceIssue(
                                            code="CONF-204",
                                            severity=ConformanceSeverity.MEDIUM,
                                            message="beam_group recipe level must be >= 1.",
                                            symbol_id="beam_group",
                                            context={
                                                "level": recipe.params.get("level"),
                                                "page_index": page_index,
                                                "system_index": system_index,
                                                "staff_index": staff_index,
                                            },
                                        )
                                    )
                            if recipe.recipe_id == "flag_stack":
                                count = _safe_int(recipe.params.get("count"))
                                if count is None or count < 1:
                                    issues.append(
                                        ConformanceIssue(
                                            code="CONF-205",
                                            severity=ConformanceSeverity.MEDIUM,
                                            message="flag_stack recipe count must be >= 1.",
                                            symbol_id="flag_stack",
                                            context={
                                                "count": recipe.params.get("count"),
                                                "page_index": page_index,
                                                "system_index": system_index,
                                                "staff_index": staff_index,
                                            },
                                        )
                                    )
    return issues


def _check_duration_dot_consistency(scene: RenderScene) -> list[ConformanceIssue]:
    issues: list[ConformanceIssue] = []
    for page_index, page in enumerate(scene.document_scene.pages):
        for system_index, system in enumerate(page.systems):
            for staff_index, staff in enumerate(system.staves):
                for layer in staff.layer_groups:
                    for glyph in layer.glyph_instances:
                        if glyph.glyph_id not in {"notehead", "rest"}:
                            continue
                        duration = _safe_float(glyph.metadata.get("duration"))
                        if duration is None:
                            continue
                        expected_dots = _duration_dot_count(duration)
                        dot_count = _safe_int(glyph.metadata.get("dot_count"))
                        if dot_count is None:
                            dot_count = 0
                        if str(glyph.metadata.get("is_measure_rest", "")).lower() == "true":
                            expected_dots = 0
                        if dot_count != expected_dots:
                            issues.append(
                                ConformanceIssue(
                                    code="CONF-301",
                                    severity=ConformanceSeverity.LOW,
                                    message=(
                                        "Glyph dotted-duration metadata is inconsistent with "
                                        "its duration."
                                    ),
                                    symbol_id=glyph.glyph_id,
                                    context={
                                        "duration": duration,
                                        "dot_count": dot_count,
                                        "expected_dot_count": expected_dots,
                                        "event_id": glyph.metadata.get("event_id"),
                                        "page_index": page_index,
                                        "system_index": system_index,
                                        "staff_index": staff_index,
                                    },
                                )
                            )
    return issues


def _recipe_frame(staff: Any, recipe_id: str) -> tuple[float, float, float] | None:
    for layer in staff.layer_groups:
        for recipe in layer.recipe_instances:
            if recipe.recipe_id != recipe_id:
                continue
            y = float(recipe.params.get("y", 0.0))
            count = int(recipe.params.get("count", 1))
            spacing = float(recipe.params.get("spacing", 16.0))
            bottom = y + max(0, count - 1) * spacing
            return (y, bottom, spacing)
    return None


def _safe_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _safe_float(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _duration_dot_count(duration: float) -> int:
    known_bases = (8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625)
    tol = 0.01
    for base in known_bases:
        if abs(duration - base * 1.5) <= tol:
            return 1
        if abs(duration - base * 1.75) <= tol:
            return 2
    return 0
