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
from pathlib import Path
from typing import Any

from fretwise.models import ChordDiagram

logger = logging.getLogger(__name__)

# Path to the YAML voicings file relative to this module's package root.
_VOICINGS_PATH = Path(__file__).parent.parent.parent.parent / "data" / "patterns" / "chord_voicings.yaml"

# Module-level cache: chord name → ChordDiagram (first/preferred voicing).
_LIBRARY: dict[str, ChordDiagram] | None = None


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


def lookup_chord(name: str) -> ChordDiagram | None:
    """Look up a chord by name, returning the preferred voicing or None.

    Lookup strategy:
    1. Exact match (e.g. "Am", "G7", "Fmaj7").
    2. Case-insensitive match.
    3. Slash chord fallback: strip the bass note (e.g. "C/G" → "C").

    Args:
        name: Chord name as it appears in the GP file or score.

    Returns:
        A ``ChordDiagram`` with correct frets and finger assignments,
        or ``None`` if no matching voicing is found.
    """
    if not name:
        return None

    lib = _get_library()

    # 1. Exact match.
    if name in lib:
        return lib[name]

    # 2. Case-insensitive (preserve accidentals — only lowercase root).
    name_lower = name.lower()
    for key, diagram in lib.items():
        if key.lower() == name_lower:
            return diagram

    # 3. Slash chord: try the chord without the bass note.
    if "/" in name:
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

    logger.debug("No voicing found for chord '%s'.", name)
    return None


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
