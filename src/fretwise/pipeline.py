"""Voice-aware pipeline orchestration for FretWise.

Runs the full generate → Viterbi → post-process pipeline, splitting notes by
GP voice so each voice is optimised independently.  Results are merged and
sorted by onset for rendering.
"""

from __future__ import annotations

from fretwise.generator import StateGenerator
from fretwise.models import FingeringResult, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.scoring import (
    resolve_chord_conflicts,
    resolve_chord_finger_ordering,
    resolve_chord_stretch,
    resolve_finger_continuity,
    resolve_section_consistency,
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
) -> tuple[list[FingeringResult], dict[str, int]]:
    """Run generate → Viterbi → post-process with per-voice separation.

    Each GP voice is optimised independently (its own Viterbi path and own
    post-processing passes), then all voice results are merged and sorted by
    onset for unified rendering.

    Args:
        events: All NoteEvents (possibly from multiple voices).
        generator: StateGenerator instance.
        optimizer: ViterbiOptimizer instance.

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
        results = optimizer.solve(list(valid_events), list(valid_states))
        results = resolve_finger_continuity(results)
        results = resolve_section_consistency(results)
        results = resolve_chord_conflicts(results)
        results = resolve_chord_stretch(results)
        results = resolve_chord_finger_ordering(results)
        all_results.extend(results)

    # Sort by onset then voice for stable, predictable ordering.
    all_results.sort(key=lambda r: (r.note_event.onset, r.note_event.voice_hint or 0))

    # Second pass on the merged result: catch inter-voice chord conflicts and
    # crossings that are only visible when all voices are combined.
    if len(voices) > 1:
        all_results = resolve_chord_conflicts(all_results)
        all_results = resolve_chord_finger_ordering(all_results)

    for i, r in enumerate(all_results):
        r.note_id = i

    stats = {
        "parsed": len(events),
        "valid_states": total_valid,
        "viterbi": len(all_results),
        "dropped": total_dropped,
    }
    return all_results, stats
