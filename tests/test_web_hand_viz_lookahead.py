"""Regression guards for next-note preview shared by 2D and 3D hand views."""
from __future__ import annotations

from pathlib import Path

_HAND_VIZ = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "hand_viz.html"
_MAIN_JS = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "main.js"


def test_lookahead_is_outside_the_animation_surface() -> None:
    """Preview strip must not overlay the SVG or the Three.js canvas."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert '<section id="hand-lookahead"' in html
    assert html.index('<section id="hand-lookahead"') < html.index('<div id="scene-wrap">')
    assert "body.dedicated-3d #hand-lookahead" in html


def test_lookahead_uses_shared_frame_payload_for_both_renderers() -> None:
    """Upcoming notes derive from the existing message payload, not a second feed."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert "function buildLookaheadGroups(frames)" in html
    installation = "CURRENT_LOOKAHEAD_GROUPS = (data && data.frames) ? "
    installation += "buildLookaheadGroups(data.frames) : [];"
    assert installation in html
    assert "updateLookahead(tNow, CURRENT_LOOKAHEAD_GROUPS);" in html
    assert "lookahead-dot" in html


def test_lookahead_preserves_dead_note_x_from_the_shared_payload() -> None:
    """Muted occurrences stay X rather than becoming open or absent slots."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    main_js = _MAIN_JS.read_text(encoding="utf-8")
    builder = main_js[main_js.index("function _buildHandVizPayload"):]
    builder = builder[: builder.index("\nfunction _postHandVizData")]

    assert "muted: Boolean(r.muted)" in builder
    assert 'muted ? " muted"' in html
    assert 'muted ? "X"' in html
    assert ".lookahead-dot.muted" in html
