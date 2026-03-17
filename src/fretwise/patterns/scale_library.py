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
class BoxPosition:
    """A single fretboard box position for a scale.

    Attributes:
        name: Label such as "box_1" or "position_1".
        root_string: String number (1–6) where root falls.
        root_fret: Fret offset relative to the key root for this box.
        pattern: Per-string fret offsets relative to hand position.
            ``pattern[0]`` = string 6 (low E), ``pattern[5]`` = string 1 (high E).
    """

    name: str
    root_string: int
    root_fret: int
    pattern: tuple[tuple[int, ...], ...]


@dataclass(frozen=True)
class ScaleDefinition:
    """A scale type with its interval structure and box positions.

    Attributes:
        name: Scale name (e.g. "major", "minor_pentatonic").
        intervals: Frozenset of semitone intervals from root (pitch classes).
        positions: Available box positions on the fretboard.
    """

    name: str
    intervals: frozenset[int]
    positions: tuple[BoxPosition, ...] = ()


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
        positions: list[BoxPosition] = []
        for pos in entry.get("positions", []):
            raw_pattern = pos.get("pattern", [])
            pattern = tuple(tuple(s) for s in raw_pattern)
            positions.append(BoxPosition(
                name=pos.get("name", ""),
                root_string=pos.get("root_string", 6),
                root_fret=pos.get("root_fret", 0),
                pattern=pattern,
            ))
        library[name] = ScaleDefinition(
            name=name,
            intervals=intervals,
            positions=tuple(positions),
        )

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
