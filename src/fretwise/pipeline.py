"""Voice-aware pipeline orchestration for FretWise.

Runs the full generate → Viterbi → post-process pipeline, splitting notes by
GP voice so each voice is optimised independently.  Results are merged and
sorted by onset for rendering.
"""

from __future__ import annotations

from fretwise.generator import StateGenerator
from fretwise.models import FingeringResult, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.scoring import (
    resolve_chord_conflicts,
    resolve_chord_finger_ordering,
    resolve_chord_finger_span,
    resolve_chord_partial_barre,
    resolve_chord_stretch,
    resolve_chord_string_diagonal,
    resolve_arpeggio_chord_fingering,
    resolve_chord_unified_hand_position,
    resolve_finger_continuity,
    resolve_pinky_run_to_index,
    resolve_section_consistency,
    resolve_sedentary_fingers,
)


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

    Returns:
        Tuple of:
        - ``results``: FingeringResult list sorted by (onset, voice).
        - ``stats``: dict with keys ``parsed``, ``valid_states``, ``viterbi``,
          ``dropped``.
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
        results = optimizer.solve(list(valid_events), valid_states_list)
        results = resolve_arpeggio_chord_fingering(results)
        results = resolve_finger_continuity(results)
        results = resolve_chord_conflicts(results)
        results = resolve_chord_stretch(results)
        results = resolve_chord_finger_ordering(results)
        results = resolve_chord_finger_span(results)
        results = resolve_chord_string_diagonal(results)
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

    # Partial-barre detection — collapse adjacent-string same-fret chord
    # subsets into an INDEX barre.  Must run AFTER chord-conflicts so the
    # duplicated INDEX created by the barre is not undone.
    all_results = resolve_chord_partial_barre(all_results)

    # Unified hand-position — snap every note of a chord to the same
    # hand_position (= lowest fret of the chord).  Cleans up the generator's
    # per-finger natural-hp assignment once the barre is applied.
    all_results = resolve_chord_unified_hand_position(all_results)

    # Pinky-run correction — overrides Viterbi's (locally cheap but
    # musically poor) choice of keeping the pinky planted for repeated
    # same-fret strikes.  Must run BEFORE sedentary annotation so the
    # latter sees the corrected finger assignments.
    all_results = resolve_pinky_run_to_index(all_results)

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
    }
    return all_results, stats
