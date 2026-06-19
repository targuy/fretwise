"""Tests for ``fretwise.audit`` — pure module (no ONNX required)."""
from __future__ import annotations

from fretwise.audit import AuditReport, audit_score, split_by_movement
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _ev(measure: int, onset: float | None = None, pitch: int = 60) -> NoteEvent:
    """Synthetic NoteEvent. Default onset = float(measure - 1) so the source
    density signal stays realistic (not all notes piled at onset 0)."""
    if onset is None:
        onset = float(measure - 1)
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=0.5,
        tempo=120.0,
        measure_index=measure,
    )


# Two far-apart hand positions; alternating them per note makes every transition
# a large position shift → high *marginal* cost (the audit now scores marginal,
# not the cumulative FingeringResult.cost, so costliness must come from states).
_FAR_POS = [
    (1, 17, Finger.PINKY, 14),
    (6, 1, Finger.INDEX, 1),
]
_CHEAP_POS = (3, 5, Finger.INDEX, 5)


def _result(
    note_id: int, measure: int, cost: float = 1.0, voice: int = 0,
    *, costly: bool = False,
) -> FingeringResult:
    event = NoteEvent(
        pitch=60, onset=float(note_id), duration=0.5, tempo=120.0,
        measure_index=measure, voice_hint=voice,
    )
    s, f, fg, hp = _FAR_POS[note_id % 2] if costly else _CHEAP_POS
    state = FingeringState(string_num=s, fret=f, finger=fg, hand_position=hp)
    return FingeringResult(
        note_id=note_id, note_event=event, state=state,
        cost=cost, alternatives=[],
    )


# ---------------------------------------------------------------------------
# split_by_movement
# ---------------------------------------------------------------------------


def test_split_empty_events_returns_empty() -> None:
    assert split_by_movement([]) == []


def test_split_no_markers_no_silent_gaps_returns_whole_piece() -> None:
    events = [_ev(measure=m) for m in range(1, 9)]  # measures 1..8 all sound
    spans = split_by_movement(events)
    assert len(spans) == 1
    assert spans[0].source == "whole_piece"
    assert spans[0].measure_start == 1
    assert spans[0].measure_end == 8


def test_split_implicit_silent_gap_of_2_measures_splits() -> None:
    # measures 1, 2, 3 then gap 4-5 silent then 6, 7
    events = [_ev(m) for m in (1, 2, 3, 6, 7)]
    spans = split_by_movement(events, silent_measure_threshold=2)
    assert len(spans) == 2
    assert spans[0].source == "implicit"
    assert (spans[0].measure_start, spans[0].measure_end) == (1, 3)
    assert (spans[1].measure_start, spans[1].measure_end) == (6, 7)


def test_split_implicit_single_silent_measure_does_not_split() -> None:
    # gap of just 1 silent measure (4) — should NOT trigger a break.
    events = [_ev(m) for m in (1, 2, 3, 5, 6)]
    spans = split_by_movement(events, silent_measure_threshold=2)
    assert len(spans) == 1
    assert spans[0].source == "whole_piece"


def test_split_explicit_markers_take_precedence() -> None:
    events = [_ev(m) for m in (1, 2, 3, 6, 7, 10, 11)]
    markers = {1: "Allegro", 6: "Adagio", 10: "Presto"}
    spans = split_by_movement(events, section_markers=markers)
    assert len(spans) == 3
    assert [s.name for s in spans] == ["Allegro", "Adagio", "Presto"]
    assert all(s.source == "explicit" for s in spans)
    assert (spans[0].measure_start, spans[0].measure_end) == (1, 5)
    assert (spans[1].measure_start, spans[1].measure_end) == (6, 9)
    assert (spans[2].measure_start, spans[2].measure_end) == (10, 11)


def test_split_explicit_marker_after_intro_adds_intro_span() -> None:
    # Notes start at measure 1 but first marker is at measure 5 → "Intro"
    # span 1-4 prepended.
    events = [_ev(m) for m in (1, 2, 5, 6)]
    markers = {5: "Allegro"}
    spans = split_by_movement(events, section_markers=markers)
    assert [s.name for s in spans] == ["Intro", "Allegro"]
    assert (spans[0].measure_start, spans[0].measure_end) == (1, 4)


def test_split_threshold_zero_disables_implicit() -> None:
    # threshold=0 means even gap=0 is a break — every pair of non-consecutive
    # measures triggers a split. Use threshold=1 to keep one-silent-measure
    # gaps from splitting; threshold=0 is intentionally aggressive.
    events = [_ev(m) for m in (1, 3, 5)]
    spans = split_by_movement(events, silent_measure_threshold=1)
    assert len(spans) == 3


# ---------------------------------------------------------------------------
# audit_score — no ML model
# ---------------------------------------------------------------------------


def test_audit_clean_short_piece_no_ml() -> None:
    events = [_ev(m) for m in range(1, 5)]
    results = [_result(i, measure=m) for i, m in enumerate(range(1, 5))]
    report = audit_score(events, results)
    assert isinstance(report, AuditReport)
    assert report.overall == "clean"
    assert report.ml_signal_available is False
    assert len(report.movements) == 1
    assert report.movements[0].verdict == "clean"
    assert report.movements[0].reasons == []
    assert report.biomechanical_report is not None
    assert report.biomechanical_report.is_clean


def test_audit_biomechanical_fatal_marks_movement_bad() -> None:
    event = NoteEvent(
        pitch=60,
        onset=0.0,
        duration=0.5,
        tempo=120.0,
        measure_index=1,
    )
    invalid = FingeringResult(
        note_id=0,
        note_event=event,
        state=FingeringState(
            string_num=3,
            fret=5,
            finger=Finger.OPEN,
            hand_position=5,
        ),
        cost=1.0,
    )

    report = audit_score([event], [invalid])

    assert report.overall == "bad"
    assert report.biomechanical_report is not None
    assert report.biomechanical_report.fatal_count == 1
    assert report.movements[0].verdict == "bad"
    assert "biomechanical_fatal" in report.movements[0].reasons


def test_audit_half_high_cost_alone_stays_clean() -> None:
    # 10 notes, 4 expensive (ratio 0.40 < SUSPECT 0.50). Per the
    # conservative cascade, anything below "majority expensive"
    # without source/ML co-signal stays clean.
    events = [_ev(m) for m in range(1, 11)]
    results = [_result(i, i + 1, costly=(i >= 6)) for i in range(10)]  # 4/10
    report = audit_score(events, results)
    assert report.movements[0].verdict == "clean"


def test_audit_high_cost_alone_flags_suspect_not_bad() -> None:
    # 10 notes, 8 expensive (ratio 0.80 ≥ BAD 0.75 → cost_red).
    # One red signal alone (no ML, no source) lands at "suspect", not
    # "bad" — the strong combined verdict requires cost_red AND ml_red.
    events = [_ev(m) for m in range(1, 11)]
    results = [_result(i, i + 1, costly=(i >= 2)) for i in range(10)]  # 8/10
    report = audit_score(events, results)
    assert report.movements[0].verdict == "suspect"
    assert "high_cost_density" in report.movements[0].reasons


def test_audit_cost_red_and_ml_red_together_flag_bad() -> None:
    # Both algorithmic red (8/10 high cost) AND ML red (uniform softmax)
    # → strong combined signal → bad.
    events = [_ev(m) for m in range(1, 11)]
    results = [_result(i, i + 1, costly=(i >= 2)) for i in range(10)]  # 8/10
    report = audit_score(events, results, ml_cost_model=_StubMLModel())
    assert report.movements[0].verdict == "bad"
    assert "high_cost_density" in report.movements[0].reasons
    assert "ml_uncertain" in report.movements[0].reasons


def test_audit_per_movement_isolation_explicit_markers() -> None:
    # Movement 1 (m 1-3): clean. Movement 2 (m 4-6): all expensive.
    events = [_ev(m) for m in (1, 2, 3, 4, 5, 6)]
    results = [
        _result(0, 1),
        _result(1, 2),
        _result(2, 3),
        _result(3, 4, costly=True),
        _result(4, 5, costly=True),
        _result(5, 6, costly=True),
    ]
    markers = {1: "Easy", 4: "Hard"}
    report = audit_score(events, results, section_markers=markers)
    assert len(report.movements) == 2
    assert report.movements[0].verdict == "clean"
    assert report.movements[1].verdict in ("suspect", "bad")
    assert report.overall in ("suspect", "bad")
    assert len(report.bad_movements) == (
        1 if report.movements[1].verdict == "bad" else 0
    )


def test_audit_empty_movement_returns_clean() -> None:
    # An explicit marker span with no notes inside should not crash.
    events = [_ev(m) for m in (1, 2, 10, 11)]
    markers = {1: "First", 5: "Empty", 10: "Third"}
    results = [_result(i, m) for i, m in enumerate((1, 2, 10, 11))]
    report = audit_score(events, results, section_markers=markers)
    empty_movement = [m for m in report.movements if m.note_count == 0]
    assert empty_movement, "Expected an empty Empty movement"
    assert empty_movement[0].verdict == "clean"
    assert empty_movement[0].reasons == []


# ---------------------------------------------------------------------------
# audit_score — with mocked ML model
# ---------------------------------------------------------------------------


class _StubMLModel:
    """PlayerCostModel double exposing only ``_predict_probs``.

    Returns a uniform softmax = max entropy (2.32 bits for 5 classes) so the
    audit sees every transition as "uncertain."
    """

    def _predict_probs(self, **kwargs):
        return [0.2, 0.2, 0.2, 0.2, 0.2]


class _ConfidentMLModel:
    """One-hot prediction → entropy ≈ 0; audit should see "confident"."""

    def _predict_probs(self, **kwargs):
        return [0.0, 1.0, 0.0, 0.0, 0.0]


def test_audit_with_ml_uniform_flags_uncertain() -> None:
    events = [_ev(m) for m in (1, 2, 3, 4, 5)]
    results = [_result(i, m) for i, m in enumerate((1, 2, 3, 4, 5))]
    report = audit_score(events, results, ml_cost_model=_StubMLModel())
    assert report.ml_signal_available is True
    movement = report.movements[0]
    # Uniform softmax = 2.32 bits >> 1.0 threshold → all transitions uncertain.
    assert movement.signals.get("ml_median_entropy", 0) > 1.0
    assert movement.signals.get("ml_uncertain_ratio", 0) >= 0.4
    assert "ml_uncertain" in movement.reasons


def test_audit_with_ml_confident_does_not_flag() -> None:
    events = [_ev(m) for m in (1, 2, 3, 4, 5)]
    results = [_result(i, m) for i, m in enumerate((1, 2, 3, 4, 5))]
    report = audit_score(events, results, ml_cost_model=_ConfidentMLModel())
    assert report.ml_signal_available is True
    movement = report.movements[0]
    assert movement.signals.get("ml_median_entropy", 0) < 0.5
    assert "ml_uncertain" not in movement.reasons
    assert "ml_borderline" not in movement.reasons


def test_audit_ml_model_exception_is_swallowed() -> None:
    """A broken model must never break the audit."""
    class _Broken:
        def _predict_probs(self, **kwargs):
            raise RuntimeError("boom")

    events = [_ev(m) for m in (1, 2, 3)]
    results = [_result(i, m) for i, m in enumerate((1, 2, 3))]
    report = audit_score(events, results, ml_cost_model=_Broken())
    assert report.ml_signal_available is True
    # No entropy values were collected, so no ml_* reasons should fire.
    assert "ml_uncertain" not in report.movements[0].reasons
    assert "ml_borderline" not in report.movements[0].reasons


# ---------------------------------------------------------------------------
# Smoke test: AuditReport JSON-serialisability (dataclasses → dict)
# ---------------------------------------------------------------------------


def test_audit_report_dataclasses_are_serialisable() -> None:
    """Verifies the dataclass shape is friendly to a future JSON endpoint."""
    import dataclasses

    events = [_ev(m) for m in (1, 2, 3)]
    results = [_result(i, m) for i, m in enumerate((1, 2, 3))]
    report = audit_score(events, results)
    payload = dataclasses.asdict(report)
    assert "movements" in payload
    assert "overall" in payload
    assert payload["overall"] in ("clean", "suspect", "bad")
    assert isinstance(payload["movements"], list)
