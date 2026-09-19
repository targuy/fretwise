"""Bounded joint fingering search outside the immutable M5 interface.

The legacy per-voice solver supplies preferences. This layer admits only
compatible whole-hand contacts, including notes held by other voices. It is a
discrete fingering planner, not an anatomical or continuous-motion certificate.
An exhausted beam means search failed, never proof that a passage is impossible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from math import isfinite

from fretwise.biomechanics import (
    BiomechanicalSeverity,
    sounding_occupations,
    validate_contact_configuration,
    validate_fingering_results,
)
from fretwise.models import FingeringResult, FingeringState
from fretwise.optimizer import CostFunctionProtocol


@dataclass(frozen=True)
class HandPlanningResult:
    """Joint-search result with complete-sequence alternatives and honest status."""

    results: list[FingeringResult]
    status: str
    changed_notes: int = 0
    expanded_states: int = 0
    alternatives: tuple[tuple[FingeringState, ...], ...] = ()


@dataclass(frozen=True)
class _Path:
    result: FingeringResult
    previous: _Path | None


@dataclass(frozen=True)
class _Beam:
    path: _Path | None
    contacts: tuple[FingeringResult, ...]
    previous_by_voice: Mapping[int, FingeringState]
    edits: int
    score: float


def _signature(state: FingeringState) -> tuple[int, int, str, int]:
    return state.string_num, state.fret, state.finger.value, state.hand_position


def _states_from_path(path: _Path | None) -> list[FingeringResult]:
    results: list[FingeringResult] = []
    while path is not None:
        results.append(path.result)
        path = path.previous
    results.reverse()
    return results


def _compatible(contacts: Sequence[FingeringResult]) -> bool:
    return not any(
        violation.severity == BiomechanicalSeverity.FATAL
        for violation in validate_contact_configuration(contacts)
    )


def _active_for(
    contacts: Sequence[FingeringResult], current: FingeringResult,
) -> tuple[FingeringResult, ...]:
    onset = current.note_event.onset
    voice = current.note_event.voice_hint or 0
    active: list[FingeringResult] = []
    for previous in contacts:
        note = previous.note_event
        if note.onset == onset and note.measure_index != current.note_event.measure_index:
            continue
        if not note.let_ring and note.onset + note.duration <= onset:
            continue
        if (
            note.onset < onset
            and previous.state.string_num == current.state.string_num
            and (note.let_ring or (note.voice_hint or 0) == voice)
        ):
            continue
        active.append(previous)
    active.append(current)
    return tuple(active)


def _tie_compatible(path: _Path | None, current: FingeringResult) -> bool:
    if not current.note_event.is_tie_dest:
        return True
    voice = current.note_event.voice_hint or 0
    source_string = current.note_event.string_hint or current.state.string_num
    while path is not None:
        previous = path.result
        if (
            (previous.note_event.voice_hint or 0) == voice
            and (previous.note_event.string_hint or previous.state.string_num) == source_string
        ):
            return (
                previous.state.string_num == current.state.string_num
                and previous.state.fret == current.state.fret
                and previous.state.finger == current.state.finger
            )
        path = path.previous
    # A sliced phrase may start with a continuation; no preceding state known.
    return True


def plan_hand_configurations(
    results: Sequence[FingeringResult],
    candidates: Mapping[int, Sequence[FingeringState]],
    cost_fn: CostFunctionProtocol | None = None,
    *,
    beam_width: int = 48,
) -> HandPlanningResult:
    """Select jointly compatible fingers while preserving every score identity.

    Args:
        results: Complete, onset-sorted legacy result sequence.
        candidates: Admissible states indexed by ``id(note_event)``. The caller
            supplies source/user locks here; the planner never relaxes them.
        cost_fn: Existing injected M4 cost for ranking admissible solutions.
        beam_width: Explicit finite search budget; an exhausted beam is reported.

    Returns:
        A valid discrete occupation plan, or the source-preserving input with
        ``search_failed``. Up to two alternatives describe whole sequences,
        never independently chosen per-note alternatives.
    """
    if beam_width < 1:
        raise ValueError("beam_width must be positive")
    ordered = sorted(results, key=lambda r: (r.note_event.onset, r.note_id))
    if not ordered:
        return HandPlanningResult([], "valid")
    if any(not candidates.get(id(result.note_event)) for result in ordered):
        return HandPlanningResult(list(results), "missing_candidates")
    accepted = all(
        _signature(result.state) in {
            _signature(state) for state in candidates[id(result.note_event)]
        }
        for result in ordered
    )
    tie_clean = not any(
        violation.code == "BIO-TIE-001"
        for violation in validate_fingering_results(ordered).violations
    )
    if accepted and tie_clean and all(
        _compatible(active) for _, active in sounding_occupations(ordered)
    ):
        return HandPlanningResult(list(results), "valid")

    beams = [_Beam(None, (), {}, 0, 0.0)]
    expanded = 0
    for original in ordered:
        next_beams: dict[tuple[object, ...], _Beam] = {}
        voice = original.note_event.voice_hint or 0
        choices = candidates[id(original.note_event)]
        for beam in beams:
            for state in choices:
                candidate = replace(original, state=state, alternatives=[], planted_fingers={})
                if not _tie_compatible(beam.path, candidate):
                    continue
                contacts = _active_for(beam.contacts, candidate)
                expanded += 1
                if not _compatible(contacts):
                    continue
                previous = beam.previous_by_voice.get(voice)
                local_cost = 0.0
                if cost_fn is not None:
                    local_cost = (
                        cost_fn.emission_cost(state) if previous is None
                        else cost_fn.transition_cost(previous, state, original.note_event)
                    )
                if not isfinite(local_cost):
                    continue
                previous_by_voice = {**beam.previous_by_voice, voice: state}
                # Minimise changes to the established musical proposal first;
                # injected M4 then ranks equally conservative repairs.
                updated = _Beam(
                    _Path(candidate, beam.path), contacts, previous_by_voice,
                    beam.edits + int(_signature(state) != _signature(original.state)),
                    beam.score + local_cost,
                )
                key = (
                    tuple((r.note_id, _signature(r.state)) for r in contacts),
                    tuple((v, _signature(s)) for v, s in sorted(previous_by_voice.items())),
                )
                prior = next_beams.get(key)
                if prior is None or (updated.edits, updated.score) < (prior.edits, prior.score):
                    next_beams[key] = updated
        if not next_beams:
            return HandPlanningResult(list(results), "search_failed", expanded_states=expanded)
        beams = sorted(next_beams.values(), key=lambda b: (b.edits, b.score))[:beam_width]

    chosen = _states_from_path(beams[0].path)
    # Final independent interval sweep also checks previously sounding voices.
    if not all(_compatible(active) for _, active in sounding_occupations(chosen)):
        return HandPlanningResult(list(results), "search_failed", expanded_states=expanded)
    alternatives = tuple(
        tuple(result.state for result in _states_from_path(beam.path))
        for beam in beams[1:3]
    )
    return HandPlanningResult(chosen, "valid", beams[0].edits, expanded, alternatives)


def refresh_fingering_costs(
    results: list[FingeringResult], cost_fn: CostFunctionProtocol,
) -> None:
    """Recompute final cumulative costs per voice and discard obsolete alternatives."""
    previous: dict[int, FingeringState] = {}
    totals: dict[int, float] = {}
    for result in sorted(results, key=lambda r: (r.note_event.onset, r.note_id)):
        voice = result.note_event.voice_hint or 0
        prior = previous.get(voice)
        marginal = (
            cost_fn.emission_cost(result.state) if prior is None
            else cost_fn.transition_cost(prior, result.state, result.note_event)
        )
        totals[voice] = totals.get(voice, 0.0) + marginal
        result.cost = totals[voice]
        result.alternatives = []
        previous[voice] = result.state
