"""Source-file quality assessment.

Guitar Pro is a permissive format authored by amateurs of varying skill.
Bad source data (wrong frets, impossible stretches, pitch-hint conflicts)
is common and will produce algorithm output that *looks* like a bug but
is actually a downstream artefact of the input.

**Methodology**: at every anomaly observed in FretWise output, check the
source quality BEFORE attributing the anomaly to the algorithm. If the
file scores poorly, the pathology should be flagged as "likely data
issue, not algo bug" and excluded from algorithm-quality metrics.

The functions here are pure (no I/O after `parse`). They consume a
list[NoteEvent] and produce a ``QualityReport``.

Reasonable thresholds (calibrated from observation, refine as needed):

| Feature | Clean | Suspect | Bad |
|---|---|---|---|
| pitch_hint_conflict_rate | 0 | <1% | ≥1% |
| very_high_fret_count (>24) | 0 | 1-3 | ≥4 |
| excessive_chord_span_count (>5 frets) | 0 | 1-5 | ≥6 |
| density (notes/beat) | <6 | 6-10 | ≥10 |

A file is "bad enough to exclude" if **any** Bad threshold is exceeded.
A file is "suspect" if **two or more** Suspect thresholds are exceeded.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass

from fretwise.models import NoteEvent

# MIDI pitches of open strings in standard EADGBE (string 1 = high e).
_STANDARD_TUNING: list[int] = [64, 59, 55, 50, 45, 40]


def _infer_tuning(events: list[NoteEvent]) -> list[int]:
    """Infer per-string open-string MIDI pitches from event hints.

    For each string number, looks at every event with string_hint + fret_hint
    + pitch and computes ``pitch - fret_hint`` (the implied open-string pitch).
    Takes the most common value per string as the inferred tuning.

    Strings without any reliable evidence keep the EADGBE default. This makes
    quality assessment robust to non-standard tunings (drop-D, half-step
    down, etc.) without depending on parser metadata.
    """
    candidates: dict[int, Counter[int]] = defaultdict(Counter)
    for e in events:
        if (
            e.string_hint is not None
            and e.fret_hint is not None
            and 1 <= e.string_hint <= len(_STANDARD_TUNING)
        ):
            candidates[e.string_hint][e.pitch - e.fret_hint] += 1

    tuning = list(_STANDARD_TUNING)
    for s, counter in candidates.items():
        if counter:
            tuning[s - 1] = counter.most_common(1)[0][0]
    return tuning

# Thresholds — refine on corpus evidence.
_VERY_HIGH_FRET = 24       # GP allows up to 27 but real guitars stop at 22–24.
_EXCESSIVE_SPAN = 5        # Physically impossible chord span (frets).
_DENSITY_SUSPECT = 6.0     # Notes per beat above which content is dubious.
_DENSITY_BAD = 10.0


@dataclass(frozen=True)
class QualityReport:
    """Aggregate quality features of a GP source.

    Attributes:
        note_count: Total NoteEvents parsed.
        duration_beats: Span from first to last onset.
        density: ``note_count / max(duration_beats, 1)``.
        pitch_hint_conflicts: Notes where ``string_hint`` + ``fret_hint``
            does not reproduce the parsed ``pitch``. Strong evidence of
            authoring error or parser misalignment.
        very_high_fret_count: Notes with ``fret_hint > 24``.
        excessive_chord_span_count: Chord onsets where simultaneous frets
            span more than 5 frets (anatomically impossible).
        max_chord_span: Largest span observed in any chord.
        verdict: ``"clean"``, ``"suspect"``, or ``"bad"``.
        rationale: Human-readable explanation of the verdict.
    """

    note_count: int
    duration_beats: float
    density: float
    pitch_hint_conflicts: int
    very_high_fret_count: int
    excessive_chord_span_count: int
    max_chord_span: int
    verdict: str
    rationale: str

    @property
    def is_clean(self) -> bool:
        return self.verdict == "clean"

    @property
    def is_suspect(self) -> bool:
        return self.verdict == "suspect"

    @property
    def is_bad(self) -> bool:
        return self.verdict == "bad"


def assess_source_quality(events: list[NoteEvent]) -> QualityReport:
    """Compute a quality report on a parsed NoteEvent sequence."""
    n = len(events)
    if n == 0:
        return QualityReport(
            note_count=0, duration_beats=0.0, density=0.0,
            pitch_hint_conflicts=0, very_high_fret_count=0,
            excessive_chord_span_count=0, max_chord_span=0,
            verdict="bad", rationale="empty file: no NoteEvents parsed",
        )

    onsets = [e.onset for e in events]
    duration = max(onsets) - min(onsets)
    density = n / max(duration, 1.0)

    tuning = _infer_tuning(events)

    pitch_hint_conflicts = 0
    very_high_fret_count = 0
    for e in events:
        if e.string_hint and e.fret_hint is not None:
            sh = e.string_hint
            if 1 <= sh <= len(tuning):
                expected = tuning[sh - 1] + e.fret_hint
                if expected != e.pitch:
                    pitch_hint_conflicts += 1
        if e.fret_hint is not None and e.fret_hint > _VERY_HIGH_FRET:
            very_high_fret_count += 1

    by_onset: dict[float, list[int]] = defaultdict(list)
    for e in events:
        if e.fret_hint is not None and e.fret_hint > 0:
            by_onset[round(e.onset, 4)].append(e.fret_hint)
    spans = [max(f) - min(f) for f in by_onset.values() if len(f) >= 2]
    max_chord_span = max(spans) if spans else 0
    excessive_chord_span_count = sum(1 for s in spans if s > _EXCESSIVE_SPAN)

    conflict_rate = pitch_hint_conflicts / n

    bad_flags = []
    suspect_flags = []
    if conflict_rate >= 0.01:
        bad_flags.append(f"{100 * conflict_rate:.1f}% pitch-hint conflicts")
    elif conflict_rate > 0:
        suspect_flags.append(f"{pitch_hint_conflicts} pitch-hint conflicts")
    if very_high_fret_count >= 4:
        bad_flags.append(f"{very_high_fret_count} frets > {_VERY_HIGH_FRET}")
    elif very_high_fret_count > 0:
        suspect_flags.append(f"{very_high_fret_count} frets > {_VERY_HIGH_FRET}")
    if excessive_chord_span_count >= 6:
        bad_flags.append(f"{excessive_chord_span_count} chord spans > {_EXCESSIVE_SPAN}")
    elif excessive_chord_span_count > 0:
        suspect_flags.append(f"{excessive_chord_span_count} chord spans > {_EXCESSIVE_SPAN}")
    if density >= _DENSITY_BAD:
        bad_flags.append(f"density {density:.2f} >= {_DENSITY_BAD}")
    elif density >= _DENSITY_SUSPECT:
        suspect_flags.append(f"density {density:.2f} >= {_DENSITY_SUSPECT}")

    if bad_flags:
        verdict, rationale = "bad", "; ".join(bad_flags)
    elif len(suspect_flags) >= 2:
        verdict, rationale = "suspect", "; ".join(suspect_flags)
    elif suspect_flags:
        verdict, rationale = "clean", "minor: " + "; ".join(suspect_flags)
    else:
        verdict, rationale = "clean", "no warning flags"

    return QualityReport(
        note_count=n,
        duration_beats=duration,
        density=density,
        pitch_hint_conflicts=pitch_hint_conflicts,
        very_high_fret_count=very_high_fret_count,
        excessive_chord_span_count=excessive_chord_span_count,
        max_chord_span=max_chord_span,
        verdict=verdict,
        rationale=rationale,
    )
