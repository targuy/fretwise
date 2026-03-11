"""Chord recognition from MIDI pitch sets.

Given a collection of MIDI pitches (or pitch classes), identifies the most
likely chord name (e.g. "Am", "G7", "Fmaj7").

Strategy:
  1. Try exact match — pitch classes match the pattern exactly.
  2. Try subset match — pitch classes are a subset of the pattern AND at least
     3 pitch classes are present (incomplete voicing / arpeggio window).
  Patterns are ordered: 4-note chords first, then triads.  Within equal
  priority, common chords (major, minor) are preferred over exotic ones.
"""

from __future__ import annotations

from collections.abc import Iterable

_NOTE_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# (intervals relative to root as sorted tuple) → chord suffix
# Ordered: 4-note first, then triads, simpler chords preferred within each group.
_CHORD_PATTERNS: list[tuple[tuple[int, ...], str]] = [
    ((0, 3, 6, 9), "dim7"),
    ((0, 4, 7, 11), "maj7"),
    ((0, 3, 7, 10), "m7"),
    ((0, 4, 7, 10), "7"),
    ((0, 3, 7, 11), "mM7"),
    ((0, 4, 7, 9), "6"),
    ((0, 3, 7, 9), "m6"),
    ((0, 2, 7), "sus2"),
    ((0, 5, 7), "sus4"),
    ((0, 4, 7), ""),       # major — no suffix
    ((0, 3, 7), "m"),      # minor
    ((0, 4, 8), "aug"),
    ((0, 3, 6), "dim"),
]


def recognize_chord(pitches: Iterable[int]) -> str | None:
    """Return chord name for a collection of MIDI pitches, or None if unknown.

    Args:
        pitches: Any iterable of MIDI note numbers (0–127).

    Returns:
        Chord name string such as "Am", "G7", "Fmaj7", or None.
    """
    pitch_classes = frozenset(p % 12 for p in pitches)
    n = len(pitch_classes)
    if n < 2:
        return None

    # Exact match: all pitch classes match the pattern exactly.
    for intervals, suffix in _CHORD_PATTERNS:
        for root in range(12):
            candidate = frozenset((root + i) % 12 for i in intervals)
            if candidate == pitch_classes:
                return _NOTE_NAMES[root] + suffix

    # Subset match: our pitch classes are a subset of the pattern.
    # Require at least 3 pitch classes to avoid false positives.
    if n >= 3:
        for intervals, suffix in _CHORD_PATTERNS:
            for root in range(12):
                candidate = frozenset((root + i) % 12 for i in intervals)
                if pitch_classes < candidate:  # strict subset
                    return _NOTE_NAMES[root] + suffix

    return None
