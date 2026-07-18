"""Behavioral tests for the Slope P3 legibility mode (strike magnifier).

P1 previews a row of upcoming note groups several beats of runway ahead; P3
answers a narrower question — "what am I about to play, right now, in
fixation, at maximum size?" It shows only the single next unstruck group,
enlarged to fill the lane gap, with a static countdown fill bar (not motion)
communicating how soon the strike is. These tests execute the real shipped
``slope-renderer.js`` in Node and assert on actual fillText output, not
source text.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_SLOPE_JS = (
    Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "slope-renderer.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run(script: str, *, width: int = 900, height: int = 600) -> dict:
    harness = f"""
globalThis.performance = globalThis.performance || {{ now: () => 0 }};
function makeCtx(fillLog) {{
  const store = {{}};
  const grad = {{ addColorStop() {{}} }};
  return new Proxy({{}}, {{
    get(_t, prop) {{
      if (prop === 'fillText') return (txt, x, y) => fillLog.push({{ txt: String(txt), x, y }});
      if (prop === 'createLinearGradient') return () => grad;
      if (prop === 'measureText') return (s) => ({{ width: String(s).length * 6 }});
      if (prop in store) return store[prop];
      return () => {{}};
    }},
    set(_t, prop, val) {{ store[prop] = val; return true; }},
  }});
}}
globalThis.window = {{ devicePixelRatio: 1, addEventListener() {{}}, removeEventListener() {{}} }};
globalThis.document = {{
  createElement() {{ return {{ width: 0, height: 0, getContext: () => makeCtx([]) }}; }},
}};

const fillLog = [];
const ctx = makeCtx(fillLog);
const canvas = {{
  width: 0, height: 0, clientWidth: {width}, clientHeight: {height}, style: {{}},
  getContext: () => ctx,
  getBoundingClientRect: () => ({{ width: {width}, height: {height}, left: 0, top: 0 }}),
}};

const {{ SlopeRenderer }} = await import({json.dumps(_SLOPE_JS.as_uri())});

const data = {{
  tempo: 120,
  beats_per_measure: 4,
  results: [
    {{ string: 1, fret: 7, finger: 'ring',   onset: 2.0, duration: 0.5, pitch: 71 }},
    {{ string: 4, fret: 6, finger: 'ring',   onset: 2.0, duration: 0.5, pitch: 56 }},
    {{ string: 2, fret: 5, finger: 'index',  onset: 2.5, duration: 0.5, pitch: 64 }},
    {{ string: 3, fret: 5, finger: 'index',  onset: 3.0, duration: 0.5, pitch: 60 }},
    {{ string: 1, fret: 8, finger: 'pinky',  onset: 3.5, duration: 0.5, pitch: 72 }},
  ],
}};
const r = new SlopeRenderer(canvas, data);
r.setLegibilityMode('p3');

// Isolate the magnifier's OWN fillText calls, not the moving discs or the
// permanent string-name labels that can share the same y-range (the same
// false-positive trap the P1 band tests hit with a naive y-region filter).
const magnifierCalls = [];
const origMagnifier = r._drawStrikeMagnifier.bind(r);
r._drawStrikeMagnifier = (...args) => {{
  const startIdx = fillLog.length;
  origMagnifier(...args);
  magnifierCalls.push(...fillLog.slice(startIdx));
}};

function frame(beat) {{
  r.currentBeat = beat;
  fillLog.length = 0;
  magnifierCalls.length = 0;
  r.render();
  return {{
    all: fillLog.map((e) => e.txt),
    magnifier: magnifierCalls.map((e) => ({{ txt: e.txt, x: e.x, y: e.y }})),
  }};
}}

{script}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_p3_shows_only_the_single_next_group() -> None:
    """Unlike P1's 4-group row, P3 shows exactly one group — the imminent one."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.magnifier.map((e) => e.txt)));
""")
    # Fret digits from the SECOND group (onset 2.5, fret 5) or later must not
    # appear — only the first group (onset 2.0: frets 7 and 6) is shown.
    digits = [t for t in out if t in ("5", "8")]
    assert digits == [], f"P3 must show only the next group, saw later frets {digits}"
    assert "7" in out and "6" in out, "P3 must show the imminent group's frets"


def test_p3_magnifier_does_not_cross_into_the_arc() -> None:
    """Same arc-avoidance rule as P1's band: confined to the straight run."""
    out = _run(
        """
const f = frame(1.0);
const g = r._foldGeometry();
console.log(JSON.stringify({ magnifier: f.magnifier, bendX: g.bendX, outerRadius: g.outerRadius }));
""",
        width=1400,
        height=650,
    )
    arcStartX = out["bendX"] - out["outerRadius"]
    overflow = [e for e in out["magnifier"] if e["x"] > arcStartX]
    assert overflow == [], f"magnifier text must stay left of the arc, saw {overflow}"


def test_p3_magnifier_sits_in_the_lane_gap_not_under_the_bottom_toolbar() -> None:
    """Same bottom-toolbar-clearance bug class as P1's original band fix."""
    out = _run("""
const f = frame(1.0);
const g = r._foldGeometry();
console.log(JSON.stringify({
  magnifier: f.magnifier,
  gapTop: g.topBase + g.spread / 2,
  gapBottom: g.bottomBase - g.spread / 2,
  bottomToolbarStartsAt: canvas.clientHeight - 88,
}));
""")
    assert out["magnifier"], "magnifier must draw something"
    for e in out["magnifier"]:
        assert e["y"] < out["bottomToolbarStartsAt"], f"{e} sits under the bottom toolbar"
        assert out["gapTop"] - 20 <= e["y"] <= out["gapBottom"] + 20, f"{e} escapes the lane gap"


def test_p3_countdown_shrinks_as_the_strike_approaches() -> None:
    """The '+beatsAway' readout must count down toward the strike, not just
    sit static — confirms the magnifier is actually reading the clock."""
    out = _run("""
const far = frame(0.2).magnifier.find((e) => String(e.txt).startsWith('+'));
const near = frame(1.8).magnifier.find((e) => String(e.txt).startsWith('+'));
console.log(JSON.stringify({ far: far ? far.txt : null, near: near ? near.txt : null }));
""")
    assert out["far"] is not None and out["near"] is not None
    far_val = float(out["far"].lstrip("+"))
    near_val = float(out["near"].lstrip("+"))
    assert near_val < far_val, "beats-away readout must shrink as currentBeat nears the onset"


def test_p3_swaps_to_the_next_group_once_the_current_one_is_struck() -> None:
    """A discrete flip, not a glide: once onset 2.0 is in the past, the
    magnifier must show group 2 (onset 2.5, fret 5), not group 1 anymore."""
    out = _run("""
const f = frame(2.6);
console.log(JSON.stringify(f.magnifier.map((e) => e.txt)));
""")
    assert "5" in out, "must have swapped to the next group's fret"
    assert "7" not in out and "6" not in out, "must have dropped the already-struck group"


def test_p3_no_longer_renders_a_coming_soon_tag() -> None:
    """P3 is implemented now — the placeholder tag must be gone."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.all));
""")
    assert not any("à venir" in t.lower() for t in out), "P3 must not show the coming-soon tag"
    assert not any("P3" in t and "loupe" in t.lower() for t in out)


def test_other_modes_do_not_draw_the_magnifier() -> None:
    """base/P1/P2/P4 must not draw the 'AVANT LA FRAPPE' magnifier card."""
    for mode in ("base", "p1", "p2", "p4"):
        out = _run(f"""
r.setLegibilityMode('{mode}');
const f = frame(1.0);
console.log(JSON.stringify(f.all));
""")
        assert not any("AVANT LA FRAPPE" in t for t in out), f"{mode} must not draw the magnifier"
