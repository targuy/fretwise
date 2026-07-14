"""Smoke tests for the per-track "Insérer les doigtés" button.

The viewer toolbar carries a single fingering action button (#btn-insert-fingerings)
that replaced the old recalculate-circle (#btn-recalc). Clicking it computes and
*saves* fingerings (POST /api/save/gp), then invalidates the cached solve and
re-runs ``selectTrack`` so the freshly-saved sidecar is shown. These guards
assert the static shell + JS carry the button and its wiring. Mirrors the
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


def test_index_shell_carries_insert_fingerings_button(client: TestClient) -> None:
    """The insert-fingerings button is served and labelled in the static shell."""
    res = client.get("/static/index.html")
    assert res.status_code == 200
    html = res.text
    assert 'id="btn-insert-fingerings"' in html
    # Matches the surrounding toolbar action buttons' class.
    assert 'class="tx-btn"' in html
    # Clearly labelled for assistive tech, and the old button is gone.
    assert 'aria-label="Insérer les doigtés"' in html
    assert 'id="btn-recalc"' not in html


def test_insert_button_sits_in_song_action_group() -> None:
    """The button lives in the toolbar-left group, after #btn-review.

    That cluster (fingering / review toggles) is the song page's action-button
    row; the insert button must join it, not float off elsewhere.
    """
    html = (_STATIC_DIR / "index.html").read_text(encoding="utf-8")
    review_idx = html.index('id="btn-review"')
    insert_idx = html.index('id="btn-insert-fingerings"')
    # Ordered after the review button within the same group.
    assert review_idx < insert_idx
    # And before the transport-center controls (Play) that follow the group.
    assert insert_idx < html.index('id="btn-play"')


def test_main_js_wires_insert_to_save_plumbing() -> None:
    """main.js resolves the button and saves, then reuses selectTrack + cache."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    # Element resolved.
    assert "$('#btn-insert-fingerings')" in js
    # Click handler wired to the insert routine.
    assert "btnInsertFingerings.addEventListener('click', _insertFingerings)" in js
    assert "async function _insertFingerings()" in js
    # Computes + saves, then invalidates cache and re-runs selectTrack.
    assert "fetchSaveGp(currentFile, currentTrackId)" in js
    assert "_solveCache.delete" in js
    assert "selectTrack(currentTrackId, _reviewTrackName)" in js


def test_main_js_insert_toggles_busy_and_handles_errors() -> None:
    """The handler shows a busy/spinner state and re-enables on completion."""
    js = (_STATIC_DIR / "js" / "main.js").read_text(encoding="utf-8")
    # Busy state on entry.
    assert "btnInsertFingerings.disabled = true" in js
    assert "btnInsertFingerings.classList.add('is-busy')" in js
    # Re-enabled in a finally block (never stuck), and errors surfaced.
    assert "btnInsertFingerings.disabled = false" in js
    assert "btnInsertFingerings.classList.remove('is-busy')" in js
    assert "finally" in js


def test_style_css_defines_insert_busy_spinner() -> None:
    """The is-busy spinner + disabled affordance exist in the stylesheet."""
    css = (_STATIC_DIR / "css" / "style.css").read_text(encoding="utf-8")
    assert ".tx-btn.is-busy" in css
    assert ".tx-btn:disabled" in css
    # Reuses the shared spin keyframe used by the song-loading spinner.
    assert "fw-spin" in css
