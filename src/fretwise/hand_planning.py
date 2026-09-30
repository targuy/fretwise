"""Bounded joint fingering search outside the immutable M5 interface.

The legacy per-voice solver supplies preferences. This layer admits only
compatible whole-hand contacts, including notes held by other voices. It is a
discrete fingering planner, not an anatomical or continuous-motion certificate.
An exhausted beam means search failed, never proof that a passage is impossible.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from itertools import combinations
from math import isfinite

from fretwise.biomechanics import (
    BiomechanicalSeverity,
    sounding_occupations,
    validate_contact_configuration,
    validate_fingering_results,
)
from fretwise.models import FingeringResult, FingeringState
from fretwise.optimizer import CostFunctionProtocol
from fretwise.sustain import contact_end, required_contact_ends


@dataclass(frozen=True)
class HandPlanningResult:
    """Joint-search result with complete-sequence alternatives and honest status."""

    results: list[FingeringResult]
    status: str
    changed_notes: int = 0
    expanded_states: int = 0
    alternatives: tuple[tuple[FingeringState, ...], ...] = ()
    released_notes: int = 0
    unresolved_note_ids: tuple[int, ...] = ()


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
    releases: Mapping[int, float]


def _signature(state: FingeringState) -> tuple[int, int, str, int]:
    return state.string_num, state.fret, state.finger.value, state.hand_position


def _states_from_path(
    path: _Path | None, releases: Mapping[int, float] | None = None,
) -> list[FingeringResult]:
    results: list[FingeringResult] = []
    while path is not None:
        result = path.result
        if releases is not None and result.note_id in releases:
            result = replace(result, let_ring_end=releases[result.note_id])
        results.append(result)
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
    required_ends: Mapping[int, float],
) -> tuple[FingeringResult, ...]:
    onset = current.note_event.onset
    voice = current.note_event.voice_hint or 0
    active: list[FingeringResult] = []
    for previous in contacts:
        note = previous.note_event
        if note.onset == onset and note.measure_index != current.note_event.measure_index:
            continue
        if contact_end(previous, required_ends[previous.note_id]) <= onset:
            continue
        if (
            note.onset < onset
            and previous.state.string_num == current.state.string_num
            and (
                (note.voice_hint or 0) == voice
                or (note.let_ring and required_ends[previous.note_id] <= onset)
            )
        ):
            continue
        active.append(previous)
    active.append(current)
    return tuple(active)


def _contact_options(
    contacts: tuple[FingeringResult, ...], onset: float,
    required_ends: Mapping[int, float],
) -> list[tuple[tuple[FingeringResult, ...], tuple[int, ...]]]:
    """Keep ringing where possible, else release the fewest expired contacts.

    The notated note stays intact. Only its optional let-ring tail may end,
    including all score occurrences sharing that physical contact.
    """
    if _compatible(contacts):
        return [(contacts, ())]
    grouped: dict[tuple[int, int, str], list[FingeringResult]] = {}
    for result in contacts:
        state = result.state
        grouped.setdefault((state.string_num, state.fret, state.finger.value), []).append(result)
    optional = [
        tuple(result.note_id for result in group)
        for group in grouped.values()
        if all(
            result.note_event.let_ring
            and result.note_event.onset < onset
            and required_ends[result.note_id] <= onset
            for result in group
        )
    ]
    for count in range(1, len(optional) + 1):
        options = []
        for selected in combinations(optional, count):
            released = tuple(note_id for group in selected for note_id in group)
            remaining = tuple(result for result in contacts if result.note_id not in released)
            if _compatible(remaining):
                options.append((remaining, released))
        if options:
            return options
    return []


def _beam_rank(beam: _Beam) -> tuple[int, int, float]:
    return len(beam.releases), beam.edits, beam.score


def _select_beams(beams: Sequence[_Beam], width: int) -> list[_Beam]:
    """Keep finger choices before filling the budget with wrist variants.

    Several hand positions can describe the same physical finger assignment.
    Letting those variants exhaust a beam can discard every future-compatible
    finger for a held bass note. Reserve one path per current physical choice,
    then use the unchanged conservative ranking for the remaining slots.
    """
    ranked = sorted(beams, key=_beam_rank)
    selected: list[_Beam] = []
    deferred: list[_Beam] = []
    choices: set[tuple[int, int, str]] = set()
    for beam in ranked:
        if beam.path is None:
            deferred.append(beam)
            continue
        state = beam.path.result.state
        choice = (state.string_num, state.fret, state.finger.value)
        if choice in choices:
            deferred.append(beam)
        else:
            choices.add(choice)
            selected.append(beam)
    return sorted((selected + deferred)[:width], key=_beam_rank)


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
        A valid discrete occupation plan, or a partially repaired sequence with
        ``search_failed`` and explicit unresolved note IDs. A hard conflict does
        not discard repairs before or after it. Up to two alternatives describe
        whole sequences sharing the selected release plan.
    """
    if beam_width < 1:
        raise ValueError("beam_width must be positive")
    ordered = sorted(results, key=lambda r: (r.note_event.onset, r.note_id))
    if not ordered:
        return HandPlanningResult([], "valid")
    missing_candidates = any(not candidates.get(id(result.note_event)) for result in ordered)
    required_ends = required_contact_ends(ordered)
    accepted = all(
        _signature(result.state) in {
            _signature(state) for state in candidates.get(id(result.note_event), ())
        }
        for result in ordered
    )
    initially_valid = validate_fingering_results(ordered).fatal_count == 0
    if accepted and initially_valid and all(
        _compatible(active) for _, active in sounding_occupations(ordered)
    ):
        return HandPlanningResult(list(results), "valid")

    beams = [_Beam(None, (), {}, 0, 0.0, {})]
    expanded = 0
    unresolved: list[int] = []
    for original in ordered:
        next_beams: dict[tuple[object, ...], _Beam] = {}
        # Wrist variants share contact feasibility and repeated transitions.
        # Keep caches local to this score occurrence: note context, source
        # identity and injected costs remain authoritative.
        contact_cache: dict[tuple[tuple[int, int, int, str], ...], list[tuple[int, ...]]] = {}
        cost_cache: dict[
            tuple[tuple[int, int, str, int] | None, tuple[int, int, str, int]], float
        ] = {}
        voice = original.note_event.voice_hint or 0
        choices = candidates.get(id(original.note_event), ())
        for beam in beams:
            for state in choices:
                candidate = replace(original, state=state, alternatives=[], planted_fingers={})
                if not _tie_compatible(beam.path, candidate):
                    continue
                contacts = _active_for(beam.contacts, candidate, required_ends)
                expanded += 1
                contact_key = tuple(
                    (r.note_id, r.state.string_num, r.state.fret, r.state.finger.value)
                    for r in contacts
                )
                if contact_key not in contact_cache:
                    contact_cache[contact_key] = [
                        released for _, released in _contact_options(
                            contacts, original.note_event.onset, required_ends,
                        )
                    ]
                release_options = contact_cache[contact_key]
                if not release_options:
                    continue
                previous = beam.previous_by_voice.get(voice)
                local_cost = 0.0
                if cost_fn is not None:
                    cost_key = (_signature(previous) if previous is not None else None,
                                _signature(state))
                    if cost_key not in cost_cache:
                        cost_cache[cost_key] = (
                            cost_fn.emission_cost(state) if previous is None
                            else cost_fn.transition_cost(previous, state, original.note_event)
                        )
                    local_cost = cost_cache[cost_key]
                if not isfinite(local_cost):
                    continue
                previous_by_voice = {**beam.previous_by_voice, voice: state}
                for released_ids in release_options:
                    active_contacts = tuple(r for r in contacts if r.note_id not in released_ids)
                    releases = dict(beam.releases)
                    releases.update(dict.fromkeys(released_ids, original.note_event.onset))
                    # Preserve optional resonance first, then established
                    # musical choices; injected M4 breaks equal repair costs.
                    updated = _Beam(
                        _Path(candidate, beam.path), active_contacts, previous_by_voice,
                        beam.edits + int(_signature(state) != _signature(original.state)),
                        beam.score + local_cost, releases,
                    )
                    key = (
                        tuple((r.note_id, _signature(r.state)) for r in active_contacts),
                        tuple((v, _signature(s)) for v, s in sorted(previous_by_voice.items())),
                    )
                    prior = next_beams.get(key)
                    if prior is None or _beam_rank(updated) < _beam_rank(prior):
                        next_beams[key] = updated
        if not next_beams:
            # Keep the best repaired prefix, expose this unsolved source note,
            # and resume search when its mandatory occupation clears. Neither
            # source locks nor written durations are relaxed to claim success.
            best = min(beams, key=_beam_rank)
            fallback = replace(original, alternatives=[], planted_fingers={})
            unresolved.append(original.note_id)
            beams = [_Beam(
                _Path(fallback, best.path),
                _active_for(best.contacts, fallback, required_ends),
                {**best.previous_by_voice, voice: fallback.state},
                best.edits, best.score, best.releases,
            )]
            continue
        beams = _select_beams(list(next_beams.values()), beam_width)

    best = beams[0]
    chosen = _states_from_path(best.path, best.releases)
    # Final independent interval sweep also checks previously sounding voices.
    valid = not unresolved and validate_fingering_results(chosen).fatal_count == 0
    alternatives = tuple(
        tuple(result.state for result in _states_from_path(beam.path))
        for beam in beams[1:3]
        if valid and beam.releases == best.releases
    )
    status = "valid" if valid else ("missing_candidates" if missing_candidates else "search_failed")
    return HandPlanningResult(
        chosen, status, best.edits, expanded, alternatives,
        released_notes=len(best.releases), unresolved_note_ids=tuple(unresolved),
    )


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
