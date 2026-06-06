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
    this._spessa = null;          // SpessaSynth Synthetizer (shared, all MIDI channels)
    this._synth = null;           // 'spessa' sentinel | soundfont-player Player | null (osc)
    this._synthLoading = false;   // loading guard to avoid double-init
    this._midiProgram = 25;       // GM program for primary track (25 = acoustic steel guitar)
    this._instrumentName = 'electric_guitar_clean'; // soundfont-player fallback instrument
    // Secondary audio channels: [{trackId, trackName, measures, synth, gain, enabled,
    //                             _loading, midiChannel, midiProgram}]
    this._secondaryChannels = [];

    this._followPlayhead = true;  // scroll follows the playhead
    // When the score is shown as server-rendered SVG (Staff / Mixed views),
    // the SvgCursorDriver owns scrolling of #core-svg-view. This engine's
    // canvas-geometry scroll (#tab-container) MUST then stay out of the way:
    // #core-svg-view is position:absolute;inset:0 inside #tab-container, so
    // scrolling the outer container shoves the (absolutely positioned) SVG box
    // up and out of frame, fighting the inner scroll. Set by main.js per
    // render; false ⇒ canvas (Tab) mode where this engine scrolls normally.
    this.usesSvgCursor = false;

    // Callbacks
    this.onMeasureChange = null;
    this.onStop = null;
    this.onPositionChange = null; // (measureFrac) → 0..1 fraction of song
    this.onSynthStatusChange = null; // ('loading'|'ready'|'error') → void
    this.onTimeChange = null;     // (seconds) → void, called on every tick

    // Audio resilience: browsers suspend/interrupt the AudioContext (tab
    // backgrounded, OS audio focus loss, autoplay policy). Without this the
    // sound silently "drops" and never comes back. We auto-resume on tab
    // refocus + any user gesture, and a watchdog re-resumes while audio is on.
    this._installAudioResilience();
  }

  /**
   * Install always-on guards that auto-resume the AudioContext whenever the
   * browser suspends it. Idempotent; safe to call once from the constructor.
   */
  _installAudioResilience() {
    if (typeof document === 'undefined' || this._resilienceInstalled) return;
    this._resilienceInstalled = true;
    const resume = () => { this.resumeAudioContext(); };
    document.addEventListener('visibilitychange', () => {
      if (!document.hidden) resume();
    });
    window.addEventListener('focus', resume);
    window.addEventListener('pointerdown', resume, true);
    window.addEventListener('keydown', resume, true);
    // Watchdog: while audio is enabled, keep the context running.
    this._resilienceTimer = setInterval(() => {
      if (this.audioEnabled || this.isPlaying) this.resumeAudioContext();
    }, 4000);
  }

  /**
   * Current playhead position in seconds from the start of the song (measure 0
   * beat 0 = t=0).  Exposed for external consumers that animate off the same
   * clock (e.g. the floating hand-visualization panel).
   */
  getCurrentTimeSec() {
    const spm = this.secondsPerMeasure;
    if (this.isPlaying && this._startTime != null) {
      const elapsed = (performance.now() - this._startTime) / 1000;
      return this._startMeasure * spm + elapsed;
    }
    const cursor = this.renderer ? (this.renderer.cursorMeasure || 0) : 0;
    return cursor * spm;
  }

  /**
   * Re-point this engine at a freshly built renderer (e.g. after a track or
   * representation-mode switch) WITHOUT tearing down the AudioContext or
   * reloading the soundfont. This is the fast path used by tab switching:
   * recreating a PlaybackEngine re-fetches and re-parses the (multi-MB) SF2
   * soundfont every time, which is the dominant tab-switch cost.
   *
   * Stops any in-flight audio, resets the per-song scheduling state and the
   * secondary channels (they are re-added by the caller for the new primary
   * track), but keeps the synth, AudioContext, master gain and volume intact.
   *
   * @param {import('./renderer.js').TabRenderer} renderer
   * @param {Object} opts
   * @param {number} [opts.tempo]
   * @param {number} [opts.beatsPerMeasure]
   */
  rebind(renderer, opts = {}) {
    // Stop anything currently sounding before swapping the score out.
    try { this.pause(); } catch (_) { /* not playing */ }
    if (this._spessa) {
      try { this._spessa.stopAll?.(); } catch (_) {}
    } else if (this._synth && this._synth !== 'spessa') {
      try { this._synth.stop(); } catch (_) {}
    }
    // Drop secondary channels of the previous primary track; the caller
    // re-adds the ones that apply to the new primary track.
    for (const ch of this._secondaryChannels) {
      if (ch.synth && ch.synth !== 'spessa') { try { ch.synth.stop(); } catch (_) {} }
    }
    this._secondaryChannels = [];

    this.renderer = renderer;
    this.tempo = opts.tempo || renderer.tempo || 120;
    this.bpm = opts.beatsPerMeasure || renderer.bpm || 4;
    this.speed = 1.0;
    this.loopStart = -1;
    this.loopEnd = -1;
    this._startMeasure = 0;
    this._lastScheduledMeasure = -1;
    this._resumeSubMeasureSec = 0;
    // Default to canvas scrolling; main.js re-asserts this per render once it
    // knows whether an SvgCursorDriver was created for the new view mode.
    this.usesSvgCursor = false;
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

  /**
   * Resume the AudioContext if the browser left it suspended (autoplay policy).
   * Browsers only permit resume() from within a user-gesture handler, so this
   * must be called from a click / keydown / touch listener. Safe to call when
   * there is no context yet (no-op) or when already running.
   *
   * @returns {Promise<void>}
   */
  async resumeAudioContext() {
    if (!this._audioCtx) return;
    // 'interrupted' is the iOS/Safari state after an audio-focus loss (call,
    // other app); 'suspended' is the standard autoplay/backgrounding state.
    if (this._audioCtx.state !== 'running') {
      try { await this._audioCtx.resume(); } catch (_) { /* ignore */ }
    }
  }

  disableAudio() {
    this.audioEnabled = false;
    if (this._spessa) {
      try { this._spessa.stopAll?.(); } catch (_) {}
    } else if (this._synth && this._synth !== 'spessa') {
      try { this._synth.stop(); } catch (_) {}
    }
    for (const ch of this._secondaryChannels) {
      if (ch.synth && ch.synth !== 'spessa') { try { ch.synth.stop(); } catch (_) {} }
      ch.synth = null;
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
   * @param {number} [midiProgram] — GM program number (0-127); inferred from name if absent
   */
  addSecondaryChannel(trackId, trackName, results, beatsPerMeasure, midiProgram) {
    this.removeSecondaryChannel(trackId); // remove if already present
    const bpm = beatsPerMeasure || this.bpm;
    const measures = PlaybackEngine._buildMeasures(results, bpm);
    // MIDI channels 1-15 for secondary tracks (0 is reserved for primary)
    const midiChannel = Math.min(15, this._secondaryChannels.length + 1);
    const resolvedProgram = (Number.isInteger(midiProgram) && midiProgram >= 0)
      ? midiProgram
      : PlaybackEngine._instrumentToMidiProgram(PlaybackEngine._inferInstrument(trackName));
    const ch = {
      trackId, trackName, measures, synth: null, gain: 0.8, enabled: true, _loading: false,
      midiChannel, midiProgram: resolvedProgram,
    };
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
      if (ch.synth && ch.synth !== 'spessa') { try { ch.synth.stop(); } catch (_) {} }
      this._secondaryChannels.splice(idx, 1);
    }
  }

  /**
   * Load instrument for a secondary channel.
   * With SpessaSynth: instant programChange on the shared synth.
   * Without: fall back to soundfont-player (async MP3 load).
   * @param {Object} ch — secondary channel object
   */
  async _loadChannelInstrument(ch) {
    if (ch._loading || ch.synth) return;

    if (this._spessa) {
      this._spessa.programChange(ch.midiChannel, ch.midiProgram);
      ch.synth = 'spessa';
      console.log(`[FretWise] secondary "${ch.trackName}" → GM ${ch.midiProgram} (ch ${ch.midiChannel})`);
      if (this.isPlaying && this._lastScheduledMeasure >= 0) {
        this._scheduleChannelNotes(ch, this._lastScheduledMeasure, 0);
      }
      return;
    }

    ch._loading = true;
    try {
      if (!window.Soundfont) {
        await new Promise((resolve, reject) => {
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
        this._audioCtx, instName, {
          soundfont: 'MusyngKite',
          format: 'mp3',
          nameToUrl: (name, sf, format) =>
            `/static/js/vendor/soundfonts/${sf}/${name}-${format}.js`,
          destination: this._masterGain || this._audioCtx.destination,
          gain: 4,
        }
      );
      console.log(`[FretWise] secondary "${ch.trackName}" ready (${instName})`);
      if (this.isPlaying && this._lastScheduledMeasure >= 0) {
        this._scheduleChannelNotes(ch, this._lastScheduledMeasure, 0);
      }
    } catch (err) {
      console.warn(`[FretWise] secondary "${ch.trackName}" load failed:`, err);
      ch.synth = null;
    } finally {
      ch._loading = false;
    }
  }

  /**
   * Infer the MusyngKite soundfont instrument name from a human-readable track name.
   * Used only for the soundfont-player fallback path.
   * @param {string} trackName
   * @returns {string} MusyngKite instrument key
   */
  static _inferInstrument(trackName) {
    const n = (trackName || '').toLowerCase();
    if (/dist|metal|crunch|heavy/i.test(n))       return 'distortion_guitar';
    if (/overdriv|driven/i.test(n))                return 'overdriven_guitar';
    if (/bass/i.test(n))                           return 'electric_bass_finger';
    if (/nylon|classical/i.test(n))                return 'acoustic_guitar_nylon';
    if (/acoustic|folk|steel/i.test(n))            return 'acoustic_guitar_steel';
    return 'electric_guitar_clean';
  }

  /**
   * Map a MusyngKite instrument name back to a GM program number.
   * Used when no explicit MIDI program is provided.
   * @param {string} instName
   * @returns {number} GM program (0-127)
   */
  static _instrumentToMidiProgram(instName) {
    return {
      acoustic_guitar_nylon:  24,
      acoustic_guitar_steel:  25,
      electric_guitar_clean:  27,
      overdriven_guitar:      29,
      distortion_guitar:      30,
      electric_bass_finger:   33,
    }[instName] ?? 27;
  }

  /**
   * Set the GM MIDI program for the primary track.
   * With SpessaSynth: applies instantly via programChange.
   * Without: infers the closest MusyngKite instrument and reloads if needed.
   * @param {number} program — GM program 0-127; -1 = unknown (keeps previous)
   */
  setMidiProgram(program) {
    if (!Number.isInteger(program) || program < 0 || program > 127) return;
    this._midiProgram = program;
    if (this._spessa) {
      this._spessa.programChange(0, program);
      return;
    }
    // Soundfont fallback: map GM program to nearest MusyngKite instrument
    const inst = program >= 32 && program <= 36 ? 'electric_bass_finger'
               : program === 24 ? 'acoustic_guitar_nylon'
               : program === 25 ? 'acoustic_guitar_steel'
               : program === 29 ? 'overdriven_guitar'
               : program === 30 ? 'distortion_guitar'
               : 'electric_guitar_clean';
    this.setInstrument(inst);
  }

  /**
   * Set instrument from track name (soundfont fallback path).
   * With SpessaSynth active, setMidiProgram() is preferred.
   * @param {string} trackName — human-readable name from the API
   */
  setInstrument(trackName) {
    const inst = PlaybackEngine._inferInstrument(trackName);
    if (this._spessa) {
      // SpessaSynth is active: instrument is set via setMidiProgram; nothing to reload
      this._instrumentName = inst;
      return;
    }
    if (inst === this._instrumentName && this._synth) return;
    this._instrumentName = inst;
    if (this._synth && this._synth !== 'spessa') {
      try { this._synth.stop(); } catch (_) {}
      this._synth = null;
    }
    this._synthLoading = false;
    if (this.audioEnabled) {
      this._initSynth().catch(() => {});
    }
  }

  /**
   * Override the instrument for a given MIDI channel index.
   * @param {number} channel - MIDI channel index (0-15); 0 = primary track
   * @param {number} program  - GM program number (0-127)
   */
  setChannelInstrument(channel, program) {
    if (!Number.isInteger(channel) || channel < 0 || channel > 15) return;
    if (!Number.isInteger(program) || program < 0 || program > 127) return;

    if (!this._instrumentOverrides) this._instrumentOverrides = {};
    this._instrumentOverrides[channel] = program;

    if (channel === 0) {
      // Primary track: delegate to setMidiProgram
      this.setMidiProgram(program);
      return;
    }

    // Secondary channels
    if (this._spessa) {
      try { this._spessa.programChange(channel, program); } catch (_) {}
    }
    // Update the stored midiProgram for the matching secondary channel
    const ch = this._secondaryChannels.find(c => c.midiChannel === channel);
    if (ch) {
      ch.midiProgram = program;
      if (this._synth && this._synth !== 'spessa' && ch.synth && ch.synth !== 'spessa') {
        try { ch.synth.setInstrument?.(channel, program); } catch (_) {}
      }
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
    // Resume at the sub-measure offset captured by the last pause() (if any),
    // so a pause+resume mid-measure picks up exactly where it stopped instead
    // of restarting the current measure from beat 0.
    const resumeOffsetSec = this._resumeSubMeasureSec || 0;
    this._startTime = performance.now() - resumeOffsetSec * 1000;
    this._resumeSubMeasureSec = 0;  // consumed
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

    // Schedule the first measure immediately (cursor hasn't moved yet).
    // skipBeforeMeasureSec drops the notes that have already played before
    // the pause point so they don't replay on resume.
    const m0 = this._startMeasure;
    this._lastScheduledMeasure = m0;
    if (this.metronome) this._scheduleMetronomeMeasure(m0);
    if (this.audioEnabled) {
      this._scheduleMeasureNotes(m0, 0, resumeOffsetSec);
    }

    this._tick();
  }

  /** Pause playback */
  pause() {
    // Snapshot the current time BEFORE flipping isPlaying so the getter
    // still returns the running elapsed-time, then freeze it.
    const frozen = this.getCurrentTimeSec();
    this.isPlaying = false;
    if (this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
    // Snap the cursor to the matching measure so getCurrentTimeSec()
    // returns `frozen` while paused (spm-granular is enough here), and
    // remember the sub-measure offset so play() can restore the exact
    // position instead of restarting the measure from its first beat.
    const spm = this.secondsPerMeasure;
    const m = Math.floor(frozen / spm);
    if (this.renderer) this.renderer.cursorMeasure = Math.max(0, Math.min(m, this.totalMeasures - 1));
    this._resumeSubMeasureSec = Math.max(0, frozen - m * spm);
    // Cut all already-scheduled audio immediately so notes don't ring
    // past the pause point and don't double when play resumes.
    if (this._spessa) {
      try { this._spessa.stopAll?.(); } catch (_) {}
    } else {
      if (this._synth && this._synth !== 'spessa') { try { this._synth.stop(); } catch (_) {} }
      for (const ch of this._secondaryChannels) {
        if (ch.synth && ch.synth !== 'spessa') { try { ch.synth.stop(); } catch (_) {} }
      }
    }
    if (this.onTimeChange) this.onTimeChange(this.getCurrentTimeSec());
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
    // An explicit seek to a measure boundary discards any sub-measure
    // pause offset captured just above by pause() — otherwise resuming
    // after a seek would start with a stale offset from the previous
    // measure.
    this._resumeSubMeasureSec = 0;
    this.renderer.cursorMeasure = Math.max(0, Math.min(m, this.totalMeasures - 1));
    this.renderer.render();
    if (this.onMeasureChange) this.onMeasureChange(this.renderer.cursorMeasure);
    if (this.onPositionChange) this.onPositionChange(this.renderer.cursorMeasure / Math.max(1, this.totalMeasures - 1));
    if (this.onTimeChange) this.onTimeChange(this.getCurrentTimeSec());
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

    // Fire per-tick time callback (sub-measure resolution) for external
    // consumers like the floating hand-visualization panel.
    if (this.onTimeChange) this.onTimeChange(this.getCurrentTimeSec());

    this._raf = requestAnimationFrame(() => this._tick());
  }

  _scrollCursorIntoView() {
    // SVG views (Staff / Mixed): the SvgCursorDriver scrolls #core-svg-view.
    // Scrolling #tab-container here too would drag the absolutely-positioned
    // SVG box out of frame, so do nothing and let the driver own it.
    if (this.usesSvgCursor) return;
    if (!this._followPlayhead) return;
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
    const sysMid = sysY + SYSTEM_H / 2;

    const rect = container.getBoundingClientRect();
    const visibleTop = container.scrollTop;
    const visibleBot = container.scrollTop + rect.height;
    const centerTarget = sysMid - rect.height / 2;

    // Only scroll when system center would be too close to top/bottom edges
    if (sysMid > visibleBot - SYSTEM_H * 0.6 || sysMid < visibleTop + SYSTEM_H * 0.6) {
      container.scrollTo({ top: Math.max(0, centerTarget), behavior: 'smooth' });
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
   * Initialise the audio synthesizer.
   * Primary path: SpessaSynth + Shan SGM-Pro SF2 (full GM, realistic samples).
   * Fallback: soundfont-player + MusyngKite MP3 samples (6 guitar presets).
   * If both fail: oscillator synthesis (this._synth stays null).
   */
  async _initSynth() {
    if (this._spessa || this._synth || this._synthLoading) return;
    this._synthLoading = true;
    if (this.onSynthStatusChange) this.onSynthStatusChange('loading');
    try {
      // ── Primary path: SpessaSynth + SF2 ───────────────────────────────────
      const { Synthetizer } = await import('/static/js/vendor/spessasynth.esm.js');
      await this._audioCtx.audioWorklet.addModule(
        '/static/js/vendor/synthetizer/worklet_processor.min.js'
      );

      console.log('[FretWise] SpessaSynth: fetching SF2 soundfont…');
      const resp = await fetch('/api/soundfont');
      if (!resp.ok) throw new Error(`SF2 fetch: HTTP ${resp.status}`);
      const sf2Buffer = await resp.arrayBuffer();

      const dest = this._masterGain || this._audioCtx.destination;
      const spessa = new Synthetizer(dest, sf2Buffer);

      // Set GM program for primary and any already-registered secondary channels
      spessa.programChange(0, this._midiProgram);
      for (const ch of this._secondaryChannels) {
        spessa.programChange(ch.midiChannel, ch.midiProgram);
        ch.synth = 'spessa';
      }

      this._spessa = spessa;
      this._synth = 'spessa';
      console.log(`[FretWise] SpessaSynth ready — GM program ${this._midiProgram}`);
      if (this.onSynthStatusChange) this.onSynthStatusChange('ready');
    } catch (err) {
      console.warn('[FretWise] SpessaSynth unavailable, falling back to MusyngKite:', err.message);
      await this._initSynthFallback();
    } finally {
      this._synthLoading = false;
    }
  }

  /**
   * Fallback synthesizer: soundfont-player + MusyngKite pre-rendered MP3 samples.
   * Only 6 guitar/bass presets available.  Used when SpessaSynth fails to load.
   */
  async _initSynthFallback() {
    try {
      if (!window.Soundfont) {
        await new Promise((resolve, reject) => {
          const s = document.createElement('script');
          s.src = '/static/js/vendor/soundfont-player.min.js';
          s.onload = resolve;
          s.onerror = () => reject(new Error('soundfont-player script failed to load'));
          document.head.appendChild(s);
        });
      }
      if (!window.Soundfont) throw new Error('window.Soundfont not defined');

      const instName = this._instrumentName;
      console.log(`[FretWise] soundfont-player: loading ${instName}…`);
      this._synth = await window.Soundfont.instrument(
        this._audioCtx, instName, {
          soundfont: 'MusyngKite',
          format: 'mp3',
          nameToUrl: (name, sf, format) =>
            `/static/js/vendor/soundfonts/${sf}/${name}-${format}.js`,
          destination: this._masterGain || this._audioCtx.destination,
          gain: 4,
        }
      );
      this._synth.play(69, this._audioCtx.currentTime, { duration: 0.5, gain: 0.8 });
      console.log(`[FretWise] soundfont-player ready — ${instName}`);
      if (this.onSynthStatusChange) this.onSynthStatusChange('ready');
    } catch (err) {
      console.error('[FretWise] soundfont-player FAILED, oscillator fallback:', err);
      this._synth = null;
      if (this.onSynthStatusChange) this.onSynthStatusChange('error');
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
  _scheduleMeasureNotes(measureIdx, offsetSec = 0, skipBeforeMeasureSec = 0) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const notes = this.renderer.measures[measureIdx];
    if (!notes || !notes.length) return;

    if (this._spessa) {
      // SpessaSynth: precise AudioContext-time scheduling via noteOn/noteOff
      const bpm = this.bpm;
      const measureOnset = Math.floor(notes[0].onset / bpm) * bpm;
      const secPerBeat = (60 / this.tempo) / this.speed;
      const now = this._audioCtx.currentTime;
      for (const note of notes) {
        const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
        if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
        const when = now + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
        const duration = Math.max(0.08, note.duration * secPerBeat - 0.025);
        const velocity = this._dynamicToVelocity(note.dynamic);
        this._spessa.noteOn(0, note.pitch, velocity, false, when);
        this._spessa.noteOff(0, note.pitch, when + duration);
      }
    } else if (this._synth) {
      // soundfont-player fallback
      const bpm = this.bpm;
      const measureOnset = Math.floor(notes[0].onset / bpm) * bpm;
      const secPerBeat = (60 / this.tempo) / this.speed;
      const now = this._audioCtx.currentTime;
      for (const note of notes) {
        const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
        if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
        const when = now + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
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
      this._scheduleChannelNotes(ch, measureIdx, offsetSec, skipBeforeMeasureSec);
    }
  }

  /** Schedule notes for a single secondary channel at a given measure.
   * @param {Object} ch - secondary channel object
   * @param {number} measureIdx
   * @param {number} [offsetSec=0]
   */
  _scheduleChannelNotes(ch, measureIdx, offsetSec = 0, skipBeforeMeasureSec = 0) {
    if (!ch.synth || !ch.enabled || !this._audioCtx || !this.audioEnabled) return;
    const chNotes = ch.measures[measureIdx];
    if (!chNotes || !chNotes.length) return;
    const chMeasureOnset = Math.floor(chNotes[0].onset / this.bpm) * this.bpm;
    const chSpb = (60 / this.tempo) / this.speed;
    const chNow = this._audioCtx.currentTime;

    if (this._spessa) {
      for (const note of chNotes) {
        const noteOffsetInMeasure = (note.onset - chMeasureOnset) * chSpb;
        if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
        const when = chNow + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
        const duration = Math.max(0.08, note.duration * chSpb - 0.025);
        const velocity = Math.min(127, Math.round(this._dynamicToVelocity(note.dynamic) * ch.gain));
        this._spessa.noteOn(ch.midiChannel, note.pitch, velocity, false, when);
        this._spessa.noteOff(ch.midiChannel, note.pitch, when + duration);
      }
      return;
    }

    for (const note of chNotes) {
      const noteOffsetInMeasure = (note.onset - chMeasureOnset) * chSpb;
      if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
      const when = chNow + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
      const duration = Math.max(0.08, note.duration * chSpb - 0.025);
      const gain = (this._dynamicToVelocity(note.dynamic) / 127) * ch.gain;
      ch.synth.play(note.pitch, when, { duration, gain });
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

