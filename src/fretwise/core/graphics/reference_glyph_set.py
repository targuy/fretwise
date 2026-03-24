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
    svg_path_data: str | None = None
    svg_path_transform: str | None = None
    svg_view_box: tuple[float, float, float, float] | None = None


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
            svg_path_data=(
                "m 0,1009.0468 -12.09375,43.3125 -4.640625,0 9.0703125,-32.5547 "
                "c -3.9843925,1.9688 -7.1718895,2.9531 -9.5624995,2.9532 "
                "-2.43751,-10e-5 -4.687508,-0.8672 -6.75,-2.6016 "
                "-2.015629,-1.7344 -3.02344,-3.8203 -3.023438,-6.2578 "
                "-2e-6,-2.0625 0.726559,-3.8203 2.179688,-5.2735 "
                "1.453118,-1.4531 3.210929,-2.1796 5.273437,-2.1796 "
                "2.062488,0 3.820299,0.7265 5.273437,2.1796 "
                "1.453109,1.4532 2.179671,3.211 2.179688,5.2735 "
                "-1.7e-5,1.2187 -0.281267,2.3672 -0.84375,3.4453 "
                "0.234358,0.1875 0.445296,0.2812 0.632812,0.2812 "
                "1.359357,0 3.1406053,-1.125 5.3437505,-3.375 "
                "1.7812258,-1.7812 3.1874744,-3.5156 4.21875,-5.2031 l 2.7421875,0"
            ),
            svg_path_transform="matrix(-1,0,0,1,0,-1006.4394)",
            svg_view_box=(0.0, 0.0, 27.0, 45.919998),
        ),
        "rest_whole": ReferenceGlyph(
            glyph_id="rest_whole",
            unicode_char="\U0001D13B",
            bbox=(0.0, -3.0, 8.0, 3.0),
            anchors={"staff_line": (4.0, 0.0)},
        ),
        "rest_half": ReferenceGlyph(
            glyph_id="rest_half",
            unicode_char="\U0001D13C",
            bbox=(0.0, -3.0, 8.0, 3.0),
            anchors={"staff_line": (4.0, 0.0)},
        ),
        "rest_eighth": ReferenceGlyph(
            glyph_id="rest_eighth",
            unicode_char="\U0001D13E",
            bbox=(0.0, -7.0, 5.0, 7.0),
            anchors={"center": (2.0, 0.0)},
            svg_path_data=(
                "M 72,-250 189,76 C 155,64 120,54 84,54 38,54 -3,87 -3,133 "
                "c 0,40 33,72 73,72 25,0 48,-15 56,-39 10,-28 6,-59 35,-59 "
                "16,0 54,48 61,63 6,12 23,12 28,0 L 127,-250 "
                "c -8,-7 -17,-10 -27,-10 -10,0 -20,3 -28,10 z"
            ),
            svg_path_transform="matrix(0.004,0,0,-0.004,0.012,0.82)",
            svg_view_box=(0.0, 0.0, 1.012, 1.86),
        ),
        "rest_sixteenth": ReferenceGlyph(
            glyph_id="rest_sixteenth",
            unicode_char="\U0001D13F",
            bbox=(0.0, -8.0, 5.0, 8.0),
            anchors={"center": (2.0, 0.0)},
        ),
        "rest_thirty_second": ReferenceGlyph(
            glyph_id="rest_thirty_second",
            unicode_char="\U0001D140",
            bbox=(0.0, -9.0, 5.0, 9.0),
            anchors={"center": (2.0, 0.0)},
            svg_path_data=(
                "m 54,-500 86,327 c -35,-13 -71,-23 -108,-23 -46,0 -87,33 -87,79 "
                "0,40 32,72 72,72 25,0 49,-15 57,-39 10,-28 5,-59 34,-59 "
                "17,0 54,54 59,71 L 206,77 C 172,65 136,54 100,54 54,54 13,87 13,133 "
                "c 0,40 33,72 73,72 25,0 48,-15 56,-39 10,-28 5,-59 34,-59 "
                "16,0 52,51 56,68 l 40,151 c -33,-12 -68,-22 -103,-22 -46,0 -87,33 -87,79 "
                "0,40 32,72 72,72 25,0 49,-15 57,-39 10,-28 5,-59 34,-59 "
                "15,0 46,49 52,63 6,12 23,12 28,0 L 109,-500 "
                "c -8,-7 -18,-10 -28,-10 -10,0 -19,3 -27,10 z"
            ),
            svg_path_transform="matrix(0.004,0,0,-0.004,0.22,1.82)",
            svg_view_box=(0.0, 0.0, 1.52, 3.86),
        ),
        "rest_sixty_fourth": ReferenceGlyph(
            glyph_id="rest_sixty_fourth",
            unicode_char="\U0001D141",
            bbox=(0.0, -10.0, 5.0, 10.0),
            anchors={"center": (2.0, 0.0)},
        ),
        "notehead_open": ReferenceGlyph(
            glyph_id="notehead_open",
            unicode_char="\U0001D15D",
            bbox=(-4.5, -3.2, 4.5, 3.2),
            anchors={"center": (0.0, 0.0), "stem_up": (4.5, 0.0), "stem_down": (-4.5, 0.0)},
        ),
        "notehead_filled": ReferenceGlyph(
            glyph_id="notehead_filled",
            unicode_char="\U0001D158",
            bbox=(-4.5, -3.2, 4.5, 3.2),
            anchors={"center": (0.0, 0.0), "stem_up": (4.5, 0.0), "stem_down": (-4.5, 0.0)},
        ),
        "notehead_muted": ReferenceGlyph(
            glyph_id="notehead_muted",
            unicode_char="\u00D7",
            bbox=(-3.5, -3.5, 3.5, 3.5),
            anchors={"center": (0.0, 0.0), "stem_up": (3.5, 0.0), "stem_down": (-3.5, 0.0)},
        ),
        "accidental_sharp": ReferenceGlyph(
            glyph_id="accidental_sharp",
            unicode_char="\u266F",
            bbox=(0.0, -4.0, 6.0, 10.0),
            anchors={"note_center": (5.0, 2.0)},
            svg_path_data=(
                "m 216,-312 c 0,-10 -8,-19 -18,-19 -10,0 -19,9 -19,19 v 145 l -83,-31 "
                "v -158 c 0,-10 -9,-19 -19,-19 -10,0 -18,9 -18,19 v 145 l -32,-12 "
                "c -2,-1 -5,-1 -7,-1 -11,0 -20,9 -20,20 v 60 c 0,8 5,16 13,19 l 46,16 "
                "V 51 L 27,40 C 25,39 22,39 20,39 9,39 0,48 0,59 v 60 c 0,8 5,15 13,18 "
                "l 46,17 v 158 c 0,10 8,19 18,19 10,0 19,-9 19,-19 V 167 l 83,31 v 158 "
                "c 0,10 9,19 19,19 10,0 18,-9 18,-19 V 211 l 32,12 c 2,1 5,1 7,1 "
                "11,0 20,-9 20,-20 v -60 c 0,-8 -5,-16 -13,-19 L 216,109 V -51 l 32,11 "
                "c 2,1 5,1 7,1 11,0 20,-9 20,-20 v -60 c 0,-8 -5,-15 -13,-18 l -46,-17 "
                "V -312 z M 96,65 V -95 l 83,30 V 95 z"
            ),
            svg_path_transform="matrix(0.004,0,0,-0.004,0,1.5)",
            svg_view_box=(0.0, 0.0, 1.1, 3.0000001),
        ),
        "accidental_flat": ReferenceGlyph(
            glyph_id="accidental_flat",
            unicode_char="\u266D",
            bbox=(0.0, -6.0, 5.0, 10.0),
            anchors={"note_center": (4.0, 2.0)},
            svg_path_data=(
                "m 27,41 -1,-66 v -11 c 0,-22 1,-44 4,-66 45,38 93,80 93,139 "
                "0,33 -14,67 -43,67 C 49,104 28,74 27,41 z m -42,-179 -12,595 c 8,5 18,8 27,8 "
                "9,0 19,-3 27,-8 L 20,112 c 25,21 58,34 91,34 52,0 89,-48 89,-102 "
                "0,-80 -86,-117 -147,-169 -15,-13 -24,-38 -45,-38 -13,0 -23,11 -23,25 z"
            ),
            svg_path_transform="matrix(0.004,0,0,-0.004,0.108,1.86)",
            svg_view_box=(0.0, 0.0, 0.90800003, 2.5119999),
        ),
        "accidental_natural": ReferenceGlyph(
            glyph_id="accidental_natural",
            unicode_char="\u266E",
            bbox=(0.0, -5.0, 5.0, 10.0),
            anchors={"note_center": (4.0, 2.0)},
            svg_path_data=(
                "m -8,375 c 8,4 17,7 26,7 9,0 17,-3 25,-7 l -3,-183 106,20 h 3 "
                "c 10,0 18,-7 18,-17 l 7,-570 c -8,-4 -16,-7 -25,-7 -9,0 -17,3 -25,7 "
                "l 3,183 -106,-20 h -3 c -10,0 -18,7 -18,17 z M 131,112 39,95 l -3,-207 92,17 z"
            ),
            svg_path_transform="matrix(0.004,0,0,-0.004,0.032,1.528)",
            svg_view_box=(0.0, 0.0, 0.72799996, 3.056),
        ),
        "key_sig_sharp": ReferenceGlyph(
            glyph_id="key_sig_sharp",
            unicode_char="\u266F",
            bbox=(0.0, -4.0, 6.0, 8.0),
            anchors={"center": (3.0, 2.0)},
        ),
        "key_sig_flat": ReferenceGlyph(
            glyph_id="key_sig_flat",
            unicode_char="\u266D",
            bbox=(0.0, -5.0, 5.0, 8.0),
            anchors={"center": (2.5, 1.5)},
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
        "accent": ReferenceGlyph(
            glyph_id="accent",
            unicode_char=">",
            bbox=(0.0, 0.0, 1.8, 1.0),
            anchors={"center": (0.9, 0.5)},
            svg_path_data=(
                "M 0.056,0.148 C 0.024,0.14 0,0.112 0,0.076 0,0.036 0.036,0 0.076,0 "
                "0.084,0 0.088,0.004 0.092,0.004 l 1.632,0.42 C 1.776,0.424 1.8,0.448 1.8,0.5 "
                "1.8,0.552 1.776,0.576 1.724,0.576 L 0.092,0.996 C 0.088,0.996 0.084,1 0.076,1 "
                "0.036,1 0,0.964 0,0.924 0,0.888 0.024,0.86 0.056,0.852 L 1.06,0.592 1.62,0.5 "
                "1.06,0.408 Z"
            ),
            svg_view_box=(0.0, 0.0, 1.8000001, 1.0),
        ),
        "ornament_turn": ReferenceGlyph(
            glyph_id="ornament_turn",
            unicode_char="~",
            bbox=(0.0, 0.0, 2.184, 1.056),
            anchors={"center": (1.092, 0.528)},
            svg_path_data=(
                "m 1.648,1.056 c -0.26,0 -0.468,-0.18000004 -0.656,-0.35600004 "
                "-0.188,-0.176 -0.372,-0.388 -0.628,-0.388 -0.132,0 -0.244,0.092 -0.244,0.216 "
                "0,0.124 0.092,0.212 0.2,0.228 0.036,-0.084 0.112,-0.124 0.192,-0.124 "
                "0.104,0 0.216,0.072 0.216,0.212 C 0.728,0.97199996 0.596,1.056 0.456,1.056 "
                "0.188,1.056 0,0.80799996 0,0.52799996 0,0.23199996 0.24,-3.8290034e-8 "
                "0.536,-3.8290034e-8 0.796,-3.8290034e-8 1.004,0.17999996 1.192,0.35599996 "
                "c 0.188,0.176 0.372,0.388 0.628,0.388 0.132,0 0.244,-0.092 0.244,-0.216 "
                "0,-0.124 -0.092,-0.212 -0.2,-0.228 -0.036,0.084 -0.112,0.124 -0.192,0.124 "
                "-0.104,0 -0.216,-0.072 -0.216,-0.212 C 1.456,0.08399996 1.588,-3.8290034e-8 "
                "1.728,-3.8290034e-8 1.996,-3.8290034e-8 2.184,0.24799996 2.184,0.52799996 "
                "2.184,0.82399996 1.944,1.056 1.648,1.056 Z"
            ),
            svg_view_box=(0.0, 0.0, 2.1839998, 1.0559999),
        ),
    }
