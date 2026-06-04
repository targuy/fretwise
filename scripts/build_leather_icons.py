#!/usr/bin/env python
"""Build FretWise's knob/wood UI artwork from the two source pictures.

Inputs (placed by the designer):
  * web/static/img/BACKGROUND.png   — flamed-maple sunburst strip (wide, short)
  * web/static/img/icons/ICON.png   — metallic volume-knob "model" (white bg)

Outputs:
  * BACKGROUND.png        — mirror-tiled into a page-friendly canvas (the side
                            burst bands extend down the page, no blurry upscale).
                            Original strip kept as BACKGROUND_STRIP.png.
  * icons/_knob_base.png  — knob with white background flood-removed (transparent).
  * icons/_disc_base.png  — clean brushed-metal disc (VOLUME/1-10 ring cropped off).
  * icons/<name>.png + <name>@2x.png  — one transparent icon per manifest entry:
                            a bold engraved feature glyph on the disc (ornate knob
                            for the big transport controls).
  * icons/_contact.png    — every icon at its real button size + a zoom, for review.

Run:  pixi run python scripts/build_leather_icons.py
"""

from __future__ import annotations

import json
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "src" / "fretwise" / "web" / "static" / "img"
ICONS = IMG / "icons"
MASTER = 256                      # working master resolution per icon
INK = (26, 18, 10, 255)          # warm near-black engraving colour
ORNATE = {"play-pause", "jump-figure"}  # keep the full VOLUME knob for these
_FONT_PATH = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"


def _font(px: int) -> ImageFont.FreeTypeFont:
    try:
        return ImageFont.truetype(_FONT_PATH, px)
    except OSError:  # pragma: no cover - non-mac fallback
        return ImageFont.load_default()


# ---------------------------------------------------------------------------
# Background
# ---------------------------------------------------------------------------

def build_background(target_w: int = 1416, aspect: float = 0.62) -> None:
    src = Image.open(IMG / "BACKGROUND.png").convert("RGB")
    strip = IMG / "BACKGROUND_STRIP.png"
    if not strip.exists():
        src.save(strip)
    else:  # rebuild from the pristine strip so re-runs are idempotent
        src = Image.open(strip).convert("RGB")
    w, h = src.size
    if target_w != w:
        src = src.resize((target_w, round(h * target_w / w)), Image.LANCZOS)
        w, h = src.size
    target_h = round(target_w * aspect)
    flipped = src.transpose(Image.FLIP_TOP_BOTTOM)
    canvas = Image.new("RGB", (w, target_h))
    y, flip = 0, False
    while y < target_h:
        canvas.paste(flipped if flip else src, (0, y))
        y += h
        flip = not flip
    canvas.save(IMG / "BACKGROUND.png")
    print(f"BACKGROUND.png  -> {canvas.size}")


# ---------------------------------------------------------------------------
# Knob bases
# ---------------------------------------------------------------------------

def build_knob_base(size: int = MASTER) -> Image.Image:
    im = Image.open(ICONS / "ICON.png").convert("RGB")
    w, h = im.size
    sentinel = (255, 0, 255)
    for seed in [(0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1)]:
        ImageDraw.floodfill(im, seed, sentinel, thresh=42)
    rgba = im.convert("RGBA")
    rgba.putdata([
        (r, g, b, 0) if (r, g, b) == sentinel else (r, g, b, 255)
        for (r, g, b, _a) in rgba.getdata()
    ])
    bbox = rgba.getbbox()
    if bbox:
        rgba = rgba.crop(bbox)
    side = max(rgba.size)
    sq = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    sq.paste(rgba, ((side - rgba.width) // 2, (side - rgba.height) // 2))
    knob = sq.resize((size, size), Image.LANCZOS)
    knob.save(ICONS / "_knob_base.png")
    return knob


def build_clean_disc(knob: Image.Image, inner: float = 0.72) -> Image.Image:
    """Crop the engraved VOLUME/1-10 bezel away, leaving a brushed-metal disc."""
    s = knob.size[0]
    c = s / 2
    r = c * inner
    mask = Image.new("L", knob.size, 0)
    ImageDraw.Draw(mask).ellipse([c - r, c - r, c + r, c + r], fill=255)
    disc = Image.new("RGBA", knob.size, (0, 0, 0, 0))
    disc.paste(knob, (0, 0), mask)
    d = ImageDraw.Draw(disc)
    # dark rim + inner highlight for a clean machined edge
    d.ellipse([c - r, c - r, c + r, c + r], outline=(48, 42, 36, 255),
              width=max(2, int(s * 0.022)))
    d.ellipse([c - r * 0.93, c - r * 0.93, c + r * 0.93, c + r * 0.93],
              outline=(255, 255, 255, 55), width=max(1, int(s * 0.008)))
    disc.save(ICONS / "_disc_base.png")
    return disc


# ---------------------------------------------------------------------------
# Glyph primitives
# ---------------------------------------------------------------------------

def _W(r: float, k: float = 0.24) -> int:
    return max(3, int(r * k))


def _arrow(d, x0, y0, x1, y1, r):  # shafted arrow tip at (x1,y1)
    w = _W(r)
    d.line([(x0, y0), (x1, y1)], fill=INK, width=w)
    ang = math.atan2(y1 - y0, x1 - x0)
    hl = r * 0.55
    for s in (+1, -1):
        a = ang + math.pi - s * math.radians(32)
        d.line([(x1, y1), (x1 + hl * math.cos(a), y1 + hl * math.sin(a))],
               fill=INK, width=w)


def _tri(d, cx, cy, r, direction=1):  # play / chevron triangle
    d.polygon([(cx - direction * r * 0.55, cy - r * 0.8),
               (cx - direction * r * 0.55, cy + r * 0.8),
               (cx + direction * r * 0.85, cy)], fill=INK)


def _text(d, s, cx, cy, r, scale=1.5):
    f = _font(int(r * scale))
    d.text((cx, cy), s, font=f, fill=INK, anchor="mm")


def _chevron(d, cx, cy, r, direction=1):
    w = _W(r, 0.26)
    d.line([(cx + direction * r * 0.3, cy - r * 0.7), (cx - direction * r * 0.4, cy),
            (cx + direction * r * 0.3, cy + r * 0.7)], fill=INK, width=w, joint="curve")


def _ring_teeth(d, cx, cy, r):  # gear
    w = _W(r, 0.22)
    d.ellipse([cx - r * 0.55, cy - r * 0.55, cx + r * 0.55, cy + r * 0.55],
              outline=INK, width=w)
    for i in range(8):
        a = i * math.pi / 4
        x0, y0 = cx + r * 0.55 * math.cos(a), cy + r * 0.55 * math.sin(a)
        x1, y1 = cx + r * 0.92 * math.cos(a), cy + r * 0.92 * math.sin(a)
        d.line([(x0, y0), (x1, y1)], fill=INK, width=int(w * 1.7))
    d.ellipse([cx - r * 0.2, cy - r * 0.2, cx + r * 0.2, cy + r * 0.2],
              outline=INK, width=w)


def _doc(d, cx, cy, r, label=""):
    d.rounded_rectangle([cx - r * 0.6, cy - r * 0.82, cx + r * 0.6, cy + r * 0.82],
                        radius=r * 0.12, outline=INK, width=_W(r, 0.16))
    if label:
        _text(d, label, cx, cy + r * 0.05, r, scale=0.95 if len(label) > 2 else 1.2)
    else:
        for k in (-0.35, -0.05, 0.25):
            d.line([(cx - r * 0.32, cy + r * k), (cx + r * 0.32, cy + r * k)],
                   fill=INK, width=_W(r, 0.11))


def _refresh(d, cx, cy, r):  # circular arrows
    w = _W(r, 0.2)
    bb = [cx - r * 0.7, cy - r * 0.7, cx + r * 0.7, cy + r * 0.7]
    d.arc(bb, start=40, end=300, fill=INK, width=w)
    a = math.radians(40)
    tx, ty = cx + r * 0.7 * math.cos(a), cy + r * 0.7 * math.sin(a)
    _arrow(d, tx - r * 0.3, ty - r * 0.3, tx + r * 0.05, ty + r * 0.2, r * 0.7)


def _hand(d, cx, cy, r):  # 4 fingers + thumb
    w = _W(r, 0.34)
    base = cy + r * 0.7
    for i, hx in enumerate((-0.42, -0.14, 0.14, 0.42)):
        top = cy - r * (0.7 if i in (1, 2) else 0.45)
        d.line([(cx + r * hx, base), (cx + r * hx, top)], fill=INK, width=w)
        d.ellipse([cx + r * hx - w / 2, top - w / 2, cx + r * hx + w / 2, top + w / 2],
                  fill=INK)
    d.line([(cx - r * 0.42, base), (cx - r * 0.8, cy + r * 0.1)], fill=INK, width=w)


def _target(d, cx, cy, r):
    w = _W(r, 0.18)
    d.ellipse([cx - r * 0.75, cy - r * 0.75, cx + r * 0.75, cy + r * 0.75],
              outline=INK, width=w)
    d.ellipse([cx - r * 0.18, cy - r * 0.18, cx + r * 0.18, cy + r * 0.18], fill=INK)
    for a in (0, 90, 180, 270):
        rad = math.radians(a)
        d.line([(cx + r * 0.6 * math.cos(rad), cy + r * 0.6 * math.sin(rad)),
                (cx + r * 0.95 * math.cos(rad), cy + r * 0.95 * math.sin(rad))],
               fill=INK, width=w)


def _note(d, cx, cy, r):  # eighth note
    d.ellipse([cx - r * 0.55, cy + r * 0.25, cx - r * 0.05, cy + r * 0.7], fill=INK)
    d.line([(cx - r * 0.07, cy + r * 0.5), (cx - r * 0.07, cy - r * 0.75)],
           fill=INK, width=_W(r, 0.16))
    d.line([(cx - r * 0.07, cy - r * 0.75), (cx + r * 0.45, cy - r * 0.45)],
           fill=INK, width=_W(r, 0.2))


def _cloud(d, cx, cy, r, slash=False):
    d.ellipse([cx - r * 0.7, cy - r * 0.1, cx - r * 0.1, cy + r * 0.5], outline=INK,
              width=_W(r, 0.16))
    d.ellipse([cx - r * 0.3, cy - r * 0.45, cx + r * 0.35, cy + r * 0.3], outline=INK,
              width=_W(r, 0.16))
    d.ellipse([cx + r * 0.05, cy - r * 0.1, cx + r * 0.65, cy + r * 0.5], outline=INK,
              width=_W(r, 0.16))
    d.rectangle([cx - r * 0.55, cy + r * 0.32, cx + r * 0.55, cy + r * 0.55], fill=INK)
    if slash:
        d.line([(cx - r * 0.8, cy + r * 0.8), (cx + r * 0.8, cy - r * 0.8)],
               fill=INK, width=_W(r, 0.18))


def _grid(d, cx, cy, r):  # chord diagram
    w = _W(r, 0.12)
    for i in range(4):
        x = cx - r * 0.6 + i * r * 0.4
        d.line([(x, cy - r * 0.7), (x, cy + r * 0.7)], fill=INK, width=w)
    for j in range(4):
        y = cy - r * 0.7 + j * r * 0.46
        d.line([(cx - r * 0.6, y), (cx + r * 0.6, y)], fill=INK, width=w)
    d.ellipse([cx - r * 0.32, cy - r * 0.05, cx - r * 0.08, cy + r * 0.19], fill=INK)
    d.ellipse([cx + r * 0.18, cy + r * 0.18, cx + r * 0.42, cy + r * 0.42], fill=INK)


# ---------------------------------------------------------------------------
# Glyph dispatch — one entry per manifest icon name.
# ---------------------------------------------------------------------------

GLYPHS = {
    "play-pause":        lambda d, c, r: _tri(d, c, c, r),
    "jump-figure":       lambda d, c, r: _target(d, c, c, r),
    "follow":            lambda d, c, r: _target(d, c, c, r * 0.9),
    "prev":              lambda d, c, r: (_tri(d, c - r * 0.35, c, r * 0.75, -1),
                                          _tri(d, c + r * 0.4, c, r * 0.75, -1)),
    "next":              lambda d, c, r: (_tri(d, c - r * 0.4, c, r * 0.75, 1),
                                          _tri(d, c + r * 0.35, c, r * 0.75, 1)),
    "chevron-left":      lambda d, c, r: _chevron(d, c, c, r, -1),
    "chevron-right":     lambda d, c, r: _chevron(d, c, c, r, 1),
    "loop-a":            lambda d, c, r: _text(d, "A", c, c, r),
    "loop-b":            lambda d, c, r: _text(d, "B", c, c, r),
    "loop-clear":        lambda d, c, r: _refresh(d, c, c, r),
    "resync":            lambda d, c, r: _refresh(d, c, c, r),
    "metronome":         lambda d, c, r: _metronome(d, c, c, r),
    "setmute":           lambda d, c, r: _text(d, "M", c, c, r),
    "back":              lambda d, c, r: _arrow(d, c + r * 0.7, c, c - r * 0.7, c, r),
    "logout":            lambda d, c, r: _logout(d, c, c, r),
    "settings":          lambda d, c, r: _ring_teeth(d, c, c, r),
    "theme-picker":      lambda d, c, r: _palette(d, c, c, r),
    "export-pdf":        lambda d, c, r: _doc(d, c, c, r),
    "export-gp":         lambda d, c, r: _doc(d, c, c, r, "GP"),
    "export-musicxml":   lambda d, c, r: _doc(d, c, c, r, "XML"),
    "download-gp":       lambda d, c, r: _download(d, c, c, r),
    "metadata-menu":     lambda d, c, r: _list_caret(d, c, c, r),
    "search":            lambda d, c, r: _search(d, c, c, r),
    "upload":            lambda d, c, r: _upload(d, c, c, r),
    "fingering-diagram": lambda d, c, r: _hand(d, c, c, r),
    "hand-viz":          lambda d, c, r: _hand(d, c, c, r),
    "fretboard":         lambda d, c, r: _fretboard(d, c, c, r),
    "legend":            lambda d, c, r: _book(d, c, c, r),
    "audit-toggle":      lambda d, c, r: _info(d, c, c, r),
    "chords-toggle":     lambda d, c, r: _grid(d, c, c, r),
    "popout":            lambda d, c, r: _popout(d, c, c, r),
    "close":             lambda d, c, r: _close(d, c, c, r),
    "cloud-icons":       lambda d, c, r: _note(d, c, c, r),
    "google-drive":      lambda d, c, r: _drive(d, c, c, r),
    "cloud-connect":     lambda d, c, r: _cloud(d, c, c, r, slash=True),
}


def _metronome(d, cx, cy, r):
    d.polygon([(cx - r * 0.7, cy + r * 0.8), (cx + r * 0.7, cy + r * 0.8),
               (cx + r * 0.32, cy - r * 0.8), (cx - r * 0.32, cy - r * 0.8)],
              outline=INK, width=_W(r, 0.16))
    d.line([(cx, cy + r * 0.55), (cx + r * 0.42, cy - r * 0.5)], fill=INK, width=_W(r, 0.16))


def _logout(d, cx, cy, r):
    w = _W(r, 0.18)
    d.line([(cx - r * 0.2, cy - r * 0.8), (cx - r * 0.8, cy - r * 0.8),
            (cx - r * 0.8, cy + r * 0.8), (cx - r * 0.2, cy + r * 0.8)],
           fill=INK, width=w, joint="curve")
    _arrow(d, cx - r * 0.1, cy, cx + r * 0.8, cy, r * 0.9)


def _palette(d, cx, cy, r):
    d.ellipse([cx - r * 0.85, cy - r * 0.8, cx + r * 0.85, cy + r * 0.85],
              outline=INK, width=_W(r, 0.14))
    for hx, hy in [(-0.4, -0.35), (0.1, -0.5), (0.5, -0.05), (0.3, 0.45)]:
        d.ellipse([cx + r * hx - r * 0.14, cy + r * hy - r * 0.14,
                   cx + r * hx + r * 0.14, cy + r * hy + r * 0.14], fill=INK)
    d.ellipse([cx - r * 0.45, cy + r * 0.25, cx - r * 0.1, cy + r * 0.6], outline=INK,
              width=_W(r, 0.1))


def _download(d, cx, cy, r):
    _arrow(d, cx, cy - r * 0.75, cx, cy + r * 0.35, r)
    d.line([(cx - r * 0.7, cy + r * 0.7), (cx + r * 0.7, cy + r * 0.7)],
           fill=INK, width=_W(r, 0.16))


def _upload(d, cx, cy, r):
    _arrow(d, cx, cy + r * 0.55, cx, cy - r * 0.55, r)
    d.line([(cx - r * 0.7, cy + r * 0.75), (cx + r * 0.7, cy + r * 0.75)],
           fill=INK, width=_W(r, 0.16))


def _list_caret(d, cx, cy, r):
    for k in (-0.5, -0.1, 0.3):
        d.line([(cx - r * 0.7, cy + r * k), (cx + r * 0.45, cy + r * k)],
               fill=INK, width=_W(r, 0.14))
    d.polygon([(cx + r * 0.2, cy + r * 0.55), (cx + r * 0.7, cy + r * 0.55),
               (cx + r * 0.45, cy + r * 0.85)], fill=INK)


def _search(d, cx, cy, r):
    w = _W(r, 0.18)
    d.ellipse([cx - r * 0.8, cy - r * 0.8, cx + r * 0.2, cy + r * 0.2],
              outline=INK, width=w)
    d.line([(cx + r * 0.12, cy + r * 0.12), (cx + r * 0.75, cy + r * 0.75)],
           fill=INK, width=int(w * 1.3))


def _book(d, cx, cy, r):
    w = _W(r, 0.14)
    d.line([(cx, cy - r * 0.7), (cx, cy + r * 0.7)], fill=INK, width=w)
    for s in (-1, 1):
        d.line([(cx, cy - r * 0.7), (cx + s * r * 0.75, cy - r * 0.5),
                (cx + s * r * 0.75, cy + r * 0.7), (cx, cy + r * 0.55)],
               fill=INK, width=w, joint="curve")


def _info(d, cx, cy, r):
    d.ellipse([cx - r * 0.8, cy - r * 0.8, cx + r * 0.8, cy + r * 0.8],
              outline=INK, width=_W(r, 0.16))
    d.ellipse([cx - r * 0.1, cy - r * 0.5, cx + r * 0.1, cy - r * 0.3], fill=INK)
    d.line([(cx, cy - r * 0.12), (cx, cy + r * 0.45)], fill=INK, width=_W(r, 0.18))


def _popout(d, cx, cy, r):
    w = _W(r, 0.16)
    d.line([(cx - r * 0.7, cy - r * 0.3), (cx - r * 0.7, cy + r * 0.7),
            (cx + r * 0.3, cy + r * 0.7)], fill=INK, width=w, joint="curve")
    _arrow(d, cx - r * 0.1, cy + r * 0.1, cx + r * 0.75, cy - r * 0.75, r * 0.9)


def _close(d, cx, cy, r):
    w = _W(r, 0.22)
    d.line([(cx - r * 0.65, cy - r * 0.65), (cx + r * 0.65, cy + r * 0.65)], fill=INK, width=w)
    d.line([(cx - r * 0.65, cy + r * 0.65), (cx + r * 0.65, cy - r * 0.65)], fill=INK, width=w)


def _fretboard(d, cx, cy, r):
    d.rounded_rectangle([cx - r * 0.85, cy - r * 0.55, cx + r * 0.85, cy + r * 0.55],
                        radius=r * 0.1, outline=INK, width=_W(r, 0.12))
    for k in (-0.4, 0.0, 0.4):
        d.line([(cx + r * k, cy - r * 0.55), (cx + r * k, cy + r * 0.55)],
               fill=INK, width=_W(r, 0.1))
    d.ellipse([cx - r * 0.24, cy - r * 0.1, cx - r * 0.04, cy + r * 0.1], fill=INK)
    d.ellipse([cx + r * 0.16, cy - r * 0.1, cx + r * 0.36, cy + r * 0.1], fill=INK)


def _drive(d, cx, cy, r):
    d.polygon([(cx, cy - r * 0.75), (cx + r * 0.8, cy + r * 0.7),
               (cx - r * 0.8, cy + r * 0.7)], outline=INK, width=_W(r, 0.16))
    d.line([(cx, cy - r * 0.75), (cx, cy + r * 0.7)], fill=INK, width=_W(r, 0.12))


# ---------------------------------------------------------------------------
# Generate
# ---------------------------------------------------------------------------

def generate_all() -> None:
    manifest = json.loads((ICONS / "manifest.json").read_text())
    sizes = manifest["render_sizes"]
    sizes["S"] = 20  # bump small icons so the engraved glyph reads
    knob = build_knob_base()
    disc = build_clean_disc(knob)

    rows = []
    for entry in manifest["icons"]:
        name = entry["name"]
        glyph = GLYPHS.get(name)
        if glyph is None:
            print(f"  ! no glyph for {name}")
            continue
        base = knob if name in ORNATE else disc
        icon = base.copy()
        d = ImageDraw.Draw(icon)
        glyph(d, MASTER / 2, MASTER * (0.30 if name in ORNATE else 0.34))
        px = sizes[entry["size"]]
        icon.resize((px, px), Image.LANCZOS).save(ICONS / f"{name}.png")
        icon.resize((px * 2, px * 2), Image.LANCZOS).save(ICONS / f"{name}@2x.png")
        rows.append((name, entry["size"], px, icon))
    _contact_sheet(rows, sizes)
    manifest["render_sizes"] = sizes
    (ICONS / "manifest.json").write_text(json.dumps(manifest, indent=2))
    print(f"generated {len(rows)} icons (+@2x)")


def _contact_sheet(rows, sizes) -> None:
    zoom, pad, lblw = 72, 14, 120
    cols = 2
    rh = zoom + pad
    canvas = Image.new("RGBA", (cols * (lblw + zoom + 90), ((len(rows) + 1) // cols) * rh + pad),
                       (40, 28, 18, 255))
    d = ImageDraw.Draw(canvas)
    f = _font(15)
    for i, (name, sz, px, icon) in enumerate(rows):
        col, row = i % cols, i // cols
        x = col * (lblw + zoom + 90) + pad
        y = row * rh + pad
        canvas.alpha_composite(icon.resize((zoom, zoom), Image.LANCZOS), (x, y))
        canvas.alpha_composite(icon.resize((px, px), Image.LANCZOS),
                               (x + zoom + 16, y + (zoom - px) // 2))
        d.text((x + zoom + 16 + px + 10, y + zoom // 2), f"{name} {px}px",
               font=f, fill=(235, 222, 198, 255), anchor="lm")
    canvas.convert("RGB").save(ICONS / "_contact.png")
    print(f"_contact.png    -> {canvas.size}")


if __name__ == "__main__":
    build_background()
    generate_all()
    print("done.")
