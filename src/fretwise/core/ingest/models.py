"""Input-phase models for the notation-core pipeline."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from fretwise.models import ChordDiagram, NoteEvent


@dataclass(frozen=True)
class SourceTrace:
    """Source coordinates for one logical note event."""

    source_path: str
    location: str
    track_name: str = ""
    measure_index: int | None = None
    voice_index: int | None = None
    beat_index: int | None = None
    note_index: int | None = None


@dataclass
class SourceTraceMap:
    """Index-based traceability map for note events."""

    by_note_index: dict[int, SourceTrace] = field(default_factory=dict)
    extensions: dict[str, Any] = field(default_factory=dict)

    def bind(self, note_index: int, trace: SourceTrace) -> None:
        """Attach a source trace to a note index."""
        self.by_note_index[note_index] = trace

    def get(self, note_index: int) -> SourceTrace | None:
        """Return the source trace for a note index, if available."""
        return self.by_note_index.get(note_index)

    def remap_indices(self, index_map: Mapping[int, int]) -> SourceTraceMap:
        """Return a new map using remapped note indices."""
        remapped = SourceTraceMap(extensions=dict(self.extensions))
        for old_index, trace in self.by_note_index.items():
            new_index = index_map.get(old_index)
            if new_index is not None:
                remapped.by_note_index[new_index] = trace
        return remapped

    def copy(self) -> SourceTraceMap:
        """Return a shallow copy suitable for phase handoff."""
        return SourceTraceMap(
            by_note_index=dict(self.by_note_index),
            extensions=dict(self.extensions),
        )

    def __len__(self) -> int:
        return len(self.by_note_index)


@dataclass(frozen=True)
class NormalizationStep:
    """One normalized transformation record."""

    rule_id: str
    message: str
    note_index: int | None = None
    before: str | None = None
    after: str | None = None


@dataclass
class NormalizationLog:
    """Append-only normalization trace."""

    steps: list[NormalizationStep] = field(default_factory=list)

    def add(
        self,
        *,
        rule_id: str,
        message: str,
        note_index: int | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Append one normalization step."""
        self.steps.append(
            NormalizationStep(
                rule_id=rule_id,
                message=message,
                note_index=note_index,
                before=before,
                after=after,
            )
        )


@dataclass(frozen=True)
class CompletionStep:
    """One prudent completion record."""

    inference_id: str
    message: str
    note_index: int | None = None
    before: str | None = None
    after: str | None = None


@dataclass
class CompletionLog:
    """Append-only completion trace."""

    steps: list[CompletionStep] = field(default_factory=list)

    def add(
        self,
        *,
        inference_id: str,
        message: str,
        note_index: int | None = None,
        before: str | None = None,
        after: str | None = None,
    ) -> None:
        """Append one completion step."""
        self.steps.append(
            CompletionStep(
                inference_id=inference_id,
                message=message,
                note_index=note_index,
                before=before,
                after=after,
            )
        )


@dataclass
class RawScore:
    """Cross-format raw extraction payload.

    RawScore is a transport envelope. It preserves parse output with minimal
    transformation and carries unknown fields for forward compatibility.
    """

    source_path: str
    source_format: str
    notes: list[NoteEvent]
    track_name: str = ""
    beats_per_measure: float = 4.0
    time_denominator: int = 4
    key_signature_fifths: int = 0
    has_anacrusis: bool = False
    section_markers: dict[int, str] = field(default_factory=dict)
    chord_markers: dict[str, str] = field(default_factory=dict)
    chord_diagrams: list[ChordDiagram] = field(default_factory=list)
    unknown_fields: dict[str, Any] = field(default_factory=dict)
    source_trace_map: SourceTraceMap = field(default_factory=SourceTraceMap)


@dataclass
class NormalizedScore:
    """Normalized score after cross-format harmonization."""

    source_path: str
    source_format: str
    notes: list[NoteEvent]
    track_name: str = ""
    beats_per_measure: float = 4.0
    time_denominator: int = 4
    key_signature_fifths: int = 0
    has_anacrusis: bool = False
    section_markers: dict[int, str] = field(default_factory=dict)
    chord_markers: dict[str, str] = field(default_factory=dict)
    chord_diagrams: list[ChordDiagram] = field(default_factory=list)
    source_trace_map: SourceTraceMap = field(default_factory=SourceTraceMap)
    normalization_log: NormalizationLog = field(default_factory=NormalizationLog)


@dataclass
class CompletedScore:
    """Completed score after prudent safe inferences."""

    source_path: str
    source_format: str
    notes: list[NoteEvent]
    track_name: str = ""
    beats_per_measure: float = 4.0
    time_denominator: int = 4
    key_signature_fifths: int = 0
    has_anacrusis: bool = False
    section_markers: dict[int, str] = field(default_factory=dict)
    chord_markers: dict[str, str] = field(default_factory=dict)
    chord_diagrams: list[ChordDiagram] = field(default_factory=list)
    source_trace_map: SourceTraceMap = field(default_factory=SourceTraceMap)
    completion_log: CompletionLog = field(default_factory=CompletionLog)


@dataclass(frozen=True)
class CorrectionDiff:
    """Traceable correction delta for candidate auto-corrections."""

    action: str
    target: str
    before: str | None = None
    after: str | None = None


@dataclass
class CorrectedCandidateScore:
    """Policy-gated corrected candidate derived from CompletedScore."""

    policy_id: str
    base_score: CompletedScore
    corrected_notes: list[NoteEvent]
    correction_diff: list[CorrectionDiff] = field(default_factory=list)
    source_trace_map: SourceTraceMap = field(default_factory=SourceTraceMap)
