"""Anatomical re-grounding tests for the fretboard hand-viz rig (M3).

Milestone 1 locked the panel wiring (``test_web_hand_viz.py``); Milestone 2
generalized the fretboard geometry (``test_web_hand_viz_geometry.py``).  Milestone
3 replaces the eyeballed hand rig with anatomically grounded, size-adaptable
values driven by a single ``handScale`` factor:

  * finger lengths (``FINGER_TOTAL``) and knuckle offsets (``MCP_OFFSETS``) derive
    from ``handScale × base proportions`` (van der Hulst 2012);
  * joint flexion is bounded by realistic ranges (Shimawaki CT studies);
  * the DIP↔PIP coupling is a tunable, lower for fingertip-on-fret press poses.

Two layers of coverage:

1. **Static source guards** (always run) — assert the rig is parameterized by
   ``handScale`` and that the new anatomical constants exist with documented
   sources, while the old ad-hoc ``clamp(..., 0, 0.95)`` ceiling is gone.

2. **Behavioural checks** (run only when ``node`` is available) — load the
   renderer's rig + solver in a stubbed DOM and verify, across a range of
   ``handScale`` values and poses:
     * the anatomical no-cross order index ≤ middle ≤ ring ≤ pinky (MCP X);
     * finger-length ordering middle > ring ≈ index > pinky;
     * solver flexion stays within the new bounds;
     * the default ``handScale`` reproduces the prior proportions (regression).
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"

# Prior (pre-M3) hand proportions — the regression target for handScale == 1.0.
_PRIOR_FINGER_TOTAL = {"index": 176.0, "middle": 194.0, "ring": 184.0, "pinky": 158.0}
_PRIOR_MCP_OFFSETS = {"index": -52.0, "middle": -18.0, "ring": 15.0, "pinky": 49.0}
_FINGER_ORDER = ["index", "middle", "ring", "pinky"]


# --------------------------------------------------------------------------- #
# Layer 1 — static source guards (no JS engine required).
# --------------------------------------------------------------------------- #
def test_rig_is_parameterized_by_hand_scale() -> None:
    """The rig derives lengths/offsets from a single handScale factor."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # handScale is a mutable factor, the rig is rebuilt from it.
    assert "let handScale" in html
    assert "function configureRig(scale)" in html
    # FINGER_TOTAL / MCP_OFFSETS are now derived (let), not frozen constants.
    assert "let FINGER_TOTAL" in html
    assert "let MCP_OFFSETS" in html
    assert "const MCP_OFFSETS_BASE" in html
    assert "const FINGER_LENGTH_RATIO" in html
    assert "const BASE_FINGER_UNIT" in html
    # configureGeometry resizes the rig (so a payload/profile can drive it).
    cfg = html[html.index("function configureGeometry(data)"):]
    cfg = cfg[: cfg.index("\n}\n")]
    assert "configureRig(" in cfg


def test_joint_flexion_and_coupling_are_grounded() -> None:
    """Realistic flexion bounds + a tunable DIP↔PIP coupling replace ad-hoc arcs."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # Flexion bounds exist and cite Shimawaki.
    assert "JOINT_FLEXION_MAX" in html
    assert "FLEXION_MAX" in html
    assert "BASE_FLEX_MAX" in html
    assert "Shimawaki" in html
    # The old ad-hoc 0.95 ceiling in solveFinger is gone.
    assert "clamp(baseFlex + roleBoost, 0, 0.95)" not in html
    assert "clamp(baseFlex + roleBoost, 0, FLEXION_MAX)" in html
    # DIP↔PIP coupling is a named, role-dependent tunable, not a baked arc.
    assert "DIP_PIP_COUPLING_DEFAULT" in html
    assert "DIP_PIP_COUPLING_PRESS" in html
    assert "function dipPipCoupling(role)" in html
    # Phalanx proportions cite the anatomical source.
    assert "van der Hulst" in html


# --------------------------------------------------------------------------- #
# Layer 2 — behavioural checks via node (skipped when node is absent).
# --------------------------------------------------------------------------- #
_NODE = shutil.which("node")
pytestmark_node = pytest.mark.skipif(_NODE is None, reason="node not available")


def _run_rig_in_node(probe: str) -> dict:
    """Execute the renderer's rig/solver in a stubbed DOM and return a JSON probe.

    ``probe`` is JS that assigns an object literal to ``out`` after the renderer
    script has loaded (the boot IIFE is inert behind DOM stubs).  ``configureRig``
    and ``solveFinger`` are in scope.
    """
    html = _HAND_VIZ.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert m, "renderer must contain an inline <script> block"
    script = m.group(1)

    harness = (
        textwrap.dedent(
            """
            function FakeEl() {}
            FakeEl.prototype.setAttribute = function () {};
            FakeEl.prototype.appendChild = function () {};
            FakeEl.prototype.removeChild = function () {};
            Object.defineProperty(FakeEl.prototype, 'firstChild', { get() { return null; } });
            FakeEl.prototype.style = {};
            FakeEl.prototype.textContent = '';
            FakeEl.prototype.addEventListener = function () {};
            const _doc = {
              createElementNS: () => new FakeEl(),
              getElementById: () => new FakeEl(),
            };
            globalThis.document = _doc;
            globalThis.window = {
              addEventListener: () => {}, parent: null, postMessage: () => {},
            };
            globalThis.performance = { now: () => 0 };
            globalThis.requestAnimationFrame = () => 0;
            globalThis.fetch = () => Promise.reject(new Error('no fetch in test'));
            """
        )
        + "\n"
        + script
        + "\n"
        + textwrap.dedent(
            """
            let out = {};
            __PROBE__
            process.stdout.write(JSON.stringify(out));
            """
        ).replace("__PROBE__", probe)
    )

    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# Probe helper: configure a scale and dump the live rig + a battery of solver
# poses, so each test can assert against the returned numbers.
_RIG_PROBE = textwrap.dedent(
    """
    configureRig(SCALE);
    out.handScale = handScale;
    out.FINGER_TOTAL = { ...FINGER_TOTAL };
    out.MCP_OFFSETS = { ...MCP_OFFSETS };
    out.FLEXION_MAX = FLEXION_MAX;
    out.BASE_FLEX_MAX = BASE_FLEX_MAX;
    out.coupling = {
      default: dipPipCoupling('idle'),
      press: dipPipCoupling('active'),
      planted: dipPipCoupling('planted'),
      hover: dipPipCoupling('hover'),
    };
    // Battery of solver poses across fingers/roles, including over-reach cases
    // that would historically pin flexion at the old 0.95 ceiling.
    const roles = ['active', 'planted', 'hover', 'idle'];
    const order = ['index', 'middle', 'ring', 'pinky'];
    const poses = [];
    for (const name of order) {
      for (const role of roles) {
        // mild reach
        poses.push(solveFinger(0, 0, 10, 90, name, role).flexion);
        // extreme over-reach (way past full extension) -> should still be bounded
        poses.push(solveFinger(0, 0, 400, 400, name, role).flexion);
        // near-zero reach (folded) -> high curl
        poses.push(solveFinger(0, 0, 2, 6, name, role).flexion);
      }
    }
    out.flexions = poses;
    """
)


def _probe_scale(scale: float) -> dict:
    return _run_rig_in_node(_RIG_PROBE.replace("SCALE", repr(float(scale))))


@pytestmark_node
def test_default_hand_scale_reproduces_prior_proportions() -> None:
    """handScale == 1.0 regenerates the historical finger lengths and offsets."""
    g = _probe_scale(1.0)
    assert g["handScale"] == pytest.approx(1.0)
    for f in _FINGER_ORDER:
        assert g["FINGER_TOTAL"][f] == pytest.approx(_PRIOR_FINGER_TOTAL[f], abs=1e-6)
        assert g["MCP_OFFSETS"][f] == pytest.approx(_PRIOR_MCP_OFFSETS[f], abs=1e-6)


@pytestmark_node
@pytest.mark.parametrize("scale", [0.6, 0.8, 1.0, 1.25, 1.6])
def test_finger_length_ordering_holds_across_scales(scale: float) -> None:
    """middle > ring ≈ index > pinky, and lengths scale isometrically."""
    g = _probe_scale(scale)
    ft = g["FINGER_TOTAL"]
    assert ft["middle"] > ft["ring"] > ft["index"] > ft["pinky"]
    # ring ≈ index (within ~8% of the middle length) — the "≈" in the spec.
    assert abs(ft["ring"] - ft["index"]) < 0.10 * ft["middle"]
    # Isometric: every length is exactly scale × the default.
    for f in _FINGER_ORDER:
        assert ft[f] == pytest.approx(scale * _PRIOR_FINGER_TOTAL[f], abs=1e-6)


@pytestmark_node
@pytest.mark.parametrize("scale", [0.6, 0.8, 1.0, 1.25, 1.6])
def test_no_cross_mcp_order_holds_across_scales(scale: float) -> None:
    """The anatomical no-cross order index < middle < ring < pinky (MCP X)."""
    g = _probe_scale(scale)
    mo = g["MCP_OFFSETS"]
    assert mo["index"] < mo["middle"] < mo["ring"] < mo["pinky"]
    # Offsets scale with the hand too (knuckles spread on a bigger palm).
    for f in _FINGER_ORDER:
        assert mo[f] == pytest.approx(scale * _PRIOR_MCP_OFFSETS[f], abs=1e-6)


@pytestmark_node
@pytest.mark.parametrize("scale", [0.6, 1.0, 1.6])
def test_solver_flexion_stays_within_bounds(scale: float) -> None:
    """Every solved pose's flexion respects the new realistic ceiling."""
    g = _probe_scale(scale)
    assert g["FLEXION_MAX"] == pytest.approx(0.90)
    assert 0.80 < g["BASE_FLEX_MAX"] < 0.83   # MCP-limited base curl
    for fl in g["flexions"]:
        assert 0.0 <= fl <= g["FLEXION_MAX"] + 1e-9
    # The bound must actually bite somewhere (over-reach + idle poses), proving
    # the ceiling is enforced rather than vacuously satisfied.
    assert max(g["flexions"]) == pytest.approx(g["FLEXION_MAX"], abs=1e-6)


@pytestmark_node
def test_dip_pip_coupling_is_lower_for_press_poses() -> None:
    """Press/plant use the LOW-coupling end; idle/hover use the relaxed default."""
    g = _probe_scale(1.0)
    c = g["coupling"]
    # Press and plant share the reduced coupling.
    assert c["press"] == pytest.approx(c["planted"])
    # Idle and hover share the relaxed rule-of-thumb default.
    assert c["default"] == pytest.approx(c["hover"])
    # Press coupling is strictly lower than the relaxed default.
    assert c["press"] < c["default"]
    # Default ≈ ⅔ rule of thumb; press is materially nearer-perpendicular.
    assert 0.6 <= c["default"] <= 0.7
    assert 0.35 <= c["press"] <= 0.5
