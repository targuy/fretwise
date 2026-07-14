"""Guard tests for P0 stability mechanisms (H-14/H-15/H-16, T-P0.1..T-P0.5).

Mirrors the other test_web_hand_viz*.py source-presence guards — there is no
headless WebGL here, so these assert the mechanisms exist in shipped source;
behavior is verified via window.__handSelfTest() (see
test_web_hand_viz_selftest.py and docs/plan_impl_slope_main3d.md §B/§5).
"""
from __future__ import annotations

from pathlib import Path

_HAND3D_JS = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "hand3d.js"


def _js() -> str:
    return _HAND3D_JS.read_text(encoding="utf-8")


def test_per_finger_latch_present_and_gated_on_wrist_convergence() -> None:
    """T-P0.1: a finger only reuses frozen angles once the finger's OWN target
    AND the wrist anchor it's attached to have both stopped moving — omitting
    the wrist gate was measured live to regress contact accuracy ~4x."""
    js = _js()
    assert "_fingerLatch" in js
    assert "const wristStill = !!this._wristConverged;" in js
    assert "animateTargets && wristStill && latch && latch.sig === sig && latch.converged && latch.ok" in js


def test_finger_latch_never_reused_on_wrist_retry_pass() -> None:
    """The R11 retry passes (animateTargets===false) must never latch — the
    wrist just moved, so a frozen finger pose would be stale (risk R4)."""
    js = _js()
    # The latch condition requires animateTargets truthy; retry calls pass
    # animateTargets=false explicitly, so they can never satisfy the gate.
    assert "_foldAllFingers(kin, false)" in js


def test_wrist_and_finger_ease_snap_exactly_on_convergence() -> None:
    """T-P0.2: once converged, the eased pose snaps to the exact target
    instead of leaving an asymptotic (nonzero, still "moving") residual."""
    js = _js()
    assert "p.x = target.x; p.y = target.y; p.z = target.z;" in js
    assert "motion.x = target.x; motion.y = target.y; motion.z = target.z;" in js


def test_ccd_scan_uses_a_real_improvement_margin() -> None:
    """T-P0.4: the discrete angle scan requires a real (not float-noise)
    improvement before accepting a new candidate over the current angle."""
    js = _js()
    assert "if (d < bestD - 1e-4) { bestD = d; bestA = a; }" in js


def test_self_test_harness_resets_state_between_runs() -> None:
    """The harness itself must be deterministic — confirmed live that without
    a reset, back-to-back __handSelfTest() calls on IDENTICAL code produced
    wildly different collision/contact numbers purely from leftover ease/latch
    state, which would make every P0 regression check unreliable."""
    html = (Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "hand_viz.html").read_text(encoding="utf-8")
    assert "delete r._wristPose;" in html
    assert "r._fingerLatch = {};" in html
    assert 'r._fingerMotion[f] = { x: null, y: null, z: null, role: "idle" };' in html
