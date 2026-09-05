"""Regression guards for next-note preview shared by 2D and 3D hand views."""
from __future__ import annotations

from pathlib import Path

_HAND_VIZ = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "hand_viz.html"


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
