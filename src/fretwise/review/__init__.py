"""Fingering review & continuous improvement (M7).

Flags impossible / suspect / high-cost fingerings produced by the pipeline so a
user can review them one by one, pick a preferred alternative, and feed that
choice back into the system.

This module only *flags and ranks*; it reuses the existing biomechanical guard
(:mod:`fretwise.biomechanics`) and the cost-outlier logic shared with
:mod:`fretwise.audit` rather than re-deriving feasibility. Alternatives,
persistence and re-bias live in sibling modules.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum

from fretwise.biomechanics import (
    BiomechanicalReport,
    BiomechanicalSeverity,
    validate_fingering_results,
)
from fretwise.config import ConfigNode, config
from fretwise.models import FingeringResult
from fretwise.scoring import marginal_costs

logger = logging.getLogger(__name__)

# Public re-exports for the rest of the feature.
from fretwise.review.alternatives import (  # noqa: E402
    MeasureAlternative,
    measure_alternatives,
)
from fretwise.review.bias import (  # noqa: E402
    ConstrainedStateGenerator,
    FeedbackBiasedPlayerCost,
)
from fretwise.review.feedback import (  # noqa: E402
    FeedbackRecord,
    SongFeedback,
    append_corpus,
    feedback_dir,
    load_song_feedback,
    save_choice,
)

__all__ = [
    "ConstrainedStateGenerator",
    "FeedbackBiasedPlayerCost",
    "FeedbackRecord",
    "MeasureAlternative",
    "ReviewItem",
    "ReviewReport",
    "Severity",
    "SongFeedback",
    "append_corpus",
    "feedback_dir",
    "flag_fingerings",
    "load_song_feedback",
    "marginal_costs",
    "measure_alternatives",
    "save_choice",
]


class Severity(StrEnum):
    """Severity of a flagged fingering, highest first when ranked."""

    IMPOSSIBLE = "impossible"   # biomechanical FATAL violation — unplayable
    SUSPECT = "suspect"         # biomechanical HIGH violation — awkward/unsafe
    HIGH_COST = "high_cost"     # Viterbi cost far above the piece baseline


_SEVERITY_RANK: dict[Severity, int] = {
    Severity.IMPOSSIBLE: 3,
    Severity.SUSPECT: 2,
    Severity.HIGH_COST: 1,
}

# Biomechanical codes that are data/tuning artefacts rather than fingering-choice
# problems — the user cannot fix them by picking a finger, so they are noise in
# the review list. BIO-STATE-003 in particular fires on every bend/harmonic and
# on any non-standard tuning (it compares pitch to standard open-string + fret).
_NON_ACTIONABLE_CODES: frozenset[str] = frozenset(
    {"BIO-STATE-001", "BIO-STATE-002", "BIO-STATE-003"}
)


@dataclass(frozen=True)
class ReviewItem:
    """One spot to review, grouping all notes sounding at a given onset."""

    item_id: str
    measure_index: int
    onset: float
    note_ids: list[int]
    severity: Severity
    score: float
    reasons: list[str]
    current: list[dict[str, object]]


@dataclass(frozen=True)
class ReviewReport:
    """Ranked list of fingerings to review plus per-severity counts."""

    items: list[ReviewItem]
    counts: dict[str, int]
    truncated: bool = False


@dataclass
class _Group:
    """Mutable accumulator for one (measure, onset) review group."""

    measure_index: int
    onset: float
    note_ids: set[int] = field(default_factory=set)
    severity: Severity = Severity.HIGH_COST
    score: float = 0.0
    reasons: list[str] = field(default_factory=list)


def cost_baseline(marginals: Sequence[float]) -> float:
    """Return the 10th-percentile marginal cost — the piece "easy note" cost.

    Args:
        marginals: Per-note marginal costs.

    Returns:
        The 10th-percentile cost, or ``0.0`` when empty.
    """
    costs = sorted(marginals)
    if not costs:
        return 0.0
    return costs[max(0, int(len(costs) * 0.10))]


def flag_fingerings(
    results: Sequence[FingeringResult],
    *,
    biomech_report: BiomechanicalReport | None = None,
    cfg: ConfigNode | None = None,
) -> ReviewReport:
    """Flag and rank fingerings that warrant user review.

    Combines two signals, deduplicated and grouped by ``(measure, onset)``:

    * **Biomechanical** — FATAL violations become :attr:`Severity.IMPOSSIBLE`,
      HIGH violations become :attr:`Severity.SUSPECT` (reuses
      :func:`fretwise.biomechanics.validate_fingering_results`).
    * **Cost outliers** — notes whose Viterbi cost exceeds
      ``max(baseline * high_cost_ratio, high_cost_floor)`` become
      :attr:`Severity.HIGH_COST`.

    Args:
        results: Fingered results for the track.
        biomech_report: Pre-computed guard report; recomputed when ``None``.
        cfg: ``config().review`` node; loaded from defaults when ``None``.

    Returns:
        A :class:`ReviewReport` sorted by severity (desc), then score (desc),
        then measure and onset (asc).
    """
    review_cfg = cfg if cfg is not None else config().review
    if biomech_report is None:
        biomech_report = validate_fingering_results(results)

    by_id: dict[int, FingeringResult] = {r.note_id: r for r in results}
    groups: dict[tuple[int, float], _Group] = {}

    def _group_for(measure: int, onset: float) -> _Group:
        key = (measure, round(onset, 6))
        grp = groups.get(key)
        if grp is None:
            grp = _Group(measure_index=measure, onset=round(onset, 6))
            groups[key] = grp
        return grp

    def _bump(grp: _Group, sev: Severity, score: float, reason: str) -> None:
        if _SEVERITY_RANK[sev] > _SEVERITY_RANK[grp.severity]:
            grp.severity = sev
        grp.score = max(grp.score, score)
        if reason not in grp.reasons:
            grp.reasons.append(reason)

    # Signal 1 — biomechanical violations (FATAL → impossible, HIGH → suspect).
    for v in biomech_report.violations:
        if v.code in _NON_ACTIONABLE_CODES:
            continue  # data/tuning/bend artefact, not a fingering-choice issue
        if v.severity == BiomechanicalSeverity.FATAL:
            sev = Severity.IMPOSSIBLE
        elif v.severity == BiomechanicalSeverity.HIGH:
            sev = Severity.SUSPECT
        else:
            continue  # MEDIUM/LOW are advisory — keep the list actionable.
        measure = v.measure_index
        # Resolve onset/measure from the offending notes when missing.
        onset = v.onset
        ids = [nid for nid in v.note_ids if nid in by_id]
        if measure is None and ids:
            measure = by_id[ids[0]].note_event.measure_index
        if onset is None and ids:
            onset = by_id[ids[0]].note_event.onset
        if measure is None or onset is None:
            continue
        grp = _group_for(measure, onset)
        grp.note_ids.update(ids)
        reason = f"{v.code}: {v.message}" if v.message else v.code
        _bump(grp, sev, 10.0 + len(ids), reason)

    # Signal 2 — cost outliers, using per-note marginal (not cumulative) cost.
    marginals = marginal_costs(results)
    baseline = cost_baseline(list(marginals.values()))
    threshold = max(baseline * float(review_cfg.high_cost_ratio),
                    float(review_cfg.high_cost_floor))
    denom = baseline if baseline > 1e-6 else 1.0
    for r in results:
        marginal = marginals.get(r.note_id)
        if marginal is None or marginal <= threshold:
            continue
        measure = r.note_event.measure_index
        if measure is None:
            continue
        ratio = marginal / denom
        grp = _group_for(measure, r.note_event.onset)
        grp.note_ids.add(r.note_id)
        _bump(grp, Severity.HIGH_COST, ratio, f"coût {ratio:.1f}× base")

    items: list[ReviewItem] = []
    for grp in groups.values():
        ids = sorted(grp.note_ids)
        current = [_serialize_current(by_id[nid]) for nid in ids if nid in by_id]
        rep_string = current[0]["string"] if current else 0
        rep_fret = current[0]["fret"] if current else 0
        item_id = f"{grp.measure_index}:{grp.onset:.4f}:{rep_string}:{rep_fret}"
        items.append(
            ReviewItem(
                item_id=item_id,
                measure_index=grp.measure_index,
                onset=grp.onset,
                note_ids=ids,
                severity=grp.severity,
                score=round(grp.score, 4),
                reasons=grp.reasons,
                current=current,
            )
        )

    items.sort(
        key=lambda it: (
            -_SEVERITY_RANK[it.severity],
            -it.score,
            it.measure_index,
            it.onset,
        )
    )

    counts = {sev.value: 0 for sev in Severity}
    for it in items:
        counts[it.severity.value] += 1

    max_items = int(review_cfg.max_items)
    truncated = len(items) > max_items
    if truncated:
        logger.info("Review list truncated: %d items capped to %d.", len(items), max_items)
        items = items[:max_items]

    return ReviewReport(items=items, counts=counts, truncated=truncated)


def _serialize_current(r: FingeringResult) -> dict[str, object]:
    """Serialize one result's chosen fingering for the review payload."""
    return {
        "note_id": r.note_id,
        "string": r.state.string_num,
        "fret": r.state.fret,
        "finger": r.state.finger.value,
        "hand_position": r.state.hand_position,
        "pitch": r.note_event.pitch,
    }
