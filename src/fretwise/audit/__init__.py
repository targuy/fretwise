"""Quality audit over a fingered score, grouped by movement.

Produces a per-movement verdict (``clean`` / ``suspect`` / ``bad``) by
combining three independent signals:

  - **Source quality**: anomalies in the parsed NoteEvent stream
    (delegates to :func:`fretwise.quality.assess_source_quality`).
  - **Algorithmic uncertainty**: notes whose Viterbi cost sits far above
    the piece-wide median (heuristic for "system at its limits").
  - **ML confidence**: per-transition entropy of the Phase 3 ONNX
    classifier when a model is supplied. Low entropy = model is sure,
    high entropy = "the model genuinely doesn't know."

Movements are segmented either from explicit ``section_markers`` provided
by the source parser, or by detecting runs of consecutive silent measures
in the NoteEvent stream as an implicit fallback.

This module is **pure logic** — no I/O, no UI, no ONNX import at module
load. The optional ML signal is computed lazily when a ``ml_cost_model``
argument is passed.
"""
from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Literal, Sequence

from fretwise.models import FingeringResult, NoteEvent
from fretwise.quality import assess_source_quality

__all__ = [
    "MovementSpan",
    "MovementVerdict",
    "AuditReport",
    "split_by_movement",
    "audit_score",
]


# Tuned defaults — calibrated on the partitions/ corpus.
# Rationale: rock music in performance mode (γ=2) has uniformly high costs
# and the ML model (GAPS 32% accuracy) is rarely confident — so naive
# thresholds fire on every piece. The audit is meant to surface SYSTEM
# LIMITS, not normal difficulty. The bar is therefore very high.
DEFAULT_SILENT_MEASURE_THRESHOLD = 2     # ≥ N silent measures = movement break
DEFAULT_HIGH_COST_RATIO_BAD = 0.75       # ≥ 75% of notes are 3× baseline cost
DEFAULT_HIGH_COST_RATIO_SUSPECT = 0.50   # ≥ 50% of notes are 3× baseline cost
# Max entropy on 5 classes = log2(5) ≈ 2.32 bits. Threshold 2.0 means
# "the model is essentially guessing across most classes."
DEFAULT_ML_ENTROPY_THRESHOLD = 2.0
DEFAULT_ML_UNCERTAIN_RATIO_BAD = 0.85    # ≥ 85% of transitions near-uniform
DEFAULT_ML_UNCERTAIN_RATIO_SUSPECT = 0.70


@dataclass(frozen=True)
class MovementSpan:
    """Range of measures belonging to one movement.

    Attributes:
        measure_start: 1-based inclusive first measure.
        measure_end: 1-based inclusive last measure.
        name: Display name (e.g. "Allegro" if explicit, "Movement 2" if
            implicit).
        source: ``"explicit"`` when derived from a parser-provided section
            marker, ``"implicit"`` when inferred from a silent-measure gap,
            ``"whole_piece"`` when no segmentation was possible.
    """

    measure_start: int
    measure_end: int
    name: str
    source: Literal["explicit", "implicit", "whole_piece"]


@dataclass(frozen=True)
class MovementVerdict:
    """Audit verdict for one movement.

    Attributes:
        span: The movement boundaries.
        verdict: One of ``"clean"``, ``"suspect"``, ``"bad"``. ``"bad"`` is
            the trigger for the UI to hide fingerings on this movement.
        reasons: Short tokens explaining which signals contributed
            (e.g. ``["source_bad", "high_cost_density"]``). Empty when
            ``verdict == "clean"``.
        signals: Raw numeric signals for diagnostics / future tuning.
        note_count: Notes in this movement (sanity check; empty movements
            get verdict ``"clean"`` by convention — nothing to flag).
    """

    span: MovementSpan
    verdict: Literal["clean", "suspect", "bad"]
    reasons: list[str]
    signals: dict[str, float]
    note_count: int


@dataclass(frozen=True)
class AuditReport:
    """Aggregate audit over an entire score.

    Attributes:
        movements: One verdict per movement, in source order.
        overall: Worst verdict across movements (``"bad"`` if any is bad,
            else ``"suspect"`` if any is suspect, else ``"clean"``).
        source_quality_verdict: The whole-score source verdict from
            :func:`fretwise.quality.assess_source_quality` (kept for
            convenience; the per-movement signal is recomputed locally).
        ml_signal_available: True iff the audit consumed a learned cost
            model (consumers may render an "audit limited" hint when False).
    """

    movements: list[MovementVerdict]
    overall: Literal["clean", "suspect", "bad"]
    source_quality_verdict: str
    ml_signal_available: bool

    @property
    def bad_movements(self) -> list[MovementVerdict]:
        """Movements that should hide fingerings in the UI by default."""
        return [m for m in self.movements if m.verdict == "bad"]


# ---------------------------------------------------------------------------
# Movement segmentation
# ---------------------------------------------------------------------------


def split_by_movement(
    events: Sequence[NoteEvent],
    section_markers: dict[int, str] | None = None,
    silent_measure_threshold: int = DEFAULT_SILENT_MEASURE_THRESHOLD,
) -> list[MovementSpan]:
    """Segment a piece into movements.

    Strategy, in order of preference:
      1. **Explicit**: if ``section_markers`` is non-empty, use those
         (each marker starts a new movement at its measure).
      2. **Implicit**: otherwise look for runs of ``>= silent_measure_threshold``
         consecutive silent measures inside the piece's measure range —
         these are treated as movement breaks. Movements are named
         "Movement 1", "Movement 2", …
      3. **Fallback**: if neither yields a split, return a single
         ``source="whole_piece"`` span covering all measures with notes.

    Args:
        events: NoteEvents (any order, ``measure_index`` is read).
        section_markers: Optional ``{1-based measure number → title}`` map
            from the source parser. Pass ``None`` or ``{}`` to skip.
        silent_measure_threshold: Implicit break detection: a run of at
            least this many silent measures triggers a new movement.

    Returns:
        Non-empty list of ``MovementSpan`` in source order.
        Empty input returns ``[]``.
    """
    measures_with_notes = sorted({
        e.measure_index for e in events if e.measure_index is not None
    })
    if not measures_with_notes:
        return []

    first_measure = measures_with_notes[0]
    last_measure = measures_with_notes[-1]

    # Strategy 1: explicit section markers.
    if section_markers:
        return _segment_from_markers(
            section_markers, first_measure, last_measure,
        )

    # Strategy 2: implicit silent-gap detection.
    spans = _segment_from_silent_gaps(
        measures_with_notes, silent_measure_threshold,
    )
    if len(spans) > 1:
        return spans

    # Strategy 3: whole piece.
    return [MovementSpan(
        measure_start=first_measure,
        measure_end=last_measure,
        name="Whole piece",
        source="whole_piece",
    )]


def _segment_from_markers(
    markers: dict[int, str],
    first_measure: int,
    last_measure: int,
) -> list[MovementSpan]:
    """Build movement spans starting at each section marker."""
    sorted_marks = sorted(markers.items())  # [(measure, title), ...]
    # The first movement may start before the first marker (e.g. intro).
    starts: list[tuple[int, str]] = []
    if sorted_marks[0][0] > first_measure:
        starts.append((first_measure, "Intro"))
    starts.extend(sorted_marks)
    starts.append((last_measure + 1, ""))  # sentinel for end

    spans: list[MovementSpan] = []
    for i in range(len(starts) - 1):
        start_measure, name = starts[i]
        next_start = starts[i + 1][0]
        end_measure = next_start - 1
        if end_measure < start_measure:
            continue  # marker beyond the range with no measures after
        spans.append(MovementSpan(
            measure_start=start_measure,
            measure_end=end_measure,
            name=name or f"Movement {len(spans) + 1}",
            source="explicit",
        ))
    return spans


def _segment_from_silent_gaps(
    measures_with_notes: list[int],
    silent_threshold: int,
) -> list[MovementSpan]:
    """Detect runs of silent measures as implicit movement breaks."""
    if not measures_with_notes:
        return []

    spans: list[MovementSpan] = []
    movement_start = measures_with_notes[0]
    last_seen = measures_with_notes[0]

    for measure in measures_with_notes[1:]:
        gap = measure - last_seen - 1  # silent measures between them
        if gap >= silent_threshold:
            spans.append(MovementSpan(
                measure_start=movement_start,
                measure_end=last_seen,
                name=f"Movement {len(spans) + 1}",
                source="implicit",
            ))
            movement_start = measure
        last_seen = measure

    spans.append(MovementSpan(
        measure_start=movement_start,
        measure_end=last_seen,
        name=f"Movement {len(spans) + 1}",
        source="implicit",
    ))
    return spans


# ---------------------------------------------------------------------------
# Audit
# ---------------------------------------------------------------------------


def audit_score(
    events: list[NoteEvent],
    results: list[FingeringResult],
    *,
    section_markers: dict[int, str] | None = None,
    ml_cost_model: object | None = None,
    silent_measure_threshold: int = DEFAULT_SILENT_MEASURE_THRESHOLD,
) -> AuditReport:
    """Audit a fingered score and return per-movement verdicts.

    Args:
        events: All parsed NoteEvents (needed for source quality on the
            full piece + movement segmentation).
        results: All FingeringResults from the pipeline, one per fingered
            note. Order does not matter.
        section_markers: Optional explicit section/movement markers from
            the source parser.
        ml_cost_model: Optional PlayerCostModel instance (e.g.
            ``LearnedPlayerCost``). When provided, the audit computes ML
            entropy per transition and uses it as a quality signal.
        silent_measure_threshold: Forwarded to ``split_by_movement``.

    Returns:
        ``AuditReport`` covering the whole piece.
    """
    movements = split_by_movement(
        events, section_markers, silent_measure_threshold,
    )
    source_report = assess_source_quality(events)

    # Baseline cost for "expensive" notes: 10th percentile of all costs.
    # Captures "what the easy notes cost in this piece" without being
    # skewed by majority — robust even when 80%+ of notes are expensive
    # (the lower-half median fails there because the bottom half still
    # contains expensive notes if they dominate).
    # If everything is uniformly expensive, the threshold stays high and
    # nothing flags — that's correct: uniformly hard ≠ system at limit.
    all_costs = sorted(r.cost for r in results if r.cost is not None)
    if all_costs:
        p10_index = max(0, int(len(all_costs) * 0.10))
        baseline_cost = all_costs[p10_index]
    else:
        baseline_cost = 0.0

    # Pre-compute ML entropy per result-index when a model is available.
    ml_entropy_by_result: dict[int, float] = {}
    ml_available = ml_cost_model is not None
    if ml_available:
        ml_entropy_by_result = _compute_ml_entropy_per_result(
            results, ml_cost_model,
        )

    verdicts: list[MovementVerdict] = []
    for span in movements:
        movement_events = [
            e for e in events
            if e.measure_index is not None
            and span.measure_start <= e.measure_index <= span.measure_end
        ]
        movement_results = [
            r for r in results
            if r.note_event.measure_index is not None
            and span.measure_start <= r.note_event.measure_index <= span.measure_end
        ]
        verdicts.append(_audit_one_movement(
            span=span,
            movement_events=movement_events,
            movement_results=movement_results,
            piece_baseline_cost=baseline_cost,
            ml_entropy_by_result=ml_entropy_by_result,
            ml_available=ml_available,
        ))

    overall: Literal["clean", "suspect", "bad"] = "clean"
    if any(v.verdict == "bad" for v in verdicts):
        overall = "bad"
    elif any(v.verdict == "suspect" for v in verdicts):
        overall = "suspect"

    return AuditReport(
        movements=verdicts,
        overall=overall,
        source_quality_verdict=source_report.verdict,
        ml_signal_available=ml_available,
    )


def _audit_one_movement(
    *,
    span: MovementSpan,
    movement_events: list[NoteEvent],
    movement_results: list[FingeringResult],
    piece_baseline_cost: float,
    ml_entropy_by_result: dict[int, float],
    ml_available: bool,
) -> MovementVerdict:
    """Compute the verdict for a single movement."""
    note_count = len(movement_events)
    reasons: list[str] = []
    signals: dict[str, float] = {}

    if note_count == 0:
        return MovementVerdict(
            span=span, verdict="clean", reasons=[], signals={},
            note_count=0,
        )

    # Signal 1: source quality on the movement subset.
    src_report = assess_source_quality(movement_events)
    signals["source_density"] = src_report.density
    signals["source_chord_span"] = float(src_report.max_chord_span)
    signals["source_conflicts"] = float(src_report.pitch_hint_conflicts)
    source_red = src_report.is_bad
    source_amber = src_report.is_suspect

    # Signal 2: algorithmic uncertainty — notes well above piece median cost.
    high_cost_threshold = max(piece_baseline_cost * 3, 5.0)
    high_cost_count = sum(
        1 for r in movement_results
        if r.cost is not None and r.cost > high_cost_threshold
    )
    high_cost_ratio = (
        high_cost_count / len(movement_results) if movement_results else 0.0
    )
    signals["high_cost_ratio"] = high_cost_ratio
    signals["high_cost_threshold"] = high_cost_threshold
    cost_red = high_cost_ratio >= DEFAULT_HIGH_COST_RATIO_BAD
    cost_amber = (
        high_cost_ratio >= DEFAULT_HIGH_COST_RATIO_SUSPECT and not cost_red
    )

    # Signal 3: ML uncertainty (entropy of softmax). Only fires when a model
    # was supplied. Entropy is the honest signal per advisor — flat
    # distributions mean "the model doesn't know," independent of
    # rule-based agreement.
    ml_red = ml_amber = False
    if ml_available and movement_results:
        entropies = [
            ml_entropy_by_result[r.note_id]
            for r in movement_results
            if r.note_id in ml_entropy_by_result
        ]
        if entropies:
            uncertain_count = sum(
                1 for e in entropies if e >= DEFAULT_ML_ENTROPY_THRESHOLD
            )
            uncertain_ratio = uncertain_count / len(entropies)
            signals["ml_median_entropy"] = statistics.median(entropies)
            signals["ml_uncertain_ratio"] = uncertain_ratio
            ml_red = uncertain_ratio >= DEFAULT_ML_UNCERTAIN_RATIO_BAD
            ml_amber = (
                uncertain_ratio >= DEFAULT_ML_UNCERTAIN_RATIO_SUSPECT
                and not ml_red
            )

    # Verdict combination — conservative cascade. Algo and ML signals are
    # noisy in isolation (rock music has uniformly high costs; the v3 model
    # has 32% GAPS accuracy and rarely emits confident softmax), so they
    # only count as red when they CO-OCCUR with another signal. Source
    # quality is the most reliable individual signal and stands alone.
    if source_red:
        reasons.append("source_bad")
    if cost_red:
        reasons.append("high_cost_density")
    if ml_red:
        reasons.append("ml_uncertain")
    if source_amber and not source_red:
        reasons.append("source_suspect")
    if cost_amber and not cost_red:
        reasons.append("elevated_cost")
    if ml_amber and not ml_red:
        reasons.append("ml_borderline")

    verdict: Literal["clean", "suspect", "bad"]
    if source_red:
        verdict = "bad"
    elif cost_red and ml_red:
        # Both algo and ML say "limit" — strong combined signal.
        verdict = "bad"
    elif source_amber and (cost_red or ml_red):
        verdict = "suspect"
    elif cost_red or ml_red:
        # One strong but noisy signal alone → soft warning.
        verdict = "suspect"
    elif source_amber and (cost_amber or ml_amber):
        verdict = "suspect"
    else:
        verdict = "clean"

    return MovementVerdict(
        span=span,
        verdict=verdict,
        reasons=reasons,
        signals=signals,
        note_count=note_count,
    )


def _compute_ml_entropy_per_result(
    results: list[FingeringResult],
    ml_cost_model: object,
) -> dict[int, float]:
    """Return ``{note_id → entropy}`` of the softmax for each transition.

    Uses the same ``_predict_probs`` private API as the parity tests.
    Skips notes whose previous-state context is missing (first note of a
    voice). On any error from the model, that transition is silently
    omitted so the audit degrades gracefully — never breaks the pipeline.
    """
    from fretwise.ml import _PHASE3_FINGER_TO_INDEX

    if not results:
        return {}

    # Group results by voice so we have meaningful "previous note" pairs.
    by_voice: dict[int, list[FingeringResult]] = {}
    for r in results:
        v = r.note_event.voice_hint if r.note_event.voice_hint is not None else 0
        by_voice.setdefault(v, []).append(r)
    for voice_results in by_voice.values():
        voice_results.sort(key=lambda r: r.note_event.onset)

    entropies: dict[int, float] = {}
    predict = getattr(ml_cost_model, "_predict_probs", None)
    if predict is None:
        return entropies

    for voice_results in by_voice.values():
        for i in range(1, len(voice_results)):
            prev = voice_results[i - 1]
            curr = voice_results[i]
            try:
                probs = predict(
                    prev_string_model=prev.state.string_num - 1,
                    prev_fret=prev.state.fret,
                    prev_finger_model=_PHASE3_FINGER_TO_INDEX.get(
                        prev.state.finger.value, 0,
                    ),
                    curr_string_model=curr.state.string_num - 1,
                    curr_fret=curr.state.fret,
                )
            except Exception:
                continue
            entropies[curr.note_id] = _shannon_entropy(probs)
    return entropies


def _shannon_entropy(probs: Sequence[float]) -> float:
    """Shannon entropy in bits of a probability distribution.

    Returns 0 for one-hot, ``log2(n)`` for uniform over n classes
    (i.e. 2.32 bits for a 5-class flat softmax).
    """
    entropy = 0.0
    for p in probs:
        if p > 0:
            entropy -= p * math.log2(p)
    return entropy
