"""Behavioral tests for the Slope 180-degree turn being a true circular arc.

_traceDepthPath used to approximate the whole string path — including the
turn — with a fixed number of sampled points connected by straight lineTo
segments (a polyline). Straight lane segments don't need that (any two
points on them are colinear), and the turn, the only genuinely curved part,
got whichever fraction of those samples happened to land inside it — visibly
faceted rather than a smooth semicircle. The fix draws the turn with a
single native ctx.arc() call per string instead. These tests execute the
real shipped ``slope-renderer.js`` in Node and assert on actual canvas
draw-call output, not source text.
"""

from __future__ import annotations

import json
import math
import shutil
import subprocess
from pathlib import Path

import pytest

_SLOPE_JS = (
    Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "slope-renderer.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run(script: str) -> dict:
    harness = f"""
globalThis.performance = globalThis.performance || {{ now: () => 0 }};
function makeCtx(calls) {{
  const store = {{}};
  const grad = {{ addColorStop() {{}} }};
  return new Proxy({{}}, {{
    get(_t, prop) {{
      if (prop === 'moveTo') return (x, y) => calls.push({{ op: 'moveTo', x, y }});
      if (prop === 'lineTo') return (x, y) => calls.push({{ op: 'lineTo', x, y }});
      if (prop === 'arc') return (x, y, radius, startAngle, endAngle, anticlockwise) =>
        calls.push({{ op: 'arc', x, y, radius, startAngle, endAngle, anticlockwise: !!anticlockwise }});
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

const calls = [];
const ctx = makeCtx(calls);
const canvas = {{
  width: 0, height: 0, clientWidth: 1200, clientHeight: 700, style: {{}},
  getContext: () => ctx,
  getBoundingClientRect: () => ({{ width: 1200, height: 700, left: 0, top: 0 }}),
}};

const {{ SlopeRenderer }} = await import({json.dumps(_SLOPE_JS.as_uri())});
const data = {{ tempo: 120, beats_per_measure: 4, results: [] }};
const r = new SlopeRenderer(canvas, data);
const g = r._foldGeometry();

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


def test_full_lane_trace_uses_exactly_one_native_arc_call_for_the_turn() -> None:
    """Tracing string 3 across its whole path (bottom -> turn -> top) must
    hit the turn with ONE ctx.arc() call, not a pile of sampled lineTo
    points standing in for a curve."""
    out = _run("""
calls.length = 0;
r._traceDepthPath(ctx, 3, 0, 1);
const arcs = calls.filter((c) => c.op === 'arc');
const lineTos = calls.filter((c) => c.op === 'lineTo');
console.log(JSON.stringify({ arcCount: arcs.length, lineToCount: lineTos.length }));
""")
    assert out["arcCount"] == 1, f"expected exactly 1 native arc() call, got {out['arcCount']}"
    # Only the two straight segments (bottom, top) still need lineTo, and
    # each needs at most 2 (their own start + end) — nowhere near the old
    # ~18-42-sample polyline that used to stand in for the curve too.
    assert out["lineToCount"] <= 4, (
        f"expected a small, bounded lineTo count (straight segments only), got {out['lineToCount']}"
    )


def test_arc_call_geometry_matches_a_true_180_degree_turn() -> None:
    """The arc's center/radius must match _foldGeometry's bend point and
    this string's own concentric radius, sweeping exactly +90deg to -90deg
    (a true semicircle) the short way (anticlockwise)."""
    out = _run("""
calls.length = 0;
r._traceDepthPath(ctx, 1, 0, 1);
const arc = calls.find((c) => c.op === 'arc');
const offset = r._stringOffset(1);
console.log(JSON.stringify({
  arc, bendX: g.bendX, centerY: g.centerY, expectedRadius: g.radius + offset,
}));
""")
    arc = out["arc"]
    assert arc is not None
    assert arc["x"] == pytest.approx(out["bendX"], abs=0.01)
    assert arc["y"] == pytest.approx(out["centerY"], abs=0.01)
    assert arc["radius"] == pytest.approx(out["expectedRadius"], abs=0.01)
    assert arc["startAngle"] == pytest.approx(math.pi / 2, abs=1e-6)
    assert arc["endAngle"] == pytest.approx(-math.pi / 2, abs=1e-6)
    assert arc["anticlockwise"] is True, "must sweep the direct 180deg way, not the long way around"


def test_different_strings_get_different_concentric_radii() -> None:
    """Each string traces its own circle (radius = g.radius + per-string
    offset) around the SAME bend center — that's what keeps the 6 strings
    visually parallel through the turn instead of collapsing to one curve."""
    out = _run("""
const radii = [1, 3, 6].map((stringNum) => {
  calls.length = 0;
  r._traceDepthPath(ctx, stringNum, 0, 1);
  const arc = calls.find((c) => c.op === 'arc');
  return { stringNum, radius: arc.radius, offset: r._stringOffset(stringNum) };
});
console.log(JSON.stringify(radii));
""")
    radii = {r["stringNum"]: r["radius"] for r in out}
    assert radii[1] != radii[3] != radii[6], "each string must get a distinct radius"
    # String 1 sits above center (negative offset), string 6 below (positive) —
    # so string 1's radius must be smaller than string 6's.
    assert radii[1] < radii[3] < radii[6]


def test_partial_range_entirely_inside_the_turn_still_uses_native_arc() -> None:
    """A note whose segment lies entirely within the turn (not spanning a
    lane) must still get a single native arc() call, with a narrower angle
    range than the full +-90deg sweep — not a special-cased polyline."""
    out = _run("""
const midDepth = (g.bottomLen + g.arcLen / 2) / g.totalLen;
const quarterDepth = (g.bottomLen + g.arcLen * 0.25) / g.totalLen;
calls.length = 0;
r._traceDepthPath(ctx, 2, quarterDepth, midDepth);
console.log(JSON.stringify(calls));
""")
    arcs = [c for c in out if c["op"] == "arc"]
    line_tos = [c for c in out if c["op"] == "lineTo"]
    assert len(arcs) == 1, f"expected 1 arc call for an arc-only range, got {len(arcs)}"
    assert line_tos == [], "a range entirely inside the turn needs no lineTo at all"
    arc = arcs[0]
    span = abs(arc["startAngle"] - arc["endAngle"])
    assert span < math.pi - 0.1, f"a quarter-to-half arc span must be narrower than the full 180deg, got {span}"


def test_pure_straight_segments_never_call_arc() -> None:
    """A range entirely within the bottom or top lane must draw pure
    straight lines — no arc() call at all."""
    out = _run("""
calls.length = 0;
r._traceDepthPath(ctx, 4, 0, 0.1); // well inside the bottom lane
const bottomArcs = calls.filter((c) => c.op === 'arc').length;
calls.length = 0;
r._traceDepthPath(ctx, 4, 0.95, 1.05); // well inside the top lane
const topArcs = calls.filter((c) => c.op === 'arc').length;
console.log(JSON.stringify({ bottomArcs, topArcs }));
""")
    assert out["bottomArcs"] == 0
    assert out["topArcs"] == 0


def test_endpoints_match_lanepoint_exactly_at_the_lane_handoffs() -> None:
    """The arc's start/end points must line up exactly with _lanePoint's own
    bottom-lane and top-lane formulas at the handoff depths — continuity
    across the straight-to-curved transition, not just a visually-close
    approximation."""
    out = _run("""
const offset = r._stringOffset(5);
const arcStartDepth = g.bottomLen / g.totalLen;
const arcEndDepth = (g.bottomLen + g.arcLen) / g.totalLen;
const pAtArcStart = r._lanePoint(5, arcStartDepth);
const pAtArcEnd = r._lanePoint(5, arcEndDepth);
const arcStartX = g.bendX + Math.cos(Math.PI / 2) * (g.radius + offset);
const arcStartY = g.centerY + Math.sin(Math.PI / 2) * (g.radius + offset);
const arcEndX = g.bendX + Math.cos(-Math.PI / 2) * (g.radius + offset);
const arcEndY = g.centerY + Math.sin(-Math.PI / 2) * (g.radius + offset);
console.log(JSON.stringify({
  pAtArcStart, pAtArcEnd, arcStartX, arcStartY, arcEndX, arcEndY,
}));
""")
    assert out["pAtArcStart"]["x"] == pytest.approx(out["arcStartX"], abs=0.01)
    assert out["pAtArcStart"]["y"] == pytest.approx(out["arcStartY"], abs=0.01)
    assert out["pAtArcEnd"]["x"] == pytest.approx(out["arcEndX"], abs=0.01)
    assert out["pAtArcEnd"]["y"] == pytest.approx(out["arcEndY"], abs=0.01)
