"""Mapping from completed input model to canonical semantic model."""

from __future__ import annotations

from pathlib import Path

from fretwise.core.canonical.models import (
    Dynamic,
    Event,
    KeySignature,
    LayoutHint,
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
from fretwise.core.canonical.models import (
    RestEvent as CanonicalRestEvent,
)
from fretwise.core.ingest import CompletedScore
from fretwise.models import NoteEvent as LegacyNoteEvent


def completed_to_canonical_score(completed_score: CompletedScore) -> Score:
    """Convert a completed score into the canonical semantic model."""
    title = Path(completed_score.source_path).stem or "untitled"
    beats_per_measure = _safe_beats_per_measure(completed_score.beats_per_measure)
    time_denominator = getattr(completed_score, "time_denominator", 4)
    time_numerator = int(round(completed_score.beats_per_measure * time_denominator / 4.0))
    time_signature = TimeSignature(numerator=time_numerator, denominator=time_denominator)
    chord_markers_by_onset = _normalize_chord_markers(completed_score.chord_markers)
    measure_number_offset = -1 if completed_score.has_anacrusis else 0

    measures: dict[int, list[tuple[int, CanonicalNoteEvent]]] = {}
    for note_index, note in enumerate(completed_score.notes):
        measure_idx = _measure_index_for_note(note, beats_per_measure=beats_per_measure)
        chord_name = chord_markers_by_onset.get(round(note.onset, 6))
        measures.setdefault(measure_idx, []).append(
            (note_index, _map_note(note_index, note, chord_name=chord_name))
        )

    canonical_measures: list[Measure] = []
    max_measure_idx = max(measures.keys(), default=-1)
    for measure_idx in range(0, max_measure_idx + 1):
        per_voice: dict[int, list[CanonicalNoteEvent]] = {}
        for _note_index, event in measures.get(measure_idx, []):
            per_voice.setdefault(event.voice, []).append(event)
        if not per_voice:
            per_voice[0] = []

        measure_number = measure_idx + 1 + measure_number_offset
        measure_start = measure_idx * beats_per_measure
        measure_end = measure_start + beats_per_measure
        voices = [
            Voice(
                number=voice_number,
                events=_inject_implicit_rests(
                    sorted(events, key=lambda e: e.onset),
                    measure_number=measure_number,
                    voice_number=voice_number,
                    measure_start=measure_start,
                    measure_end=measure_end,
                ),
            )
            for voice_number, events in sorted(per_voice.items(), key=lambda item: item[0])
        ]
        canonical_measures.append(
            Measure(
                number=measure_number,
                time_signature=time_signature,
                voices=voices,
                section_name=completed_score.section_markers.get(measure_number, ""),
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
        key_signature=_fifths_to_key_signature(completed_score.key_signature_fifths),
    )


def _fifths_to_key_signature(fifths: int) -> KeySignature:
    """Convert a circle-of-fifths value to a KeySignature.

    Positive fifths = sharps (e.g. +2 = D major).
    Negative fifths = flats (e.g. -3 = Eb major).
    Zero = C major.
    """
    _SHARP_TONICS = ["C", "G", "D", "A", "E", "B", "F#", "C#"]
    _FLAT_TONICS  = ["C", "F", "Bb", "Eb", "Ab", "Db", "Gb", "Cb"]
    if fifths >= 0:
        tonic = _SHARP_TONICS[min(fifths, len(_SHARP_TONICS) - 1)]
    else:
        tonic = _FLAT_TONICS[min(abs(fifths), len(_FLAT_TONICS) - 1)]
    return KeySignature(tonic=tonic, mode="major", fifths=fifths)


def _measure_index_for_note(note: LegacyNoteEvent, *, beats_per_measure: int) -> int:
    if note.measure_index is not None and note.measure_index > 0:
        return int(note.measure_index) - 1
    return int(note.onset // beats_per_measure)


def _safe_beats_per_measure(beats_per_measure: float) -> int:
    if beats_per_measure <= 0:
        return 4
    return int(round(beats_per_measure))


def _normalize_chord_markers(chord_markers: dict[str, str]) -> dict[float, str]:
    by_onset: dict[float, str] = {}
    for onset_text, chord_name in chord_markers.items():
        name = str(chord_name or "").strip()
        if not name:
            continue
        try:
            onset = round(float(onset_text), 6)
        except (TypeError, ValueError):
            continue
        by_onset[onset] = name
    return by_onset


def _map_note(
    note_index: int,
    note: LegacyNoteEvent,
    *,
    chord_name: str | None = None,
) -> CanonicalNoteEvent:
    techniques: list[Technique] = []
    if note.articulation.value != "normal":
        techniques.append(Technique(name=note.articulation.value))
    if note.tapping:
        techniques.append(Technique(name="tapping"))
    if note.palm_muted:
        techniques.append(Technique(name="palm_mute"))
    if note.let_ring:
        techniques.append(Technique(name="let_ring"))
    if note.bend_value is not None:
        techniques.append(Technique(name="bend", value=str(note.bend_value)))
    if note.strum_direction in {"up", "down"}:
        techniques.append(Technique(name=f"strum_{note.strum_direction}"))
    layout_hints: list[LayoutHint] = []
    if chord_name:
        layout_hints.append(LayoutHint(key="chord_name", value=chord_name))
    if note.note_step:
        layout_hints.append(LayoutHint(key="pitch_step", value=str(note.note_step).upper()))
    if note.note_accidental:
        layout_hints.append(
            LayoutHint(key="pitch_accidental", value=str(note.note_accidental).lower())
        )
    if note.note_octave is not None:
        layout_hints.append(LayoutHint(key="pitch_octave", value=str(note.note_octave)))

    if note.is_tie_dest:
        layout_hints.append(LayoutHint(key="is_tie_dest", value="true"))

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
        pitch_notated=_to_notated_pitch(note),
        pitch_sounding=note.pitch,
        tab_info=tab_info,
        techniques=techniques,
        dynamic=dynamic,
        layout_hints=layout_hints,
    )


def _to_notated_pitch(note: LegacyNoteEvent) -> int:
    # Guitar notation is conventionally written one octave above sounding pitch.
    if note.string_hint is not None:
        return note.pitch + 12
    return note.pitch


def _inject_implicit_rests(
    events: list[CanonicalNoteEvent],
    *,
    measure_number: int,
    voice_number: int,
    measure_start: float,
    measure_end: float,
) -> list[Event]:
    if not events:
        return [
            CanonicalRestEvent(
                event_id=f"r-m{measure_number}-v{voice_number}-0",
                onset=measure_start,
                duration=measure_end - measure_start,
                voice=voice_number,
                layout_hints=[LayoutHint(key="measure_rest", value="true")],
            )
        ]

    timeline: list[Event] = []
    cursor = measure_start
    rest_index = 0
    idx = 0
    tolerance = 1e-6

    while idx < len(events):
        onset = events[idx].onset
        if onset > cursor + tolerance:
            for rest_onset, rest_duration in _split_rest_span(cursor, onset):
                timeline.append(
                    CanonicalRestEvent(
                        event_id=f"r-m{measure_number}-v{voice_number}-{rest_index}",
                        onset=rest_onset,
                        duration=rest_duration,
                        voice=voice_number,
                    )
                )
                rest_index += 1

        cluster_end = cursor
        while idx < len(events) and abs(events[idx].onset - onset) <= tolerance:
            note = events[idx]
            timeline.append(note)
            cluster_end = max(cluster_end, note.onset + note.duration)
            idx += 1
        cursor = max(cursor, cluster_end)

    if measure_end > cursor + tolerance:
        for rest_onset, rest_duration in _split_rest_span(cursor, measure_end):
            timeline.append(
                CanonicalRestEvent(
                    event_id=f"r-m{measure_number}-v{voice_number}-{rest_index}",
                    onset=rest_onset,
                    duration=rest_duration,
                    voice=voice_number,
                )
            )
            rest_index += 1

    return timeline


def _split_rest_span(start: float, end: float) -> list[tuple[float, float]]:
    tolerance = 1e-6
    durations = (
        4.0,
        3.5,
        3.0,
        2.0,
        1.75,
        1.5,
        1.0,
        0.875,
        0.75,
        0.5,
        0.375,
        0.25,
        0.1875,
        0.125,
        0.09375,
        0.0625,
    )
    pieces: list[tuple[float, float]] = []
    cursor = start
    remaining = end - start

    while remaining > tolerance:
        if remaining < durations[-1] + tolerance:
            pieces.append((cursor, remaining))
            break

        next_piece: float | None = None
        for candidate in durations:
            if remaining + tolerance < candidate:
                continue
            next_piece = candidate
            break
        if next_piece is None:
            next_piece = min(durations[-1], remaining)

        pieces.append((cursor, next_piece))
        cursor += next_piece
        remaining = end - cursor

    return pieces
