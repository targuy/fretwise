"""Static chord voicing library.

Provides a curated database of common guitar chord voicings loaded from
``data/patterns/chord_voicings.yaml``.  Used as a fallback when GP file chord
diagram data is missing or corrupted.

Usage
-----
>>> from fretwise.patterns.chord_library import lookup_chord
>>> diagram = lookup_chord("Am")
>>> diagram.frets  # [0, 1, 2, 2, 0, -1]  (high_e … low_E)
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fretwise.models import ChordDiagram

logger = logging.getLogger(__name__)

# Path to the YAML voicings file relative to this module's package root.
_VOICINGS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "patterns" / "chord_voicings.yaml"

# Module-level cache: chord name → ChordDiagram (first/preferred voicing).
_LIBRARY: dict[str, ChordDiagram] | None = None

# Module-level cache: quality suffix → list of movable shapes.
_MOVABLE: dict[str, list[_MovableShape]] | None = None

# Open-string pitch class per string, standard tuning E2 A2 D3 G3 B3 E4.
# Indexed as everywhere else: [str1 high_e, str2 B, str3 G, str4 D, str5 A, str6 low_E].
_OPEN_PC: tuple[int, ...] = (4, 11, 7, 2, 9, 4)

# Note name → pitch class (root parsing for generated chords).
_NAME_TO_PC: dict[str, int] = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4,
    "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11, "CB": 11, "B#": 0,
}

# Highest barre fret we will reach for before declaring a shape too high to use.
_MAX_ANCHOR_FRET = 12

# Pattern: leading note name (root) + remaining quality suffix.
_NAME_RE = re.compile(r"^([A-Ga-g][#b]?)(.*)$")


@dataclass(frozen=True)
class _MovableShape:
    """A canonical movable barre shape for one chord quality.

    Attributes:
        root_string: Root string (6 = low E "E-shape", 5 = A "A-shape").
        offsets: Per-string fret offsets from the anchor fret, same indexing as
            ``ChordDiagram.frets`` ([str1 high_e … str6 low_E]).  -1 = muted.
    """

    root_string: int
    offsets: tuple[int, ...]


def _load_library() -> dict[str, ChordDiagram]:
    """Load and cache the chord voicings YAML file."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed — chord library unavailable.")
        return {}

    if not _VOICINGS_PATH.exists():
        logger.warning("Chord voicings file not found at %s.", _VOICINGS_PATH)
        return {}

    with _VOICINGS_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    library: dict[str, ChordDiagram] = {}
    for entry in data.get("chords", []):
        name: str = entry.get("name", "")
        if not name:
            continue
        frets: list[int] = entry.get("frets", [-1] * 6)
        fingers: list[int] = entry.get("fingers", [0] * len(frets))
        base_fret: int = entry.get("base_fret", 1)
        # Only store the first (preferred) voicing per chord name.
        if name not in library:
            library[name] = ChordDiagram(
                name=name,
                frets=frets,
                fingers=fingers,
                string_count=len(frets),
                base_fret=base_fret,
                source_id=0,
            )

    logger.debug("Loaded %d chord voicings from library.", len(library))
    return library


def _get_library() -> dict[str, ChordDiagram]:
    """Return the cached library, loading it on first call."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _load_library()
    return _LIBRARY


def _load_movable() -> dict[str, list[_MovableShape]]:
    """Load and cache the ``movable_shapes`` section of the voicings YAML."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        return {}

    if not _VOICINGS_PATH.exists():
        return {}

    with _VOICINGS_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    shapes: dict[str, list[_MovableShape]] = {}
    for entry in data.get("movable_shapes", []):
        quality: str = entry.get("quality", "")
        families: list[_MovableShape] = []
        for fam in entry.get("families", []):
            offsets = fam.get("frets")
            root_string = fam.get("root_string")
            if offsets is None or root_string is None:
                continue
            families.append(
                _MovableShape(root_string=int(root_string), offsets=tuple(int(o) for o in offsets))
            )
        if families:
            shapes[quality] = families

    logger.debug("Loaded movable shapes for %d qualities.", len(shapes))
    return shapes


def _get_movable() -> dict[str, list[_MovableShape]]:
    """Return the cached movable-shape table, loading it on first call."""
    global _MOVABLE
    if _MOVABLE is None:
        _MOVABLE = _load_movable()
    return _MOVABLE


def _derive_fingers(frets: list[int]) -> list[int]:
    """Assign a finger to each fretted string from absolute frets.

    One finger per distinct fret value, ascending fret → ascending finger
    (lowest fret = index = 1).  Open (0) and muted (-1) strings get 0.  This
    keeps fingers consistent with frets (a finger never holds two frets) and is
    exactly how barre shapes are fingered: the lowest fret is the barre.

    Args:
        frets: Absolute fret per string (-1 muted, 0 open).

    Returns:
        Finger per string (0 none, 1 index … 4 pinky).
    """
    fretted = sorted({f for f in frets if f > 0})
    fret_to_finger = {f: i + 1 for i, f in enumerate(fretted)}
    return [fret_to_finger.get(f, 0) if f > 0 else 0 for f in frets]


def _generate_movable(root_pc: int, quality: str, name: str) -> ChordDiagram | None:
    """Generate a standard barre voicing for ``(root_pc, quality)``.

    Finds, for each available E/A family of the quality's movable shape, the
    lowest anchor fret (>= 1) where the root pitch class lands on the shape's
    root string, then builds absolute frets.  Prefers the family that yields the
    lower anchor fret (more playable), staying at or below fret 12 when possible.

    Args:
        root_pc: Root pitch class (0 = C … 11 = B).
        quality: Quality suffix (e.g. "m7", "" for major).
        name: Display name for the returned diagram.

    Returns:
        A validated ``ChordDiagram``, or None if no shape exists for the quality.
    """
    families = _get_movable().get(quality)
    if not families:
        return None

    candidates: list[tuple[int, int, ChordDiagram]] = []
    for shape in families:
        open_root_pc = _OPEN_PC[shape.root_string - 1]
        anchor = (root_pc - open_root_pc) % 12
        if anchor == 0:
            anchor = 12  # root on the open string → use the octave (fret-12) shape
        frets = [o + anchor if o >= 0 else -1 for o in shape.offsets]
        diagram = ChordDiagram(
            name=name,
            frets=frets,
            fingers=_derive_fingers(frets),
            string_count=6,
            base_fret=anchor,
            source_id=0,
        )
        # Sort key: lower anchor first; tie-break prefers the E-shape (string 6).
        candidates.append((anchor, 0 if shape.root_string == 6 else 1, diagram))

    if not candidates:
        return None
    candidates.sort(key=lambda c: (c[0], c[1]))
    return candidates[0][2]


def lookup_chord(name: str) -> ChordDiagram | None:
    """Look up a chord by name, returning the preferred voicing or None.

    Lookup strategy:
    1. Exact match against a curated open voicing (e.g. "Am", "G7", "Fmaj7").
    2. Case-insensitive curated match.
    3. Slash chord fallback: strip the bass note (e.g. "C/G" → "C").
    4. Generated movable barre voicing for the (root, quality) — used for any
       chromatic root / quality not present in the curated set.

    The 78 curated open voicings always take precedence over generated ones.

    Args:
        name: Chord name as it appears in the GP file or score.

    Returns:
        A ``ChordDiagram`` with correct frets and finger assignments,
        or ``None`` if no matching voicing is found.
    """
    if not name:
        return None

    lib = _get_library()

    # 1. Exact match (curated open voicing — preferred).
    if name in lib:
        return lib[name]

    # 2. Case-insensitive (preserve accidentals — only lowercase root).
    name_lower = name.lower()
    for key, diagram in lib.items():
        if key.lower() == name_lower:
            return diagram

    # 3. Slash chord: try the chord without the bass note.
    #    Guard against quality suffixes that contain "/" (e.g. "6/9", "m6/9"):
    #    only treat as a slash chord when the text after "/" is a note name.
    if "/" in name and _looks_like_bass_note(name.split("/", 1)[1].strip()):
        root_part = name.split("/")[0].strip()
        result = lookup_chord(root_part)
        if result is not None:
            # Return a copy with the original slash name for display.
            return ChordDiagram(
                name=name,
                frets=result.frets,
                fingers=result.fingers,
                string_count=result.string_count,
                base_fret=result.base_fret,
                source_id=result.source_id,
            )

    # 4. Generate a movable barre voicing.
    generated = _generate_from_name(name)
    if generated is not None:
        return generated

    logger.debug("No voicing found for chord '%s'.", name)
    return None


def _looks_like_bass_note(text: str) -> bool:
    """True if ``text`` is a bare note name (slash-chord bass), e.g. "G", "F#".

    Distinguishes a real slash bass from a quality suffix that contains "/"
    such as "9" in "6/9".

    Args:
        text: The portion of a chord name after the "/".

    Returns:
        True if it is a note name optionally followed by a single accidental.
    """
    return bool(re.fullmatch(r"[A-Ga-g][#b]?", text))


def _generate_from_name(name: str) -> ChordDiagram | None:
    """Parse a chord name and generate a movable voicing, or None.

    Splits ``name`` into a root note and a quality suffix, normalises the
    quality to the keys used in ``movable_shapes:``, and delegates to
    :func:`_generate_movable`.

    Args:
        name: Chord name such as "G#m7", "Bb9", "Faug".

    Returns:
        A generated ``ChordDiagram`` or None if the name cannot be parsed or
        the quality has no movable shape.
    """
    match = _NAME_RE.match(name)
    if not match:
        return None
    root_str, quality = match.group(1), match.group(2)
    root_pc = _NAME_TO_PC.get(root_str.upper())
    if root_pc is None:
        return None
    quality = _normalise_quality(quality)
    if quality is None:
        return None
    return _generate_movable(root_pc, quality, name)


# Quality-suffix aliases → canonical movable_shapes key.
_QUALITY_ALIASES: dict[str, str] = {
    "": "",
    "maj": "",
    "M": "",
    "min": "m",
    "m": "m",
    "-": "m",
    "dom7": "7",
    "7": "7",
    "maj7": "maj7",
    "Maj7": "maj7",
    "M7": "maj7",
    "Δ": "maj7",
    "m7": "m7",
    "min7": "m7",
    "-7": "m7",
    "m7b5": "m7b5",
    "min7b5": "m7b5",
    "ø": "m7b5",
    "halfdim": "m7b5",
    "dim": "dim",
    "°": "dim",
    "dim7": "dim7",
    "°7": "dim7",
    "aug": "aug",
    "+": "aug",
    "sus2": "sus2",
    "sus4": "sus4",
    "sus": "sus4",
    "6": "6",
    "m6": "m6",
    "min6": "m6",
    "9": "9",
    "maj9": "maj9",
    "M9": "maj9",
    "m9": "m9",
    "min9": "m9",
    "add9": "add9",
    "6/9": "6/9",
    "69": "6/9",
    "mM7": "mM7",
    "mMaj7": "mM7",
    "minmaj7": "mM7",
}


def _normalise_quality(suffix: str) -> str | None:
    """Map a raw quality suffix to a canonical movable-shape key, or None.

    Matching is case-SENSITIVE on purpose: "m" (minor) and "M" (major) differ
    only by case, so a case-insensitive fallback would conflate "m7" and "M7".

    Args:
        suffix: Quality portion of a chord name (e.g. "m7", "Maj7", "").

    Returns:
        Canonical key present in ``movable_shapes:`` or None if unsupported.
    """
    return _QUALITY_ALIASES.get(suffix)


def is_corrupt_diagram_set(diagrams: list[ChordDiagram]) -> bool:
    """Detect whether all diagrams in a set share identical fret data.

    Guitar Pro files sometimes encode every chord diagram with the same fret
    values (a known data corruption pattern).  Returns True when the set has
    at least 2 entries and all share the same frets list.

    Args:
        diagrams: List of parsed ChordDiagram objects.

    Returns:
        True if the frets data appears corrupted (all identical).
    """
    if len(diagrams) < 2:
        return False
    first = diagrams[0].frets
    return all(d.frets == first for d in diagrams[1:])


def repair_diagrams(diagrams: list[ChordDiagram]) -> list[ChordDiagram]:
    """Replace corrupted diagram fret data with library voicings.

    For each diagram whose name matches the library, substitute the library
    voicing.  Diagrams that have no library match are left unchanged (keeping
    at least the original name and any non-corrupt data they might have).

    Args:
        diagrams: List of ChordDiagram objects (potentially corrupted).

    Returns:
        New list with corrected fret/finger data where possible.
    """
    repaired: list[ChordDiagram] = []
    for diag in diagrams:
        replacement = lookup_chord(diag.name)
        if replacement is not None:
            repaired.append(
                ChordDiagram(
                    name=diag.name,
                    frets=replacement.frets,
                    fingers=replacement.fingers,
                    string_count=replacement.string_count,
                    base_fret=replacement.base_fret,
                    source_id=diag.source_id,
                )
            )
        else:
            repaired.append(diag)
    return repaired
