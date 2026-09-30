"""Shared written-duration and optional let-ring contact boundaries."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from math import inf, isfinite

from fretwise.models import FingeringResult


def required_contact_ends(results: Sequence[FingeringResult]) -> dict[int, float]:
    """Return absolute minimum release beats, including complete tied chains.

    Keys identify score occurrences, not reusable Guitar Pro source note IDs.
    An optional let-ring extension can end after this boundary; a written
    duration or a tied continuation cannot be shortened by the hand planner.
    """
    return required_tie_ends(
        (
            result.note_id, result.note_event.onset, result.note_event.duration,
            result.note_event.voice_hint or 0,
            result.note_event.string_hint or result.state.string_num,
            result.note_event.pitch, result.note_event.is_tie_dest,
        )
        for result in results
    )


def required_tie_ends(
    records: Iterable[tuple[int, float, float, int, int, int, bool]],
) -> dict[int, float]:
    """Resolve tied minima from (key, onset, duration, voice, string, pitch, tie)."""
    ends: dict[int, float] = {}
    following: dict[tuple[int, int], tuple[int, float, int, bool]] = {}
    for key, onset, duration, voice, string, pitch, tie in sorted(
        records, key=lambda row: (row[1], row[0]), reverse=True,
    ):
        end = onset + duration
        successor = following.get((voice, string))
        if successor is not None:
            next_key, next_onset, next_pitch, next_tie = successor
            if next_tie and next_pitch == pitch and next_onset > onset:
                end = max(end, ends[next_key])
        ends[key] = end
        following[(voice, string)] = (key, onset, pitch, tie)
    return ends


def contact_end(result: FingeringResult, required_end: float | None = None) -> float:
    """Return a contact end without trusting a release before written music ends.

    Unbounded let-ring keeps the historical sustain-until-rearticulation
    behavior. Invalid/non-finite explicit bounds never suppress a contact;
    the biomechanical validator reports them separately.
    """
    note = result.note_event
    minimum = max(note.onset + note.duration, required_end or -inf)
    if not note.let_ring:
        return minimum
    release = result.let_ring_end
    if release is None or not isfinite(release):
        return inf
    return max(minimum, release)
