"""Tests for ``_measure_tempo_array`` — the per-measure tempo the web app ships
so the playback engine can place every measure at its true wall-clock time.

Background: the player reconstructed the whole timeline from a single scalar
tempo (``events[0].tempo``). Any mid-song tempo change (a ritardando, a faster
chorus) then desynced the cursor and audio from the music — the dominant cause
of the tracks drifting apart. Shipping the real per-measure tempo fixes it.
These tests pin the contract of the helper that produces that array.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fretwise.web.app import _measure_tempo_array


def _events(*pairs: tuple[int, float]) -> list[Any]:
    """Minimal note-like objects carrying ``measure_index`` and ``tempo``."""
    return [SimpleNamespace(measure_index=mi, tempo=t) for mi, t in pairs]


def test_constant_tempo_returns_flat_array() -> None:
    """One tempo throughout ⇒ that tempo per measure."""
    evs = _events((1, 120.0), (2, 120.0), (3, 120.0))
    assert _measure_tempo_array(None, evs) == [120.0, 120.0, 120.0]


def test_first_event_of_measure_wins() -> None:
    """The tempo in force at the downbeat is the measure's tempo (first wins)."""
    evs = _events((1, 120.0), (1, 999.0), (2, 90.0))
    assert _measure_tempo_array(None, evs) == [120.0, 90.0]


def test_tempo_change_is_reflected_per_measure() -> None:
    """A mid-song tempo change shows up on the exact measure it starts."""
    evs = _events((1, 120.0), (2, 120.0), (3, 80.0), (4, 80.0))
    assert _measure_tempo_array(None, evs) == [120.0, 120.0, 80.0, 80.0]


def test_measures_without_tempo_carry_forward() -> None:
    """A rest bar (no event, or a zero/absent tempo) inherits the last tempo."""
    # Measure 2 has no event at all; it must carry forward measure 1's tempo.
    evs = _events((1, 100.0), (3, 140.0))
    assert _measure_tempo_array(None, evs) == [100.0, 100.0, 140.0]


def test_zero_or_missing_tempo_is_ignored() -> None:
    """Non-positive tempos don't set a measure; the carry-forward value stands."""
    evs = _events((1, 120.0), (2, 0.0), (3, 60.0))
    assert _measure_tempo_array(None, evs) == [120.0, 120.0, 60.0]


def test_no_events_returns_empty() -> None:
    """No notes ⇒ [] ⇒ frontend keeps its single scalar tempo fallback."""
    assert _measure_tempo_array(None, []) == []


def test_no_usable_tempo_returns_empty() -> None:
    """Events present but no positive tempo anywhere ⇒ [] (uniform fallback)."""
    evs = _events((1, 0.0), (2, 0.0))
    assert _measure_tempo_array(None, evs) == []
