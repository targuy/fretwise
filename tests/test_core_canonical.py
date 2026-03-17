"""Tests for canonical semantic model mapping."""

from __future__ import annotations

from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.ingest import CompletedScore
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    duration: float = 1.0,
    voice_hint: int | None = 0,
    string_hint: int | None = None,
    fret_hint: int | None = None,
    tapping: bool = False,
    let_ring: bool = False,
    palm_muted: bool = False,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=voice_hint,
        string_hint=string_hint,
        fret_hint=fret_hint,
        tapping=tapping,
        let_ring=let_ring,
        palm_muted=palm_muted,
    )


def test_completed_to_canonical_score_builds_basic_structure() -> None:
    completed = CompletedScore(
        source_path="fixtures/song.gp",
        source_format="gpif",
        notes=[_note(pitch=64, onset=0.0), _note(pitch=66, onset=1.0)],
        track_name="Lead",
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)

    assert score.title == "song"
    assert len(score.tracks) == 1
    assert score.tracks[0].name == "Lead"
    measures = score.tracks[0].staff_groups[0].staves[0].measures
    assert len(measures) == 1
    assert measures[0].number == 1
    assert len(measures[0].voices) == 1
    assert len(measures[0].voices[0].events) == 2


def test_completed_to_canonical_score_preserves_tab_info() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )

    score = completed_to_canonical_score(completed)
    event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]

    assert event.tab_info is not None
    assert event.tab_info.string == 1
    assert event.tab_info.fret == 0


def test_completed_to_canonical_score_extracts_techniques() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[_note(pitch=64, onset=0.0, tapping=True)],
    )

    score = completed_to_canonical_score(completed)
    event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]
    technique_names = {tech.name for tech in event.techniques}

    assert "tapping" in technique_names


def test_completed_to_canonical_score_extracts_span_techniques() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[_note(pitch=64, onset=0.0, let_ring=True, palm_muted=True)],
    )

    score = completed_to_canonical_score(completed)
    event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]
    technique_names = {tech.name for tech in event.techniques}

    assert "let_ring" in technique_names
    assert "palm_mute" in technique_names


def test_completed_to_canonical_score_handles_empty_input() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[],
        beats_per_measure=0.0,
    )
    score = completed_to_canonical_score(completed)

    assert score.tempo_marks[0].bpm == 120.0
    measures = score.tracks[0].staff_groups[0].staves[0].measures
    assert measures == []
