"""Smoke tests for the fretboard hand-viz panel wiring (FastAPI TestClient).

The hand-viz feature is purely client-side: a toolbar button (#btn-hand-viz)
toggles a floating panel (#hand-viz-panel) whose iframe (#hand-viz-frame) loads
the committed renderer ``/static/hand_viz.html``. There is no HTTP endpoint to
hit, so these guards assert that (1) the app serves the renderer and the static
shell, and (2) the shell + JS still carry the toggle wiring described by the
milestone. Mirrors the review-panel smoke test in ``test_web_review.py``.
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


def test_index_shell_carries_hand_viz_button_and_panel(client: TestClient) -> None:
    """The toolbar button, the panel, and the iframe wiring are present."""
    res = client.get("/static/index.html")
    assert res.status_code == 200
    html = res.text
    # Toggle button (index.html:323).
    assert 'id="btn-hand-viz"' in html
    # Floating panel the button reveals (index.html:410).
    assert 'id="hand-viz-panel"' in html
    # Iframe inside the panel, pointing at the committed renderer (index.html:419).
    assert 'id="hand-viz-frame"' in html
    assert 'src="/static/hand_viz.html"' in html


def test_main_js_toggles_panel_on_button_click(client: TestClient) -> None:
    """main.js binds #btn-hand-viz to a toggle that shows/hides the panel."""
    res = client.get("/static/js/main.js")
    assert res.status_code == 200
    js = res.text
    # Elements are resolved.
    assert "$('#btn-hand-viz')" in js
    assert "$('#hand-viz-panel')" in js
    assert "$('#hand-viz-frame')" in js
    # Click handler wired to the toggle.
    assert "btnHandViz.addEventListener('click', _toggleHandViz)" in js
    # The toggle flips the panel between hidden and shown.
    assert "function _toggleHandViz()" in js
    assert "handVizPanel.style.display = visible ? 'none' : 'flex'" in js


def test_renderer_file_committed_and_nonempty() -> None:
    """The hand_viz.html renderer exists on disk (the iframe target)."""
    renderer = _STATIC_DIR / "hand_viz.html"
    assert renderer.is_file()
    assert renderer.stat().st_size > 0
