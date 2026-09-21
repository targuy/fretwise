"""Regression guards for the sole HandPerformance 3D host."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"
_HAND_V2_JS = _STATIC_DIR / "js" / "hand_v2.js"
_THREE_JS = _STATIC_DIR / "js" / "vendor" / "three.module.min.js"


def test_hand_host_contains_only_the_reference_3d_renderer() -> None:
    """The removed SVG hand renderer has no host, fallback, or source path."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert "import { create } from './js/hand_v2.js'" in html
    assert 'id="scene3d"' in html
    assert "create(mount)" in html
    assert "renderer.clearPerformance" in html
    for removed in (
        "<svg", "HandSimulator", "solveFinger", "layer-hand", "layer-fretboard",
        "layer-shadow", "scene-wrap", "enableHand3d", "disableHand3d",
        "schematic fallback", "fretwise-hand-data", "fretwise-hand-seek",
    ):
        assert removed not in html


def test_legacy_payloads_adapt_to_v2_data_without_restoring_a_renderer() -> None:
    """Saved frame payloads remain readable by the current 3D-only contract."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert "function adaptLegacyFrames(data)" in html
    assert "schemaVersion: '1.0'" in html
    assert "LEGACY_FRAMES_ADAPTED" in html
    assert "function handPerformanceFor(data)" in html
    assert "await renderer.setPerformance(performanceData);" in html


def test_host_uses_only_versioned_transport_and_absolute_clock() -> None:
    """The iframe consumes parent transport; it owns no alternate animation path."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert html.count("addEventListener('message'") == 1
    assert "fretwise:load" in html
    assert "fretwise:transport" in html
    assert "HAND_TRANSPORT.timeAt(now)" in html
    assert "HAND_TRANSPORT.isDesynced(now)" in html


def test_top_projection_control_is_retained_for_3d_renderer() -> None:
    """Top view remains a camera preset of the same Three.js renderer."""
    html = _HAND_VIZ.read_text(encoding="utf-8")

    assert 'id="btn-top-view"' in html
    assert 'aria-pressed="false"' in html
    assert "camera = 'top'" in html
    assert "renderer?.setCameraView(camera)" in html


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
@pytest.mark.parametrize("path", [_HAND_V2_JS, _THREE_JS])
def test_current_renderer_modules_are_syntax_clean(path: Path) -> None:
    """Current ES modules parse in Node."""
    proc = subprocess.run(
        [shutil.which("node") or "node", "--input-type=module", "--check"],
        input=path.read_text(encoding="utf-8", errors="ignore"),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
    )
    assert proc.returncode == 0, f"{path.name} syntax error:\n{proc.stderr}"
