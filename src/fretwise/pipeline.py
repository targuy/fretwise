"""Voice-aware pipeline orchestration for FretWise.

Runs the full generate → Viterbi → post-process pipeline, splitting notes by
GP voice so each voice is optimised independently.  Results are merged and
sorted by onset for rendering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from fretwise.biomechanics import (
    BiomechanicalReport,
    BiomechanicalSeverity,
    BiomechanicalViolation,
    validate_fingering_results,
)
from fretwise.generator import StateGenerator
from fretwise.hand_planning import plan_hand_configurations, refresh_fingering_costs
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.phrase_arbitration import arbitrate_phrase_proposals, copy_fingering_results
from fretwise.scoring import (
    CostFunction,
    resolve_arpeggio_chord_fingering,
    resolve_chord_conflicts,
    resolve_chord_finger_ordering,
    resolve_chord_finger_span,
    resolve_chord_learned_fingers,
    resolve_chord_partial_barre,
    resolve_chord_stretch,
    resolve_chord_string_diagonal,
    resolve_chord_unified_hand_position,
    resolve_finger_continuity,
    resolve_pinky_run_to_index,
    resolve_section_consistency,
    resolve_sedentary_fingers,
)
from fretwise.segmentation import Position, segment_into_positions

_UNFINGERABLE_SOURCE_COST = 1_000_000.0
_LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True)
class PipelineResult:
    """Additive pipeline payload including final guard validation."""

    results: list[FingeringResult]
    stats: dict[str, int]
    biomechanical_report: BiomechanicalReport


def _anchors_from_segments(
    segments: list[Position], n_notes: int,
) -> list[int | None]:
    """Build a per-note-index anchor lookup from a list of Positions.

    Notes not covered by any segment (shouldn't happen if segmentation covers
    the full sequence, but guarded for safety) are assigned None — the
    scoring layer falls back to A' tolerance for those transitions.
    """
    anchors: list[int | None] = [None] * n_notes
    for seg in segments:
        for i in range(seg.start_idx, seg.end_idx + 1):
            if 0 <= i < n_notes:
                anchors[i] = seg.anchor
    return anchors


def _state_signature(results: list[FingeringResult]) -> tuple[tuple[int, int, str, int], ...]:
    """Return a compact signature of final state choices for convergence checks."""
    return tuple(
        (
            result.state.string_num,
            result.state.fret,
            result.state.finger.value,
            result.state.hand_position,
        )
        for result in results
    )


def _fallback_state_for_unfingerable_source_note(note: NoteEvent) -> FingeringState | None:
    """Keep source-tab notes visible when no generated state is valid."""
    if note.string_hint is None or note.fret_hint is None:
        return None
    fret = int(note.fret_hint)
    finger = Finger.OPEN if fret == 0 else Finger.INDEX
    return FingeringState(
        string_num=int(note.string_hint),
        fret=fret,
        finger=finger,
        hand_position=max(1, fret),
    )


def _resolve_final_chord_guards(results: list[FingeringResult]) -> list[FingeringResult]:
    """Run final chord repair passes until stable.

    Earlier resolvers such as section consistency or learned chord inference can
    reintroduce duplicate fingers or crossed chord assignments. This final pass
    keeps the public optimizer contract intact while ensuring the sequence that
    reaches export has been rechecked by the deterministic chord rules.
    """
    resolved = list(results)
    for _ in range(3):
        before = _state_signature(resolved)
        resolved = resolve_chord_partial_barre(resolved)
        resolved = resolve_chord_conflicts(resolved)
        resolved = resolve_chord_finger_ordering(resolved)
        resolved = resolve_chord_finger_span(resolved)
        resolved = resolve_chord_string_diagonal(resolved)
        resolved = resolve_chord_partial_barre(resolved)
        resolved = resolve_chord_unified_hand_position(resolved)
        if _state_signature(resolved) == before:
            break
    return resolved


def split_by_voice(events: list[NoteEvent]) -> dict[int, list[NoteEvent]]:
    """Group NoteEvents by voice index.

    Args:
        events: All NoteEvents from the parser.

    Returns:
        Dict mapping voice index → NoteEvents.  Events with ``voice_hint=None``
        are placed in voice 0.
    """
    voices: dict[int, list[NoteEvent]] = {}
    for e in events:
        v = e.voice_hint if e.voice_hint is not None else 0
        voices.setdefault(v, []).append(e)
    return voices


def run_pipeline(
    events: list[NoteEvent],
    generator: StateGenerator,
    optimizer: ViterbiOptimizer,
    pattern_matcher: PatternMatcher | None = None,
    chord_finger_classifier: object | None = None,
    phrase_window_fingerer: object | None = None,
) -> tuple[list[FingeringResult], dict[str, int]]:
    """Run generate → pattern-match → Viterbi → post-process with per-voice separation.

    Each GP voice is optimised independently (its own Viterbi path and own
    post-processing passes), then all voice results are merged and sorted by
    onset for unified rendering.

    Args:
        events: All NoteEvents (possibly from multiple voices).
        generator: StateGenerator instance.
        optimizer: ViterbiOptimizer instance.
        pattern_matcher: Optional PatternMatcher to reorder states before Viterbi.
        chord_finger_classifier: Optional learned chord-finger model.
        phrase_window_fingerer: Optional ``LearnedPhraseWindowFingerer``; when
            given, admissible melodic finger proposals compete with the
            physically validated rule sequence under the active cost function.
            Positions and chord choices stay rule-chosen.

    Returns:
        Tuple of:
        - ``results``: FingeringResult list sorted by (onset, voice).
        - ``stats``: dict with keys ``parsed``, ``valid_states``, ``viterbi``,
          ``dropped`` (plus ``phrase_window_proposed``, ``phrase_window_applied``,
          ``phrase_window_rejected`` / ``phrase_window_demoted`` when active).
    """
    voices = split_by_voice(events)
    all_results: list[FingeringResult] = []
    total_valid = 0
    total_dropped = 0
    total_source_unfingerable = 0
    candidates_by_event: dict[int, list[FingeringState]] = {}
    unfingerable_events: set[int] = set()

    for voice_idx in sorted(voices.keys()):
        voice_events = voices[voice_idx]
        state_lists = generator.states_for_sequence(voice_events)
        valid_pairs: list[tuple[NoteEvent, list[FingeringState]]] = []
        fallback_event_ids: set[int] = set()
        for event, states in zip(voice_events, state_lists):
            # M5 returns references to its input states. Keep independent
            # admissibility snapshots before any later resolver edits states.
            candidates_by_event[id(event)] = [replace(state) for state in states]
            if states:
                valid_pairs.append((event, states))
                continue
            fallback = _fallback_state_for_unfingerable_source_note(event)
            if fallback is None:
                raise ValueError(
                    f"No admissible fingering for MIDI pitch {event.pitch} "
                    f"at beat {event.onset}; source note was not discarded."
                )
            valid_pairs.append((event, [fallback]))
            fallback_event_ids.add(id(event))
            total_source_unfingerable += 1
            unfingerable_events.add(id(event))
        total_valid += len(valid_pairs)
        total_dropped += len(voice_events) - len(valid_pairs)

        if not valid_pairs:
            continue

        valid_events, valid_states = zip(*valid_pairs)
        valid_states_list = list(valid_states)
        if pattern_matcher is not None:
            valid_states_list = pattern_matcher.apply(
                list(valid_events), valid_states_list,
            )

        # B integration: compute per-voice segment anchors and activate
        # segment-aware shift cost if the cost function supports it.
        # Use the optimizer's public API (set_segment_anchors / clear_segment_anchors)
        # so the pipeline never reaches into M5 internals.
        valid_events_list = list(valid_events)
        segment_activated = False
        if isinstance(optimizer.cost_fn, CostFunction):
            segments = segment_into_positions(valid_events_list)
            if segments:
                anchors = _anchors_from_segments(segments, len(valid_events_list))
                optimizer.set_segment_anchors(anchors)
                segment_activated = True

        try:
            results = optimizer.solve(valid_events_list, valid_states_list)
        finally:
            if segment_activated:
                optimizer.clear_segment_anchors()
        results = copy_fingering_results(results)
        # Cost-aware arpeggio stabilisation: pass the same CostFunction used by
        # this voice's Viterbi run so the resolver only overrides finger/
        # hand_position when it is cost-neutral-or-better under the active
        # weights/profile (segment anchors are cleared above, so the resolver
        # sees the A' per-state shift cost — the same view a post-Viterbi edit
        # is judged against). Returns None for non-CostFunction optimizers,
        # in which case the resolver keeps its legacy behaviour.
        arpeggio_cost_fn = (
            optimizer.cost_fn if isinstance(optimizer.cost_fn, CostFunction) else None
        )
        results = resolve_arpeggio_chord_fingering(results, cost_fn=arpeggio_cost_fn)
        results = resolve_finger_continuity(results)
        results = resolve_chord_conflicts(results)
        results = resolve_chord_stretch(results)
        results = resolve_chord_finger_ordering(results)
        results = resolve_chord_finger_span(results)
        results = resolve_chord_string_diagonal(results)
        if chord_finger_classifier is not None:
            results = resolve_chord_learned_fingers(results, chord_finger_classifier)
        results = resolve_section_consistency(results)
        for result in results:
            if id(result.note_event) in fallback_event_ids:
                result.cost = max(result.cost, _UNFINGERABLE_SOURCE_COST)
        all_results.extend(results)

    # Sort by onset then voice for stable, predictable ordering.
    all_results.sort(key=lambda r: (r.note_event.onset, r.note_event.voice_hint or 0))

    # Preserve notation identities and source durations across voices. A unison
    # may share one physical contact; deleting a score occurrence loses its
    # source identity and can shorten the other voice's sustained note.

    # Second pass on the merged result: catch inter-voice chord conflicts and
    # crossings that are only visible when all voices are combined.
    if len(voices) > 1:
        all_results = resolve_chord_conflicts(all_results)
        all_results = resolve_chord_finger_ordering(all_results)
        all_results = resolve_chord_finger_span(all_results)
        all_results = resolve_chord_string_diagonal(all_results)

    for i, r in enumerate(all_results):
        r.note_id = i

    all_results = _resolve_final_chord_guards(all_results)

    # Pinky-run correction — overrides Viterbi's (locally cheap but
    # musically poor) choice of keeping the pinky planted for repeated
    # same-fret strikes.  Must run BEFORE sedentary annotation so the
    # latter sees the corrected finger assignments.
    all_results = resolve_pinky_run_to_index(all_results)
    all_results = _resolve_final_chord_guards(all_results)

    hand_stats: dict[str, int] = {}
    baseline_valid = False
    if isinstance(generator, StateGenerator):
        # Rule resolvers can change a locked finger. Restore admissibility
        # before joint search and establish the protected baseline before ML.
        for result in all_results:
            allowed = candidates_by_event.get(id(result.note_event), [])
            if allowed and result.state not in allowed:
                result.state = replace(min(allowed, key=lambda state: (
                    state.string_num != result.state.string_num,
                    state.fret != result.state.fret,
                    state.finger != result.state.finger,
                    abs(state.hand_position - result.state.hand_position),
                )))
        planned = plan_hand_configurations(
            all_results, candidates_by_event, optimizer.cost_fn,
        )
        all_results = copy_fingering_results(planned.results)
        baseline_valid = planned.status == "valid"
        hand_stats = {
            "hand_plan_changed": planned.changed_notes,
            "hand_plan_expanded": planned.expanded_states,
            "hand_plan_search_failed": int(planned.status != "valid"),
        }

    # ML proposes fingers; M5 selects a complete per-voice path including
    # both phrase boundaries. The protected baseline survives failed inference,
    # incompatible contacts, source locks and any increase in sequence cost.
    pw_stats: dict[str, int] = {}
    if phrase_window_fingerer is not None:
        from fretwise.ml.phrase_window import (
            LearnedPhraseWindowFingerer,
            resolve_phrase_window_fingers,
        )
        if isinstance(phrase_window_fingerer, LearnedPhraseWindowFingerer):
            pw_stats = {
                "phrase_window_proposed": 0,
                "phrase_window_applied": 0,
                "phrase_window_rejected": 0,
                "phrase_window_demoted": 0,
            }
            if not baseline_valid:
                pw_stats["phrase_window_skipped_invalid_baseline"] = 1
            else:
                baseline = copy_fingering_results(all_results)
                try:
                    proposals = resolve_phrase_window_fingers(
                        copy_fingering_results(baseline), phrase_window_fingerer,
                        stats_out=pw_stats,
                    )
                    pw_stats["phrase_window_proposed"] = pw_stats["phrase_window_applied"]
                    selected = arbitrate_phrase_proposals(
                        baseline, proposals, candidates_by_event, optimizer.cost_fn,
                    )
                    all_results = selected.results
                    pw_stats.update({
                        "phrase_window_proposed": selected.proposed,
                        "phrase_window_applied": selected.applied,
                        "phrase_window_rejected": selected.proposed - selected.applied,
                        "phrase_window_hand_plan_changed": selected.hand_plan_changed,
                        "phrase_window_hand_plan_expanded": selected.hand_plan_expanded,
                    })
                    if selected.fallback:
                        pw_stats["phrase_window_fallback"] = 1
                except Exception as exc:  # noqa: BLE001 - preserve rule-only result
                    _LOGGER.warning(
                        "Phrase-window inference/arbitration failed; using rules: %s", exc,
                    )
                    all_results = baseline
                    pw_stats["phrase_window_applied"] = 0
                    pw_stats["phrase_window_rejected"] = pw_stats["phrase_window_proposed"]
                    pw_stats["phrase_window_fallback"] = 1
    if optimizer.cost_fn is not None:
        refresh_fingering_costs(all_results, optimizer.cost_fn)
    for result in all_results:
        if id(result.note_event) in unfingerable_events:
            result.cost = max(result.cost, _UNFINGERABLE_SOURCE_COST)

    # Sedentary/planted fingers — read-only w.r.t. FingeringState.  Runs on the
    # merged, fully-resolved list so every active finger decision is final and
    # all voices share one consistent hand model.  See
    # docs/finger_placement_strategy.md.
    all_results = resolve_sedentary_fingers(all_results)

    stats = {
        "parsed": len(events),
        "valid_states": total_valid,
        "viterbi": len(all_results),
        "dropped": total_dropped,
        "source_unfingerable": total_source_unfingerable,
        "hard_constraint_violations": validate_fingering_results(all_results).fatal_count,
        **hand_stats,
        **pw_stats,
    }
    return all_results, stats


def run_pipeline_with_guard_report(
    events: list[NoteEvent],
    generator: StateGenerator,
    optimizer: ViterbiOptimizer,
    pattern_matcher: PatternMatcher | None = None,
    chord_finger_classifier: object | None = None,
    phrase_window_fingerer: object | None = None,
) -> PipelineResult:
    """Run the legacy pipeline and validate final biomechanical invariants.

    This API preserves the public ``run_pipeline`` tuple contract while giving
    callers access to a pure final-output guard report.
    """
    results, stats = run_pipeline(
        events,
        generator,
        optimizer,
        pattern_matcher=pattern_matcher,
        chord_finger_classifier=chord_finger_classifier,
        phrase_window_fingerer=phrase_window_fingerer,
    )
    report = validate_fingering_results(results)
    if stats["source_unfingerable"]:
        unvalidated = [result for result in results if result.cost >= _UNFINGERABLE_SOURCE_COST]
        report = BiomechanicalReport(report.checked_notes, (*report.violations, *(
            BiomechanicalViolation(
                "BIO-SOURCE-001", BiomechanicalSeverity.FATAL,
                "No admissible source fingering; displayed position is unvalidated.",
                note_ids=(result.note_id,), measure_index=result.note_event.measure_index,
                onset=result.note_event.onset,
            ) for result in unvalidated
        )))
    return PipelineResult(
        results=results,
        stats=stats,
        biomechanical_report=report,
    )
