"""Guard tests for the Slope view's text-sharpness fix (S-1/S-2/S-3, T-P3).

The Slope renderer draws text (fret digits, chord labels) that glides
continuously with playback. Sub-pixel positions and non-integer font
sizes read as "blur" while moving, even though the canvas itself is high-DPI.
These guards assert the fix's mechanics are present in the shipped source —
there is no headless WebGL/canvas here, so behavior is verified by presence
of the snapping helpers and their use at the actual draw call sites (mirrors
the other test_web_*.py smoke tests in this suite).
"""
from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_SLOPE_JS = _STATIC_DIR / "js" / "slope-renderer.js"


def _slope_js() -> str:
    return _SLOPE_JS.read_text(encoding="utf-8")


def test_slope_backing_store_matches_client_size_times_dpr() -> None:
    """resize() sizes the canvas backing store from clientWidth/Height * dpr, and
    pins the CSS box to that same size (see test_web_slope_text_sharpness.py's
    behavioral test_css_box_is_pinned_to_the_exact_backing_store_size for why
    the pin matters — a bare `width:100%` box can drift from the backing store
    and get resampled by the browser, blurring text)."""
    js = _slope_js()
    assert "const bw = Math.max(1, Math.floor(rect.width * this.dpr));" in js
    assert "const bh = Math.max(1, Math.floor(rect.height * this.dpr));" in js
    assert "this.canvas.width = bw;" in js
    assert "this.canvas.height = bh;" in js
    assert "this.canvas.style.width = `${bw / this.dpr}px`;" in js
    assert "this.canvas.style.height = `${bh / this.dpr}px`;" in js
    assert "this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);" in js


def test_slope_canvas_has_no_css_transform_scale() -> None:
    """A CSS transform:scale on the canvas would resample already-sharp pixels."""
    css = (_STATIC_DIR / "css" / "style.css").read_text(encoding="utf-8")
    start = css.index("#slope-canvas {")
    end = css.index("}", start)
    rule = css[start:end]
    assert "transform" not in rule


def test_slope_text_snapping_helpers_present() -> None:
    """T-P3.1/T-P3.2: device-pixel position snap + integer font-size floor.

    (Behavioral coverage of the actual legibility numbers — the real point of
    this mechanism — lives in test_web_slope_text_sharpness.py; this is just a
    presence guard for the helpers themselves.)"""
    js = _slope_js()
    assert "_snapPx(v)" in js
    assert "_snapFontSizeClamped(cssSize, floorDevicePx)" in js


def test_fret_disc_uses_snapped_positions_and_dpr_scaled_floors() -> None:
    """_drawFretDisc (the moving fret-number label) must use the snap helpers,
    not raw fillText(point.x, point.y) with an unclamped font size — and the
    floor must scale with dpr (Math.round(N * dpr)), not a bare device-px
    constant, which used to vanish the label entirely on a 1x display
    (see test_fret_digit_is_never_dropped_on_a_1x_display in
    test_web_slope_text_sharpness.py)."""
    js = _slope_js()
    disc_start = js.index("_drawFretDisc(ctx, note, point, radius, meta, showText = true) {")
    disc_end = js.index("\n  }", disc_start)
    body = js[disc_start:disc_end]
    assert "this._snapPx(point.x)" in body
    assert "this._snapFontSizeClamped(fretSizeRaw, Math.round(13 * dpr))" in body
    # Fret digit is never optional — it must always be drawn.
    assert "ctx.fillText(String(note.fret)" in body
    # The note-name letter was removed entirely (the reading band carries it) —
    # no leftover conditional branch for it.
    assert "noteName" not in body


def test_chord_label_uses_snapped_position() -> None:
    """The chord label glides with the fold geometry like the note bars do."""
    js = _slope_js()
    label_start = js.index("_drawChordLabel(chord) {")
    label_end = js.index("\n  }", label_start)
    body = js[label_start:label_end]
    assert "ctx.fillText(chord.label, this._snapPx(x), this._snapPx(y));" in body
