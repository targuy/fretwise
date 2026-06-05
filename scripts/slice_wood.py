#!/usr/bin/env python
"""Slice FretWise's wood-panel UI artwork from the designer's texture sheets.

Inputs (placed by the designer, 1407x768 contact sheets, 8 columns x 4 rows):
  * web/static/img/backgrounds.png             — wood tiles, light (top) + dark (bottom)
  * web/static/img/backgrounds with knobs.png  — same tiles with a metal knob (unused here;
                                                 the knob base comes from icons/ICON.png at a
                                                 higher resolution — see build_leather_icons.py)

Outputs (web/static/img/wood/):
  * dark.png   / light.png   — seamless mirror-tiled wood squares (background-repeat).
  * dark-strip.png           — wide seamless horizontal band for header / toolbar chrome.
  * dark-frame.png / light-frame.png
                             — fully-framed plaques cropped to the frame's outer edge,
                               for CSS `border-image` 9-slice on panels / cards.

The tiles are used UNCUT (native pixels, repeated / 9-sliced) — never stretched.

Run:  python scripts/slice_wood.py
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
IMG = ROOT / "src" / "fretwise" / "web" / "static" / "img"
WOOD = IMG / "wood"

# Contact-sheet grid (measured from the non-white content bands).
COLS = [(34, 192), (205, 361), (374, 530), (543, 697),
        (709, 864), (876, 1032), (1043, 1201), (1213, 1370)]
ROWS = [(115, 258), (292, 430), (455, 590), (597, 724)]

# Which cell holds which variant (row, col).
LIGHT_BASE = (0, 0)   # "Texture sans bord", light maple
DARK_BASE = (2, 0)    # "Texture sans bord", dark rosewood
LIGHT_FRAME = (1, 7)  # "Texture totalement encadree", light
DARK_FRAME = (3, 7)   # "Texture totalement encadree", dark


def _cell(sheet: Image.Image, rc: tuple[int, int]) -> Image.Image:
    r, c = rc
    x0, x1 = COLS[c]
    y0, y1 = ROWS[r]
    return sheet.crop((x0, y0, x1, y1))


def _seamless(tile: Image.Image, box: tuple[int, int, int, int], size: int) -> Image.Image:
    """Mirror a clean interior crop into a 2x2 block that repeats with no seam.

    `box` must exclude the cell's bright border / caption bleed — a stray light
    row landing on the mirror fold would otherwise double into a seam line.
    """
    core = tile.crop(box).resize((size, size), Image.LANCZOS)
    block = Image.new("RGB", (size * 2, size * 2))
    block.paste(core, (0, 0))
    block.paste(core.transpose(Image.FLIP_LEFT_RIGHT), (size, 0))
    block.paste(core.transpose(Image.FLIP_TOP_BOTTOM), (0, size))
    block.paste(core.transpose(Image.ROTATE_180), (size, size))
    return block


def _frame(tile: Image.Image, l: int, t: int, r: int, b: int) -> Image.Image:
    """Crop a fully-framed plaque to the outer edge of its frame (drop wood margin
    + any caption bleed)."""
    w, h = tile.size
    return tile.crop((l, t, w - r, h - b))


def main() -> None:
    WOOD.mkdir(parents=True, exist_ok=True)
    bg = Image.open(IMG / "backgrounds.png").convert("RGB")

    # --- seamless base tiles -------------------------------------------------
    # clean interior boxes (exclude the cell's bright border + caption bleed)
    dark = _seamless(_cell(bg, DARK_BASE), box=(6, 6, 152, 116), size=128)
    light = _seamless(_cell(bg, LIGHT_BASE), box=(4, 2, 155, 138), size=128)
    dark.save(WOOD / "dark.png")
    light.save(WOOD / "light.png")
    print(f"dark.png   -> {dark.size}")
    print(f"light.png  -> {light.size}")

    # --- wide chrome strip (header / toolbar) --------------------------------
    core = dark.crop((0, 0, 128, 128))
    strip = Image.new("RGB", (128 * 8, 128))
    for i in range(8):
        cell = core if i % 2 == 0 else core.transpose(Image.FLIP_LEFT_RIGHT)
        strip.paste(cell, (i * 128, 0))
    strip.save(WOOD / "dark-strip.png")
    print(f"dark-strip.png -> {strip.size}")

    # --- framed plaques for border-image -------------------------------------
    # margins measured per tile so the crop lands on the frame's outer edge.
    lf = _frame(_cell(bg, LIGHT_FRAME), l=9, t=7, r=9, b=10)
    df = _frame(_cell(bg, DARK_FRAME), l=6, t=4, r=6, b=10)
    # The dark plaque carries a "page-curl" decoration in its bottom-right corner;
    # patch it by mirroring the clean (symmetric) bottom-left corner over it.
    pw, ph = 60, 48
    w, h = df.size
    patch = df.crop((0, h - ph, pw, h)).transpose(Image.FLIP_LEFT_RIGHT)
    df.paste(patch, (w - pw, h - ph))
    lf.save(WOOD / "light-frame.png")
    df.save(WOOD / "dark-frame.png")
    print(f"light-frame.png -> {lf.size}")
    print(f"dark-frame.png  -> {df.size}")


if __name__ == "__main__":
    main()
