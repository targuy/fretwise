"""Smoke tests for the dedicated 3D-hand tab wiring (FastAPI TestClient).

The hand-viz feature is purely client-side: the "3D" view-segment button
(data-mode="hand_3d") shows an iframe (#hand3d-view-frame) pointing at the
committed renderer ``/static/hand_viz.html?view=3d``. That renderer boots the
single HandPerformance implementation. Schematic SVG remains automatic
failure fallback, never a user-selectable mode. These guards assert static
serving, iframe wiring, and absence of historical controls.
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


def test_main_js_freezes_selected_view_while_recalculating() -> None:
    """A 3D solve must not flash the stale 2D canvas during reload."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    assert "function _prepareRepresentationLoading(mode)" in js
    assert "_prepareRepresentationLoading(getSelectedRepresentationMode());" in js
    assert "if (tabCanvas) tabCanvas.style.display = 'none';" in js
    assert "hand3dViewFrame.style.display = showHand3d ? 'block' : 'none';" in js


def test_hand_viz_renderer_carries_top_projection_control_only() -> None:
    """Dedicated view exposes top projection, not legacy hand/2D selectors."""
    html = (_STATIC_DIR / "hand_viz.html").read_text(encoding="utf-8")
    assert 'id="btn-top-view"' in html
    assert "Vue dessus" in html
    assert 'id="btn-3d"' not in html
    assert 'id="hand-engine"' not in html
    assert "Historique" not in html


def test_renderer_file_committed_and_nonempty() -> None:
    """The hand_viz.html renderer exists on disk (the iframe target)."""
    renderer = _STATIC_DIR / "hand_viz.html"
    assert renderer.is_file()
    assert renderer.stat().st_size > 0
