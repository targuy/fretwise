"""Canvas let-ring rendering (pure Tablature view).

The canvas TAB renderer used to draw let-ring as one horizontal band shared by
every string, dedup-ed by onset: an isolated ringing note produced only a tiny
label and *no* line at all, and chord let-rings collapsed onto a single row.

``TabRenderer._drawLetRingStrings`` now draws one dashed sustain line per string,
running from each ringing note along its own string to the next strike (or the
bar end). These tests execute the real ``renderer.js`` in Node so they fail on a
behavioural regression, not merely a moved string.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_RENDERER_JS = (
    Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "renderer.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run(scenario: str) -> dict:
    """Run renderer._drawLetRingStrings on a scenario; return recorded draw calls."""
    # A file:// URL, not a bare path: Node rejects absolute Windows paths as ESM
    # specifiers (ERR_UNSUPPORTED_ESM_URL_SCHEME — the drive letter reads as a scheme).
    harness = f"""
globalThis.window = {{ devicePixelRatio: 1, innerWidth: 1200 }};
globalThis.document = {{ documentElement: {{}} }};
globalThis.getComputedStyle = () => ({{ getPropertyValue: () => '' }});

const calls = [];
function mkCtx() {{
  let dash = [];
  let cur = [0, 0];
  return {{
    save(){{}}, restore(){{}}, beginPath(){{}},
    moveTo(x, y){{ cur = [x, y]; }},
    lineTo(x, y){{ calls.push({{ t:'line', x0:Math.round(cur[0]), y0:Math.round(cur[1]),
                                 x1:Math.round(x), y1:Math.round(y), dashed: dash.length>0 }}); }},
    setLineDash(d){{ dash = d; }}, stroke(){{}},
    fillText(txt, x, y){{ calls.push({{ t:'text', txt, x:Math.round(x), y:Math.round(y) }}); }},
    measureText(s){{ return {{ width: s.length * 4 }}; }},
    set font(v){{}}, set fillStyle(v){{}}, set strokeStyle(v){{}},
    set lineWidth(v){{}}, set textAlign(v){{}}, set textBaseline(v){{}},
  }};
}}
const canvas = {{ getContext: mkCtx, style:{{}}, width:0, height:0 }};

const {{ TabRenderer }} = await import({json.dumps(_RENDERER_JS.as_uri())});
const r = new TabRenderer(canvas, {{ results: [] }});
const ctx = mkCtx();

{scenario}

console.log(JSON.stringify(calls));
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_chord_let_ring_draws_one_dashed_line_per_string_no_overlap() -> None:
    """Two strings ringing → two dashed lines at distinct y (their own lanes)."""
    calls = _run("""
r._drawLetRingStrings(ctx, [
  { note:{ onset:0, string:1, let_ring:true }, x:100, y:80 },
  { note:{ onset:0, string:2, let_ring:true }, x:100, y:96 },
  { note:{ onset:1, string:1, let_ring:false }, x:160, y:80 },
], 0, 60, 500);
""")
    lines = [c for c in calls if c["t"] == "line" and c["dashed"]]
    assert len(lines) == 2, "one dashed line per ringing string"
    ys = sorted({line["y0"] for line in lines})
    assert len(ys) == 2, "the two lines must not share a row (the old overlap bug)"
    assert ys[1] - ys[0] >= 10, "lines sit in separate string lanes"


def test_isolated_let_ring_note_still_draws_a_line_to_bar_end() -> None:
    """Regression: a lone ringing note produced no line under the old band code."""
    calls = _run("""
r._drawLetRingStrings(ctx, [
  { note:{ onset:0, string:3, let_ring:true }, x:120, y:112 },
], 0, 60, 500);
""")
    lines = [c for c in calls if c["t"] == "line" and c["dashed"]]
    assert len(lines) == 1
    # Rings out to (near) the right edge of the measure.
    assert lines[0]["x1"] > 400
    assert any(c["t"] == "text" and c["txt"] == "let ring" for c in calls)


def test_let_ring_stops_at_next_strike_on_same_string() -> None:
    """The sustain line ends before the next struck note on that string."""
    calls = _run("""
r._drawLetRingStrings(ctx, [
  { note:{ onset:0, string:2, let_ring:true }, x:100, y:96 },
  { note:{ onset:2, string:2, let_ring:false }, x:300, y:96 },
], 0, 60, 500);
""")
    line = next(c for c in calls if c["t"] == "line" and c["dashed"])
    assert 100 < line["x1"] < 300, "line must terminate before the next strike"


def test_no_let_ring_notes_draws_nothing() -> None:
    calls = _run("""
r._drawLetRingStrings(ctx, [
  { note:{ onset:0, string:1, let_ring:false }, x:100, y:80 },
], 0, 60, 500);
""")
    assert calls == []
