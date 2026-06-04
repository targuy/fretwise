"""PDF backend for canonical RenderScene."""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

from reportlab.pdfgen import canvas as rl_canvas

from fretwise.core.scene import RenderScene


def render_scene_to_pdf_bytes(scene: RenderScene) -> bytes:
    """Render scene to PDF bytes."""
    if not scene.document_scene.pages:
        buffer = BytesIO()
        canvas = rl_canvas.Canvas(buffer, pagesize=(1200.0, 380.0), pageCompression=0)
        canvas.showPage()
        canvas.save()
        return buffer.getvalue()

    first_page = scene.document_scene.pages[0]
    buffer = BytesIO()
    canvas = rl_canvas.Canvas(
        buffer,
        pagesize=(first_page.width, first_page.height),
        pageCompression=0,
    )
    _draw_scene_pages(canvas, scene)
    canvas.save()
    return buffer.getvalue()


def render_scene_to_pdf_file(scene: RenderScene, output_path: Path) -> None:
    """Render scene to a PDF file path."""
    if not scene.document_scene.pages:
        canvas = rl_canvas.Canvas(str(output_path), pagesize=(1200.0, 380.0), pageCompression=0)
        canvas.showPage()
        canvas.save()
        return

    first_page = scene.document_scene.pages[0]
    canvas = rl_canvas.Canvas(
        str(output_path),
        pagesize=(first_page.width, first_page.height),
        pageCompression=0,
    )
    _draw_scene_pages(canvas, scene)
    canvas.save()


def _draw_scene_pages(canvas: rl_canvas.Canvas, scene: RenderScene) -> None:
    for page_index, page in enumerate(scene.document_scene.pages):
        page_w = page.width
        page_h = page.height

        if page_index > 0:
            canvas.setPageSize((page_w, page_h))

        canvas.setStrokeColorRGB(1, 1, 1)
        canvas.setFillColorRGB(1, 1, 1)
        canvas.rect(0, 0, page_w, page_h, fill=1, stroke=0)

        canvas.setFillColorRGB(0, 0, 0)
        canvas.setFont("Helvetica", 14)
        canvas.drawString(30, _to_pdf_y(page_h, 24), scene.document_scene.title)

        for system in page.systems:
            for staff in system.staves:
                for layer in staff.layer_groups:
                    for recipe in layer.recipe_instances:
                        if recipe.recipe_id == "tab_lines":
                            _draw_lines(canvas, page_h, recipe.params, color=(0.4, 0.4, 0.4))
                        elif recipe.recipe_id == "staff_lines":
                            _draw_lines(canvas, page_h, recipe.params, color=(0.1, 0.1, 0.1))
                        elif recipe.recipe_id == "barline":
                            _draw_barline(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "ledger_line":
                            _draw_ledger_line(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "stem_line":
                            _draw_stem_line(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "flag_stack":
                            _draw_flag_stack(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "beam_group":
                            _draw_beam_group(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "tuplet_bracket":
                            _draw_tuplet_bracket(canvas, page_h, recipe.params, recipe.metadata)
                        elif recipe.recipe_id == "tie_arc":
                            _draw_arc(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "slur_arc":
                            _draw_arc(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "let_ring_span":
                            _draw_tab_span(
                                canvas,
                                page_h,
                                recipe.params,
                                label="L.R.",
                                color=(0.3, 0.3, 0.6),
                            )
                        elif recipe.recipe_id == "palm_mute_span":
                            label = str(recipe.params.get("label", "P.M."))
                            _draw_tab_span(
                                canvas,
                                page_h,
                                recipe.params,
                                label=label,
                                color=(0.1, 0.1, 0.1),
                            )
                    for text in layer.text_instances:
                        canvas.setFont(text.font_family, text.font_size)
                        canvas.setFillColorRGB(0, 0, 0)
                        canvas.drawString(text.x, _to_pdf_y(page_h, text.y), text.text)
                    for glyph in layer.glyph_instances:
                        _draw_glyph(
                            canvas,
                            page_h,
                            glyph_id=glyph.glyph_id,
                            x=glyph.x,
                            y=glyph.y,
                            size=glyph.size,
                            metadata=glyph.metadata,
                        )

        canvas.showPage()


def _draw_lines(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
    *,
    color: tuple[float, float, float],
) -> None:
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    width = float(params.get("width", 100.0))
    count = int(params.get("count", 6))
    spacing = float(params.get("spacing", 16.0))
    canvas.setStrokeColorRGB(*color)
    canvas.setLineWidth(1.0)
    for idx in range(count):
        line_y = y + idx * spacing
        y_pdf = _to_pdf_y(page_h, line_y)
        canvas.line(x, y_pdf, x + width, y_pdf)


def _draw_stem_line(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x = float(params.get("x", 0.0))
    y0 = float(params.get("y0", 0.0))
    y1 = float(params.get("y1", 0.0))
    width = float(params.get("width", 0.8))
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(max(0.5, width))
    canvas.line(x, _to_pdf_y(page_h, y0), x, _to_pdf_y(page_h, y1))


def _draw_barline(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x = float(params.get("x", 0.0))
    y0 = float(params.get("y0", 0.0))
    y1 = float(params.get("y1", y0))
    width = float(params.get("width", 0.8))
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(max(0.6, width))
    canvas.line(x, _to_pdf_y(page_h, y0), x, _to_pdf_y(page_h, y1))


def _draw_ledger_line(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    width = float(params.get("width", 1.0))
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(max(0.8, width))
    y_pdf = _to_pdf_y(page_h, y)
    canvas.line(x0, y_pdf, x1, y_pdf)


def _draw_flag_stack(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    count = int(params.get("count", 0))
    spacing = float(params.get("spacing", 4.0))
    width = float(params.get("width", 0.75))
    direction = str(params.get("direction", "up"))
    if count <= 0:
        return
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(max(0.6, width))
    x_ctrl1 = 3.8
    x_ctrl2 = 4.8
    x_end = 1.4
    y_ctrl1 = 1.8
    y_ctrl2 = 5.2
    y_end = 8.8
    for index in range(count):
        yi = y - index * spacing if direction == "down" else y + index * spacing
        path = canvas.beginPath()
        path.moveTo(x, _to_pdf_y(page_h, yi))
        if direction == "down":
            path.curveTo(
                x + x_ctrl1,
                _to_pdf_y(page_h, yi - y_ctrl1),
                x + x_ctrl2,
                _to_pdf_y(page_h, yi - y_ctrl2),
                x + x_end,
                _to_pdf_y(page_h, yi - y_end),
            )
        else:
            path.curveTo(
                x + x_ctrl1,
                _to_pdf_y(page_h, yi + y_ctrl1),
                x + x_ctrl2,
                _to_pdf_y(page_h, yi + y_ctrl2),
                x + x_end,
                _to_pdf_y(page_h, yi + y_end),
            )
        canvas.drawPath(path, stroke=1, fill=0)


def _draw_beam_group(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    base_y = float(params.get("y", 0.0))
    y0 = float(params.get("y0", base_y))
    y1 = float(params.get("y1", y0))
    level = int(params.get("level", 1))
    thickness = float(params.get("thickness", 2.5))
    gap = float(params.get("gap", 3.0))
    direction = str(params.get("direction", "up"))
    if x1 <= x0:
        return
    level_index = max(1, level) - 1
    # Stems-up: secondary beams stack downward (positive y, toward notehead).
    # Stems-down: secondary beams stack upward (negative y, toward notehead).
    sign = -1.0 if direction == "down" else 1.0
    offset = level_index * (thickness + gap) * sign
    near_y0 = y0 + offset
    near_y1 = y1 + offset
    far_y0 = near_y0 + sign * max(1.0, thickness)
    far_y1 = near_y1 + sign * max(1.0, thickness)

    canvas.setFillColorRGB(0, 0, 0)
    canvas.setStrokeColorRGB(0, 0, 0)
    path = canvas.beginPath()
    path.moveTo(x0, _to_pdf_y(page_h, near_y0))
    path.lineTo(x1, _to_pdf_y(page_h, near_y1))
    path.lineTo(x1, _to_pdf_y(page_h, far_y1))
    path.lineTo(x0, _to_pdf_y(page_h, far_y0))
    path.close()
    canvas.drawPath(path, fill=1, stroke=0)


def _draw_tab_span(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
    *,
    label: str,
    color: tuple[float, float, float],
) -> None:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    if x1 <= x0:
        return

    y_pdf = _to_pdf_y(page_h, y)
    canvas.setStrokeColorRGB(*color)
    canvas.setFillColorRGB(*color)
    canvas.setLineWidth(0.8)
    canvas.setDash(3, 2)
    canvas.line(x0, y_pdf, x1, y_pdf)
    canvas.setDash()
    canvas.setFont("Helvetica", 6)
    canvas.drawString(x0, y_pdf + 1.0, label)


def _draw_arc(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x0 = float(params.get("x0", 0.0))
    y0 = float(params.get("y0", 0.0))
    x1 = float(params.get("x1", x0))
    y1 = float(params.get("y1", y0))
    curvature = float(params.get("curvature", 8.0))
    if x1 <= x0:
        return

    cy = max(y0, y1) + curvature
    dx = x1 - x0
    c1x = x0 + dx / 3.0
    c2x = x0 + 2.0 * dx / 3.0

    path = canvas.beginPath()
    path.moveTo(x0, _to_pdf_y(page_h, y0))
    path.curveTo(
        c1x,
        _to_pdf_y(page_h, cy),
        c2x,
        _to_pdf_y(page_h, cy),
        x1,
        _to_pdf_y(page_h, y1),
    )
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(1.0)
    canvas.drawPath(path, stroke=1, fill=0)


def _draw_tuplet_bracket(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
    metadata: dict[str, object] | None,
) -> None:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    number = int(params.get("number", 3))
    direction = str(params.get("direction", "up"))
    tuplet_style = str((metadata or {}).get("style") or params.get("style") or "standard")

    if tuplet_style == "tablature_rhythm":
        margin = 3.5
        font_name = "Times-BoldItalic"
        font_size = 10.0
        text_half_w = 5.8
        # In scene coords Y increases downward (same as SVG).  "down" means the bracket
        # is placed below the beam line (hooks open downward, away from the staff).
        hook_y1 = y + 4.2 if direction == "down" else y - 4.2
        line_width = 1.1
    else:
        margin = 2.5
        font_name = "Times-Italic"
        font_size = 8.0
        text_half_w = 4.2
        hook_y1 = y + 3.0 if direction == "down" else y - 3.0
        line_width = 0.8

    bx0 = x0 - margin
    bx1 = x1 + margin
    xmid = (bx0 + bx1) / 2.0
    left_arm_end = xmid - text_half_w
    right_arm_start = xmid + text_half_w

    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setLineWidth(line_width)
    canvas.line(bx0, _to_pdf_y(page_h, y), bx0, _to_pdf_y(page_h, hook_y1))
    if left_arm_end > bx0 + 0.5:
        canvas.line(bx0, _to_pdf_y(page_h, y), left_arm_end, _to_pdf_y(page_h, y))
    if right_arm_start < bx1 - 0.5:
        canvas.line(right_arm_start, _to_pdf_y(page_h, y), bx1, _to_pdf_y(page_h, y))
    canvas.line(bx1, _to_pdf_y(page_h, y), bx1, _to_pdf_y(page_h, hook_y1))

    canvas.setFillColorRGB(0, 0, 0)
    canvas.setFont(font_name, font_size)
    canvas.drawCentredString(xmid, _to_pdf_y(page_h, y + font_size * 0.16), str(number))


def _to_pdf_y(page_h: float, scene_y: float) -> float:
    return page_h - scene_y


def _draw_glyph(
    canvas: rl_canvas.Canvas,
    page_h: float,
    *,
    glyph_id: str,
    x: float,
    y: float,
    size: float,
    metadata: dict[str, object],
) -> None:
    y_pdf = _to_pdf_y(page_h, y)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setStrokeColorRGB(0, 0, 0)

    if glyph_id == "notehead":
        _draw_notehead_glyph(canvas, page_h, x=x, y=y, size=size, metadata=metadata)
        return

    if glyph_id == "clef":
        clef = str((metadata or {}).get("clef", "treble"))
        # ReportLab base-14 fonts lack SMuFL clef glyphs, so use the
        # conventional clef letters: treble = G clef, bass = F clef,
        # percussion = the neutral two-bar symbol (rendered as "||").
        char = {"bass": "F", "percussion": "||"}.get(clef, "G")
        canvas.setFont("Times-Roman", max(10.0, size))
        canvas.drawString(x, y_pdf, char)
        return

    if glyph_id == "time_signature":
        numerator = int(metadata.get("numerator", 4))
        denominator = int(metadata.get("denominator", 4))
        fs = max(9.0, size)
        canvas.setFont("Times-Roman", fs)
        canvas.drawCentredString(x, _to_pdf_y(page_h, y - 4.5), str(numerator))
        canvas.drawCentredString(x, _to_pdf_y(page_h, y + 5.5), str(denominator))
        return

    if glyph_id == "rest":
        _draw_rest_glyph(canvas, page_h, x=x, y=y, size=size, metadata=metadata)
        return
    if glyph_id == "accidental_sharp":
        canvas.setFont("Helvetica", max(8.0, size))
        canvas.drawString(x, y_pdf, "#")
        return
    if glyph_id == "accidental_flat":
        canvas.setFont("Helvetica", max(8.0, size))
        canvas.drawString(x, y_pdf, "b")
        return
    if glyph_id == "accidental_natural":
        canvas.setFont("Helvetica", max(8.0, size))
        canvas.drawString(x, y_pdf, "♮")
        return

    radius = max(1.0, size)
    canvas.circle(x, y_pdf, radius, fill=0, stroke=1)


def _draw_notehead_glyph(
    canvas: rl_canvas.Canvas,
    page_h: float,
    *,
    x: float,
    y: float,
    size: float,
    metadata: dict[str, object],
) -> None:
    filled = bool(metadata.get("filled", False))
    rx = max(3.4, float(metadata.get("rx", size * 1.1)))
    ry = max(2.4, float(metadata.get("ry", size * 0.78)))
    rotation = float(metadata.get("rotation", -20.0))
    stroke_width = max(0.6, float(metadata.get("stroke_width", 0.9)))
    y_pdf = _to_pdf_y(page_h, y)
    canvas.saveState()
    canvas.translate(x, y_pdf)
    canvas.rotate(rotation)
    canvas.setLineWidth(stroke_width)
    canvas.ellipse(-rx, -ry, rx, ry, fill=1 if filled else 0, stroke=1)
    canvas.restoreState()
    dot_count = int(metadata.get("dot_count", 0) or 0)
    if dot_count <= 0:
        return
    spacing = max(2.6, float(metadata.get("staff_spacing", 8.0)) * 0.33)
    on_line = str(metadata.get("on_staff_line", "false")).lower() == "true"
    dot_y = y - spacing * 0.45 if on_line else y
    dot_r = max(1.0, ry * 0.32)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setStrokeColorRGB(0, 0, 0)
    for idx in range(dot_count):
        dot_x = x + rx + 2.3 + idx * (dot_r * 2.5)
        canvas.circle(dot_x, _to_pdf_y(page_h, dot_y), dot_r, fill=1, stroke=0)


def _draw_rest_glyph(
    canvas: rl_canvas.Canvas,
    page_h: float,
    *,
    x: float,
    y: float,
    size: float,
    metadata: dict[str, object],
) -> None:
    duration = float(metadata.get("duration", 0.5) or 0.5)
    rest_kind = str(metadata.get("rest_kind") or _duration_class(duration))
    if str(metadata.get("is_measure_rest", "")).lower() == "true":
        rest_kind = "whole"
    block_w = max(6.0, float(metadata.get("rest_block_width", 8.0)))
    block_h = max(2.0, float(metadata.get("rest_block_height", 3.0)))
    half_w = block_w / 2.0
    augmentation_dot_count = int(metadata.get("dot_count", 0) or 0)
    is_tab_rhythm = str(metadata.get("mode", "")).strip() == "tablature_rhythm"
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.setFillColorRGB(0, 0, 0)

    def _draw_augmentation_dots(dot_y: float) -> None:
        if augmentation_dot_count <= 0:
            return
        for idx in range(augmentation_dot_count):
            dot_x = x + 5.0 + idx * 2.8
            canvas.circle(dot_x, _to_pdf_y(page_h, dot_y), 1.15, fill=1, stroke=0)

    if rest_kind == "whole":
        canvas.setLineWidth(0.7)
        canvas.line(x - 5.5, _to_pdf_y(page_h, y), x + 5.5, _to_pdf_y(page_h, y))
        canvas.rect(
            x - half_w,
            _to_pdf_y(page_h, y + block_h),
            block_w,
            block_h,
            fill=1,
            stroke=0,
        )
        _draw_augmentation_dots(y + 1.2)
        return

    if rest_kind == "half":
        canvas.setLineWidth(0.7)
        canvas.line(x - 5.5, _to_pdf_y(page_h, y), x + 5.5, _to_pdf_y(page_h, y))
        canvas.rect(
            x - half_w,
            _to_pdf_y(page_h, y),
            block_w,
            block_h,
            fill=1,
            stroke=0,
        )
        _draw_augmentation_dots(y + 0.5)
        return

    canvas.setLineWidth(1.1 if is_tab_rhythm else 1.0)
    if rest_kind == "quarter":
        path = canvas.beginPath()
        path.moveTo(x - 2.0, _to_pdf_y(page_h, y + 4.0))
        path.lineTo(x + 2.5, _to_pdf_y(page_h, y + 1.5))
        path.curveTo(
            x + 4.0,
            _to_pdf_y(page_h, y + 0.5),
            x - 3.5,
            _to_pdf_y(page_h, y - 2.0),
            x + 0.5,
            _to_pdf_y(page_h, y - 3.0),
        )
        path.curveTo(
            x + 2.5,
            _to_pdf_y(page_h, y - 4.0),
            x - 1.0,
            _to_pdf_y(page_h, y + 5.5),
            x + 0.5,
            _to_pdf_y(page_h, y + 7.0),
        )
        canvas.drawPath(path, stroke=1, fill=0)
        _draw_augmentation_dots(y + 0.5)
        return

    intrinsic_dot_count = {
        "eighth": 1,
        "sixteenth": 2,
        "thirty_second": 3,
        "sixty_fourth": 4,
    }.get(rest_kind, 1)
    canvas.setLineWidth(0.95 if is_tab_rhythm else 0.8)
    canvas.line(x - 1.5, _to_pdf_y(page_h, y + 4.0), x + 2.0, _to_pdf_y(page_h, y - 3.8))
    canvas.setLineWidth(0.0)
    for idx in range(intrinsic_dot_count):
        dot_x = x - 1.0 - idx * 0.8
        dot_y = y - 3.0 + idx * 2.8
        canvas.circle(dot_x, _to_pdf_y(page_h, dot_y), 1.25, fill=1, stroke=0)
    _draw_augmentation_dots(y + 0.8)


def _duration_class(duration: float) -> str:
    base = _duration_components(duration)[0]
    if base >= 4.0:
        return "whole"
    if base >= 2.0:
        return "half"
    if base >= 1.0:
        return "quarter"
    if base >= 0.5:
        return "eighth"
    if base >= 0.25:
        return "sixteenth"
    if base >= 0.125:
        return "thirty_second"
    return "sixty_fourth"


def _duration_components(duration: float) -> tuple[float, int]:
    known_bases = (8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125, 0.0625)
    tol = 0.01
    for base in known_bases:
        if abs(duration - base) <= tol:
            return base, 0
        if abs(duration - base * 1.5) <= tol:
            return base, 1
        if abs(duration - base * 1.75) <= tol:
            return base, 2
    return duration, 0
