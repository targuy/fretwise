"""Projection-contract guards for HandPerformance v2 camera views."""

from __future__ import annotations

import json
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
    assert "Math.max(TOP_VIEW_HEIGHT, 220 / aspect) * this.zoom / 2" in projection
    assert "this.camera.left = -halfHeight * aspect" in projection
    assert "this.camera.right = halfHeight * aspect" in projection
    resize = source[source.index("resize() {"):source.index("\n  dispose() {")]
    assert "this._updateProjection()" in resize


def test_top_projection_has_readable_fingering_scale() -> None:
    """Top view magnifies finger contacts while preserving a mobile hand span."""
    source = _source()
    assert "const TOP_VIEW_HEIGHT = 150" in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_top_camera_stability_shifts_seeks_and_resize() -> None:
    """The top camera stays put in frame and pans smoothly at its edges."""
    script = f"import {{topCameraFocus as focus}} from {json.dumps(_HAND_V2.as_uri())};" + """
const initial = focus(null, 30, 110, 150, 0);
let held = initial;
for(let i=1;i<=120;i++) held=focus(held, 35+i%8, 105-i%9, 150, i/60);
const nearEdge=focus(held, -40, 190, 150, 2+1/60);
const shifted = focus(held, 250, 330, 150, 2+1/60);
let settled=shifted;
for(let i=2;i<=180;i++) settled=focus(settled,250,330,150,2+i/60);
const paused=focus(settled,120,200,150,settled.time);
const backward=focus(settled,300,360,150,1);
const forward=focus(held,300,360,150,10);
const resized=focus(held,30,140,55,held.time);
console.log(JSON.stringify({initial,held,nearEdge,shifted,settled,paused,backward,forward,resized}));
"""
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["held"]["x"] == result["initial"]["x"] == 70
    assert result["nearEdge"]["x"] == 70
    assert 70 < result["shifted"]["x"] < 90
    assert result["shifted"]["x"] - 70 <= 450 / 60
    assert result["settled"]["x"] == pytest.approx(225, abs=.01)
    assert result["paused"] == result["settled"]
    assert result["backward"]["x"] == result["settled"]["x"]
    assert 70 < result["forward"]["x"] < 255
    assert result["resized"]["x"] == 70


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_perspective_camera_only_pans_when_projected_fingers_leave_view() -> None:
    """Screen-space bounds, including vertical movement, control perspective pans."""
    script = f"import {{cameraPanDelta}} from {json.dumps(_HAND_V2.as_uri())};" + """
const point=(x,y)=>({x,y,halfWidth:100,halfHeight:50});
const inside=cameraPanDelta([point(-.8,.7),point(.82,-.85)]);
const contactChanged=cameraPanDelta([point(-.8,.7),point(.82,-.85),point(.4,.3)]);
const right=cameraPanDelta([point(1.05,.2)]);
const left=cameraPanDelta([point(-1.05,.2)]);
const up=cameraPanDelta([point(0,1.2)]);
const both=cameraPanDelta([point(-1.1,0),point(1.1,0)]);
console.log(JSON.stringify({inside,contactChanged,right,left,up,both}));
"""
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    result = json.loads(proc.stdout)
    assert result["inside"] == result["contactChanged"] == {"x": 0, "y": 0}
    assert result["right"] == {"x": pytest.approx(35), "y": 0}
    assert result["left"] == {"x": pytest.approx(-35), "y": 0}
    assert result["up"] == {"x": 0, "y": pytest.approx(25)}
    assert result["both"] == {"x": 0, "y": 0}


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_perspective_distance_is_continuous_across_mobile_breakpoint() -> None:
    """A one-pixel resize near 480 px cannot jump the whole neck by 48 mm."""
    script = (
        f"import {{perspectiveCameraDistance as distance}} from {json.dumps(_HAND_V2.as_uri())};"
        "console.log(JSON.stringify([distance(360),distance(479),distance(480),"
        "distance(481),distance(600),distance(480,2)]));"
    )
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    low, before, at, after, high, zoomed = json.loads(proc.stdout)
    assert low == 312
    assert high == 264
    assert before > at > after
    assert before - after < 1
    assert zoomed == 2 * at


def test_top_view_cannot_be_tilted_by_pointer_drag() -> None:
    """Plan view remains exactly 90 degrees after user interaction."""
    source = _source()
    assert 'if (this.cameraView === "top") { point = [e.clientX, e.clientY]; return; }' in source


@pytest.mark.skipif(shutil.which("node") is None, reason="node not available")
def test_embedded_viewport_excludes_fixed_transport_toolbar() -> None:
    """Canvas height must describe the visible area on desktop and mobile."""
    source = (_HAND_V2.parent / "main.js").read_text(encoding="utf-8")
    start = source.index("function resizeHand3dViewport() {")
    function = source[start:source.index("\nconst hand3dViewportObserver", start)]
    script = """
let top=227, parentBottom=1064, footerTop=987, footerHeight=93;
const window={innerHeight:1080};
const toolbar={getBoundingClientRect:()=>({top:footerTop,height:footerHeight})};
const hand3dViewFrame={style:{display:'block'},getBoundingClientRect:()=>({top}),
 parentElement:{clientTop:0,get clientHeight(){return parentBottom-top;},
 getBoundingClientRect:()=>({top})}};
""" + function + """
resizeHand3dViewport();const desktop=hand3dViewFrame.style.height;
top=223;parentBottom=828;footerTop=743;footerHeight=101;window.innerHeight=844;
resizeHand3dViewport();const mobile=hand3dViewFrame.style.height;
footerHeight=0;resizeHand3dViewport();const hiddenToolbar=hand3dViewFrame.style.height;
hand3dViewFrame.style.display='none';top=0;resizeHand3dViewport();
console.log(JSON.stringify({desktop,mobile,hiddenToolbar,hiddenFrame:hand3dViewFrame.style.height}));
"""
    proc = subprocess.run(
        [shutil.which("node"), "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
    )
    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout) == {
        "desktop": "760px", "mobile": "520px",
        "hiddenToolbar": "605px", "hiddenFrame": "605px",
    }


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
