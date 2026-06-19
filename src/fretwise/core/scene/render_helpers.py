"""Pure render utility functions extracted from scene/builders.py.

These functions are stateless (no shared mutable state, no closures) and
operate only on their arguments. They can be tested independently.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Duration utilities
# ---------------------------------------------------------------------------

_KNOWN_BASE_DURATIONS: tuple[float, ...] = (
    8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625
)


def duration_components(duration: float) -> tuple[float, int]:
    """Return (base_duration, dot_count) for a rhythmic duration value."""
    tol = 0.01
    for base in _KNOWN_BASE_DURATIONS:
        if abs(duration - base) <= tol:
            return base, 0
        if abs(duration - base * 1.5) <= tol:
            return base, 1
        if abs(duration - base * 1.75) <= tol:
            return base, 2
    return duration, 0


def base_duration(duration: float) -> float:
    """Return the base (un-dotted) value of a duration."""
    return duration_components(duration)[0]


def dot_count(duration: float) -> int:
    """Return the number of augmentation dots for a duration (0, 1, or 2)."""
    return duration_components(duration)[1]


def flag_count(duration: float) -> int:
    """Return the number of flags/beams for a note duration."""
    b = base_duration(duration)
    if b >= 1.0:
        return 0
    if b >= 0.5:
        return 1
    if b >= 0.25:
        return 2
    return 3


def duration_class(duration: float) -> str:
    """Return a string name for the rhythmic duration class."""
    b = base_duration(duration)
    if b >= 4.0:
        return "whole"
    if b >= 2.0:
        return "half"
    if b >= 1.0:
        return "quarter"
    if b >= 0.5:
        return "eighth"
    if b >= 0.25:
        return "sixteenth"
    if b >= 0.125:
        return "thirty_second"
    return "sixty_fourth"


def rest_kind(duration: float, *, is_measure_rest: bool = False) -> str:
    """Return the glyph kind string for a rest."""
    if is_measure_rest:
        return "whole"
    return duration_class(duration)


def notated_duration(
    actual: float,
    tuplet_actual: int | None,
    tuplet_normal: int | None,
) -> float:
    """Return the display duration for flag-count and beam-level computation.

    For a triplet 8th (actual≈0.333, tuplet_actual=3, tuplet_normal=2):
    returns 0.333 × (3/2) = 0.5 (the display 8th-note base).
    """
    if tuplet_actual and tuplet_normal and tuplet_normal > 0:
        return actual * tuplet_actual / tuplet_normal
    return actual


def is_filled_notehead(duration: float) -> bool:
    """Return True if the notehead should be filled (quarter or shorter)."""
    return base_duration(duration) <= 1.0


def is_measure_rest_event(
    onset: float,
    duration: float,
    *,
    measure_number: int,
    beats_per_measure: int,
) -> bool:
    """Return True if the event spans a full measure (whole-bar rest display)."""
    tolerance = 1e-6
    measure_start = (measure_number - 1) * beats_per_measure
    onset_in_measure = onset - measure_start
    return (
        abs(onset_in_measure) <= tolerance
        and abs(duration - beats_per_measure) <= 0.01
    )


# ---------------------------------------------------------------------------
# Boolean helpers
# ---------------------------------------------------------------------------

def boolish(value: object) -> bool:
    """Coerce a string-ish metadata value to bool."""
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def safe_int(value: str | None) -> int | None:
    """Parse an optional string to int; return None on failure."""
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Stem helpers
# ---------------------------------------------------------------------------

def stem_direction(voice_number: int) -> str:
    """Return 'down' for voice ≥ 1, 'up' otherwise."""
    return "down" if voice_number >= 1 else "up"


def stem_x_for_notehead(x: float, *, direction: str, stem_offset: float) -> float:
    """Return the stem attachment X given notehead centre and stem direction."""
    if direction == "down":
        return x - stem_offset
    return x + stem_offset
