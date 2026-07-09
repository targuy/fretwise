"""Convert unified-schema records to FingeredNote / NoteSequence / FingeredChord.

This is the bridge between the harvester's unified JSON format and the
project's ML data types defined in src/dataset/schema.py.
"""
from __future__ import annotations

from typing import Any

from fretwise.dataset.data_schema.schema import (
    Finger,
    FingeredChord,
    FingeredNote,
    NoteSequence,
    Technique,
)

_LH_TO_FINGER: dict[str, Finger] = {
    "open": Finger.NONE,
    "thumb": Finger.THUMB,
    "index": Finger.INDEX,
    "middle": Finger.MIDDLE,
    "ring": Finger.RING,
    "pinky": Finger.PINKY,
}

_TECHNIQUE_MAP: dict[str, Technique] = {
    "hammer_on": Technique.HAMMER_ON,
    "hammer": Technique.HAMMER_ON,
    "pull_off": Technique.PULL_OFF,
    "pull": Technique.PULL_OFF,
    "slide": Technique.SLIDE,
    "slide_up": Technique.SLIDE,
    "slide_down": Technique.SLIDE,
    "bend": Technique.BEND,
    "vibrato": Technique.VIBRATO,
    "tap": Technique.TAP,
    "harmonic": Technique.HARMONIC,
    "barre": Technique.BARRE,
}

_SPN_TO_MIDI: dict[str, int] = {}
_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
_FLAT_NAMES = {"Db": 1, "Eb": 3, "Fb": 4, "Gb": 6, "Ab": 8, "Bb": 10, "Cb": 11}
for _oct in range(-1, 10):
    for _i, _name in enumerate(_NOTE_NAMES):
        _SPN_TO_MIDI[f"{_name}{_oct}"] = (_oct + 1) * 12 + _i
    for _flat, _semi in _FLAT_NAMES.items():
        _SPN_TO_MIDI[f"{_flat}{_oct}"] = (_oct + 1) * 12 + _semi


def _spn_to_midi(spn: str) -> int | None:
    return _SPN_TO_MIDI.get(spn)


def _tuning_to_midi(tuning_spn: list[str]) -> list[int]:
    """Convert SPN tuning list (low-to-high) to MIDI pitch list (high-to-low).

    Unified schema stores tuning low-to-high: ["E2", "A2", "D3", "G3", "B3", "E4"]
    Our NoteSequence stores tuning high-to-low: [64, 59, 55, 50, 45, 40]
    """
    midi_low_to_high = []
    for spn in tuning_spn:
        m = _spn_to_midi(spn)
        if m is not None:
            midi_low_to_high.append(m)
        else:
            midi_low_to_high.append(0)
    return list(reversed(midi_low_to_high))


def _pick_technique(techniques: list[str]) -> Technique:
    for t in techniques:
        mapped = _TECHNIQUE_MAP.get(t)
        if mapped is not None:
            return mapped
    return Technique.NORMAL


def unified_note_to_fingered(note: dict[str, Any]) -> FingeredNote | None:
    """Convert a single unified-schema note dict to FingeredNote.

    Returns None if the note lacks required string/fret information.
    """
    string = note.get("string")
    fret = note.get("fret")
    pitch = note.get("pitch_midi")

    if string is None or fret is None:
        return None
    if pitch is None:
        pitch = 0

    lh = note.get("left_hand_finger")
    finger = _LH_TO_FINGER.get(lh or "", Finger.NONE)

    techniques = note.get("techniques") or []
    technique = _pick_technique(techniques)

    return FingeredNote(
        string=int(string),
        fret=int(fret),
        finger=finger,
        midi_pitch=int(pitch),
        duration=1.0,
        technique=technique,
    )


def unified_record_to_sequences(record: dict[str, Any]) -> list[NoteSequence]:
    """Convert one unified-schema record to a list of NoteSequences (one per track)."""
    sequences = []
    source_path = record.get("metadata", {}).get("source_path") or record.get("metadata", {}).get("source_file", "")
    source_format = record.get("metadata", {}).get("source_format", "")
    tempo = record.get("metadata", {}).get("tempo_bpm") or 120

    for track in record.get("tracks", []):
        if track.get("is_drum"):
            continue
        if track.get("instrument") not in ("guitar", None):
            continue

        tuning_spn = track.get("tuning") or ["E2", "A2", "D3", "G3", "B3", "E4"]
        tuning_midi = _tuning_to_midi(tuning_spn)

        notes: list[FingeredNote] = []
        for event in track.get("events", []):
            if event.get("type") == "rest":
                continue

            duration = event.get("duration_beats", 1.0)

            for note_dict in event.get("notes", []):
                if note_dict.get("tied_to_previous"):
                    continue
                fn = unified_note_to_fingered(note_dict)
                if fn is not None:
                    fn.duration = float(duration)
                    notes.append(fn)

        if notes:
            sequences.append(NoteSequence(
                notes=notes,
                tempo=int(tempo),
                tuning=tuning_midi,
                source_file=str(source_path),
                source_type=str(source_format),
            ))

    return sequences


def unified_chord_diagram_to_fingered(
    diagram: dict[str, Any], chord_name: str = "", source: str = "",
) -> FingeredChord | None:
    """Convert a unified chord_diagram dict to FingeredChord."""
    frets_raw = diagram.get("frets", [])
    fingers_raw = diagram.get("fingers", [])
    base_fret = int(diagram.get("base_fret", 1) or 1)

    if not frets_raw:
        return None

    strings: list[int | None] = []
    for f in frets_raw:
        if f is None or f in ("x", "X", -1):
            strings.append(None)
        else:
            strings.append(int(f))

    while len(strings) < 6:
        strings.append(None)
    strings = strings[:6]

    fingers: list[Finger | None] = []
    for f in fingers_raw:
        if f is None:
            fingers.append(None)
        elif isinstance(f, str):
            fingers.append(_LH_TO_FINGER.get(f, None))
        elif isinstance(f, int):
            if f == 0:
                fingers.append(None)
            else:
                finger_map = {1: Finger.INDEX, 2: Finger.MIDDLE, 3: Finger.RING, 4: Finger.PINKY, 5: Finger.THUMB}
                fingers.append(finger_map.get(f))
        else:
            fingers.append(None)

    while len(fingers) < 6:
        fingers.append(None)
    fingers = fingers[:6]

    barres = diagram.get("barres", [])
    is_barre = bool(barres)

    name = diagram.get("name") or chord_name or ""

    return FingeredChord(
        name=name,
        strings=strings,
        fingers=fingers,
        position=base_fret,
        is_barre=is_barre,
        source=source,
    )


def extract_chords_from_record(record: dict[str, Any]) -> list[FingeredChord]:
    """Extract all chord diagrams from a unified record as FingeredChords."""
    chords = []
    source = record.get("metadata", {}).get("source_file", "")
    for track in record.get("tracks", []):
        for event in track.get("events", []):
            diagram = event.get("chord_diagram")
            if diagram is not None:
                chord = unified_chord_diagram_to_fingered(
                    diagram, chord_name=event.get("chord_symbol", ""), source=source,
                )
                if chord is not None:
                    chords.append(chord)
    return chords
