"""Measure-level diversified alternatives via a windowed re-solve.

For a flagged measure we re-run the *existing* pipeline on a small window (the
measure plus a fixed context buffer), freezing the surrounding notes and asking
the optimizer for several *distinct* fingerings of the measure. Diversity is
obtained by penalising state choices already emitted by earlier variants — a
plain cost injection, so the Viterbi optimizer (M5) is never modified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace

from fretwise.biomechanics import validate_fingering_results
from fretwise.config import ConfigNode, config
from fretwise.generator import STANDARD_TUNING, GeneratorConfig, StateGenerator
from fretwise.models import FingeringResult, FingeringState, NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline_with_guard_report
from fretwise.review.bias import ConstrainedStateGenerator
from fretwise.scoring import CostFunction, CostWeights, RulePreferences

logger = logging.getLogger(__name__)

# In-window banned signature: (onset, string, fret, finger).
_BanSig = tuple[float, int, int, str]
# Note identity key: (onset, pitch, voice_hint).
_NoteKey = tuple[float, int, int | None]


@dataclass(frozen=True)
class MeasureAlternative:
    """One candidate fingering for a measure."""

    variant_id: str
    is_current: bool
    fingerings: list[dict[str, object]]
    cost: float
    label: str
    playable: bool


class DiversityCostFunction(CostFunction):
    """CostFunction that penalises already-seen in-window state choices.

    Subclasses (rather than wraps) :class:`CostFunction` so the pipeline's
    ``isinstance`` segment-anchor activation keeps working unchanged.
    """

    def __init__(
        self,
        *,
        weights: CostWeights | None,
        player_cost_model: object | None,
        rule_preferences: RulePreferences | None,
        target_measures: set[int],
        banned: set[_BanSig],
        penalty: float,
    ) -> None:
        super().__init__(
            weights=weights,
            rule_preferences=rule_preferences,
            player_cost_model=player_cost_model,
        )
        self._target = target_measures
        self._banned = banned
        self._penalty = penalty

    def transition_cost(
        self,
        s1: FingeringState,
        s2: FingeringState,
        note: NoteEvent,
        index: int | None = None,
    ) -> float:
        cost = super().transition_cost(s1, s2, note, index)
        if note.measure_index in self._target:
            sig = (round(note.onset, 6), s2.string_num, s2.fret, s2.finger.value)
            if sig in self._banned:
                cost += self._penalty
        return cost


def _note_key(note: NoteEvent) -> _NoteKey:
    return (round(note.onset, 6), note.pitch, note.voice_hint)


def _derive_tuning(events: list[NoteEvent]) -> list[int]:
    """Infer per-string open-string MIDI pitches from the source hints.

    GP tabs encode the real (possibly non-standard / dropped / capo'd) tuning
    implicitly: ``open_pitch[string] = note.pitch - note.fret``. Using this — not
    the hard-coded standard tuning — lets free position exploration propose valid
    alternate voicings (e.g. the same pitch one fret over on another string).
    Strings never seen fall back to standard tuning.
    """
    tuning = list(STANDARD_TUNING)
    seen: dict[int, int] = {}
    for e in events:
        if (
            e.string_hint is not None and e.fret_hint is not None
            and 1 <= e.string_hint <= len(tuning) and e.string_hint not in seen
        ):
            seen[e.string_hint] = e.pitch - e.fret_hint
    for string_num, open_pitch in seen.items():
        tuning[string_num - 1] = open_pitch
    return tuning


class _LocalReVoiceGenerator(StateGenerator):
    """Generator that offers positions *near* each note's source position.

    For a hinted note it enumerates same-pitch positions within ``window`` frets
    on the source string, plus the adjacent strings — so alternatives stay local
    and playable (slide a fret, shift the run, change a finger) instead of
    re-voicing the whole measure. Un-hinted notes fall back to full exploration.
    """

    def __init__(self, tuning: list[int], *, window: int = 3) -> None:
        super().__init__(GeneratorConfig(open_string_pitches=list(tuning)))
        self._tuning = list(tuning)
        self._window = window

    def states_for(self, note: NoteEvent) -> list[FingeringState]:
        if note.string_hint is None or note.fret_hint is None:
            return super().states_for(note)
        max_fret = self._config.max_fret
        out: list[FingeringState] = []
        for s in range(1, len(self._tuning) + 1):
            fret = note.pitch - self._tuning[s - 1]
            if fret < 0 or fret > max_fret:
                continue
            if abs(fret - note.fret_hint) > self._window and abs(s - note.string_hint) > 1:
                continue
            out.extend(super().states_for(replace(note, string_hint=s, fret_hint=fret)))
        return out or super().states_for(note)


def _window_signature(window: list[FingeringResult]) -> tuple[_BanSig, ...]:
    return tuple(
        sorted(
            (round(r.note_event.onset, 6), r.state.string_num, r.state.fret,
             r.state.finger.value)
            for r in window
        )
    )


def _label(window: list[FingeringResult]) -> str:
    """Short human label for a variant (best-effort)."""
    if not window:
        return "—"
    min_hp = min(r.state.hand_position for r in window)
    fingers = {r.state.finger.value for r in window}
    parts = [f"Position {min_hp}"]
    # Barre: ≥2 simultaneous index notes on the same fret.
    by_onset: dict[float, list[FingeringResult]] = {}
    for r in window:
        by_onset.setdefault(round(r.note_event.onset, 6), []).append(r)
    if any(
        sum(1 for r in grp if r.state.finger.value == "index") >= 2
        for grp in by_onset.values()
    ):
        parts.append("barré")
    if "pinky" in fingers:
        parts.append("auriculaire")
    return " · ".join(parts)


def measure_alternatives(
    events: list[NoteEvent],
    results: list[FingeringResult],
    measure_index: int,
    *,
    weights: CostWeights | None = None,
    player_cost_model: object | None = None,
    chord_finger_classifier: object | None = None,
    rule_preferences: RulePreferences | None = None,
    cfg: ConfigNode | None = None,
) -> list[MeasureAlternative]:
    """Return up to ``count`` distinct, playable fingerings for a measure.

    Variant #1 is always the current solution. Further variants are produced by
    re-solving the window with growing penalties on previously-emitted choices.
    Fewer than ``count`` may be returned when the voicing is source-constrained
    (only the finger can vary) — never silently padded.

    Args:
        events: All note events for the track.
        results: Current fingered results for the track.
        measure_index: 1-based measure to generate alternatives for.
        weights: Cost weights (defaults to performance mode).
        player_cost_model: Optional learned/biased player cost.
        chord_finger_classifier: Optional chord finger classifier.
        rule_preferences: Optional scoring rule preferences.
        cfg: ``config().review`` node; loaded from defaults when ``None``.

    Returns:
        Distinct alternatives, current first, each guaranteed biomechanically
        clean within the measure.
    """
    review_cfg = cfg if cfg is not None else config().review
    count = int(review_cfg.alternatives.count)
    ctx = int(review_cfg.alternatives.context_measures)
    base_penalty = float(review_cfg.alternatives.diversity_penalty)
    max_attempts = int(review_cfg.alternatives.max_attempts)
    weights = weights or CostWeights.performance()

    lo, hi = measure_index - ctx, measure_index + ctx
    in_window = [
        e for e in events
        if e.measure_index is not None and lo <= e.measure_index <= hi
    ]
    if not any(e.measure_index == measure_index for e in in_window):
        return []

    # Target-measure notes explore positions NEAR the source (same string within
    # a fret window, or the same pitch on an adjacent string) so alternatives are
    # sensible local re-voicings — keep the finger and slide a fret, shift the
    # run, swap a finger — not a wild full re-voicing. Tuning is derived from the
    # source so positions are correct on dropped / non-standard tunings.
    context_events = list(in_window)
    tuning = _derive_tuning(events)
    base_generator: StateGenerator = _LocalReVoiceGenerator(
        tuning, window=int(review_cfg.alternatives.get("fret_window", 3)),
    )

    # Original note ids by identity, to map re-solved notes back.
    orig_id_by_key: dict[_NoteKey, int] = {
        _note_key(r.note_event): r.note_id for r in results
    }
    # Locks: every context note outside the target measure stays fixed.
    locks: dict[_NoteKey, FingeringState] = {
        _note_key(r.note_event): r.state
        for r in results
        if r.note_event.measure_index is not None
        and lo <= r.note_event.measure_index <= hi
        and r.note_event.measure_index != measure_index
    }
    generator = ConstrainedStateGenerator(base_generator, locks)
    matcher = PatternMatcher()

    from fretwise.review import marginal_costs  # lazy: avoids import cycle

    target = {measure_index}
    banned: set[_BanSig] = set()
    seen: set[tuple[_BanSig, ...]] = set()
    alternatives: list[MeasureAlternative] = []

    # Variant #1 — the current solution.
    current_window = [r for r in results if r.note_event.measure_index == measure_index]
    seen.add(_window_signature(current_window))
    banned.update(_window_signature(current_window))
    current_playable = validate_fingering_results(current_window).fatal_count == 0
    alternatives.append(
        _to_alternative("v1", current_window, orig_id_by_key,
                        marginal_costs(results), is_current=True,
                        playable=current_playable)
    )

    # Gather several distinct candidate re-voicings, then keep the best ones.
    candidates: list[MeasureAlternative] = []
    penalty = base_penalty
    attempts = 0
    while len(candidates) < count * 3 and attempts < max_attempts:
        attempts += 1
        cost_fn = DiversityCostFunction(
            weights=weights,
            player_cost_model=player_cost_model,
            rule_preferences=rule_preferences,
            target_measures=target,
            banned=banned,
            penalty=penalty,
        )
        try:
            payload = run_pipeline_with_guard_report(
                context_events, generator, ViterbiOptimizer(cost_fn),
                pattern_matcher=matcher,
                chord_finger_classifier=chord_finger_classifier,
            )
        except Exception as exc:  # pragma: no cover — defensive
            logger.warning("Alternative re-solve failed (measure %d): %s",
                           measure_index, exc)
            break

        window = [
            r for r in payload.results
            if r.note_event.measure_index == measure_index
        ]
        sig = _window_signature(window)
        if sig in seen:
            penalty *= 1.5  # push for genuine diversity
            continue
        seen.add(sig)
        banned.update(sig)
        fatal_here = any(
            v.measure_index == measure_index
            for v in payload.biomechanical_report.violations
            if v.severity.value == "fatal"
        )
        candidates.append(
            _to_alternative(
                "tmp", window, orig_id_by_key, marginal_costs(payload.results),
                is_current=False, playable=not fatal_here,
            )
        )

    # Only ever propose *playable* alternatives — drop any candidate with a fatal
    # biomechanical violation in the measure (unplayable / impossible). The
    # current solution (variant #1) is always kept so the user sees what is being
    # reviewed, even when it is itself flagged. Remaining playable candidates are
    # ranked by lowest cost (closest to the current optimum).
    playable_candidates = sorted(
        (a for a in candidates if a.playable), key=lambda a: a.cost,
    )
    dropped = len(candidates) - len(playable_candidates)
    for i, alt in enumerate(playable_candidates[: count - 1]):
        alternatives.append(replace(alt, variant_id=f"v{i + 2}"))

    if dropped:
        logger.info(
            "Dropped %d unplayable alternative(s) for measure %d.",
            dropped, measure_index,
        )
    if len(alternatives) < count:
        logger.info(
            "Only %d distinct playable alternatives for measure %d (requested %d).",
            len(alternatives), measure_index, count,
        )
    return alternatives


def _to_alternative(
    variant_id: str,
    window: list[FingeringResult],
    orig_id_by_key: dict[_NoteKey, int],
    costs: dict[int, float],
    *,
    is_current: bool,
    playable: bool,
) -> MeasureAlternative:
    fingerings: list[dict[str, object]] = []
    for r in sorted(window, key=lambda x: (x.note_event.onset, x.state.string_num)):
        key = _note_key(r.note_event)
        fingerings.append(
            {
                "note_id": orig_id_by_key.get(key, r.note_id),
                "string": r.state.string_num,
                "fret": r.state.fret,
                "finger": r.state.finger.value,
                "hand_position": r.state.hand_position,
                "onset": round(r.note_event.onset, 6),
                "pitch": r.note_event.pitch,
                "voice_hint": r.note_event.voice_hint,
            }
        )
    cost = round(sum(costs.get(r.note_id, 0.0) for r in window), 4)
    return MeasureAlternative(
        variant_id=variant_id,
        is_current=is_current,
        fingerings=fingerings,
        cost=cost,
        label="Actuel" if is_current else _label(window),
        playable=playable,
    )
