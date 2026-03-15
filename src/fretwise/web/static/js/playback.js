/**
 * playback.js — Playback engine with tempo-accurate cursor, audio synthesis,
 * metronome, A/B loop selection, and beat-level scheduling.
 */

export class PlaybackEngine {
  /**
   * @param {import('./renderer.js').TabRenderer} renderer
   * @param {Object} opts
   * @param {number} [opts.tempo] BPM
   * @param {number} [opts.beatsPerMeasure]
   */
  constructor(renderer, opts = {}) {
    this.renderer = renderer;
    this.tempo = opts.tempo || renderer.tempo || 120;
    this.bpm = opts.beatsPerMeasure || renderer.bpm || 4;
    this.speed = 1.0;       // playback speed multiplier
    this.loopStart = -1;
    this.loopEnd = -1;
    this.isPlaying = false;
    this.metronome = false;
    this.audioEnabled = false;
    this._raf = null;
    this._startTime = 0;
    this._startMeasure = 0;
    this._audioCtx = null;
    this._masterGain = null;
    this._volume = 0.7;        // master volume 0..1
    this._lastScheduledMeasure = -1;

    // Callbacks
    this.onMeasureChange = null;
    this.onStop = null;
    this.onPositionChange = null; // (measureFrac) → 0..1 fraction of song
  }

  get totalMeasures() {
    return this.renderer.measures.length;
  }

  /** Seconds per measure = (beatsPerMeasure / tempo) * 60 */
  get secondsPerMeasure() {
    return (this.bpm / this.tempo) * 60 / this.speed;
  }

  /** Enable audio — must be called on user gesture */
  enableAudio() {
    if (!this._audioCtx) {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (!this._masterGain) {
      this._masterGain = this._audioCtx.createGain();
      this._masterGain.gain.value = this._volume;
      this._masterGain.connect(this._audioCtx.destination);
    }
    if (this._audioCtx.state === 'suspended') {
      this._audioCtx.resume();
    }
    this.audioEnabled = true;
    return true;
  }

  disableAudio() {
    this.audioEnabled = false;
    return false;
  }

  /** Set master volume (0.0 – 1.0). */
  setVolume(v) {
    this._volume = Math.max(0, Math.min(1, v));
    if (this._masterGain) {
      this._masterGain.gain.setTargetAtTime(
        this._volume, this._audioCtx.currentTime, 0.015
      );
    }
  }

  /** Start or resume playback from current cursor */
  play() {
    if (this.isPlaying) return;
    this.isPlaying = true;
    this._startMeasure = this.renderer.cursorMeasure;
    this._startTime = performance.now();
    this._lastScheduledMeasure = -1;

    if ((this.metronome || this.audioEnabled) && !this._audioCtx) {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    if (this._audioCtx && !this._masterGain) {
      this._masterGain = this._audioCtx.createGain();
      this._masterGain.gain.value = this._volume;
      this._masterGain.connect(this._audioCtx.destination);
    }
    if (this._audioCtx?.state === 'suspended') {
      this._audioCtx.resume();
    }

    // Schedule the first measure immediately (cursor hasn't moved yet)
    const m0 = this._startMeasure;
    this._lastScheduledMeasure = m0;
    if (this.metronome) this._scheduleMetronomeMeasure(m0);
    if (this.audioEnabled) this._scheduleMeasureNotes(m0);

    this._tick();
  }

  /** Pause playback */
  pause() {
    this.isPlaying = false;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
  }

  /** Toggle play/pause */
  toggle() {
    if (this.isPlaying) this.pause();
    else this.play();
  }

  /** Stop and reset to beginning */
  stop() {
    this.pause();
    this.renderer.cursorMeasure = 0;
    this.renderer.render();
    if (this.onStop) this.onStop();
  }

  /** Jump to specific measure */
  goToMeasure(m) {
    const wasPlaying = this.isPlaying;
    this.pause();
    this.renderer.cursorMeasure = Math.max(0, Math.min(m, this.totalMeasures - 1));
    this.renderer.render();
    if (this.onMeasureChange) this.onMeasureChange(this.renderer.cursorMeasure);
    if (this.onPositionChange) this.onPositionChange(this.renderer.cursorMeasure / Math.max(1, this.totalMeasures - 1));
    if (wasPlaying) this.play();
  }

  /** Go to previous measure */
  prev() { this.goToMeasure(this.renderer.cursorMeasure - 1); }

  /** Go to next measure */
  next() { this.goToMeasure(this.renderer.cursorMeasure + 1); }

  /** Set speed multiplier (0.1 – 2.0) */
  setSpeed(s) {
    const wasMeasure = this.renderer.cursorMeasure;
    const wasPlaying = this.isPlaying;
    this.pause();
    this.speed = Math.max(0.1, Math.min(2.0, s));
    if (wasPlaying) {
      this._startMeasure = wasMeasure;
      this._startTime = performance.now();
      this.play();
    }
  }

  /** Set loop A marker (start) */
  setLoopStart(m) {
    this.loopStart = Math.max(0, Math.min(m, this.totalMeasures - 1));
    this.renderer.loopStart = this.loopStart;
    if (this.loopEnd < this.loopStart) {
      this.loopEnd = this.loopStart;
      this.renderer.loopEnd = this.loopEnd;
    }
    this.renderer.render();
  }

  /** Set loop B marker (end) */
  setLoopEnd(m) {
    this.loopEnd = Math.max(0, Math.min(m, this.totalMeasures - 1));
    this.renderer.loopEnd = this.loopEnd;
    if (this.loopStart < 0) {
      this.loopStart = 0;
      this.renderer.loopStart = 0;
    }
    if (this.loopEnd < this.loopStart) {
      this.loopStart = this.loopEnd;
      this.renderer.loopStart = this.loopStart;
    }
    this.renderer.render();
  }

  /** Clear loop range */
  clearLoop() {
    this.loopStart = -1;
    this.loopEnd = -1;
    this.renderer.loopStart = -1;
    this.renderer.loopEnd = -1;
    this.renderer.render();
  }

  /** Set loop range directly (for legacy full-song loop) */
  setLoop(start, end) {
    this.loopStart = start;
    this.loopEnd = end;
    this.renderer.loopStart = start;
    this.renderer.loopEnd = end;
    this.renderer.render();
  }

  /** Toggle metronome */
  toggleMetronome() {
    this.metronome = !this.metronome;
    if (this.metronome && !this._audioCtx) {
      this._audioCtx = new (window.AudioContext || window.webkitAudioContext)();
    }
    return this.metronome;
  }

  // ── Internal animation loop ───────────────────────────────────────

  _tick() {
    if (!this.isPlaying) return;

    const elapsed = (performance.now() - this._startTime) / 1000;
    const measureOffset = Math.floor(elapsed / this.secondsPerMeasure);
    let targetMeasure = this._startMeasure + measureOffset;

    // Loop handling
    if (this.loopStart >= 0 && this.loopEnd >= this.loopStart) {
      const loopLen = this.loopEnd - this.loopStart + 1;
      if (targetMeasure > this.loopEnd) {
        // Loop back: restart from loopStart
        this._startMeasure = this.loopStart;
        this._startTime = performance.now();
        this._lastScheduledMeasure = -1;
        targetMeasure = this.loopStart;
      }
    }

    // End of song
    if (targetMeasure >= this.totalMeasures) {
      this.pause();
      this.renderer.cursorMeasure = this.totalMeasures - 1;
      this.renderer.render();
      if (this.onStop) this.onStop();
      return;
    }

    // Update cursor if changed
    if (targetMeasure !== this.renderer.cursorMeasure) {
      this.renderer.cursorMeasure = targetMeasure;
      this.renderer.render();
      if (this.onMeasureChange) this.onMeasureChange(targetMeasure);
      if (this.onPositionChange) this.onPositionChange(targetMeasure / Math.max(1, this.totalMeasures - 1));

      // Scroll cursor into view
      this._scrollCursorIntoView();

      // Schedule audio for this measure
      if (targetMeasure !== this._lastScheduledMeasure) {
        this._lastScheduledMeasure = targetMeasure;
        if (this.metronome) this._scheduleMetronomeMeasure(targetMeasure);
        if (this.audioEnabled) this._scheduleMeasureNotes(targetMeasure);
      }
    }

    this._raf = requestAnimationFrame(() => this._tick());
  }

  _scrollCursorIntoView() {
    const canvas = this.renderer.canvas;
    const container = canvas.parentElement;
    if (!container) return;

    const sys = this.renderer.systems.find(
      s => this.renderer.cursorMeasure >= s.startMeasure &&
           this.renderer.cursorMeasure < s.startMeasure + s.measures.length
    );
    if (!sys) return;

    const sysIdx = this.renderer.systems.indexOf(sys);
    const SYSTEM_H = 200, INTER_SYSTEM = 16, MARGIN_T = 12;
    const sysY = MARGIN_T + sysIdx * (SYSTEM_H + INTER_SYSTEM);

    const rect = container.getBoundingClientRect();
    if (sysY < container.scrollTop || sysY + SYSTEM_H > container.scrollTop + rect.height) {
      container.scrollTo({ top: Math.max(0, sysY - 40), behavior: 'smooth' });
    }
  }

  // ── Metronome click ───────────────────────────────────────────────

  /** Schedule N metronome clicks for the given measure (one per beat). */
  _scheduleMetronomeMeasure(_measureIdx) {
    if (!this._audioCtx) return;
    const secPerBeat = (60 / this.tempo) / this.speed;
    const now = this._audioCtx.currentTime;
    for (let b = 0; b < this.bpm; b++) {
      this._click(now + b * secPerBeat, b === 0);
    }
  }

  /** Schedule a single metronome click.
   *  @param {number} t — AudioContext time
   *  @param {boolean} isDownbeat — first beat gets a higher pitch
   */
  _click(t, isDownbeat = false) {
    if (!this._audioCtx) return;
    const startTime = t ?? this._audioCtx.currentTime;
    const osc = this._audioCtx.createOscillator();
    const gain = this._audioCtx.createGain();
    osc.connect(gain);
    gain.connect(this._masterGain || this._audioCtx.destination);
    osc.frequency.value = isDownbeat ? 1200 : 900;
    gain.gain.setValueAtTime(0.18, startTime);
    gain.gain.exponentialRampToValueAtTime(0.001, startTime + 0.06);
    osc.start(startTime);
    osc.stop(startTime + 0.08);
  }

  // ── Note audio synthesis ──────────────────────────────────────────

  /** Schedule all notes in a measure to play at correct times.
   *  @param {number} measureIdx
   *  @param {number} [offsetSec=0] — extra delay (seconds) added to all notes,
   *    used for lookahead scheduling of the NEXT measure before its cursor fires.
   */
  _scheduleMeasureNotes(measureIdx, offsetSec = 0) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const notes = this.renderer.measures[measureIdx];
    if (!notes || !notes.length) return;

    const bpm = this.bpm;
    const measureOnset = Math.floor(notes[0].onset / bpm) * bpm;
    const secPerBeat = (60 / this.tempo) / this.speed;
    const now = this._audioCtx.currentTime;

    for (const note of notes) {
      const beatInMeasure = note.onset - measureOnset;
      const delay = offsetSec + beatInMeasure * secPerBeat;
      const durSec = note.duration * secPerBeat;
      this._scheduleNote(note.pitch, now + delay, durSec);
    }
  }

  /**
   * Synthesize a plucked-string guitar note using additive synthesis.
   * Multiple sine harmonics with individual decay rates approximate
   * the bright attack and natural decay of a plucked guitar string.
   */
  _scheduleNote(pitch, startTime, durationSec) {
    if (!this._audioCtx) return;
    const ctx = this._audioCtx;
    const freq = 440 * Math.pow(2, (pitch - 69) / 12);

    // Master compressor to avoid clipping
    const comp = ctx.createDynamicsCompressor();
    comp.threshold.value = -18;
    comp.ratio.value = 4;
    // Route: osc → gain → body → comp → masterGain → destination
    const dest = this._masterGain || ctx.destination;
    comp.connect(dest);

    // Harmonic series: [relative amplitude, decay multiplier]
    // Higher harmonics decay faster — typical of plucked strings
    const harmonics = [
      [0.28, 0.90],  // fundamental — slow decay
      [0.22, 0.70],  // 2nd harmonic
      [0.16, 0.55],  // 3rd
      [0.10, 0.42],  // 4th
      [0.07, 0.32],  // 5th
      [0.04, 0.24],  // 6th
      [0.02, 0.18],  // 7th
      [0.01, 0.13],  // 8th
    ];

    // Slight body resonance — lowpass peaking around 200-800 Hz
    const body = ctx.createBiquadFilter();
    body.type = 'peaking';
    body.frequency.value = Math.min(freq * 2.5, 600);
    body.gain.value = 3;
    body.Q.value = 0.8;
    body.connect(comp);

    const attackDur = 0.003;  // 3 ms attack — sharp pluck

    // Use entries() — indexOf([...]) always returns -1 in JS (reference comparison)
    for (const [harmIdx, [ampRel, decayMul]] of harmonics.entries()) {
      const harmFreq = freq * (harmIdx + 1);
      if (harmFreq > 18000) continue;  // beyond hearing range

      const osc = ctx.createOscillator();
      osc.type = 'sine';
      osc.frequency.value = harmFreq;

      const gain = ctx.createGain();
      const decayEnd = startTime + Math.max(0.15, Math.min(durationSec * decayMul, 3.0));

      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(ampRel * 0.9, startTime + attackDur);
      gain.gain.exponentialRampToValueAtTime(0.0001, decayEnd);

      osc.connect(gain);
      gain.connect(body);

      osc.start(startTime);
      osc.stop(decayEnd + 0.02);
    }
  }
}

