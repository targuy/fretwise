"""Minimal end-to-end notation-core pipeline."""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.core.backends import render_scene_to_svg
from fretwise.core.canonical import Score, completed_to_canonical_score
from fretwise.core.complete import complete_normalized_score
from fretwise.core.decision import DecisionOutcome, DecisionPolicy, decide_from_validation
from fretwise.core.graphics import (
    ConformanceIssue,
    RepresentationMode,
    check_scene_conformance,
    default_notation_policy,
)
from fretwise.core.ingest import CompletedScore, NormalizedScore, RawScore
from fretwise.core.normalize import normalize_raw_score
from fretwise.core.scene import RenderScene, canonical_to_render_scene
from fretwise.core.validate import ValidationReport, validate_completed_score


@dataclass
class CorePipelineResult:
    """Full payload produced by the minimal core pipeline."""

    normalized_score: NormalizedScore
    completed_score: CompletedScore
    validation_report: ValidationReport
    decision_outcome: DecisionOutcome
    canonical_score: Score
    render_scene: RenderScene
    conformance_issues: list[ConformanceIssue]
    svg: str


def run_core_pipeline_from_raw(
    raw_score: RawScore,
    *,
    decision_policy: DecisionPolicy | None = None,
    representation_mode: RepresentationMode = RepresentationMode.TAB,
    track_kind: str = "guitar",
    page_width: float | None = None,
) -> CorePipelineResult:
    """Execute the minimal core chain from raw input to SVG output.

    Args:
        raw_score: The raw extraction payload.
        decision_policy: Optional notation decision policy.
        representation_mode: Standard/tab/hybrid render mode.
        track_kind: Instrument family ("guitar"|"bass"|"drums"|"vocal"|
            "other").  Drives the staff clef and the written-pitch octave
            convention.  Defaults to ``"guitar"`` (legacy behaviour).
        page_width: Optional client viewport width in pixels.  When provided
            the layout engine uses it to determine how many measures fit per
            row, so the note size stays fixed rather than stretching to fill.
    """
    normalized_score = normalize_raw_score(raw_score)
    completed_score = complete_normalized_score(normalized_score)
    validation_report = validate_completed_score(completed_score)
    decision_outcome = decide_from_validation(validation_report, policy=decision_policy)
    canonical_score = completed_to_canonical_score(completed_score, track_kind=track_kind)
    render_scene = canonical_to_render_scene(
        canonical_score,
        mode=representation_mode.value,
        page_width=page_width,
    )
    conformance_issues = check_scene_conformance(
        render_scene,
        mode=representation_mode,
        policy=default_notation_policy(),
    )
    svg = render_scene_to_svg(render_scene)
    return CorePipelineResult(
        normalized_score=normalized_score,
        completed_score=completed_score,
        validation_report=validation_report,
        decision_outcome=decision_outcome,
        canonical_score=canonical_score,
        render_scene=render_scene,
        conformance_issues=conformance_issues,
        svg=svg,
    )
