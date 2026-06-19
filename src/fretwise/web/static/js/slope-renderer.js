/**
 * slope-renderer.js — Guitar-Hero-style top-down fingering view.
 *
 * Frontend-only view: it consumes the same `/api/solve` payload as TabRenderer
 * and samples the PlaybackEngine clock on every animation frame so tempo stays
 * locked to audio even when the visual renderer has to degrade quality.
 */

const FINGER_META = {
  open: { label: '0', color: '#d9d6cc', discColor: '#fffdf2' },
  index: { label: 'i', color: '#ffd44d', discColor: '#fff4bd' },
  middle: { label: 'm', color: '#60c060', discColor: '#dcf2dc' },
  ring: { label: 'r', color: '#6090e0', discColor: '#dce9ff' },
  pinky: { label: 'p', color: '#c060c0', discColor: '#f2dcf2' },
};

const MEASURE_BEATS = 4;
const FUTURE_BEATS = MEASURE_BEATS;
const LANE_TOP_Y_RATIO = 0.10;
const HIT_Y_RATIO = 0.78;
const STRING_COLLISION_GAP_BEATS = 0.45;
const MIN_NOTE_GAP_PX = 30;
const MIN_FRAME_MS = 1000 / 24;
const HIGH_QUALITY_FRAME_MS = 1000 / 42;
const LOW_QUALITY_FRAME_MS = 1000 / 18;

export class SlopeRenderer {
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
    this.canvas.__fretwiseSlopeRenderer = this;
    this._onResize = () => this.resize();
    window.addEventListener('resize', this._onResize);
    this.resize();
  }

  destroy() {
    this._stopAnimationLoop();
    if (this.canvas.__fretwiseSlopeRenderer === this) {
      delete this.canvas.__fretwiseSlopeRenderer;
    }
    window.removeEventListener('resize', this._onResize);
  }

  getPerformanceStats() {
    return {
      quality: this._quality,
      dpr: this.dpr,
      lastRenderMs: Math.round(this._lastRenderMs * 10) / 10,
      targetMinFps: 24,
      animationRunning: !!this._raf,
    };
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.dpr = this._renderDpr();
    this.canvas.width = Math.max(1, Math.floor(rect.width * this.dpr));
    this.canvas.height = Math.max(1, Math.floor(rect.height * this.dpr));
    this.ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
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

  bindPlayback(playback) {
    this.playback = playback || null;
    if (this.visible) this._startAnimationLoop();
  }

  _renderDpr() {
    const device = window.devicePixelRatio || 1;
    if (this._quality >= 2) return 1;
    if (this._quality === 1) return Math.min(1.25, device);
    return Math.min(1.6, device);
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

    const frameGap = this._lastFrameTs ? ts - this._lastFrameTs : MIN_FRAME_MS;
    this._lastFrameTs = ts;
    const started = performance.now();
    const previousBeat = this.currentBeat;
    if (this.playback) this._syncFromSeconds(this.playback.getCurrentTimeSec(), this.playback);
    else this._syncFromSeconds(this._lastSeconds, null);
    if (this.playback?.isPlaying && frameGap > MIN_FRAME_MS * 0.92) {
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
    if (frameGap > MIN_FRAME_MS || renderMs > HIGH_QUALITY_FRAME_MS) {
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
    this._drawStrings();
    for (const note of this._visibleNotesForFrame()) this._drawNoteBar(note);
    for (const chord of this._visibleChordsForFrame()) this._drawChordLabel(chord);
    this._drawHitFlashes();
    this._drawNowPulse();
    this._drawTempoHeart();
  }

  _totalBeats() {
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
      .map((note, order) => ({
        ...note,
        onset: Number(note.onset || 0),
        duration: Math.max(0.05, Number(note.duration || 0.25)),
        string: Number(note.string || note.string_num || 1),
        fret: Number(note.fret || 0),
        order,
      }))
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

  _lerp(a, b, t) {
    return a + (b - a) * t;
  }

  _lanePoint(stringNum, depth) {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    const topY = h * LANE_TOP_Y_RATIO;
    const hitY = h * HIT_Y_RATIO;
    const left = this._laneLeft();
    const right = this._laneRight();
    const t = (6 - stringNum) / 5;
    return {
      x: this._lerp(left, right, t),
      y: this._lerp(hitY, topY, depth),
      scale: 1,
    };
  }

  _laneLeft() {
    const w = this.canvas.clientWidth;
    return Math.max(148, w * 0.17);
  }

  _laneRight() {
    const w = this.canvas.clientWidth;
    return Math.min(w - 128, w * 0.84);
  }

  _laneSpacing() {
    return Math.max(1, (this._laneRight() - this._laneLeft()) / 5);
  }

  _minimumGapBeats() {
    const visibleHeight = Math.max(1, this._hitY() - this.canvas.clientHeight * LANE_TOP_Y_RATIO);
    const pixelGapBeats = (MIN_NOTE_GAP_PX / visibleHeight) * FUTURE_BEATS;
    return Math.max(STRING_COLLISION_GAP_BEATS, pixelGapBeats);
  }

  _depthForBeat(noteBeat) {
    return (noteBeat - this.currentBeat) / FUTURE_BEATS;
  }

  _hitY() {
    return this.canvas.clientHeight * HIT_Y_RATIO;
  }

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
    const gradient = ctx.createLinearGradient(0, 0, 0, h);
    gradient.addColorStop(0, '#07080b');
    gradient.addColorStop(0.56, '#161214');
    gradient.addColorStop(1, '#050506');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    ctx.save();
    ctx.globalAlpha = 0.34;
    const gridSteps = this._quality >= 2 ? 8 : 16;
    for (let i = 0; i <= gridSteps; i += 1) {
      const depth = i / gridSteps;
      const left = this._lanePoint(6, depth);
      const right = this._lanePoint(1, depth);
      ctx.strokeStyle = i % 2 === 0 ? 'rgba(255,232,164,0.16)' : 'rgba(255,255,255,0.055)';
      ctx.lineWidth = i % 4 === 0 ? 1.7 : 1;
      ctx.beginPath();
      ctx.moveTo(left.x - this._laneSpacing() * 0.52, left.y);
      ctx.lineTo(right.x + this._laneSpacing() * 0.52, right.y);
      ctx.stroke();
    }
    ctx.restore();

    const topLeft = this._lanePoint(6, 1);
    const topRight = this._lanePoint(1, 1);
    ctx.save();
    ctx.strokeStyle = 'rgba(238, 238, 232, 0.82)';
    ctx.lineWidth = 1.6;
    ctx.shadowColor = 'rgba(238, 238, 232, 0.55)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 10;
    ctx.beginPath();
    ctx.moveTo(topLeft.x - this._laneSpacing() * 0.52, topLeft.y);
    ctx.lineTo(topRight.x + this._laneSpacing() * 0.52, topRight.y);
    ctx.stroke();
    ctx.restore();
  }

  _drawStrings() {
    const ctx = this.ctx;
    for (let stringNum = 1; stringNum <= 6; stringNum += 1) {
      const near = this._lanePoint(stringNum, 0);
      const far = this._lanePoint(stringNum, 1);
      const grad = ctx.createLinearGradient(far.x, far.y, near.x, near.y);
      grad.addColorStop(0, 'rgba(255,255,255,0.34)');
      grad.addColorStop(1, 'rgba(255,255,255,0.9)');
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.35 + (7 - stringNum) * 0.22;
      ctx.shadowColor = 'rgba(255,255,255,0.28)';
      ctx.shadowBlur = this._quality >= 2 ? 0 : 8;
      ctx.beginPath();
      ctx.moveTo(near.x, near.y);
      ctx.lineTo(far.x, far.y);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
  }

  _visibleNotesForFrame() {
    const visible = [];
    const totalBeats = this._totalBeats();
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const source of this.notes) {
        const note = { ...source, onset: source.onset + repeat * totalBeats };
        const startDepth = this._depthForBeat(note.onset);
        const endDepth = this._depthForBeat(note.onset + note.duration);
        if (endDepth >= 0 && startDepth <= 1.16) visible.push(note);
      }
    }
    visible.sort((a, b) => a.string - b.string || a.onset - b.onset);
    const gapBeats = this._minimumGapBeats();
    for (const note of visible) {
      const next = visible.find((candidate) => (
        candidate.string === note.string && candidate.onset > note.onset
      ));
      if (next) {
        const maxDuration = Math.max(0.05, next.onset - note.onset - gapBeats);
        note.duration = Math.min(note.duration, maxDuration);
      }
    }
    return visible.sort((a, b) => b.onset - a.onset);
  }

  _visibleChordsForFrame() {
    const visible = [];
    const totalBeats = this._totalBeats();
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const source of this.chordEvents) {
        const chord = { ...source, onset: source.onset + repeat * totalBeats };
        const depth = this._depthForBeat(chord.onset);
        if (depth >= -0.08 && depth <= 1.16) visible.push(chord);
      }
    }
    return visible.sort((a, b) => b.onset - a.onset);
  }

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
      this._hitFlashes.push({
        string: note.string,
        fret: note.fret,
        finger: note.finger,
        created: now,
      });
    }
    if (this._hitFlashes.length > 32) {
      this._hitFlashes.splice(0, this._hitFlashes.length - 32);
    }
  }

  _drawHitFlashes() {
    if (!this._hitFlashes.length) return;
    const now = performance.now();
    const ttl = this._quality >= 2 ? 180 : 140;
    this._hitFlashes = this._hitFlashes.filter((flash) => now - flash.created < ttl);
    const ctx = this.ctx;
    for (const flash of this._hitFlashes) {
      const age = now - flash.created;
      const alpha = Math.max(0, 1 - age / ttl);
      const point = this._lanePoint(flash.string, 0);
      const meta = FINGER_META[String(flash.finger || '').toLowerCase()] || FINGER_META.open;
      const radius = Math.max(16, Math.min(26, this._laneSpacing() * 0.24));
      ctx.save();
      ctx.beginPath();
      ctx.rect(0, 0, this.canvas.clientWidth, this._hitY());
      ctx.clip();
      ctx.globalAlpha = alpha;
      ctx.shadowColor = meta.color;
      ctx.shadowBlur = this._quality >= 2 ? 0 : 18 * alpha;
      ctx.fillStyle = meta.discColor || '#fffdf2';
      ctx.beginPath();
      ctx.arc(point.x, point.y - radius * 0.1, radius * (1 + (1 - alpha) * 0.35), 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = meta.color;
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.shadowBlur = 0;
      ctx.fillStyle = '#050505';
      ctx.font = `900 ${Math.max(16, radius * 1.08)}px Inter, sans-serif`;
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText(String(flash.fret), point.x, point.y - radius * 0.1 + 0.5);
      ctx.restore();
    }
  }

  _drawChordTriangle(point, radius, scale) {
    const ctx = this.ctx;
    const size = 10 * scale + 7;
    const tipY = point.y - radius - 4;
    ctx.save();
    ctx.fillStyle = '#ff3030';
    ctx.shadowColor = 'rgba(255, 48, 48, 0.8)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 12 * scale + 4;
    ctx.beginPath();
    ctx.moveTo(point.x, tipY);
    ctx.lineTo(point.x - size * 0.72, tipY - size * 1.2);
    ctx.lineTo(point.x + size * 0.72, tipY - size * 1.2);
    ctx.closePath();
    ctx.fill();
    ctx.restore();
  }

  _chordTriangleCenterY(point, radius, scale) {
    const size = 10 * scale + 7;
    const tipY = point.y - radius - 4;
    return tipY - size * 0.8;
  }

  _drawNoteBar(note) {
    const startDepth = this._depthForBeat(note.onset);
    const endDepth = this._depthForBeat(note.onset + note.duration);
    if (endDepth < 0 || startDepth > 1.16) return;

    const now = this.currentBeat;
    const active = note.onset <= now && now <= note.onset + note.duration;
    const vibration = active ? 1 + 0.18 * Math.sin(performance.now() / 34) : 1;
    const a = this._lanePoint(note.string, Math.max(0, Math.min(1.08, startDepth)));
    const b = this._lanePoint(note.string, Math.max(0, Math.min(1.08, endDepth)));
    const meta = FINGER_META[String(note.finger || '').toLowerCase()] || FINGER_META.open;
    const widthA = Math.min(32, this._laneSpacing() * 0.33) * vibration;
    const widthB = Math.min(32, this._laneSpacing() * 0.33);
    const angle = Math.atan2(b.y - a.y, b.x - a.x);
    const nx = Math.cos(angle + Math.PI / 2);
    const ny = Math.sin(angle + Math.PI / 2);
    const ctx = this.ctx;

    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, this.canvas.clientWidth, this._hitY());
    ctx.clip();

    const tubeWidth = Math.max(20, (widthA + widthB) * 0.78);
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.shadowColor = meta.color;
    ctx.shadowBlur = this._quality >= 2 ? 0 : active ? 28 * vibration : 14;
    ctx.strokeStyle = meta.color;
    ctx.lineWidth = tubeWidth * 1.35;
    ctx.globalAlpha = active ? 0.32 : 0.18;
    if (this._quality < 2 || active) {
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }

    ctx.globalAlpha = 0.92;
    ctx.shadowBlur = this._quality >= 2 ? 0 : active ? 16 * vibration : 9;
    const fill = ctx.createLinearGradient(
      a.x - nx * widthA, a.y - ny * widthA,
      a.x + nx * widthA, a.y + ny * widthA,
    );
    fill.addColorStop(0, 'rgba(0,0,0,0.58)');
    fill.addColorStop(0.16, meta.color);
    fill.addColorStop(0.48, '#fff7d8');
    fill.addColorStop(0.72, meta.color);
    fill.addColorStop(1, 'rgba(0,0,0,0.48)');
    ctx.strokeStyle = fill;
    ctx.lineWidth = tubeWidth;
    ctx.beginPath();
    ctx.moveTo(a.x, a.y);
    ctx.lineTo(b.x, b.y);
    ctx.stroke();

    ctx.shadowBlur = 0;
    ctx.globalAlpha = 0.55;
    ctx.strokeStyle = 'rgba(255,255,255,0.78)';
    ctx.lineWidth = 4;
    ctx.beginPath();
    ctx.moveTo(a.x + nx * tubeWidth * 0.17, a.y + ny * tubeWidth * 0.17);
    ctx.lineTo(b.x + nx * tubeWidth * 0.17, b.y + ny * tubeWidth * 0.17);
    ctx.stroke();

    const labelPoint = {
      x: (a.x + b.x) / 2,
      y: (a.y + b.y) / 2,
      scale: (a.scale + b.scale) / 2,
    };
    const labelRadius = Math.max(16, Math.min(26, this._laneSpacing() * 0.24));
    ctx.globalAlpha = 1;
    ctx.shadowColor = 'rgba(255,255,255,0.62)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 16;
    ctx.fillStyle = meta.discColor || '#fffdf2';
    ctx.beginPath();
    ctx.arc(labelPoint.x, labelPoint.y, labelRadius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = 'rgba(0,0,0,0.28)';
    ctx.lineWidth = 2;
    ctx.stroke();
    ctx.shadowBlur = 0;
    ctx.fillStyle = '#050505';
    ctx.font = `900 ${Math.max(16, labelRadius * 1.08)}px Inter, sans-serif`;
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(String(note.fret), labelPoint.x, labelPoint.y + 0.5);
    if (note.chord) this._drawChordTriangle(labelPoint, labelRadius, labelPoint.scale);
    ctx.restore();
  }

  _drawChordLabel(chord) {
    const startDepth = this._depthForBeat(chord.onset);
    const endDepth = this._depthForBeat(chord.onset + chord.duration);
    const labelDepth = Math.max(0, Math.min(1.04, (startDepth + endDepth) / 2));
    const right = this._lanePoint(1, labelDepth);
    const rawX = right.x + Math.max(48, this._laneSpacing() * 0.58);
    const x = Math.min(this.canvas.clientWidth - 92, rawX);
    const labelRadius = Math.max(16, Math.min(26, this._laneSpacing() * 0.24));
    const y = this._chordTriangleCenterY(right, labelRadius, right.scale);
    const ctx = this.ctx;
    ctx.save();
    ctx.beginPath();
    ctx.rect(0, 0, this.canvas.clientWidth, this._hitY());
    ctx.clip();
    ctx.fillStyle = '#ff3030';
    ctx.shadowColor = 'rgba(255, 48, 48, 0.72)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 20;
    ctx.font = '900 24px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(chord.label, x, y);
    ctx.restore();
  }

  _drawNowPulse() {
    const ctx = this.ctx;
    const w = this.canvas.clientWidth;
    const beatPhase = this.currentBeat - Math.floor(this.currentBeat);
    ctx.save();
    ctx.globalAlpha = (1 - beatPhase) * 0.18;
    if (this._quality >= 2) ctx.globalAlpha *= 0.45;
    ctx.strokeStyle = '#f7e8a4';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.ellipse(w * 0.5, this._hitY(), w * 0.39 * (1 + beatPhase * 0.16), 54, 0, 0, Math.PI * 2);
    ctx.stroke();
    ctx.restore();
  }

  _drawTempoHeart() {
    const ctx = this.ctx;
    const beatPhase = this.currentBeat - Math.floor(this.currentBeat);
    const pulse = 1 + Math.pow(1 - beatPhase, 5) * 0.34;
    const cx = Math.max(54, this.canvas.clientWidth * 0.055);
    const cy = this.canvas.clientHeight * 0.50;
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

  setSpeed(speed) {
    this._lastSpeed = speed || 1;
  }
}
