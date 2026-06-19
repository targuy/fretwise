"""Adapters between legacy parser outputs and the new RawScore envelope."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from fretwise.core.ingest.models import RawScore, SourceTrace, SourceTraceMap
from fretwise.models import ChordDiagram, NoteEvent


def legacy_parse_to_raw_score(
    path: Path,
    *,
    source_format: str,
    events: Sequence[NoteEvent],
    track_name: str = "",
    beats_per_measure: float = 4.0,
    time_denominator: int = 4,
    key_signature_fifths: int = 0,
    has_anacrusis: bool = False,
    section_markers: Mapping[int, str] | None = None,
    chord_markers: Mapping[str, str] | None = None,
    chord_diagrams: Sequence[ChordDiagram] | None = None,
    unknown_fields: Mapping[str, Any] | None = None,
    measure_time_signatures: Mapping[int, tuple[int, int]] | None = None,
) -> RawScore:
    """Build a RawScore from the current parser contract.

    This function is a migration bridge: existing parser adapters can keep
    returning NoteEvent lists while the refactored pipeline consumes RawScore.
    """
    source_trace_map = SourceTraceMap()
    source_path = str(path)
    for note_index, _event in enumerate(events):
        source_trace_map.bind(
            note_index,
            SourceTrace(
                source_path=source_path,
                location=f"events[{note_index}]",
                track_name=track_name,
                note_index=note_index,
            ),
        )

    return RawScore(
        source_path=source_path,
        source_format=source_format,
        notes=list(events),
        track_name=track_name,
        beats_per_measure=beats_per_measure,
        time_denominator=time_denominator,
        key_signature_fifths=key_signature_fifths,
        has_anacrusis=has_anacrusis,
        section_markers=dict(section_markers or {}),
        chord_markers=dict(chord_markers or {}),
        chord_diagrams=list(chord_diagrams or []),
        unknown_fields=dict(unknown_fields or {}),
        source_trace_map=source_trace_map,
        measure_time_signatures=dict(measure_time_signatures or {}),
    )
