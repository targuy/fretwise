"""Prudent completion pipeline: NormalizedScore -> CompletedScore."""

from __future__ import annotations

from fretwise.core.ingest.models import CompletedScore, CompletionLog, NormalizedScore


def complete_normalized_score(normalized_score: NormalizedScore) -> CompletedScore:
    """Apply only safe, deterministic completion steps.

    At this stage we intentionally keep completion minimal. The function exists
    so callers can rely on an explicit phase boundary and completion trace.
    """
    completion_log = CompletionLog()
    completion_log.add(
        inference_id="C-000.noop",
        message="No safe completion rule applied.",
    )

    return CompletedScore(
        source_path=normalized_score.source_path,
        source_format=normalized_score.source_format,
        notes=list(normalized_score.notes),
        track_name=normalized_score.track_name,
        beats_per_measure=normalized_score.beats_per_measure,
        time_denominator=normalized_score.time_denominator,
        key_signature_fifths=normalized_score.key_signature_fifths,
        has_anacrusis=normalized_score.has_anacrusis,
        section_markers=dict(normalized_score.section_markers),
        chord_markers=dict(normalized_score.chord_markers),
        chord_diagrams=list(normalized_score.chord_diagrams),
        source_trace_map=normalized_score.source_trace_map.copy(),
        completion_log=completion_log,
    )
