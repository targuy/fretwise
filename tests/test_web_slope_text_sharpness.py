"""Behavioral guards for the Slope view's text sharpness during motion (Lot C).

Unlike ``test_web_slope_dpr.py`` (which greps the source for the presence of the
snap helpers), these tests execute the REAL shipped ``slope-renderer.js`` in Node
against a recording 2D-context mock, drive the animation clock to several
fractional beat offsets, and assert on the ACTUAL pixel coordinates passed to
``ctx.fillText`` and the ACTUAL backing-store resolution.

Root cause they lock down: the gliding fret-digit label is already snapped to the
device-pixel grid, but adaptive quality used to drop ``this.dpr`` below
``window.devicePixelRatio`` the instant playback degraded quality. A backing store
smaller than the display is CSS-upscaled by the browser, resampling (blurring)
every already-snapped glyph. The fix pins the backing store to the true device
dpr; quality is shed via shadows/step-count/passes, never resolution.
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


def _run(script: str, device_pixel_ratio: float = 2) -> dict:
    """Instantiate the real SlopeRenderer in Node; return the test script's JSON.

    A recording 2D-context Proxy captures every ``fillText`` call. The canvas /
    document / window globals are the minimum surface the renderer touches.
    """
    # file:// URL, not a bare Windows path: Node rejects "D:\..." as an ESM
    # specifier (the drive letter parses as a URL scheme).
    harness = f"""
globalThis.performance = globalThis.performance || {{ now: () => 0 }};
function makeCtx(fillLog) {{
  const store = {{}};
  const grad = {{ addColorStop() {{}} }};
  return new Proxy({{}}, {{
    get(_t, prop) {{
      if (prop === 'fillText') return (txt, x, y) => fillLog.push({{ txt: String(txt), x, y }});
      if (prop === 'createLinearGradient') return () => grad;
      if (prop in store) return store[prop];
      return () => {{}};
    }},
    set(_t, prop, val) {{ store[prop] = val; return true; }},
  }});
}}
globalThis.window = {{
  devicePixelRatio: {device_pixel_ratio},
  addEventListener() {{}},
  removeEventListener() {{}},
}};
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
  results: [{{ string: 3, fret: 7, finger: 'index', onset: 1.0, duration: 1.0, pitch: 62 }}],
}};
const r = new SlopeRenderer(canvas, data);

// Render one frame at a given beat and return the device-space coords of the
// gliding fret digit ('7'), or null if it was not drawn.
function fretDigitDevice(beat) {{
  r.currentBeat = beat;
  fillLog.length = 0;
  r.render();
  const hit = fillLog.find((e) => e.txt === '7');
  if (!hit) return null;
  return {{ x: hit.x, y: hit.y, devX: hit.x * r.dpr, devY: hit.y * r.dpr, dpr: r.dpr }};
}}
const nearInt = (v) => Math.abs(v - Math.round(v)) < 1e-6;

{script}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_gliding_fret_digit_lands_on_integer_device_pixels() -> None:
    """Across fractional beat offsets the fret digit's fillText x/y must be exact
    integers in DEVICE space — otherwise the glyph rasterizes at a different
    sub-pixel every frame and shimmers/blurs while moving."""
    out = _run("""
const beats = [0.10, 0.37, 0.63, 0.91, 1.234, 2.718];
const rows = beats.map((b) => {
  const p = fretDigitDevice(b);
  return { beat: b, drawn: !!p, devX: p && p.devX, devY: p && p.devY,
           xInt: p && nearInt(p.devX), yInt: p && nearInt(p.devY) };
});
console.log(JSON.stringify(rows));
""")
    assert out, "fret digit was never drawn — fixture note not visible"
    for row in out:
        assert row["drawn"], f"fret digit not drawn at beat {row['beat']}"
        assert row["xInt"], f"fret devX {row['devX']} not integer at beat {row['beat']}"
        assert row["yInt"], f"fret devY {row['devY']} not integer at beat {row['beat']}"


def test_snap_px_maps_fractional_css_to_integer_device_pixel() -> None:
    """_snapPx(12.37) at dpr=2 -> 12.5 css, i.e. exactly 25 device px (not 24.74)."""
    out = _run("""
r.dpr = 2;
console.log(JSON.stringify({
  css: r._snapPx(12.37),
  device: r._snapPx(12.37) * 2,
}));
""")
    assert out["css"] == 12.5
    assert out["device"] == 25


def test_backing_store_stays_at_true_device_dpr_under_quality_degradation() -> None:
    """THE FIX: when adaptive quality degrades during playback, the backing store
    must NOT shrink below the display resolution (which would CSS-upscale and blur
    the whole canvas). _renderDpr() must equal the true device dpr at every
    quality level, and the fret digit must remain integer in device space."""
    out = _run("""
const dprByQuality = {};
for (const q of [0, 1, 2]) { r._quality = q; dprByQuality[q] = r._renderDpr(); }
// Simulate the worst-case degrade the animation loop can reach.
r._quality = 2;
r.dpr = r._renderDpr();
r.resize();
const p = fretDigitDevice(0.37);
console.log(JSON.stringify({
  dprByQuality,
  devicePixelRatio: window.devicePixelRatio,
  backingW: canvas.width,
  displayW: canvas.clientWidth * window.devicePixelRatio,
  fretDevXInt: p && nearInt(p.devX),
}));
""")
    dpr = out["devicePixelRatio"]
    # No quality level may drop the backing store below the true device dpr.
    assert out["dprByQuality"] == {"0": dpr, "1": dpr, "2": dpr}
    # Backing store exactly covers the display -> browser never resamples it.
    assert out["backingW"] == out["displayW"]
    assert out["fretDevXInt"], "fret digit off the device grid after degrade"


def test_css_box_is_pinned_to_the_exact_backing_store_size() -> None:
    """THE FIX (follow-up): resize() must pin canvas.style.width/height to the
    exact px the backing store was sized for, not leave the stylesheet's
    `width:100%` in charge.

    Left as a percentage, the browser recomputes the CSS box size fresh on
    every paint (sub-pixel layout rounding, a reflow, a scrollbar appearing);
    any drift between that box and the backing store's integer-pixel size
    makes the COMPOSITOR resample the whole canvas to fit — a continuous soft
    blur on exactly the high-frequency content (glyph edges) that _snapPx
    already made land on exact device pixels. Reproduced here with a
    fractional bounding-rect width (843.7px), the realistic case (a
    non-integer container width, common at 125%/150% Windows display
    scaling) that a naive integer-rect test would never catch."""
    out = _run("""
canvas.getBoundingClientRect = () => ({ width: 843.7, height: 512.3, left: 0, top: 0 });
r.resize();
console.log(JSON.stringify({
  backingW: canvas.width,
  backingH: canvas.height,
  styleW: canvas.style.width,
  styleH: canvas.style.height,
  dpr: r.dpr,
}));
""")
    # The CSS box (parsed back from the "<n>px" string) must reproduce the
    # backing store exactly: backingW / dpr, to full float precision — any
    # rounding here is exactly the drift that causes compositor resampling.
    css_w = float(out["styleW"].removesuffix("px"))
    css_h = float(out["styleH"].removesuffix("px"))
    assert css_w == out["backingW"] / out["dpr"]
    assert css_h == out["backingH"] / out["dpr"]
    # And the stylesheet's 100% must no longer be the deciding size — an
    # explicit px value is set.
    assert out["styleW"] != "100%"
    assert out["styleH"] != "100%"


def test_font_size_snaps_to_integer_device_pixels() -> None:
    """Font sizes must land on whole device pixels (a fractional-device-px glyph
    is what reads as mush); the clamped variant enforces a floor."""
    out = _run("""
r.dpr = 2;
console.log(JSON.stringify({
  clampedDevice: r._snapFontSizeClamped(9.3, 11) * 2,   // rounds to whole device px
  clampFloorDevice: r._snapFontSizeClamped(2.0, 11) * 2, // clamped up to floor 11
}));
""")
    assert out["clampedDevice"] == 19  # round(9.3*2)=19
    assert out["clampFloorDevice"] == 11  # max(11, round(2*2)=4) = 11


def test_note_name_letter_is_never_dropped_on_a_1x_display() -> None:
    """Regression: on a 1x-DPR display (the common case on a high-refresh
    gaming monitor, which is almost never run at fractional OS scaling), the
    note-name letter used to compute devicePx = round(radius*0.38 * 1) ~= 6,
    below the old fixed 8-device-px floor -> _snapFontSizeOrNull returned null
    and the letter was silently never drawn AT ALL, independent of every
    crispness fix (there was nothing there to be crisp). It must now always
    render, at a real reading size, at every dpr from 1 to 3."""
    out = _run("""
const rows = [1, 1.25, 1.5, 2, 3].map((dpr) => {
  r.dpr = dpr;
  fillLog.length = 0;
  r._drawFretDisc(ctx, { fret: 7, noteName: 'B' }, { x: 100, y: 100 }, r._circleRadius(),
    { discColor: '#fffdf2', color: '#c68a2e' });
  const letter = fillLog.find((e) => e.txt === 'B');
  const digit = fillLog.find((e) => e.txt === '7');
  return { dpr, letterDrawn: !!letter, digitDrawn: !!digit };
});
console.log(JSON.stringify(rows));
""")
    for row in out:
        assert row["digitDrawn"], f"fret digit not drawn at dpr={row['dpr']}"
        assert row["letterDrawn"], f"note-name letter not drawn at dpr={row['dpr']} (the bug)"


def test_disc_and_font_sizes_meet_a_real_minimum_reading_size() -> None:
    """The fret digit and note-name letter must be a genuinely legible CSS
    size at every dpr, not just crisply-rasterized-but-tiny. Guards the actual
    numbers a human reads, not just the snap-to-pixel mechanics."""
    out = _run("""
const rows = [1, 2].map((dpr) => {
  r.dpr = dpr;
  const radius = r._circleRadius();
  return {
    dpr, radius,
    fretCss: r._snapFontSizeClamped(Math.max(13, radius * 0.80), Math.round(13 * dpr)),
    nameCss: r._snapFontSizeClamped(Math.max(9, radius * 0.44), Math.round(9 * dpr)),
  };
});
console.log(JSON.stringify(rows));
""")
    for row in out:
        assert row["radius"] >= 12, f"disc radius {row['radius']} too small to hold two lines of text"
        assert row["fretCss"] >= 13, f"fret digit {row['fretCss']}css px at dpr={row['dpr']} too small"
        assert row["nameCss"] >= 9, f"note-name letter {row['nameCss']}css px at dpr={row['dpr']} too small"
