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
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

_OUT_DIR = Path(__file__).parent.parent / "docs" / "benchmarks"


def _safe_track_slug(name: str) -> str:
    """Turn a track name into a filesystem-safe slug."""
    slug = re.sub(r"[^\w\- ]", "", name).strip()
    slug = re.sub(r"\s+", "_", slug)
    return slug[:60] or "track"


def process_track(
    gp_path: Path,
    track_name: str,
    events: list,
    section_markers: dict,
    pdf_artist: str,
    pdf_title: str,
    mode: str,
    max_measures: int,
    out_stem: str,
    chord_diagrams: list | None = None,
) -> None:
    """Run the pipeline on a single track's events and write output files."""
    if not events:
        print(f"  [skip] No notes found.")
        return

    weights_cls = {
        "reference": CostWeights.reference,
        "performance": CostWeights.performance,
        "musical": CostWeights.musical,
        "learning": CostWeights.learning,
    }[mode]
    cost_fn = CostFunction(weights=weights_cls())
    generator = StateGenerator()
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    results, stats = run_pipeline(events, generator, optimizer, pattern_matcher=matcher)

    total_cost = sum(r.cost for r in results)
    print(f"  Notes  : {len(results)}  |  cost = {total_cost:.2f}")

    from collections import Counter
    if results:
        pitch_counts = Counter(r.note_event.pitch for r in results)
        most_common_pitch, most_common_count = pitch_counts.most_common(1)[0]
        ratio = most_common_count / len(results)
        if ratio > 0.4:
            print(
                f"  WARNING: {most_common_count}/{len(results)} notes share pitch "
                f"{most_common_pitch} ({ratio:.0%}) — may be wrong track."
            )

    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    title = f"{out_stem}  [{mode} mode]"

    report_path = _OUT_DIR / f"{out_stem}_report.txt"
    report_path.write_text(render_text_report(results, title=title), encoding="utf-8")
    print(f"  Report : {report_path.name}")

    tab_path = _OUT_DIR / f"{out_stem}_tab.txt"
    tab_path.write_text(
        render_ascii_tab(results, title=title, max_measures=max_measures), encoding="utf-8"
    )
    print(f"  Tab    : {tab_path.name}")

    pdf_path = _OUT_DIR / f"{out_stem}_tab.pdf"
    render_pdf_tab(
        results,
        pdf_path,
        title=pdf_title,
        artist=pdf_artist,
        instrument=track_name,
        mode_label=f"{mode} mode",
        section_markers=section_markers or None,
        chord_diagrams=chord_diagrams or None,
    )
    print(f"  PDF    : {pdf_path.name}")
    if chord_diagrams:
        print(f"  Chords : {len(chord_diagrams)} diagram(s) embedded in PDF")


def process(gp_path: Path, mode: str = "reference", max_measures: int = 20) -> None:
    print(f"\n{'='*60}")
    print(f"File : {gp_path.name}  [{mode} mode]")
    print(f"{'='*60}")

    stem = gp_path.stem
    clean_stem = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", stem).strip()
    parts = clean_stem.split("-", 1)
    pdf_title = parts[1].strip() if len(parts) == 2 else clean_stem
    pdf_artist = parts[0].strip() if len(parts) == 2 else ""

    adapter = get_adapter(gp_path)

    # -- Multi-track: process every guitar track if the adapter supports it.
    if hasattr(adapter, "list_guitar_tracks"):
        tracks = adapter.list_guitar_tracks(gp_path)
        if not tracks:
            print("No guitar tracks found — skipping.")
            return
        print(f"Tracks : {len(tracks)} guitar track(s) found")
        section_markers: dict[int, str] = {}
        for track_id, track_name, _pitches in tracks:
            slug = _safe_track_slug(track_name)
            out_stem = f"{stem}_{slug}"
            print(f"\n  Track [{track_id}] {track_name!r}")
            events = adapter.parse_track(gp_path, track_id)
            section_markers = dict(getattr(adapter, "section_markers", {}) or {})
            diagrams = list(getattr(adapter, "chord_diagrams", []) or [])
            print(f"  Parsed : {len(events)} notes")
            process_track(
                gp_path, track_name, events, section_markers,
                pdf_artist, pdf_title, mode, max_measures, out_stem,
                chord_diagrams=diagrams or None,
            )
        return

    # -- Single-track fallback (guitarpro_adapter, etc.)
    events = adapter.parse(gp_path)
    track_name_single: str = getattr(adapter, "track_name", "") or ""
    section_markers_single: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})
    diagrams_single: list = list(getattr(adapter, "chord_diagrams", []) or [])
    print(f"Parsed : {len(events)} notes"
          + (f"  [{track_name_single}]" if track_name_single else ""))

    if not events:
        print("No notes found — skipping.")
        return

    process_track(
        gp_path, track_name_single, events, section_markers_single,
        pdf_artist, pdf_title, mode, max_measures, stem,
        chord_diagrams=diagrams_single or None,
    )


def main() -> None:
    if len(sys.argv) > 1:
        paths = [Path(a) for a in sys.argv[1:]]
    else:
        fixture_dir = Path(__file__).parent.parent / "tests" / "fixtures"
        paths = sorted(fixture_dir.glob("*.gp"))

    if not paths:
        print("No .gp files found.")
        sys.exit(1)

    for p in paths:
        process(p)


if __name__ == "__main__":
    main()
