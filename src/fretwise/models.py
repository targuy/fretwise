"""Core data models for FretWise.

These dataclasses are the shared language between all modules (M1–M6).
They must never be modified without validating the impact on every module.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class Articulation(StrEnum):
    """Musical articulation applied to a note."""

    NORMAL = "normal"
    LEGATO = "legato"
    STACCATO = "staccato"
    SLIDE = "slide"
    HAMMER_ON = "hammer_on"
    PULL_OFF = "pull_off"
    BEND = "bend"
    VIBRATO = "vibrato"


class Dynamic(StrEnum):
    """Dynamic level (loudness) of a note."""

    PP = "pp"
    P = "p"
    MP = "mp"
    MF = "mf"
    F = "f"
    FF = "ff"


class Finger(StrEnum):
    """Left-hand finger used to fret a note."""

    OPEN = "open"
    INDEX = "index"
    MIDDLE = "middle"
    RING = "ring"
    PINKY = "pinky"


@dataclass
class NoteEvent:
    """Atomic unit produced by M1 (Parser).

    Represents a single note in its temporal and musical context.
    The ``string_hint`` and ``fret_hint`` fields carry the corde/fret from
    the source tablature when available (GP format always provides them;
    MusicXML/MIDI may not).

    Attributes:
        pitch: MIDI note number (0–127).
        onset: Position in beats from the beginning of the piece.
        duration: Note duration in beats.
        tempo: Local tempo in BPM at the time this note is played.
        articulation: Musical articulation (default: NORMAL).
        dynamic: Dynamic level (default: MF).
        string_hint: Source string number 1–6, if known from the file.
        fret_hint: Source fret number 0–24, if known from the file.
        let_ring: True when the source score marks this note as "let ring"
            (sustain until next note on the same string).
    """

    pitch: int
    onset: float
    duration: float
    tempo: float
    articulation: Articulation = Articulation.NORMAL
    dynamic: Dynamic = Dynamic.MF
    string_hint: int | None = None
    fret_hint: int | None = None
    voice_hint: int | None = None
    let_ring: bool = False


@dataclass
class FingeringState:
    """A complete fingering choice for a given note.

    Encodes the full physical decision: which string, which fret, which
    finger, and where the hand (wrist) is positioned on the neck.

    Attributes:
        string_num: Guitar string number 1–6 (1 = high e, 6 = low E).
        fret: Fret number 0–24 (0 = open string).
        finger: Left-hand finger pressing the note.
        hand_position: Fret covered by the index finger, i.e. wrist position.
            For an open string this is 1 (conventional minimum position).
    """

    string_num: int
    fret: int
    finger: Finger
    hand_position: int


@dataclass
class FingeringResult:
    """Output of M5 (Optimizer) for a single note.

    Pairs a NoteEvent with the chosen FingeringState and the associated
    cost metadata.  The ``alternatives`` list holds other states ranked
    by ascending cost for inspection and export.

    Attributes:
        note_id: Sequential index of the note in the piece (0-based).
        note_event: The note being fingered.
        state: The chosen (optimal) fingering state.
        cost: Total transition cost assigned by the optimizer.
        alternatives: Other candidate states with their costs, sorted
            ascending.  Empty list if only one state was possible.
    """

    note_id: int
    note_event: NoteEvent
    state: FingeringState
    cost: float
    alternatives: list[tuple[FingeringState, float]] = field(default_factory=list)
