"""Scale pattern library and recognition.

Loads scale definitions from ``data/patterns/scales.yaml`` and provides
recognition of scale segments from sequences of MIDI pitches.

Usage
-----
>>> from fretwise.patterns.scale_library import recognize_scale, get_scale
>>> recognize_scale([60, 62, 64, 65, 67, 69, 71])  # C major
ScaleMatch(name='major', root=0, confidence=1.0)
>>> get_scale("minor_pentatonic")
ScaleDefinition(name='minor_pentatonic', intervals=frozenset({0, 3, 5, 7, 10}), ...)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_SCALES_PATH = (
    Path(__file__).parent.parent.parent.parent / "data" / "patterns" / "scales.yaml"
)

_NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ScaleDefinition:
    """A scale type with its interval structure.

    Attributes:
        name: Scale name (e.g. "major", "minor_pentatonic").
        intervals: Frozenset of semitone intervals from root (pitch classes).
    """

    name: str
    intervals: frozenset[int]


@dataclass(frozen=True)
class ScaleMatch:
    """Result of scale recognition.

    Attributes:
        name: Scale name that matched.
        root: Root pitch class (0–11, where 0=C).
        root_name: Note name of the root (e.g. "A", "Eb").
        confidence: Match quality (0.0–1.0).  1.0 = all pitches fit the scale.
    """

    name: str
    root: int
    root_name: str
    confidence: float


# ---------------------------------------------------------------------------
# Library loading
# ---------------------------------------------------------------------------

_LIBRARY: dict[str, ScaleDefinition] | None = None


def _load_library() -> dict[str, ScaleDefinition]:
    """Load scale definitions from YAML."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        logger.warning("PyYAML not installed — scale library unavailable.")
        return {}

    if not _SCALES_PATH.exists():
        logger.warning("Scale library not found at %s.", _SCALES_PATH)
        return {}

    with _SCALES_PATH.open(encoding="utf-8") as fh:
        data: dict[str, Any] = yaml.safe_load(fh)

    library: dict[str, ScaleDefinition] = {}
    for entry in data.get("scales", []):
        name: str = entry.get("name", "")
        if not name:
            continue
        intervals = frozenset(entry.get("intervals", []))
        library[name] = ScaleDefinition(name=name, intervals=intervals)

    logger.debug("Loaded %d scale definitions.", len(library))
    return library


def _get_library() -> dict[str, ScaleDefinition]:
    """Return cached library, loading on first call."""
    global _LIBRARY
    if _LIBRARY is None:
        _LIBRARY = _load_library()
    return _LIBRARY


def get_scale(name: str) -> ScaleDefinition | None:
    """Look up a scale definition by name.

    Args:
        name: Scale name (e.g. "major", "minor_pentatonic").

    Returns:
        ScaleDefinition or None if not found.
    """
    return _get_library().get(name)


def list_scales() -> list[str]:
    """Return all available scale names."""
    return list(_get_library().keys())


# ---------------------------------------------------------------------------
# Fretboard rendering (training module) — transpose box positions to a root
# ---------------------------------------------------------------------------

# Note name → pitch class. Mirrors chord_library._NAME_TO_PC (kept local:
# this is a static music-theory table, not a shared inter-module contract).
_NAME_TO_PC: dict[str, int] = {
    "C": 0, "C#": 1, "DB": 1, "D": 2, "D#": 3, "EB": 3, "E": 4, "FB": 4,
    "E#": 5, "F": 5, "F#": 6, "GB": 6, "G": 7, "G#": 8, "AB": 8, "A": 9,
    "A#": 10, "BB": 10, "B": 11, "CB": 11, "B#": 0,
}

# Open-string pitch class by string number (standard tuning E2 A2 D3 G3 B3 E4).
_OPEN_PC_BY_STRING: dict[int, int] = {1: 4, 2: 11, 3: 7, 4: 2, 5: 9, 6: 4}

# Open-string MIDI pitch by string number, same tuning.
_OPEN_MIDI_BY_STRING: dict[int, int] = {1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40}


def scale_boxes_for_root(name: str, root: str) -> list[dict[str, Any]] | None:
    """Playable fretboard boxes for scale ``name`` in key ``root``.

    Boxes are **derived from the scale's interval set**, not from the
    hand-authored ``positions:`` patterns in ``scales.yaml``. Those patterns
    have never had a consumer (recognition works off ``_SCALE_PATTERNS``, and
    ``PatternMatcher`` reads only the intervals), and an audit against the
    interval sets shows most of them place out-of-scale notes — they are not
    a trustworthy source for a chart a player reads.

    Boxes are **positional** (the CAGED school): one fret window anchored on
    an in-scale note of the low E string, held across all six strings, with
    every in-scale note inside it. The hand never moves within a box, so a box
    is fully described by "put the index at fret N" — which is what makes it
    usable as a warm-up chart.

    The alternative school, three-notes-per-string, pivots the hand as it
    climbs. It is not used here: deriving it requires walking scale degrees
    across strings, and that walk drifts badly on scales whose step sizes do
    not divide evenly into the tuning. Six-note scales fall a semitone behind
    per string (the blues scale smears across nine frets), and scales with a
    three-semitone step climb instead (harmonic minor runs from fret 8 to 16).
    A fixed window cannot drift, and the number of notes per string is simply
    however many the scale puts there — two or three, as in real positional
    playing.

    Boxes are ordered from the tonic anchor, so ``position_1`` is the
    root-position box as conventionally taught.

    Args:
        name: Scale name (e.g. "major", "minor_pentatonic").
        root: Root note name (e.g. "E", "Bb", "f#"). Case-insensitive.

    Returns:
        A list of ``{name, min_fret, max_fret, notes}`` dicts (one per box),
        where each note is ``{string, fret, is_root}`` — or None if the scale
        name or root note is not recognised.
    """
    scale = get_scale(name)
    if scale is None:
        return None
    root_pc = _NAME_TO_PC.get(root.strip().upper())
    if root_pc is None:
        return None

    in_scale = {(root_pc + i) % 12 for i in scale.intervals}
    # Frets the hand covers without shifting. Only the pentatonics are tight
    # enough for four: from six notes up, the scale's widest step no longer
    # fits, and some strings would contribute a single note to the box.
    span = 4 if len(scale.intervals) <= 5 else 5

    # Anchors: in-scale frets on the low E string. Rotated so the tonic leads
    # (position_1 == root position), and anchors that wrapped past the tonic
    # are lifted an octave so the sequence keeps climbing the neck instead of
    # dropping back to the nut — the carousel is meant to walk upward.
    low_e_pc = _OPEN_PC_BY_STRING[6]
    in_octave = [f for f in range(12) if (low_e_pc + f) % 12 in in_scale]
    tonic_at = next((i for i, f in enumerate(in_octave) if (low_e_pc + f) % 12 == root_pc), 0)
    anchors = in_octave[tonic_at:] + [f + 12 for f in in_octave[:tonic_at]]

    def coverage(start: int, width: int) -> int:
        """Fewest notes any single string contributes to this window."""
        return min(
            sum(1 for f in range(start, start + width) if (_OPEN_PC_BY_STRING[s] + f) % 12 in in_scale)
            for s in range(1, 7)
        )

    def place(anchor: int, taken: set[tuple[int, int]]) -> tuple[int, int] | None:
        """Window ``(start, width)`` for an anchor, or None if it has no own box.

        The anchor marks a scale degree on the low E string, but the shape's
        lowest note often sits under it on another string — the textbook second
        pentatonic box starts a fret below its own anchor. So the window slides
        down from the anchor and takes the highest placement that leaves no
        string with a single note in it.

        Placements already used by a lower anchor are skipped rather than
        accepted, and the search continues. That matters at the nominal width:
        two neighbouring anchors often share their best four-fret window, and
        stopping there would collapse them into one box. Continuing finds the
        wider placement instead — which is how the third pentatonic box comes
        out as the familiar five-fret stretch shape rather than disappearing.
        """
        for width in (span, span + 1):
            for start in range(anchor, max(anchor - width, -1), -1):
                if coverage(start, width) >= 2 and (start, width) not in taken:
                    return start, width
        return None

    boxes: list[dict[str, Any]] = []
    seen: set[tuple[int, int]] = set()
    for anchor in anchors:
        notes: list[dict[str, Any]] = []
        placed = place(anchor, seen)
        if placed is None:
            continue
        start, width = placed
        seen.add((start, width))
        for string_num in range(6, 0, -1):
            open_pc = _OPEN_PC_BY_STRING[string_num]
            for fret in range(start, start + width):
                pc = (open_pc + fret) % 12
                if pc in in_scale:
                    notes.append({"string": string_num, "fret": fret, "is_root": pc == root_pc})
        frets_only = [n["fret"] for n in notes]
        boxes.append({
            "name": f"position_{len(boxes) + 1}",
            "min_fret": min(frets_only),
            "max_fret": max(frets_only),
            "notes": notes,
        })
    return boxes


# ---------------------------------------------------------------------------
# Scale recognition
# ---------------------------------------------------------------------------

# Built-in interval sets for recognition (don't require YAML loading).
_SCALE_PATTERNS: list[tuple[str, frozenset[int]]] = [
    ("major", frozenset({0, 2, 4, 5, 7, 9, 11})),
    ("natural_minor", frozenset({0, 2, 3, 5, 7, 8, 10})),
    ("harmonic_minor", frozenset({0, 2, 3, 5, 7, 8, 11})),
    ("dorian", frozenset({0, 2, 3, 5, 7, 9, 10})),
    ("mixolydian", frozenset({0, 2, 4, 5, 7, 9, 10})),
    ("phrygian", frozenset({0, 1, 3, 5, 7, 8, 10})),
    ("lydian", frozenset({0, 2, 4, 6, 7, 9, 11})),
    ("minor_pentatonic", frozenset({0, 3, 5, 7, 10})),
    ("major_pentatonic", frozenset({0, 2, 4, 7, 9})),
    ("blues", frozenset({0, 3, 5, 6, 7, 10})),
]


def recognize_scale(
    pitches: list[int],
    *,
    min_notes: int = 4,
) -> ScaleMatch | None:
    """Identify the most likely scale from a sequence of MIDI pitches.

    Strategy:
    1. Extract unique pitch classes from the input.
    2. For each candidate root (0–11), compute how many input pitch classes
       fit each scale pattern.
    3. Return the best match if confidence >= threshold.

    Longer scales (7-note) are preferred over subsets (pentatonic) to avoid
    matching a pentatonic when all 7 diatonic notes are present.

    Args:
        pitches: MIDI note numbers (0–127).
        min_notes: Minimum distinct pitch classes required for recognition.

    Returns:
        ScaleMatch with name, root, and confidence, or None if no match found.
    """
    pitch_classes = frozenset(p % 12 for p in pitches)
    n = len(pitch_classes)
    if n < min_notes:
        return None

    best: ScaleMatch | None = None
    best_score = 0.0

    for root in range(12):
        # Transpose pitch classes so root → 0.
        relative = frozenset((pc - root) % 12 for pc in pitch_classes)

        for scale_name, intervals in _SCALE_PATTERNS:
            # How many of our pitch classes fit this scale?
            matching = len(relative & intervals)
            # How many pitch classes fall outside?
            outside = n - matching
            # Confidence: proportion that fits, penalised for out-of-scale notes.
            if n == 0:
                continue
            confidence = matching / n
            # Require all notes to fit (or at most 1 chromatic passing tone).
            if outside > 1:
                continue

            # Prefer 7-note scales over subsets when both match equally.
            # Tiebreaker: more intervals = more specific match.
            score = confidence * 100.0 + len(intervals) * 0.1

            if score > best_score:
                best_score = score
                best = ScaleMatch(
                    name=scale_name,
                    root=root,
                    root_name=_NOTE_NAMES[root],
                    confidence=confidence,
                )

    # Only return matches with high confidence.
    if best is not None and best.confidence >= 0.75:
        return best
    return None
