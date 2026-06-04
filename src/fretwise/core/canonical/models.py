"""Canonical semantic model (format and backend independent)."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Technique:
    """Instrumental technique attached to an event."""

    name: str
    value: str | None = None


@dataclass(frozen=True)
class Tuning:
    """String tuning in sounding MIDI pitches (high to low string)."""

    open_pitches: tuple[int, ...] = (64, 59, 55, 50, 45, 40)
    label: str = "EADGBE"


@dataclass(frozen=True)
class TabInfo:
    """Tab-specific execution data for a note event."""

    string: int | None = None
    fret: int | None = None
    tuning: Tuning | None = None
    left_hand_finger: str | None = None


@dataclass(frozen=True)
class LayoutHint:
    """Layout-related hint attached to canonical events."""

    key: str
    value: str


@dataclass(frozen=True)
class Tuplet:
    """Tuplet ratio."""

    actual: int
    normal: int


@dataclass(frozen=True)
class Tie:
    """Tie relation metadata."""

    tie_id: str
    continues: bool = False


@dataclass(frozen=True)
class Slur:
    """Slur span metadata."""

    slur_id: str
    continues: bool = False


@dataclass(frozen=True)
class Dynamic:
    """Canonical dynamic marking."""

    mark: str


@dataclass(frozen=True)
class TempoMark:
    """Tempo at a given onset."""

    onset: float
    bpm: float


@dataclass(frozen=True)
class TimeSignature:
    """Time signature marker."""

    numerator: int
    denominator: int = 4


@dataclass(frozen=True)
class KeySignature:
    """Key signature marker."""

    tonic: str = "C"
    mode: str = "major"
    fifths: int = 0


@dataclass(frozen=True)
class Barline:
    """Barline style marker."""

    style: str = "single"


@dataclass(frozen=True)
class RepeatStructure:
    """Repeat section metadata."""

    start_measure: int
    end_measure: int
    times: int = 2


@dataclass
class Event:
    """Base canonical event."""

    event_id: str
    onset: float
    duration: float
    voice: int


@dataclass
class NoteEvent(Event):
    """Canonical pitched event with optional tab execution data."""

    pitch_notated: int
    pitch_sounding: int
    tab_info: TabInfo | None = None
    techniques: list[Technique] = field(default_factory=list)
    tuplet: Tuplet | None = None
    tie: Tie | None = None
    slur: Slur | None = None
    dynamic: Dynamic | None = None
    layout_hints: list[LayoutHint] = field(default_factory=list)


@dataclass
class RestEvent(Event):
    """Canonical rest event."""

    layout_hints: list[LayoutHint] = field(default_factory=list)


@dataclass
class ChordEvent(Event):
    """Canonical chord event (simultaneous note events)."""

    notes: list[NoteEvent] = field(default_factory=list)
    layout_hints: list[LayoutHint] = field(default_factory=list)


@dataclass
class Voice:
    """Voice lane inside a measure."""

    number: int
    events: list[Event] = field(default_factory=list)


@dataclass
class Measure:
    """Measure container."""

    number: int
    time_signature: TimeSignature
    voices: list[Voice] = field(default_factory=list)
    barline: Barline = field(default_factory=Barline)
    repeat: RepeatStructure | None = None
    section_name: str = ""


@dataclass
class Staff:
    """Staff container."""

    staff_id: str
    clef: str
    measures: list[Measure] = field(default_factory=list)


@dataclass
class StaffGroup:
    """Group of related staves."""

    group_id: str
    name: str = ""
    staves: list[Staff] = field(default_factory=list)


@dataclass
class Track:
    """Track container."""

    track_id: str
    name: str
    staff_groups: list[StaffGroup] = field(default_factory=list)
    #: Instrument family driving clef/octave choices:
    #: "guitar" | "bass" | "drums" | "vocal" | "other". Defaults to guitar so
    #: existing single-track guitar paths render exactly as before.
    kind: str = "guitar"


@dataclass
class Score:
    """Top-level canonical score."""

    score_id: str
    title: str
    tracks: list[Track] = field(default_factory=list)
    tempo_marks: list[TempoMark] = field(default_factory=list)
    key_signature: KeySignature = field(default_factory=KeySignature)
