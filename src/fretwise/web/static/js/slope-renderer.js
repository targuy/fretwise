/**
 * slope-renderer.js - Folded top-down fingering playback view.
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
// P2 density slider bounds, in beats. Below MIN, notes crowd/overlap in the
// shrunken window; above MAX, the path is stretched so thin each note
// occupies a sliver of a pixel-beat, defeating the whole point of slowing
// the glide down for legibility.
const MIN_DENSITY_BEATS = MEASURE_BEATS * 6;
const MAX_DENSITY_BEATS = MEASURE_BEATS * 12;
// Default matches MIN_DENSITY_BEATS: the slowest glide is the safest starting
// point, and it keeps the renderer's own default in sync with the slider's
// (see main.js's _SLOPE_DENSITY_MIN/_slopeDensity fallback).
const FUTURE_BEATS = MIN_DENSITY_BEATS;
// P4 — stepped scroll: how many beats wide each hold is. Half a beat (an
// eighth note at 4/4) is short enough that the view still reads as playing
// along in real time, but long enough to give a real fixation window between
// jumps instead of a barely-shorter blur.
const STEP_BEATS = 0.5;
const PAST_BEATS = 0.75;
const STRING_COLLISION_GAP_BEATS = 0.18;
const MIN_NOTE_GAP_PX = 28;
const MIN_CIRCLE_PAD_PX = 5;
const MEASURE_NOTE_PAD_PX = 7;
const TARGET_FRAME_MS = 1000 / 60;
// Cap the backing-store resolution so a 4x display doesn't allocate an absurd
// buffer, but never below a real device's dpr — see _renderDpr().
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
    // Legibility aid mode (P1–P4): 'base' = raw slope, 'p1' = fixed reading
    // band (default), 'p2' = density control, 'p3' = strike magnifier (see
    // _drawStrikeMagnifier). See setLegibilityMode.
    this.legibilityMode = 'p1';
    // P2 (density): how many beats of future notes are visible on screen at
    // once. Fewer beats -> the same physical path length covers less musical
    // time -> notes glide slower in px/s and sit farther apart, both of which
    // make the residual smooth-pursuit slip (the eye's ~0.9 tracking gain
    // never reaches 1, independent of screen Hz) proportionally smaller
    // relative to glyph size. See setDensity.
    this.futureBeats = FUTURE_BEATS;
    // P4 (stepped scroll): the beat used for on-screen positioning is
    // quantized to this many beats when legibilityMode === 'p4' — see
    // _renderBeat(). The actual playback clock (this.currentBeat) stays
    // continuous throughout, so audio sync and hit detection are unaffected;
    // only what gets drawn where is stepped.
    this.stepBeats = STEP_BEATS;
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
    this._frameGeometry = null;
    this._frameVisibleBoundaries = null;
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
      targetMinFps: 50,
      animationRunning: !!this._raf,
    };
  }

  resize() {
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.dpr = this._renderDpr();
    // Device-pixel-exact backing store: floor(rect * dpr), same math the CSS
    // box is pinned to below.
    const bw = Math.max(1, Math.floor(rect.width * this.dpr));
    const bh = Math.max(1, Math.floor(rect.height * this.dpr));
    this.canvas.width = bw;
    this.canvas.height = bh;
    // Pin the CSS box to the EXACT size the backing store was sized for
    // (bw/dpr, bh/dpr), in px — not the stylesheet's `width:100%`. Left as a
    // percentage, the box's rendered size is whatever the layout engine
    // computes for "100% of the parent" on each paint, independently of the
    // integer-pixel backing store above; any sub-pixel drift between the two
    // (sub-pixel layout rounding, a scrollbar appearing, a parent reflow)
    // makes the browser resample the ENTIRE canvas to fit the box each
    // frame — a continuous soft blur on exactly the high-frequency content
    // (glyph edges) that _snapPx/_snapFontSizeClamped worked to make crisp,
    // while low-frequency content (fret-disc circles, lane lines) looks
    // almost unaffected. That mismatch is invisible to source-level pixel
    // math (draw calls land on exact device pixels of the BACKING STORE) —
    // it only shows up as the compositor scales the finished bitmap into a
    // box of a slightly different size.
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

  /* Select the in-motion legibility aid. See the class-level modes note.
     Unknown values fall back to 'base' so a stale localStorage value can't
     blank the view. */
  setLegibilityMode(mode) {
    const allowed = ['base', 'p1', 'p2', 'p3', 'p4', 'p5'];
    this.legibilityMode = allowed.includes(mode) ? mode : 'base';
  }

  /* P2 — density: how many beats of upcoming notes are visible at once.
     Clamped to [MIN_DENSITY_BEATS, MAX_DENSITY_BEATS] so an extreme value
     can't collapse the lane (too few beats -> notes overlap/crowd) or spread
     notes into illegibly-tiny specks (too many beats -> everything shrinks
     toward one pixel per beat). No cache to invalidate here: _foldGeometry's
     cache key already includes futureBeats, so it naturally recomputes on
     the next render when this changes. */
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
    // Lot C (text sharpness): the backing store must ALWAYS match the true
    // device pixel ratio. If it drops below it (as the old quality-scaled
    // ramp did — 1.5x on a 2x display), the canvas element is CSS-upscaled to
    // fill its box, which resamples and blurs every already-snapped glyph the
    // instant playback degrades quality. Draw-cost is shed elsewhere (shadows,
    // path-step count, the extra glow pass — all gated on `this._quality`),
    // never on resolution.
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
    this._beginFrameCaches();
    this._drawBackground(w, h);
    this._drawMeasureBars();
    for (const note of this._visibleNotesForFrame()) this._drawNoteBar(note);
    for (const chord of this._visibleChordsForFrame()) this._drawChordLabel(chord);
    this._drawHitFlashes();
    this._drawNowPulse();
    this._drawTempoHeart();
    if (this.legibilityMode === 'p1') {
      this._drawReadingBand(w, h);
    } else if (this.legibilityMode === 'p2') {
      this._drawDensityReadout(w, h);
    } else if (this.legibilityMode === 'p3') {
      this._drawStrikeMagnifier(w, h);
    } else if (this.legibilityMode === 'p4') {
      this._drawSteppedScrollReadout(w, h);
    } else if (this.legibilityMode === 'p5') {
      this._drawChordLookaheadBand(w, h);
    }
    this._endFrameCaches();
  }

  /* Upcoming notes to show, earliest first, from the current playhead forward.
     Chords (same onset) are kept together as one group. */
  _upcomingNotes(maxGroups) {
    const eps = 1e-4;
    const ahead = this.notes
      .filter((n) => n.onset >= this.currentBeat - eps)
      .sort((a, b) => a.onset - b.onset || a.string - b.string);
    const groups = [];
    let cur = null;
    for (const n of ahead) {
      if (!cur || Math.abs(n.onset - cur.onset) > eps) {
        // Check the cap BEFORE starting a new group, not after: the group
        // just pushed for maxGroups may be a chord (several notes sharing
        // this onset) whose later notes haven't been seen yet in this sorted
        // pass — breaking right after the push would drop them, silently
        // truncating the last group's chord down to whichever single note
        // happened to sort first (lowest string). Most visible with
        // maxGroups=1 (P3's single-group magnifier), but the same truncation
        // could hit P1's 4th group too.
        if (groups.length >= maxGroups) break;
        cur = { onset: n.onset, notes: [n] };
        groups.push(cur);
      } else {
        cur.notes.push(n);
      }
    }
    return groups;
  }

  /* P1 — fixed reading band. A static strip shows the next few note groups in
     large, still text. Because it never moves, the eye reads it in fixation
     (not smooth pursuit), so it stays sharp at any tempo / refresh rate — the
     moving discs keep carrying position/colour/length, the band carries the
     reading. */
  _drawReadingBand(w, h) {
    const groups = this._upcomingNotes(4);
    if (!groups.length) return;
    const ctx = this.ctx;
    const pad = 12;
    const gapPx = 10;

    // Vertical placement: NOT pinned to the bottom edge — that zone is covered
    // by the fixed playback toolbar + scrubber (~88px, see main.js's
    // BOT_GUTTER), so a bottom-pinned band was invisible/clipped in practice
    // (confirmed: "coupé en bas, pas lisible"). The fold geometry leaves a real
    // empty gap between the bottom lane (the incoming/near-future strip) and
    // the top lane (the far-future strip, after the arc) — dead space with
    // nothing drawn in it. Center the band there instead: visible, doesn't
    // overlap either lane, and sits where the eye naturally rests between the
    // two lanes rather than requiring a saccade all the way to a screen edge.
    const g = this._foldGeometry();
    const gapTop = g.topBase + g.spread / 2;
    const gapBottom = g.bottomBase - g.spread / 2;
    const cardH = Math.max(56, Math.min(96, gapBottom - gapTop - 24));
    const bandY = (gapTop + gapBottom) / 2 - cardH / 2;

    // Horizontal extent: a band spanning the FULL canvas width crosses through
    // the arc (the string turn) — the arc's rightmost bulge sits at almost
    // exactly this band's vertical center (x = bendX + outerRadius occurs at
    // y = centerY, see _lanePoint's arc branch), so a full-width band visually
    // cut through the turn ("écrase le tournant des cordes"). Confine the band
    // to the straight-run zone left of the arc, and center it THERE (not
    // pinned to the left edge, which read as off-center against the lanes
    // spanning most of the canvas).
    const maxBandRight = Math.max(240, g.bendX - g.outerRadius - 24);
    // Size cards to a fixed comfortable target (IDEAL_CARD_W) rather than
    // maximizing into whatever room is available — a cap close to the
    // available width leaves near-zero slack, so the row always ends up
    // hugging the left edge regardless of a "center it" formula below (this
    // was the actual bug: the old 190px cap nearly filled realistic
    // straight-run zones, leaving ~12px of "slack" — invisible in practice).
    // Only shrink below the target on a zone too narrow to fit it.
    const IDEAL_CARD_W = 160;
    const idealWidth = IDEAL_CARD_W * 4 + gapPx * 3;
    const bandWidth = Math.min(idealWidth, maxBandRight - pad * 2);
    const cardW = (bandWidth - gapPx * 3) / 4;
    const bandLeft = Math.max(pad, (maxBandRight - bandWidth) / 2);

    ctx.save();
    // Dim scrim behind the band so the moving lane doesn't bleed through the text.
    ctx.fillStyle = 'rgba(6, 8, 12, 0.85)';
    ctx.fillRect(bandLeft - 8, bandY - 8, bandWidth + 16, cardH + 16);
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('À VENIR', bandLeft, bandY - 12);

    groups.forEach((group, gi) => {
      const x = bandLeft + gi * (cardW + gapPx);
      const beatsAway = group.onset - this.currentBeat;
      // The imminent group is brightest; later ones fade so the eye lands on
      // "what's next" first.
      const prom = gi === 0 ? 1 : Math.max(0.4, 1 - gi * 0.22);
      ctx.globalAlpha = prom;
      ctx.fillStyle = gi === 0 ? 'rgba(76,175,80,0.16)' : 'rgba(255,255,255,0.05)';
      this._roundRect(ctx, x, bandY, cardW, cardH, 8);
      ctx.fill();
      if (gi === 0) {
        ctx.strokeStyle = 'rgba(76,175,80,0.85)';
        ctx.lineWidth = 1.5;
        this._roundRect(ctx, x, bandY, cardW, cardH, 8);
        ctx.stroke();
      }

      // Stack the group's notes (a chord) as compact rows inside the card.
      const rows = group.notes.slice(0, 4);
      const rowH = (cardH - 20) / rows.length;
      // Below ~100px the fixed dot+digit+name+string layout no longer fits —
      // a narrow zone (a tall/near-square panel drives outerRadius up, eating
      // most of the straight-run width before the arc) would otherwise
      // overlap neighbouring cards' text. Drop the note-name/string and show
      // ONLY the finger dot + a big digit, using the freed width to keep it
      // large rather than shrinking everything to illegible mush.
      const compact = cardW < 100;
      const dotR = compact ? 5 : 7;
      const dotX = x + (compact ? 12 : 18);
      const digitX = dotX + dotR + 8;
      // Rough glyph-width factor for a bold ("900") numeral: ~0.62x font-size.
      const digitMaxW = (cardW - (digitX - x) - (compact ? 6 : 46)) / 0.62;
      rows.forEach((n, ri) => {
        const cy = bandY + 10 + rowH * ri + rowH / 2;
        const meta = FINGER_META[String(n.finger || '').toLowerCase()] || FINGER_META.open;
        // Finger colour dot.
        ctx.globalAlpha = prom;
        ctx.fillStyle = meta.color;
        ctx.beginPath();
        ctx.arc(dotX, cy, dotR, 0, Math.PI * 2);
        ctx.fill();
        // Big fret number — the primary reading target.
        ctx.fillStyle = '#ffffff';
        ctx.font = `900 ${Math.max(14, Math.min(38, rowH * 0.94, digitMaxW))}px Inter, sans-serif`;
        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillText(String(n.fret), digitX, cy);
        if (!compact) {
          // Note name + string, smaller, to the right.
          ctx.fillStyle = 'rgba(255,255,255,0.75)';
          ctx.font = '700 15px Inter, sans-serif';
          ctx.fillText(`${n.noteName}`, digitX + 30, cy - 7);
          ctx.fillStyle = 'rgba(255,255,255,0.5)';
          ctx.font = '600 12px Inter, sans-serif';
          ctx.fillText(`${STRING_NAMES[n.string] || ''}${n.string}`, digitX + 30, cy + 10);
        }
      });

      // "in N.n beats" hint under the imminent card.
      if (gi === 0) {
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = 'rgba(76,175,80,0.9)';
        ctx.font = '600 10px Inter, sans-serif';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'alphabetic';
        ctx.fillText(`+${beatsAway.toFixed(1)}`, x + cardW - 6, bandY + 14);
      }
    });
    ctx.restore();
  }

  /* Shared corner-tag y position for P2's live readout and P3/P4's "coming
     soon" notices: centered in the same lane gap _drawReadingBand uses — NOT
     the bottom edge, which is covered by the fixed playback toolbar +
     scrubber (see _drawReadingBand's comment; the original bottom-pinned
     placement bit this tag too before it was noticed on the reading band). */
  _tagY(h) {
    const g = this._foldGeometry();
    const gapTop = g.topBase + g.spread / 2;
    const gapBottom = g.bottomBase - g.spread / 2;
    return this._clamp(h * 0.5, gapTop + 20, gapBottom - 6);
  }

  _drawTag(w, h, label, color) {
    const ctx = this.ctx;
    const y = this._tagY(h);
    ctx.save();
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'alphabetic';
    const tw = ctx.measureText(label).width;
    ctx.fillStyle = 'rgba(6,8,12,0.8)';
    this._roundRect(ctx, w / 2 - tw / 2 - 10, y - 15, tw + 20, 22, 6);
    ctx.fill();
    ctx.fillStyle = color;
    ctx.fillText(label, w / 2, y);
    ctx.restore();
  }

  /* P2 is live (the density control) — show its current setting rather than
     a "coming soon" placeholder. */
  _drawDensityReadout(w, h) {
    this._drawTag(
      w, h,
      `P2 — densité : ${this.futureBeats.toFixed(1)} temps visibles`,
      'rgba(120,200,255,0.95)',
    );
  }

  /* P4 is live (stepped scroll, see _renderBeat) — show a status readout
     rather than a "coming soon" placeholder. */
  _drawSteppedScrollReadout(w, h) {
    this._drawTag(
      w, h,
      `P4 — défilement cranté : pas de ${this.stepBeats} temps`,
      'rgba(255,183,77,0.95)',
    );
  }

  /* P3 — reading magnifier before the strike. Where P1 previews a ROW of
     upcoming groups (read while there's still several beats of runway) and
     P2 just enlarges the moving discs, P3 answers a narrower question: "what
     am I about to play, right now, in fixation, at maximum size?" It shows
     ONLY the single next unstruck group, as large as the lane gap allows,
     with a shrinking countdown bar that reads the remaining time as a static
     fill level (not motion) — the group swaps the instant it's struck, a
     discrete flip rather than a glide, so there's never a moment where the
     magnifier itself is something the eye has to track. */
  _drawStrikeMagnifier(w, h) {
    const groups = this._upcomingNotes(1);
    if (!groups.length) return;
    const group = groups[0];
    const ctx = this.ctx;
    const pad = 12;

    const g = this._foldGeometry();
    const gapTop = g.topBase + g.spread / 2;
    const gapBottom = g.bottomBase - g.spread / 2;
    // Same arc-avoidance as P1's band (see _drawReadingBand): stay left of
    // the string turn, whose rightmost bulge sits at this gap's vertical
    // center.
    const maxRight = Math.max(240, g.bendX - g.outerRadius - 24);
    const cardW = Math.min(360, maxRight - pad * 2);
    const cardH = Math.max(56, gapBottom - gapTop - 24);
    const cardX = Math.max(pad, (maxRight - cardW) / 2);
    const cardY = (gapTop + gapBottom) / 2 - cardH / 2;

    const beatsAway = Math.max(0, group.onset - this.currentBeat);
    // A full window's worth of lead time reads as a full bar; 0 beats away
    // (the strike instant) reads as empty. minimumGapBeats is the shortest
    // gap the renderer already treats as "distinct notes", so it's a sane
    // floor for what "about to strike" means.
    const horizonBeats = Math.max(this._minimumGapBeats() * 4, 1.5);
    const urgency = 1 - this._clamp(beatsAway / horizonBeats, 0, 1);

    ctx.save();
    ctx.fillStyle = 'rgba(6, 8, 12, 0.88)';
    ctx.fillRect(cardX - 8, cardY - 8, cardW + 16, cardH + 16);
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('AVANT LA FRAPPE', cardX, cardY - 12);

    ctx.fillStyle = 'rgba(76,175,80,0.14)';
    this._roundRect(ctx, cardX, cardY, cardW, cardH, 10);
    ctx.fill();
    ctx.strokeStyle = 'rgba(76,175,80,0.9)';
    ctx.lineWidth = 2;
    this._roundRect(ctx, cardX, cardY, cardW, cardH, 10);
    ctx.stroke();

    // Countdown bar: a static fill level, not a moving element — it still
    // communicates "how soon" without asking the eye to track anything.
    const barH = 6;
    const barY = cardY + cardH - barH - 8;
    ctx.fillStyle = 'rgba(255,255,255,0.12)';
    this._roundRect(ctx, cardX + 10, barY, cardW - 20, barH, 3);
    ctx.fill();
    ctx.fillStyle = urgency > 0.75 ? 'rgba(255,138,101,0.95)' : 'rgba(76,175,80,0.95)';
    this._roundRect(ctx, cardX + 10, barY, (cardW - 20) * urgency, barH, 3);
    ctx.fill();

    const rows = group.notes.slice(0, 4);
    const rowsTop = cardY + 26;
    const rowsH = barY - 10 - rowsTop;
    const rowH = rowsH / rows.length;
    const dotR = Math.min(16, Math.max(9, rowH * 0.28));
    const dotX = cardX + 26;
    const digitX = dotX + dotR + 14;
    const digitMaxW = (cardW - (digitX - cardX) - 90) / 0.62;
    rows.forEach((n, ri) => {
      const cy = rowsTop + rowH * ri + rowH / 2;
      const meta = FINGER_META[String(n.finger || '').toLowerCase()] || FINGER_META.open;
      ctx.fillStyle = meta.color;
      ctx.beginPath();
      ctx.arc(dotX, cy, dotR, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = '#ffffff';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'middle';
      ctx.font = `900 ${Math.max(20, Math.min(56, rowH * 0.86, digitMaxW))}px Inter, sans-serif`;
      ctx.fillText(String(n.fret), digitX, cy);
      ctx.fillStyle = 'rgba(255,255,255,0.78)';
      ctx.font = '700 18px Inter, sans-serif';
      ctx.fillText(`${n.noteName || ''}`, cardX + cardW - 66, cy - 9);
      ctx.fillStyle = 'rgba(255,255,255,0.55)';
      ctx.font = '600 14px Inter, sans-serif';
      ctx.fillText(`${STRING_NAMES[n.string] || ''}${n.string}`, cardX + cardW - 66, cy + 11);
    });

    ctx.fillStyle = 'rgba(76,175,80,0.9)';
    ctx.font = '700 12px Inter, sans-serif';
    ctx.textAlign = 'right';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText(`+${beatsAway.toFixed(2)}`, cardX + cardW - 6, cardY + cardH + 20);
    ctx.restore();
  }

  /* P5 — chord-diagram lookahead. Mixes P1's fixed reading band (never
     moves, so it's read in fixation, not smooth pursuit) with a genuine
     6-string chord shape per group instead of a flat note list: every
     string gets its own row, played strings get a filled disc + fret digit,
     unplayed/muted strings get a hollow ring — without that, there's no way
     to tell "not played" from "chord I haven't read yet" at a glance.
     10 groups (P1 shows 4), laid out as narrow, TALL cards — one column per
     group, one fixed row per string — rather than P1's wide, short cards.
     Six FIXED rows per card is what guarantees no collision between
     displayed notes: every string has exactly one slot, played or hollow,
     so nothing can ever land on top of anything else. Circle radius targets
     the range between P1's (12-18px) and P2's (16-24px), shrinking further
     only if six rows genuinely don't fit the available height — the same
     graceful-degradation approach as P1's compact mode. Card WIDTH shrinks
     to fit all 10 columns in the arc-safe zone (same shrink-to-fit as P1's
     compact mode); radius/digit size are driven by cardH, not cardW, so
     legibility per string doesn't degrade as the column count grows. */
  _drawChordLookaheadBand(w, h) {
    const groups = this._upcomingNotes(10);
    if (!groups.length) return;
    const ctx = this.ctx;
    const pad = 12;
    const gapPx = 10;

    const g = this._foldGeometry();
    const gapTop = g.topBase + g.spread / 2;
    const gapBottom = g.bottomBase - g.spread / 2;
    // Reuse P1's vertical centering (bottom toolbar clearance already
    // solved there) but claim much more of the gap's height — tall cards
    // are what let 6 string-rows have real room per row.
    const cardH = Math.max(90, Math.min(280, gapBottom - gapTop - 24));
    const cardY = (gapTop + gapBottom) / 2 - cardH / 2;

    // Same arc-avoidance as P1/P3: stay left of the string turn, whose
    // rightmost bulge sits at this gap's vertical center.
    const maxBandRight = Math.max(240, g.bendX - g.outerRadius - 24);
    const count = groups.length;
    // Each card only needs one column (string label + one disc/ring stack),
    // far narrower than P1's dot+digit+name+string row. 60px is enough for
    // a ~42px disc (radius up to 21) plus the string-label sliver and
    // padding — still tight for 10 columns in the arc-safe zone, so cardW
    // below shrinks below this target on narrower screens (same
    // shrink-to-fit as P1's compact mode; radius/digit size don't depend on
    // cardW so per-string legibility holds even when cards get narrow).
    const IDEAL_CARD_W = 60;
    const idealWidth = IDEAL_CARD_W * count + gapPx * (count - 1);
    const bandWidth = Math.min(idealWidth, maxBandRight - pad * 2);
    const cardW = (bandWidth - gapPx * (count - 1)) / count;
    const bandLeft = Math.max(pad, (maxBandRight - bandWidth) / 2);

    ctx.save();
    ctx.fillStyle = 'rgba(255,255,255,0.55)';
    ctx.font = '600 11px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    ctx.fillText('PROCHAINS ACCORDS', bandLeft, cardY - 12);

    const rowPad = 4;
    const rowH = (cardH - rowPad * 2) / 6;
    // Target: between P1's circleRadius (12-18) and P2's (16-24). Also
    // clamped to cardW/2 — with 10 narrow columns squeezed into the
    // arc-safe zone, a height-only radius could exceed the column's own
    // width and spill into the next card; that clamp is what keeps 10
    // columns collision-free the same way rowH/2 keeps 6 rows collision-free.
    const targetRadius = this._clamp(this._laneSpacing() * 0.42, 14, 21);
    const radius = Math.min(targetRadius, rowH / 2 - 2, cardW / 2 - 3);

    groups.forEach((group, gi) => {
      const x = bandLeft + gi * (cardW + gapPx);
      const prom = gi === 0 ? 1 : Math.max(0.4, 1 - gi * 0.18);
      ctx.globalAlpha = prom;

      ctx.fillStyle = 'rgba(6, 8, 12, 0.85)';
      ctx.fillRect(x - 4, cardY - 4, cardW + 8, cardH + 8);
      ctx.fillStyle = gi === 0 ? 'rgba(76,175,80,0.14)' : 'rgba(255,255,255,0.04)';
      this._roundRect(ctx, x, cardY, cardW, cardH, 8);
      ctx.fill();
      if (gi === 0) {
        ctx.strokeStyle = 'rgba(76,175,80,0.85)';
        ctx.lineWidth = 1.5;
        this._roundRect(ctx, x, cardY, cardW, cardH, 8);
        ctx.stroke();
      }

      // One triangle per CHORD, not per note: drawn once above the card,
      // only when a note in this group actually carries a chord label (see
      // _buildChordEvents/note.chord) — a single melody note doesn't get one.
      if (group.notes.some((n) => n.chord)) {
        const tipY = cardY - 6;
        const size = 8;
        ctx.fillStyle = '#ff3030';
        ctx.beginPath();
        ctx.moveTo(x + cardW / 2, tipY);
        ctx.lineTo(x + cardW / 2 - size, tipY - size * 1.4);
        ctx.lineTo(x + cardW / 2 + size, tipY - size * 1.4);
        ctx.closePath();
        ctx.fill();
      }

      const cx = x + cardW / 2;
      for (let row = 0; row < 6; row += 1) {
        const stringNum = row + 1; // row 0 = string 1 ('e', highest) at top
        const cy = cardY + rowPad + rowH * row + rowH / 2;
        const played = group.notes.find((n) => n.string === stringNum);

        ctx.textAlign = 'left';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = 'rgba(255,255,255,0.4)';
        ctx.font = '600 9px Inter, sans-serif';
        ctx.fillText(STRING_NAMES[stringNum] || '', x + 2, cy);

        if (played) {
          const meta = FINGER_META[String(played.finger || '').toLowerCase()] || FINGER_META.open;
          ctx.fillStyle = meta.color;
          ctx.beginPath();
          ctx.arc(cx, cy, radius, 0, Math.PI * 2);
          ctx.fill();
          ctx.fillStyle = '#050505';
          ctx.textAlign = 'center';
          ctx.font = `900 ${Math.max(10, radius * 1.05)}px Inter, sans-serif`;
          ctx.fillText(String(played.fret), cx, cy + 0.5);
        } else {
          // Unplayed/muted string: hollow ring only, no fill, no digit — the
          // only way to distinguish "not played" from "not read yet".
          ctx.strokeStyle = 'rgba(255,255,255,0.30)';
          ctx.lineWidth = Math.max(1.2, radius * 0.16);
          ctx.beginPath();
          ctx.arc(cx, cy, radius * 0.7, 0, Math.PI * 2);
          ctx.stroke();
        }
      }
    });
    ctx.restore();
  }

  _roundRect(ctx, x, y, w, h, r) {
    const rr = Math.min(r, w / 2, h / 2);
    ctx.beginPath();
    ctx.moveTo(x + rr, y);
    ctx.arcTo(x + w, y, x + w, y + h, rr);
    ctx.arcTo(x + w, y + h, x, y + h, rr);
    ctx.arcTo(x, y + h, x, y, rr);
    ctx.arcTo(x, y, x + w, y, rr);
    ctx.closePath();
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

  _lerp(a, b, t) {
    return a + (b - a) * t;
  }

  _clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  _beginFrameCaches() {
    this._frameGeometry = this._foldGeometry();
    this._frameVisibleBoundaries = this._computeVisibleMeasureBoundaryBeats();
  }

  _endFrameCaches() {
    this._frameGeometry = null;
    this._frameVisibleBoundaries = null;
  }

  _foldGeometry() {
    const w = this.canvas.clientWidth;
    const h = this.canvas.clientHeight;
    // futureBeats is part of the key: it feeds pastLen below, so a density
    // change (setDensity) must not silently return a stale cached geometry.
    const key = `${Math.round(w)}:${Math.round(h)}:${this.futureBeats}`;
    if (this._frameGeometry) return this._frameGeometry;
    if (this._geometry && this._geometryKey === key) return this._geometry;
    const marginX = Math.max(70, Math.min(120, w * 0.055));
    const spacing = Math.max(30, Math.min(44, h * 0.052, w * 0.024));
    const spread = spacing * 5;
    const topBase = Math.max(54 + spread / 2, h * 0.20);
    const bottomBase = Math.min(h - 54 - spread / 2, h * 0.80);
    const radius = Math.max(86, (bottomBase - topBase) / 2);
    const outerRadius = radius + spread / 2;
    const startX = Math.max(marginX + 70, Math.min(w * 0.12, w - 520));
    const bendX = Math.max(startX + 260, w - marginX - outerRadius - 18);
    const farX = Math.max(marginX + 28, Math.min(startX - 96, w * 0.085));
    const centerY = (topBase + bottomBase) / 2;
    const bottomLen = Math.max(1, bendX - startX);
    const arcLen = Math.PI * radius;
    const topLen = Math.max(1, bendX - farX);
    const pastLen = (PAST_BEATS / this.futureBeats) * (bottomLen + arcLen + topLen);

    const geometry = {
      w,
      h,
      spacing,
      spread,
      topBase,
      bottomBase,
      startX,
      bendX,
      farX,
      radius,
      outerRadius,
      centerY,
      bottomLen,
      arcLen,
      topLen,
      pastLen,
      totalLen: bottomLen + arcLen + topLen,
    };
    this._geometry = geometry;
    this._geometryKey = key;
    return geometry;
  }

  _stringOffset(stringNum) {
    const g = this._foldGeometry();
    return (Number(stringNum) - 1 - 2.5) * g.spacing;
  }

  _lanePoint(stringNum, depth) {
    const g = this._foldGeometry();
    const minDepth = -PAST_BEATS / this.futureBeats;
    const t = this._clamp(depth, minDepth, 1.08);
    const d = t * g.totalLen;
    const offset = (Number(stringNum) - 1 - 2.5) * g.spacing;

    if (d < 0) {
      return {
        x: g.startX + d,
        y: g.bottomBase + offset,
        scale: 1,
      };
    }

    if (d <= g.bottomLen) {
      return {
        x: g.startX + d,
        y: g.bottomBase + offset,
        scale: 1,
      };
    }

    if (d <= g.bottomLen + g.arcLen) {
      const arcD = d - g.bottomLen;
      const angle = Math.PI / 2 - arcD / g.radius;
      const stringRadius = g.radius + offset;
      return {
        x: g.bendX + Math.cos(angle) * stringRadius,
        y: g.centerY + Math.sin(angle) * stringRadius,
        scale: 1,
      };
    }

    const topD = d - g.bottomLen - g.arcLen;
    return {
      x: g.bendX - topD,
      y: g.topBase - offset,
      scale: 1,
    };
  }

  _laneSpacing() {
    return this._foldGeometry().spacing;
  }

  _minimumGapBeats() {
    const g = this._foldGeometry();
    const pixelGapBeats = (MIN_NOTE_GAP_PX / Math.max(1, g.totalLen)) * this.futureBeats;
    return Math.max(STRING_COLLISION_GAP_BEATS, pixelGapBeats);
  }

  _depthForBeat(noteBeat) {
    return (noteBeat - this._renderBeat()) / this.futureBeats;
  }

  /* P4 — stepped scroll. Continuous glide is exactly what smooth pursuit
     can't track sharply, independent of refresh rate (the eye's tracking
     gain tops out around 0.9, never reaching 1). Quantizing the beat used
     for POSITIONING (not this.currentBeat itself, which stays continuous —
     see the constructor) turns the glide into a sequence of held frames:
     the eye gets a real fixation window between jumps instead of continuous
     motion to chase. Every on-screen position derives from _depthForBeat,
     so quantizing it there alone makes P4 apply everywhere (notes, chord
     labels, measure bars) without threading a mode check through each draw
     call. The now-line and hit flashes are pinned to depth 0 directly
     (bypassing _depthForBeat), so the strike line itself never jumps. */
  _renderBeat() {
    if (this.legibilityMode !== 'p4') return this.currentBeat;
    return Math.floor(this.currentBeat / this.stepBeats) * this.stepBeats;
  }

  _hitY() {
    return this._foldGeometry().bottomBase;
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
    gradient.addColorStop(0.48, '#151214');
    gradient.addColorStop(1, '#050506');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, w, h);

    ctx.save();
    ctx.strokeStyle = 'rgba(238, 238, 232, 0.56)';
    ctx.lineWidth = 1.4;
    ctx.shadowColor = 'rgba(238, 238, 232, 0.32)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 10;
    this._traceDepthPath(ctx, 1, 1, 1.055);
    this._traceDepthPath(ctx, 6, 1, 1.055);
    ctx.stroke();
    ctx.restore();

    this._drawStrings(ctx);
    this._drawStringLabels(ctx);
  }

  _drawStringLabels(ctx) {
    const g = this._foldGeometry();
    ctx.save();
    ctx.fillStyle = 'rgba(255,248,220,0.72)';
    ctx.font = `800 ${Math.max(11, Math.min(14, g.spacing * 0.78))}px Inter, sans-serif`;
    ctx.textAlign = 'right';
    ctx.textBaseline = 'middle';
    for (let stringNum = 1; stringNum <= 6; stringNum += 1) {
      const p = this._lanePoint(stringNum, 0);
      ctx.fillText(STRING_NAMES[stringNum], p.x - Math.max(22, g.spacing * 1.2), p.y);
    }
    ctx.restore();
  }

  _drawStrings(ctx = this.ctx) {
    for (let stringNum = 6; stringNum >= 1; stringNum -= 1) {
      const start = this._lanePoint(stringNum, 0);
      const end = this._lanePoint(stringNum, 1);
      const grad = ctx.createLinearGradient(start.x, start.y, end.x, end.y);
      grad.addColorStop(0, 'rgba(255,255,255,0.92)');
      grad.addColorStop(0.45, 'rgba(255,255,255,0.58)');
      grad.addColorStop(1, 'rgba(255,255,255,0.32)');
      ctx.strokeStyle = grad;
      ctx.lineWidth = 1.15 + (stringNum - 1) * 0.28;
      ctx.shadowColor = 'rgba(255,255,255,0.24)';
      ctx.shadowBlur = this._quality >= 2 ? 0 : 7;
      ctx.beginPath();
      this._traceDepthPath(ctx, stringNum, 0, 1);
      ctx.stroke();
    }
    ctx.shadowBlur = 0;
  }

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

  _drawMeasureBars() {
    const ctx = this.ctx;
    ctx.save();
    ctx.strokeStyle = 'rgba(255,255,255,0.86)';
    ctx.lineWidth = 1.05;
    ctx.shadowBlur = 0;

    for (const beat of this._visibleMeasureBoundaryBeats()) {
      if (Math.abs(beat - this.currentBeat) < 0.015) continue;
      this._strokeStringCrossbar(ctx, this._depthForBeat(beat), 0);
    }
    ctx.restore();
  }

  _strokeStringCrossbar(ctx, depth, extraSpacing = 0.55) {
    const g = this._foldGeometry();
    const high = this._lanePoint(1, depth);
    const low = this._lanePoint(6, depth);
    const dx = low.x - high.x;
    const dy = low.y - high.y;
    const len = Math.max(1, Math.hypot(dx, dy));
    const ux = dx / len;
    const uy = dy / len;
    ctx.beginPath();
    ctx.moveTo(high.x - ux * g.spacing * extraSpacing, high.y - uy * g.spacing * extraSpacing);
    ctx.lineTo(low.x + ux * g.spacing * extraSpacing, low.y + uy * g.spacing * extraSpacing);
    ctx.stroke();
  }

  _traceDepthPath(ctx, stringNum, startDepth, endDepth) {
    const minDepth = -PAST_BEATS / this.futureBeats;
    const start = this._clamp(startDepth, minDepth, 1.08);
    const end = this._clamp(endDepth, minDepth, 1.08);
    const steps = Math.max(3, Math.ceil(Math.abs(end - start) * (this._quality >= 2 ? 18 : 42)));
    for (let i = 0; i <= steps; i += 1) {
      const depth = this._lerp(start, end, i / steps);
      const p = this._lanePoint(stringNum, depth);
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
  }

  _circleRadius() {
    // Bumped 10-16 -> 12-18 (Lot C follow-up #2, legibility): the old cap left
    // ~6px of headroom for a fret digit + note-name letter stacked in one
    // disc — too little regardless of pixel-crispness. Capped at 18, not
    // higher, so adjacent-string discs (spacing tops out at 44px) keep a
    // visible gap rather than touching.
    if (this.legibilityMode === 'p2') {
      // P2 drops the note-name letter (see _drawFretDisc), so the disc only
      // ever holds one glyph — push the cap close to _laneSpacing()'s ceiling
      // (44px) instead of leaving headroom for a second line of text.
      // Stays just under spacing/2 so adjacent-string discs still clear each
      // other by a couple of px rather than touching.
      return Math.max(16, Math.min(24, this._laneSpacing() * 0.48));
    }
    return Math.max(12, Math.min(18, this._laneSpacing() * 0.40));
  }

  _pixelBeats(px) {
    const g = this._foldGeometry();
    return (px / Math.max(1, g.totalLen)) * this.futureBeats;
  }

  _visibleMeasureBoundaryBeats() {
    if (this._frameVisibleBoundaries) return this._frameVisibleBoundaries;
    return this._computeVisibleMeasureBoundaryBeats();
  }

  _computeVisibleMeasureBoundaryBeats() {
    const totalBeats = this._totalBeats();
    const boundaries = this._measureBoundaryBeats();
    const minBeat = this.currentBeat - PAST_BEATS - MEASURE_BEATS;
    const maxBeat = this.currentBeat + this.futureBeats * 1.12 + MEASURE_BEATS;
    const visible = new Map();
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const boundary of boundaries) {
        const beat = boundary + repeat * totalBeats;
        if (beat >= minBeat && beat <= maxBeat) visible.set(beat.toFixed(6), beat);
      }
    }
    return Array.from(visible.values()).sort((a, b) => a - b);
  }

  _distanceToMeasureBoundaryBeats(beat) {
    let best = Infinity;
    for (const boundary of this._visibleMeasureBoundaryBeats()) {
      if (Math.abs(boundary - this.currentBeat) < 0.015) continue;
      best = Math.min(best, Math.abs(boundary - beat));
    }
    return best;
  }

  _noteBeatSegments(note) {
    const start = Number(note.onset);
    const end = start + Number(note.duration || 0);
    if (!(end > start)) return [];
    const pad = this._pixelBeats(MEASURE_NOTE_PAD_PX);
    const boundaries = this._visibleMeasureBoundaryBeats()
      .filter((beat) => beat > start + pad && beat < end - pad);
    let cursor = start;
    const segments = [];
    for (const boundary of boundaries) {
      const leftEnd = boundary - pad;
      if (leftEnd - cursor > 0.025) segments.push([cursor, leftEnd]);
      cursor = boundary + pad;
    }
    if (end - cursor > 0.025) segments.push([cursor, end]);
    return segments;
  }

  _markReadableLabels(visible) {
    const radius = this._circleRadius();
    const minDistance = radius * 2 + MIN_CIRCLE_PAD_PX;
    const measurePadBeats = this._pixelBeats(radius + MEASURE_NOTE_PAD_PX);
    const byString = new Map();
    for (const note of visible.sort((a, b) => a.onset - b.onset || a.string - b.string)) {
      const startDepth = this._depthForBeat(note.onset);
      const endDepth = this._depthForBeat(note.onset + note.duration);
      const labelDepth = this._clamp(
        (Math.max(-PAST_BEATS / this.futureBeats, startDepth) + Math.min(1.06, endDepth)) / 2,
        -PAST_BEATS / this.futureBeats,
        1.06,
      );
      const point = this._lanePoint(note.string, labelDepth);
      note._labelPoint = point;
      note._labelDepth = labelDepth;
      const labelBeat = this.currentBeat + labelDepth * this.futureBeats;
      const clearsMeasure = this._distanceToMeasureBoundaryBeats(labelBeat) >= measurePadBeats;
      const prev = byString.get(note.string);
      const farEnough = !prev || Math.hypot(point.x - prev.x, point.y - prev.y) >= minDistance;
      note.showLabel = farEnough && clearsMeasure;
      if (note.showLabel) byString.set(note.string, point);
    }
    return visible;
  }

  _visibleNotesForFrame() {
    const visible = [];
    const totalBeats = this._totalBeats();
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const source of this.notes) {
        const note = { ...source, onset: source.onset + repeat * totalBeats };
        const startDepth = this._depthForBeat(note.onset);
        const endDepth = this._depthForBeat(note.onset + note.duration);
        if (endDepth >= -PAST_BEATS / this.futureBeats && startDepth <= 1.12) visible.push(note);
      }
    }
    visible.sort((a, b) => a.string - b.string || a.onset - b.onset);
    const gapBeats = this._minimumGapBeats();
    const byString = new Map();
    for (const note of visible) {
      const notesOnString = byString.get(note.string) || [];
      notesOnString.push(note);
      byString.set(note.string, notesOnString);
    }
    for (const notesOnString of byString.values()) {
      notesOnString.sort((a, b) => a.onset - b.onset);
      for (let i = 0; i < notesOnString.length - 1; i += 1) {
        const note = notesOnString[i];
        const next = notesOnString[i + 1];
        const maxDuration = Math.max(0.05, next.onset - note.onset - gapBeats);
        note.duration = Math.min(note.duration, maxDuration);
      }
    }
    return this._markReadableLabels(visible).sort((a, b) => b.onset - a.onset);
  }

  _visibleChordsForFrame() {
    const visible = [];
    const totalBeats = this._totalBeats();
    for (let repeat = -1; repeat <= 1; repeat += 1) {
      for (const source of this.chordEvents) {
        const chord = { ...source, onset: source.onset + repeat * totalBeats };
        const depth = this._depthForBeat(chord.onset);
        if (depth >= -0.08 && depth <= 1.12) visible.push(chord);
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
        noteName: note.noteName,
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
    const ttl = this._quality >= 2 ? 180 : 150;
    this._hitFlashes = this._hitFlashes.filter((flash) => now - flash.created < ttl);
    const ctx = this.ctx;
    for (const flash of this._hitFlashes) {
      const age = now - flash.created;
      const alpha = Math.max(0, 1 - age / ttl);
      const point = this._lanePoint(flash.string, 0);
      const meta = FINGER_META[String(flash.finger || '').toLowerCase()] || FINGER_META.open;
      const radius = this._circleRadius();
      ctx.save();
      ctx.globalAlpha = alpha;
      ctx.shadowColor = meta.color;
      ctx.shadowBlur = this._quality >= 2 ? 0 : 18 * alpha;
      this._drawFretDisc(ctx, flash, point, radius * (1 + (1 - alpha) * 0.25), meta);
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
    if (endDepth < 0 || startDepth > 1.12) return;

    const now = this.currentBeat;
    const active = note.onset <= now && now <= note.onset + note.duration;
    const vibration = active ? 1 + 0.16 * Math.sin(performance.now() / 34) : 1;
    const minDepth = -PAST_BEATS / this.futureBeats;
    const rawADepth = Math.max(minDepth, Math.min(1.08, startDepth));
    const rawBDepth = Math.max(0, Math.min(1.08, endDepth));
    const meta = FINGER_META[String(note.finger || '').toLowerCase()] || FINGER_META.open;
    const exportWarning = note.gp_fingering_export_status === 'missing_source_note_id';
    const strokeColor = exportWarning ? '#e53935' : meta.color;
    const ctx = this.ctx;
    const tubeWidth = Math.max(8, Math.min(14, this._laneSpacing() * 0.34)) * vibration;
    const segments = this._noteBeatSegments(note)
      .map(([from, to]) => [
        this._clamp(this._depthForBeat(from), minDepth, 1.08),
        this._clamp(this._depthForBeat(to), minDepth, 1.08),
      ])
      .filter(([fromDepth, toDepth]) => toDepth > minDepth && fromDepth < 1.08);
    if (!segments.length) return;

    ctx.save();
    ctx.lineCap = 'round';
    ctx.lineJoin = 'round';
    ctx.shadowColor = strokeColor;
    ctx.shadowBlur = this._quality >= 2 ? 0 : active ? 28 * vibration : 14;
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = tubeWidth * 1.45;
    ctx.globalAlpha = active ? 0.34 : 0.18;
    if (this._quality < 2 || active) {
      for (const [aDepth, bDepth] of segments) {
        ctx.beginPath();
        this._traceDepthPath(ctx, note.string, aDepth, bDepth);
        ctx.stroke();
      }
    }

    ctx.globalAlpha = 0.92;
    ctx.shadowBlur = this._quality >= 2 ? 0 : active ? 16 * vibration : 9;
    ctx.strokeStyle = strokeColor;
    ctx.lineWidth = tubeWidth;
    for (const [aDepth, bDepth] of segments) {
      ctx.beginPath();
      this._traceDepthPath(ctx, note.string, aDepth, bDepth);
      ctx.stroke();
    }

    ctx.shadowBlur = 0;
    ctx.globalAlpha = 0.50;
    ctx.strokeStyle = 'rgba(255,255,255,0.76)';
    ctx.lineWidth = Math.max(3, tubeWidth * 0.16);
    for (const [aDepth, bDepth] of segments) {
      ctx.beginPath();
      this._traceDepthPath(ctx, note.string, aDepth, bDepth);
      ctx.stroke();
    }

    const labelPoint = note._labelPoint || this._lanePoint(
      note.string,
      this._clamp((rawADepth + rawBDepth) / 2, minDepth, 1.06),
    );
    const labelRadius = this._circleRadius();
    if (note.showLabel !== false) {
      ctx.globalAlpha = 1;
      ctx.shadowColor = 'rgba(255,255,255,0.48)';
      ctx.shadowBlur = this._quality >= 2 ? 0 : 9;
      this._drawFretDisc(ctx, note, labelPoint, labelRadius, meta);
      if (note.chord) this._drawChordTriangle(labelPoint, labelRadius, labelPoint.scale);
    } else if (active) {
      ctx.globalAlpha = 0.95;
      ctx.shadowColor = strokeColor;
      ctx.shadowBlur = this._quality >= 2 ? 0 : 10;
      this._drawFretDisc(ctx, note, labelPoint, labelRadius * 0.72, meta, false);
    }
    ctx.restore();
  }

  /* T-P3.1: snap a CSS-px coordinate to the nearest DEVICE pixel (the canvas
     transform is set to `dpr` in resize(), so every draw call happens in CSS
     px — a fractional CSS px means the glyph rasterizes at a different
     sub-pixel offset every frame while the note glides, which reads as a
     blur/shimmer even though nothing about the text itself changed). */
  _snapPx(v) {
    const dpr = this.dpr || 1;
    return Math.round(v * dpr) / dpr;
  }

  /* T-P3.2: round a font size to a size that lands on an integer DEVICE
     pixel, clamped to never render below `floorDevicePx` (a font a fraction
     of a device pixel tall is what actually reads as "bouillie", independent
     of the fractional-position blur T-P3.1 fixes). Use for text that must
     always render (the fret digit — never skip it). */
  _snapFontSizeClamped(cssSize, floorDevicePx) {
    const dpr = this.dpr || 1;
    const devicePx = Math.max(floorDevicePx, Math.round(cssSize * dpr));
    return devicePx / dpr;
  }

  _drawFretDisc(ctx, note, point, radius, meta, showText = true) {
    const exportWarning = note.gp_fingering_export_status === 'missing_source_note_id';
    ctx.fillStyle = exportWarning ? '#ffe3e3' : (meta.discColor || '#fffdf2');
    ctx.beginPath();
    ctx.arc(point.x, point.y, radius, 0, Math.PI * 2);
    ctx.fill();
    ctx.strokeStyle = exportWarning ? '#e53935' : meta.color;
    ctx.lineWidth = Math.max(1.4, radius * 0.14);
    ctx.stroke();
    if (!showText) return;
    ctx.shadowBlur = 0;
    ctx.fillStyle = exportWarning ? '#d32f2f' : '#050505';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    // In P1 the fixed reading band carries the note name; the moving disc drops
    // the letter and shows the fret digit alone — one thick glyph survives motion
    // far better than two stacked, and the redundant letter is right there in the
    // band, read in fixation. P2 drops it too, for the same reason plus its own
    // goal: maximize the fret digit itself (_circleRadius already gives P2 a
    // bigger disc; freeing the second text row lets the digit fill it).
    const noteName = (this.legibilityMode === 'p1' || this.legibilityMode === 'p2') ? '' : (note.noteName || '');
    const alpha = ctx.globalAlpha;
    const px = this._snapPx(point.x);
    const dpr = this.dpr || 1;
    // Legibility floors (Lot C follow-up #2): the floor MUST be expressed as
    // `desiredCssPx * dpr`, not a bare device-px constant. A bare device-px
    // floor (the old "11 device px") is fine at dpr>=2 but on a 1x display —
    // the common case on a high-refresh (144-240Hz) gaming monitor, which is
    // almost never run at fractional OS scaling — device px === CSS px, so
    // "11 device px" is really just an 11 CSS px floor... except the OLD
    // note-name floor (8 device px) with the old raw size formula
    // (radius*0.38, ~6 CSS px at max radius) computed devicePx=round(6*1)=6,
    // BELOW the floor of 8, so _snapFontSizeOrNull returned null — the
    // note-name letter was silently never drawn at all on a 1x display,
    // independent of every crispness fix (backing-store DPR, CSS-box pin):
    // there was nothing there to be crisp. Scaling the floor by dpr fixes
    // that at the source, and raising both floors to real reading sizes (not
    // just "big enough to rasterize cleanly") addresses the digit being
    // technically crisp but still too small to read while gliding.
    const fretSizeRaw = noteName ? Math.max(13, radius * 0.80) : Math.max(14, radius * 0.95);
    const fretSize = this._snapFontSizeClamped(fretSizeRaw, Math.round(13 * dpr));
    ctx.font = `900 ${fretSize}px Inter, sans-serif`;
    ctx.fillText(String(note.fret), px, this._snapPx(point.y - (noteName ? radius * 0.18 : -0.5)));
    if (noteName) {
      // Note-name letter: guaranteed >=9 CSS px now (never dropped — a
      // consistently-small differentiator letter beats one that vanishes on
      // some displays and not others).
      const nameSizeRaw = Math.max(9, radius * 0.44);
      const nameSize = this._snapFontSizeClamped(nameSizeRaw, Math.round(9 * dpr));
      ctx.globalAlpha = alpha * 0.88;
      ctx.font = `850 ${nameSize}px Inter, sans-serif`;
      ctx.fillText(noteName, px, this._snapPx(point.y + radius * 0.42));
      ctx.globalAlpha = alpha;
    }
  }

  _drawChordLabel(chord) {
    const startDepth = this._depthForBeat(chord.onset);
    const endDepth = this._depthForBeat(chord.onset + chord.duration);
    const labelDepth = Math.max(0, Math.min(1.06, (startDepth + endDepth) / 2));
    const high = this._lanePoint(1, labelDepth);
    const g = this._foldGeometry();
    const rawX = high.x + Math.max(28, g.spacing * 1.6);
    const x = Math.min(this.canvas.clientWidth - 92, rawX);
    const labelRadius = Math.max(16, Math.min(27, g.spacing * 1.12));
    const y = this._chordTriangleCenterY(high, labelRadius, high.scale);
    const ctx = this.ctx;
    ctx.save();
    ctx.fillStyle = '#ff3030';
    ctx.shadowColor = 'rgba(255, 48, 48, 0.72)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 20;
    ctx.font = '900 22px Inter, sans-serif';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.fillText(chord.label, this._snapPx(x), this._snapPx(y));
    ctx.restore();
  }

  _drawNowPulse() {
    const ctx = this.ctx;
    const g = this._foldGeometry();
    ctx.save();
    ctx.strokeStyle = '#1f8fff';
    ctx.lineWidth = Math.max(3.2, g.spacing * 0.13);
    ctx.shadowColor = 'rgba(31,143,255,0.75)';
    ctx.shadowBlur = this._quality >= 2 ? 0 : 12;
    this._strokeStringCrossbar(ctx, 0, 0);
    ctx.translate(5, 0);
    this._strokeStringCrossbar(ctx, 0, 0);
    ctx.restore();
  }

  _drawTempoHeart() {
    const ctx = this.ctx;
    const beatPhase = this.currentBeat - Math.floor(this.currentBeat);
    const pulse = 1 + Math.pow(1 - beatPhase, 5) * 0.34;
    const cx = Math.max(54, this.canvas.clientWidth * 0.055);
    // Vertical-center placement used to be safe when this was the only thing
    // drawn there; it now collides with the P1 reading band / P2 density
    // readout / P3-P4 tags, which all live in the lane gap around
    // clientHeight*0.5 (confirmed: "72 BPM" landing directly on a band
    // card's digit row). Pin it above the top lane instead — dead space no
    // legibility aid uses.
    const cy = Math.max(40, this._foldGeometry().topBase - 45);
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
