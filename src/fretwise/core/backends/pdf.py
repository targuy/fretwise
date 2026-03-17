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
                        elif recipe.recipe_id == "stem_line":
                            _draw_stem_line(canvas, page_h, recipe.params)
                        elif recipe.recipe_id == "beam_group":
                            _draw_beam_group(canvas, page_h, recipe.params)
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


def _draw_beam_group(
    canvas: rl_canvas.Canvas,
    page_h: float,
    params: dict[str, object],
) -> None:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    thickness = float(params.get("thickness", 2.5))
    width = x1 - x0
    if width <= 0.0:
        return
    y_top_pdf = _to_pdf_y(page_h, y)
    canvas.setFillColorRGB(0, 0, 0)
    canvas.setStrokeColorRGB(0, 0, 0)
    canvas.rect(
        x0,
        y_top_pdf - max(1.0, thickness),
        width,
        max(1.0, thickness),
        fill=1,
        stroke=0,
    )


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

    if glyph_id == "clef":
        canvas.setFont("Times-Roman", max(10.0, size))
        canvas.drawString(x, y_pdf, "G")
        return

    if glyph_id == "time_signature":
        numerator = int(metadata.get("numerator", 4))
        denominator = int(metadata.get("denominator", 4))
        canvas.setFont("Helvetica", max(9.0, size))
        canvas.drawString(x, y_pdf, f"{numerator}/{denominator}")
        return

    if glyph_id == "rest":
        canvas.setFont("Times-Roman", max(9.0, size))
        canvas.drawString(x, y_pdf, "rest")
        return
    if glyph_id == "accidental_sharp":
        canvas.setFont("Helvetica", max(8.0, size))
        canvas.drawString(x, y_pdf, "#")
        return
    if glyph_id == "accidental_flat":
        canvas.setFont("Helvetica", max(8.0, size))
        canvas.drawString(x, y_pdf, "b")
        return

    radius = max(1.0, size)
    canvas.circle(x, y_pdf, radius, fill=0, stroke=1)
