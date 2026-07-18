"""Behavioral tests for the Slope tempo-heart indicator's position.

The heart+BPM readout used to be pinned to the left corner (clientWidth *
0.055), which sits close to where the top lane's far/oldest-visible notes
and their chord labels/triangles cluster — collisions were confirmed in
practice ("Fmaj7" text landing on the heart icon). It's now centered
horizontally and pinned near the very top of the canvas, well clear of every
lane regardless of x. These tests execute the real shipped
``slope-renderer.js`` in Node and assert on actual geometry/fillText output,
not source text.
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


def _run(script: str, *, width: int = 968, height: int = 816) -> dict:
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

// A melody spread across the whole visible window, including near the top
// lane's far/oldest-visible end where the old heart position used to collide.
const data = {{
  tempo: 72,
  beats_per_measure: 4,
  results: Array.from({{ length: 24 }}, (_, i) => ({{
    string: (i % 6) + 1,
    fret: i % 12,
    finger: ['open', 'index', 'middle', 'ring', 'pinky'][i % 5],
    onset: i * 1.5,
    duration: 0.5,
    pitch: 40 + i,
    chord: i % 4 === 0 ? 'Am' : undefined,
  }})),
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


def test_heart_is_horizontally_centered() -> None:
    """The BPM text is drawn 44px right of the heart icon itself (cx + 44,
    see _drawTempoHeart) — check the heart icon's own cx, not the text's x."""
    out = _run("""
r.render();
const bpm = fillLog.find((e) => String(e.txt).includes('BPM'));
console.log(JSON.stringify({
  heartCx: bpm ? bpm.x - 44 : null,
  centerX: canvas.clientWidth / 2,
}));
""")
    assert out["heartCx"] is not None
    assert out["heartCx"] == pytest.approx(out["centerX"], abs=1), (
        "heart+BPM must be centered horizontally (\"au milieu\"), not left-pinned"
    )


def test_heart_sits_near_the_very_top_well_clear_of_topbase() -> None:
    out = _run("""
r.render();
const bpm = fillLog.find((e) => String(e.txt).includes('BPM'));
const g = r._foldGeometry();
console.log(JSON.stringify({ bpmY: bpm ? bpm.y : null, topBase: g.topBase }));
""")
    assert out["bpmY"] is not None
    assert out["bpmY"] < out["topBase"] - 60, (
        "heart must sit well above topBase, clear of the top lane and any "
        "chord label/triangle that sticks up past it"
    )


def test_heart_never_collides_with_note_or_chord_text_across_many_beats() -> None:
    """Regression guard for the originally-reported bug: sample several
    beats spanning a full loop of the visible window and confirm the BPM
    text never lands within a glyph-width of any note/chord label text."""
    out = _run("""
const results = [];
for (let beat = 0; beat < 20; beat += 2.5) {
  r.currentBeat = beat;
  fillLog.length = 0;
  r.render();
  const bpm = fillLog.find((e) => String(e.txt).includes('BPM'));
  if (!bpm) continue;
  const others = fillLog.filter((e) => e !== bpm);
  const collisions = others.filter((e) => Math.abs(e.x - bpm.x) < 10 && Math.abs(e.y - bpm.y) < 10);
  results.push({ beat, bpmX: bpm.x, bpmY: bpm.y, collisions: collisions.map((e) => e.txt) });
}
console.log(JSON.stringify(results));
""")
    for sample in out:
        assert sample["collisions"] == [], (
            f"beat {sample['beat']}: BPM text collided with {sample['collisions']}"
        )
