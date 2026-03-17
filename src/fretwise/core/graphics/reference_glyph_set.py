"""Reference glyph set declarations for stable notation symbols."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ReferenceGlyph:
    """Stable glyph metadata."""

    glyph_id: str
    unicode_char: str
    bbox: tuple[float, float, float, float]
    anchors: dict[str, tuple[float, float]] = field(default_factory=dict)


def default_reference_glyph_set() -> dict[str, ReferenceGlyph]:
    """Return the default stable glyph inventory."""
    return {
        "clef_treble": ReferenceGlyph(
            glyph_id="clef_treble",
            unicode_char="\U0001D11E",
            bbox=(0.0, -8.0, 10.0, 28.0),
            anchors={"staff_line_g": (5.0, 12.0)},
        ),
        "rest_quarter": ReferenceGlyph(
            glyph_id="rest_quarter",
            unicode_char="\U0001D13D",
            bbox=(0.0, -6.0, 6.0, 14.0),
            anchors={"center": (3.0, 4.0)},
        ),
        "accidental_sharp": ReferenceGlyph(
            glyph_id="accidental_sharp",
            unicode_char="\u266F",
            bbox=(0.0, -4.0, 6.0, 10.0),
            anchors={"note_center": (5.0, 2.0)},
        ),
        "accidental_flat": ReferenceGlyph(
            glyph_id="accidental_flat",
            unicode_char="\u266D",
            bbox=(0.0, -6.0, 5.0, 10.0),
            anchors={"note_center": (4.0, 2.0)},
        ),
        "time_sig_4": ReferenceGlyph(
            glyph_id="time_sig_4",
            unicode_char="4",
            bbox=(0.0, -1.0, 5.0, 8.0),
            anchors={"baseline": (0.0, 0.0)},
        ),
        "tab_digit_0": ReferenceGlyph(
            glyph_id="tab_digit_0",
            unicode_char="0",
            bbox=(0.0, -1.0, 5.0, 7.0),
            anchors={"baseline": (0.0, 0.0), "center": (2.5, 3.0)},
        ),
    }

