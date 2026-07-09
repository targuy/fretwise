"""Data schemas for guitar fingering datasets."""
import json
from dataclasses import asdict, dataclass, field
from enum import IntEnum


class Finger(IntEnum):
    NONE = 0
    INDEX = 1
    MIDDLE = 2
    RING = 3
    PINKY = 4
    THUMB = 5


class Technique(IntEnum):
    NORMAL = 0
    HAMMER_ON = 1
    PULL_OFF = 2
    SLIDE = 3
    BEND = 4
    VIBRATO = 5
    TAP = 6
    HARMONIC = 7
    BARRE = 8


@dataclass
class FingeredNote:
    string: int              # 1-6 (1=high E)
    fret: int                # 0-24
    finger: Finger
    midi_pitch: int          # MIDI note number
    duration: float          # in beats
    technique: Technique = Technique.NORMAL
    is_rest: bool = False

    def to_dict(self):
        d = asdict(self)
        d["finger"] = self.finger.value
        d["technique"] = self.technique.value
        return d


@dataclass
class FingeredChord:
    name: str                           # e.g. "Am7"
    strings: list[int | None]        # fret per string, None=muted, length 6
    fingers: list[Finger | None]     # finger per string, None=muted
    position: int = 0                   # base fret (for barre chords)
    is_barre: bool = False
    source: str = ""

    def to_dict(self):
        d = asdict(self)
        d["fingers"] = [f.value if f is not None else None for f in self.fingers]
        return d


@dataclass
class NoteSequence:
    """A sequence of fingered notes from a single track/voice."""
    notes: list[FingeredNote] = field(default_factory=list)
    tempo: int = 120
    tuning: list[int] = field(default_factory=lambda: [64, 59, 55, 50, 45, 40])
    source_file: str = ""
    source_type: str = ""  # "guitarpro", "musicxml", "chord_lib", "synthetic"

    @property
    def has_fingering(self) -> bool:
        return any(n.finger != Finger.NONE for n in self.notes)

    @property
    def fingering_coverage(self) -> float:
        playable = [n for n in self.notes if not n.is_rest and n.fret > 0]
        if not playable:
            return 0.0
        return sum(1 for n in playable if n.finger != Finger.NONE) / len(playable)

    def to_dict(self):
        return {
            "notes": [n.to_dict() for n in self.notes],
            "tempo": self.tempo,
            "tuning": self.tuning,
            "source_file": self.source_file,
            "source_type": self.source_type,
            "fingering_coverage": self.fingering_coverage,
        }

    def to_transitions(self) -> list[dict]:
        """Extract note-to-note transitions with fingering — the core ML training unit."""
        playable = [n for n in self.notes if not n.is_rest]
        transitions = []
        for i in range(1, len(playable)):
            prev, curr = playable[i - 1], playable[i]
            transitions.append({
                "prev_string": prev.string,
                "prev_fret": prev.fret,
                "prev_finger": prev.finger.value,
                "prev_technique": prev.technique.value,
                "curr_string": curr.string,
                "curr_fret": curr.fret,
                "curr_finger": curr.finger.value,
                "curr_technique": curr.technique.value,
                "fret_delta": curr.fret - prev.fret,
                "string_delta": curr.string - prev.string,
            })
        return transitions


def save_sequences(sequences: list[NoteSequence], path: str):
    data = [s.to_dict() for s in sequences]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_chords(chords: list[FingeredChord], path: str):
    data = [c.to_dict() for c in chords]
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
