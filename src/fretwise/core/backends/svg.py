"""SVG backend for canonical RenderScene."""

from __future__ import annotations

from html import escape

from fretwise.core.graphics.reference_glyph_set import default_reference_glyph_set
from fretwise.core.scene import RenderScene


_REFERENCE_GLYPHS = default_reference_glyph_set()
_REST_KIND_TO_REFERENCE_GLYPH = {
    "quarter": "rest_quarter",
    "eighth": "rest_eighth",
    "sixteenth": "rest_sixteenth",
    "thirty_second": "rest_thirty_second",
}

_REPEAT_BARLINE_VIEWBOX_W = 1.864
_REPEAT_BARLINE_VIEWBOX_H = 6.6639997
_REPEAT_BARLINE_HOOK_UP_PATH = (
    "m 450,333 c 9,0 16,-8 16,-16 0,-3 -1,-6 -3,-9 C 364,164 248,-56 75,-56 "
    "l -75,0 0,87 c 0,14 11,25 25,25 l 50,0 c 159,0 271,136 362,270 3,4 8,7 13,7 z"
)
_REPEAT_BARLINE_HOOK_DOWN_PATH = (
    "m 466,-317 c 0,-8 -7,-16 -16,-16 -5,0 -10,3 -13,7 -91,134 -203,270 -362,270 "
    "l -50,0 C 11,-56 0,-45 0,-31 l 0,87 75,0 c 173,0 289,-220 388,-364 2,-3 3,-6 3,-9 z"
)
_REPEAT_BARLINE_DOT_PATH = (
    "M 0,0 C 0,31 25,56 56,56 87,56 112,31 112,0 112,-31 87,-56 56,-56 25,-56 0,-31 0,0 Z"
)


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
                    elif recipe.recipe_id == "barline":
                        out.append(_render_barline(recipe.params))
                    elif recipe.recipe_id == "ledger_line":
                        out.append(_render_ledger_line(recipe.params))
                    elif recipe.recipe_id == "stem_line":
                        out.append(_render_stem_line(recipe.params))
                    elif recipe.recipe_id == "flag_stack":
                        out.extend(_render_flag_stack(recipe.params))
                    elif recipe.recipe_id == "beam_group":
                        out.append(_render_beam_group(recipe.params))
                    elif recipe.recipe_id == "tie_arc":
                        out.append(_render_arc(recipe.params, stroke="#111"))
                    elif recipe.recipe_id == "slur_arc":
                        out.append(_render_arc(recipe.params, stroke="#111"))
                    elif recipe.recipe_id == "let_ring_span":
                        out.extend(
                            _render_tab_span(
                                recipe.params,
                                label="L.R.",
                                stroke="#446",
                                dy=-1.0,
                            )
                        )
                    elif recipe.recipe_id == "palm_mute_span":
                        label = str(recipe.params.get("label", "P.M."))
                        out.extend(
                            _render_tab_span(
                                recipe.params,
                                label=label,
                                stroke="#111",
                                dy=-1.0,
                            )
                        )
                    elif recipe.recipe_id == "tab_slide_line":
                        x0 = float(recipe.params.get("x0", 0.0))
                        y0 = float(recipe.params.get("y0", 0.0))
                        x1 = float(recipe.params.get("x1", x0))
                        y1 = float(recipe.params.get("y1", y0))
                        if x1 > x0:
                            out.append(
                                f'<line x1="{x0:.2f}" y1="{y0:.2f}" '
                                f'x2="{x1:.2f}" y2="{y1:.2f}" '
                                f'stroke="#111" stroke-width="0.9"/>'
                            )
                    elif recipe.recipe_id == "tuplet_bracket":
                        out.extend(_render_tuplet_bracket(recipe.params, recipe.metadata))
                    elif recipe.recipe_id == "filled_circle":
                        cx = float(recipe.params.get("cx", 0.0))
                        cy = float(recipe.params.get("cy", 0.0))
                        r = float(recipe.params.get("r", 1.0))
                        out.append(
                            f'<circle cx="{cx:.2f}" cy="{cy:.2f}" r="{r:.2f}" '
                            f'fill="black" stroke="none"/>'
                        )
                for text in layer.text_instances:
                    out.extend(_render_text_instance(text=text))
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


def _render_barline(params: dict[str, object]) -> str:
    x = float(params.get("x", 0.0))
    y0 = float(params.get("y0", 0.0))
    y1 = float(params.get("y1", y0))
    width = float(params.get("width", 0.8))
    return (
        f'<line x1="{x:.2f}" y1="{y0:.2f}" x2="{x:.2f}" y2="{y1:.2f}" '
        f'stroke="black" stroke-width="{max(0.6, width):.2f}"/>'
    )


def _render_ledger_line(params: dict[str, object]) -> str:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    width = float(params.get("width", 1.0))
    return (
        f'<line x1="{x0:.2f}" y1="{y:.2f}" x2="{x1:.2f}" y2="{y:.2f}" '
        f'stroke="black" stroke-width="{max(0.8, width):.2f}"/>'
    )


def _render_flag_stack(params: dict[str, object]) -> list[str]:
    x = float(params.get("x", 0.0))
    y = float(params.get("y", 0.0))
    count = int(params.get("count", 0))
    spacing = float(params.get("spacing", 4.0))
    width = float(params.get("width", 0.75))
    direction = str(params.get("direction", "up"))
    if count <= 0:
        return []
    paths: list[str] = []
    x_ctrl1 = 3.8
    x_ctrl2 = 4.8
    x_end = 1.4
    y_ctrl1 = 1.8
    y_ctrl2 = 5.2
    y_end = 8.8
    for index in range(count):
        if direction == "down":
            yi = y - index * spacing
            path_d = (
                f"M{x:.2f},{yi:.2f} "
                f"C{x + x_ctrl1:.2f},{yi - y_ctrl1:.2f} "
                f"{x + x_ctrl2:.2f},{yi - y_ctrl2:.2f} "
                f"{x + x_end:.2f},{yi - y_end:.2f}"
            )
        else:
            yi = y + index * spacing
            path_d = (
                f"M{x:.2f},{yi:.2f} "
                f"C{x + x_ctrl1:.2f},{yi + y_ctrl1:.2f} "
                f"{x + x_ctrl2:.2f},{yi + y_ctrl2:.2f} "
                f"{x + x_end:.2f},{yi + y_end:.2f}"
            )
        paths.append(
            f'<path d="{path_d}" '
            f'fill="none" stroke="black" stroke-width="{max(0.6, width):.2f}"/>'
        )
    return paths


def _render_beam_group(params: dict[str, object]) -> str:
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
        return ""
    level_index = max(1, level) - 1
    # Stems-up: secondary beams stack downward (positive y, toward notehead).
    # Stems-down: secondary beams stack upward (negative y, toward notehead).
    sign = -1.0 if direction == "down" else 1.0
    offset = level_index * (thickness + gap) * sign
    near_y0 = y0 + offset
    near_y1 = y1 + offset
    far_y0 = near_y0 + sign * max(1.0, thickness)
    far_y1 = near_y1 + sign * max(1.0, thickness)
    return (
        '<polygon points="'
        f"{x0:.2f},{near_y0:.2f} "
        f"{x1:.2f},{near_y1:.2f} "
        f"{x1:.2f},{far_y1:.2f} "
        f"{x0:.2f},{far_y0:.2f}"
        '" fill="black"/>'
    )


def _render_arc(params: dict[str, object], *, stroke: str) -> str:
    x0 = float(params.get("x0", 0.0))
    y0 = float(params.get("y0", 0.0))
    x1 = float(params.get("x1", x0))
    y1 = float(params.get("y1", y0))
    curvature = float(params.get("curvature", 8.0))
    if x1 <= x0:
        return ""
    cx = (x0 + x1) / 2.0
    cy = max(y0, y1) + curvature
    return (
        f'<path d="M{x0:.2f},{y0:.2f} Q{cx:.2f},{cy:.2f} {x1:.2f},{y1:.2f}" '
        f'fill="none" stroke="{stroke}" stroke-width="1"/>'
    )


def _render_tab_span(
    params: dict[str, object],
    *,
    label: str,
    stroke: str,
    dy: float,
) -> list[str]:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    if x1 <= x0:
        return []
    text = (
        f'<text x="{x0:.2f}" y="{(y + dy):.2f}" '
        f'font-family="Helvetica" font-size="6">{escape(label)}</text>'
    )
    line = (
        f'<line x1="{x0:.2f}" y1="{y:.2f}" x2="{x1:.2f}" y2="{y:.2f}" '
        f'stroke="{stroke}" stroke-width="0.8" stroke-dasharray="3 2"/>'
    )
    return [text, line]


def _render_tuplet_bracket(
    params: dict[str, object], metadata: dict[str, object] | None = None
) -> list[str]:
    x0 = float(params.get("x0", 0.0))
    x1 = float(params.get("x1", x0))
    y = float(params.get("y", 0.0))
    number = int(params.get("number", 3))
    direction = str(params.get("direction", "up"))
    tuplet_style = str((metadata or {}).get("style") or params.get("style") or "standard")

    if tuplet_style == "tablature_rhythm":
        return _render_tablature_rhythm_tuplet_bracket(
            x0=x0,
            x1=x1,
            y=y,
            number=number,
            direction=direction,
        )
    return _render_standard_tuplet_bracket(
        x0=x0,
        x1=x1,
        y=y,
        number=number,
        direction=direction,
    )


def _render_tablature_rhythm_tuplet_bracket(
    *, x0: float, x1: float, y: float, number: int, direction: str
) -> list[str]:
    """Render the heavier Guitar Pro-like bracket used only in TAB+Rhythm."""

    margin = 3.5
    bx0 = x0 - margin
    bx1 = x1 + margin
    xmid = (bx0 + bx1) / 2.0

    font_size = 10
    text_half_w = 5.8

    hook_h = 4.2
    # Hooks point away from the beam: when the bracket is below the beam
    # (direction=="up"), hooks open downward (+y); above (direction=="down"),
    # hooks open upward (-y).
    tick_y1 = y + hook_h if direction == "down" else y - hook_h

    stroke = 'stroke="black" stroke-width="1.1" fill="none" stroke-linecap="round"'
    out: list[str] = []

    # Left vertical tick
    out.append(f'<line x1="{bx0:.2f}" y1="{y:.2f}" x2="{bx0:.2f}" y2="{tick_y1:.2f}" {stroke}/>')
    # Left horizontal arm (bx0 to xmid - text_half_w)
    left_arm_end = xmid - text_half_w
    if left_arm_end > bx0 + 0.5:
        out.append(f'<line x1="{bx0:.2f}" y1="{y:.2f}" x2="{left_arm_end:.2f}" y2="{y:.2f}" {stroke}/>')
    # Right horizontal arm (xmid + text_half_w to bx1)
    right_arm_start = xmid + text_half_w
    if right_arm_start < bx1 - 0.5:
        out.append(f'<line x1="{right_arm_start:.2f}" y1="{y:.2f}" x2="{bx1:.2f}" y2="{y:.2f}" {stroke}/>')
    # Right vertical tick
    out.append(f'<line x1="{bx1:.2f}" y1="{y:.2f}" x2="{bx1:.2f}" y2="{tick_y1:.2f}" {stroke}/>')
    # Centered italic bold number, vertically centered on the arm line.
    out.append(
        f'<text x="{xmid:.2f}" y="{y:.2f}" '
        f'font-family="serif" font-size="{font_size}" '
        f'font-style="italic" font-weight="bold" '
        f'text-anchor="middle" dominant-baseline="middle">{number}</text>'
    )
    return out


def _render_standard_tuplet_bracket(
    *, x0: float, x1: float, y: float, number: int, direction: str
) -> list[str]:
    """Render the lighter bracket used by standard notation views."""

    margin = 2.5
    bx0 = x0 - margin
    bx1 = x1 + margin
    xmid = (bx0 + bx1) / 2.0

    text_half_w = 4.2
    hook_h = 3.0
    # In SVG Y increases downward. "up" means bracket is above the notes (stems-up):
    # hooks point upward = smaller y.  "down" means bracket is below the notes: hooks
    # point downward = larger y.
    hook_y1 = y - hook_h if direction == "up" else y + hook_h
    stroke = 'stroke="black" stroke-width="0.8" fill="none" stroke-linecap="round"'
    out: list[str] = []

    out.append(f'<line x1="{bx0:.2f}" y1="{y:.2f}" x2="{bx0:.2f}" y2="{hook_y1:.2f}" {stroke}/>')
    left_arm_end = xmid - text_half_w
    if left_arm_end > bx0 + 0.5:
        out.append(f'<line x1="{bx0:.2f}" y1="{y:.2f}" x2="{left_arm_end:.2f}" y2="{y:.2f}" {stroke}/>')
    right_arm_start = xmid + text_half_w
    if right_arm_start < bx1 - 0.5:
        out.append(f'<line x1="{right_arm_start:.2f}" y1="{y:.2f}" x2="{bx1:.2f}" y2="{y:.2f}" {stroke}/>')
    out.append(f'<line x1="{bx1:.2f}" y1="{y:.2f}" x2="{bx1:.2f}" y2="{hook_y1:.2f}" {stroke}/>')
    out.append(
        f'<text x="{xmid:.2f}" y="{y:.2f}" '
        'font-family="Times New Roman,serif" font-size="8" '
        'font-style="italic" text-anchor="middle" dominant-baseline="middle">'
        f'{number}</text>'
    )
    return out


def _render_text_instance(*, text) -> list[str]:
    raw_text = str(text.text)
    metadata = text.metadata or {}
    attrs = [
        f'x="{text.x:.2f}"',
        f'y="{text.y:.2f}"',
        f'font-family="{escape(text.font_family)}"',
        f'font-size="{text.font_size:.2f}"',
    ]
    text_anchor = str(metadata.get("text_anchor", "")).strip()
    dominant_baseline = str(metadata.get("dominant_baseline", "")).strip()
    if text_anchor:
        attrs.append(f'text-anchor="{escape(text_anchor)}"')
    if dominant_baseline:
        attrs.append(f'dominant-baseline="{escape(dominant_baseline)}"')
    if metadata.get("kind") == "chord_name":
        attrs.append('class="fw-chord-name"')
        attrs.append(f'data-chord="{escape(raw_text)}"')
    if metadata.get("kind") == "note" and metadata.get("tab_string") is not None:
        attrs.append('class="fw-tab-note"')
        attrs.append(f'data-event-id="{escape(str(metadata.get("event_id", "")))}"')
        attrs.append(f'data-tab-string="{escape(str(metadata.get("tab_string", "")))}"')
        onset = metadata.get("onset")
        if onset is not None:
            try:
                onset_str = f"{float(onset):.6f}"
            except (TypeError, ValueError):
                onset_str = str(onset)
            attrs.append(f'data-onset="{escape(onset_str)}"')
    text_svg = f"<text {' '.join(attrs)}>{escape(raw_text)}</text>"

    # Keep tab digits readable by masking the line segment behind each digit.
    if metadata.get("tab_string") is not None and metadata.get("kind") == "note":
        glyph_count = max(1, len(raw_text))
        mask_w = max(7.0, text.font_size * (0.55 + 0.45 * glyph_count))
        mask_h = max(7.0, text.font_size * 0.95)
        rect = (
            f'<rect x="{(text.x - mask_w / 2.0):.2f}" y="{(text.y - mask_h / 2.0):.2f}" '
            f'width="{mask_w:.2f}" height="{mask_h:.2f}" fill="white" stroke="none" '
            'class="fw-tab-note-mask"/>'
        )
        return [rect, text_svg]
    return [text_svg]


def _render_glyph(
    glyph_id: str,
    *,
    x: float,
    y: float,
    size: float,
    metadata: dict[str, object],
) -> str:
    if glyph_id == "notehead":
        return _render_notehead_glyph(x=x, y=y, size=size, metadata=metadata)
    if glyph_id == "notehead_muted":
        return _render_notehead_muted_glyph(x=x, y=y, size=size, metadata=metadata)
    if glyph_id == "notehead_harmonic":
        # Diamond shape (◇) for harmonic notes: rotated square centered at (x, y).
        pts = (
            f"{x:.2f},{(y - 3.5):.2f} "
            f"{(x + 4.5):.2f},{y:.2f} "
            f"{x:.2f},{(y + 3.5):.2f} "
            f"{(x - 4.5):.2f},{y:.2f}"
        )
        event_id = (metadata or {}).get("event_id", "")
        return (
            f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="0.8" '
            f'class="fw-notehead-harmonic" data-event-id="{event_id}"/>'
        )
    if glyph_id == "clef":
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Bravura,Times New Roman,serif" '
            f'font-size="{max(18.0, size):.2f}" dominant-baseline="middle">'
            "𝄞</text>"
        )
    if glyph_id == "time_signature":
        numerator = int(metadata.get("numerator", 4))
        denominator = int(metadata.get("denominator", 4))
        fs = max(9.0, size)
        return (
            f'<text x="{x:.2f}" y="{(y - 4.5):.2f}" '
            f'font-family="Times New Roman" font-size="{fs:.2f}" text-anchor="middle">'
            f"{numerator}</text>"
            f'<text x="{x:.2f}" y="{(y + 5.5):.2f}" '
            f'font-family="Times New Roman" font-size="{fs:.2f}" text-anchor="middle">'
            f"{denominator}</text>"
        )
    if glyph_id == "rest":
        return _render_rest_glyph(x=x, y=y, size=size, metadata=metadata)
    if glyph_id == "accidental_sharp":
        rendered = _render_reference_path_glyph(
            reference_glyph_id="accidental_sharp",
            x=x,
            y=y,
            size=size,
            size_multiplier=1.0,
            anchor_x=0.0,
            anchor_y=0.78,
        )
        if rendered is not None:
            return rendered
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Helvetica" font-size="{max(8.0, size):.2f}">'
            "♯</text>"
        )
    if glyph_id == "accidental_flat":
        rendered = _render_reference_path_glyph(
            reference_glyph_id="accidental_flat",
            x=x,
            y=y,
            size=size,
            size_multiplier=1.0,
            anchor_x=0.0,
            anchor_y=0.78,
        )
        if rendered is not None:
            return rendered
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Helvetica" font-size="{max(8.0, size):.2f}">'
            "♭</text>"
        )
    if glyph_id == "accidental_natural":
        rendered = _render_reference_path_glyph(
            reference_glyph_id="accidental_natural",
            x=x,
            y=y,
            size=size,
            size_multiplier=1.0,
            anchor_x=0.0,
            anchor_y=0.78,
        )
        if rendered is not None:
            return rendered
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Bravura,Helvetica,serif" font-size="{max(8.0, size):.2f}">'
            "♮</text>"
        )
    if glyph_id == "accent":
        rendered = _render_reference_path_glyph(
            reference_glyph_id="accent",
            x=x,
            y=y,
            size=size,
            size_multiplier=0.42,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        if rendered is not None:
            return rendered
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Times New Roman" font-size="{max(7.0, size):.2f}">'
            "&gt;</text>"
        )
    if glyph_id == "ornament_turn":
        rendered = _render_reference_path_glyph(
            reference_glyph_id="ornament_turn",
            x=x,
            y=y,
            size=size,
            size_multiplier=0.55,
            anchor_x=0.5,
            anchor_y=0.5,
        )
        if rendered is not None:
            return rendered
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Times New Roman" font-size="{max(7.0, size):.2f}">'
            "~</text>"
        )
    if glyph_id == "repeat_barline_left":
        return _render_repeat_barline_glyph(x=x, y=y, size=size, direction="left")
    if glyph_id == "repeat_barline_right":
        return _render_repeat_barline_glyph(x=x, y=y, size=size, direction="right")
    if glyph_id == "key_sig_sharp":
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Bravura,Helvetica,serif" font-size="{max(7.0, size):.2f}" '
            f'dominant-baseline="middle">'
            "♯</text>"
        )
    if glyph_id == "key_sig_flat":
        return (
            f'<text x="{x:.2f}" y="{y:.2f}" '
            f'font-family="Bravura,Helvetica,serif" font-size="{max(7.0, size):.2f}" '
            f'dominant-baseline="middle">'
            "♭</text>"
        )
    return (
        f'<circle cx="{x:.2f}" cy="{y:.2f}" '
        f'r="{max(1.0, size):.2f}" '
        'fill="none" stroke="black"/>'
    )


def _render_notehead_muted_glyph(
    *, x: float, y: float, size: float, metadata: dict[str, object]
) -> str:
    """Render an X-shaped notehead for muted/dead notes."""
    rx = max(3.4, float(metadata.get("rx", size * 1.1)))
    ry = max(2.4, float(metadata.get("ry", size * 0.78)))
    stroke_width = max(0.8, float(metadata.get("stroke_width", 1.0)))
    return (
        f'<line x1="{x - rx:.2f}" y1="{y - ry:.2f}" '
        f'x2="{x + rx:.2f}" y2="{y + ry:.2f}" '
        f'stroke="black" stroke-width="{stroke_width:.2f}"/>'
        f'<line x1="{x + rx:.2f}" y1="{y - ry:.2f}" '
        f'x2="{x - rx:.2f}" y2="{y + ry:.2f}" '
        f'stroke="black" stroke-width="{stroke_width:.2f}"/>'
    )


def _render_notehead_glyph(
    *, x: float, y: float, size: float, metadata: dict[str, object]
) -> str:
    filled = bool(metadata.get("filled", False))
    rx = max(3.4, float(metadata.get("rx", size * 1.1)))
    ry = max(2.4, float(metadata.get("ry", size * 0.78)))
    rotation = float(metadata.get("rotation", -20.0))
    stroke_width = max(0.6, float(metadata.get("stroke_width", 0.9)))
    fill = "black" if filled else "white"
    body = (
        f'<ellipse cx="{x:.2f}" cy="{y:.2f}" rx="{rx:.2f}" ry="{ry:.2f}" '
        f'fill="{fill}" stroke="black" stroke-width="{stroke_width:.2f}" '
        f'transform="rotate({rotation:.2f} {x:.2f} {y:.2f})"/>'
    )
    dot_count = int(metadata.get("dot_count", 0) or 0)
    if dot_count <= 0:
        return body

    spacing = max(2.6, float(metadata.get("staff_spacing", 8.0)) * 0.33)
    on_line = str(metadata.get("on_staff_line", "false")).lower() == "true"
    dot_y = y - spacing * 0.45 if on_line else y
    dot_r = max(1.0, ry * 0.32)
    dots = []
    for idx in range(dot_count):
        dot_x = x + rx + 2.3 + idx * (dot_r * 2.5)
        dots.append(
            f'<circle cx="{dot_x:.2f}" cy="{dot_y:.2f}" r="{dot_r:.2f}" fill="black" stroke="none"/>'
        )
    return body + "".join(dots)


def _render_rest_glyph(
    *, x: float, y: float, size: float, metadata: dict[str, object]
) -> str:
    duration = float(metadata.get("duration", 0.5) or 0.5)
    rest_kind = str(metadata.get("rest_kind") or _duration_class(duration))
    if str(metadata.get("is_measure_rest", "")).lower() == "true":
        rest_kind = "whole"
    block_w = max(6.0, float(metadata.get("rest_block_width", 8.0)))
    block_h = max(2.0, float(metadata.get("rest_block_height", 3.0)))
    half_w = block_w / 2.0
    augmentation_dot_count = int(metadata.get("dot_count", 0) or 0)
    is_tab_rhythm = str(metadata.get("mode", "")).strip() == "tablature_rhythm"
    rect_attrs = 'stroke="black" stroke-width="1" fill="black"'
    path_attrs = 'stroke="black" stroke-width="1" fill="none" stroke-linecap="round" stroke-linejoin="round"'

    def _augmentation_dots(dot_y: float) -> str:
        if augmentation_dot_count <= 0:
            return ""
        dots: list[str] = []
        for idx in range(augmentation_dot_count):
            dot_x = x + 5.0 + idx * 2.8
            dots.append(
                f'<circle cx="{dot_x:.2f}" cy="{dot_y:.2f}" r="1.15" fill="black" stroke="none"/>'
            )
        return "".join(dots)

    vector_rest = _REST_KIND_TO_REFERENCE_GLYPH.get(rest_kind)
    if vector_rest is not None:
        rendered = _render_reference_path_glyph(
            reference_glyph_id=vector_rest,
            x=x,
            y=y,
            size=size,
            size_multiplier=1.2 if is_tab_rhythm else (1.15 if rest_kind == "quarter" else 1.0),
            anchor_x=0.5,
            anchor_y=0.5,
        )
        if rendered is not None:
            return rendered + _augmentation_dots(y + 0.5)

    if rest_kind == "whole":
        return (
            f'<line x1="{x - 5.5:.2f}" y1="{y:.2f}" x2="{x + 5.5:.2f}" y2="{y:.2f}" '
            'stroke="black" stroke-width="0.7"/>'
            f'<rect x="{x - half_w:.2f}" y="{y + 0.2:.2f}" '
            f'width="{block_w:.2f}" height="{block_h:.2f}" {rect_attrs}/>'
            + _augmentation_dots(y + 1.2)
        )
    if rest_kind == "half":
        return (
            f'<line x1="{x - 5.5:.2f}" y1="{y:.2f}" x2="{x + 5.5:.2f}" y2="{y:.2f}" '
            'stroke="black" stroke-width="0.7"/>'
            f'<rect x="{x - half_w:.2f}" y="{y - block_h + 0.1:.2f}" '
            f'width="{block_w:.2f}" height="{block_h:.2f}" {rect_attrs}/>'
            + _augmentation_dots(y + 0.5)
        )
    if rest_kind == "quarter":
        return (
            f'<path d="M{x - 2.0:.2f},{y + 4.0:.2f} '
            f'L{x + 2.5:.2f},{y + 1.5:.2f} '
            f'C{x + 4.0:.2f},{y + 0.5:.2f} {x - 3.5:.2f},{y - 2.0:.2f} {x + 0.5:.2f},{y - 3.0:.2f} '
            f'C{x + 2.5:.2f},{y - 4.0:.2f} {x - 1.0:.2f},{y + 5.5:.2f} {x + 0.5:.2f},{y + 7.0:.2f}" '
            f'{path_attrs}/>'
            + _augmentation_dots(y + 0.5)
        )

    intrinsic_dot_count = {
        "eighth": 1,
        "sixteenth": 2,
        "thirty_second": 3,
        "sixty_fourth": 4,
    }.get(rest_kind, 1)
    dots: list[str] = []
    for idx in range(intrinsic_dot_count):
        dot_x = x - 1.0 - idx * 0.8
        dot_y = y - 3.0 + idx * 2.8
        dots.append(
            f'<circle cx="{dot_x:.2f}" cy="{dot_y:.2f}" r="1.25" fill="black" stroke="none"/>'
        )
    return (
        f'<line x1="{x - 1.5:.2f}" y1="{y + 4.0:.2f}" '
        f'x2="{x + 2.0:.2f}" y2="{y - 3.8:.2f}" '
        'stroke="black" stroke-width="0.8"/>'
        + "".join(dots)
        + _augmentation_dots(y + 0.8)
    )


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


def _render_reference_path_glyph(
    *,
    reference_glyph_id: str,
    x: float,
    y: float,
    size: float,
    size_multiplier: float,
    anchor_x: float,
    anchor_y: float,
) -> str | None:
    reference_glyph = _REFERENCE_GLYPHS.get(reference_glyph_id)
    if reference_glyph is None:
        return None
    if reference_glyph.svg_path_data is None or reference_glyph.svg_view_box is None:
        return None

    _, _, view_box_w, view_box_h = reference_glyph.svg_view_box
    if view_box_w <= 0.0 or view_box_h <= 0.0:
        return None

    draw_h = max(0.5, size * size_multiplier)
    scale = draw_h / view_box_h
    draw_w = view_box_w * scale
    origin_x = x - draw_w * anchor_x
    origin_y = y - draw_h * anchor_y

    path_transform = ""
    if reference_glyph.svg_path_transform:
        path_transform = f' transform="{reference_glyph.svg_path_transform}"'

    return (
        f'<g transform="translate({origin_x:.4f},{origin_y:.4f}) scale({scale:.6f})">'
        f'<path d="{reference_glyph.svg_path_data}"{path_transform} fill="currentColor"/>'
        "</g>"
    )


def _render_repeat_barline_glyph(*, x: float, y: float, size: float, direction: str) -> str:
    draw_h = max(8.0, size)
    scale = draw_h / _REPEAT_BARLINE_VIEWBOX_H
    draw_w = _REPEAT_BARLINE_VIEWBOX_W * scale
    origin_x = x - draw_w * 0.5
    origin_y = y - draw_h * 0.5

    left_primitives = (
        '<rect x="0" y="1.332" width="0.60000002" height="4" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_HOOK_UP_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,0,1.332)" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_HOOK_DOWN_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,0,5.332)" fill="currentColor"/>'
        '<rect x="0.9" y="1.332" width="0.19" height="4" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_DOT_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,1.39,1.832)" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_DOT_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,1.39,2.832)" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_DOT_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,1.39,3.832)" fill="currentColor"/>'
        f'<path d="{_REPEAT_BARLINE_DOT_PATH}" '
        'transform="matrix(0.004,0,0,-0.004,1.39,4.832)" fill="currentColor"/>'
    )

    if direction == "right":
        return (
            f'<g transform="translate({origin_x:.4f},{origin_y:.4f}) scale({scale:.6f}) '
            f'translate({_REPEAT_BARLINE_VIEWBOX_W:.4f},0) scale(-1,1)">'
            f"{left_primitives}"
            "</g>"
        )
    return (
        f'<g transform="translate({origin_x:.4f},{origin_y:.4f}) scale({scale:.6f})">'
        f"{left_primitives}"
        "</g>"
    )
