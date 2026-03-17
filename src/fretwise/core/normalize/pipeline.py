"""Normalization pipeline: RawScore -> NormalizedScore."""

from __future__ import annotations

from dataclasses import replace

from fretwise.core.ingest.models import NormalizationLog, NormalizedScore, RawScore
from fretwise.models import NoteEvent


def normalize_raw_score(raw_score: RawScore) -> NormalizedScore:
    """Normalize parser output without rewriting musical content."""
    log = NormalizationLog()
    normalized_notes: list[NoteEvent] = []

    # Rule N-001: voice_hint must be explicit (legacy None -> 0).
    for note_index, note in enumerate(raw_score.notes):
        normalized_note = note
        if note.voice_hint is None:
            normalized_note = replace(note, voice_hint=0)
            log.add(
                rule_id="N-001.voice_hint.default_zero",
                message="voice_hint None normalized to 0.",
                note_index=note_index,
                before="None",
                after="0",
            )
        normalized_notes.append(normalized_note)

    # Rule N-002: deterministic ordering by onset then voice.
    indexed_notes = list(enumerate(normalized_notes))
    sorted_indexed_notes = sorted(
        indexed_notes,
        key=lambda item: (
            item[1].onset,
            item[1].voice_hint if item[1].voice_hint is not None else 0,
            item[0],
        ),
    )
    reordered = any(
        old_index != new_index
        for new_index, (old_index, _n) in enumerate(sorted_indexed_notes)
    )
    if reordered:
        log.add(
            rule_id="N-002.order.by_onset_voice",
            message="Notes reordered by onset/voice for deterministic downstream layout.",
        )

    index_map = {
        old_index: new_index
        for new_index, (old_index, _n) in enumerate(sorted_indexed_notes)
    }
    normalized_trace_map = raw_score.source_trace_map.remap_indices(index_map)

    return NormalizedScore(
        source_path=raw_score.source_path,
        source_format=raw_score.source_format,
        notes=[note for _old_index, note in sorted_indexed_notes],
        track_name=raw_score.track_name,
        beats_per_measure=raw_score.beats_per_measure,
        section_markers=dict(raw_score.section_markers),
        chord_markers=dict(raw_score.chord_markers),
        chord_diagrams=list(raw_score.chord_diagrams),
        source_trace_map=normalized_trace_map,
        normalization_log=log,
    )
