"""Mapping from completed input model to canonical semantic model."""

from __future__ import annotations

from pathlib import Path

from fretwise.core.canonical.models import (
    Dynamic,
    KeySignature,
    Measure,
    Score,
    Staff,
    StaffGroup,
    TabInfo,
    Technique,
    TempoMark,
    TimeSignature,
    Track,
    Tuning,
    Voice,
)
from fretwise.core.canonical.models import (
    NoteEvent as CanonicalNoteEvent,
)
from fretwise.core.ingest import CompletedScore
from fretwise.models import NoteEvent as LegacyNoteEvent


def completed_to_canonical_score(completed_score: CompletedScore) -> Score:
    """Convert a completed score into the canonical semantic model."""
    title = Path(completed_score.source_path).stem or "untitled"
    beats_per_measure = _safe_beats_per_measure(completed_score.beats_per_measure)
    time_signature = TimeSignature(numerator=beats_per_measure, denominator=4)

    measures: dict[int, list[tuple[int, CanonicalNoteEvent]]] = {}
    for note_index, note in enumerate(completed_score.notes):
        measure_idx = int(note.onset // beats_per_measure)
        measures.setdefault(measure_idx, []).append(
            (note_index, _map_note(note_index, note))
        )

    canonical_measures: list[Measure] = []
    for measure_idx in sorted(measures.keys()):
        per_voice: dict[int, list[CanonicalNoteEvent]] = {}
        for _note_index, event in measures[measure_idx]:
            per_voice.setdefault(event.voice, []).append(event)

        voices = [
            Voice(number=voice_number, events=sorted(events, key=lambda e: e.onset))
            for voice_number, events in sorted(per_voice.items(), key=lambda item: item[0])
        ]
        canonical_measures.append(
            Measure(
                number=measure_idx + 1,
                time_signature=time_signature,
                voices=voices,
            )
        )

    staff = Staff(staff_id="staff-1", clef="treble", measures=canonical_measures)
    staff_group = StaffGroup(group_id="group-1", name="main", staves=[staff])
    track = Track(
        track_id="track-1",
        name=completed_score.track_name or "Track 1",
        staff_groups=[staff_group],
    )
    first_tempo = completed_score.notes[0].tempo if completed_score.notes else 120.0

    return Score(
        score_id="score-1",
        title=title,
        tracks=[track],
        tempo_marks=[TempoMark(onset=0.0, bpm=first_tempo)],
        key_signature=KeySignature(),
    )


def _safe_beats_per_measure(beats_per_measure: float) -> int:
    if beats_per_measure <= 0:
        return 4
    return int(round(beats_per_measure))


def _map_note(note_index: int, note: LegacyNoteEvent) -> CanonicalNoteEvent:
    techniques: list[Technique] = []
    if note.articulation.value != "normal":
        techniques.append(Technique(name=note.articulation.value))
    if note.tapping:
        techniques.append(Technique(name="tapping"))
    if note.palm_muted:
        techniques.append(Technique(name="palm_muted"))
    if note.bend_value is not None:
        techniques.append(Technique(name="bend", value=str(note.bend_value)))

    tab_info: TabInfo | None = None
    if note.string_hint is not None or note.fret_hint is not None:
        tab_info = TabInfo(
            string=note.string_hint,
            fret=note.fret_hint,
            tuning=Tuning(),
            left_hand_finger=None,
        )

    dynamic = Dynamic(mark=note.dynamic.value)
    voice = note.voice_hint if note.voice_hint is not None else 0
    return CanonicalNoteEvent(
        event_id=f"n{note_index}",
        onset=note.onset,
        duration=note.duration,
        voice=voice,
        pitch_notated=note.pitch,
        pitch_sounding=note.pitch,
        tab_info=tab_info,
        techniques=techniques,
        dynamic=dynamic,
    )
