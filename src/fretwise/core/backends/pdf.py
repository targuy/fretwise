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
                            _draw_tab_lines(canvas, page_h, recipe.params)
                    for text in layer.text_instances:
                        canvas.setFont(text.font_family, text.font_size)
                        canvas.setFillColorRGB(0, 0, 0)
                        canvas.drawString(text.x, _to_pdf_y(page_h, text.y), text.text)
                    for glyph in layer.glyph_instances:
                        radius = max(1.0, glyph.size)
                        canvas.setStrokeColorRGB(0, 0, 0)
                        canvas.circle(glyph.x, _to_pdf_y(page_h, glyph.y), radius, fill=0, stroke=1)

        canvas.showPage()


def _draw_tab_lines(
    canvas: rl_canvas.Canvas, page_h: float, params: dict[str, object]
) -> None:
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    width = float(params.get("width", 100.0))
    count = int(params.get("count", 6))
    spacing = float(params.get("spacing", 16.0))
    canvas.setStrokeColorRGB(0.4, 0.4, 0.4)
    canvas.setLineWidth(1.0)
    for idx in range(count):
        line_y = y + idx * spacing
        y_pdf = _to_pdf_y(page_h, line_y)
        canvas.line(x, y_pdf, x + width, y_pdf)


def _to_pdf_y(page_h: float, scene_y: float) -> float:
    return page_h - scene_y

