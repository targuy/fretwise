"""Tests for notation-core input phases (ingest/normalize/complete)."""

from __future__ import annotations

from pathlib import Path

from fretwise.core.complete import complete_normalized_score
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.normalize import normalize_raw_score
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(pitch: int, onset: float, voice_hint: int | None = None) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=voice_hint,
    )


def test_legacy_parse_to_raw_score_keeps_metadata_and_trace() -> None:
    events = [_note(64, 0.0), _note(67, 1.0)]
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=events,
        track_name="Lead Guitar",
        beats_per_measure=3.0,
        section_markers={1: "Intro"},
    )

    assert raw_score.source_path.endswith("song.gp")
    assert raw_score.source_format == "gpif"
    assert raw_score.track_name == "Lead Guitar"
    assert raw_score.beats_per_measure == 3.0
    assert raw_score.section_markers == {1: "Intro"}
    assert len(raw_score.source_trace_map) == 2
    trace = raw_score.source_trace_map.get(1)
    assert trace is not None
    assert trace.location == "events[1]"


def test_normalize_raw_score_sets_voice_hint_and_reorders_deterministically() -> None:
    events = [
        _note(67, 2.0, voice_hint=None),
        _note(64, 1.0, voice_hint=1),
        _note(60, 0.0, voice_hint=0),
    ]
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=events,
    )

    normalized_score = normalize_raw_score(raw_score)

    assert [n.onset for n in normalized_score.notes] == [0.0, 1.0, 2.0]
    assert all(n.voice_hint is not None for n in normalized_score.notes)
    rule_ids = {step.rule_id for step in normalized_score.normalization_log.steps}
    assert "N-001.voice_hint.default_zero" in rule_ids
    assert "N-002.order.by_onset_voice" in rule_ids

    # Note index 0 in normalized output comes from original events[2].
    trace0 = normalized_score.source_trace_map.get(0)
    assert trace0 is not None
    assert trace0.location == "events[2]"


def test_complete_normalized_score_preserves_payload_and_writes_completion_log() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(60, 0.0, voice_hint=0)],
    )
    normalized_score = normalize_raw_score(raw_score)

    completed_score = complete_normalized_score(normalized_score)

    assert completed_score.source_path == normalized_score.source_path
    assert completed_score.source_format == normalized_score.source_format
    assert completed_score.notes == normalized_score.notes
    assert completed_score.source_trace_map.get(0) == normalized_score.source_trace_map.get(0)
    assert len(completed_score.completion_log.steps) == 1
    assert completed_score.completion_log.steps[0].inference_id == "C-000.noop"
