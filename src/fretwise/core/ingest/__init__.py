"""Ingestion and parsing boundary layer."""

from fretwise.core.ingest.adapters import legacy_parse_to_raw_score
from fretwise.core.ingest.models import (
    CompletedScore,
    CompletionLog,
    CompletionStep,
    CorrectedCandidateScore,
    CorrectionDiff,
    NormalizationLog,
    NormalizationStep,
    NormalizedScore,
    RawScore,
    SourceTrace,
    SourceTraceMap,
)

__all__ = [
    "CompletedScore",
    "CompletionLog",
    "CompletionStep",
    "CorrectedCandidateScore",
    "CorrectionDiff",
    "NormalizationLog",
    "NormalizationStep",
    "NormalizedScore",
    "RawScore",
    "SourceTrace",
    "SourceTraceMap",
    "legacy_parse_to_raw_score",
]
