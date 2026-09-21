/**
 * rain-renderer.js - Falling-notes playback view over a horizontal fretboard.
 *
 * Frontend-only view: it consumes the same `/api/solve` payload as TabRenderer
 * (via the tablature solve) and samples the PlaybackEngine clock on every
 * animation frame, exactly like SlopeRenderer. The screen shows a guitar neck
 * along the bottom (frets 0-22 left to right, high-e string on top, low-E at
 * the bottom) and fluo note bars falling straight down: a bar's colour is the
 * fingering, its length is the duration, and its bottom edge touches its
 * string on the neck at the exact onset beat.
 */

const FINGER_META = {
  open: { label: '0', color: '#d9d6cc', discColor: '#fffdf2' },
  index: { label: 'i', color: '#ffd44d', discColor: '#fff4bd' },
  middle: { label: 'm', color: '#60c060', discColor: '#dcf2dc' },
  ring: { label: 'r', color: '#6090e0', discColor: '#dce9ff' },
  pinky: { label: 'p', color: '#c060c0', discColor: '#f2dcf2' },
};

const MEASURE_BEATS = 4;
// Density slider bounds, in beats of upcoming notes visible vertically.
// Rain's usable fall height is a single screen (no folded path like Slope),
// so the range sits far below Slope's 24-48: below MIN the bars stretch so
// long they overlap their own lane, above MAX everything compresses into
// confetti at the top of the screen.
const MIN_DENSITY_BEATS = 8;
const MAX_DENSITY_BEATS = 24;
const DEFAULT_DENSITY_BEATS = 12;
const STRING_COLLISION_GAP_BEATS = 0.18;
const TARGET_FRAME_MS = 1000 / 60;
const MAX_RENDER_DPR = 3;
const MIN_ACCEPTABLE_FRAME_MS = 1000 / 50;
const HIGH_QUALITY_FRAME_MS = 1000 / 60;
const LOW_QUALITY_FRAME_MS = 1000 / 42;
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
const STRING_OPEN_MIDI = {
  1: 64, // high E
  2: 59,
  3: 55,
  4: 50,
  5: 45,
  6: 40, // low E
};
const STRING_NAMES = {
  1: 'e',
  2: 'B',
  3: 'G',
  4: 'D',
  5: 'A',
  6: 'E',
};
const FRET_COUNT = 22; // cells 0..22 -> 23 columns (0 = open strings)
// Single inlay dots plus the double dot at 12 — standard fingerboard markers.
const INLAY_FRETS = [3, 5, 7, 9, 15, 17, 19, 21];

// ── Minimum-size floor ────────────────────────────────────────────────
// The fixed bottom toolbar (footer#toolbar, grid-template-rows: 28px 64px)
// physically overlaps the bottom ~92px of this canvas (it fills its
// container's full padding box, same as SlopeRenderer) — reserve enough
// clearance that the neck/fret-numbers never render behind it.
const BOTTOM_UI_CLEARANCE_PX = 100;
const NUMBERS_H = 24;
const NECK_MIN_H = 120;
const NECK_MAX_H = 200;
// Below this, the fall zone is too cramped to read a bar's motion at all.
const MIN_FALL_ZONE_H = 120;
// Hard floor: below it we stop shrinking further and let the container
// scroll instead (both #tab-container axes already have overflow:auto).
const MIN_TOTAL_HEIGHT = BOTTOM_UI_CLEARANCE_PX + NUMBERS_H + NECK_MIN_H + MIN_FALL_ZONE_H;
// Narrowest a fret cell may get before cell width stops shrinking and the
// neck instead grows wider than its container (horizontal scroll for the
// cells that don't fit) — guarantees at least ~6 cells stay visible without
// scrolling on any realistic viewport width.
const MIN_CELL_W = 34;
// Worst-case margin (see _rainGeometry's marginL, capped at 46, plus the
// fixed 14px right margin) used only to size this floor — a rough bound is
// fine since this merely decides whether horizontal scroll kicks in.
const MIN_TOTAL_WIDTH = 46 + 14 + MIN_CELL_W * (FRET_COUNT + 1);

export class RainRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {Object} data
   */
  constructor(canvas, data) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.data = data || {};
    this.results = Array.isArray(data?.results) ? data.results : [];
    this.tempo = data?.tempo || 120;
    this.bpm = data?.beats_per_measure || 4;
    this.currentBeat = 0;
    this.visible = false;
    this.futureBeats = DEFAULT_DENSITY_BEATS;
    this.dpr = window.devicePixelRatio || 1;
    this.playback = null;
    this._lastSeconds = 0;
    this._raf = null;
    this._quality = 0;
    this._slowFrames = 0;
    this._fastFrames = 0;
    this._lastFrameTs = 0;
    this._lastRenderMs = 0;
    this._backgroundCanvas = null;
    this._backgroundKey = '';
    this._hitFlashes = [];
    this.notes = this._applyStringCollisionGuard(this.results);
    this.chordEvents = this._buildChordEvents();
    this._totalBeatsValue = this._computeTotalBeats();
    this._measureBoundaryBeatsValue = this._computeMeasureBoundaryBeats();
    this._geometry = null;
    this._geometryKey = '';
    this.canvas.__fretwiseRainRenderer = this;
    this._onResize = () => this.resize();
    window.addEventListener('resize', this._onResize);
    this.resize();
  }

  destroy() {
    this._stopAnimationLoop();
    if (this.canvas.__fretwiseRainRenderer === this) {
      delete this.canvas.__fretwiseRainRenderer;
    }
    window.removeEventListener('resize', this._onResize);
  }

  getPerformanceStats() {
    return {
      quality: this._quality,
      dpr: this.dpr,
      lastRenderMs: Math.round(this._lastRenderMs * 10) / 10,
      targetMinFps: 50,
      animationRunning: !!this._raf,
    };
  }

  resize() {
    // Read the CONTAINER's box, not the canvas's own — once we start
    // enforcing a minimum content size below, the canvas can end up bigger
    // than its container (that's the point: #tab-container's overflow:auto
    // then scrolls it). Reading the canvas's own rect after that would be
    // self-referential and could never shrink back down on a later resize.
    const container = this.canvas.parentElement;
    const rect = (container || this.canvas).getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.dpr = this._renderDpr();
    // Never shrink below the size that guarantees all 6 strings (height) and
    // at least ~6 fret cells (width) stay legible — past that floor we grow
    // the canvas past its container instead, and its container scrolls.
    const cssW = Math.max(rect.width, MIN_TOTAL_WIDTH);
    const cssH = Math.max(rect.height, MIN_TOTAL_HEIGHT);
    // Device-pixel-exact backing store + CSS box pinned to the exact same
    // size — same rationale as SlopeRenderer.resize(): any sub-pixel drift
    // between the two makes the compositor resample the whole canvas each
    // frame, blurring exactly the high-frequency edges we draw.
    const bw = Math.max(1, Math.floor(cssW * this.dpr));
    const bh = Math.max(1, Math.floor(cssH * this.dpr));
    this.canvas.width = bw;
    this.canvas.height = bh;
    this.canvas.style.width = `${bw / this.dpr}px`;
    this.canvas.style.height = `${bh / this.dpr}px`;
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this.ctx.imageSmoothingEnabled = false;
    this._geometry = null;
    this._geometryKey = '';
    this._invalidateStaticCache();
    this.render();
  }

  setVisible(on) {
    this.visible = !!on;
    this.canvas.style.display = on ? 'block' : 'none';
    if (on) {
      this.resize();
      this._startAnimationLoop();
    } else {
      this._stopAnimationLoop();
    }
  }

  /* Density: how many beats of upcoming notes span the fall zone. Clamped so
     an extreme value can't stretch bars past their own lane (too few beats)
     or shrink them into specks (too many). No cache to invalidate: the fall
     geometry does not depend on futureBeats, only the per-frame y mapping. */
  setDensity(beats) {
    const n = Number(beats);
    if (!Number.isFinite(n)) return;
    this.futureBeats = Math.max(MIN_DENSITY_BEATS, Math.min(MAX_DENSITY_BEATS, n));
  }

  bindPlayback(playback) {
    this.playback = playback || null;
    if (this.visible) this._startAnimationLoop();
  }

  setSpeed(speed) {
    this._lastSpeed = speed || 1;
  }

  _renderDpr() {
    // The backing store must always match the true device pixel ratio —
    // draw-cost is shed on shadows/glow (gated on this._quality), never on
    // resolution. See SlopeRenderer._renderDpr for the full rationale.
    return Math.min(MAX_RENDER_DPR, window.devicePixelRatio || 1);
  }

  _invalidateStaticCache() {
    this._backgroundCanvas = null;
    this._backgroundKey = '';
  }

  _startAnimationLoop() {
    if (this._raf || !this.visible || !this.playback?.isPlaying) return;
    this._lastFrameTs = 0;
    this._raf = requestAnimationFrame((ts) => this._animationFrame(ts));
  }

  _stopAnimationLoop() {
    if (!this._raf) return;
    cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  _animationFrame(ts) {
    this._raf = null;
    if (!this.visible) return;

    const frameGap = this._lastFrameTs ? ts - this._lastFrameTs : TARGET_FRAME_MS;
    this._lastFrameTs = ts;
    const started = performance.now();
    const previousBeat = this.currentBeat;
    if (this.playback) this._syncFromSeconds(this.playback.getCurrentTimeSec(), this.playback);
    else this._syncFromSeconds(this._lastSeconds, null);
    if (this.playback?.isPlaying && frameGap > TARGET_FRAME_MS * 0.82) {
      this._captureCrossedHits(previousBeat, this.currentBeat);
    }
    this.render();
    this._lastRenderMs = performance.now() - started;
    this._updateAdaptiveQuality(frameGap, this._lastRenderMs);

    if (this.playback?.isPlaying) {
      this._raf = requestAnimationFrame((nextTs) => this._animationFrame(nextTs));
    }
  }

  _updateAdaptiveQuality(frameGap, renderMs) {
    if (frameGap > MIN_ACCEPTABLE_FRAME_MS || renderMs > HIGH_QUALITY_FRAME_MS) {
      this._slowFrames += 1;
      this._fastFrames = 0;
    } else {
      this._fastFrames += 1;
      this._slowFrames = 0;
    }

    if ((this._slowFrames >= 3 || renderMs > LOW_QUALITY_FRAME_MS) && this._quality < 2) {
      this._quality += 1;
      this._slowFrames = 0;
      const oldDpr = this.dpr;
      this.dpr = this._renderDpr();
      if (Math.abs(this.dpr - oldDpr) > 0.01) this.resize();
      else this._invalidateStaticCache();
    } else if (this._fastFrames >= 90 && this._quality > 0) {
      this._quality -= 1;
      this._fastFrames = 0;
      this.resize();
    }
  }

  _syncFromSeconds(seconds, playback) {
    const secPerBeat = playback?._secPerBeat || (60 / this.tempo);
    const baseBeat = playback?._measureBaseBeat || 0;
    const totalBeats = this._totalBeats();
    this._lastSeconds = Number(seconds) || 0;
    this.currentBeat = (baseBeat + this._lastSeconds / secPerBeat) % totalBeats;
    if (this.currentBeat < 0) this.currentBeat += totalBeats;
  }

  /**
   * Sync this view from the audio/playback clock.
   *
   * @param {number} seconds
   * @param {import('./playback.js').PlaybackEngine} playback
   */
  setPlaybackTime(seconds, playback) {
    if (playback) this.bindPlayback(playback);
    this._syncFromSeconds(seconds, playback || this.playback);
    if (this.visible && !this.playback?.isPlaying) this.render();
  }

  render() {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    if (!w || !h) return;
    this._drawBackground(w, h);
    this._drawMeasureBars();
    const visible = this._visibleNotesForFrame();
    this._drawFallLanes(visible);
    for (const note of visible) this._drawNoteBar(note);
    this._drawChordLabels(visible);
    this._drawHitFlashes();
    this._drawTempoHeart();
  }

  _totalBeats() {
    return this._totalBeatsValue || this._computeTotalBeats();
  }

  _computeTotalBeats() {
    const maxNote = this.notes.reduce((mx, n) => Math.max(mx, n.onset + n.duration), 0);
    const measureBeats = Array.isArray(this.data.measure_beats)
      ? this.data.measure_beats.reduce((sum, b) => sum + (Number(b) || 0), 0)
      : 0;
    return Math.max(MEASURE_BEATS, measureBeats, Math.ceil(maxNote / MEASURE_BEATS) * MEASURE_BEATS);
  }

  _applyStringCollisionGuard(notes) {
    const totalBeats = Math.max(MEASURE_BEATS, Math.ceil(
      notes.reduce((mx, n) => Math.max(mx, Number(n.onset || 0) + Number(n.duration || 0)), 0)
      / MEASURE_BEATS,
    ) * MEASURE_BEATS);
    const guarded = notes
      .map((note, order) => {
        const stringNum = Number(note.string || note.string_num || 1);
        const fret = Number(note.fret || 0);
        const pitch = this._pitchForNote(note, stringNum, fret);
        return {
          ...note,
          onset: Number(note.onset || 0),
          duration: Math.max(0.05, Number(note.duration || 0.25)),
          string: stringNum,
          fret,
          pitch,
          noteName: this._noteNameForPitch(pitch),
          order,
        };
      })
      .filter((note) => note.string >= 1 && note.string <= 6)
      .sort((a, b) => a.onset - b.onset || a.string - b.string || a.order - b.order);

    for (let stringNum = 1; stringNum <= 6; stringNum += 1) {
      const onString = guarded.filter((note) => note.string === stringNum);
      onString.forEach((note, index) => {
        const next = onString[(index + 1) % onString.length];
        if (!next) return;
        const nextOnset = next.onset <= note.onset ? next.onset + totalBeats : next.onset;
        const maxDuration = Math.max(0.05, nextOnset - note.onset - STRING_COLLISION_GAP_BEATS);
        note.duration = Math.min(note.duration, maxDuration);
      });
    }

    return guarded.sort((a, b) => a.order - b.order).map(({ order, ...note }) => note);
  }

  _buildChordEvents() {
    const markers = this.data.chord_markers || {};
    const byKey = new Map();
    const markerFor = (onset) => (
      markers[String(onset)]
      || markers[Number(onset).toFixed(1)]
      || markers[Number(onset).toFixed(2)]
      || markers[Number(onset).toFixed(6)]
      || ''
    );
    for (const note of this.notes) {
      const label = note.chord || markerFor(note.onset);
      if (!label) continue;
      const key = `${note.onset.toFixed(6)}:${label}`;
      const entry = byKey.get(key) || { label, onset: note.onset, duration: note.duration };
      entry.duration = Math.max(entry.duration, note.duration);
      byKey.set(key, entry);
      note.chord = label;
    }
    return Array.from(byKey.values()).sort((a, b) => a.onset - b.onset);
  }

  _pitchForNote(note, stringNum, fret) {
    const direct = Number(note.pitch);
    if (Number.isFinite(direct)) return direct;
    const openPitch = STRING_OPEN_MIDI[stringNum];
    return Number.isFinite(openPitch) ? openPitch + fret : null;
  }

  _noteNameForPitch(pitch) {
    if (!Number.isFinite(pitch)) return '';
    return NOTE_NAMES[((Math.round(pitch) % 12) + 12) % 12];
  }

  _clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  _snapPx(v) {
    const dpr = this.dpr || 1;
    return Math.round(v * dpr) / dpr;
  }

  /* ── Geometry ──────────────────────────────────────────────────────── */

  /* Static screen layout: the neck band at the bottom (6 string lines, 23
     uniform fret cells), the fret-number strip below it, and the fall zone
     above. Cached per canvas size. */
  _rainGeometry() {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const key = `${Math.round(w)}:${Math.round(h)}`;
    if (this._geometry && this._geometryKey === key) return this._geometry;

    const neckH = this._clamp(h * 0.22, NECK_MIN_H, NECK_MAX_H);
    // Reserve BOTTOM_UI_CLEARANCE_PX below the numbers strip: the fixed
    // footer toolbar overlaps that band of the canvas (see resize()), so
    // without this the neck/numbers render behind it and are invisible.
    const neckBottom = h - BOTTOM_UI_CLEARANCE_PX - NUMBERS_H;
    const neckTop = neckBottom - neckH;
    // Left margin hosts the string letters (e/B/G/D/A/E); right margin is
    // symmetric-ish padding after the last fret cell.
    const marginL = Math.max(30, Math.min(46, w * 0.03));
    const marginR = 14;
    // Floored at MIN_CELL_W: resize() already grows the canvas past its
    // container once the natural width would fall below that floor, so this
    // max() is a defensive consistency guard, not the primary enforcement.
    const cellW = Math.max(MIN_CELL_W, (w - marginL - marginR) / (FRET_COUNT + 1));
    const stringPad = Math.max(10, neckH * 0.09);
    const stringGap = (neckH - stringPad * 2) / 5;

    const geometry = {
      w,
      h,
      neckTop,
      neckBottom,
      neckH,
      numbersY: neckBottom + NUMBERS_H / 2 + 1,
      marginL,
      cellW,
      stringPad,
      stringGap,
    };
    this._geometry = geometry;
    this._geometryKey = key;
    return geometry;
  }

  _fretLeft(fret) {
    const g = this._rainGeometry();
    return g.marginL + fret * g.cellW;
  }

  /* Landing y of a string on the neck: string 1 (high e) is the TOP line. */
  _stringY(stringNum) {
    const g = this._rainGeometry();
    return g.neckTop + g.stringPad + (this._clamp(stringNum, 1, 6) - 1) * g.stringGap;
  }

  /* Fall-lane x of a (string, fret) pair: each fret cell is subdivided by
     string — high e leftmost, low E rightmost — so two notes on the same
     fret but different strings never share a column, and the lane points at
     its exact string×fret intersection on the neck. */
  _laneX(stringNum, fret) {
    const g = this._rainGeometry();
    const f = this._clamp(fret, 0, FRET_COUNT);
    return this._fretLeft(f) + g.cellW * (0.15 + 0.7 * (this._clamp(stringNum, 1, 6) - 1) / 5);
  }

  /* Beats-to-pixels, PER STRING: each string's rate is its own landing y
     divided by futureBeats, so every note crosses y=0 exactly futureBeats
     before its onset regardless of which string it lands on. A single
     shared rate (e.g. always string 1's) would make lower strings — whose
     landing line sits further from y=0 — enter the screen earlier than a
     higher string for the SAME onset, so a chord spanning several strings
     would visibly stagger its entrance and fall out of lockstep even though
     all its notes still land at the correct simultaneous instant. Scaling
     the rate per string keeps every note at the same fractional progress
     (and thus visually locked together) at every tick, purely by choosing
     travel speed proportional to travel distance. */
  _pxPerBeat(stringNum) {
    return Math.max(4, this._stringY(stringNum) / this.futureBeats);
  }

  /* y of a beat relative to a landing line, at the given string's rate. */
  _yForBeat(beat, landY, stringNum) {
    return landY - (beat - this.currentBeat) * this._pxPerBeat(stringNum);
  }

  /* ── Static background (cached offscreen) ──────────────────────────── */

  _drawBackground(w, h) {
    const key = `${Math.round(w)}:${Math.round(h)}:${this._quality}`;
    if (this._backgroundCanvas && this._backgroundKey === key) {
      this.ctx.drawImage(this._backgroundCanvas, 0, 0, w, h);
      return;
    }
    const ctx = this.ctx;
    this._drawStaticBackground(ctx, w, h);
    const cache = document.createElement('canvas');
    cache.width = Math.max(1, Math.floor(w * this.dpr));
    cache.height = Math.max(1, Math.floor(h * this.dpr));
    const cacheCtx = cache.getContext('2d');
    cacheCtx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    this._drawStaticBackground(cacheCtx, w, h);
    this._backgroundCanvas = cache;
    this._backgroundKey = key;
  }

  _drawStaticBackground(ctx, w, h) {
    const g = this._rainGeometry();
    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, '#07080b');
    gradient.addColorStop(0.55, '#0b0d12');
    gradient.addColorStop(1, '#050506');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    // Neck plate: a slightly warmer band so the fretboard reads as a physical
    // object under the falling notes.
    const neckGrad = ctx.createLinearGradient(0, g.neckTop, 0, g.neckBottom);
    neckGrad.addColorStop(0, 'rgba(48, 36, 26, 0.9)');
    neckGrad.addColorStop(1, 'rgba(28, 21, 16, 0.9)');
    ctx.fillStyle = neckGrad;
    ctx.fillRect(g.marginL, g.neckTop, g.cellW * (FRET_COUNT + 1), g.neckH);

    // Fret wires: vertical lines at every cell boundary. The nut (between
    // cell 0 — open strings — and cell 1) is thicker and brighter.
    const rightEdge = this._fretLeft(FRET_COUNT + 1);
    ctx.lineCap = 'butt';
    for (let f = 1; f <= FRET_COUNT + 1; f += 1) {
      const x = this._snapPx(this._fretLeft(f));
      const nut = f === 1;
      ctx.strokeStyle = nut ? 'rgba(245, 240, 225, 0.95)' : 'rgba(200, 200, 205, 0.42)';
      ctx.lineWidth = nut ? 4 : 1.6;
      ctx.beginPath();
      ctx.moveTo(x, g.neckTop);
      ctx.lineTo(x, g.neckBottom);
      ctx.stroke();
    }

    // Fingerboard inlay dots at the usual frets (double at 12), centered in
    // the cell and vertically in the neck.
    ctx.fillStyle = 'rgba(240, 234, 214, 0.30)';
    const dotR = Math.max(3.5, Math.min(6, g.cellW * 0.16));
    const dotX = (f) => this._fretLeft(f) + g.cellW / 2;
    const midY = (g.neckTop + g.neckBottom) / 2;
    for (const f of INLAY_FRETS) {
      ctx.beginPath();
      ctx.arc(dotX(f), midY, dotR, 0, Math.PI * 2);
      ctx.fill();
    }
    ctx.beginPath();
    ctx.arc(dotX(12), midY - g.stringGap, dotR, 0, Math.PI * 2);
    ctx.arc(dotX(12), midY + g.stringGap, dotR, 0, Math.PI * 2);
    ctx.fill();

    // Strings: horizontal lines, high e (thin) on top, low E (thick) at the
    // bottom — same thickness ramp as the Slope view's lanes.
    for (let s = 1; s <= 6; s += 1) {
      const y = this._snapPx(this._stringY(s));
      ctx.strokeStyle = 'rgba(255,255,255,0.78)';
      ctx.lineWidth = 1.15 + (s - 1) * 0.28;
      ctx.shadowColor = 'rgba(255,255,255,0.22)';
      ctx.shadowBlur = this._quality >= 2 ? 0 : 5;
      ctx.beginPath();
      ctx.moveTo(g.marginL, y);
      ctx.lineTo(rightEdge, y);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;

    // String letters left of the neck, fret numbers 0-22 under each cell.
    ctx.fillStyle = 'rgba(255,248,220,0.72)';
    ctx.font = `800 ${Math.max(11, Math.min(14, g.stringGap * 0.7))}px Inter, sans-serif`;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let s = 1; s <= 6; s += 1) {
      ctx.fillText(STRING_NAMES[s], g.marginL - 8, this._stringY(s));
    }
    ctx.fillStyle = 'rgba(255,255,255,0.60)';
    ctx.font = `700 ${Math.max(10, Math.min(13, g.cellW * 0.4))}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    for (let f = 0; f <= FRET_COUNT; f += 1) {
      ctx.fillText(String(f), this._fretLeft(f) + g.cellW / 2, g.numbersY);
    }
  }

  /* ── Measure bars ──────────────────────────────────────────────────── */

  _measureBoundaryBeats() {
    return this._measureBoundaryBeatsValue || this._computeMeasureBoundaryBeats();
  }

  _computeMeasureBoundaryBeats() {
    const totalBeats = this._totalBeats();
    const measureBeats = Array.isArray(this.data.measure_beats)
      ? this.data.measure_beats.map((b) => Number(b) || 0).filter((b) => b > 0)
      : [];
    const boundaries = [];
    if (measureBeats.length) {
      let beat = 0;
      boundaries.push(0);
      for (const length of measureBeats) {
        beat += length;
        boundaries.push(beat);
      }
    } else {
      for (let beat = 0; beat <= totalBeats + MEASURE_BEATS; beat += MEASURE_BEATS) {
        boundaries.push(beat);
      }
    }
    return boundaries;
  }

  /* Faint horizontal rhythm guides across the fall zone, one per measure
     boundary, referenced to the neck's top edge as the landing line. */
  _drawMeasureBars() {
    const g = this._rainGeometry();
    const ctx = this.ctx;
    const totalBeats = this._totalBeats();
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.16)';
    ctx.lineWidth = 1;
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const boundary of this._measureBoundaryBeats()) {
        const beat = boundary + repeat * totalBeats;
        // Purely decorative grid line, not tied to any single note's lane —
        // string 1's rate is as good a reference as any.
        const y = this._yForBeat(beat, g.neckTop, 1);
        if (y < -2 || y > g.neckTop + 2) continue;
        const sy = this._snapPx(y);
        ctx.beginPath();
        ctx.moveTo(g.marginL, sy);
        ctx.lineTo(this._fretLeft(FRET_COUNT + 1), sy);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  /* ── Notes ─────────────────────────────────────────────────────────── */

  /* Notes whose bar intersects the screen this frame, replicated across the
     song loop like SlopeRenderer._visibleNotesForFrame. */
  _visibleNotesForFrame() {
    const visible = [];
    const totalBeats = this._totalBeats();
    const pastBeats = 0.3;
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const source of this.notes) {
        const note = { ...source, onset: source.onset + repeat * totalBeats };
        const ahead = note.onset - this.currentBeat;
        if (ahead > this.futureBeats * 1.08) continue;
        if (note.onset + note.duration < this.currentBeat - pastBeats) continue;
        visible.push(note);
      }
    }
    return visible.sort((a, b) => b.onset - a.onset);
  }

  /* Thin vertical guide from the top of the screen down to the note's own
     string line — only for lanes that currently carry a visible bar, so the
     screen stays clean (matches the sketch: lines only where notes fall). */
  _drawFallLanes(visible) {
    const ctx = this.ctx;
    const seen = new Set();
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.13)';
    ctx.lineWidth = 1;
    for (const note of visible) {
      const key = `${note.string}:${note.fret}`;
      if (seen.has(key)) continue;
      seen.add(key);
      const x = this._snapPx(this._laneX(note.string, note.fret));
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, this._stringY(note.string));
      ctx.stroke();
    }
    ctx.restore();
  }

  _drawNoteBar(note) {
    const g = this._rainGeometry();
    const landY = this._stringY(note.string);
    const yBottomRaw = this._yForBeat(note.onset, landY, note.string);
    const yTop = this._yForBeat(note.onset + note.duration, landY, note.string);
    // A bar being consumed keeps its bottom pinned on the string line and
    // shrinks from below; once the tail passes the line the note is done.
    const yBottom = Math.min(yBottomRaw, landY);
    if (yTop >= landY || yBottom <= 0) return;

    const now = this.currentBeat;
    const active = note.onset <= now && now <= note.onset + note.duration;
    const meta = FINGER_META[String(note.finger || '').toLowerCase()] || FINGER_META.open;
    const exportWarning = note.gp_fingering_export_status === 'missing_source_note_id';
    const color = exportWarning ? '#e53935' : meta.color;
    const ctx = this.ctx;
    const barW = this._clamp(g.cellW * 0.10, 5, 10) * (active ? 1.25 : 1);
    const x = this._laneX(note.string, note.fret);
    const topClamped = Math.max(0, yTop);
    const height = yBottom - topClamped;
    if (height <= 0) return;

    ctx.save();
    // Outer glow pass (skipped at the lowest quality tier, like Slope).
    if (this._quality < 2 || active) {
      ctx.shadowColor = color;
      ctx.shadowBlur = active ? 22 : 12;
    }
    ctx.fillStyle = color;
    ctx.globalAlpha = active ? 1 : 0.88;
    ctx.beginPath();
    ctx.roundRect(x - barW / 2, topClamped, barW, height, barW / 2);
    ctx.fill();
    // Bright core stripe for the fluo-tube look.
    ctx.shadowBlur = 0;
    ctx.globalAlpha = active ? 0.85 : 0.55;
    ctx.fillStyle = 'rgba(255,255,255,0.82)';
    const coreW = Math.max(1.5, barW * 0.3);
    ctx.beginPath();
    ctx.roundRect(x - coreW / 2, topClamped + 1, coreW, Math.max(1, height - 2), coreW / 2);
    ctx.fill();
    if (note.muted) {
      // Match Tab, notation, Slope and the hand lookahead: this occurrence
      // is a dead note, never an unlabelled ordinary fret contact.
      ctx.fillStyle = '#fffdf2';
      ctx.font = `900 ${Math.max(13, barW * 2.1)}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('X', this._snapPx(x), this._snapPx((topClamped + yBottom) / 2));
    }
    ctx.restore();
  }

  /* Red chord labels: one per chord group, at the group's onset height,
     right of the group's rightmost bar. */
  _drawChordLabels(visible) {
    const eps = 1e-4;
    const ctx = this.ctx;
    const g = this._rainGeometry();
    const drawn = new Set();
    ctx.save();
    ctx.fillStyle = '#ff3030';
    ctx.shadowColor = 'rgba(255, 48, 48, 0.72)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 14;
    ctx.font = '900 18px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    for (const note of visible) {
      if (!note.chord) continue;
      const key = `${note.onset.toFixed(4)}:${note.chord}`;
      if (drawn.has(key)) continue;
      drawn.add(key);
      const group = visible.filter(
        (n) => n.chord === note.chord && Math.abs(n.onset - note.onset) < eps,
      );
      let maxX = -Infinity;
      let refY = Infinity;
      for (const n of group) {
        maxX = Math.max(maxX, this._laneX(n.string, n.fret));
        refY = Math.min(refY, this._yForBeat(n.onset, this._stringY(n.string), n.string));
      }
      if (!Number.isFinite(maxX)) continue;
      const y = this._clamp(refY, 14, g.neckTop - 8);
      const x = Math.min(g.w - 80, maxX + 14);
      ctx.fillText(note.chord, this._snapPx(x), this._snapPx(y));
    }
    ctx.restore();
  }

  /* ── Hit flashes ───────────────────────────────────────────────────── */

  _beatWasCrossed(previousBeat, currentBeat, noteBeat, totalBeats) {
    const prev = ((previousBeat % totalBeats) + totalBeats) % totalBeats;
    const curr = ((currentBeat % totalBeats) + totalBeats) % totalBeats;
    const beat = ((noteBeat % totalBeats) + totalBeats) % totalBeats;
    if (Math.abs(curr - prev) < 0.0001) return false;
    if (curr > prev) return beat > prev && beat <= curr;
    return beat > prev || beat <= curr;
  }

  _captureCrossedHits(previousBeat, currentBeat) {
    const totalBeats = this._totalBeats();
    const now = performance.now();
    for (const note of this.notes) {
      if (!this._beatWasCrossed(previousBeat, currentBeat, note.onset, totalBeats)) continue;
      // Sparks are generated once, at creation, so they stay fixed across a
      // flash's lifetime instead of re-randomizing every frame. Every flash
      // created in the SAME _captureCrossedHits call shares an identical
      // `created` timestamp (this loop's `now`) — a chord's several notes
      // therefore ignite, expand and fade in lockstep, making their shared
      // instant visually unmistakable.
      const sparks = Array.from({ length: 6 }, () => ({
        angle: Math.random() * Math.PI * 2,
        speed: 0.6 + Math.random() * 0.6,
      }));
      this._hitFlashes.push({
        string: note.string,
        fret: note.fret,
        finger: note.finger,
        created: now,
        sparks,
      });
    }
    if (this._hitFlashes.length > 32) {
      this._hitFlashes.splice(0, this._hitFlashes.length - 32);
    }
  }

  /* Impact flash on the string×fret intersection: a small fireball burst
     (white-hot core burning out to the finger colour, an outward shockwave
     ring, and a handful of flying embers) so the exact instant a note — or
     several at once, for a chord — hits its string reads as a clear "bang"
     rather than a soft fade. Ring/embers are dropped at the lowest quality
     tier to shed draw cost; the core itself always renders. */
  _drawHitFlashes() {
    if (!this._hitFlashes.length) return;
    const now = performance.now();
    const ttl = this._quality >= 2 ? 180 : 150;
    this._hitFlashes = this._hitFlashes.filter((flash) => now - flash.created < ttl);
    const ctx = this.ctx;
    const g = this._rainGeometry();
    const baseR = this._clamp(g.cellW * 0.22, 8, 14);
    const richEffect = this._quality < 2;
    for (const flash of this._hitFlashes) {
      const age = now - flash.created;
      const progress = this._clamp(age / ttl, 0, 1);
      const alpha = 1 - progress;
      const meta = FINGER_META[String(flash.finger || '').toLowerCase()] || FINGER_META.open;
      const x = this._laneX(flash.string, flash.fret);
      const y = this._stringY(flash.string);

      if (richEffect) {
        const ringR = baseR * (1 + progress * 2.4);
        ctx.save();
        ctx.globalAlpha = alpha * 0.55;
        ctx.strokeStyle = meta.color;
        ctx.lineWidth = Math.max(1.2, baseR * 0.18) * (1 - progress * 0.5);
        ctx.beginPath();
        ctx.arc(x, y, ringR, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();
      }

      const coreR = Math.max(1, baseR * (1 + progress * 0.5) * (1 - progress * 0.3));
      ctx.save();
      ctx.globalAlpha = alpha;
      const grad = ctx.createRadialGradient(x, y, 0, x, y, coreR);
      grad.addColorStop(0, '#fffced');
      grad.addColorStop(0.35, meta.discColor || '#fffdf2');
      grad.addColorStop(0.75, meta.color);
      grad.addColorStop(1, 'rgba(255,255,255,0)');
      ctx.fillStyle = grad;
      ctx.shadowColor = meta.color;
      ctx.shadowBlur = richEffect ? 20 * alpha : 0;
      ctx.beginPath();
      ctx.arc(x, y, coreR, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      if (richEffect && flash.sparks) {
        const dist = baseR * (0.4 + progress * 1.8);
        ctx.save();
        ctx.globalAlpha = alpha * 0.85;
        ctx.fillStyle = meta.color;
        for (const spark of flash.sparks) {
          const sx = x + Math.cos(spark.angle) * dist * spark.speed;
          const sy = y + Math.sin(spark.angle) * dist * spark.speed;
          ctx.beginPath();
          ctx.arc(sx, sy, Math.max(1, 2.2 * (1 - progress)), 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.restore();
      }
    }
  }

  /* ── Tempo heart (same as Slope) ───────────────────────────────────── */

  _drawTempoHeart() {
    const ctx = this.ctx;
    const beatPhase = this.currentBeat - Math.floor(this.currentBeat);
    const pulse = 1 + Math.pow(1 - beatPhase, 5) * 0.34;
    const cx = this.canvas.clientWidth / 2;
    const cy = 30;
    const size = 26 * pulse;
    ctx.save();
    ctx.translate(cx, cy);
    ctx.rotate(-Math.PI / 4);
    ctx.fillStyle = '#e85d75';
    ctx.shadowColor = 'rgba(232, 93, 117, 0.7)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 22 * pulse;
    ctx.beginPath();
    ctx.roundRect(-size / 2, -size / 2, size, size, 7);
    ctx.fill();
    ctx.beginPath();
    ctx.arc(0, -size / 2, size / 2, 0, Math.PI * 2);
    ctx.arc(size / 2, 0, size / 2, 0, Math.PI * 2);
    ctx.fill();
    ctx.restore();

    ctx.save();
    ctx.fillStyle = '#fff8e6';
    ctx.font = '800 16px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.shadowColor = 'rgba(247, 232, 164, 0.52)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 12;
    const effectiveBpm = Math.round(this.tempo * (this._lastSpeed || 1));
    ctx.fillText(`${effectiveBpm} BPM`, cx + 44, cy);
    ctx.restore();
  }
}
