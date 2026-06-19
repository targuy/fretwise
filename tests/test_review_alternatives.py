"""Tests for ``fretwise.review.alternatives`` — windowed diversified re-solve."""
from __future__ import annotations

import inspect

from fretwise.generator import StateGenerator
from fretwise.models import NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.pipeline import run_pipeline_with_guard_report
from fretwise.review.alternatives import measure_alternatives
from fretwise.scoring import CostFunction, CostWeights


def _events() -> list[NoteEvent]:
    """Two measures of un-hinted notes (free string/fret → real choices)."""
    events: list[NoteEvent] = []
    pitches = [60, 62, 64, 65]
    onset = 0.0
    for measure in (1, 2):
        for p in pitches:
            events.append(
                NoteEvent(pitch=p, onset=onset, duration=0.5, tempo=120.0,
                          measure_index=measure, voice_hint=0)
            )
            onset += 0.5
    return events


def _solve(events: list[NoteEvent]):
    cost_fn = CostFunction(weights=CostWeights.performance())
    return run_pipeline_with_guard_report(
        events, StateGenerator(), ViterbiOptimizer(cost_fn),
    )


def test_alternatives_first_is_current() -> None:
    events = _events()
    payload = _solve(events)
    alts = measure_alternatives(events, payload.results, measure_index=2)
    assert alts
    assert alts[0].is_current is True
    assert alts[0].label == "Actuel"


def test_alternatives_are_distinct_and_capped() -> None:
    events = _events()
    payload = _solve(events)
    alts = measure_alternatives(events, payload.results, measure_index=2)
    assert len(alts) <= 4
    signatures = {
        tuple(sorted((f["string"], f["fret"], f["finger"]) for f in a.fingerings))
        for a in alts
    }
    assert len(signatures) == len(alts)  # every variant is distinct


def test_alternatives_only_cover_target_measure() -> None:
    events = _events()
    payload = _solve(events)
    alts = measure_alternatives(events, payload.results, measure_index=2)
    target_notes = {
        round(r.note_event.onset, 6)
        for r in payload.results if r.note_event.measure_index == 2
    }
    for a in alts:
        onsets = {round(float(f["onset"]), 6) for f in a.fingerings}
        assert onsets <= target_notes


def test_alternatives_unknown_measure_returns_empty() -> None:
    events = _events()
    payload = _solve(events)
    assert measure_alternatives(events, payload.results, measure_index=99) == []


def test_proposed_alternatives_are_all_playable() -> None:
    """Unplayable/impossible candidates must never be proposed. The current
    solution (variant #1) is exempt — it is the thing being reviewed."""
    events = _events()
    payload = _solve(events)
    alts = measure_alternatives(events, payload.results, measure_index=2)
    for a in alts:
        if not a.is_current:
            assert a.playable is True


def test_m5_viterbi_interface_unchanged() -> None:
    """Guard: the feature must never alter the M5 public contract."""
    init_params = list(inspect.signature(ViterbiOptimizer.__init__).parameters)
    assert init_params == ["self", "cost_fn"]
    solve_params = list(inspect.signature(ViterbiOptimizer.solve).parameters)
    assert solve_params == ["self", "notes", "state_lists"]
