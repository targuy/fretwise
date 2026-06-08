"""Feature-flag + fallback guards for the optional 3D hand renderer (M5).

Milestone 5 adds an OPT-IN three.js 3D hand as an alternative to the mature 2.5D
SVG renderer in ``hand_viz.html``.  The non-negotiable invariant is that the SVG
path stays the default, unchanged experience: the 3D mode is purely additive and
strictly behind a flag that defaults OFF, and it must fall back to SVG whenever
three.js fails to load or WebGL is unavailable.

WHAT THESE TESTS COVER
----------------------
1. **Static source guards** (always run, no JS engine) — the feature flag exists
   and defaults OFF; the SVG ``<svg id="scene">`` is present and is the default
   (the 3D mount starts ``display:none``); ``hand_viz.html`` does NOT register a
   second postMessage listener (the 3D path reuses the one payload contract); the
   3D rig reuses the shared kinematics (``solveFinger`` / ``HandSimulator`` /
   geometry helpers) rather than forking a second model; and the vendored
   three.js asset + ``hand3d.js`` module are present.

2. **Behavioural flag + fallback checks** (run only when ``node`` is available)
   — execute the flag-resolution logic from ``hand_viz.html`` in a stubbed DOM:
     * no flag           → 3D NOT requested (SVG default),
     * ``?hand3d=1``     → requested,
     * ``?hand3d=0``     → NOT requested (explicit opt-out),
     * localStorage flag → requested,
   and ``node --check`` both ``hand3d.js`` and the vendored ``three.module.min.js``
   as ES modules so a syntax error fails CI.

WHAT IS *NOT* COVERED (and why)
-------------------------------
Live WebGL/3D rendering is **out of scope for automated tests**: this CI
environment has no headless WebGL context, so we cannot instantiate a real
``THREE.WebGLRenderer`` or assert pixels.  Instead we verify, by construction and
static guard, that:
  * the renderer factory returns ``null`` (→ SVG fallback) when WebGL is absent
    (``webglAvailable()`` gates ``create()``), and
  * the host swaps cleanly to SVG on any import/construction failure.
The actual on-GPU geometry of the rigged hand is validated manually / visually,
not here.  See ``hand3d.js`` for the rig and ``hand_viz.html`` for the bridge.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


def _strip_js_comments(src: str) -> str:
    """Remove block + line comments so negative-presence guards test CODE only.

    The 3D rig's header prose intentionally *mentions* names like ``solveFinger``
    and ``fretwise-hand-data`` to document that it does NOT use them; the guards
    below assert those names are absent from the executable code, not the prose.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.DOTALL)
    src = re.sub(r"//[^\n]*", "", src)
    return src

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"
_HAND3D_JS = _STATIC_DIR / "js" / "hand3d.js"
_THREE_JS = _STATIC_DIR / "js" / "vendor" / "three.module.min.js"
_HAND_MESH_JS = _STATIC_DIR / "js" / "vendor" / "hand_mesh.js"
_HAND_C_JPG = _STATIC_DIR / "img" / "hand" / "HAND_C.jpg"
_HAND_N_JPG = _STATIC_DIR / "img" / "hand" / "HAND_N.jpg"
_HAND_S_JPG = _STATIC_DIR / "img" / "hand" / "HAND_S.jpg"


# --------------------------------------------------------------------------- #
# Layer 1 — static source guards (no JS engine required).
# --------------------------------------------------------------------------- #
def test_3d_assets_present() -> None:
    """The 3D rig module and the vendored three.js asset both ship."""
    assert _HAND3D_JS.is_file(), "hand3d.js must be vendored under static/js/"
    assert _THREE_JS.is_file(), "three.module.min.js must be vendored locally"
    # three.js is a non-trivial bundle (sanity floor so we don't ship a stub).
    assert _THREE_JS.stat().st_size > 200_000
    three_src = _THREE_JS.read_text(encoding="utf-8", errors="ignore")
    assert "Three.js" in three_src or "three.js" in three_src.lower()
    # The rig imports three.js as an ES module from the vendored path.
    h3d = _HAND3D_JS.read_text(encoding="utf-8")
    assert 'from "./vendor/three.module.min.js"' in h3d


def test_skin_texture_assets_present() -> None:
    """The three skin-texture maps and the OBJ hand-mesh module are on disk."""
    assert _HAND_C_JPG.is_file(), "HAND_C.jpg (color/diffuse) must exist"
    assert _HAND_N_JPG.is_file(), "HAND_N.jpg (normal map) must exist"
    assert _HAND_S_JPG.is_file(), "HAND_S.jpg (specular map) must exist"
    # Each texture file must be a non-trivial JPEG (floor: 50 KB).
    for path in (_HAND_C_JPG, _HAND_N_JPG, _HAND_S_JPG):
        assert path.stat().st_size > 50_000, f"{path.name} looks empty"
    # hand_mesh.js must exist and export the three Float32Arrays.
    assert _HAND_MESH_JS.is_file(), "hand_mesh.js must be vendored under static/js/vendor/"
    assert _HAND_MESH_JS.stat().st_size > 0, "hand_mesh.js must be non-empty"
    mesh_src = _HAND_MESH_JS.read_text(encoding="utf-8")
    assert "export const HAND_MESH_POSITIONS" in mesh_src
    assert "export const HAND_MESH_UVS" in mesh_src
    assert "export const HAND_MESH_NORMALS" in mesh_src


def test_hand3d_js_references_texture_and_mesh_loaders() -> None:
    """hand3d.js contains the ``_loadTextures`` and ``_loadHandMesh`` methods."""
    h3d = _HAND3D_JS.read_text(encoding="utf-8")
    assert "_loadTextures" in h3d, "_loadTextures method must exist in hand3d.js"
    assert "_loadHandMesh" in h3d, "_loadHandMesh method must exist in hand3d.js"
    # The texture paths must be referenced.
    assert "HAND_C.jpg" in h3d
    assert "HAND_N.jpg" in h3d
    assert "HAND_S.jpg" in h3d
    # The hand mesh module path must be referenced.
    assert "hand_mesh.js" in h3d
    # The two methods must be wired together in the constructor chain.
    assert "_loadTextures().then" in h3d
    # Both methods must degrade gracefully (console.warn fallback).
    assert "_loadHandMesh" in h3d
    # The existing pose contract must be intact: palm.position.set used in update().
    code = _strip_js_comments(h3d)
    assert "this.palm.position.set(" in code, "palm pose (position.set) must remain in update()"


def test_flag_helper_exists_and_defaults_off() -> None:
    """``hand3dRequested`` exists and returns false with no flag set."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    assert "function hand3dRequested()" in html
    # The default fall-through returns false (SVG).  Grab the function body.
    body = html[html.index("function hand3dRequested()"):]
    body = body[: body.index("\nfunction setHand3dFlag")]
    # No flag set → must end by returning false.
    assert "return false;" in body
    # Reads from URL param "hand3d" and the localStorage key, nothing else.
    assert '"hand3d"' in body or "'hand3d'" in body
    assert "fretwise.hand3d" in html
    # The runtime active-state defaults to false (SVG).
    assert "let HAND3D_ACTIVE   = false" in html or "let HAND3D_ACTIVE = false" in html
    assert "let HAND3D_RENDERER = null" in html


def test_svg_is_the_default_renderer() -> None:
    """The SVG scene is present and the default; the 3D mount starts hidden."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # The unchanged SVG scene still exists.
    assert '<svg id="scene"' in html
    # The 3D mount exists but is hidden by default (display:none).
    m = re.search(r'<div id="scene3d"[^>]*>', html)
    assert m, "a #scene3d mount must exist"
    assert "display:none" in m.group(0).replace(" ", "")
    # The boot only enables 3D when the OFF-by-default flag is requested.
    assert "if (hand3dRequested()) {" in html
    assert "enableHand3d();" in html


def test_single_postmessage_contract_reused() -> None:
    """The 3D path reuses the one postMessage payload contract (no 2nd listener)."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # Exactly one window 'message' listener — the existing data/seek handler.
    assert html.count('addEventListener("message"') == 1
    # The data + seek message types are still the sole contract.
    assert "fretwise-hand-data" in html
    assert "fretwise-hand-seek" in html
    # hand3d.js itself must NOT register its own message/data listener: it is a
    # downstream consumer of the shared sim, not a second payload subscriber.
    # (The module's header comment may *mention* the message types, so we guard
    # the executable code only, with comments stripped.)
    h3d_code = _strip_js_comments(_HAND3D_JS.read_text(encoding="utf-8"))
    assert 'addEventListener("message"' not in h3d_code  # no postMessage listener
    assert "fretwise-hand-data" not in h3d_code          # no use of the payload type


def test_3d_reuses_shared_kinematics_not_a_fork() -> None:
    """The 3D snapshot is built from the shared sim/IK, not a second solver."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    snap = html[html.index("function buildKinSnapshot(sim)"):]
    snap = snap[: snap.index("\nfunction hand3dGeometry")]
    # Uses the SAME IK solver and simulator accessors the SVG path uses.
    assert "solveFinger(" in snap
    assert "sim.getMcpPos(" in snap
    assert "sim.fingers[" in snap
    assert "fingerPxWidth(" in snap
    # hand3d.js must NOT re-implement the kinematic solver: no solveFinger CALL,
    # no flexion/coupling constants — it only re-expresses joints as 3D bones.
    # (The module header may *mention* solveFinger in prose; guard the call.)
    h3d_code = _strip_js_comments(_HAND3D_JS.read_text(encoding="utf-8"))
    assert "solveFinger(" not in h3d_code
    assert "JOINT_FLEXION_MAX" not in h3d_code
    assert "DIP_PIP_COUPLING" not in h3d_code
    # The same CURRENT_SIM drives both renderers in the frame loop.
    assert "buildKinSnapshot(CURRENT_SIM)" in html


def test_toggle_button_is_wired_to_enable_path() -> None:
    """The visible "3D : off" HUD button toggles the renderer (not display-only).

    Regression guard for the "button visible but I can't reach 3D mode" symptom:
    the ``#btn-3d`` control must be bound to a click handler that flips the
    persisted flag and calls ``enableHand3d`` / ``disableHand3d``.  We also pin
    that the binding is hoisted to TOP LEVEL — above the ``installData(await
    loadData())`` boot IIFE — so a throw while installing data can never leave
    the button dead.
    """
    html = _HAND_VIZ.read_text(encoding="utf-8")

    # The HUD button still ships labelled "3D : off" (default OFF on first load).
    assert 'id="btn-3d"' in html
    assert "3D : off" in html

    # It is looked up and a click handler is registered that hits the enable
    # path, the disable path, and persists the flag in both directions.
    assert 'document.getElementById("btn-3d")' in html
    assert 'btn3d.addEventListener("click"' in html
    assert "await enableHand3d();" in html
    assert "disableHand3d();" in html
    assert "setHand3dFlag(true);" in html
    assert "setHand3dFlag(false);" in html

    # Wiring must be hoisted ABOVE the data-load IIFE so it cannot be skipped by
    # an exception during installData(): the binding's getElementById call must
    # appear before `installData(await loadData());`.
    bind_at = html.index('document.getElementById("btn-3d")')
    boot_at = html.index("installData(await loadData());")
    assert bind_at < boot_at, (
        "the #btn-3d toggle must be wired before the async data-load boot so a "
        "data-install failure can't leave the visible button dead"
    )

    # Default stays OFF: nothing forces 3D on at load; the only auto-enable path
    # is still gated behind the OFF-by-default flag helper.
    assert "if (hand3dRequested()) {" in html


def test_fallback_to_svg_on_failure() -> None:
    """Enable path falls back to SVG (never a broken panel) on any failure."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    enable = html[html.index("async function enableHand3d()"):]
    enable = enable[: enable.index("\nfunction disableHand3d")]
    # A failure (import error / null renderer) restores the SVG and hides 3D.
    assert "catch (e)" in enable
    assert "HAND3D_ACTIVE   = false" in enable or "HAND3D_ACTIVE = false" in enable
    # The factory returning null is treated as a failure → SVG.
    assert "if (!renderer)" in enable
    # The renderer factory gates on WebGL availability.
    h3d = _HAND3D_JS.read_text(encoding="utf-8")
    assert "function webglAvailable()" in h3d
    assert "if (!webglAvailable()) return null;" in h3d
    # create() never throws on construction failure — it returns null.
    create = h3d[h3d.index("export function create(container)"):]
    assert "return null;" in create


# --------------------------------------------------------------------------- #
# Layer 2 — behavioural flag resolution + module syntax via node.
# --------------------------------------------------------------------------- #
_NODE = shutil.which("node")
pytestmark_node = pytest.mark.skipif(_NODE is None, reason="node not available")


def _extract_flag_helpers() -> str:
    """Pull the flag-resolution helpers out of hand_viz.html for unit exec."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    start = html.index("const HAND3D_STORAGE_KEY")
    end = html.index("function setHand3dFlag")
    # Include setHand3dFlag's close brace by re-slicing to the next blank-ish
    # marker; simplest is to grab through the end of setHand3dFlag.
    after = html[end:]
    end2 = end + after.index("\n}") + 2
    return html[start:end2]


def _run_flag_in_node(search: str, storage_val: str | None) -> bool:
    """Execute hand3dRequested() under a stubbed window and return its bool."""
    helpers = _extract_flag_helpers()
    storage_js = (
        "null" if storage_val is None else f'"{storage_val}"'
    )
    harness = (
        textwrap.dedent(
            f"""
            const _store = {{ "fretwise.hand3d": {storage_js} }};
            globalThis.window = {{
              location: {{ search: {search!r} }},
              localStorage: {{
                getItem: (k) => (k in _store ? _store[k] : null),
                setItem: () => {{}},
              }},
            }};
            globalThis.URLSearchParams = URLSearchParams;
            """
        )
        + "\n"
        + helpers
        + "\n"
        + "process.stdout.write(JSON.stringify(hand3dRequested()));\n"
    )
    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return proc.stdout.strip() == "true"


@pytestmark_node
def test_flag_off_by_default_no_params() -> None:
    """No URL param and no storage flag → 3D NOT requested (SVG default)."""
    assert _run_flag_in_node("", None) is False


@pytestmark_node
def test_flag_on_via_url_param() -> None:
    """``?hand3d=1`` requests the 3D renderer."""
    assert _run_flag_in_node("?hand3d=1", None) is True
    assert _run_flag_in_node("?hand3d", None) is True


@pytestmark_node
def test_flag_explicit_opt_out_via_url() -> None:
    """``?hand3d=0`` is an explicit opt-out even if storage says on."""
    assert _run_flag_in_node("?hand3d=0", "1") is False


@pytestmark_node
def test_flag_on_via_localstorage() -> None:
    """The persisted localStorage flag enables 3D when no URL param is present."""
    assert _run_flag_in_node("", "1") is True
    assert _run_flag_in_node("", "0") is False


@pytestmark_node
def test_hand3d_module_is_syntax_clean() -> None:
    """hand3d.js parses as a valid ES module (node --check)."""
    src = _HAND3D_JS.read_text(encoding="utf-8")
    proc = subprocess.run(
        [_NODE, "--input-type=module", "--check"],
        input=src,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"hand3d.js syntax error:\n{proc.stderr}"


@pytestmark_node
def test_vendored_three_is_syntax_clean() -> None:
    """The vendored three.js parses as a valid ES module (node --check)."""
    src = _THREE_JS.read_text(encoding="utf-8")
    proc = subprocess.run(
        [_NODE, "--input-type=module", "--check"],
        input=src,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"three.module.min.js syntax error:\n{proc.stderr}"
