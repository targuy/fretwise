"""Regression tests for P2 layout bugs: dense passages, measure overflow.

These tests cover:
- raw_measure_width growing with note density (Test 1)
- Standard mode wider than TAB mode for dense passages (Test 2)
- canonical_to_page_layout producing adequate measure widths in standard mode (Test 3)
- Full Aigle Noir pipeline, measures 77+ beat counts (Test 4 — skipped if fixture absent)
- No EventLayout.x exceeds its MeasureLayout right bound (Test 5)
"""

from __future__ import annotations

from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Test 1 — raw_measure_width grows with note density
# ---------------------------------------------------------------------------


def test_raw_measure_width_grows_with_note_density() -> None:
    """Plus il y a d'onsets, plus la mesure est large."""
    from fretwise.core.layout.rules import default_layout_rules, raw_measure_width

    rules = default_layout_rules()

    sparse = [0.0, 2.0]  # 2 quarter notes in 4/4
    dense = [i * 0.25 for i in range(16)]  # 16 sixteenth notes

    w_sparse = raw_measure_width(sparse, 4, rules)
    w_dense = raw_measure_width(dense, 4, rules)

    assert w_dense > w_sparse, (
        f"Dense ({w_dense:.1f}) should be wider than sparse ({w_sparse:.1f})"
    )


# ---------------------------------------------------------------------------
# Test 2 — standard mode produces wider measures than TAB for dense passages
# ---------------------------------------------------------------------------


def test_standard_mode_wider_than_tab_for_dense_passage() -> None:
    """En mode standard, les mesures denses doivent être plus larges qu'en TAB."""
    from dataclasses import replace

    from fretwise.core.layout.rules import LayoutRules, default_layout_rules, raw_measure_width

    dense_onsets = [i * 0.25 for i in range(16)]

    rules_tab = default_layout_rules()
    rules_std = replace(rules_tab, space_per_beat=48.0, min_note_width=20.0)

    w_tab = raw_measure_width(dense_onsets, 4, rules_tab)
    w_std = raw_measure_width(dense_onsets, 4, rules_std)

    assert w_std > w_tab, (
        f"Standard mode ({w_std:.1f}) should be wider than TAB mode ({w_tab:.1f})"
    )
    assert w_std >= 360.0, (
        f"16 sixteenth notes in standard mode should be ≥360px, got {w_std:.1f}px"
    )


# ---------------------------------------------------------------------------
# Test 3 — canonical_to_page_layout produces adequate widths in standard mode
# ---------------------------------------------------------------------------


def test_canonical_page_layout_standard_mode_adequate_width() -> None:
    """En mode standard, chaque mesure doit avoir au moins 150px."""
    from fretwise.core.canonical.models import (
        Measure,
        NoteEvent,
        Score,
        Staff,
        StaffGroup,
        TempoMark,
        TimeSignature,
        Track,
        Voice,
    )
    from fretwise.core.layout.builders import canonical_to_page_layout

    # Build a measure of 8 eighth notes
    notes = [
        NoteEvent(
            event_id=f"n{i}",
            onset=float(i) * 0.5,
            duration=0.5,
            voice=0,
            pitch_notated=64,
            pitch_sounding=64,
        )
        for i in range(8)
    ]
    measure = Measure(
        number=1,
        time_signature=TimeSignature(numerator=4, denominator=4),
        voices=[Voice(number=0, events=notes)],
    )
    staff = Staff(staff_id="s1", clef="treble", measures=[measure])
    score = Score(
        score_id="sc1",
        title="test",
        tracks=[
            Track(
                track_id="t1",
                name="Guitar",
                staff_groups=[
                    StaffGroup(group_id="g1", name="main", staves=[staff])
                ],
            )
        ],
        tempo_marks=[TempoMark(onset=0.0, bpm=120.0)],
    )

    page = canonical_to_page_layout(score, mode="standard")
    system = page.systems[0]
    measure_layout = system.staves[0].measure_layouts[0]

    assert measure_layout.width >= 150.0, (
        f"Measure in standard mode should be ≥150px, got {measure_layout.width:.1f}px"
    )


# ---------------------------------------------------------------------------
# Test 4 — Aigle Noir full pipeline (skipped if fixture absent)
# ---------------------------------------------------------------------------

_AIGLE_CANDIDATES: list[Path] = list(Path("tests/fixtures").rglob("*[Aa]igle*"))


@pytest.mark.skipif(
    not _AIGLE_CANDIDATES,
    reason="Aigle Noir fixture not present in tests/fixtures/",
)
def test_aigle_noir_no_overflow_in_standard_mode() -> None:
    """Aigle Noir mesures 77+ doivent avoir le bon nombre de temps."""
    filepath = _AIGLE_CANDIDATES[0]
    ext = filepath.suffix.lower()

    if ext != ".gp":
        pytest.skip("Aigle Noir only tested with .gp format")

    from fretwise.parser.gpif_adapter import GpifAdapter

    adapter = GpifAdapter(str(filepath))
    adapter.parse()

    from fretwise.core.canonical.mappers import completed_to_canonical_score
    from fretwise.core.complete.pipeline import run_completion
    from fretwise.core.ingest.adapters import legacy_parse_to_raw_score
    from fretwise.core.normalize.pipeline import run_normalization

    raw = legacy_parse_to_raw_score(
        filepath,
        source_format="gp",
        events=adapter.notes,
        beats_per_measure=adapter.beats_per_measure,
        measure_time_signatures=getattr(adapter, "measure_time_signatures", {}) or {},
    )
    normalized = run_normalization(raw)
    completed = run_completion(normalized)
    canonical = completed_to_canonical_score(completed)

    track = canonical.tracks[0]
    staff = track.staff_groups[0].staves[0]
    measures_by_number = {m.number: m for m in staff.measures}

    # Measures 77+ should be 3/4 (3 quarter beats)
    if 77 in measures_by_number:
        m77 = measures_by_number[77]
        ts = m77.time_signature
        beats = ts.numerator * 4 // ts.denominator
        assert beats == 3, (
            f"Measure 77 should be 3 beats, got {beats} ({ts.numerator}/{ts.denominator})"
        )

    # No event duration should exceed its measure's beat count (with 1 cent tolerance)
    for m in staff.measures:
        if m.number < 77:
            continue
        ts = m.time_signature
        measure_beats = ts.numerator * 4 // ts.denominator
        for v in m.voices:
            for e in v.events:
                assert e.duration <= measure_beats + 0.01, (
                    f"Event {e.event_id!r} in M{m.number} has duration {e.duration}"
                    f" > measure_beats {measure_beats}"
                )


# ---------------------------------------------------------------------------
# Test 5 — Layout bounds: no event x exceeds its measure right bound
# ---------------------------------------------------------------------------


def test_event_layout_x_within_measure_bounds() -> None:
    """Aucun EventLayout.x ne doit dépasser x + width de sa MeasureLayout."""
    from fretwise.core.canonical.models import (
        Measure,
        NoteEvent,
        Score,
        Staff,
        StaffGroup,
        TempoMark,
        TimeSignature,
        Track,
        Voice,
    )
    from fretwise.core.layout.builders import canonical_to_page_layout

    # Dense score: 16 sixteenth notes spread across two voices
    all_notes = [
        NoteEvent(
            event_id=f"n{i}",
            onset=float(i) * 0.25,
            duration=0.25,
            voice=i % 2,
            pitch_notated=60 + i % 12,
            pitch_sounding=60 + i % 12,
        )
        for i in range(16)
    ]
    measure = Measure(
        number=1,
        time_signature=TimeSignature(numerator=4, denominator=4),
        voices=[
            Voice(number=0, events=[n for n in all_notes if n.voice == 0]),
            Voice(number=1, events=[n for n in all_notes if n.voice == 1]),
        ],
    )
    staff = Staff(staff_id="s1", clef="treble", measures=[measure])
    score = Score(
        score_id="sc1",
        title="test",
        tracks=[
            Track(
                track_id="t1",
                name="Guitar",
                staff_groups=[
                    StaffGroup(group_id="g1", name="main", staves=[staff])
                ],
            )
        ],
        tempo_marks=[TempoMark(onset=0.0, bpm=120.0)],
    )

    page = canonical_to_page_layout(score, mode="standard_tablature")
    for system in page.systems:
        for staff_layout in system.staves:
            for ml in staff_layout.measure_layouts:
                right_bound = ml.x + ml.width + 5.0  # 5px tolerance
                for el in ml.event_layouts:
                    assert el.x <= right_bound, (
                        f"Event {el.event_id!r} x={el.x:.1f} exceeds measure right bound"
                        f" {right_bound:.1f} (measure {ml.measure_number},"
                        f" measure_x={ml.x:.1f}, width={ml.width:.1f})"
                    )
