"""Run concordance validation on GP fixtures.

Compares FretWise's optimised fingerings against the original tab data
(string_hint / fret_hint) from Guitar Pro files.

Usage:
    python scripts/validate_concordance.py                      # all fixtures
    python scripts/validate_concordance.py tests/fixtures/song.gp  # one file
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights
from fretwise.validation import (
    ConcordanceReport,
    compute_concordance,
    format_concordance_report,
)

_OUT_DIR = Path(__file__).parent.parent / "docs" / "benchmarks"


def validate_file(
    gp_path: Path,
    mode: str = "reference",
) -> list[tuple[str, ConcordanceReport]]:
    """Run pipeline and compute concordance for all tracks in a GP file.

    Returns:
        List of (track_label, ConcordanceReport) tuples.
    """
    adapter = get_adapter(gp_path)
    weights = CostWeights.reference()
    cost_fn = CostFunction(weights=weights)
    generator = StateGenerator()
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()

    reports: list[tuple[str, ConcordanceReport]] = []

    if hasattr(adapter, "list_guitar_tracks"):
        tracks = adapter.list_guitar_tracks(gp_path)
        for track_id, track_name, _pitches in tracks:
            events = adapter.parse_track(gp_path, track_id)
            if not events:
                continue
            results, _stats = run_pipeline(
                events, generator, optimizer, pattern_matcher=matcher,
            )
            report = compute_concordance(results)
            reports.append((f"{gp_path.stem} / {track_name}", report))
    else:
        events = adapter.parse(gp_path)
        track_name = getattr(adapter, "track_name", "") or gp_path.stem
        if events:
            results, _stats = run_pipeline(
                events, generator, optimizer, pattern_matcher=matcher,
            )
            report = compute_concordance(results)
            reports.append((f"{gp_path.stem} / {track_name}", report))

    return reports


def main() -> None:
    if len(sys.argv) > 1:
        paths = [Path(a) for a in sys.argv[1:]]
    else:
        fixture_dir = Path(__file__).parent.parent / "tests" / "fixtures"
        paths = sorted(fixture_dir.glob("*.gp"))

    if not paths:
        print("No .gp files found.")
        sys.exit(1)

    all_reports: list[tuple[str, ConcordanceReport]] = []

    for p in paths:
        print(f"\n{'='*60}")
        print(f"File: {p.name}")
        print(f"{'='*60}")
        track_reports = validate_file(p)
        for label, report in track_reports:
            print(f"  {label}: {report.summary()}")
            all_reports.append((label, report))

    # Aggregate summary
    print(f"\n{'='*60}")
    print("AGGREGATE CONCORDANCE")
    print(f"{'='*60}")

    total_hinted = sum(r.hinted_notes for _, r in all_reports)
    total_str = sum(r.string_matches for _, r in all_reports)
    total_fret = sum(r.fret_matches for _, r in all_reports)
    total_pos = sum(r.position_matches for _, r in all_reports)
    total_notes = sum(r.total_notes for _, r in all_reports)

    if total_hinted > 0:
        print(f"Tracks          : {len(all_reports)}")
        print(f"Total notes     : {total_notes}")
        print(f"Hinted notes    : {total_hinted}")
        print(f"String match    : {total_str:>5d}  ({total_str/total_hinted:.1%})")
        print(f"Fret match      : {total_fret:>5d}  ({total_fret/total_hinted:.1%})")
        print(f"Position match  : {total_pos:>5d}  ({total_pos/total_hinted:.1%})")
    else:
        print("No hinted notes found in any file.")

    # Write detailed report
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    report_path = _OUT_DIR / "concordance_report.txt"
    with report_path.open("w", encoding="utf-8") as f:
        f.write("FretWise Concordance Validation Report\n")
        f.write("=" * 40 + "\n\n")
        for label, report in all_reports:
            f.write(format_concordance_report(report, title=label))
            f.write("\n\n")
    print(f"\nDetailed report: {report_path}")


if __name__ == "__main__":
    main()
