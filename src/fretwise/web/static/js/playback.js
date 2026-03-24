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
    this._synth = null;          // soundfont-player Player (null = oscillator fallback)
    this._synthLoading = false;  // loading guard to avoid double-init
    this._instrumentName = 'electric_guitar_clean'; // current soundfont instrument
    // Secondary audio channels: [{trackId, trackName, measures, synth, gain, enabled, _loading}]
    this._secondaryChannels = [];

    // Callbacks
    this.onMeasureChange = null;
    this.onStop = null;
    this.onPositionChange = null; // (measureFrac) → 0..1 fraction of song
    this.onSynthStatusChange = null; // ('loading'|'ready'|'error') → void
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
    this._initSynth().catch(() => { /* oscillator fallback ok */ });
    // Reload any secondary channels whose synth was stopped
    for (const ch of this._secondaryChannels) {
      if (!ch.synth) this._loadChannelInstrument(ch).catch(() => {});
    }
    return true;
  }

  disableAudio() {
    this.audioEnabled = false;
    if (this._synth) {
      try { this._synth.stop(); } catch (_) {}
    }
    for (const ch of this._secondaryChannels) {
      if (ch.synth) { try { ch.synth.stop(); } catch (_) {} ch.synth = null; }
    }
    return false;
  }

  // ── Secondary channel management ─────────────────────────────────

  /**
   * Build a measures array from a flat results array (same logic as _groupMeasures).
   * @param {Array} results — note objects with onset field
   * @param {number} bpm — beats per measure
   * @returns {Array<Array>}
   */
  static _buildMeasures(results, bpm) {
    if (!results || !results.length) return [];
    const measures = [];
    let bucket = [];
    let start = 0;
    for (const n of results) {
      while (n.onset >= start + bpm - 0.001) {
        measures.push(bucket);
        bucket = [];
        start += bpm;
      }
      bucket.push(n);
    }
    if (bucket.length) measures.push(bucket);
    return measures;
  }

  /**
   * Add a secondary audio channel for a track (plays alongside the primary).
   * @param {number} trackId
   * @param {string} trackName
   * @param {Array}  results — note objects from /api/notes
   * @param {number} beatsPerMeasure
   */
  addSecondaryChannel(trackId, trackName, results, beatsPerMeasure) {
    this.removeSecondaryChannel(trackId); // remove if already present
    const bpm = beatsPerMeasure || this.bpm;
    const measures = PlaybackEngine._buildMeasures(results, bpm);
    const ch = { trackId, trackName, measures, synth: null, gain: 0.8, enabled: true, _loading: false };
    this._secondaryChannels.push(ch);
    if (this.audioEnabled && this._audioCtx) {
      this._loadChannelInstrument(ch).catch(err =>
        console.warn(`[FretWise] secondary channel "${trackName}" load failed:`, err)
      );
    }
  }

  /**
   * Remove and stop a secondary audio channel.
   * @param {number} trackId
   */
  removeSecondaryChannel(trackId) {
    const idx = this._secondaryChannels.findIndex(c => c.trackId === trackId);
    if (idx >= 0) {
      const ch = this._secondaryChannels[idx];
      if (ch.synth) { try { ch.synth.stop(); } catch (_) {} }
      this._secondaryChannels.splice(idx, 1);
    }
  }

  /**
   * Load soundfont-player instrument for a secondary channel.
   * @param {Object} ch — secondary channel object
   */
  async _loadChannelInstrument(ch) {
    if (ch._loading || ch.synth) return;
    ch._loading = true;
    try {
      if (!window.Soundfont) {
        await new Promise((resolve, reject) => {
          // Script already injected by _initSynth? Check before adding again
          if (document.querySelector('script[src*="soundfont-player"]')) { resolve(); return; }
          const s = document.createElement('script');
          s.src = '/static/js/vendor/soundfont-player.min.js';
          s.onload = resolve;
          s.onerror = () => reject(new Error('soundfont-player load failed'));
          document.head.appendChild(s);
        });
      }
      if (!window.Soundfont) throw new Error('Soundfont not available');
      const instName = PlaybackEngine._inferInstrument(ch.trackName);
      ch.synth = await window.Soundfont.instrument(
        this._audioCtx,
        instName,
        {
          soundfont: 'MusyngKite',
          format: 'mp3',
          nameToUrl: (name, sf, format) =>
            `/static/js/vendor/soundfonts/${sf}/${name}-${format}.js`,
          destination: this._masterGain || this._audioCtx.destination,
          gain: 4,
        }
      );
      console.log(`[FretWise] secondary "${ch.trackName}" ready (${instName})`);
    } catch (err) {
      console.warn(`[FretWise] secondary "${ch.trackName}" load failed:`, err);
      ch.synth = null;
    } finally {
      ch._loading = false;
    }
  }

  /**
   * Infer the GM soundfont instrument name from a human-readable track name.
   * @param {string} trackName — e.g. "E. Guitar", "Bass", "Distortion"
   * @returns {string} soundfont instrument name (matches gleitz/midi-js-soundfonts key)
   */
  static _inferInstrument(trackName) {
    const n = (trackName || '').toLowerCase();
    if (/dist|metal|crunch|heavy/i.test(n))       return 'distortion_guitar';
    if (/overdriv|driven/i.test(n))                return 'overdriven_guitar';
    if (/bass/i.test(n))                           return 'electric_bass_finger';
    if (/nylon|classical/i.test(n))                return 'acoustic_guitar_nylon';
    if (/acoustic|folk|steel/i.test(n))            return 'acoustic_guitar_steel';
    // Default: clean electric covers Lead, Rhythm, E. Guitar, Jazz Guitar, etc.
    return 'electric_guitar_clean';
  }

  /**
   * Set the current instrument from a track name string and (re)load if needed.
   * Safe to call before or after enableAudio().
   * @param {string} trackName — human-readable name from the API
   */
  setInstrument(trackName) {
    const inst = PlaybackEngine._inferInstrument(trackName);
    if (inst === this._instrumentName && this._synth) return; // no change
    this._instrumentName = inst;
    // Discard previous synth so _initSynth() reloads with new instrument
    if (this._synth) {
      try { this._synth.stop(); } catch (_) {}
      this._synth = null;
    }
    this._synthLoading = false;
    if (this.audioEnabled) {
      this._initSynth().catch(() => {});
    }
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

  /**
   * Load soundfont-player (UMD) and the MusyngKite soundfont for the current instrument.
   * On success, this._synth = Soundfont Player instance.
   * On any failure, this._synth stays null and the oscillator fallback is used.
   */
  async _initSynth() {
    if (this._synth || this._synthLoading) return;
    this._synthLoading = true;
    if (this.onSynthStatusChange) this.onSynthStatusChange('loading');
    try {
      // Step 1 — inject soundfont-player UMD script (sets window.Soundfont)
      if (!window.Soundfont) {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = '/static/js/vendor/soundfont-player.min.js';
          s.onload = resolve;
          s.onerror = () => reject(new Error('soundfont-player script failed to load'));
          document.head.appendChild(s);
        });
      }
      if (!window.Soundfont) throw new Error('window.Soundfont not defined after script load');

      // Step 2 — load the instrument from local pre-rendered MP3 samples
      const instName = this._instrumentName;
      console.log(`[FretWise] soundfont-player: loading ${instName}…`);
      this._synth = await window.Soundfont.instrument(
        this._audioCtx,
        instName,
        {
          soundfont: 'MusyngKite',
          format: 'mp3',
          nameToUrl: (name, sf, format) =>
            `/static/js/vendor/soundfonts/${sf}/${name}-${format}.js`,
          destination: this._masterGain || this._audioCtx.destination,
          gain: 4,
        }
      );

      // Audible confirmation note: A4 for 0.5 s
      this._synth.play(69, this._audioCtx.currentTime, { duration: 0.5, gain: 0.8 });

      console.log(`[FretWise] soundfont-player ready — ${instName}`);
      if (this.onSynthStatusChange) this.onSynthStatusChange('ready');
    } catch (err) {
      console.error('[FretWise] soundfont-player FAILED, oscillator fallback:', err);
      this._synth = null;
      if (this.onSynthStatusChange) this.onSynthStatusChange('error');
    } finally {
      this._synthLoading = false;
    }
  }

  /** Map dynamic marking to MIDI velocity (0-127). */
  _dynamicToVelocity(dynamic) {
    return { pp: 32, p: 48, mp: 64, mf: 80, f: 96, ff: 112 }[dynamic] ?? 80;
  }

  /** Schedule all notes in a measure to play at correct times.
   *  Dispatches to SpessaSynth (SF2) when loaded, oscillator otherwise.
   *  @param {number} measureIdx
   *  @param {number} [offsetSec=0] — extra delay (seconds) before first note
   */
  _scheduleMeasureNotes(measureIdx, offsetSec = 0) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const notes = this.renderer.measures[measureIdx];
    if (!notes || !notes.length) return;

    if (this._synth) {
      // soundfont-player: schedule notes via AudioContext time (precise, no setTimeout drift)
      const bpm = this.bpm;
      const measureOnset = Math.floor(notes[0].onset / bpm) * bpm;
      const secPerBeat = (60 / this.tempo) / this.speed;
      const now = this._audioCtx.currentTime;
      for (const note of notes) {
        const when = now + offsetSec + (note.onset - measureOnset) * secPerBeat;
        const duration = Math.max(0.08, note.duration * secPerBeat - 0.025);
        const gain = this._dynamicToVelocity(note.dynamic) / 127;
        this._synth.play(note.pitch, when, { duration, gain });
      }
    } else {
      console.log(`[FretWise] measure ${measureIdx}: oscillator fallback (synth=${this._synth}, loading=${this._synthLoading})`);
      this._scheduleMeasureNotesOscillator(measureIdx, offsetSec);
    }

    // Schedule secondary audio channels (same AudioContext time base = perfect sync)
    for (const ch of this._secondaryChannels) {
      if (!ch.enabled || !ch.synth) continue;
      const chNotes = ch.measures[measureIdx];
      if (!chNotes || !chNotes.length) continue;
      const chBpm = this.bpm;
      const chMeasureOnset = Math.floor(chNotes[0].onset / chBpm) * chBpm;
      const chSpb = (60 / this.tempo) / this.speed;
      const chNow = this._audioCtx.currentTime;
      for (const note of chNotes) {
        const when = chNow + offsetSec + (note.onset - chMeasureOnset) * chSpb;
        const duration = Math.max(0.08, note.duration * chSpb - 0.025);
        const gain = (this._dynamicToVelocity(note.dynamic) / 127) * ch.gain;
        ch.synth.play(note.pitch, when, { duration, gain });
      }
    }
  }

  /** Original oscillator-based note scheduler (fallback). */
  _scheduleMeasureNotesOscillator(measureIdx, offsetSec = 0) {
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

