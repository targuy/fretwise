"""Cost-aware sequence arbitration between rule fingerings and ML proposals.

M5 remains unchanged: each voice is solved over a restricted union of the
baseline and admissible proposed states. A final whole-hand check may reject
the proposal, but must never replace a valid baseline with a costlier path.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite

from fretwise.hand_planning import plan_hand_configurations
from fretwise.models import FingeringResult, FingeringState
from fretwise.optimizer import CostFunctionProtocol, ViterbiOptimizer


@dataclass(frozen=True)
class PhraseArbitrationResult:
    """Accepted sequence and counts distinguishing proposals from applied changes."""

    results: list[FingeringResult]
    proposed: int = 0
    applied: int = 0
    hand_plan_changed: int = 0
    hand_plan_expanded: int = 0
    fallback: bool = False


def copy_fingering_results(results: Sequence[FingeringResult]) -> list[FingeringResult]:
    """Copy mutable decisions without copying the authoritative score events."""
    return [
        replace(
            result,
            state=replace(result.state),
            alternatives=[(replace(state), cost) for state, cost in result.alternatives],
            planted_fingers=dict(result.planted_fingers),
        )
        for result in results
    ]


def _voice_costs(
    results: Sequence[FingeringResult], cost_fn: CostFunctionProtocol,
) -> dict[int, float]:
    previous: dict[int, FingeringState] = {}
    counts: dict[int, int] = defaultdict(int)
    totals: dict[int, float] = defaultdict(float)
    for result in sorted(results, key=lambda row: (row.note_event.onset, row.note_id)):
        voice = result.note_event.voice_hint or 0
        prior = previous.get(voice)
        local = (
            cost_fn.emission_cost(result.state) if prior is None
            else cost_fn.transition_cost(
                prior, result.state, result.note_event, index=counts[voice],
            )
        )
        totals[voice] += local
        previous[voice] = result.state
        counts[voice] += 1
    return dict(totals)


def arbitrate_phrase_proposals(
    baseline: Sequence[FingeringResult],
    proposals: Sequence[FingeringResult],
    candidates: Mapping[int, Sequence[FingeringState]],
    cost_fn: CostFunctionProtocol,
) -> PhraseArbitrationResult:
    """Select an admissible, physically valid path no costlier than the baseline.

    Args:
        baseline: Complete rule sequence, already checked by the hand planner.
        proposals: ML decisions in baseline order, preserving score identities.
        candidates: Original admissible states keyed by ``id(note_event)``.
            These snapshots include source and user locks and are never edited.
        cost_fn: Active M4 objective, with temporary segment anchors cleared.

    Returns:
        A copied baseline or an accepted sequence. Costs include the first
        emission and every transition in each voice, including phrase edges.
        A cheaper voice cannot compensate for a more expensive other voice.
    """
    if len(baseline) != len(proposals) or any(
        base.note_id != proposal.note_id or base.note_event is not proposal.note_event
        for base, proposal in zip(baseline, proposals)
    ):
        raise ValueError("Phrase proposals must preserve all baseline score identities")
    saved = copy_fingering_results(baseline)
    proposed = sum(base.state != row.state for base, row in zip(saved, proposals))
    if not proposed:
        return PhraseArbitrationResult(saved)
    if any(row.state not in candidates.get(id(row.note_event), ()) for row in saved):
        return PhraseArbitrationResult(saved, proposed=proposed, fallback=True)

    # A chord remains the complete rule proposal, also when spread across voices.
    onset_counts = Counter(
        (row.note_event.measure_index, round(row.note_event.onset, 6)) for row in saved
    )
    options: dict[int, list[FingeringState]] = {}
    voices: dict[int, list[int]] = defaultdict(list)
    for index, (base, proposal) in enumerate(zip(saved, proposals)):
        choices = [replace(base.state)]  # deterministic baseline preference on ties
        state = proposal.state
        key = base.note_event.measure_index, round(base.note_event.onset, 6)
        if (
            onset_counts[key] == 1
            and state != base.state
            and state.string_num == base.state.string_num
            and state.fret == base.state.fret
            and state.hand_position == base.state.hand_position
            and state in candidates[id(base.note_event)]
        ):
            choices.append(replace(state))
        options[id(base.note_event)] = choices
        voices[base.note_event.voice_hint or 0].append(index)

    selected = copy_fingering_results(saved)
    optimizer = ViterbiOptimizer(cost_fn)
    baseline_costs = _voice_costs(saved, cost_fn)
    for voice, indices in voices.items():
        indices.sort(key=lambda index: (saved[index].note_event.onset, saved[index].note_id))
        path = optimizer.solve(
            [saved[index].note_event for index in indices],
            [options[id(saved[index].note_event)] for index in indices],
        )
        # A cheaper prefix can tie the baseline after a later transition.
        # Prefer the complete baseline on ties, not only the first local state.
        if path[-1].cost >= baseline_costs[voice] - 1e-9:
            continue
        for index, result in zip(indices, path):
            selected[index] = replace(
                saved[index], state=replace(result.state), cost=result.cost,
                alternatives=[], planted_fingers={},
            )

    if all(base.state == row.state for base, row in zip(saved, selected)):
        return PhraseArbitrationResult(saved, proposed=proposed)

    # Temporal occupations and ties can couple voices even though their M4
    # paths are independent. Repairs have only the same restricted choices.
    planned = plan_hand_configurations(selected, options, cost_fn)
    if planned.status != "valid":
        return PhraseArbitrationResult(
            saved, proposed=proposed, hand_plan_expanded=planned.expanded_states, fallback=True,
        )
    final_costs = _voice_costs(planned.results, cost_fn)
    if any(
        not isfinite(final_costs[voice]) or not isfinite(cost)
        or final_costs[voice] > cost + 1e-9
        for voice, cost in baseline_costs.items()
    ):
        return PhraseArbitrationResult(
            saved, proposed=proposed, hand_plan_expanded=planned.expanded_states, fallback=True,
        )
    final_by_id = {row.note_id: row for row in planned.results}
    final = [final_by_id[row.note_id] for row in saved]
    applied = sum(base.state != row.state for base, row in zip(saved, final))
    return PhraseArbitrationResult(
        copy_fingering_results(final), proposed, applied,
        planned.changed_notes, planned.expanded_states,
    )
