"""Smoke tests for the dedicated 3D-hand tab wiring (FastAPI TestClient).

The hand-viz feature is purely client-side: the "3D" view-segment button
(data-mode="hand_3d") shows an iframe (#hand3d-view-frame) pointing at the
committed renderer ``/static/hand_viz.html?view=3d``. That renderer defaults
to the 3D rig but also carries its own internal 2D/3D toggle (#btn-3d,
unhidden in dedicated mode) so the tab can fall back to the SVG rendering
that used to live in the removed floating panel. There is no HTTP endpoint
to hit, so these guards assert that (1) the app serves the renderer and the
static shell, and (2) the shell + JS still carry the iframe wiring described
by the milestone. Mirrors the review-panel smoke test in ``test_web_review.py``.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.web.app import create_app

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(fixtures_dir=tmp_path))


def test_hand_viz_renderer_is_served(client: TestClient) -> None:
    """The iframe target /static/hand_viz.html loads as HTML."""
    res = client.get("/static/hand_viz.html")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
    # SAMEORIGIN lets our own shell frame the renderer (clickjacking guard).
    assert res.headers.get("X-Frame-Options") == "SAMEORIGIN"


def test_index_shell_carries_hand3d_iframe() -> None:
    """The dedicated 3D tab's iframe, pointing at the committed renderer, is present."""
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    assert 'id="hand3d-view-frame"' in html
    assert 'data-src="/static/hand_viz.html?view=3d"' in html
    # The floating panel this replaced must be gone.
    assert 'id="hand-viz-panel"' not in html
    assert 'id="btn-hand-viz"' not in html


def test_main_js_wires_hand3d_iframe() -> None:
    """main.js resolves the hand3d iframe and shows/hides it with the view mode."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "$('#hand3d-view-frame')" in js
    assert "function _isHand3dViewVisible()" in js
    assert "function _ensureHand3dViewFrame()" in js
    # The floating-panel toggle this replaced must be gone.
    assert "_toggleHandViz" not in js
    assert "handVizPanel" not in js


def test_hand_viz_renderer_carries_dedicated_2d_toggle() -> None:
    """hand_viz.html exposes #btn-3d (unhidden in dedicated mode) as the 2D fallback."""
    html = (_STATIC_DIR / "hand_viz.html").read_text(encoding="utf-8")
    assert 'id="btn-3d"' in html
    # Dedicated-mode CSS must NOT hide the toggle (it did before this milestone).
    assert "body.dedicated-3d #btn-3d" not in html


def test_renderer_file_committed_and_nonempty() -> None:
    """The hand_viz.html renderer exists on disk (the iframe target)."""
    renderer = _STATIC_DIR / "hand_viz.html"
    assert renderer.is_file()
    assert renderer.stat().st_size > 0
