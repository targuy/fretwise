"""Tests for the source-quality assessment module."""
from __future__ import annotations

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.quality import assess_source_quality


def _note(idx: int, pitch: int = 64, string_hint: int | None = None,
          fret_hint: int | None = None) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=float(idx),
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=string_hint,
        fret_hint=fret_hint,
    )


def test_empty_returns_bad() -> None:
    report = assess_source_quality([])
    assert report.is_bad
    assert "empty" in report.rationale.lower()


def test_clean_simple_sequence() -> None:
    events = [_note(i, pitch=64 + i, string_hint=1, fret_hint=i) for i in range(10)]
    report = assess_source_quality(events)
    assert report.is_clean
    assert report.pitch_hint_conflicts == 0


def test_pitch_hint_conflict_flagged_as_suspect_low_rate() -> None:
    events = [_note(i, pitch=64, string_hint=1, fret_hint=0) for i in range(100)]
    # Inject one bad event: string 1 fret 5 should give pitch 69, not 64
    events[50] = _note(50, pitch=64, string_hint=1, fret_hint=5)
    report = assess_source_quality(events)
    assert report.pitch_hint_conflicts == 1
    # 1/100 = 1% — threshold is "bad" at >= 1%
    assert report.is_bad


def test_pitch_hint_conflict_under_threshold_is_clean() -> None:
    events = [_note(i, pitch=64, string_hint=1, fret_hint=0) for i in range(500)]
    events[100] = _note(100, pitch=64, string_hint=1, fret_hint=5)
    report = assess_source_quality(events)
    assert report.pitch_hint_conflicts == 1
    # 1/500 = 0.2% — under bad threshold, minor flag → clean
    assert report.is_clean
    assert "minor" in report.rationale


def test_very_high_fret_count_three_is_suspect() -> None:
    # pitch must match (string 1 = pitch 64 at fret 0), so compute correctly
    events = [_note(i, pitch=64 + 25 + i, string_hint=1, fret_hint=25 + i) for i in range(3)]
    events.extend([_note(10 + i, pitch=64, string_hint=1, fret_hint=0) for i in range(50)])
    report = assess_source_quality(events)
    assert report.very_high_fret_count == 3
    assert report.pitch_hint_conflicts == 0
    # 3 high frets alone = suspect flag, no other flags → clean (minor)
    assert report.is_clean


def test_very_high_fret_count_four_is_bad() -> None:
    events = [_note(i, pitch=64 + 25 + i, string_hint=1, fret_hint=25 + i) for i in range(4)]
    events.extend([_note(10 + i, pitch=64, string_hint=1, fret_hint=0) for i in range(50)])
    report = assess_source_quality(events)
    assert report.pitch_hint_conflicts == 0
    assert report.is_bad
    assert ">" in report.rationale


def test_excessive_chord_span_flagged() -> None:
    events = []
    # Build 6 chords with span > 5 at distinct onsets
    for i in range(6):
        events.append(_note(i, pitch=64, string_hint=1, fret_hint=2))
        events.append(_note(i, pitch=80, string_hint=6, fret_hint=10))
        # Override onset for chord-grouping
        events[-1].onset = float(i)
        events[-2].onset = float(i)
    # 6 chord spans of 8 frets each → bad
    report = assess_source_quality(events)
    assert report.excessive_chord_span_count == 6
    assert report.is_bad
