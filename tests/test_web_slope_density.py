"""Behavioral tests for the Slope P2 density control.

P2 exposes how many beats of upcoming notes are visible on screen at once.
Fewer beats means the same physical path length covers less musical time, so
notes glide slower in px/s and sit farther apart — both reduce the residual
smooth-pursuit slip (the eye's tracking gain never reaches 1, independent of
screen refresh rate) relative to glyph size. These tests execute the real
shipped ``slope-renderer.js`` in Node and assert on actual geometry/position
output, not source text.
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
    {{ string: 3, fret: 7, finger: 'index', onset: 1.0, duration: 0.5, pitch: 62 }},
    {{ string: 3, fret: 9, finger: 'ring', onset: 5.0, duration: 0.5, pitch: 65 }},
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


def test_density_defaults_to_the_minimum_density_beats() -> None:
    """No-op by default: a user who never touches the slider gets the slowest,
    most legible glide (MIN_DENSITY_BEATS), matching the slider's own default."""
    out = _run("console.log(JSON.stringify({ futureBeats: r.futureBeats }));")
    assert out["futureBeats"] == 24  # MIN_DENSITY_BEATS = MEASURE_BEATS(4) * 6


def test_set_density_lowers_future_beats_and_recomputes_geometry() -> None:
    """A lower density value slows the glide: fewer beats span the same path,
    so px-per-beat goes up (each beat of music occupies more screen space)."""
    out = _run("""
r.setDensity(48); // warm the geometry cache at the top of the range
r.render();
const before = r._foldGeometry().totalLen;
const beforePxPerBeat = before / r.futureBeats;
r.setDensity(24);
r.render();
const after = r._foldGeometry().totalLen;
const afterPxPerBeat = after / r.futureBeats;
console.log(JSON.stringify({
  futureBeats: r.futureBeats,
  beforePxPerBeat, afterPxPerBeat,
}));
""")
    assert out["futureBeats"] == 24
    assert out["afterPxPerBeat"] > out["beforePxPerBeat"], (
        "lower density must give each beat MORE screen space (slower glide)"
    )


def test_set_density_is_clamped_to_a_sane_range() -> None:
    """An extreme value must not collapse the lane or shrink notes to specks."""
    out = _run("""
r.setDensity(1);
const tooLow = r.futureBeats;
r.setDensity(999);
const tooHigh = r.futureBeats;
r.setDensity(NaN);
const afterNaN = r.futureBeats;
console.log(JSON.stringify({ tooLow, tooHigh, afterNaN }));
""")
    assert out["tooLow"] == 24  # MIN_DENSITY_BEATS
    assert out["tooHigh"] == 48  # MAX_DENSITY_BEATS
    assert out["afterNaN"] == 48, "a non-finite value must be ignored, not blank the setting"


def test_p2_readout_shows_the_current_density_and_clears_the_bottom_toolbar() -> None:
    """P2's tag confirms the live setting (not a 'coming soon' placeholder) and
    must sit in the lane gap, not under the fixed bottom playback toolbar
    (main.js BOT_GUTTER ~88px) — the same bug that hid the P1 band."""
    out = _run("""
r.setLegibilityMode('p2');
r.setDensity(31.5);
fillLog.length = 0;
r.render();
const g = r._foldGeometry();
const tag = fillLog.find((e) => String(e.txt).includes('P2'));
console.log(JSON.stringify({
  tagText: tag ? tag.txt : null,
  tagY: tag ? tag.y : null,
  gapTop: g.topBase + g.spread / 2,
  gapBottom: g.bottomBase - g.spread / 2,
  bottomToolbarStartsAt: canvas.clientHeight - 88,
}));
""")
    assert out["tagText"] is not None, "P2 must draw a live readout tag"
    assert "31.5" in out["tagText"], "readout must show the current density value"
    assert out["tagY"] < out["bottomToolbarStartsAt"], "must clear the fixed bottom toolbar"
    assert out["gapTop"] < out["tagY"] < out["gapBottom"], "must sit inside the lane gap"


def test_p2_maximizes_circle_radius_and_drops_the_note_name_letter() -> None:
    """P2's whole point is maximum-size digits: bigger discs than base/P1, and
    the note-name letter dropped so the freed space goes to the fret digit."""
    out = _run("""
r.setLegibilityMode('base');
const baseRadius = r._circleRadius();
r.setLegibilityMode('p2');
const p2Radius = r._circleRadius();
fillLog.length = 0;
r.currentBeat = 1.0;
r.render();
console.log(JSON.stringify({
  baseRadius, p2Radius,
  texts: fillLog.map((e) => e.txt),
}));
""")
    assert out["p2Radius"] > out["baseRadius"], "P2 discs must be bigger than base"
    letters = [t for t in out["texts"] if t in ("A", "B", "C", "D", "E", "F", "G")]
    assert letters == [], f"P2 discs must not draw the note-name letter, saw {letters}"


def test_p3_p4_coming_soon_tags_also_clear_the_bottom_toolbar() -> None:
    """Regression: _drawModeComingSoonTag shared the same bottom-pinned bug as
    the P1 band before the fix; both now route through the shared _tagY()."""
    for mode in ("p3", "p4"):
        out = _run(f"""
r.setLegibilityMode('{mode}');
fillLog.length = 0;
r.render();
const tag = fillLog.find((e) => String(e.txt).toUpperCase().includes('{mode.upper()}'));
console.log(JSON.stringify({{
  tagY: tag ? tag.y : null,
  bottomToolbarStartsAt: canvas.clientHeight - 88,
}}));
""")
        assert out["tagY"] is not None, f"{mode} must draw its tag"
        assert out["tagY"] < out["bottomToolbarStartsAt"], f"{mode} tag must clear the toolbar"
