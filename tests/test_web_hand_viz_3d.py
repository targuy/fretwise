"""Runtime guards for the single HandPerformance renderer host."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"
_HAND_V2_JS = _STATIC_DIR / "js" / "hand_v2.js"
_MAIN_JS = _STATIC_DIR / "js" / "main.js"
_THREE_JS = _STATIC_DIR / "js" / "vendor" / "three.module.min.js"
_NODE = shutil.which("node")


def test_reference_hand_is_unconditional_and_legacy_mode_is_removed() -> None:
    """HandPerformance v2 boots directly; old engine has no runtime path."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    main = _MAIN_JS.read_text(encoding="utf-8")

    assert "await import('./js/hand_v2.js')" in html
    assert "enableHand3d().then" in html
    assert not (_STATIC_DIR / "js" / "hand3d.js").exists()
    assert not (_STATIC_DIR / "js" / "pose_cache.js").exists()
    for removed in (
        "hand3dRequested",
        "handRenderer",
        "fretwise.handRenderer",
        "HAND_ENGINE",
        'id="hand-engine"',
        "Historique",
        'id="btn-3d"',
    ):
        assert removed not in html
        assert removed not in main


def test_reference_assets_and_schematic_failure_fallback_remain() -> None:
    """Current renderer and Three.js ship; SVG appears only if v2 fails."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert _HAND_V2_JS.is_file()
    assert _THREE_JS.is_file()
    assert _THREE_JS.stat().st_size > 200_000
    assert '<svg id="scene"' in html
    assert '<div id="scene3d" style="display:none;' in html

    enable = html[html.index("async function enableHand3d()"):]
    enable = enable[: enable.index("\nfunction disableHand3d")]
    assert "await import('./js/hand_v2.js')" in enable
    assert "if (!renderer)" in enable
    assert "catch (e)" in enable
    assert "console.warn" in enable
    assert "mount.style.display = \"none\"" in enable
    assert "svg.style.display   = \"block\"" in enable


def test_top_projection_control_is_accessible_and_wired_before_boot() -> None:
    """Top control selects 90-degree orthographic view and exposes state."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert 'id="btn-top-view"' in html
    assert 'aria-pressed="false"' in html
    assert 'document.getElementById("btn-top-view")' in html
    assert 'btnTopView.addEventListener("click"' in html
    assert "HAND_CAMERA = 'top'" in html
    assert "HAND3D_RENDERER.setCameraView(HAND_CAMERA)" in html
    assert 'btn.setAttribute("aria-pressed", String(topActive))' in html

    bind_at = html.index('document.getElementById("btn-top-view")')
    boot_at = html.index("if (!HAND_TRANSPORT.sessionId) installData(initialData);")
    assert bind_at < boot_at


def test_single_versioned_message_contract_is_reused() -> None:
    """One host listener owns HandPerformance transport and fallback data."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert html.count('addEventListener("message"') == 1
    assert "fretwise:load" in html
    assert "fretwise:transport" in html
    assert "fretwise-hand-data" in html
    assert "fretwise-hand-seek" in html


@pytest.mark.skipif(_NODE is None, reason="node not available")
@pytest.mark.parametrize("path", [_HAND_V2_JS, _THREE_JS])
def test_current_renderer_modules_are_syntax_clean(path: Path) -> None:
    """Current ES modules parse in Node."""
    proc = subprocess.run(
        [_NODE, "--input-type=module", "--check"],
        input=path.read_text(encoding="utf-8", errors="ignore"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"{path.name} syntax error:\n{proc.stderr}"
