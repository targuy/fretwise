"""Behavioral tests for the Slope reading band (chord-diagram lookahead).

The band is a fixed strip (read in fixation, never glided) showing a genuine
6-string chord shape per upcoming group: every string gets a row, played
strings get a filled disc + fret digit (no note-name letter — string
identity comes from fixed row position, row 0 = string 1), unplayed/muted
strings get a hollow ring. 20 upcoming groups, one chord triangle per card
(not per note). These tests execute the real shipped ``slope-renderer.js``
in Node and assert on actual canvas draw-call output, not source text.
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


def _run(script: str, *, width: int = 1400, height: int = 700) -> dict:
    # Wider/taller than the default test canvas elsewhere: the band's 20 tall
    # cards need real room in the lane gap to avoid every case degrading to
    # the graceful-shrink floor, which would mask real bugs in the
    # normal-size path.
    harness = f"""
globalThis.performance = globalThis.performance || {{ now: () => 0 }};
function makeCtx(fillLog, shapeLog, styleLog) {{
  const store = {{}};
  const grad = {{ addColorStop() {{}} }};
  let lastShape = null;
  return new Proxy({{}}, {{
    get(_t, prop) {{
      if (prop === 'fillText') return (txt, x, y) => fillLog.push({{ txt: String(txt), x, y }});
      if (prop === 'createLinearGradient') return () => grad;
      if (prop === 'measureText') return (s) => ({{ width: String(s).length * 6 }});
      if (prop === 'beginPath') return () => {{ lastShape = null; }};
      if (prop === 'arc') return (x, y, radius) => {{
        lastShape = {{ x, y, radius, kind: null }};
        shapeLog.push(lastShape);
      }};
      if (prop === 'fill') return () => {{ if (lastShape) lastShape.kind = 'fill'; }};
      if (prop === 'stroke') return () => {{ if (lastShape) lastShape.kind = 'stroke'; }};
      if (prop in store) return store[prop];
      return () => {{}};
    }},
    set(_t, prop, val) {{
      if (prop === 'fillStyle') styleLog.push(val);
      store[prop] = val;
      return true;
    }},
  }});
}}
globalThis.window = {{ devicePixelRatio: 1, addEventListener() {{}}, removeEventListener() {{}} }};
globalThis.document = {{
  createElement() {{ return {{ width: 0, height: 0, getContext: () => makeCtx([], [], []) }}; }},
}};

const fillLog = [];
const shapeLog = [];
const styleLog = [];
const ctx = makeCtx(fillLog, shapeLog, styleLog);
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
    // A genuine chord (3 strings, same onset, tagged with a chord label) at
    // a beat clear of any measure boundary, plus 19 more single-note groups
    // so there are enough upcoming groups to fill all 20 band cards.
    {{ string: 1, fret: 0, finger: 'open',  onset: 5.5,  duration: 0.5, pitch: 64, chord: 'Am' }},
    {{ string: 2, fret: 1, finger: 'index', onset: 5.5,  duration: 0.5, pitch: 61, chord: 'Am' }},
    {{ string: 3, fret: 2, finger: 'ring',  onset: 5.5,  duration: 0.5, pitch: 57, chord: 'Am' }},
    {{ string: 3, fret: 4, finger: 'index', onset: 6.5,  duration: 0.5, pitch: 59 }},
    {{ string: 4, fret: 3, finger: 'ring',  onset: 7.5,  duration: 0.5, pitch: 53 }},
    {{ string: 2, fret: 5, finger: 'pinky', onset: 8.5,  duration: 0.5, pitch: 65 }},
    {{ string: 5, fret: 2, finger: 'index', onset: 9.5,  duration: 0.5, pitch: 47 }},
    {{ string: 6, fret: 1, finger: 'index', onset: 10.5, duration: 0.5, pitch: 41 }},
    {{ string: 1, fret: 3, finger: 'ring',  onset: 11.5, duration: 0.5, pitch: 67 }},
    {{ string: 2, fret: 2, finger: 'middle',onset: 12.5, duration: 0.5, pitch: 62 }},
    {{ string: 3, fret: 1, finger: 'index', onset: 13.5, duration: 0.5, pitch: 56 }},
    {{ string: 4, fret: 2, finger: 'ring',  onset: 14.5, duration: 0.5, pitch: 55 }},
    {{ string: 5, fret: 3, finger: 'index', onset: 15.5, duration: 0.5, pitch: 48 }},
    {{ string: 6, fret: 2, finger: 'middle',onset: 16.5, duration: 0.5, pitch: 42 }},
    {{ string: 1, fret: 5, finger: 'pinky', onset: 17.5, duration: 0.5, pitch: 69 }},
    {{ string: 2, fret: 3, finger: 'ring',  onset: 18.5, duration: 0.5, pitch: 63 }},
    {{ string: 3, fret: 3, finger: 'ring',  onset: 19.5, duration: 0.5, pitch: 58 }},
    {{ string: 4, fret: 5, finger: 'pinky', onset: 20.5, duration: 0.5, pitch: 58 }},
    {{ string: 5, fret: 1, finger: 'index', onset: 21.5, duration: 0.5, pitch: 46 }},
    {{ string: 6, fret: 3, finger: 'ring',  onset: 22.5, duration: 0.5, pitch: 43 }},
    {{ string: 1, fret: 1, finger: 'index', onset: 23.5, duration: 0.5, pitch: 65 }},
    {{ string: 2, fret: 4, finger: 'ring',  onset: 24.5, duration: 0.5, pitch: 64 }},
  ],
}};
const r = new SlopeRenderer(canvas, data);

// Isolate the band's OWN draw calls (fillText + shapes), not the moving
// discs or permanent fretboard labels that can share the same coordinates —
// a naive y-region filter produces false positives against those.
const bandFills = [];
const bandShapes = [];
const bandStyles = [];
const origDraw = r._drawChordLookaheadBand.bind(r);
r._drawChordLookaheadBand = (...args) => {{
  const fillStart = fillLog.length;
  const shapeStart = shapeLog.length;
  const styleStart = styleLog.length;
  origDraw(...args);
  bandFills.push(...fillLog.slice(fillStart));
  bandShapes.push(...shapeLog.slice(shapeStart));
  bandStyles.push(...styleLog.slice(styleStart));
}};

function frame(beat) {{
  r.currentBeat = beat;
  fillLog.length = 0;
  shapeLog.length = 0;
  styleLog.length = 0;
  bandFills.length = 0;
  bandShapes.length = 0;
  bandStyles.length = 0;
  r.render();
  return {{
    allFills: fillLog.map((e) => e.txt),
    fills: bandFills.map((e) => ({{ txt: e.txt, x: e.x, y: e.y }})),
    shapes: bandShapes,
    triangleFillCount: bandStyles.filter((s) => s === '#ff3030').length,
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


def test_band_shows_twenty_groups() -> None:
    """The band must show 20 upcoming groups — one column of 6 discs/rings
    each, so 120 shapes total (20 cards x 6 strings)."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify({ shapeCount: f.shapes.length }));
""")
    assert out["shapeCount"] == 120, f"expected 20 cards x 6 strings = 120 shapes, got {out['shapeCount']}"


def test_p5_unplayed_strings_are_hollow_played_strings_are_filled() -> None:
    """The Am chord group (onset 5.5) plays strings 1-3 and leaves 4-6 muted:
    those three must be hollow rings (stroke, no fill), not filled discs."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.shapes));
""")
    kinds = [s["kind"] for s in out]
    filled = kinds.count("fill")
    hollow = kinds.count("stroke")
    assert filled == 22, f"22 notes are actually played across all 20 groups, got {filled} filled"
    assert hollow == 120 - 22, f"the rest must be hollow rings, got {hollow} hollow"


def test_band_draws_no_string_letter_next_to_the_disc() -> None:
    """Row position (row 0 = string 1) identifies the string now, not a
    letter next to the disc — removed so every freed pixel of column width
    goes to the disc/digit instead."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.fills.map((e) => e.txt)));
""")
    letters = [t for t in out if t in ("e", "B", "G", "D", "A", "E")]
    assert letters == [], f"the band must not draw string-letter labels, saw {letters}"


def test_moving_disc_drops_the_note_name_letter() -> None:
    """The band's own circles never had a letter (see the test above) — this
    covers the OTHER circles: the moving fret-discs gliding along the lane
    itself (_drawFretDisc). The reading band carries the note name; the
    moving disc shows only the fret digit, so the freed space goes to
    making that digit as big as possible."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.allFills));
""")
    letters = [t for t in out if t in ("A", "B", "C", "D", "E", "F", "G")]
    assert letters == [], f"moving discs must not draw the note-name letter, saw {letters}"


def test_band_played_string_shows_its_fret_digit() -> None:
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.fills.map((e) => e.txt)));
""")
    # The Am chord's frets (0, 1, 2) must appear as digit text.
    assert "0" in out and "1" in out and "2" in out


def test_band_draws_the_chord_triangle_once_not_per_note() -> None:
    """The Am group has 3 notes all tagged chord: 'Am' -> exactly ONE triangle
    for that card, not three. Single-note groups (no chord tag) get none, so
    across all 20 upcoming groups the triangle-red fillStyle must be set
    exactly once, not 3 times (once per Am note) or 20 times (once per card)."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify({ triangleFillCount: f.triangleFillCount }));
""")
    assert out["triangleFillCount"] == 1, (
        f"expected exactly 1 triangle (one chord group), got {out['triangleFillCount']}"
    )


def test_chord_triangle_count_matches_chorded_groups() -> None:
    """Direct structural check: exactly 1 of the 20 upcoming groups is a chord
    (the Am at onset 5.5); confirm _upcomingNotes/group.notes reflects that,
    which is what _drawChordLookaheadBand's triangle condition reads."""
    out = _run("""
r.currentBeat = 1.0;
const groups = r._upcomingNotes(20);
const chordedGroups = groups.filter((g) => g.notes.some((n) => n.chord)).length;
console.log(JSON.stringify({ groupCount: groups.length, chordedGroups }));
""")
    assert out["groupCount"] == 20
    assert out["chordedGroups"] == 1, "only the Am group (3 notes, same onset) should be tagged"


def test_band_circle_radius_stays_bounded_and_legible() -> None:
    """20 narrow columns genuinely can't reach a big-disc radius on most
    screens — an honest space trade-off, not a bug, since cardW/2-2 caps it
    (see _drawChordLookaheadBand). What must hold: the radius never exceeds
    its own 21px target ceiling, and it doesn't collapse to an illegible
    speck on a reasonably-sized canvas."""
    out = _run("""
const f = frame(1.0);
const shapeRadii = f.shapes.map((s) => s.radius).filter((r2) => r2 > 0);
console.log(JSON.stringify({ shapeRadii }));
""")
    for r_val in out["shapeRadii"]:
        assert r_val <= 21.5, f"radius {r_val} must not exceed the 21px target ceiling"
    assert min(out["shapeRadii"]) >= 6, (
        f"radius {min(out['shapeRadii'])} is too small to read even on a 1400px-wide canvas"
    )


def test_band_cards_do_not_overlap_horizontally() -> None:
    """Collision avoidance at the card level: 20 columns must be strictly
    ordered left-to-right, each column's circle radius small enough
    (clamped to cardW/2-2, see _drawChordLookaheadBand) that adjacent
    discs can't touch even when 20 narrow columns are squeezed together.
    Uses the real production canvas size (968x816) where the columns
    actually squeeze narrow enough for the cardW clamp — not the rowH
    clamp — to be the binding constraint."""
    out = _run(
        """
const f = frame(1.0);
// Group shape x's into 20 clusters (cards) by rounding — each card's 6
// circles share the same cx.
const xs = [...new Set(f.shapes.map((s) => Math.round(s.x)))].sort((a, b) => a - b);
const maxRadius = Math.max(...f.shapes.map((s) => s.radius));
console.log(JSON.stringify({ xs, maxRadius }));
""",
        width=968,
        height=816,
    )
    xs = out["xs"]
    assert len(xs) == 20, f"expected 20 distinct card columns, got {len(xs)}"
    for i in range(1, len(xs)):
        gap = xs[i] - xs[i - 1]
        assert gap > 0, "cards must be strictly left-to-right, no two sharing a column"
        assert gap >= out["maxRadius"] * 2, (
            f"column pitch {gap} must clear the disc diameter {out['maxRadius'] * 2} "
            "or adjacent discs would overlap"
        )


def test_band_no_two_shapes_share_a_row_within_a_card() -> None:
    """Collision avoidance at the row level: within one card (fixed cx), the
    6 string rows must have 6 distinct y positions - fixed grid, no overlap."""
    out = _run("""
const f = frame(1.0);
console.log(JSON.stringify(f.shapes));
""")
    by_x: dict[float, set] = {}
    for s in out:
        by_x.setdefault(round(s["x"]), set()).add(round(s["y"]))
    for x, ys in by_x.items():
        assert len(ys) == 6, f"card at x={x} must have 6 distinct row y's, got {len(ys)}"
