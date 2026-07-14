"""Guard tests for P1 biomechanics mechanisms (H-9/H-10/H-12/H-13, T-P1.1..T-P1.4).

Mirrors the other test_web_hand_viz*.py source-presence guards. Behavior is
verified via window.__handSelfTest() interactively (see
docs/plan_impl_slope_main3d.md §5); these assert the mechanisms — and their
documented postmortems, so future work doesn't blindly repeat a dead end —
are present in shipped source.
"""
from __future__ import annotations

from pathlib import Path

_HAND3D_JS = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "hand3d.js"


def _js() -> str:
    return _HAND3D_JS.read_text(encoding="utf-8")


def test_palm_bridge_routes_via_an_elbow_not_a_straight_line() -> None:
    """T-P1.1: the wrist-to-knuckle palm bridge is two segments (via an
    elbow waypoint), not one straight diagonal slab that cuts through the
    neck for bass-string fingerings."""
    js = _js()
    assert "this.wristStub = new THREE.Mesh(new THREE.CylinderGeometry(1, 1, 1, 12), materials.skin);" in js
    assert "this.elbow = new THREE.Object3D();" in js
    bridge_start = js.index("bridgePalm(ky, kz) {")
    bridge_end = js.index("\n  }", bridge_start)
    body = js[bridge_start:bridge_end]
    assert "this.elbow.position.set(0, ky, 0);" in body
    assert "this.wristStub.position.set(0, ky / 2, 0);" in body


def test_palm_collision_diagnostic_samples_the_elbow_path() -> None:
    """The coarse collision proxy must sample the SAME two-segment route the
    rendered mesh follows — sampling the old straight line would make the
    diagnostic stale relative to what's actually drawn."""
    js = _js()
    sample_start = js.index("_palmSamplePoints(m, out) {")
    sample_end = js.index("\n  }", sample_start)
    body = js[sample_start:sample_end]
    assert "m.elbow.getWorldPosition(pts[i]);" in body


def test_palm_fix_never_moves_wrist_or_anchors() -> None:
    """R1 (risk registry): the palm/neck fix must be purely visual — it must
    never touch m.node.position or the MCP anchors, which reach depends on.
    bridgePalm only writes to this.palm/this.wristStub/this.elbow transforms."""
    js = _js()
    bridge_start = js.index("bridgePalm(ky, kz) {")
    bridge_end = js.index("\n  }", bridge_start)
    body = js[bridge_start:bridge_end]
    assert "m.node.position" not in body
    assert "anchors[" not in body


def test_idle_rest_pose_has_a_collision_safety_net() -> None:
    """T-P1.3: unlike active/hover fingers (CCD with a collision callback),
    the idle rest curl is a fixed pose — it must be collision-checked and
    fall back toward a known-safe curl, or a deep rest curl can swing a
    resting finger's phalanx into the neck."""
    js = _js()
    assert "_relaxIdleSafely(d) {" in js
    method_start = js.index("_relaxIdleSafely(d) {")
    method_end = js.index("\n  }", method_start)
    body = js[method_start:method_end]
    assert "this._segmentsHitNeck(d.segments())" in body
    assert "SAFE_CURL" in body


def test_idle_curl_is_deeper_than_the_pre_p1_baseline() -> None:
    """T-P1.3: the tuned rest curl must be deeper than the old {0.9,1.0,0.5}
    baseline (which floated fingertips ~54mm above the strings, H-12 target
    is ~5-15mm) — this guards against a future edit silently reverting the
    height fix while leaving the safety-net machinery in place."""
    js = _js()
    assert "const IDLE_CURL      = { mcp: 1.32, pip: 1.52, dip: 0.66 };" in js


def test_finger_yaw_capped_at_45_degrees() -> None:
    """H-13: fingers may only 'point' toward a fret up to 45°, never rotate
    further — large position changes must be carried by the wrist, not by
    stretching a finger's lateral reach."""
    js = _js()
    assert "MCP_POINT_MAX = 45 * DEG;" in js
    assert "clampN(yawRaw, -MCP_ABD_HALF[name], MCP_ABD_HALF[name])" in js
