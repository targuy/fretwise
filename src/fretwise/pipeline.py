"""Voice-aware pipeline orchestration for FretWise.

Runs the full generate → Viterbi → post-process pipeline, splitting notes by
GP voice so each voice is optimised independently.  Results are merged and
sorted by onset for rendering.
"""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.biomechanics import BiomechanicalReport, validate_fingering_results
from fretwise.generator import StateGenerator
from fretwise.models import FingeringResult, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
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
            given, melodic (non-chord) fingers are overridden by the
            phrase_window predictions with the pinky demotion belt
            (GDS-026 #63 production activation). Positions stay rule-chosen.

    Returns:
        Tuple of:
        - ``results``: FingeringResult list sorted by (onset, voice).
        - ``stats``: dict with keys ``parsed``, ``valid_states``, ``viterbi``,
          ``dropped`` (plus ``phrase_window_applied`` / ``phrase_window_demoted``
          when the fingerer is active).
    """
    voices = split_by_voice(events)
    all_results: list[FingeringResult] = []
    total_valid = 0
    total_dropped = 0

    for voice_idx in sorted(voices.keys()):
        voice_events = voices[voice_idx]
        state_lists = generator.states_for_sequence(voice_events)
        valid_pairs = [(e, sl) for e, sl in zip(voice_events, state_lists) if sl]
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
        all_results.extend(results)

    # Sort by onset then voice for stable, predictable ordering.
    all_results.sort(key=lambda r: (r.note_event.onset, r.note_event.voice_hint or 0))

    # Deduplicate cross-voice unison notes: when two voices play the exact same
    # (string, fret) at the same onset, keep only the first occurrence.  GP
    # files frequently double-notate the same pitch across voices; rendering
    # both produces two fingers on one spot, which is physically impossible.
    seen: set[tuple[float, int, int]] = set()
    deduped: list[FingeringResult] = []
    for r in all_results:
        key = (round(r.note_event.onset, 6), r.state.string_num, r.state.fret)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    all_results = deduped

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

    # phrase_window production pass (GDS-026 #63) — overrides melodic
    # (non-chord) fingers with the ML prediction + pinky demotion belt.
    # Runs after every rule resolver so chords and positions are final, and
    # BEFORE sedentary annotation so the hand model sees the applied fingers.
    pw_stats: dict[str, int] = {}
    if phrase_window_fingerer is not None:
        from fretwise.ml.phrase_window import (
            LearnedPhraseWindowFingerer,
            resolve_phrase_window_fingers,
        )
        if isinstance(phrase_window_fingerer, LearnedPhraseWindowFingerer):
            all_results = resolve_phrase_window_fingers(
                all_results, phrase_window_fingerer, stats_out=pw_stats,
            )

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
    return PipelineResult(
        results=results,
        stats=stats,
        biomechanical_report=validate_fingering_results(results),
    )
