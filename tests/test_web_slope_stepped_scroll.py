"""Behavioral tests for the Slope P4 legibility mode (stepped scroll).

Continuous glide is what smooth pursuit can never track sharply, independent
of screen refresh rate (the eye's tracking gain tops out ~0.9). P4's answer
is to quantize the beat used for ON-SCREEN POSITIONING to a fixed step, so
motion becomes a sequence of brief held frames instead of continuous glide —
each hold is a real fixation window. The actual playback clock stays
continuous (audio sync / hit detection are unaffected); only what gets drawn
where is stepped. These tests execute the real shipped ``slope-renderer.js``
in Node and assert on actual geometry/fillText output, not source text.
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


def _run(script: str) -> dict:
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
  width: 0, height: 0, clientWidth: 900, clientHeight: 600, style: {{}},
  getContext: () => ctx,
  getBoundingClientRect: () => ({{ width: 900, height: 600, left: 0, top: 0 }}),
}};

const {{ SlopeRenderer }} = await import({json.dumps(_SLOPE_JS.as_uri())});

const data = {{
  tempo: 120,
  beats_per_measure: 4,
  results: [
    // Onsets deliberately clear of measure boundaries (multiples of 4) —
    // _markReadableLabels hides a note's digit near one, which would make
    // these position assertions flaky for reasons unrelated to P4 itself.
    {{ string: 3, fret: 7, finger: 'index', onset: 5.5, duration: 0.5, pitch: 62 }},
    {{ string: 3, fret: 9, finger: 'ring',  onset: 11.5, duration: 0.5, pitch: 65 }},
  ],
}};
const r = new SlopeRenderer(canvas, data);

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


def test_render_beat_quantizes_only_in_p4_mode() -> None:
    out = _run("""
r.setLegibilityMode('base');
r.currentBeat = 1.3;
const baseBeat = r._renderBeat();
r.setLegibilityMode('p4');
r.currentBeat = 1.3;
const p4Beat = r._renderBeat();
r.currentBeat = 1.6;
const p4Beat2 = r._renderBeat();
console.log(JSON.stringify({ baseBeat, p4Beat, p4Beat2, stepBeats: r.stepBeats }));
""")
    assert out["stepBeats"] == 0.5
    assert out["baseBeat"] == 1.3, "non-p4 modes must NOT quantize the render beat"
    assert out["p4Beat"] == 1.0, "1.3 must floor to the 0.5 step below it"
    assert out["p4Beat2"] == 1.5, "1.6 must floor to the 0.5 step below it"


def test_p4_holds_note_position_within_a_step_then_jumps() -> None:
    """The whole point: within one step, position must not move at all; once
    currentBeat crosses into the next step, it must jump discretely."""
    out = _run("""
r.setLegibilityMode('p4');
function noteX(beat) {
  r.currentBeat = beat;
  fillLog.length = 0;
  r.render();
  const hit = fillLog.find((e) => e.txt === '7');
  return hit ? hit.x : null;
}
const xAtStart = noteX(1.0);
const xMidStep = noteX(1.3); // same 0.5 step as 1.0 -> must floor to 1.0 too
const xNextStep = noteX(1.5); // new step
console.log(JSON.stringify({ xAtStart, xMidStep, xNextStep }));
""")
    assert out["xAtStart"] is not None and out["xNextStep"] is not None
    assert out["xMidStep"] == out["xAtStart"], "position must hold steady within one step"
    assert out["xNextStep"] != out["xAtStart"], "position must jump once the step boundary is crossed"


def test_other_modes_keep_continuous_motion() -> None:
    """Regression guard: P4's quantization must not leak into base/P1/P2/P3 —
    those must keep moving every frame, not just at step boundaries."""
    for mode in ("base", "p1", "p2", "p3"):
        out = _run(f"""
r.setLegibilityMode('{mode}');
function noteX(beat) {{
  r.currentBeat = beat;
  fillLog.length = 0;
  r.render();
  const hit = fillLog.find((e) => e.txt === '7');
  return hit ? hit.x : null;
}}
const xAtStart = noteX(1.0);
const xMidStep = noteX(1.3);
console.log(JSON.stringify({{ xAtStart, xMidStep }}));
""")
        assert out["xAtStart"] is not None and out["xMidStep"] is not None
        assert out["xMidStep"] != out["xAtStart"], (
            f"{mode} must keep gliding continuously, not hold like P4"
        )


def test_strike_line_never_jumps_regardless_of_mode() -> None:
    """The now-line is pinned to depth 0 directly (bypassing _depthForBeat),
    so it must sit at the exact same screen position in every mode/beat."""
    out = _run("""
const points = ['base', 'p1', 'p2', 'p3', 'p4'].map((mode) => {
  r.setLegibilityMode(mode);
  r.currentBeat = 3.7;
  return r._lanePoint(3, 0);
});
console.log(JSON.stringify(points));
""")
    xs = {round(p["x"], 6) for p in out}
    assert len(xs) == 1, f"strike line x must be identical across modes, saw {xs}"


def test_p4_readout_shows_the_step_and_clears_the_bottom_toolbar() -> None:
    out = _run("""
r.setLegibilityMode('p4');
fillLog.length = 0;
r.render();
const g = r._foldGeometry();
const tag = fillLog.find((e) => String(e.txt).includes('P4'));
console.log(JSON.stringify({
  tagText: tag ? tag.txt : null,
  tagY: tag ? tag.y : null,
  gapTop: g.topBase + g.spread / 2,
  gapBottom: g.bottomBase - g.spread / 2,
  bottomToolbarStartsAt: canvas.clientHeight - 88,
}));
""")
    assert out["tagText"] is not None, "P4 must draw a live readout tag"
    assert "0.5" in out["tagText"], "readout must show the current step size"
    assert out["tagY"] < out["bottomToolbarStartsAt"], "must clear the fixed bottom toolbar"
    assert out["gapTop"] < out["tagY"] < out["gapBottom"], "must sit inside the lane gap"


def test_p4_no_longer_renders_a_coming_soon_tag() -> None:
    out = _run("""
r.setLegibilityMode('p4');
fillLog.length = 0;
r.render();
console.log(JSON.stringify(fillLog.map((e) => e.txt)));
""")
    assert not any("à venir" in t.lower() for t in out), "P4 must not show the coming-soon tag"
