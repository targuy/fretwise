"""Phrase-model suggestions must preserve globally coherent playable fingerings."""

from __future__ import annotations

import copy
import json
import os
from collections import defaultdict
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path

import pytest

from fretwise.generator import GeneratorConfig, StateGenerator
from fretwise.ml.phrase_window import LearnedPhraseWindowFingerer, NotePrediction, PhraseNote
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.pipeline import run_pipeline_with_guard_report
from fretwise.scoring import CostFunction, CostWeights

_TUNING = (64, 59, 55, 50, 45, 40)


class _Predictions(LearnedPhraseWindowFingerer):
    """Replace only model inference; retain the real pipeline and physical checks."""

    def __init__(self, predict: Callable[[PhraseNote, int], Finger]) -> None:
        self.predict = predict
        self.calls: list[list[PhraseNote]] = []

    def predict_sequence(self, notes: list[PhraseNote], stride: int = 1) -> list[NotePrediction]:
        self.calls.append(copy.deepcopy(notes))
        out = []
        names = [finger.value for finger in Finger]
        for index, note in enumerate(notes):
            finger = self.predict(note, index)
            probabilities = tuple(.96 if name == finger.value else .01 for name in names)
            out.append(NotePrediction(
                finger=finger.value, probabilities=probabilities,
                anchor=max(1, note.fret - 2), entropy=0.0, n_windows=1,
            ))
        return out


class _RecordingGenerator(StateGenerator):
    def __init__(self, config: GeneratorConfig | None = None) -> None:
        super().__init__(config)
        self.batches: list[tuple[list[list[FingeringState]], list[list[FingeringState]]]] = []

    def states_for_sequence(self, notes: list[NoteEvent]) -> list[list[FingeringState]]:
        states = super().states_for_sequence(notes)
        self.batches.append((states, copy.deepcopy(states)))
        return states


def _note(
    fret: int, onset: float, *, string: int = 4, voice: int = 0,
    duration: float = .5, finger: Finger | None = None, tied: bool = False,
) -> NoteEvent:
    return NoteEvent(
        pitch=_TUNING[string - 1] + fret, onset=onset, duration=duration, tempo=90,
        string_hint=string, fret_hint=fret, voice_hint=voice, source_finger=finger,
        source_note_id=f"v{voice}-s{string}-f{fret}",
        measure_index=int(onset // 4) + 1, is_tie_dest=tied,
    )


def _intro() -> list[NoteEvent]:
    """Seven repeated-note plateaus reproducing the reported timing, not a GP fixture."""
    return [
        _note(fret, bar * 4 + strike * .5)
        for bar, fret in enumerate((10, 10, 7, 7, 10, 8, 7))
        for strike in range(8)
    ]


def _reported_prediction(note: PhraseNote, _: int) -> Finger:
    measure, strike = int(note.onset // 4) + 1, int(note.onset % 4 * 2)
    if measure == 3:
        return Finger.INDEX if strike < 2 else Finger.RING
    if measure == 6:
        return Finger.RING if strike == 0 else Finger.MIDDLE
    if measure == 7:
        return Finger.MIDDLE if strike == 0 else Finger.RING
    return Finger.RING


def _costs(results: list[FingeringResult], cost: CostFunction) -> dict[int, float]:
    totals: dict[int, float] = defaultdict(float)
    previous: dict[int, FingeringState] = {}
    for result in sorted(results, key=lambda row: (row.note_event.onset, row.note_id)):
        voice = result.note_event.voice_hint or 0
        prior = previous.get(voice)
        totals[voice] += (
            cost.emission_cost(result.state) if prior is None
            else cost.transition_cost(prior, result.state, result.note_event)
        )
        previous[voice] = result.state
    return dict(totals)


def _assert_plateaus_stable(results: list[FingeringResult]) -> None:
    for measure in (3, 6, 7):
        notes = [row for row in results if row.note_event.measure_index == measure]
        assert len(notes) == 8
        assert len({row.state.finger for row in notes}) == 1, (
            measure, [row.state.finger for row in notes],
        )


def test_reported_intro_swaps_do_not_override_lower_cost_stable_path() -> None:
    events = _intro()
    original = copy.deepcopy(events)
    cost = CostFunction(weights=CostWeights.performance())
    baseline = run_pipeline_with_guard_report(events, StateGenerator(), ViterbiOptimizer(cost))
    model = _Predictions(_reported_prediction)
    actual = run_pipeline_with_guard_report(
        events, StateGenerator(), ViterbiOptimizer(cost), phrase_window_fingerer=model,
    )
    assert model.calls, "Regression must actually exercise the model proposal"
    _assert_plateaus_stable(actual.results)
    assert _costs(actual.results, cost)[0] <= _costs(baseline.results, cost)[0] + 1e-9
    assert actual.biomechanical_report.fatal_count == 0
    assert len(actual.results) == len(events)
    assert events == original
    assert [(r.state.string_num, r.state.fret) for r in actual.results] == [
        (event.string_hint, event.fret_hint) for event in events
    ]


def test_phrase_model_cannot_mutate_generator_candidates_or_source_locks() -> None:
    events = [_note(7, index * .5, finger=Finger.MIDDLE) for index in range(8)]
    generator = _RecordingGenerator(GeneratorConfig(source_finger_policy="lock"))
    model = _Predictions(lambda note, index: Finger.INDEX if index % 2 else Finger.RING)
    actual = run_pipeline_with_guard_report(
        events, generator, ViterbiOptimizer(CostFunction()), phrase_window_fingerer=model,
    )
    assert model.calls
    assert all(result.state.finger == Finger.MIDDLE for result in actual.results)
    for live, snapshot in generator.batches:
        assert live == snapshot, "Post-processing corrupted original admissible candidates"
        allowed = {id(state) for states in live for state in states}
        assert all(id(result.state) not in allowed for result in actual.results)


def test_proposal_keeps_chord_contacts_ties_and_separate_voice_identities() -> None:
    events = [
        _note(5, 0, string=2),
        _note(7, 0, string=3, voice=1),
        _note(5, 1, string=2, duration=1),
        _note(5, 2, string=2, duration=1, tied=True),
        _note(7, 3, string=2),
        _note(7, 1.5, string=3, voice=1),
        _note(7, 2.5, string=3, voice=1),
        _note(5, 3.5, string=3, voice=1),
    ]
    cost = CostFunction(weights=CostWeights.performance())
    baseline = run_pipeline_with_guard_report(events, StateGenerator(), ViterbiOptimizer(cost))
    actual = run_pipeline_with_guard_report(
        events, StateGenerator(), ViterbiOptimizer(cost),
        phrase_window_fingerer=_Predictions(lambda note, index: Finger.RING),
    )
    assert sorted(id(row.note_event) for row in actual.results) == sorted(map(id, events))
    by_event = {id(row.note_event): row for row in actual.results}
    for row in baseline.results:
        if row.note_event.onset == 0:
            assert by_event[id(row.note_event)].state == row.state
    assert by_event[id(events[2])].state == by_event[id(events[3])].state
    assert actual.biomechanical_report.fatal_count == 0
    for voice, total in _costs(actual.results, cost).items():
        assert total <= _costs(baseline.results, cost)[voice] + 1e-9


def test_real_phrase_v2_keeps_intro_plateaus_stable_when_bundle_available() -> None:
    pytest.importorskip("onnxruntime")
    models = Path(os.environ.get(
        "FRETWISE_TEST_MODEL_DIR", str(Path(__file__).parents[1] / "data/models"),
    ))
    manifest = models / "phrase_window_fingering_v2_manifest.json"
    if not manifest.exists():
        pytest.skip("Phrase v2 model bundle unavailable")
    heads = json.loads(manifest.read_text(encoding="utf-8"))["heads"].values()
    if not all((models / head).exists() for head in heads):
        pytest.skip("Phrase v2 ONNX heads unavailable")
    model = LearnedPhraseWindowFingerer.from_model_dir(models, version="v2")
    events = _intro()
    cost = CostFunction(weights=CostWeights.performance())
    baseline = run_pipeline_with_guard_report(events, StateGenerator(), ViterbiOptimizer(cost))
    actual = run_pipeline_with_guard_report(
        events, StateGenerator(), ViterbiOptimizer(cost), phrase_window_fingerer=model,
    )
    _assert_plateaus_stable(actual.results)
    assert _costs(actual.results, cost)[0] <= _costs(baseline.results, cost)[0] + 1e-9
    assert actual.biomechanical_report.fatal_count == 0


class _FingerCost:
    """Small injected M4 objective with an explicit cost for changing contact."""

    def __init__(self, index: float, middle: float, change: float = 0) -> None:
        self.costs = {Finger.INDEX: index, Finger.MIDDLE: middle}
        self.change = change

    def emission_cost(self, state: FingeringState) -> float:
        return self.costs.get(state.finger, 10)

    def transition_cost(
        self, previous: FingeringState, current: FingeringState,
        note: NoteEvent, index: int | None = None,
    ) -> float:
        return self.emission_cost(current) + self.change * (previous.finger != current.finger)


def _arbitration_rows() -> tuple[
    list[FingeringResult], list[FingeringResult], dict[int, list[FingeringState]],
]:
    events = [_note(5, i * .5) for i in range(5)]
    baseline = [
        FingeringResult(i, note, FingeringState(4, 5, Finger.INDEX, 5), 0)
        for i, note in enumerate(events)
    ]
    proposals = [replace(row, state=FingeringState(4, 5, Finger.MIDDLE, 5)) for row in baseline]
    candidates = {
        id(row.note_event): [copy.copy(row.state), copy.copy(proposal.state)]
        for row, proposal in zip(baseline, proposals)
    }
    return baseline, proposals, candidates


@pytest.mark.parametrize(
    ("index_cost", "middle_cost", "expected"),
    [(3, 1, Finger.MIDDLE), (1, 3, Finger.INDEX), (1, 1, Finger.INDEX)],
    ids=["better-model-accepted", "worse-model-rejected", "neutral-keeps-baseline"],
)
def test_sequence_arbitration_accepts_only_global_cost_improvement(
    index_cost: float, middle_cost: float, expected: Finger,
) -> None:
    from fretwise.phrase_arbitration import arbitrate_phrase_proposals

    baseline, proposals, candidates = _arbitration_rows()
    before = copy.deepcopy((baseline, proposals, candidates))
    outcome = arbitrate_phrase_proposals(
        baseline, proposals, candidates, _FingerCost(index_cost, middle_cost),
    )
    assert all(row.state.finger == expected for row in outcome.results)
    assert (baseline, proposals, candidates) == before
    assert [id(row.note_event) for row in outcome.results] == [
        id(row.note_event) for row in baseline
    ]


def test_sequence_cost_includes_entry_and_exit_of_short_model_proposal() -> None:
    from fretwise.phrase_arbitration import arbitrate_phrase_proposals

    baseline, proposals, candidates = _arbitration_rows()
    proposals[0] = copy.deepcopy(baseline[0])
    proposals[-1] = copy.deepcopy(baseline[-1])
    # Keep the same note identities, as required by any source-preserving proposal.
    proposals[0].note_event = baseline[0].note_event
    proposals[-1].note_event = baseline[-1].note_event
    cost = _FingerCost(index=2, middle=0, change=10)
    outcome = arbitrate_phrase_proposals(baseline, proposals, candidates, cost)
    # Three locally cheaper notes save 6, but entering/exiting costs 20.
    assert [row.state.finger for row in outcome.results] == [Finger.INDEX] * 5


@pytest.mark.parametrize("roundoff", [0.0, -5e-10], ids=["exact", "floating-roundoff"])
def test_cheaper_prefix_compensated_at_phrase_end_keeps_whole_baseline(roundoff: float) -> None:
    from fretwise.phrase_arbitration import arbitrate_phrase_proposals

    baseline, proposals, candidates = _arbitration_rows()
    proposals[-1] = replace(baseline[-1], state=replace(baseline[-1].state))
    # Four middle notes save 8, then returning to the last index costs 8.
    # A numerical residue must not turn this equal-cost path into an improvement.
    cost = _FingerCost(index=3, middle=1, change=8 + roundoff)
    outcome = arbitrate_phrase_proposals(baseline, proposals, candidates, cost)
    assert [row.state for row in outcome.results] == [row.state for row in baseline]
    assert outcome.applied == 0


def test_old_algorithm_sidecar_is_stale_until_recomputed(tmp_path: Path) -> None:
    from fretwise.web.app import (
        FINGERING_ALGO_VERSION,
        _fingering_meta_is_current,
        _read_fingering_meta,
        _write_fingering_sidecar,
    )

    source = tmp_path / "synthetic.gp"
    source.write_bytes(b"Synthetic file used only for metadata freshness")
    old = {"algo_version": "2.1", "source_mtime": source.stat().st_mtime}
    assert FINGERING_ALGO_VERSION == "2.4"
    assert not _fingering_meta_is_current(old, source)
    baseline, _, _ = _arbitration_rows()
    assert _write_fingering_sidecar(source, baseline, track_id=3)
    current = _read_fingering_meta(source)
    assert current is not None
    assert current["algo_version"] == FINGERING_ALGO_VERSION
    assert _fingering_meta_is_current(current, source)
