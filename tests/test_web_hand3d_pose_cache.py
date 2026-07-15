"""Deferred-rendering pose cache for the articulated 3D hand (Lot D — perf).

WHY THIS EXISTS
---------------
The articulated fretting-hand rig (``hand3d.js``) is CPU-bound, not GPU-bound:
posing one frame runs a per-finger CCD fold-to-contact solve (up to 6 passes ×
3 joints × ~100 one-degree steps, each doing a full ``updateMatrixWorld`` + an
8-sample neck-collision test) times ~5 fingers times up to 10 wrist-compensation
re-folds — hundreds of thousands of matrix ops per frame.  Driven every
``requestAnimationFrame`` during playback, it blows the frame budget and the
panel appears frozen/choppy.  Rendering (a handful of tube meshes) is trivial.

THE FIX: the converged pose is a deterministic pure function of the fingering
signature + hand position, so we solve each DISTINCT shape ONCE via
``PoseCache.resolve`` and let the render loop replay the cached keyframe cheaply.
A shape held across N frames must trigger exactly ONE solve, not N.

WHAT THESE TESTS PROVE
----------------------
``PoseCache.resolve`` is the gate the whole fix hinges on, so we execute the real
``pose_cache.js`` in Node and assert the call-count contract directly: an
N-frame hold triggers one solve; a repeated shape re-uses the cache; distinct
shapes each solve once; and the LRU bound holds.  This is the "assert the solver
was called ONCE, not N times" test the perf fix is defined against — it does not
need a GPU/WebGL context (which CI lacks), because the gate is pure logic.

The real ``hand3d.js`` cannot be imported in plain Node (it imports three.js,
which needs a DOM/WebGL context), so the shipped wiring — that
``_updateArticulated`` actually routes through ``_poseCache.resolve`` and that the
look-ahead prefill calls ``warmPose`` — is pinned by the static source guards at
the bottom, connecting the tested gate to the code that uses it.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.web.app import create_app

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_POSE_CACHE_JS = _STATIC_DIR / "js" / "pose_cache.js"
_HAND3D_JS = _STATIC_DIR / "js" / "hand3d.js"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run(script: str) -> dict:
    """Execute a Node snippet with PoseCache imported; return its JSON stdout."""
    # A file:// URL, not a bare path: Node rejects absolute Windows paths as ESM
    # specifiers (the drive letter reads as a scheme).  Mirrors test_web_track_balance.
    harness = f"""
import {{ PoseCache }} from {json.dumps(_POSE_CACHE_JS.as_uri())};
{script}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


# --------------------------------------------------------------------------- #
# Behavioural — the solve-once-per-shape gate (executes the real pose_cache.js). #
# --------------------------------------------------------------------------- #
def test_held_shape_solves_once_not_once_per_frame() -> None:
    """A shape held across N frames triggers exactly ONE solve (the perf fix).

    This is the core regression guard: without the cache, the render loop would
    re-run the expensive CCD solve every one of the 120 frames.  With it, the
    first frame solves and the other 119 replay the cached keyframe.
    """
    out = _run(
        """
        let solveCalls = 0;
        const cache = new PoseCache(512);
        // Mirror hand3d.js's _updateArticulated gate: resolve(key, solveFn) —
        // the expensive solve runs only on a cache miss; a cheap replay uses
        // the cached keyframe otherwise.
        function frame(sig) {
          const key = sig + "#5:2";   // signature + hand-position, as hand3d keys it
          return cache.resolve(key, () => { solveCalls++; return { sig }; });
        }
        for (let i = 0; i < 120; i++) frame("iA5:6|mA6:5|r-|p-");
        console.log(JSON.stringify({
          solveCalls, hits: cache.hits, misses: cache.misses, size: cache.size,
        }));
        """
    )
    assert out["solveCalls"] == 1, "the solver ran per-frame instead of once per shape"
    assert out["misses"] == 1
    assert out["hits"] == 119, "119 of 120 held frames must be cheap cache hits"
    assert out["size"] == 1


def test_distinct_shapes_each_solve_once_and_repeats_are_free() -> None:
    """Each distinct shape solves once; returning to a prior shape is a cache hit."""
    out = _run(
        """
        let solveCalls = 0;
        const cache = new PoseCache(512);
        function frame(sig) {
          return cache.resolve(sig + "#5:2", () => { solveCalls++; return { sig }; });
        }
        for (let i = 0; i < 60; i++) frame("A");   // shape A, held
        const afterA = solveCalls;
        for (let i = 0; i < 60; i++) frame("B");   // shape B, held
        for (let i = 0; i < 60; i++) frame("C");   // shape C, held
        for (let i = 0; i < 30; i++) frame("A");   // back to A — must be cached
        console.log(JSON.stringify({
          afterA, total: solveCalls, hits: cache.hits, misses: cache.misses,
        }));
        """
    )
    assert out["afterA"] == 1, "shape A must solve once even held 60 frames"
    assert out["total"] == 3, "3 distinct shapes -> 3 solves; the A-reprise is free"
    assert out["misses"] == 3
    # 59 (A) + 59 (B) + 59 (C) + 30 (A reprise) = 207 cheap replays.
    assert out["hits"] == 207


def test_resolve_does_not_call_solver_on_a_hit() -> None:
    """resolve() must not invoke solveFn when the key is already present."""
    out = _run(
        """
        let calls = 0;
        const cache = new PoseCache();
        const a = cache.resolve("k", () => { calls++; return 1; });
        const b = cache.resolve("k", () => { calls++; return 2; });
        console.log(JSON.stringify({ calls, a, b }));
        """
    )
    assert out["calls"] == 1, "solveFn must run once; the 2nd resolve is a hit"
    assert out["a"] == 1
    assert out["b"] == 1, "a hit returns the FIRST solved value, not a re-solve"


def test_cache_is_lru_bounded() -> None:
    """The cache evicts the least-recently-used entry past maxEntries (bounded RAM)."""
    out = _run(
        """
        const cache = new PoseCache(4);
        for (let i = 0; i < 4; i++) cache.resolve("k" + i, () => i);
        cache.get("k0");                       // touch k0 -> now most-recent
        cache.resolve("k4", () => 4);          // overflow -> evict LRU (k1, not k0)
        console.log(JSON.stringify({
          size: cache.size, hasK0: cache.has("k0"), hasK1: cache.has("k1"), hasK4: cache.has("k4"),
        }));
        """
    )
    assert out["size"] == 4, "the cache must stay bounded at maxEntries"
    assert out["hasK0"] is True, "recently-used entry must survive eviction"
    assert out["hasK1"] is False, "the least-recently-used entry must be evicted"
    assert out["hasK4"] is True


# --------------------------------------------------------------------------- #
# Static wiring guards — connect the tested gate to the shipped code.          #
# (hand3d.js can't be imported in Node: it pulls three.js/WebGL.)              #
# --------------------------------------------------------------------------- #
def test_hand3d_routes_through_the_pose_cache() -> None:
    """hand3d.js imports PoseCache and gates the per-frame solve through it."""
    h3d = _HAND3D_JS.read_text(encoding="utf-8")
    assert 'from "./pose_cache.js"' in h3d, "hand3d.js must import the pose cache module"
    assert "this._poseCache = new PoseCache" in h3d
    # The expensive solve must be reached ONLY via the cache's resolve() gate.
    assert "this._poseCache.resolve(" in h3d
    assert "_solveConvergedPose(" in h3d
    # The cheap replay path (output-space easing of the cached keyframe) exists.
    assert "_easeAndApplyPose(" in h3d
    # The look-ahead prefill entry point exists.
    assert "warmPose(kin)" in h3d


def test_hand_viz_prefills_upcoming_poses() -> None:
    """hand_viz.html warms the cache ahead of the playhead during idle time."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    assert "_scheduleHandPosePrefill(" in html
    assert "HAND3D_RENDERER.warmPose(" in html
    # The prefill must run off the critical path (idle callback), not inline.
    assert "requestIdleCallback" in html


def test_pose_cache_module_is_served() -> None:
    """The app serves /static/js/pose_cache.js so hand3d.js's import resolves."""
    client = TestClient(create_app())
    res = client.get("/static/js/pose_cache.js")
    assert res.status_code == 200
    assert "export class PoseCache" in res.text
