"""Generate hand-viz JSON data for the browser visualization.

Usage:
    python scripts/generate_hand_viz.py [gp_file]

By default, parses ``tests/fixtures/The Beatles-Yesterday-01-22-2026.gp``,
runs the full fingering pipeline, and writes the first 10 seconds of results
to ``web/hand_viz_data.json``. Open ``web/hand_viz.html`` in a browser next
to the JSON to view the animation.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fretwise.export.hand_viz import export_hand_viz_json
from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights


_ROOT = Path(__file__).parent.parent
_DEFAULT_GP = _ROOT / "tests" / "fixtures" / "The Beatles-Yesterday-01-22-2026.gp"
_OUT_JSON = _ROOT / "web" / "hand_viz_data.json"


def _split_artist_title(stem: str) -> tuple[str, str]:
    """Filename format is ``Artist-Title-MM-DD-YYYY``."""
    parts = stem.split("-")
    if len(parts) >= 5 and all(p.isdigit() for p in parts[-3:]):
        return parts[0].strip(), "-".join(parts[1:-3]).strip()
    return "", stem


def main() -> None:
    gp_path = Path(sys.argv[1]) if len(sys.argv) > 1 else _DEFAULT_GP
    print(f"[hand-viz] parsing {gp_path.name}")

    adapter = get_adapter(gp_path)
    events = adapter.parse(gp_path)
    track_name = getattr(adapter, "track_name", "") or ""

    cost_fn = CostFunction(weights=CostWeights.performance())
    gen = StateGenerator()
    opt = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    results, stats = run_pipeline(events, gen, opt, pattern_matcher=matcher)

    artist, title = _split_artist_title(gp_path.stem)
    data = export_hand_viz_json(
        results,
        _OUT_JSON,
        title=title,
        artist=artist,
        track_name=track_name,
        max_seconds=10.0,
    )
    print(
        f"[hand-viz] stats: {stats}  -> kept {len(data['frames'])} frames "
        f"in the first {data['meta']['max_seconds']:.0f}s "
        f"(tempo {data['meta']['tempo']:.0f})",
    )
    print(f"[hand-viz] wrote {_OUT_JSON}")


if __name__ == "__main__":
    main()
