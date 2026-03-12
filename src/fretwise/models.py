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
    WIDE_VIBRATO = "wide_vibrato"
    HARMONIC = "harmonic"
    TAPPING = "tapping"
    MUTED = "muted"
    TREMOLO = "tremolo"


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

    # ── Bend ──────────────────────────────────────────────────────────────────
    # bend_value: max bend in semitones (0.5=half step, 1.0=whole, 1.5, 2.0)
    # bend_type: "normal" | "release" | "pre_bend" | "pre_bend_release" |
    #            "unison" | "grace" | None
    bend_value: float | None = None
    bend_type: str | None = None

    # ── Slide ─────────────────────────────────────────────────────────────────
    # slide_type: "legato" (destination not re-struck) |
    #             "shift"  (destination IS re-struck) |
    #             "slide_in_above" | "slide_in_below" |
    #             "slide_out_up" | "slide_out_down" | None
    slide_type: str | None = None

    # ── Vibrato ───────────────────────────────────────────────────────────────
    vibrato_wide: bool = False          # wide vibrato (larger amplitude)

    # ── Harmonics ─────────────────────────────────────────────────────────────
    # harmonic_type: "natural" | "pinch" | "harp" | "artificial" | None
    harmonic_type: str | None = None
    harmonic_fret: int | None = None    # overtone fret (natural harmonic)

    # ── Performance modifiers ─────────────────────────────────────────────────
    muted: bool = False                 # x note — percussive, no clear pitch
    palm_muted: bool = False            # P.M. — pick-hand palm rests on strings
    tapping: bool = False               # T — pick-hand tap on fretboard
    accent: bool = False                # > accent mark
    accent_strong: bool = False         # >> heavy accent
    tremolo_picking: bool = False       # rapid continuous alternate picking


# Bend type string constants (used in NoteEvent.bend_type)
class BendType:
    NORMAL = "normal"
    RELEASE = "release"
    PRE_BEND = "pre_bend"
    PRE_BEND_RELEASE = "pre_bend_release"
    UNISON = "unison"
    GRACE = "grace"


# Slide type string constants (used in NoteEvent.slide_type)
class SlideType:
    LEGATO = "legato"
    SHIFT = "shift"
    SLIDE_IN_ABOVE = "slide_in_above"
    SLIDE_IN_BELOW = "slide_in_below"
    SLIDE_OUT_UP = "slide_out_up"
    SLIDE_OUT_DOWN = "slide_out_down"


# Harmonic type string constants (used in NoteEvent.harmonic_type)
class HarmonicType:
    NATURAL = "natural"
    PINCH = "pinch"
    HARP = "harp"
    ARTIFICIAL = "artificial"


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


@dataclass
class ChordDiagram:
    """Chord diagram extracted from the source GP file.

    Represents a chord fingering diagram (box diagram) as stored in the
    DiagramCollection of a Guitar Pro file.

    Attributes:
        name: Chord name (e.g. "Am", "F#m7", "Dsus2").
        string_count: Number of strings shown (6 for standard guitar).
        base_fret: If 0, diagram starts at fret 1.  If >0, the leftmost
            fret column corresponds to this fret number (shown as a Roman
            numeral or Arabic number beside the diagram).
        frets: Fret pressed per string. Index 0 = string 1 (high e),
            index 5 = string 6 (low E).  -1 = muted (X), 0 = open (O).
        source_id: Original integer id in the DiagramCollection (for
            matching beat-level chord references).
        fingers: Finger number per string (same indexing as frets).
            0 = unspecified, 1 = index, 2 = middle, 3 = ring, 4 = pinky.
    """

    name: str
    frets: list[int]          # len == string_count
    string_count: int = 6
    base_fret: int = 0
    source_id: int = 0
    fingers: list[int] = field(default_factory=list)
