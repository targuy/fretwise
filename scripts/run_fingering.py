"""Run fingering optimization on a .gp file and write readable output.

Usage:
    python scripts/run_fingering.py tests/fixtures/song.gp

Outputs (next to the input file, or in docs/benchmarks/):
    <name>_report.txt    — note-by-note table (onset, pitch, string, fret, finger, cost)
    <name>_tab.txt       — ASCII tablature with finger annotations (first 20 measures)
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

# Ensure src/ is on the path when running as a script.
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fretwise.export import render_ascii_tab, render_pdf_tab, render_text_report
from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

_OUT_DIR = Path(__file__).parent.parent / "docs" / "benchmarks"


def process(gp_path: Path, mode: str = "reference", max_measures: int = 20) -> None:
    print(f"\n{'='*60}")
    print(f"File   : {gp_path.name}")
    print(f"Mode   : {mode}")
    print(f"{'='*60}")

    # -- Parse
    adapter = get_adapter(gp_path)
    events = adapter.parse(gp_path)
    track_name: str = getattr(adapter, "track_name", "") or ""
    section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})
    print(f"Parsed : {len(events)} notes"
          + (f"  [{track_name}]" if track_name else "")
          + (f"  {len(section_markers)} section(s)" if section_markers else ""))

    if not events:
        print("No notes found — skipping.")
        return

    # -- Generate states, Viterbi, post-process (per voice)
    weights_cls = {
        "reference": CostWeights.reference,
        "performance": CostWeights.performance,
        "musical": CostWeights.musical,
        "learning": CostWeights.learning,
    }[mode]
    cost_fn = CostFunction(weights=weights_cls())
    generator = StateGenerator()
    optimizer = ViterbiOptimizer(cost_fn)
    results, stats = run_pipeline(events, generator, optimizer)

    print(f"States : {stats['valid_states']} total  "
          f"({stats['valid_states']}/{stats['parsed']} notes have valid states)")
    total_cost = sum(r.cost for r in results)
    print(f"Viterbi: {len(results)} results  |  total cost = {total_cost:.2f}")

    # Degenerate track heuristic: warn if > 40% of results share the same pitch
    # (likely a wrong track — keyboard pedal note, click track, etc.)
    if results:
        from collections import Counter
        pitch_counts = Counter(r.note_event.pitch for r in results)
        most_common_pitch, most_common_count = pitch_counts.most_common(1)[0]
        ratio = most_common_count / len(results)
        if ratio > 0.4:
            print(
                f"WARNING: {most_common_count}/{len(results)} notes share pitch "
                f"{most_common_pitch} ({ratio:.0%}). "
                "This may be the wrong track (keyboard/bass pedal note?)."
            )

    # -- Output paths
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    stem = gp_path.stem
    # Strip trailing Songsterr-style date suffix "-MM-DD-YYYY"
    clean_stem = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", stem).strip()
    # Split "Artist-Song" into artist / title on first dash
    parts = clean_stem.split("-", 1)
    pdf_title = parts[1].strip() if len(parts) == 2 else clean_stem
    pdf_artist = parts[0].strip() if len(parts) == 2 else ""
    title = f"{stem}  [{mode} mode]"

    # -- Text report (all notes)
    report_path = _OUT_DIR / f"{stem}_report.txt"
    report = render_text_report(results, title=title)
    report_path.write_text(report, encoding="utf-8")
    print(f"Report : {report_path}")

    # -- ASCII tab (first N measures)
    tab_path = _OUT_DIR / f"{stem}_tab.txt"
    tab = render_ascii_tab(results, title=title, max_measures=max_measures)
    tab_path.write_text(tab, encoding="utf-8")
    print(f"Tab    : {tab_path}  (first {max_measures} measures)")

    # -- PDF tab (full song)
    pdf_path = _OUT_DIR / f"{stem}_tab.pdf"
    render_pdf_tab(
        results,
        pdf_path,
        title=pdf_title,
        artist=pdf_artist,
        instrument=track_name,
        mode_label=f"{mode} mode",
        section_markers=section_markers or None,
    )
    print(f"PDF    : {pdf_path}")

    # -- Quick preview (4 measures)
    preview = render_ascii_tab(results, title=title, max_measures=4)
    print("\n--- ASCII tab preview (4 measures) ---")
    for line in preview.splitlines():
        print(line)
    print("...")


def main() -> None:
    if len(sys.argv) > 1:
        paths = [Path(a) for a in sys.argv[1:]]
    else:
        # Default: both fixture files
        fixture_dir = Path(__file__).parent.parent / "tests" / "fixtures"
        paths = sorted(fixture_dir.glob("*.gp"))

    if not paths:
        print("No .gp files found.")
        sys.exit(1)

    for p in paths:
        process(p)


if __name__ == "__main__":
    main()
