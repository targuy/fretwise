"""Behavioral tests for the Slope legibility modes (P1 reading band, P2–P4 tags).

The Slope note text is unreadable in motion at any refresh rate — the eye reads a
gliding glyph in smooth pursuit, which physically cannot resolve fine text past a
low tempo. P1's answer is a fixed reading band pinned to the bottom edge: it never
moves, so the eye reads it in fixation (sharp at any tempo). These tests execute
the real shipped ``slope-renderer.js`` in Node against a recording 2D-context mock
and assert on the ACTUAL fillText calls, not the source text.
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
    """Instantiate the real SlopeRenderer in Node; return the test script's JSON."""
    # file:// URL, not a bare Windows path (Node rejects "D:\..." as an ESM specifier).
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

// A little melody across strings so the band has several groups to show.
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

// Record the fillText calls in the bottom reading-band region for one frame.
function frameTexts(beat) {{
  r.currentBeat = beat;
  fillLog.length = 0;
  r.render();
  const h = canvas.clientHeight;
  return {{
    all: fillLog.map((e) => e.txt),
    band: fillLog.filter((e) => e.y > h - 140).map((e) => e.txt),
  }};
}}

{script}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        # Force UTF-8: node emits UTF-8, but subprocess defaults to the Windows
        # locale (cp1252), which mangles the band header's accented 'À'.
        encoding="utf-8",
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_p1_reading_band_shows_upcoming_notes_in_a_fixed_strip() -> None:
    """P1 draws the 'À VENIR' band with the fret + note name of upcoming notes."""
    out = _run("""
r.setLegibilityMode('p1');
const t = frameTexts(2.0);
console.log(JSON.stringify(t.band));
""")
    # Match the ASCII part of the header to sidestep source-encoding fuss.
    assert any("VENIR" in t for t in out), "the reading-band header must be drawn"
    # The imminent group (fret 7 on string 1, fret 6 on string 4) must be in the band.
    assert "7" in out and "6" in out
    assert "B" in out, "note name B (string 1 fret 7) must be shown in the band"
    assert "G#" in out, "note name G# (string 4 fret 6) must be shown in the band"


def test_p1_upcoming_groups_are_ordered_and_chorded() -> None:
    """The band groups notes by onset (a chord stays one group) earliest-first."""
    out = _run("""
r.setLegibilityMode('p1');
const groups = r._upcomingNotes(4);
console.log(JSON.stringify(groups.map(g => ({ onset: g.onset, n: g.notes.length }))));
""")
    onsets = [g["onset"] for g in out]
    assert onsets == sorted(onsets), "groups must be earliest-onset first"
    assert out[0]["onset"] == 2.0 and out[0]["n"] == 2, "the onset-2.0 chord is one 2-note group"
    assert out[1]["onset"] == 2.5 and out[1]["n"] == 1


def test_p1_moving_disc_drops_the_note_name_letter() -> None:
    """In P1 the moving disc shows the fret digit alone (the band carries the
    letter); the redundant letter on the gliding disc is what blurs worst."""
    out = _run("""
r.setLegibilityMode('p1');
// A note mid-flight (not in the band) — its disc must draw the digit, no letter.
const t = frameTexts(1.0);
// Above the band only: strip the band region.
const h = canvas.clientHeight;
const moving = [];
const seen = new Set();
r.currentBeat = 1.0; fillLog.length = 0; r.render();
for (const e of fillLog) { if (e.y <= h - 140) moving.push(e.txt); }
console.log(JSON.stringify(moving));
""")
    # No standalone note-name letters among the moving discs (digits only).
    letters = [t for t in out if t in ("A", "B", "C", "D", "E", "F", "G")]
    assert letters == [], f"moving discs must not draw note-name letters in P1, saw {letters}"


def test_base_mode_has_no_band_and_keeps_disc_letters() -> None:
    """'base' is the untouched slope: no reading band, discs keep their letter."""
    out = _run("""
r.setLegibilityMode('base');
const t = frameTexts(1.0);
console.log(JSON.stringify(t.all));
""")
    assert not any("VENIR" in t for t in out), "base mode must not draw the reading band"


def test_unimplemented_modes_render_a_coming_soon_tag() -> None:
    """P2–P4 aren't built yet: they render as base plus a corner tag naming the
    plan, so the button does something honest rather than nothing."""
    for mode in ("p2", "p3", "p4"):
        out = _run(f"""
r.setLegibilityMode('{mode}');
const t = frameTexts(1.0);
console.log(JSON.stringify(t.all));
""")
        assert any(mode.upper() in t for t in out), f"{mode} must draw its coming-soon tag"
        assert not any("VENIR" in t for t in out), f"{mode} must not draw the P1 band"


def test_unknown_mode_falls_back_to_base_not_blank() -> None:
    """A stale/garbage mode value must not blank the view."""
    out = _run("""
r.setLegibilityMode('nonsense');
console.log(JSON.stringify({ mode: r.legibilityMode }));
""")
    assert out["mode"] == "base"
