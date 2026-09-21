"""Projection-contract guards for HandPerformance v2 camera views."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HAND_V2 = (
    Path(__file__).parents[1]
    / "src"
    / "fretwise"
    / "web"
    / "static"
    / "js"
    / "hand_v2.js"
)


def _source() -> str:
    return _HAND_V2.read_text(encoding="utf-8")


def test_top_camera_is_true_orthographic_projection() -> None:
    """Top view uses its own orthographic camera, never perspective-at-distance."""
    source = _source()
    assert "new THREE.PerspectiveCamera" in source
    assert "new THREE.OrthographicCamera" in source
    assert 'this.cameraView === "top"' in source
    assert "this.camera = this.topCamera" in source
    assert 'getCameraProjection()' in source
    assert '"orthographic" : "perspective"' in source


def test_top_camera_is_normal_to_fretboard_and_keeps_neck_horizontal() -> None:
    """90-degree view follows transformed board axes, including world rotation."""
    source = _source()
    assert "V(0, 1, 0).applyQuaternion(this.world.quaternion)" in source
    assert "addScaledVector(boardNormal, TOP_CAMERA_DISTANCE)" in source
    assert "V(0, 0, 1).applyQuaternion(this.world.quaternion)" in source
    assert "this.camera.up.copy(screenUp)" in source


def test_camera_api_accepts_face_and_top_and_rejects_unknown_views() -> None:
    """Host can switch explicitly between face/perspective and top/orthographic."""
    source = _source()
    assert "const cameras = {face:" in source
    assert "top: null" in source
    assert "if (!(view in cameras)) return false;" in source
    assert "setCameraView(view) { return this.setCamera(view); }" in source
    camera_api = source[source.index("setCamera(view) {"):source.index("setCameraView(view)")]
    assert "return true;" in camera_api


def test_resize_recomputes_orthographic_frustum_from_live_aspect() -> None:
    """Resize changes left/right bounds while preserving vertical top-view scale."""
    source = _source()
    projection = source[source.index("_updateProjection() {"):source.index("\n  resize() {")]
    assert "const aspect = width / height;" in projection
    assert "const halfHeight = TOP_VIEW_HEIGHT * this.zoom / 2;" in projection
    assert "this.camera.left = -halfHeight * aspect" in projection
    assert "this.camera.right = halfHeight * aspect" in projection
    resize = source[source.index("resize() {"):source.index("\n  dispose() {")]
    assert "this._updateProjection()" in resize


def test_top_view_cannot_be_tilted_by_pointer_drag() -> None:
    """Plan view remains exactly 90 degrees after user interaction."""
    source = _source()
    assert 'if (this.cameraView === "top") { point = [e.clientX, e.clientY]; return; }' in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_hand_v2_module_is_syntax_clean() -> None:
    """Shipped camera implementation remains valid ES-module syntax."""
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "--check"],
        input=_source(),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
