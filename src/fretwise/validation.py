"""Concordance validation — compare FretWise output against source tablature.

Measures how well the optimizer's choices match the original tab author's
string/fret assignments.  Only meaningful for GP files where string_hint and
fret_hint are provided by the parser.

Metrics:
    string_concordance  — % of notes where chosen string == source string
    fret_concordance    — % of notes where chosen fret   == source fret
    position_concordance — % of notes where BOTH match
"""

from __future__ import annotations

from dataclasses import dataclass, field

from fretwise.models import FingeringResult


@dataclass
class ConcordanceReport:
    """Concordance metrics for a single piece or track.

    Attributes:
        total_notes: Total notes in the result.
        hinted_notes: Notes with both string_hint and fret_hint.
        string_matches: Count where state.string_num == string_hint.
        fret_matches: Count where state.fret == fret_hint.
        position_matches: Count where both string AND fret match.
        deviations: List of (note_id, expected_str, expected_fret,
                    actual_str, actual_fret) for mismatched notes.
    """

    total_notes: int = 0
    hinted_notes: int = 0
    string_matches: int = 0
    fret_matches: int = 0
    position_matches: int = 0
    deviations: list[tuple[int, int, int, int, int]] = field(default_factory=list)

    @property
    def string_concordance(self) -> float:
        """Fraction of hinted notes with matching string (0.0–1.0)."""
        return self.string_matches / self.hinted_notes if self.hinted_notes else 0.0

    @property
    def fret_concordance(self) -> float:
        """Fraction of hinted notes with matching fret (0.0–1.0)."""
        return self.fret_matches / self.hinted_notes if self.hinted_notes else 0.0

    @property
    def position_concordance(self) -> float:
        """Fraction of hinted notes with both string AND fret matching."""
        return self.position_matches / self.hinted_notes if self.hinted_notes else 0.0

    def summary(self) -> str:
        """One-line summary string."""
        if self.hinted_notes == 0:
            return f"No hinted notes (total: {self.total_notes})"
        return (
            f"string={self.string_concordance:.1%}  "
            f"fret={self.fret_concordance:.1%}  "
            f"position={self.position_concordance:.1%}  "
            f"({self.hinted_notes}/{self.total_notes} hinted)"
        )


def compute_concordance(results: list[FingeringResult]) -> ConcordanceReport:
    """Compute concordance between optimizer output and source tab hints.

    Args:
        results: FingeringResult list from the pipeline.

    Returns:
        ConcordanceReport with all metrics populated.
    """
    report = ConcordanceReport(total_notes=len(results))

    for r in results:
        ne = r.note_event
        if ne.string_hint is None or ne.fret_hint is None:
            continue

        report.hinted_notes += 1
        str_match = r.state.string_num == ne.string_hint
        fret_match = r.state.fret == ne.fret_hint

        if str_match:
            report.string_matches += 1
        if fret_match:
            report.fret_matches += 1
        if str_match and fret_match:
            report.position_matches += 1
        else:
            report.deviations.append((
                r.note_id,
                ne.string_hint,
                ne.fret_hint,
                r.state.string_num,
                r.state.fret,
            ))

    return report


def format_concordance_report(
    report: ConcordanceReport,
    title: str = "",
) -> str:
    """Format a human-readable concordance report.

    Args:
        report: A ConcordanceReport.
        title: Optional title line.

    Returns:
        Multi-line string suitable for console or file output.
    """
    lines: list[str] = []
    if title:
        lines.append(title)
        lines.append("=" * len(title))
    lines.append("")
    lines.append(f"Total notes     : {report.total_notes}")
    lines.append(f"Hinted notes    : {report.hinted_notes}")
    lines.append(f"String match    : {report.string_matches:>5d}  "
                 f"({report.string_concordance:.1%})")
    lines.append(f"Fret match      : {report.fret_matches:>5d}  "
                 f"({report.fret_concordance:.1%})")
    lines.append(f"Position match  : {report.position_matches:>5d}  "
                 f"({report.position_concordance:.1%})")
    lines.append(f"Deviations      : {len(report.deviations)}")

    if report.deviations:
        lines.append("")
        lines.append("Top deviations (note_id, expected→actual):")
        lines.append(
            f"  {'#':>5s}  {'exp_str':>7s}  {'exp_fret':>8s}  "
            f"{'act_str':>7s}  {'act_fret':>8s}"
        )
        lines.append("  " + "-" * 45)
        for nid, es, ef, as_, af in report.deviations[:30]:
            lines.append(f"  {nid:>5d}  {es:>7d}  {ef:>8d}  {as_:>7d}  {af:>8d}")
        if len(report.deviations) > 30:
            lines.append(f"  ... {len(report.deviations) - 30} more deviation(s)")

    return "\n".join(lines)
