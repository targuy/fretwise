"""Guard tests for the 3D-hand self-test harness (T-B.1, docs/plan_impl_slope_main3d.md §B).

`window.__handSelfTest()` is a deterministic, off-clock sweep of the
articulated 3D rig that returns the metrics each spec acceptance criterion
(spec_vues_slope_main3d.md §5) is defined against: contact (H-11), collision
(H-9), perf (H-16), stillness (H-15), camera invariant (H-18), distal-phalanx
angle (H-10). There is no headless WebGL here, so — like the other
test_web_hand_viz*.py guards — this asserts the harness and the constants it
depends on are present in the shipped source, not that a browser run
succeeds (that's exercised interactively / in follow-up phases' sweeps).
"""
from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"


def _hand_viz_html() -> str:
    return (_STATIC_DIR / "hand_viz.html").read_text(encoding="utf-8")


def _hand3d_js() -> str:
    return (_STATIC_DIR / "js" / "hand3d.js").read_text(encoding="utf-8")


def test_self_test_hook_is_exposed_globally() -> None:
    html = _hand_viz_html()
    assert "window.__handSelfTest = function (opts) {" in html


def test_self_test_guards_against_inactive_renderer() -> None:
    """Must fail gracefully (not throw) when the 3D rig isn't live."""
    html = _hand_viz_html()
    assert '"3D articulated renderer not active' in html


def test_self_test_covers_every_spec_metric_family() -> None:
    """One field per §5 sweep: contact/collision/perf/still/camInvariant/distalAngle."""
    html = _hand_viz_html()
    body_start = html.index("window.__handSelfTest = function (opts) {")
    body_end = html.index("\n};", body_start)
    body = html[body_start:body_end]
    for field in ("contact:", "collision:", "perf:", "still:", "camInvariant:", "distalAngle:"):
        assert field in body, f"self-test return object missing '{field}'"


def test_self_test_reads_live_constants_not_magic_numbers() -> None:
    """STRING_SURFACE/CONTACT_EPS must come from the hand3d.js module export,
    not a hardcoded copy that can silently drift from the real rig."""
    html = _hand_viz_html()
    assert "HAND3D_MODULE.STRING_SURFACE" in html
    js = _hand3d_js()
    assert "export { Hand3DRenderer, webglAvailable, STRING_SURFACE, CONTACT_EPS };" in js
