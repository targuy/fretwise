"""Measure-level diversified alternatives via a windowed re-solve.

For a flagged measure we re-run the *existing* pipeline on a small window (the
measure plus a fixed context buffer), freezing the surrounding notes and asking
the optimizer for several *distinct* fingerings of the measure. Diversity is
obtained by penalising state choices already emitted by earlier variants — a
plain cost injection, so the Viterbi optimizer (M5) is never modified.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fretwise.config import ConfigNode, config
from fretwise.generator import StateGenerator
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
    context_events = [
        e for e in events
        if e.measure_index is not None and lo <= e.measure_index <= hi
    ]
    if not any(e.measure_index == measure_index for e in context_events):
        return []

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
    generator = ConstrainedStateGenerator(StateGenerator(), locks)
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
    alternatives.append(
        _to_alternative("v1", current_window, orig_id_by_key,
                        marginal_costs(results), is_current=True, playable=True)
    )

    penalty = base_penalty
    attempts = 0
    while len(alternatives) < count and attempts < max_attempts:
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
            penalty *= 1.5  # push harder for genuine diversity
            continue
        seen.add(sig)
        banned.update(sig)
        fatal_here = any(
            v.measure_index == measure_index
            for v in payload.biomechanical_report.violations
            if v.severity.value == "fatal"
        )
        alternatives.append(
            _to_alternative(
                f"v{len(alternatives) + 1}", window, orig_id_by_key,
                marginal_costs(payload.results),
                is_current=False, playable=not fatal_here,
            )
        )

    if len(alternatives) < count:
        logger.info(
            "Only %d distinct alternatives for measure %d (requested %d).",
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
