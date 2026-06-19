"""Tests for ``_measure_beats_array`` — the per-measure beat counts the web app
ships so the playback engine can place every measure at its true start.

Background: the multi-track player used a single scalar ``beats_per_measure`` and
reconstructed each measure's start as ``floor(onset / bpm) * bpm``. That drifts
after any meter change or short (pickup) bar, desyncing the cursor from the audio
and the tracks from each other. Shipping the real per-measure beat counts fixes
it. These tests pin the contract of the helper that produces that array.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from fretwise.web.app import _measure_beats_array


def _events(*measure_indices: int) -> list[Any]:
    """Minimal note-like objects carrying just ``measure_index``."""
    return [SimpleNamespace(measure_index=mi) for mi in measure_indices]


def _adapter(mts: dict[int, tuple[int, int]] | None, bpm: float = 4.0) -> Any:
    return SimpleNamespace(measure_time_signatures=mts, beats_per_measure=bpm)


def test_meter_change_returns_per_measure_quarter_beats() -> None:
    """4/4 → 2/4 → 4/4 yields [4.0, 2.0, 4.0] in quarter-note beats."""
    adapter = _adapter({1: (4, 4), 2: (2, 4), 3: (4, 4)})
    assert _measure_beats_array(adapter, _events(1, 2, 3)) == [4.0, 2.0, 4.0]


def test_compound_meter_uses_quarter_beats_not_numerator() -> None:
    """6/8 is 3.0 quarter beats (num * 4 / den), not 6."""
    adapter = _adapter({1: (6, 8)}, bpm=3.0)
    assert _measure_beats_array(adapter, _events(1)) == [3.0]


def test_sparse_signatures_carry_forward() -> None:
    """Measures absent from the dict inherit the last stated signature."""
    # Only measures 1 and 3 are stated; 2 and 4 carry forward 4/4 then 3/4.
    adapter = _adapter({1: (4, 4), 3: (3, 4)})
    assert _measure_beats_array(adapter, _events(1, 2, 3, 4)) == [4.0, 4.0, 3.0, 3.0]


def test_array_extends_to_last_measure_with_notes() -> None:
    """The array spans every measure that has notes, even past the last signature."""
    adapter = _adapter({1: (3, 4)})
    # Notes reach measure 3 although only measure 1's signature is stated.
    assert _measure_beats_array(adapter, _events(1, 3)) == [3.0, 3.0, 3.0]


def test_no_signatures_returns_empty_for_uniform_fallback() -> None:
    """No per-measure signatures (MusicXML/MIDI) ⇒ [] ⇒ frontend keeps uniform bpm."""
    assert _measure_beats_array(_adapter(None), _events(1, 2)) == []
    assert _measure_beats_array(_adapter({}), _events(1, 2)) == []


def test_anacrusis_short_bar_is_honoured() -> None:
    """A pickup bar encoded as a short signature shifts every later measure start.

    1/4 pickup then 4/4 ⇒ measure starts 0, 1, 5, 9 — none on a 4-beat grid, which
    is exactly the case ``floor(onset/4)*4`` got wrong.
    """
    adapter = _adapter({1: (1, 4), 2: (4, 4)})
    beats = _measure_beats_array(adapter, _events(1, 2, 3, 4))
    assert beats == [1.0, 4.0, 4.0, 4.0]
    # Prefix sums = true measure starts: not multiples of 4 after the pickup.
    starts, acc = [], 0.0
    for b in beats:
        starts.append(acc)
        acc += b
    assert starts == [0.0, 1.0, 5.0, 9.0]


def test_signatures_beyond_notes_still_counted() -> None:
    """Trailing measures that have a signature but no notes are still sized."""
    adapter = _adapter({1: (4, 4), 2: (4, 4), 3: (2, 4)})
    # Notes only in measure 1, but signatures define 3 measures.
    assert _measure_beats_array(adapter, _events(1)) == [4.0, 4.0, 2.0]
