"""Tests for canonical semantic model mapping."""

from __future__ import annotations

from fretwise.core.canonical import RestEvent, completed_to_canonical_score
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
    note_step: str | None = None,
    note_accidental: str | None = None,
    note_octave: int | None = None,
    measure_index: int | None = None,
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
        note_step=note_step,
        note_accidental=note_accidental,
        note_octave=note_octave,
        measure_index=measure_index,
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
    events = measures[0].voices[0].events
    assert len([event for event in events if not isinstance(event, RestEvent)]) == 2
    rests = [event for event in events if isinstance(event, RestEvent)]
    assert len(rests) == 1
    assert abs(rests[0].duration - 2.0) < 1e-6
    assert abs(sum(rest.duration for rest in rests) - 2.0) < 1e-6


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


def test_completed_to_canonical_score_extracts_strum_direction_technique() -> None:
    event = _note(pitch=64, onset=0.0)
    event.strum_direction = "down"
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[event],
    )

    score = completed_to_canonical_score(completed)
    mapped_event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]
    technique_names = {tech.name for tech in mapped_event.techniques}

    assert "strum_down" in technique_names


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


def test_completed_to_canonical_score_injects_internal_measure_rests() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[
            _note(pitch=64, onset=0.0, duration=0.5),
            _note(pitch=66, onset=2.0, duration=0.5),
        ],
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)
    voice_events = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events
    rests = [event for event in voice_events if isinstance(event, RestEvent)]

    assert len(rests) == 2
    assert abs(rests[0].onset - 0.5) < 1e-6
    assert abs(rests[0].duration - 1.5) < 1e-6
    assert abs(rests[1].onset - 2.5) < 1e-6
    assert abs(rests[1].duration - 1.5) < 1e-6


def test_completed_to_canonical_score_emits_full_measure_rest_for_empty_measure() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[
            _note(pitch=64, onset=0.0, duration=1.0),
            _note(pitch=66, onset=8.0, duration=1.0),
        ],
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)
    measures = score.tracks[0].staff_groups[0].staves[0].measures
    assert len(measures) == 3
    middle_measure_events = measures[1].voices[0].events
    assert len(middle_measure_events) == 1
    assert isinstance(middle_measure_events[0], RestEvent)
    assert abs(middle_measure_events[0].onset - 4.0) < 1e-6
    assert abs(middle_measure_events[0].duration - 4.0) < 1e-6


def test_completed_to_canonical_score_prefers_dotted_rest_segments_when_exact() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[
            _note(pitch=64, onset=0.0, duration=0.25),
            _note(pitch=66, onset=2.0, duration=0.25),
        ],
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)
    voice_events = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events
    rests = [event for event in voice_events if isinstance(event, RestEvent)]

    assert len(rests) == 2
    assert abs(rests[0].onset - 0.25) < 1e-6
    assert abs(rests[0].duration - 1.75) < 1e-6
    assert abs(rests[1].onset - 2.25) < 1e-6
    assert abs(rests[1].duration - 1.75) < 1e-6


def test_completed_to_canonical_score_maps_chord_marker_to_layout_hint() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[_note(pitch=64, onset=0.0, duration=1.0)],
        beats_per_measure=4.0,
        chord_markers={"0.000000": "A5"},
    )

    score = completed_to_canonical_score(completed)
    event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]
    chord_hints = [hint for hint in event.layout_hints if hint.key == "chord_name"]

    assert len(chord_hints) == 1
    assert chord_hints[0].value == "A5"


def test_completed_to_canonical_score_maps_note_spelling_layout_hints() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[
            _note(
                pitch=61,
                onset=0.0,
                duration=1.0,
                note_step="C",
                note_accidental="sharp",
                note_octave=5,
            )
        ],
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)
    event = score.tracks[0].staff_groups[0].staves[0].measures[0].voices[0].events[0]
    hints = {hint.key: hint.value for hint in event.layout_hints}

    assert hints.get("pitch_step") == "C"
    assert hints.get("pitch_accidental") == "sharp"
    assert hints.get("pitch_octave") == "5"


def test_completed_to_canonical_score_prefers_source_measure_index_when_present() -> None:
    completed = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[
            _note(
                pitch=64,
                onset=4.0,
                duration=1.0,
                measure_index=5,
            )
        ],
        beats_per_measure=4.0,
    )

    score = completed_to_canonical_score(completed)
    measures = score.tracks[0].staff_groups[0].staves[0].measures

    assert len(measures) == 5
    assert measures[-1].number == 5
    note_events = [e for e in measures[-1].voices[0].events if not isinstance(e, RestEvent)]
    assert len(note_events) == 1
