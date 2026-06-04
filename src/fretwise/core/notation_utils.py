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

from fretwise.config import config as _config

# ---------------------------------------------------------------------------
# Internal constants
# ---------------------------------------------------------------------------

# Tunable notation constants are sourced from the centralized config
# (src/fretwise/config/defaults.yaml -> notation). Values mirror the prior
# inline literals exactly; this is a refactor, not a tuning change.
_NOTATION_CFG = _config().notation

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
_E4_DIATONIC_INDEX: int = _NOTATION_CFG.clef_reference.treble_bottom_line_diatonic_index

# Absolute diatonic step of G2 (bass-clef bottom line reference).
# octave 2 × 7 diatonic steps/octave + G (step 4) = 18.
_G2_DIATONIC_INDEX: int = _NOTATION_CFG.clef_reference.bass_bottom_line_diatonic_index

# Bottom-line diatonic reference per clef.  Treble anchors on E4, bass on G2.
# (Percussion does not use diatonic placement — see ``percussion_note_y``.)
_CLEF_BOTTOM_LINE_INDEX: dict[str, int] = {
    "treble": _E4_DIATONIC_INDEX,
    "bass": _G2_DIATONIC_INDEX,
}

# General-MIDI percussion-key → vertical position on a 5-line drum staff,
# expressed in *diatonic steps above the bottom line* (each step = staff_spacing
# / 2; the bottom line is 0, the top line is 8).  Values are clamped to stay
# within ~one ledger line of the staff so a drum part reads like a real drum
# part (MuseScore-style) instead of exploding into a dozen ledger lines.
#
# Layout convention (bottom → top), matching common drum-notation practice:
#   kick           → bottom space      (≈ step 1)
#   floor / low tom → just below middle (steps 2–3)
#   snare          → middle line        (step 4)
#   mid / high tom  → above middle       (steps 5–7)
#   hi-hat / cymbals/ride → top line or above (steps 8–10)
_GM_DRUM_STAFF_STEP: dict[int, int] = {
    35: 1,   # Acoustic Bass Drum
    36: 1,   # Bass Drum 1 (kick)
    37: 4,   # Side Stick
    38: 4,   # Acoustic Snare
    39: 6,   # Hand Clap
    40: 4,   # Electric Snare
    41: 2,   # Low Floor Tom
    42: 9,   # Closed Hi-Hat
    43: 2,   # High Floor Tom
    44: 9,   # Pedal Hi-Hat
    45: 3,   # Low Tom
    46: 9,   # Open Hi-Hat
    47: 5,   # Low-Mid Tom
    48: 6,   # Hi-Mid Tom
    49: 10,  # Crash Cymbal 1
    50: 7,   # High Tom
    51: 9,   # Ride Cymbal 1
    52: 10,  # Chinese Cymbal
    53: 9,   # Ride Bell
    54: 8,   # Tambourine
    55: 10,  # Splash Cymbal
    56: 8,   # Cowbell
    57: 10,  # Crash Cymbal 2
    58: 7,   # Vibraslap
    59: 9,   # Ride Cymbal 2
}

# Default drum-staff step for any percussion key outside the explicit map:
# place it on the middle line so it never escapes the staff band.
_GM_DRUM_DEFAULT_STEP: int = _NOTATION_CFG.percussion.default_staff_step

# GM percussion keys that are notated with an 'x'-shaped notehead
# (hi-hats, cymbals, ride).  Used by the scene builder to pick the glyph.
_GM_DRUM_X_NOTEHEAD_KEYS: frozenset[int] = frozenset(
    {42, 44, 46, 49, 51, 52, 53, 55, 57, 59}
)


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
    clef: str = "treble",
) -> float:
    """Return the SVG Y-coordinate for a note on a pitched (treble/bass) staff.

    The bottom staff line sits at ``staff_y_origin + 4 × staff_spacing`` and is
    anchored to a clef-specific reference pitch:

    * treble → E4 (MIDI 64)
    * bass   → G2 (MIDI 43)

    Each diatonic step upward subtracts ``staff_spacing / 2`` (SVG y increases
    downward, so higher pitches have smaller Y values).

    For ``clef == "percussion"`` use :func:`percussion_note_y` instead; this
    helper falls back to treble placement for unknown clefs.

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
        clef: ``"treble"`` (default) or ``"bass"``.

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

    bottom_line_index = _CLEF_BOTTOM_LINE_INDEX.get(clef, _E4_DIATONIC_INDEX)
    diatonic_delta = abs_index - bottom_line_index
    return staff_y_origin + 4.0 * staff_spacing - diatonic_delta * (staff_spacing / 2.0)


def percussion_note_y(
    pitch_midi: int,
    *,
    staff_y_origin: float,
    staff_spacing: float,
) -> float:
    """Return the SVG Y-coordinate for a General-MIDI drum on a 5-line staff.

    Percussion is *not* placed by pitch (that produces a ledger-line explosion
    for the low GM drum keys).  Instead each GM percussion key maps to a fixed
    vertical slot — kick near the bottom space, snare on the middle line,
    hi-hat/cymbals on or above the top line, toms spread in between — so the
    part reads like a conventional drum staff.

    Args:
        pitch_midi: GM percussion key number (typically 35–59).
        staff_y_origin: SVG y-coordinate of the top (5th) staff line.
        staff_spacing: Distance in SVG units between adjacent staff lines.

    Returns:
        SVG y-coordinate for the notehead centre, clamped to the staff band
        plus at most ~one ledger line above/below.
    """
    step = _GM_DRUM_STAFF_STEP.get(pitch_midi, _GM_DRUM_DEFAULT_STEP)
    # Steps are measured upward from the bottom line (step 0).  The staff itself
    # spans steps 0..8; clamp to -2..10 so nothing strays beyond one ledger.
    step = max(-2, min(10, step))
    return staff_y_origin + 4.0 * staff_spacing - step * (staff_spacing / 2.0)


def is_x_notehead_drum(pitch_midi: int) -> bool:
    """Return ``True`` if a GM percussion key is drawn with an 'x' notehead.

    Hi-hats, cymbals and the ride are conventionally notated with cross
    noteheads; drums (kick/snare/toms) use ordinary noteheads.
    """
    return pitch_midi in _GM_DRUM_X_NOTEHEAD_KEYS
