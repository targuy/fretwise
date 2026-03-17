"""SVG backend for canonical RenderScene."""

from __future__ import annotations

from html import escape

from fretwise.core.scene import RenderScene


def render_scene_to_svg(scene: RenderScene) -> str:
    """Render a scene into a minimal SVG string."""
    if not scene.document_scene.pages:
        return (
            '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="380">'
            "</svg>"
        )

    page = scene.document_scene.pages[0]
    out: list[str] = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{page.width}" '
        f'height="{page.height}" viewBox="0 0 {page.width} {page.height}">',
        '<rect x="0" y="0" width="100%" height="100%" fill="white"/>',
        f'<text x="30" y="24" font-family="Helvetica" font-size="14">'
        f"{escape(scene.document_scene.title)}</text>",
    ]

    for system in page.systems:
        for staff in system.staves:
            for layer in staff.layer_groups:
                for recipe in layer.recipe_instances:
                    if recipe.recipe_id == "tab_lines":
                        out.extend(_render_lines(recipe.params, stroke="#666"))
                    elif recipe.recipe_id == "staff_lines":
                        out.extend(_render_lines(recipe.params, stroke="#222"))
                    elif recipe.recipe_id == "stem_line":
                        out.append(_render_stem_line(recipe.params))
                    elif recipe.recipe_id == "beam_group":
                        out.append(_render_beam_group(recipe.params))
                for text in layer.text_instances:
                    out.append(
                        f'<text x="{text.x:.2f}" y="{text.y:.2f}" '
                        f'font-family="{escape(text.font_family)}" '
                        f'font-size="{text.font_size:.2f}">'
                        f"{escape(text.text)}</text>"
                    )
                for glyph in layer.glyph_instances:
                    out.append(
                        _render_glyph(
                            glyph.glyph_id,
                            x=glyph.x,
                            y=glyph.y,
                            size=glyph.size,
                            metadata=glyph.metadata,
                        )
                    )

    out.append("</svg>")
    return "\n".join(out)


def _render_lines(params: dict[str, object], *, stroke: str) -> list[str]:
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    width = float(params.get("width", 100.0))
    count = int(params.get("count", 6))
    spacing = float(params.get("spacing", 16.0))
    lines: list[str] = []
    for idx in range(count):
        line_y = y + idx * spacing
        lines.append(
            f'<line x1="{x:.2f}" y1="{line_y:.2f}" x2="{x + width:.2f}" '
            f'y2="{line_y:.2f}" stroke="{stroke}" stroke-width="1"/>'
        )
    return lines


def _render_stem_line(params: dict[str, object]) -> str:
    x = float(params.get("x", 0.0))
    y0 = float(params.get("y0", 0.0))
    y1 = float(params.get("y1", 0.0))
    width = float(params.get("width", 0.8))
    return (
        f'<line x1="{x:.2f}" y1="{y0:.2f}" x2="{x:.2f}" y2="{y1:.2f}" '
        f'stroke="black" stroke-width="{max(0.5, width):.2f}"/>'
    )


def _render_beam_group(params: dict[str, object]) -> str:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    thickness = float(params.get("thickness", 2.5))
    width = max(0.0, x1 - x0)
    if width <= 0.0:
        return ""
    return (
        f'<rect x="{x0:.2f}" y="{(y - thickness):.2f}" '
        f'width="{width:.2f}" height="{max(1.0, thickness):.2f}" fill="black"/>'
    )


def _render_glyph(
    glyph_id: str,
    *,
    x: float,
    y: float,
    size: float,
    metadata: dict[str, object],
) -> str:
    if glyph_id == "clef":
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Times New Roman" font-size="{max(10.0, size):.2f}">'
            "𝄞</text>"
        )
    if glyph_id == "time_signature":
        numerator = int(metadata.get("numerator", 4))
        denominator = int(metadata.get("denominator", 4))
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Helvetica" font-size="{max(9.0, size):.2f}">'
            f"{numerator}/{denominator}</text>"
        )
    if glyph_id == "rest":
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Times New Roman" font-size="{max(9.0, size):.2f}">'
            "𝄽</text>"
        )
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" '
        f'r="{max(1.0, size):.2f}" '
        'fill="none" stroke="black"/>'
    )
