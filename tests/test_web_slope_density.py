"""Behavioral tests for the Slope density control.

Density exposes how many beats of upcoming notes are visible on screen at
once. Fewer beats means the same physical path length covers less musical
time, so notes glide slower in px/s and sit farther apart — both reduce the
residual smooth-pursuit slip (the eye's tracking gain never reaches 1,
independent of screen refresh rate) relative to glyph size. These tests
execute the real shipped ``slope-renderer.js`` in Node and assert on actual
geometry/position output, not source text.
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
