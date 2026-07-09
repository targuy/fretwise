"""CAGED system scale and arpeggio patterns with fingerings.

Conventions
-----------
- String numbering: 1 = high E, 6 = low E  (matches schema.py).
- ``fret_offset``: semitones relative to ``root_fret`` on each string.
  Absolute fret = root_fret + fret_offset.
- Base patterns use root_fret >= 1 so no open-string edge cases arise.
  Transposition simply shifts root_fret; offsets stay constant.
- Finger mapping: 1=index, 2=middle, 3=ring, 4=pinky.
  Within each string the hand spans 4 frets; finger = fret - hand_lo + 1.
- ``intervals`` list is the single source of truth; ``notes_per_string``
  is derived from it automatically.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fretwise.dataset.data_schema.schema import Finger, FingeredNote, NoteSequence, Technique

# ---------------------------------------------------------------------------
# Standard tuning: MIDI pitches for open strings  (1=high E .. 6=low E)
# ---------------------------------------------------------------------------
STANDARD_TUNING = [64, 59, 55, 50, 45, 40]

# ---------------------------------------------------------------------------
# Scale interval sets (semitones from root, mod 12)
# ---------------------------------------------------------------------------
SCALE_INTERVALS: dict[str, list[int]] = {
    "major":            [0, 2, 4, 5, 7, 9, 11],
    "minor":            [0, 2, 3, 5, 7, 8, 10],
    "minor_pentatonic": [0, 3, 5, 7, 10],
    "major_pentatonic": [0, 2, 4, 7, 9],
    "blues":            [0, 3, 5, 6, 7, 10],
    "harmonic_minor":   [0, 2, 3, 5, 7, 8, 11],
    "melodic_minor":    [0, 2, 3, 5, 7, 9, 11],
}

# Note names for labelling transpositions
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]

# All 12 chromatic keys (as semitone offset from C)
ALL_KEYS = list(range(12))


# ---------------------------------------------------------------------------
# Dataclass
# ---------------------------------------------------------------------------
@dataclass
class CAGEDPattern:
    """One CAGED shape for a given scale type.

    ``intervals`` is the canonical note list: each entry is
    ``(string, fret_offset, finger)`` where *fret_offset* is relative
    to ``root_fret``.  ``notes_per_string`` is derived on construction.
    """

    name: str
    shape: str
    scale_type: str
    root_string: int
    root_fret: int
    intervals: list[tuple[int, int, int]]
    notes_per_string: dict[int, list[tuple[int, int]]] = field(
        default_factory=dict, init=False
    )

    def __post_init__(self) -> None:
        nps: dict[int, list[tuple[int, int]]] = {}
        for string, fret_offset, finger in self.intervals:
            nps.setdefault(string, []).append((fret_offset, finger))
        for s in nps:
            nps[s].sort(key=lambda x: x[0])
        self.notes_per_string = nps


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------
def _validate_pattern(pattern: CAGEDPattern) -> None:
    """Assert every note in *pattern* belongs to the declared scale."""
    expected = set(SCALE_INTERVALS[pattern.scale_type])
    root_midi = STANDARD_TUNING[pattern.root_string - 1] + pattern.root_fret
    for string, fret_offset, _finger in pattern.intervals:
        note_midi = STANDARD_TUNING[string - 1] + pattern.root_fret + fret_offset
        interval = (note_midi - root_midi) % 12
        if interval not in expected:
            raise ValueError(
                f"Pattern '{pattern.name}': note on string {string}, "
                f"fret_offset {fret_offset} gives interval {interval} "
                f"which is not in {pattern.scale_type} intervals {sorted(expected)}"
            )


# ---------------------------------------------------------------------------
# CAGED shape geometry
# ---------------------------------------------------------------------------
# Each CAGED shape is defined by:
#   - root_string: which string carries the lowest root
#   - hand_offset: offset of the index-finger fret relative to root_fret
#     (e.g. 0 means index on root, -2 means index 2 frets below root)
#   - base_root_fret: fret of root in the base position (ensures all
#     frets >= 0)
#
# The hand spans 4 frets on every string:
#   [root_fret + hand_offset, root_fret + hand_offset + 3]
#
# We scan this window on all 6 strings for scale tones.
# ---------------------------------------------------------------------------

_CAGED_SHAPES = [
    # (name, root_string, hand_offset, base_root_fret)
    #
    # E shape: root at index finger on string 6
    ("E", 6, 0, 3),
    # D shape: root at index finger on string 4
    ("D", 4, 0, 5),
    # C shape: root at ring finger on string 5 (index is 2 below root)
    ("C", 5, -2, 3),
    # A shape: root at index finger on string 5
    ("A", 5, 0, 3),
    # G shape: root at pinky on string 6 (index is 3 below root)
    ("G", 6, -3, 4),
]


# ---------------------------------------------------------------------------
# Finger assignment
# ---------------------------------------------------------------------------
def _assign_fingers(
    frets_on_string: list[int],
    hand_lo: int,
) -> list[int]:
    """Assign fingers 1-4 to frets within a 4-fret hand span.

    Parameters
    ----------
    frets_on_string : list of absolute frets on one string
    hand_lo : absolute fret where the index finger sits

    Returns
    -------
    list of finger numbers (1-4)
    """
    fingers = []
    for fret in frets_on_string:
        f = fret - hand_lo + 1
        # Clamp to [1, 4] for edge cases
        f = max(1, min(4, f))
        fingers.append(f)
    return fingers


# ---------------------------------------------------------------------------
# Pattern generation engine
# ---------------------------------------------------------------------------
def _generate_box_patterns_for_scale(scale_type: str) -> list[CAGEDPattern]:
    """Generate all 5 CAGED shapes for a given scale type."""
    scale_ivs = set(SCALE_INTERVALS[scale_type])
    patterns = []

    for shape_name, root_string, hand_offset, base_root_fret in _CAGED_SHAPES:
        root_midi = STANDARD_TUNING[root_string - 1] + base_root_fret
        hand_lo = base_root_fret + hand_offset
        hand_hi = hand_lo + 3  # 4-fret span

        intervals: list[tuple[int, int, int]] = []

        for s in range(6, 0, -1):
            string_open_midi = STANDARD_TUNING[s - 1]
            frets_on_string: list[int] = []

            for fret in range(max(0, hand_lo), hand_hi + 1):
                note_midi = string_open_midi + fret
                interval = (note_midi - root_midi) % 12
                if interval in scale_ivs:
                    frets_on_string.append(fret)

            if frets_on_string:
                fingers = _assign_fingers(frets_on_string, hand_lo)
                for fret, finger in zip(frets_on_string, fingers):
                    fret_offset = fret - base_root_fret
                    intervals.append((s, fret_offset, finger))

        if intervals:
            nice_type = scale_type.replace("_", " ").title()
            patterns.append(CAGEDPattern(
                name=f"{nice_type} - {shape_name} Shape",
                shape=shape_name,
                scale_type=scale_type,
                root_string=root_string,
                root_fret=base_root_fret,
                intervals=intervals,
            ))

    return patterns


# ---------------------------------------------------------------------------
# Master pattern generator
# ---------------------------------------------------------------------------
def generate_caged_patterns() -> list[CAGEDPattern]:
    """Generate base CAGED patterns for all supported scale types.

    Returns at least 25 patterns (5 shapes x 5+ scale types = 35).
    """
    all_patterns: list[CAGEDPattern] = []

    for scale_type in SCALE_INTERVALS:
        all_patterns.extend(_generate_box_patterns_for_scale(scale_type))

    # Validate every pattern
    for p in all_patterns:
        _validate_pattern(p)

    return all_patterns


# ---------------------------------------------------------------------------
# Transposition
# ---------------------------------------------------------------------------
def generate_all_transpositions(
    patterns: list[CAGEDPattern],
    keys: list[int] | None = None,
) -> list[CAGEDPattern]:
    """Transpose *patterns* to every key in *keys* (semitone offsets 0-11).

    Parameters
    ----------
    patterns : list[CAGEDPattern]
        Base patterns (as returned by ``generate_caged_patterns``).
    keys : list[int] | None
        Semitone offsets from the base root.  ``None`` means all 12 keys.

    Returns
    -------
    list[CAGEDPattern]
        Only patterns whose notes all fall within frets 0-24 are included.
    """
    if keys is None:
        keys = ALL_KEYS

    transposed: list[CAGEDPattern] = []

    for pattern in patterns:
        for key_offset in keys:
            new_root_fret = pattern.root_fret + key_offset
            if new_root_fret < 0:
                continue
            all_valid = True
            for _s, fo, _f in pattern.intervals:
                abs_fret = new_root_fret + fo
                if abs_fret < 0 or abs_fret > 24:
                    all_valid = False
                    break
            if not all_valid:
                continue

            root_midi = STANDARD_TUNING[pattern.root_string - 1] + new_root_fret
            key_name = NOTE_NAMES[root_midi % 12]
            nice_type = pattern.scale_type.replace("_", " ").title()
            new_name = f"{key_name} {nice_type} - {pattern.shape} Shape"

            transposed.append(CAGEDPattern(
                name=new_name,
                shape=pattern.shape,
                scale_type=pattern.scale_type,
                root_string=pattern.root_string,
                root_fret=new_root_fret,
                intervals=list(pattern.intervals),
            ))

    return transposed


# ---------------------------------------------------------------------------
# Conversion to NoteSequence
# ---------------------------------------------------------------------------
def to_note_sequences(
    patterns: list[CAGEDPattern],
    duration: float = 1.0,
    tempo: int = 120,
) -> list[NoteSequence]:
    """Convert CAGED patterns into ``NoteSequence`` objects.

    Notes are ordered ascending by pitch -- standard scale-practice order.
    """
    sequences: list[NoteSequence] = []

    for pattern in patterns:
        notes: list[FingeredNote] = []
        for string, fret_offset, finger in pattern.intervals:
            abs_fret = pattern.root_fret + fret_offset
            midi_pitch = STANDARD_TUNING[string - 1] + abs_fret
            notes.append(FingeredNote(
                string=string,
                fret=abs_fret,
                finger=Finger(finger),
                midi_pitch=midi_pitch,
                duration=duration,
                technique=Technique.NORMAL,
                is_rest=False,
            ))

        notes.sort(key=lambda n: (n.midi_pitch, -n.string))

        seq = NoteSequence(
            notes=notes,
            tempo=tempo,
            tuning=list(STANDARD_TUNING),
            source_file=f"caged:{pattern.name}",
            source_type="synthetic",
        )
        sequences.append(seq)

    return sequences


# ---------------------------------------------------------------------------
# Convenience: generate everything
# ---------------------------------------------------------------------------
def generate_full_dataset(
    keys: list[int] | None = None,
) -> tuple[list[CAGEDPattern], list[NoteSequence]]:
    """Generate transposed CAGED patterns and their NoteSequences.

    Returns
    -------
    patterns : list[CAGEDPattern]
        All valid transposed patterns (target >= 300).
    sequences : list[NoteSequence]
        One NoteSequence per pattern.
    """
    base = generate_caged_patterns()
    transposed = generate_all_transpositions(base, keys)
    sequences = to_note_sequences(transposed)
    return transposed, sequences


# ---------------------------------------------------------------------------
# Self-test when run directly
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    base = generate_caged_patterns()
    print(f"Base patterns: {len(base)}")
    for p in base:
        print(f"  {p.name:45s}  shape={p.shape}  root_str={p.root_string}  "
              f"root_fret={p.root_fret}  notes={len(p.intervals)}")

    transposed = generate_all_transpositions(base)
    print(f"\nTransposed patterns: {len(transposed)}")

    seqs = to_note_sequences(transposed)
    print(f"NoteSequences: {len(seqs)}")
    if seqs:
        s = seqs[0]
        print(f"  First sequence: '{s.source_file}', {len(s.notes)} notes, "
              f"coverage={s.fingering_coverage:.0%}")
