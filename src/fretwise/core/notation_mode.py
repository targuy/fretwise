"""Centralized notation mode definitions.

Single source of truth for all mode-dependent logic on the backend.
Consumers should import helper functions from here rather than duplicating
set membership tests or hardcoded mode string comparisons.

Design note — no circular import
---------------------------------
This module intentionally does **not** import from ``fretwise.core.graphics``
or ``fretwise.core.scene``/``fretwise.core.layout``, because those packages
mutually depend on each other.  The canonical string values defined here
mirror those in ``RepresentationMode`` (StrEnum in
``fretwise.core.graphics.notation_policy``); they are kept in sync by
convention — the strings are stable public API.
"""

from __future__ import annotations

__all__ = [
    "ALL_MODES",
    "has_standard",
    "has_tab",
    "is_valid_mode",
    "system_height_for_mode",
]

# ---------------------------------------------------------------------------
# Canonical mode string constants
# ---------------------------------------------------------------------------
# These mirror RepresentationMode (StrEnum) values from notation_policy.py.
# Do NOT import that enum here — it triggers graphics/__init__.py which
# creates a circular import through the scene ↔ layout ↔ graphics chain.

_MODE_STANDARD: str = "standard"
_MODE_TAB: str = "tablature"
_MODE_STANDARD_TAB: str = "standard_tablature"
_MODE_TAB_RHYTHM: str = "tablature_rhythm"

ALL_MODES: tuple[str, ...] = (
    _MODE_STANDARD,
    _MODE_TAB,
    _MODE_STANDARD_TAB,
    _MODE_TAB_RHYTHM,
)

_MODES_WITH_TAB: frozenset[str] = frozenset(
    {_MODE_TAB, _MODE_TAB_RHYTHM, _MODE_STANDARD_TAB}
)
_MODES_WITH_STANDARD: frozenset[str] = frozenset(
    {_MODE_STANDARD, _MODE_STANDARD_TAB}
)


def has_tab(mode: str) -> bool:
    """Return True when *mode* includes a tablature staff.

    Args:
        mode: Notation mode string (e.g. ``"tablature"``, ``"standard_tablature"``).

    Returns:
        ``True`` for ``tablature``, ``tablature_rhythm``, and ``standard_tablature``.
    """
    return mode in _MODES_WITH_TAB


def has_standard(mode: str) -> bool:
    """Return True when *mode* includes a standard-notation staff.

    Args:
        mode: Notation mode string.

    Returns:
        ``True`` for ``standard`` and ``standard_tablature``.
    """
    return mode in _MODES_WITH_STANDARD


def is_valid_mode(mode: str) -> bool:
    """Return True when *mode* is a known notation mode string.

    Args:
        mode: Candidate mode string.

    Returns:
        ``True`` if *mode* is one of the four canonical values.
    """
    return mode in ALL_MODES


def system_height_for_mode(mode: str) -> float:
    """Return the ``system_height`` layout rule value for *mode*.

    Args:
        mode: Notation mode string.

    Returns:
        Appropriate system height in layout units.  ``standard_tablature``
        (the default) returns ``190.0`` to accommodate staff + gap + tab +
        rhythm zone plus tuplet brackets above beamed passages.
        ``standard``-only needs ``96.0`` for the same upper-bracket clearance.
        ``tablature`` and ``tablature_rhythm`` use ``130.0``.
    """
    if mode == _MODE_STANDARD:
        return 96.0
    if mode in (_MODE_TAB, _MODE_TAB_RHYTHM):
        return 130.0
    return 190.0  # standard_tablature (default)
