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
    // Per-measure length in quarter beats (index i = measure i+1), shipped by the
    // backend from the real per-measure time signatures. null ⇒ uniform `bpm`
    // fallback (MusicXML/MIDI). Drives a meter-aware timeline so the cursor, the
    // audio and every track stay aligned across meter changes / pickup bars.
    this._measureBeats = Array.isArray(opts.measureBeats) ? opts.measureBeats : null;
    this._slotStartBeat = null;  // lazily (re)built slot timeline; see _ensureTimeline()
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
    this._primaryVolume = 0.8; // current/open-track volume (CC7 on ch 0); balances
                               // it against the 0.8 backing tracks instead of dominating
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
    this.onSynthProgress = null;     // (frac|null, loadedMB, totalMB) → void, during SF download
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
    if (this.isPlaying && this._startTime != null) {
      const elapsed = (performance.now() - this._startTime) / 1000;
      return this._measureStartSec(this._startMeasure) + elapsed;
    }
    const cursor = this.renderer ? (this.renderer.cursorMeasure || 0) : 0;
    return this._measureStartSec(cursor);
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
    this._measureBeats = Array.isArray(opts.measureBeats) ? opts.measureBeats : null;
    this._slotStartBeat = null;  // force timeline rebuild for the new score
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

  /** Seconds per measure for a uniform 4/4-style score (legacy approximation).
   *  Per-measure timing now flows through the meter-aware timeline below; this
   *  getter is kept for external/rough consumers and equals the first-measure
   *  duration when meters vary. */
  get secondsPerMeasure() {
    return (this.bpm / this.tempo) * 60 / this.speed;
  }

  /** Seconds per quarter-note beat at the current tempo + speed. */
  get _secPerBeat() {
    return (60 / this.tempo) / this.speed;
  }

  /**
   * (Re)build the meter-aware timeline. `_slotStartBeat[s]` is the onset, in
   * quarter beats relative to the first rendered measure, where cursor slot `s`
   * begins; `_measureBaseBeat` is the absolute onset (in note-onset units) of
   * that first measure. Per-measure lengths come from `_measureBeats` (the real
   * time signatures); any measure without data falls back to uniform `this.bpm`,
   * so a null `_measureBeats` reproduces the legacy uniform behaviour exactly.
   * Cached and rebuilt only when the score, measure count or bpm changes.
   */
  _ensureTimeline() {
    const n = this.totalMeasures;
    const beats = this._measureBeats;
    if (this._slotStartBeat
        && this._slotStartBeat.length === n + 1
        && this._timelineBeatsRef === beats
        && this._timelineRendererRef === this.renderer
        && this._timelineBpm === this.bpm) {
      return;
    }
    const nums = this.renderer ? this.renderer.measureNumbers : null;
    const minMeasure = (nums && nums.length) ? nums[0] : 1;
    const beatsFor = (globalIdx0) =>
      (beats && beats[globalIdx0] > 0) ? beats[globalIdx0] : this.bpm;
    // Absolute onset of the first rendered measure = beats of all measures before it.
    let base = 0;
    for (let i = 0; i < minMeasure - 1; i++) base += beatsFor(i);
    const start = new Array(n + 1);
    start[0] = 0;
    for (let s = 0; s < n; s++) {
      const globalIdx0 = ((nums && nums[s] != null) ? nums[s] : (minMeasure + s)) - 1;
      start[s + 1] = start[s] + beatsFor(globalIdx0);
    }
    this._slotStartBeat = start;
    this._measureBaseBeat = base;
    this._timelineBeatsRef = beats;
    this._timelineRendererRef = this.renderer;
    this._timelineBpm = this.bpm;
  }

  /** Onset (quarter beats relative to the first measure) at the start of slot `m`. */
  _slotStartBeatAt(m) {
    this._ensureTimeline();
    const i = Math.max(0, Math.min(m, this.totalMeasures));
    return this._slotStartBeat[i];
  }

  /** Wall-clock seconds (from the first measure) at the start of cursor slot `m`. */
  _measureStartSec(m) {
    return this._slotStartBeatAt(m) * this._secPerBeat;
  }

  /** Absolute measure-start onset (note-onset units) for cursor slot `m`.
   *  This is the shared reference EVERY track uses to place notes within the
   *  measure, which is what keeps the tracks in sync with each other. */
  _measureOnsetBeats(m) {
    this._ensureTimeline();
    return this._measureBaseBeat + this._slotStartBeatAt(m);
  }

  /** Cursor slot containing wall-clock second `sec` (0…totalMeasures; the upper
   *  bound signals past-the-end so the play loop can stop). */
  _secToMeasure(sec) {
    this._ensureTimeline();
    const beat = Math.max(0, sec / this._secPerBeat);
    const starts = this._slotStartBeat;
    let lo = 0, hi = starts.length - 1;          // largest m with starts[m] <= beat
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= beat) lo = mid; else hi = mid - 1;
    }
    return lo;
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
    // Prefer the parser's 1-based measure_index — the SAME grouping the primary
    // renderer uses (_groupMeasures) — so secondary tracks stay measure-aligned
    // with the primary even under pickup bars / variable meter. Index m maps to
    // slot (m-1), matching a primary that starts at measure 1. Fall back to
    // onset/bpm bucketing only when measure_index is absent.
    if (results.some((n) => n.measure_index != null)) {
      const byM = new Map();
      let maxM = 1;
      for (const n of results) {
        const mi = n.measure_index ?? 1;
        if (!byM.has(mi)) byM.set(mi, []);
        byM.get(mi).push(n);
        if (mi > maxM) maxM = mi;
      }
      const measures = [];
      for (let m = 1; m <= maxM; m++) measures.push(byM.get(m) ?? []);
      return measures;
    }
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
      this._spessa.programChange(ch.midiChannel, this._resolveProgram(ch.midiProgram));
      ch.synth = 'spessa';
      console.log(`[FretWise] secondary "${ch.trackName}" → GM ${ch.midiProgram} (ch ${ch.midiChannel})`);
      if (this.isPlaying && this._lastScheduledMeasure >= 0) {
        this._scheduleChannelNotes(ch, this._lastScheduledMeasure, 0);
      }
      return;
    }

    // Defer to SpessaSynth: until the shared synth has resolved (loading, or not
    // started yet), do NOT spin up a heavy per-channel MusyngKite MP3 fallback
    // (multi-MB main-thread decode × N tracks = the UI freeze that stalls the
    // playhead on multi-track songs). _initSynth() binds every secondary channel
    // to the shared synth on success; only a definitive SpessaSynth failure
    // (this._spessaFailed) drops us to the MusyngKite path below.
    if (!this._spessaFailed) return;

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
      this._spessa.programChange(0, this._resolveProgram(program));
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
   * Map a desired GM program onto a program the loaded SpessaSynth soundfont
   * actually contains. GM soundfonts return `desired` unchanged; non-GM banks
   * (single-instrument packs, game/arcade soundfonts) that lack it would
   * otherwise make SpessaSynth fall back to preset 0 (frequently DRUMS), so
   * guitar tabs sound like percussion. Preference: exact program → a
   * guitar-named preset → the first available preset.
   * @param {number} desired GM program (0-127)
   * @returns {number} a program present in the soundfont (or `desired` if unknown)
   */
  _resolveProgram(desired) {
    const presets = this._spessaPresets;
    if (!presets || !presets.length) return desired;  // not loaded yet: trust caller
    const bank0 = presets.filter((p) => (p.bank ?? 0) === 0);
    const pool = bank0.length ? bank0 : presets;
    if (pool.some((p) => p.program === desired)) return desired;
    const guitar = pool.find((p) => /guitar|gtr/i.test(p.presetName || p.name || ''));
    if (guitar) return guitar.program;
    return pool[0].program;
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

  /**
   * Set a MIDI channel's volume via CC7 (Main Volume), 0..1. Applies live, incl.
   * to sustaining notes. Channel 0 is the primary (currently-open) track — the UI
   * exposes this next to the master volume so the open track can be balanced
   * against the backing tracks instead of always dominating.
   * @param {number} channel MIDI channel (0 = primary)
   * @param {number} vol 0..1
   */
  setChannelVolume(channel, vol) {
    const v = Math.max(0, Math.min(1, vol));
    if (channel === 0) this._primaryVolume = v;
    if (this._spessa) {
      try { this._spessa.controllerChange(channel, 7, Math.round(v * 127)); } catch (_) { /* pre-init */ }
    }
  }

  /** Volume of the primary (open) track, 0..1. */
  get primaryVolume() { return this._primaryVolume; }

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
    // returns `frozen` while paused, and remember the sub-measure offset so
    // play() can restore the exact position instead of restarting the measure
    // from its first beat. Uses the meter-aware timeline so a short/long bar
    // resolves to the right measure.
    const m = Math.min(this._secToMeasure(frozen), Math.max(0, this.totalMeasures - 1));
    if (this.renderer) this.renderer.cursorMeasure = Math.max(0, m);
    this._resumeSubMeasureSec = Math.max(0, frozen - this._measureStartSec(m));
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

    // A render, callback (cursor overlay, hand-viz, scroll) or audio-scheduling
    // error must NEVER kill the animation loop and freeze the playhead. Run the
    // body guarded, log anything that throws, and always reschedule while
    // playing so the cursor keeps advancing regardless of audio health.
    try {
      this._tickBody();
    } catch (err) {
      console.warn('[FretWise] playback tick error (continuing):', err);
    }
    if (this.isPlaying) this._raf = requestAnimationFrame(() => this._tick());
  }

  _tickBody() {
    const elapsed = (performance.now() - this._startTime) / 1000;
    // Map elapsed wall-clock time to a measure via the meter-aware timeline:
    // each measure consumes its own real duration, so the cursor no longer
    // drifts from the audio after a meter change or pickup bar.
    let targetMeasure = this._secToMeasure(this._measureStartSec(this._startMeasure) + elapsed);

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

  /** Schedule one metronome click per beat for the given measure, using that
   *  measure's real beat count (so a 2/4 or 6/8 bar clicks the right number). */
  _scheduleMetronomeMeasure(measureIdx) {
    if (!this._audioCtx) return;
    this._ensureTimeline();
    const slotBeats = this._slotStartBeat[measureIdx + 1] - this._slotStartBeat[measureIdx];
    const clicks = Math.max(1, Math.round(slotBeats > 0 ? slotBeats : this.bpm));
    const secPerBeat = this._secPerBeat;
    const now = this._audioCtx.currentTime;
    for (let b = 0; b < clicks; b++) {
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
      const sf2Buffer = await this._fetchWithProgress(resp);

      const dest = this._masterGain || this._audioCtx.destination;
      const spessa = new Synthetizer(dest, sf2Buffer);

      // Wait for the worklet to finish parsing the soundfont, then snapshot its
      // preset list. We need it to map GM programs onto presets the soundfont
      // actually provides: a non-GM bank (a single-instrument guitar pack, a
      // game/arcade soundfont, …) usually lacks GM program 25, and SpessaSynth
      // then silently falls back to preset 0 — which is often DRUMS, so guitar
      // tabs play as percussion. _resolveProgram() avoids that.
      // Wait for the worklet to ACTUALLY finish parsing before marking ready.
      // Big banks (StrixGuitarPack 186 MB, East_West 426 MB) take many seconds —
      // a fixed 4 s cap would mark the synth "ready" mid-parse, so notes would hit
      // a half-built synth (silence) and presetList would still be empty. Resolve
      // as soon as isReady fires; scale the *safety* cap with file size so a huge
      // bank gets the time it needs (~0.5 ms/KB ⇒ ~95 s for 186 MB), capped at 3 min.
      const readyCapMs = Math.min(180000, Math.max(8000, (sf2Buffer.byteLength / 1024) * 0.5));
      try {
        await Promise.race([
          spessa.isReady,
          new Promise((r) => setTimeout(r, readyCapMs)),
        ]);
      } catch (_) { /* isReady rejected — proceed with whatever presets exist */ }
      this._spessaPresets = Array.isArray(spessa.presetList) ? spessa.presetList.slice() : [];

      this._spessa = spessa;
      this._synth = 'spessa';

      // Set the (resolved) GM program for primary and any registered secondary channels
      const primaryProg = this._resolveProgram(this._midiProgram);
      spessa.programChange(0, primaryProg);
      // Balance the open track against the backing tracks (CC7 on channel 0).
      try { spessa.controllerChange(0, 7, Math.round(this._primaryVolume * 127)); } catch (_) { /* */ }
      for (const ch of this._secondaryChannels) {
        spessa.programChange(ch.midiChannel, this._resolveProgram(ch.midiProgram));
        ch.synth = 'spessa';
        // Catch up any missed notes in the current measure (SpessaSynth finished
        // loading while the song was already playing, so secondary channels were
        // silent for the first few bars).
        if (this.isPlaying && this._lastScheduledMeasure >= 0) {
          this._scheduleChannelNotes(ch, this._lastScheduledMeasure, 0);
        }
      }

      console.log(`[FretWise] SpessaSynth ready — ${this._spessaPresets.length} presets; `
        + `GM ${this._midiProgram}`
        + (primaryProg !== this._midiProgram ? ` → ${primaryProg} (mapped; ${this._midiProgram} absent)` : ''));
      if (this.onSynthStatusChange) this.onSynthStatusChange('ready');
    } catch (err) {
      console.warn('[FretWise] SpessaSynth unavailable, falling back to MusyngKite:', err.message);
      await this._initSynthFallback();
    } finally {
      this._synthLoading = false;
      // Secondary channels deferred their load while SpessaSynth was resolving
      // (see _loadChannelInstrument). If SpessaSynth ultimately failed, open the
      // MusyngKite fallback gate and bind them now; on success _initSynth has
      // already bound them to the shared synth above.
      if (!this._spessa) {
        this._spessaFailed = true;
        for (const ch of this._secondaryChannels) {
          if (!ch.synth) this._loadChannelInstrument(ch).catch(() => {});
        }
      }
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

  /**
   * Read a fetch Response to an ArrayBuffer while reporting download progress via
   * onSynthProgress(frac, loadedMB, totalMB). Falls back to a plain read (with an
   * indeterminate progress signal) when the body isn't streamable or the size is
   * unknown. Used so the soundfont download shows a real progress bar.
   * @param {Response} resp
   * @returns {Promise<ArrayBuffer>}
   */
  async _fetchWithProgress(resp) {
    const total = Number(resp.headers.get('Content-Length')) || 0;
    if (!resp.body || !total) {
      this.onSynthProgress?.(null);
      return resp.arrayBuffer();
    }
    const MB = 1048576;
    const reader = resp.body.getReader();
    const chunks = [];
    let loaded = 0;
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      chunks.push(value);
      loaded += value.length;
      this.onSynthProgress?.(loaded / total, (loaded / MB).toFixed(1), (total / MB).toFixed(1));
    }
    const out = new Uint8Array(loaded);
    let off = 0;
    for (const c of chunks) { out.set(c, off); off += c.length; }
    return out.buffer;
  }

  /** Schedule all notes in a measure to play at correct times.
   *  Dispatches to SpessaSynth (SF2) when loaded, oscillator otherwise.
   *  @param {number} measureIdx
   *  @param {number} [offsetSec=0] — extra delay (seconds) before first note
   */
  _scheduleMeasureNotes(measureIdx, offsetSec = 0, skipBeforeMeasureSec = 0) {
    // Audio dispatch must never throw into play()/_tick() and freeze the
    // playhead. Swallow + log here; the warning names the real failure (e.g.
    // a synth/worklet API mismatch) so it can be fixed without losing the cursor.
    try {
      this._scheduleMeasureNotesImpl(measureIdx, offsetSec, skipBeforeMeasureSec);
    } catch (err) {
      console.warn('[FretWise] note scheduling failed (playhead continues):', err);
    }
  }

  _scheduleMeasureNotesImpl(measureIdx, offsetSec = 0, skipBeforeMeasureSec = 0) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const notes = this.renderer.measures[measureIdx];

    // Primary track scheduling (skipped for rest bars, but secondary always runs below).
    if (notes && notes.length) {
      if (this._spessa) {
        // SpessaSynth: precise AudioContext-time scheduling via noteOn/noteOff
        const measureOnset = this._measureOnsetBeats(measureIdx);
        const secPerBeat = this._secPerBeat;
        const now = this._audioCtx.currentTime;
        for (const note of notes) {
          const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
          if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
          const when = now + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
          const duration = Math.max(0.08, note.duration * secPerBeat - 0.025);
          const velocity = this._dynamicToVelocity(note.dynamic);
          // v3 SpessaSynth API: 4th arg is an options object ({ time }), NOT a
          // (debug, startTime) pair. Passing a boolean makes the lib do
          // `'time' in false` and throw on every note → total silence.
          this._spessa.noteOn(0, note.pitch, velocity, { time: when });
          this._spessa.noteOff(0, note.pitch, false, { time: when + duration });
        }
      } else if (this._synth) {
        // soundfont-player fallback
        const measureOnset = this._measureOnsetBeats(measureIdx);
        const secPerBeat = this._secPerBeat;
        const now = this._audioCtx.currentTime;
        for (const note of notes) {
          const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
          if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
          const when = now + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
          const duration = Math.max(0.08, note.duration * secPerBeat - 0.025);
          const gain = this._dynamicToVelocity(note.dynamic) / 127;
          this._synth.play(note.pitch, when, { duration, gain });
        }
      } else if (this._synthLoading) {
        // SpessaSynth (SF2) is still loading: stay silent for this measure instead
        // of playing the harsh oscillator. The real instrument takes over within a
        // few seconds — and only on the first page-load, since later songs reuse
        // the already-loaded synth. Brief silence beats a few bars of bad tone.
      } else {
        // Synth definitively unavailable (SpessaSynth + MusyngKite both failed):
        // last-resort oscillator so playback is never completely silent.
        this._scheduleMeasureNotesOscillator(measureIdx, offsetSec);
      }
    }

    // Schedule secondary audio channels (same AudioContext time base = perfect sync).
    // Runs even when the primary measure is empty so backing tracks play through rest bars.
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
    // ch.measures is indexed by (1-based measure_index − 1), built from all
    // measures starting at 1.  The primary renderer's slot `measureIdx` maps to
    // global measure number `measureNumbers[measureIdx]` (which can be > 1 when
    // the primary track starts with rest bars).  Without this lookup, secondary
    // notes for measures 1..minM-1 are compared against a chMeasureOnset that is
    // already minM beats ahead, making every noteOffsetInMeasure negative and
    // silencing the entire secondary channel.
    const globalMeasureNum = (this.renderer?.measureNumbers?.[measureIdx] ?? (measureIdx + 1));
    const chNotes = ch.measures[globalMeasureNum - 1];
    if (!chNotes || !chNotes.length) return;
    // Same shared measure-onset reference the primary track uses — keeps secondary
    // tracks locked to the primary even when meters change.
    const chMeasureOnset = this._measureOnsetBeats(measureIdx);
    const chSpb = this._secPerBeat;
    const chNow = this._audioCtx.currentTime;

    if (this._spessa) {
      for (const note of chNotes) {
        const noteOffsetInMeasure = (note.onset - chMeasureOnset) * chSpb;
        if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
        const when = chNow + offsetSec + (noteOffsetInMeasure - skipBeforeMeasureSec);
        const duration = Math.max(0.08, note.duration * chSpb - 0.025);
        const velocity = Math.min(127, Math.round(this._dynamicToVelocity(note.dynamic) * ch.gain));
        this._spessa.noteOn(ch.midiChannel, note.pitch, velocity, { time: when });
        this._spessa.noteOff(ch.midiChannel, note.pitch, false, { time: when + duration });
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

    const measureOnset = this._measureOnsetBeats(measureIdx);
    const secPerBeat = this._secPerBeat;
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

