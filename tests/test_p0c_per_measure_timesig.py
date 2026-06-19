"""P0-C failing tests for per-measure time signature in completed_to_canonical_score().

These tests are intentionally RED — the fix (measure_time_signatures field on
CompletedScore and its use in mappers.py) does not exist yet.  They define the
expected contract so the implementation can be written TDD-style.

Bug summary:
    completed_to_canonical_score() uses a single global beats_per_measure for all
    measures.  Songs that change meter (e.g. 3/4 → 4/4) produce phantom rests
    because measure boundaries are calculated with the wrong duration.

Expected fix:
    1. CompletedScore gains an optional field:
           measure_time_signatures: dict[int, tuple[int, int]] = {}
       The key is the 1-based measure number; the value is (numerator, denominator).
    2. mappers.py reads this dict per-measure and passes the correct beats_per_measure
       to _inject_implicit_rests and stores the correct TimeSignature on each Measure.
    3. The grouping of NoteEvents into measures continues to prefer note.measure_index
       when available; when absent it falls back to onset // per_measure_beats.
"""

from __future__ import annotations

import pytest

from fretwise.core.canonical.models import (
    RestEvent as CanonicalRestEvent,
)
from fretwise.core.canonical.mappers import completed_to_canonical_score
from fretwise.core.ingest.models import CompletedScore
from fretwise.models import Articulation, Dynamic, NoteEvent


# ---------------------------------------------------------------------------
# Factory helpers
# ---------------------------------------------------------------------------

def _make_note(
    pitch: int,
    onset: float,
    duration: float,
    *,
    measure_index: int | None = None,
    voice_hint: int | None = 0,
) -> NoteEvent:
    """Create a minimal NoteEvent for mapper tests."""
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=1,       # force guitar transposition (+12) path
        fret_hint=0,
        voice_hint=voice_hint,
        measure_index=measure_index,
    )


def _all_events(score_result) -> list:
    """Flatten all events from a canonical Score into a single list."""
    events = []
    for track in score_result.tracks:
        for sg in track.staff_groups:
            for staff in sg.staves:
                for measure in staff.measures:
                    for voice in measure.voices:
                        events.extend(voice.events)
    return events


def _measures(score_result) -> list:
    """Return all Measure objects from a canonical Score."""
    measures = []
    for track in score_result.tracks:
        for sg in track.staff_groups:
            for staff in sg.staves:
                measures.extend(staff.measures)
    return measures


# ---------------------------------------------------------------------------
# P0-C-01 — CompletedScore accepts measure_time_signatures field (default: {})
# ---------------------------------------------------------------------------

def test_completed_score_accepts_measure_time_signatures_field() -> None:
    """CompletedScore must have a measure_time_signatures field defaulting to {}."""
    score = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=[],
    )
    # Field must exist and default to empty dict
    assert hasattr(score, "measure_time_signatures")
    assert score.measure_time_signatures == {}


# ---------------------------------------------------------------------------
# P0-C-02 — measure_time_signatures accepts a non-empty dict
# ---------------------------------------------------------------------------

def test_completed_score_measure_time_signatures_accepts_dict() -> None:
    """CompletedScore(measure_time_signatures={1: (4, 4), 2: (3, 4)}) must not raise."""
    score = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=[],
        measure_time_signatures={1: (4, 4), 2: (3, 4)},
    )
    assert score.measure_time_signatures == {1: (4, 4), 2: (3, 4)}


# ---------------------------------------------------------------------------
# P0-C-03 — Fallback: empty measure_time_signatures uses global beats_per_measure
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_fallback_to_global_bpm() -> None:
    """When measure_time_signatures is empty, the global 4/4 is used for all measures."""
    notes = [
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 4.0, 1.0, measure_index=2),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,
        time_denominator=4,
        measure_time_signatures={},
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)
    for m in all_m:
        assert m.time_signature.numerator == 4
        assert m.time_signature.denominator == 4


# ---------------------------------------------------------------------------
# P0-C-04 — Per-measure time signatures are stored on each Measure
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_per_measure_time_signatures() -> None:
    """Measures with explicit entries in measure_time_signatures get correct time sigs."""
    # 3 notes in 4/4 (measure 1, beats 0-3), then 2 notes in 3/4 (measure 2, beats 0-2)
    notes = [
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
        _make_note(65, 4.0, 1.5, measure_index=2),
        _make_note(67, 5.5, 1.5, measure_index=2),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,   # global default (4/4)
        time_denominator=4,
        measure_time_signatures={
            1: (4, 4),
            2: (3, 4),
        },
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)

    # Measure 1 must be 4/4
    m1 = next(m for m in all_m if m.number == 1)
    assert m1.time_signature.numerator == 4
    assert m1.time_signature.denominator == 4

    # Measure 2 must be 3/4
    m2 = next(m for m in all_m if m.number == 2)
    assert m2.time_signature.numerator == 3
    assert m2.time_signature.denominator == 4


# ---------------------------------------------------------------------------
# P0-C-05 — No phantom rests in a 3/4 measure when global default is 4/4
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_no_phantom_rest_in_3_4_measure() -> None:
    """A 3/4 measure containing exactly 3 beats of notes must produce no rest events.

    Bug: without the fix, the injector thinks the measure is 4 beats long and
    appends a 1-beat phantom rest at the end.
    """
    notes = [
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,   # global is 4/4, but measure 1 is 3/4
        time_denominator=4,
        measure_time_signatures={1: (3, 4)},
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)
    m1 = next(m for m in all_m if m.number == 1)

    rest_events = [
        e
        for voice in m1.voices
        for e in voice.events
        if isinstance(e, CanonicalRestEvent)
    ]
    assert rest_events == [], (
        f"Phantom rests found in 3/4 measure: {rest_events}"
    )


# ---------------------------------------------------------------------------
# P0-C-06 — Total event duration in measure equals the per-measure beats count
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_total_duration_matches_timesig() -> None:
    """Sum of all event durations in a measure must equal its beats_per_measure.

    This is the precise check that phantom rests inflate the sum.
    Tested for both a 4/4 measure and a 3/4 measure in the same score.
    """
    notes = [
        # Measure 1: 3 quarter notes filling 3/4
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
        # Measure 2: 4 quarter notes filling 4/4
        _make_note(65, 3.0, 1.0, measure_index=2),
        _make_note(67, 4.0, 1.0, measure_index=2),
        _make_note(69, 5.0, 1.0, measure_index=2),
        _make_note(71, 6.0, 1.0, measure_index=2),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,
        time_denominator=4,
        measure_time_signatures={
            1: (3, 4),
            2: (4, 4),
        },
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)

    m1 = next(m for m in all_m if m.number == 1)
    m2 = next(m for m in all_m if m.number == 2)

    total_dur_m1 = sum(
        e.duration for voice in m1.voices for e in voice.events
    )
    total_dur_m2 = sum(
        e.duration for voice in m2.voices for e in voice.events
    )

    assert total_dur_m1 == pytest.approx(3.0, abs=1e-9), (
        f"3/4 measure total duration should be 3.0 beats, got {total_dur_m1}"
    )
    assert total_dur_m2 == pytest.approx(4.0, abs=1e-9), (
        f"4/4 measure total duration should be 4.0 beats, got {total_dur_m2}"
    )


# ---------------------------------------------------------------------------
# P0-C-07 — Grouping via measure_index (not onset arithmetic)
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_groups_by_measure_index_when_available() -> None:
    """NoteEvents with measure_index set must be grouped by that index, not by onset.

    This matters for 3/4 measures: without measure_index, onset 3.0 // 4.0 = 0
    would place the second measure's notes in measure 1.
    """
    notes = [
        # Measure 1 (3/4): onsets 0, 1, 2
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
        # Measure 2 (4/4): onsets 3, 4, 5, 6
        # Without measure_index and with global bpm=4, onset 3 → measure_idx 0 (wrong!)
        _make_note(65, 3.0, 1.0, measure_index=2),
        _make_note(67, 4.0, 1.0, measure_index=2),
        _make_note(69, 5.0, 1.0, measure_index=2),
        _make_note(71, 6.0, 1.0, measure_index=2),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,
        time_denominator=4,
        measure_time_signatures={1: (3, 4), 2: (4, 4)},
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)

    m1 = next(m for m in all_m if m.number == 1)
    m2 = next(m for m in all_m if m.number == 2)

    note_count_m1 = sum(
        1
        for voice in m1.voices
        for e in voice.events
        if not isinstance(e, CanonicalRestEvent)
    )
    note_count_m2 = sum(
        1
        for voice in m2.voices
        for e in voice.events
        if not isinstance(e, CanonicalRestEvent)
    )

    assert note_count_m1 == 3, f"Measure 1 should have 3 notes, got {note_count_m1}"
    assert note_count_m2 == 4, f"Measure 2 should have 4 notes, got {note_count_m2}"


# ---------------------------------------------------------------------------
# P0-C-08 — Denominator is propagated correctly (e.g. 6/8)
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_denominator_6_8() -> None:
    """measure_time_signatures=(6, 8) must produce Measure.time_signature with denom=8."""
    # 6/8 = 6 eighth notes = 3 beats (if beat = quarter note)
    # beats_per_measure in the model is in quarter-note beats → 3.0 for 6/8
    notes = [
        _make_note(60, 0.0, 0.5, measure_index=1),
        _make_note(62, 0.5, 0.5, measure_index=1),
        _make_note(64, 1.0, 0.5, measure_index=1),
        _make_note(65, 1.5, 0.5, measure_index=1),
        _make_note(67, 2.0, 0.5, measure_index=1),
        _make_note(69, 2.5, 0.5, measure_index=1),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=3.0,   # global fallback (3 quarter-note beats = 6/8)
        time_denominator=8,
        measure_time_signatures={1: (6, 8)},
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)
    m1 = next(m for m in all_m if m.number == 1)
    assert m1.time_signature.numerator == 6
    assert m1.time_signature.denominator == 8


# ---------------------------------------------------------------------------
# P0-C-09 — Mixed meter: measures not in the dict use the global fallback
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_mixed_meter_unlisted_uses_global() -> None:
    """Measures absent from measure_time_signatures fall back to the global time sig."""
    notes = [
        # Measure 1: 3/4 (explicit)
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
        # Measure 2: uses global (4/4) — NOT in measure_time_signatures
        _make_note(65, 3.0, 1.0, measure_index=2),
        _make_note(67, 4.0, 1.0, measure_index=2),
        _make_note(69, 5.0, 1.0, measure_index=2),
        _make_note(71, 6.0, 1.0, measure_index=2),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,   # global = 4/4
        time_denominator=4,
        measure_time_signatures={1: (3, 4)},  # only measure 1 overridden
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)

    m2 = next(m for m in all_m if m.number == 2)
    assert m2.time_signature.numerator == 4
    assert m2.time_signature.denominator == 4


# ---------------------------------------------------------------------------
# P0-C-10 — Two consecutive time signature changes in same score
# ---------------------------------------------------------------------------

def test_completed_to_canonical_score_two_consecutive_sig_changes() -> None:
    """Three different time signatures in three consecutive measures all resolve correctly."""
    notes = [
        # Measure 1: 4/4 (4 beats)
        _make_note(60, 0.0, 1.0, measure_index=1),
        _make_note(62, 1.0, 1.0, measure_index=1),
        _make_note(64, 2.0, 1.0, measure_index=1),
        _make_note(65, 3.0, 1.0, measure_index=1),
        # Measure 2: 3/4 (3 beats)
        _make_note(67, 4.0, 1.0, measure_index=2),
        _make_note(69, 5.0, 1.0, measure_index=2),
        _make_note(71, 6.0, 1.0, measure_index=2),
        # Measure 3: 2/4 (2 beats)
        _make_note(72, 7.0, 1.0, measure_index=3),
        _make_note(74, 8.0, 1.0, measure_index=3),
    ]
    completed = CompletedScore(
        source_path="test.gp5",
        source_format="gp5",
        notes=notes,
        beats_per_measure=4.0,
        time_denominator=4,
        measure_time_signatures={
            1: (4, 4),
            2: (3, 4),
            3: (2, 4),
        },
    )
    canonical = completed_to_canonical_score(completed)
    all_m = _measures(canonical)

    m1 = next(m for m in all_m if m.number == 1)
    m2 = next(m for m in all_m if m.number == 2)
    m3 = next(m for m in all_m if m.number == 3)

    assert (m1.time_signature.numerator, m1.time_signature.denominator) == (4, 4)
    assert (m2.time_signature.numerator, m2.time_signature.denominator) == (3, 4)
    assert (m3.time_signature.numerator, m3.time_signature.denominator) == (2, 4)

    # Also verify no phantom rests in any of the three measures
    for measure, expected_beats in [(m1, 4.0), (m2, 3.0), (m3, 2.0)]:
        total = sum(e.duration for voice in measure.voices for e in voice.events)
        assert total == pytest.approx(expected_beats, abs=1e-9), (
            f"Measure {measure.number} ({expected_beats} beats): got total {total}"
        )
