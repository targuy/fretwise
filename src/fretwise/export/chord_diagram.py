"""Chord diagram box renderer.

Draws standard guitar chord box diagrams:
- 6 vertical lines (strings), string 1 (high e) on the right
- N horizontal lines (frets), typically 5
- X above top = muted string,  O above top = open string
- Open circle with finger number inside = fretted position
  (1=index, 2=middle, 3=ring, 4=pinky;  0 or absent → plain dot)
- Barre: filled rounded bar across strings sharing the same (minimum) fret
  with the finger number centred on it
- Thick top bar = nut (when base_fret == 0)
- Roman numeral to right of diagram = fret position (when base_fret > 0)
- Chord name above diagram in bold

String ordering in diagram (left to right): string 6 (low E) ... string 1 (high e)
This is the standard "facing the guitarist" orientation.
"""

from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfgen import canvas

from fretwise.models import ChordDiagram

# ---------------------------------------------------------------------------
# Roman numeral helper
# ---------------------------------------------------------------------------

_ROMAN: list[tuple[int, str]] = [
    (10, "X"), (9, "IX"), (8, "VIII"), (7, "VII"), (6, "VI"),
    (5, "V"), (4, "IV"), (3, "III"), (2, "II"), (1, "I"),
]


def _to_roman(n: int) -> str:
    """Convert a positive integer to a Roman numeral string (I–XXIV)."""
    if n <= 0:
        return str(n)
    result = ""
    for val, numeral in _ROMAN:
        while n >= val:
            result += numeral
            n -= val
    return result


# ---------------------------------------------------------------------------
# Single diagram renderer
# ---------------------------------------------------------------------------


def draw_chord_diagram(
    c: canvas.Canvas,
    diagram: ChordDiagram,
    x: float,
    y: float,
    cell_w: float = 9.0,
    cell_h: float = 9.0,
    fret_rows: int = 5,
) -> tuple[float, float]:
    """Draw one chord diagram.

    The coordinate origin is the top-left corner of the fret box.
    ReportLab y increases upward, so y is the TOP of the box.

    Args:
        c: ReportLab Canvas.
        diagram: ChordDiagram data to render.
        x: Left edge of the diagram box (pt).
        y: Top edge of the diagram box (pt).
        cell_w: Horizontal spacing between adjacent string lines (pt).
        cell_h: Vertical spacing between adjacent fret lines (pt).
        fret_rows: Number of fret rows to draw (default 5).

    Returns:
        (total_width, total_height) of the rendered area including name and markers.
    """
    n_strings = diagram.string_count
    box_w = (n_strings - 1) * cell_w
    box_h = fret_rows * cell_h

    # ----- String x positions --------------------------------------------------
    # Left = string 6 (low E), Right = string 1 (high e).
    # Our frets list index 0 = string 1 (high e) = rightmost.
    def str_x(s_idx: int) -> float:
        """x position for string index s_idx (0=high e → rightmost)."""
        return x + (n_strings - 1 - s_idx) * cell_w

    # ----- Chord name above diagram -------------------------------------------
    name_offset = 12.0
    c.setFont("Helvetica-Bold", 8.0)
    c.setFillColor(colors.black)
    c.drawCentredString(x + box_w / 2, y + name_offset, diagram.name)

    # ----- Nut (thick bar at top for open-position chords) -------------------
    # base_fret <= 1 means open position (fret 1 = first fret, no capo/position shift).
    if diagram.base_fret <= 1:
        c.setFillColor(colors.black)
        c.rect(x, y - 1.5, box_w, 1.5, fill=1, stroke=0)
    else:
        # Barre/position chord: show fret number to the right instead of a nut.
        c.setFont("Helvetica", 6.0)
        c.setFillColor(colors.black)
        label = _to_roman(diagram.base_fret) + "fr"
        c.drawString(x + box_w + 3.0, y - cell_h / 2 - 2.0, label)

    # ----- Grid: vertical string lines ----------------------------------------
    c.setStrokeColor(colors.black)
    c.setLineWidth(0.5)
    for s_idx in range(n_strings):
        sx = str_x(s_idx)
        c.line(sx, y, sx, y - box_h)

    # ----- Grid: horizontal fret lines ----------------------------------------
    for f in range(fret_rows + 1):
        fy = y - f * cell_h
        c.line(x, fy, x + box_w, fy)

    # ----- Mute (X) and open (O) markers above the diagram --------------------
    marker_y = y + 3.0
    c.setFont("Helvetica", 6.0)
    for s_idx, fret_val in enumerate(diagram.frets):
        sx = str_x(s_idx)
        if fret_val == -1:
            c.setFillColor(colors.black)
            c.drawCentredString(sx, marker_y, "×")
        elif fret_val == 0:
            c.setFillColor(colors.black)
            c.drawCentredString(sx, marker_y, "○")

    # ----- Barre detection: strings sharing the lowest fret value get a bar -----
    dot_r = 2.5
    fretted = [(s_idx, fv) for s_idx, fv in enumerate(diagram.frets) if fv > 0]
    barre_fret: int | None = None
    barre_strings: list[int] = []
    if len(fretted) >= 2:
        min_fret = min(fv for _, fv in fretted)
        barre_strings = [s_idx for s_idx, fv in fretted if fv == min_fret]
        if len(barre_strings) >= 2:
            barre_fret = min_fret

    if barre_fret is not None:
        barre_row = barre_fret - max(diagram.base_fret, 1)
        if 0 <= barre_row < fret_rows:
            barre_y = y - barre_row * cell_h - cell_h / 2
            # x positions: str_x returns rightmost for s_idx=0
            xs = sorted(str_x(s) for s in barre_strings)
            bx0, bx1 = xs[0], xs[-1]
            barre_w = bx1 - bx0
            c.setFillColor(colors.black)
            c.roundRect(bx0 - dot_r, barre_y - dot_r, barre_w + 2 * dot_r,
                        2 * dot_r, dot_r, fill=1, stroke=0)
            # Finger number on the barre
            barre_finger = diagram.fingers[barre_strings[0]] if diagram.fingers else 0
            if barre_finger:
                c.setFillColor(colors.white)
                c.setFont("Helvetica-Bold", dot_r * 1.6)
                c.drawCentredString((bx0 + bx1) / 2, barre_y - dot_r * 0.55,
                                    str(barre_finger))
            c.setFillColor(colors.black)

    # ----- Fret dots: open circle with finger number --------------------------
    barre_set = set(barre_strings)
    for s_idx, fret_val in enumerate(diagram.frets):
        if fret_val <= 0 or s_idx in barre_set:
            continue
        row = fret_val - max(diagram.base_fret, 1)
        if row < 0 or row >= fret_rows:
            continue
        sx = str_x(s_idx)
        dot_y = y - row * cell_h - cell_h / 2
        # Open circle (white fill, black stroke)
        c.setFillColor(colors.white)
        c.setStrokeColor(colors.black)
        c.setLineWidth(0.8)
        c.circle(sx, dot_y, dot_r, fill=1, stroke=1)
        # Finger number inside
        finger_num = diagram.fingers[s_idx] if diagram.fingers else 0
        if finger_num:
            c.setFillColor(colors.black)
            c.setFont("Helvetica-Bold", dot_r * 1.6)
            c.drawCentredString(sx, dot_y - dot_r * 0.55, str(finger_num))
        c.setStrokeColor(colors.black)
        c.setFillColor(colors.black)

    # Total dimensions: width includes some right margin for base fret label.
    right_margin = 20.0 if diagram.base_fret > 0 else 0.0
    total_w = box_w + right_margin
    # Height: name + marker zone + box.
    total_h = name_offset + 4.0 + box_h + 2.0
    return total_w, total_h


# ---------------------------------------------------------------------------
# Standalone PDF of all diagrams
# ---------------------------------------------------------------------------


def render_chord_diagrams_pdf(
    diagrams: list[ChordDiagram],
    output_path: Path,
    title: str = "Chord Diagrams",
    cols: int = 6,
    cell_w: float = 9.0,
    cell_h: float = 9.0,
) -> None:
    """Render all chord diagrams to a standalone A4 PDF.

    Args:
        diagrams: List of ChordDiagram objects to render.
        output_path: Destination PDF file path (created or overwritten).
        title: Page title shown at the top of the first page.
        cols: Number of diagrams per row.
        cell_w: Width between adjacent string lines in each diagram (pt).
        cell_h: Height between adjacent fret lines in each diagram (pt).
    """
    PAGE_W, PAGE_H = 595.0, 842.0
    MARGIN = 28.0
    FRET_ROWS = 5

    c = canvas.Canvas(str(output_path), pagesize=(PAGE_W, PAGE_H))

    # Compute slot dimensions.
    usable_w = PAGE_W - 2 * MARGIN
    slot_w = usable_w / cols
    # Height of one diagram: name(12) + marker(7) + box(fret_rows*cell_h) + pad(6)
    slot_h = 12.0 + 7.0 + FRET_ROWS * cell_h + 6.0

    y = PAGE_H - MARGIN

    # Title
    if title:
        c.setFont("Helvetica-Bold", 14)
        c.setFillColor(colors.black)
        c.drawString(MARGIN, y - 14, title)
        y -= 24.0

    if not diagrams:
        c.save()
        return

    for idx, diagram in enumerate(diagrams):
        col = idx % cols
        if col == 0 and idx > 0:
            y -= slot_h
        if y - slot_h < MARGIN:
            c.showPage()
            y = PAGE_H - MARGIN

        dx = MARGIN + col * slot_w + (slot_w - (diagram.string_count - 1) * cell_w) / 2
        dy = y - 12.0  # top of box (y of box top)

        draw_chord_diagram(c, diagram, dx, dy, cell_w=cell_w, cell_h=cell_h, fret_rows=FRET_ROWS)

    c.save()
