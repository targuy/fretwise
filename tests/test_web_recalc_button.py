"""Smoke tests for the per-track "Recalculate fingering" button.

The recalc feature is purely client-side: a toolbar button (#btn-recalc) in
the song-page action group re-runs the existing solve plumbing for the current
track (drop the cached solve, re-call ``selectTrack``) and shows a busy/spinner
state while the optimizer runs. There is no new HTTP endpoint, so these guards
assert that the static shell + JS carry the button and its wiring. Mirrors the
hand-viz smoke test in ``test_web_hand_viz.py``.
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


def test_index_shell_carries_recalc_button(client: TestClient) -> None:
    """The recalc button is served and labelled in the static shell."""
    res = client.get("/static/index.html")
    assert res.status_code == 200
    html = res.text
    assert 'id="btn-recalc"' in html
    # Matches the surrounding toolbar action buttons' class.
    assert 'class="tx-btn"' in html
    # Clearly labelled for assistive tech.
    assert 'aria-label="Recalculate fingering"' in html


def test_recalc_button_sits_in_song_action_group() -> None:
    """The button lives in the toolbar-left group, right after #btn-review.

    That cluster (fingering / hand-viz / review toggles) is the song page's
    bottom action-button row; the recalc button must join it, not float off
    on its own elsewhere in the markup.
    """
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    review_idx = html.index('id="btn-review"')
    recalc_idx = html.index('id="btn-recalc"')
    handviz_idx = html.index('id="btn-hand-viz"')
    # Ordered immediately after the review button within the same group.
    assert handviz_idx < review_idx < recalc_idx
    # And before the transport-center controls (Play) that follow the group.
    assert recalc_idx < html.index('id="btn-play"')


def test_main_js_wires_recalc_to_existing_solve_plumbing() -> None:
    """main.js resolves the button and reuses selectTrack + the solve cache."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    # Element resolved.
    assert "$('#btn-recalc')" in js
    # Click handler wired to the recompute routine.
    assert "btnRecalc.addEventListener('click', _recalculateFingering)" in js
    assert "async function _recalculateFingering()" in js
    # Reuses the existing solve plumbing: invalidate cache + re-run selectTrack.
    assert "_solveCache.delete" in js
    assert "selectTrack(currentTrackId, _reviewTrackName)" in js


def test_main_js_recalc_toggles_busy_and_handles_errors() -> None:
    """The handler shows a busy/spinner state and re-enables on completion."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    # Busy state on entry.
    assert "btnRecalc.disabled = true" in js
    assert "btnRecalc.classList.add('is-busy')" in js
    # Re-enabled in a finally block (never stuck), and errors surfaced.
    assert "btnRecalc.disabled = false" in js
    assert "btnRecalc.classList.remove('is-busy')" in js
    assert "finally" in js


def test_style_css_defines_recalc_busy_spinner() -> None:
    """The is-busy spinner + disabled affordance exist in the stylesheet."""
    css = (_STATIC_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert ".tx-btn.is-busy" in css
    assert ".tx-btn:disabled" in css
    # Reuses the shared spin keyframe used by the song-loading spinner.
    assert "fw-spin" in css
