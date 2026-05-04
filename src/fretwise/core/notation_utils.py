"""Shared music-notation utilities: pitch placement and diatonic step helpers.

This module is the single source of truth for converting MIDI pitches and note
names to staff Y-coordinates.  Both ``core.layout.rules`` and
``core.scene.builders`` delegate here so the two subsystems cannot diverge.

Musical reference — treble clef (staff_y_origin = y of the 5th / top line):
    F5 (MIDI 77) → staff_y_origin + 0                     (5th line, top)
    D5 (MIDI 74) → staff_y_origin + 1 × staff_spacing     (4th line)
    B4 (MIDI 71) → staff_y_origin + 2 × staff_spacing     (3rd line, middle)
    G4 (MIDI 67) → staff_y_origin + 3 × staff_spacing     (2nd line)
    E4 (MIDI 64) → staff_y_origin + 4 × staff_spacing     (1st line, bottom)
    C4 (MIDI 60) → staff_y_origin + 5 × staff_spacing     (1st ledger below)

Each diatonic step = staff_spacing / 2.  Y increases downward (SVG convention).
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Maps each note letter to its diatonic position within an octave (C = 0 … B = 6).
_DIATONIC_LETTER_STEP: dict[str, int] = {
    "C": 0,
    "D": 1,
    "E": 2,
    "F": 3,
    "G": 4,
    "A": 5,
    "B": 6,
}

# Maps chromatic pitch class (0–11, C = 0) to diatonic step in the octave.
# Accidentals collapse onto their lower diatonic neighbour
# (e.g. C# → C = 0, Eb → D = 1, Bb → A = 5).
_CHROMATIC_TO_DIATONIC: tuple[int, ...] = (
    0,   # C
    0,   # C# / Db
    1,   # D
    1,   # D# / Eb
    2,   # E
    3,   # F
    3,   # F# / Gb
    4,   # G
    4,   # G# / Ab
    5,   # A
    5,   # A# / Bb
    6,   # B
)

# Absolute diatonic step of E4 (treble-clef bottom line reference).
# octave 4 × 7 diatonic steps/octave + E (step 2) = 30.
_E4_DIATONIC_INDEX: int = 4 * 7 + 2  # = 30


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def diatonic_step_index(pitch_midi: int) -> int:
    """Return the absolute diatonic step index for a MIDI pitch (C0 = 0).

    Chromatic (accidental) pitches collapse to their lower diatonic step so
    that, for example, C# and Db both return the same index as C.

    Args:
        pitch_midi: MIDI pitch number (0–127).

    Returns:
        Non-negative integer: octave × 7 + letter_step_in_octave.
    """
    octave = pitch_midi // 12 - 1
    diatonic_in_octave = _CHROMATIC_TO_DIATONIC[pitch_midi % 12]
    return octave * 7 + diatonic_in_octave


def diatonic_step_from_name(step: str, octave: int) -> int:
    """Return the absolute diatonic step index from a note letter and octave.

    Args:
        step: Note letter, one of A–G (case-insensitive).
        octave: Scientific octave number (C4 = middle C, octave 4).

    Returns:
        Non-negative integer: octave × 7 + letter_step_in_octave.

    Raises:
        KeyError: If *step* is not a valid note letter.
    """
    return octave * 7 + _DIATONIC_LETTER_STEP[step.upper()]


def diatonic_step_from_metadata(
    metadata: dict[str, str],
    *,
    fallback_pitch: int = 64,
) -> int:
    """Return the diatonic step index using metadata fields when available.

    Prefers the enharmonically-correct ``pitch_step`` / ``pitch_octave`` pair
    from the metadata dict (e.g. ``{"pitch_step": "B", "pitch_octave": "4"}``)
    because it distinguishes C# from Db.  Falls back to ``fallback_pitch``
    when those fields are absent or malformed.

    Args:
        metadata: Note metadata dict, typically from the canonical model.
        fallback_pitch: MIDI pitch used when ``pitch_step``/``pitch_octave``
            are not present or invalid.

    Returns:
        Absolute diatonic step index.
    """
    step_raw = str(metadata.get("pitch_step", "")).strip().upper()
    octave_raw = str(metadata.get("pitch_octave", "")).strip()
    if step_raw in _DIATONIC_LETTER_STEP:
        try:
            return diatonic_step_from_name(step_raw, int(octave_raw))
        except (ValueError, KeyError):
            pass
    return diatonic_step_index(fallback_pitch)


def standard_note_y(
    pitch_midi: int,
    *,
    staff_y_origin: float,
    staff_spacing: float,
    step: str | None = None,
    octave: int | None = None,
) -> float:
    """Return the SVG Y-coordinate for a note on a treble-clef staff.

    E4 (MIDI 64) sits on the bottom line at ``staff_y_origin + 4 × staff_spacing``.
    Each diatonic step upward subtracts ``staff_spacing / 2`` (SVG y increases
    downward, so higher pitches have smaller Y values).

    When *step* and *octave* are both provided they are preferred over
    *pitch_midi* for the diatonic mapping, which correctly handles enharmonic
    equivalents (C# vs Db, etc.).

    Args:
        pitch_midi: MIDI pitch number (0–127).  Always required; used as the
            fallback diatonic source when *step*/*octave* are absent.
        staff_y_origin: SVG y-coordinate of the top (5th) staff line.
        staff_spacing: Distance in SVG units between adjacent staff lines.
        step: Optional note letter (A–G) for enharmonic-correct placement.
        octave: Optional scientific octave (must be supplied together with
            *step*; ignored if *step* is ``None``).

    Returns:
        SVG y-coordinate for the notehead centre.
    """
    if step is not None and octave is not None:
        try:
            abs_index = diatonic_step_from_name(step, octave)
        except KeyError:
            abs_index = diatonic_step_index(pitch_midi)
    else:
        abs_index = diatonic_step_index(pitch_midi)

    diatonic_delta = abs_index - _E4_DIATONIC_INDEX
    return staff_y_origin + 4.0 * staff_spacing - diatonic_delta * (staff_spacing / 2.0)
