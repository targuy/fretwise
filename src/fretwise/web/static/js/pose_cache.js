/* ============================================================================
   FretWise — pose cache for the articulated 3D hand (hand3d.js).

   WHY THIS EXISTS (performance):
     The articulated fretting-hand rig is CPU-bound, not GPU-bound.  Posing one
     frame runs a per-finger CCD fold-to-contact solve — for each finger, up to
     CCD_PASSES (6) passes over 3 joints, each brute-force scanning ~90-110
     one-degree steps, and every candidate step does a full updateMatrixWorld()
     plus an 8-sample-per-segment neck-collision test.  That inner loop runs
     thousands of times per finger, times ~5 fingers, times up to
     WRIST_COMP_TRIES (10) wrist-compensation re-folds — i.e. hundreds of
     thousands of matrix ops PER FRAME.  Driven every requestAnimationFrame
     (~60x/s) during playback, it blows the frame budget and the panel appears
     frozen/choppy.  The rendering itself (a handful of tube meshes, one draw
     call each) is trivially cheap by comparison.

     KEY INSIGHT: the converged pose is a DETERMINISTIC pure function of the
     fingering signature (per-finger role + fret + strings) plus the resolved
     hand position (index fret + player-most string).  The same shape always
     folds to the same joint angles.  So we solve each DISTINCT shape exactly
     ONCE, cache the converged keyframe, and let the per-frame render loop
     REPLAY it (cheap output-space easing between keyframes) instead of
     re-running the solver live.  Repeated shapes (very common in music) and
     held notes cost nothing after the first solve; the look-ahead warmer can
     even fill the cache before the playhead arrives.

   This module is intentionally DEPENDENCY-FREE (no three.js, no DOM) so it can
   be unit-tested in plain Node and imported by hand3d.js without pulling WebGL.
   ============================================================================ */

/* A small LRU-bounded keyframe cache.

   `resolve(key, solveFn)` is the gate that the performance fix hinges on:
   `solveFn` (the expensive CCD/wrist-compensation solve) is invoked ONLY on a
   cache miss.  On a hit the cached value is returned and `solveFn` is never
   called — so a shape held across N frames triggers exactly ONE solve, not N.
   `hits` / `misses` / `solves` are exposed for tests and the in-browser
   diagnostics overlay. */
export class PoseCache {
  constructor(maxEntries = 512) {
    this.maxEntries = maxEntries > 0 ? maxEntries : 512;
    this._map = new Map();
    this.hits = 0;
    this.misses = 0;
    this.solves = 0;
  }

  has(key) {
    return this._map.has(key);
  }

  /* Read + mark as most-recently-used (so the LRU eviction below keeps hot
     shapes and drops shapes not seen for a long while). */
  get(key) {
    const value = this._map.get(key);
    if (value !== undefined) {
      this._map.delete(key);
      this._map.set(key, value);
    }
    return value;
  }

  set(key, value) {
    if (this._map.has(key)) this._map.delete(key);
    this._map.set(key, value);
    while (this._map.size > this.maxEntries) {
      const oldest = this._map.keys().next().value;
      this._map.delete(oldest);
    }
    return value;
  }

  /* THE GATE.  Return the cached keyframe for `key`, computing (and caching) it
     via `solveFn` only when absent.  This is what turns an N-frame hold into a
     single solve. */
  resolve(key, solveFn) {
    if (this._map.has(key)) {
      this.hits++;
      return this.get(key);
    }
    this.misses++;
    this.solves++;
    const value = solveFn();
    this.set(key, value);
    return value;
  }

  clear() {
    this._map.clear();
    this.hits = 0;
    this.misses = 0;
    this.solves = 0;
  }

  get size() {
    return this._map.size;
  }
}
