/**
 * playback.js — Playback engine with tempo-accurate cursor, audio synthesis,
 * metronome, A/B loop selection, and beat-level scheduling.
 */

// Single-entry in-memory cache of the last fetched SF2/SF3 ArrayBuffer, keyed by
// its (versioned, immutable) URL. Lets a re-created engine — or a genuine bank
// switch back to a previously loaded bank — skip the multi-hundred-MB download.
// Bounded to ONE bank so we never retain 2× a 400 MB buffer; switching banks
// drops the previous one. Module-level so it survives engine re-creation.
const _SF2_BUFFER_CACHE = new Map();

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
    // Per-measure tempo in BPM (index i = measure i+1), from the real per-note
    // tempo shipped by the backend. null ⇒ single-tempo fallback (this.tempo
    // everywhere), which reproduces the legacy behaviour exactly. Drives a
    // tempo-aware timeline so a mid-song tempo change (ritardando, faster chorus)
    // no longer desyncs the cursor and the audio from the music.
    this._measureTempos = Array.isArray(opts.measureTempos) ? opts.measureTempos : null;
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
    // ── Lookahead scheduler (see _pumpScheduler) ──────────────────────
    // Notes are queued on the AudioContext clock up to _lookaheadSec ahead of
    // "now", from a per-play anchor mapping song-position → AudioContext time —
    // instead of being scheduled at t=now the instant the cursor crosses a bar
    // (which the browser then plays late, and which coupled audio timing to the
    // render frame). _schedLeadSec is the startup head-start given to the first
    // downbeat so it is placed slightly in the future.
    this._schedLeadSec = 0.12;
    this._lookaheadSec = 0.25;
    this._audioAnchorTime = 0;      // AudioContext time mapped to _audioAnchorSongSec
    this._audioAnchorSongSec = 0;   // song position (speed-1 seconds) at the anchor
    this._schedulerMeasure = 0;     // next measure the pump will schedule
    this._skipMeasure = -1;         // measure the sub-measure resume-skip applies to
    this._firstScheduleSkipSec = 0; // seconds to skip inside _skipMeasure (resume/seek)
    this._spessa = null;          // SpessaSynth Synthetizer (shared, all MIDI channels)
    this._synth = null;           // 'spessa' sentinel | soundfont-player Player | null (osc)
    this._synthLoading = false;   // loading guard to avoid double-init
    this._midiProgram = 25;       // GM program for primary track (25 = acoustic steel guitar)
    this._instrumentName = 'electric_guitar_clean'; // soundfont-player fallback instrument
    this._pitchBendRangeSemitones = 12; // wide enough for guitar slides, bends and vibrato
    this._pitchBendRangeChannels = new Set();
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
    this.onSoundfontWarning = null;  // (message, {presetCount, url}) → void, when the active bank is not General MIDI
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
    this._measureTempos = Array.isArray(opts.measureTempos) ? opts.measureTempos : null;
    this._slotStartBeat = null;  // force timeline rebuild for the new score
    this.speed = 1.0;
    this.loopStart = -1;
    this.loopEnd = -1;
    this._startMeasure = 0;
    this._lastScheduledMeasure = -1;
    this._schedulerMeasure = 0;
    this._skipMeasure = -1;
    this._firstScheduleSkipSec = 0;
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
    const tempos = this._measureTempos;
    if (this._slotStartBeat
        && this._slotStartBeat.length === n + 1
        && this._timelineBeatsRef === beats
        && this._timelineTemposRef === tempos
        && this._timelineRendererRef === this.renderer
        && this._timelineBpm === this.bpm
        && this._timelineTempo === this.tempo) {
      return;
    }
    const nums = this.renderer ? this.renderer.measureNumbers : null;
    const minMeasure = (nums && nums.length) ? nums[0] : 1;
    const beatsFor = (globalIdx0) =>
      (beats && beats[globalIdx0] > 0) ? beats[globalIdx0] : this.bpm;
    const tempoFor = (globalIdx0) =>
      (tempos && tempos[globalIdx0] > 0) ? tempos[globalIdx0] : this.tempo;
    // Absolute onset of the first rendered measure = beats of all measures before it.
    let base = 0;
    for (let i = 0; i < minMeasure - 1; i++) base += beatsFor(i);
    const start = new Array(n + 1);     // cumulative quarter-beats at slot start
    const startSec = new Array(n + 1);  // cumulative seconds at slot start (speed 1)
    const secPerBeat = new Array(n);    // per-slot seconds/quarter-beat (speed 1)
    start[0] = 0;
    startSec[0] = 0;
    for (let s = 0; s < n; s++) {
      const globalIdx0 = ((nums && nums[s] != null) ? nums[s] : (minMeasure + s)) - 1;
      const slotBeats = beatsFor(globalIdx0);
      const spb = 60 / tempoFor(globalIdx0);   // seconds per quarter-beat, speed 1
      start[s + 1] = start[s] + slotBeats;
      startSec[s + 1] = startSec[s] + slotBeats * spb;
      secPerBeat[s] = spb;
    }
    this._slotStartBeat = start;
    this._slotStartSecBase = startSec;
    this._slotSecPerBeatBase = secPerBeat;
    this._measureBaseBeat = base;
    this._timelineBeatsRef = beats;
    this._timelineTemposRef = tempos;
    this._timelineRendererRef = this.renderer;
    this._timelineBpm = this.bpm;
    this._timelineTempo = this.tempo;
  }

  /** Onset (quarter beats relative to the first measure) at the start of slot `m`. */
  _slotStartBeatAt(m) {
    this._ensureTimeline();
    const i = Math.max(0, Math.min(m, this.totalMeasures));
    return this._slotStartBeat[i];
  }

  /** Wall-clock seconds (from the first measure) at the start of cursor slot `m`.
   *  Tempo-aware: sums each preceding measure's own duration, so a mid-song
   *  tempo change places every later measure at its true time. Speed is applied
   *  at read time (uniform multiplier) so changing speed needs no rebuild. */
  _measureStartSec(m) {
    this._ensureTimeline();
    const i = Math.max(0, Math.min(m, this.totalMeasures));
    return this._slotStartSecBase[i] / this.speed;
  }

  /** Seconds per quarter-beat inside cursor slot `m` (tempo of that measure). */
  _measureSecPerBeat(m) {
    this._ensureTimeline();
    const i = Math.max(0, Math.min(m, this.totalMeasures - 1));
    const spb = this._slotSecPerBeatBase[i];
    return (spb > 0 ? spb : (60 / this.tempo)) / this.speed;
  }

  /** AudioContext time at which song position `songSec` (speed-scaled seconds
   *  from the first measure) should sound, per the current play anchor. */
  _songSecToAudioTime(songSec) {
    return this._audioAnchorTime + (songSec - this._audioAnchorSongSec);
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
    const target = Math.max(0, sec * this.speed);   // seconds at speed 1
    const starts = this._slotStartSecBase;
    let lo = 0, hi = starts.length - 1;          // largest m with starts[m] <= target
    while (lo < hi) {
      const mid = (lo + hi + 1) >> 1;
      if (starts[mid] <= target) lo = mid; else hi = mid - 1;
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
   * Pick the lowest free MIDI channel for a secondary track.
   * Channel 0 is the primary track and channel 9 is the GM percussion channel
   * (a melodic part placed there plays as drums) — both are skipped. Reuses
   * channels freed by removed tracks; overflows past 14 melodic channels share
   * channel 15 rather than colliding with primary/percussion.
   * @returns {number} MIDI channel index (1-8, 10-15)
   */
  _allocateMidiChannel() {
    const used = new Set(this._secondaryChannels.map((c) => c.midiChannel));
    for (let ch = 1; ch <= 15; ch += 1) {
      if (ch === 9) continue;        // GM percussion channel — never melodic
      if (!used.has(ch)) return ch;
    }
    return 15;                        // >14 backing tracks: share the last channel
  }

  /**
   * Heuristic: is this a drum/percussion track? Such tracks must play on GM
   * channel 9 (the drum kit) — a melodic program (the GP file often stores 0 for
   * them, i.e. Acoustic Grand Piano) makes the kit sound like a piano.
   * @param {string} name
   * @returns {boolean}
   */
  static _isPercussionTrack(name) {
    return /\b(drums?|percussion|batterie|claps?|cymbals?|snare|kick|hi-?hat|toms?)\b/i.test(name || '');
  }

  /**
   * Add a secondary audio channel for a track (plays alongside the primary).
   * @param {number} trackId
   * @param {string} trackName
   * @param {Array}  results — note objects from /api/notes
   * @param {number} beatsPerMeasure
   * @param {number} [midiProgram] — GM program number (0-127); inferred from name if absent
   * @param {string} [kind] — backend track kind ("guitar"|"bass"|"drums"|…); the
   *   authoritative percussion signal (a mis-named drum track no longer plays as piano)
   */
  addSecondaryChannel(trackId, trackName, results, beatsPerMeasure, midiProgram, kind) {
    this.removeSecondaryChannel(trackId); // remove if already present
    const bpm = beatsPerMeasure || this.bpm;
    const measures = PlaybackEngine._buildMeasures(results, bpm);
    // Trust the backend kind first (GP 7/8 carries a real per-track instrument
    // kind); fall back to the name heuristic for adapters that don't (MusicXML/
    // MIDI). Drums MUST play on GM channel 9 or the kit sounds like a piano.
    const percussion = String(kind || '').toLowerCase() === 'drums'
      || PlaybackEngine._isPercussionTrack(trackName);
    // Percussion always plays on GM channel 9 (the drum kit); melodic tracks get
    // the next free non-9 channel.
    const midiChannel = percussion ? 9 : this._allocateMidiChannel();
    const resolvedProgram = (Number.isInteger(midiProgram) && midiProgram >= 0)
      ? midiProgram
      : PlaybackEngine._instrumentToMidiProgram(PlaybackEngine._inferInstrument(trackName));
    const ch = {
      trackId, trackName, measures, synth: null, gain: 0.8, enabled: true, _loading: false,
      midiChannel, midiProgram: resolvedProgram, percussion,
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
      // Channel 9 is the GM drum kit: do NOT send a melodic programChange (it would
      // turn the kit into a piano/guitar). Pitch-bend range is set lazily, only when
      // a note actually bends (see _schedulePitchAutomation), to avoid flooding the
      // synth with RPN messages it logs as "Unrecognized RPN" for silent channels.
      if (!ch.percussion) {
        this._spessa.programChange(ch.midiChannel, this._resolveProgram(ch.midiProgram));
      }
      // Track volume via CC7 (like the primary), so velocity carries only the
      // note dynamics/expression and the mixer slider works live on held notes.
      try { this._spessa.controllerChange(ch.midiChannel, 7, Math.round((ch.gain ?? 0.8) * 127)); } catch (_) {}
      ch.synth = 'spessa';
      console.log(`[FretWise] secondary "${ch.trackName}" → `
        + (ch.percussion ? 'percussion (ch 9)' : `GM ${ch.midiProgram} (ch ${ch.midiChannel})`));
      this._catchUpChannel(ch);
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
      this._catchUpChannel(ch);
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
    // 1. Exact GM program present → use it.
    if (pool.some((p) => p.program === desired)) return desired;
    // 2. Any preset in the same GM family (the 8-program block: guitars 24-31,
    //    basses 32-39, pianos 0-7, …). Keeps a bass/keys/strings part on its own
    //    family instead of collapsing every channel onto a guitar (or preset 0,
    //    often DRUMS) when a non-GM / single-instrument bank is loaded.
    const famStart = Math.floor(Math.max(0, Math.min(127, desired)) / 8) * 8;
    const sameFamily = pool.find((p) => p.program >= famStart && p.program <= famStart + 7);
    if (sameFamily) return sameFamily.program;
    // 3. Last resort: a guitar-named preset, else the first available.
    const guitar = pool.find((p) => /guitar|gtr/i.test(p.presetName || p.name || ''));
    if (guitar) return guitar.program;
    return pool[0].program;
  }

  /**
   * Fire onSoundfontWarning when the loaded bank does not look like General MIDI.
   * A GM bank exposes presets spanning many families (bass 32-39, keys, strings,
   * a drum kit); a single-instrument / guitar-only pack has a handful. On such a
   * bank, non-guitar tracks have nowhere to map and everything collapses onto one
   * timbre — the "wrong instruments whatever the soundfont" symptom. Heuristic,
   * best-effort: never throws, only advisory.
   * @param {string} [url] — resolved soundfont URL (for the diagnostic message)
   */
  _warnIfNotGeneralMidi(url) {
    try {
      const presets = this._spessaPresets || [];
      if (!presets.length) return;
      const bank0 = presets.filter((p) => (p.bank ?? 0) === 0);
      const programs = new Set(bank0.map((p) => p.program));
      const hasBass = [...programs].some((p) => p >= 32 && p <= 39);
      const hasDrums = presets.some((p) => (p.bank ?? 0) === 128)
        || presets.some((p) => /drum|kit|percussion/i.test(p.presetName || p.name || ''));
      // A real GM bank has dozens of distinct programs; < 12 or no bass family is
      // a strong "single-instrument / non-GM pack" signal.
      const looksGm = programs.size >= 12 && hasBass;
      if (looksGm) return;
      const name = (() => { try { return decodeURIComponent(new URL(url, location.href).searchParams.get('name') || ''); } catch (_) { return ''; } })();
      const msg = `Le soundfont actif${name ? ` « ${name} »` : ''} n'est pas un banc `
        + `General MIDI complet (${programs.size} instrument(s)`
        + `${hasDrums ? '' : ', pas de batterie'}${hasBass ? '' : ', pas de basse'}). `
        + `Les pistes autres que guitare sonneront faux. Choisissez un banc GM `
        + `(ex. GeneralUser-GS) dans les réglages.`;
      console.warn('[FretWise]', msg);
      this.onSoundfontWarning?.(msg, { presetCount: programs.size, url });
    } catch (_) { /* advisory only */ }
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
    if (channel === 0) {
      this._primaryVolume = v;
    } else {
      // Persist on the secondary channel so re-scheduling / catch-up keeps the level.
      const ch = this._secondaryChannels.find((c) => c.midiChannel === channel);
      if (ch) ch.gain = v;
    }
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
    this._resumeSubMeasureSec = 0;  // consumed

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

    // Anchor the audio clock to the current song position, plus a small startup
    // lead so the very first downbeat is queued slightly in the future (never at
    // t=now, which the browser plays late). The cursor clock is offset by the
    // same lead so the moving cursor and the sound stay aligned. The lookahead
    // pump (_pumpScheduler), driven every tick, then queues each measure at its
    // true absolute AudioContext time — timing is no longer tied to when the
    // cursor happens to cross a bar line during a (possibly janky) render frame.
    const lead = (this._audioCtx && this.audioEnabled) ? this._schedLeadSec : 0;
    this._startTime = performance.now() + lead * 1000 - resumeOffsetSec * 1000;
    this._audioAnchorSongSec = this._measureStartSec(this._startMeasure) + resumeOffsetSec;
    this._audioAnchorTime = (this._audioCtx ? this._audioCtx.currentTime : 0) + lead;
    this._schedulerMeasure = this._startMeasure;
    this._skipMeasure = this._startMeasure;
    this._firstScheduleSkipSec = resumeOffsetSec;
    this._lastScheduledMeasure = this._startMeasure - 1;

    // Prime the pump once so the first measures are queued before the first
    // animation frame (a delayed first RAF must not create a startup gap).
    if (this.audioEnabled || this.metronome) this._pumpScheduler();

    this._tick();
  }

  /**
   * Lookahead scheduler pump. Queues every measure whose start falls within
   * `_lookaheadSec` of the AudioContext clock, at its true absolute time derived
   * from the play anchor. Idempotent per measure (advances `_schedulerMeasure`),
   * cheap enough to call on every animation frame. This is the decoupling that
   * keeps notes on time regardless of render-frame jitter.
   */
  _pumpScheduler() {
    if (!this._audioCtx) return;
    const horizon = this._audioCtx.currentTime + this._lookaheadSec;
    let guard = 0;
    while (this._schedulerMeasure < this.totalMeasures && guard++ < 1024) {
      const m = this._schedulerMeasure;
      const absStart = this._songSecToAudioTime(this._measureStartSec(m));
      if (absStart > horizon) break;   // not due yet
      const skip = (m === this._skipMeasure) ? (this._firstScheduleSkipSec || 0) : 0;
      if (this.metronome) this._scheduleMetronomeMeasure(m, absStart, skip);
      if (this.audioEnabled) this._scheduleMeasureNotes(m, absStart, skip);
      this._lastScheduledMeasure = m;
      this._schedulerMeasure = m + 1;
    }
  }

  /**
   * Re-anchor and restart the scheduler at `measure` (used on A/B loop wrap).
   * Cuts notes already queued past the loop point so they don't ring over the
   * restart, and resets the cursor clock so the two stay aligned.
   */
  _restartSegment(measure) {
    const lead = (this._audioCtx && this.audioEnabled) ? this._schedLeadSec : 0;
    this._startMeasure = measure;
    this._startTime = performance.now() + lead * 1000;
    this._audioAnchorSongSec = this._measureStartSec(measure);
    this._audioAnchorTime = (this._audioCtx ? this._audioCtx.currentTime : 0) + lead;
    this._schedulerMeasure = measure;
    this._skipMeasure = measure;
    this._firstScheduleSkipSec = 0;
    this._lastScheduledMeasure = measure - 1;
    if (this._spessa) {
      try { this._spessa.stopAll?.(); } catch (_) {}
      this._resetPitchBends();
    } else if (this._synth && this._synth !== 'spessa') {
      try { this._synth.stop(); } catch (_) {}
    }
  }

  /**
   * Schedule ONE just-loaded secondary channel to catch up the measures the pump
   * has already queued for the other channels, using the shared anchor so it
   * lands in sync. Used when a backing track's instrument resolves mid-playback.
   * @param {Object} ch
   */
  _catchUpChannel(ch) {
    if (!this.isPlaying || !this._audioCtx || !ch || !ch.synth) return;
    const cur = this.renderer ? this.renderer.cursorMeasure : this._startMeasure;
    const elapsed = (performance.now() - this._startTime) / 1000;
    const curSongSec = this._measureStartSec(this._startMeasure) + elapsed;
    const skipInCur = Math.max(0, curSongSec - this._measureStartSec(cur));
    const upTo = Math.max(cur, this._schedulerMeasure - 1);
    for (let m = cur; m <= upTo && m < this.totalMeasures; m += 1) {
      const absStart = this._songSecToAudioTime(this._measureStartSec(m));
      this._scheduleChannelNotes(ch, m, absStart, (m === cur) ? skipInCur : 0);
    }
  }

  /**
   * Rewind the pump to the current playhead so every channel (re)schedules from
   * the present. Safe ONLY when nothing is currently sounding (all channels were
   * silent because the synth was still loading) — used when SpessaSynth finishes
   * loading mid-playback. Re-scheduling audible notes this way would double them.
   */
  _resyncSchedulerToNow() {
    if (!this.isPlaying || !this._audioCtx) return;
    const cur = this.renderer ? this.renderer.cursorMeasure : this._startMeasure;
    const elapsed = (performance.now() - this._startTime) / 1000;
    const curSongSec = this._measureStartSec(this._startMeasure) + elapsed;
    this._audioAnchorTime = this._audioCtx.currentTime;
    this._audioAnchorSongSec = curSongSec;
    this._schedulerMeasure = cur;
    this._skipMeasure = cur;
    this._firstScheduleSkipSec = Math.max(0, curSongSec - this._measureStartSec(cur));
    this._lastScheduledMeasure = cur - 1;
    this._pumpScheduler();
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
      this._resetPitchBends();
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
    // During the startup lead (elapsed < 0) `targetMeasure` can fall below the
    // start; hold the cursor at the start measure until real playback begins.
    if (targetMeasure < this._startMeasure) targetMeasure = this._startMeasure;

    // Loop handling — re-anchor the scheduler at the loop start (cuts ringing
    // notes past the loop point) and reset the cursor clock in one place.
    if (this.loopStart >= 0 && this.loopEnd >= this.loopStart) {
      if (targetMeasure > this.loopEnd) {
        this._restartSegment(this.loopStart);
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

    // Update cursor if changed (rendering only — audio scheduling is decoupled)
    if (targetMeasure !== this.renderer.cursorMeasure) {
      this.renderer.cursorMeasure = targetMeasure;
      this.renderer.render();
      if (this.onMeasureChange) this.onMeasureChange(targetMeasure);
      if (this.onPositionChange) this.onPositionChange(targetMeasure / Math.max(1, this.totalMeasures - 1));
      this._scrollCursorIntoView();
    }

    // Lookahead audio scheduling — runs every tick, independent of cursor
    // crossings and of the render above, so a heavy render frame or GC pause can
    // no longer make notes fire late.
    if (this.audioEnabled || this.metronome) this._pumpScheduler();

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
   *  measure's real beat count (so a 2/4 or 6/8 bar clicks the right number)
   *  and that measure's own tempo. Clicks are placed on the absolute audio
   *  timeline (`absStart`), matching the lookahead note scheduler.
   *  @param {number} measureIdx
   *  @param {number} absStart — AudioContext time of the measure's first beat
   *  @param {number} [skipSec=0] — skip clicks before this offset (resume/seek)
   */
  _scheduleMetronomeMeasure(measureIdx, absStart, skipSec = 0) {
    if (!this._audioCtx) return;
    this._ensureTimeline();
    const base = Number.isFinite(absStart) ? absStart : this._audioCtx.currentTime;
    const slotBeats = this._slotStartBeat[measureIdx + 1] - this._slotStartBeat[measureIdx];
    const clicks = Math.max(1, Math.round(slotBeats > 0 ? slotBeats : this.bpm));
    const secPerBeat = this._measureSecPerBeat(measureIdx);
    for (let b = 0; b < clicks; b++) {
      const off = b * secPerBeat;
      if (off < skipSec) continue;
      this._click(base + off, b === 0);
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

      // ── Soundfont fetch (diagnostic-instrumented; see point #1) ──────────
      // `/api/soundfont` 307-redirects to a versioned, immutable URL, so resp.url
      // identifies the actual bank. We log fetch-vs-parse timing separately and
      // reuse the bytes from the module-level cache when the same bank is loaded
      // again (engine re-creation, or switching back to a previously seen bank),
      // which is the difference between a multi-second reload and an instant one.
      console.log('[FretWise] SpessaSynth: fetching SF2 soundfont…');
      const tFetch = performance.now();
      const resp = await fetch('/api/soundfont');
      if (!resp.ok) throw new Error(`SF2 fetch: HTTP ${resp.status}`);
      let sf2Buffer = _SF2_BUFFER_CACHE.get(resp.url);
      if (sf2Buffer) {
        this.onSynthProgress?.(1, (sf2Buffer.byteLength / 1048576).toFixed(1),
          (sf2Buffer.byteLength / 1048576).toFixed(1));
        console.log(`[FretWise] SF2 reused from in-memory cache: ${resp.url} `
          + `(${(sf2Buffer.byteLength / 1048576).toFixed(1)} MB, no download)`);
      } else {
        sf2Buffer = await this._fetchWithProgress(resp);
        _SF2_BUFFER_CACHE.clear();                       // keep at most one bank
        _SF2_BUFFER_CACHE.set(resp.url, sf2Buffer);
        console.log(`[FretWise] SF2 downloaded in ${(performance.now() - tFetch).toFixed(0)} ms: `
          + `${resp.url} (${(sf2Buffer.byteLength / 1048576).toFixed(1)} MB)`);
      }
      if (this._lastSf2Url && this._lastSf2Url !== resp.url) {
        console.warn(`[FretWise] active soundfont bank CHANGED `
          + `(${this._lastSf2Url} → ${resp.url}) — this forces a synth reload.`);
      }
      this._lastSf2Url = resp.url;

      const dest = this._masterGain || this._audioCtx.destination;
      const tParse = performance.now();
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
      console.log(`[FretWise] SF2 parsed/ready in ${(performance.now() - tParse).toFixed(0)} ms `
        + `(worklet decode; cap was ${(readyCapMs / 1000).toFixed(0)} s)`);
      this._spessaPresets = Array.isArray(spessa.presetList) ? spessa.presetList.slice() : [];

      this._spessa = spessa;
      this._synth = 'spessa';

      // Set the (resolved) GM program for primary and any registered secondary channels
      const primaryProg = this._resolveProgram(this._midiProgram);
      spessa.programChange(0, primaryProg);
      // Balance the open track against the backing tracks (CC7 on channel 0).
      try { spessa.controllerChange(0, 7, Math.round(this._primaryVolume * 127)); } catch (_) { /* */ }
      for (const ch of this._secondaryChannels) {
        if (!ch.percussion) {
          spessa.programChange(ch.midiChannel, this._resolveProgram(ch.midiProgram));
        }
        try { spessa.controllerChange(ch.midiChannel, 7, Math.round((ch.gain ?? 0.8) * 127)); } catch (_) {}
        ch.synth = 'spessa';
      }
      // SpessaSynth finished loading while the song was already playing: every
      // channel was silent until now (primary stayed silent during load, and
      // secondaries deferred), so rewind the pump to the present and reschedule
      // all channels from here. Safe against doubling precisely because nothing
      // was audible yet.
      if (this.isPlaying) this._resyncSchedulerToNow();

      console.log(`[FretWise] SpessaSynth ready — ${this._spessaPresets.length} presets; `
        + `GM ${this._midiProgram}`
        + (primaryProg !== this._midiProgram ? ` → ${primaryProg} (mapped; ${this._midiProgram} absent)` : ''));
      // Warn when the active bank is not General MIDI: without GM programs for
      // bass/drums/keys, the browser synth collapses every track onto a guitar
      // (or preset 0 = drums), so tabs sound wrong whatever soundfont is tried.
      this._warnIfNotGeneralMidi(resp.url);
      // DIAGNOSTIC: confirm what the synth itself thinks is on each channel after
      // our programChange calls, vs what we asked for — exposes any internal
      // override (e.g. drum-channel auto-reset, preset-not-found fallback).
      try {
        spessa.eventHandler.addEvent('programchange', 'fretwise-diag', (e) =>
          console.log(`[FretWise][diag] programchange event: channel ${e.channel} → `
            + `bank ${e.bank} program ${e.program}`));
      } catch (_) { /* diagnostic only */ }
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

  _playbackPitch(note) {
    const harmonicPitch = Number(note?.harmonic_resultant_pitch);
    if (Number.isFinite(harmonicPitch) && harmonicPitch > 0) return harmonicPitch;
    const pitch = Number(note?.pitch);
    return Number.isFinite(pitch) ? pitch : 60;
  }

  _clampVelocity(value) {
    return Math.max(1, Math.min(127, Math.round(value)));
  }

  _expressionForNote(note, baseDurationSec) {
    let duration = baseDurationSec;
    let velocityScale = 1.0;

    if (note.ghost) velocityScale *= 0.45;
    if (note.muted) velocityScale *= 0.65;
    if (note.palm_muted) velocityScale *= 0.78;
    if (note.accent) velocityScale *= 1.15;
    if (note.accent_strong) velocityScale *= 1.32;
    if (note.slap || note.pop) velocityScale *= 1.22;
    if (note.golpe) velocityScale *= 1.35;
    if (note.tapping) velocityScale *= 1.1;
    if (note.rasgueado) velocityScale *= 1.12;

    if (note.let_ring) duration *= 1.35;
    if (note.palm_muted) duration *= 0.55;
    if (note.staccato || note.articulation === 'staccato') duration *= 0.45;
    if (note.rasgueado) duration *= 0.82;
    if (note.articulation === 'hammer_on' || note.articulation === 'pull_off') {
      velocityScale *= 0.82;
      duration *= 1.08;
    } else if (note.articulation === 'legato') {
      velocityScale *= 0.9;
      duration *= 1.12;
    }
    if (note.muted || note.golpe) duration = Math.min(duration * 0.28, 0.12);

    return {
      duration: Math.max(0.035, duration),
      velocityScale,
    };
  }

  _strumOffsetSec(note, measureNotes, secPerBeat) {
    const direction = note?.strum_direction || (note?.rasgueado ? 'down' : null);
    if (direction !== 'up' && direction !== 'down') return 0;
    const onset = Number(note.onset);
    const stringNum = Number(note.string);
    if (!Number.isFinite(onset) || !Number.isFinite(stringNum)) return 0;

    const chord = (measureNotes || [])
      .filter(n => Math.abs(Number(n.onset) - onset) < 0.00001 && Number.isFinite(Number(n.string)))
      .sort((a, b) => direction === 'down'
        ? Number(b.string) - Number(a.string)
        : Number(a.string) - Number(b.string));
    if (chord.length <= 1) return 0;

    const rank = chord.findIndex(n => Number(n.string) === stringNum && Number(n.pitch) === Number(note.pitch));
    if (rank <= 0) return 0;
    const step = note?.rasgueado
      ? Math.min(0.012, secPerBeat * 0.025)
      : Math.min(0.018, secPerBeat * 0.035);
    return rank * step;
  }

  _noteAttacks(note, when, duration, secPerBeat) {
    if (!note.tremolo_picking) return [{ when, duration }];
    const interval = Math.max(0.045, secPerBeat / 4);
    const count = Math.max(2, Math.floor(duration / interval));
    const attacks = [];
    for (let i = 0; i < count; i += 1) {
      const attackWhen = when + i * interval;
      const remaining = duration - i * interval;
      if (remaining <= 0.02) break;
      attacks.push({
        when: attackWhen,
        duration: Math.max(0.03, Math.min(interval * 0.82, remaining)),
      });
    }
    return attacks;
  }

  _ensurePitchBendRange(channel) {
    if (!this._spessa || !Number.isInteger(channel)) return;
    if (this._pitchBendRangeChannels.has(channel)) return;
    try {
      this._spessa.setPitchBendRange(channel, this._pitchBendRangeSemitones);
      this._sendPitchWheel(channel, 0, this._audioCtx?.currentTime ?? 0);
      this._pitchBendRangeChannels.add(channel);
    } catch (_) {
      // Pitch bend is expressive sugar: scheduling notes must never depend on it.
    }
  }

  _resetPitchBends() {
    if (!this._spessa) return;
    const now = this._audioCtx?.currentTime ?? 0;
    this._sendPitchWheel(0, 0, now);
    for (const ch of this._secondaryChannels) {
      if (Number.isInteger(ch.midiChannel)) this._sendPitchWheel(ch.midiChannel, 0, now);
    }
    for (const ch of this._pitchBendRangeChannels) {
      if (Number.isInteger(ch)) this._sendPitchWheel(ch, 0, now);
    }
  }

  _sendPitchWheel(channel, semitones, time) {
    if (!this._spessa) return;
    const range = Math.max(1, this._pitchBendRangeSemitones);
    const clamped = Math.max(-range, Math.min(range, Number(semitones) || 0));
    const normalized = clamped / range;
    const value = Math.max(0, Math.min(16383, Math.round(8192 + normalized * 8191)));
    const lsb = value & 0x7f;
    const msb = (value >> 7) & 0x7f;
    try {
      this._spessa.pitchWheel(channel, lsb, msb, { time });
    } catch (_) {
      // Some fallback or older synth builds may not support scheduled pitch wheel.
    }
  }

  _pitchSamplesForNote(note, measureNotes, startTime, durationSec) {
    // Number.isFinite (no coercion) is deliberate: bend_value is null for the
    // overwhelming majority of notes, and Number(null) === 0 — Number.isFinite
    // would then wrongly call every un-bent note "bent". Number.isFinite alone
    // returns false for null/undefined without coercing them to 0 first.
    const hasBend = Number.isFinite(note.bend_value);
    const hasSlide = !!note.slide_type || note.articulation === 'slide';
    const hasVibrato = note.articulation === 'vibrato'
      || note.articulation === 'wide_vibrato'
      || note.vibrato_wide;
    if (!hasBend && !hasSlide && !hasVibrato) return [];

    const duration = Math.max(0.04, durationSec);
    const points = this._basePitchPoints(note, measureNotes);
    const evalBase = (frac) => this._interpolatedPitch(points, frac);
    const samples = [];

    if (hasVibrato) {
      const amp = (note.vibrato_wide || note.articulation === 'wide_vibrato') ? 0.45 : 0.22;
      const rateHz = note.vibrato_wide ? 5.3 : 6.2;
      const startFrac = Math.min(0.35, 0.12 / duration);
      const sampleCount = Math.max(3, Math.ceil(duration / 0.045));
      for (let i = 0; i <= sampleCount; i += 1) {
        const frac = i / sampleCount;
        const vib = frac < startFrac
          ? 0
          : Math.sin((frac - startFrac) * duration * rateHz * Math.PI * 2) * amp;
        samples.push({ time: startTime + frac * duration, semitones: evalBase(frac) + vib });
      }
    } else {
      for (const point of points) {
        samples.push({ time: startTime + point.frac * duration, semitones: point.semitones });
      }
    }

    samples.push({ time: startTime + duration + 0.012, semitones: 0 });
    return samples;
  }

  _basePitchPoints(note, measureNotes) {
    const points = [{ frac: 0, semitones: 0 }];
    const bendValue = Number(note.bend_value);
    if (Number.isFinite(bendValue) && Math.abs(bendValue) > 0.001) {
      const type = String(note.bend_type || 'normal');
      if (type === 'release') {
        points.push({ frac: 0, semitones: bendValue }, { frac: 0.68, semitones: 0 });
      } else if (type === 'pre_bend') {
        points.push({ frac: 0, semitones: bendValue }, { frac: 0.9, semitones: bendValue });
      } else if (type === 'pre_bend_release') {
        points.push({ frac: 0, semitones: bendValue }, { frac: 0.78, semitones: 0 });
      } else {
        points.push({ frac: 0.34, semitones: bendValue }, { frac: 0.9, semitones: bendValue });
      }
    }

    const slideType = note.slide_type || (note.articulation === 'slide' ? 'shift' : null);
    if (slideType) {
      const target = this._slideTargetSemitones(note, measureNotes, slideType);
      if (target !== null) {
        if (slideType === 'slide_in_above' || slideType === 'slide_in_below') {
          points.push({ frac: 0, semitones: target }, { frac: 0.22, semitones: 0 });
        } else if (slideType === 'slide_out_up' || slideType === 'slide_out_down') {
          points.push({ frac: 0.2, semitones: 0 }, { frac: 0.85, semitones: target });
        } else {
          points.push({ frac: 0.08, semitones: 0 }, { frac: 0.82, semitones: target });
        }
      }
    }
    return points.sort((a, b) => a.frac - b.frac);
  }

  _slideTargetSemitones(note, measureNotes, slideType) {
    if (slideType === 'slide_in_above') return 2;
    if (slideType === 'slide_in_below') return -2;
    if (slideType === 'slide_out_up') return 2;
    if (slideType === 'slide_out_down') return -2;

    const onset = Number(note.onset);
    const stringNum = Number(note.string);
    const pitch = Number(note.pitch);
    if (!Number.isFinite(onset) || !Number.isFinite(stringNum) || !Number.isFinite(pitch)) {
      return null;
    }
    const next = (measureNotes || [])
      .filter(n => Number(n.onset) > onset + 0.00001 && Number(n.string) === stringNum)
      .sort((a, b) => Number(a.onset) - Number(b.onset))[0];
    if (!next || !Number.isFinite(Number(next.pitch))) return null;
    return Number(next.pitch) - pitch;
  }

  _interpolatedPitch(points, frac) {
    if (!points.length) return 0;
    let prev = points[0];
    for (const next of points.slice(1)) {
      if (frac <= next.frac) {
        const span = Math.max(0.0001, next.frac - prev.frac);
        const t = Math.max(0, Math.min(1, (frac - prev.frac) / span));
        return prev.semitones + (next.semitones - prev.semitones) * t;
      }
      prev = next;
    }
    return prev.semitones;
  }

  _schedulePitchAutomation(channel, note, measureNotes, when, duration) {
    if (!this._spessa) return;
    const samples = this._pitchSamplesForNote(note, measureNotes, when, duration);
    if (!samples.length) return;
    this._ensurePitchBendRange(channel);
    this._sendPitchWheel(channel, 0, Math.max(0, when - 0.004));
    for (const sample of samples) {
      this._sendPitchWheel(channel, sample.semitones, sample.time);
    }
  }

  /** Sounding duration (seconds) from the backend's phrasing engine (P1), or
   *  null when the note carries no `perf` block (legacy/staff-only fallback —
   *  caller then falls back to _expressionForNote). `perf.dur_beats` already
   *  encodes articulation scaling AND let-ring look-ahead to the next note on
   *  the same string (computed track-wide in Python, not measure-locally). */
  _perfDurationSec(note, secPerBeat) {
    const beats = note?.perf?.dur_beats;
    return Number.isFinite(beats) ? Math.max(0.03, beats * secPerBeat) : null;
  }

  /** Final MIDI velocity from the backend's phrasing engine, or null. */
  _perfVelocity(note) {
    const v = note?.perf?.velocity;
    return Number.isInteger(v) ? v : null;
  }

  /** Schedule a note's pitch-bend/slide/vibrato from the backend's dense
   *  `perf.bend` curve (P1) — smooth glide instead of the old sparse
   *  corner-point stair-step. Returns true if it scheduled anything, so the
   *  caller can fall back to the legacy in-browser curve otherwise. */
  _schedulePitchAutomationPerf(channel, note, when, secPerBeat) {
    const curve = note?.perf?.bend;
    if (!this._spessa || !Array.isArray(curve) || !curve.length) return false;
    this._ensurePitchBendRange(channel);
    this._sendPitchWheel(channel, 0, Math.max(0, when - 0.004));
    for (const [beatOffset, semitones] of curve) {
      this._sendPitchWheel(channel, semitones, when + beatOffset * secPerBeat);
    }
    return true;
  }

  _hasPitchExpression(note) {
    // Prefer the backend's resolution (P1): it already worked out slide
    // targets etc. from the whole track, not just the current measure.
    if (note?.perf) return !!note.perf.bend;
    // Number.isFinite (no coercion) — see the comment in _pitchSamplesForNote.
    // The bug this guards against: Number(null) === 0, so wrapping in Number()
    // made every un-bent note (bend_value === null, the overwhelming majority)
    // register as "has pitch expression". Every chord note on every track —
    // including simultaneous drum hits, whose GM program is a meaningless
    // placeholder (0 = Acoustic Piano) since percussion always plays on channel
    // 9 — then grabbed a shared auxiliary MIDI channel and reprogrammed it,
    // stepping on whatever real instrument (guitar, strings…) was using that
    // channel for its own chord bends. Audible symptom: random piano bleed-through
    // on tracks that have no piano at all.
    return Number.isFinite(note?.bend_value)
      || !!note?.slide_type
      || note?.articulation === 'slide'
      || note?.articulation === 'vibrato'
      || note?.articulation === 'wide_vibrato'
      || !!note?.vibrato_wide;
  }

  _createPitchChannelAllocator(baseChannel, midiProgram, volume) {
    const reserved = new Set([0, 9, baseChannel]);
    for (const ch of this._secondaryChannels) {
      if (Number.isInteger(ch.midiChannel)) reserved.add(ch.midiChannel);
    }
    const pool = [];
    for (let ch = 1; ch <= 15; ch += 1) {
      if (!reserved.has(ch)) pool.push(ch);
    }
    const busyUntil = new Map();
    const resolvedProgram = this._resolveProgram(midiProgram);
    const level = Math.max(0, Math.min(127, Math.round((volume ?? 0.8) * 127)));

    return (note, measureNotes, when, duration) => {
      if (!this._hasPitchExpression(note)) return baseChannel;
      const sameOnset = (measureNotes || [])
        .filter(n => Math.abs(Number(n.onset) - Number(note.onset)) < 0.00001);
      if (sameOnset.length <= 1) return baseChannel;

      const free = pool.find(ch => (busyUntil.get(ch) ?? 0) <= when - 0.002);
      if (!Number.isInteger(free)) return null;
      busyUntil.set(free, when + duration + 0.05);
      try {
        this._spessa.programChange(free, resolvedProgram);
        this._spessa.controllerChange(free, 7, level);
      } catch (_) {
        // A failed auxiliary channel should play normally, without pitch automation.
        return null;
      }
      this._ensurePitchBendRange(free);
      return free;
    };
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

  /** Earliest later-onset same-pitch note offset (seconds from measure start),
   *  or Infinity if none. Two notes of the same pitch on one MIDI channel cannot
   *  both ring — the second's noteOn (or the first's noteOff) cuts the other — so
   *  the scheduler trims the earlier note to end just before the later restrikes,
   *  turning a swallowed/half-cut re-attack into a clean one (the audible
   *  "cacophony" from overlapping voices on channel 0). */
  _nextSamePitchOffsetSec(note, measureNotes, measureOnset, secPerBeat, playbackPitch, myOffsetSec) {
    let best = Infinity;
    for (const other of measureNotes) {
      if (other === note) continue;
      if (this._playbackPitch(other) !== playbackPitch) continue;
      const off = (Number(other.onset) - measureOnset) * secPerBeat;
      if (off > myOffsetSec + 1e-6 && off < best) best = off;
    }
    return best;
  }

  /** Cap a note's duration so it ends just before the same pitch restrikes. */
  _capSamePitchDuration(rawDuration, when, absStart, nextSameOffsetSec) {
    if (!Number.isFinite(nextSameOffsetSec)) return rawDuration;
    const cap = (absStart + nextSameOffsetSec) - when - 0.006;
    return Math.max(0.03, Math.min(rawDuration, cap));
  }

  /** Schedule all notes in a measure to play at correct times.
   *  Dispatches to SpessaSynth (SF2) when loaded, oscillator otherwise.
   *  @param {number} measureIdx
   *  @param {number} absStart — AudioContext time of the measure's first beat
   *  @param {number} [skipBeforeMeasureSec=0] — drop notes before this offset (resume/seek)
   */
  _scheduleMeasureNotes(measureIdx, absStart, skipBeforeMeasureSec = 0) {
    // Audio dispatch must never throw into play()/_tick() and freeze the
    // playhead. Swallow + log here; the warning names the real failure (e.g.
    // a synth/worklet API mismatch) so it can be fixed without losing the cursor.
    try {
      this._scheduleMeasureNotesImpl(measureIdx, absStart, skipBeforeMeasureSec);
    } catch (err) {
      console.warn('[FretWise] note scheduling failed (playhead continues):', err);
    }
  }

  _scheduleMeasureNotesImpl(measureIdx, absStart, skipBeforeMeasureSec = 0) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const base = Number.isFinite(absStart) ? absStart : this._audioCtx.currentTime;
    const notes = this.renderer.measures[measureIdx];
    const measureOnset = this._measureOnsetBeats(measureIdx);
    const secPerBeat = this._measureSecPerBeat(measureIdx);

    // Primary track scheduling (skipped for rest bars, but secondary always runs below).
    if (notes && notes.length) {
      if (this._spessa) {
        // SpessaSynth: precise AudioContext-time scheduling via noteOn/noteOff
        const pitchChannelFor = this._createPitchChannelAllocator(
          0, this._midiProgram, this._primaryVolume,
        );
        for (const note of notes) {
          const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
          if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
          const playbackPitch = this._playbackPitch(note);
          const strumOffset = this._strumOffsetSec(note, notes, secPerBeat);
          const when = base + noteOffsetInMeasure + strumOffset;
          const perfDur = this._perfDurationSec(note, secPerBeat);
          const expr = perfDur == null
            ? this._expressionForNote(note, Math.max(0.04, note.duration * secPerBeat - 0.025))
            : { duration: perfDur, velocityScale: 1 };
          const nextSame = this._nextSamePitchOffsetSec(
            note, notes, measureOnset, secPerBeat, playbackPitch, noteOffsetInMeasure);
          const dur = this._capSamePitchDuration(expr.duration, when, base, nextSame);
          const perfVel = this._perfVelocity(note);
          const velocity = perfVel != null
            ? perfVel
            : this._clampVelocity(this._dynamicToVelocity(note.dynamic) * expr.velocityScale);
          const pitchChannel = pitchChannelFor(note, notes, when, dur);
          const playChannel = Number.isInteger(pitchChannel) ? pitchChannel : 0;
          if (Number.isInteger(pitchChannel)) {
            if (!this._schedulePitchAutomationPerf(pitchChannel, note, when, secPerBeat)) {
              this._schedulePitchAutomation(pitchChannel, note, notes, when, dur);
            }
          }
          // v3 SpessaSynth API: 4th arg is an options object ({ time }), NOT a
          // (debug, startTime) pair. Passing a boolean makes the lib do
          // `'time' in false` and throw on every note → total silence.
          for (const attack of this._noteAttacks(note, when, dur, secPerBeat)) {
            this._spessa.noteOn(playChannel, playbackPitch, velocity, { time: attack.when });
            this._spessa.noteOff(playChannel, playbackPitch, false, { time: attack.when + attack.duration });
          }
        }
      } else if (this._synth) {
        // soundfont-player fallback
        for (const note of notes) {
          const noteOffsetInMeasure = (note.onset - measureOnset) * secPerBeat;
          if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
          const playbackPitch = this._playbackPitch(note);
          const strumOffset = this._strumOffsetSec(note, notes, secPerBeat);
          const when = base + noteOffsetInMeasure + strumOffset;
          const perfDur = this._perfDurationSec(note, secPerBeat);
          const expr = perfDur == null
            ? this._expressionForNote(note, Math.max(0.04, note.duration * secPerBeat - 0.025))
            : { duration: perfDur, velocityScale: 1 };
          const nextSame = this._nextSamePitchOffsetSec(
            note, notes, measureOnset, secPerBeat, playbackPitch, noteOffsetInMeasure);
          const dur = this._capSamePitchDuration(expr.duration, when, base, nextSame);
          const perfVel = this._perfVelocity(note);
          const gain = perfVel != null
            ? Math.min(1, perfVel / 127)
            : Math.min(1, (this._dynamicToVelocity(note.dynamic) / 127) * expr.velocityScale);
          for (const attack of this._noteAttacks(note, when, dur, secPerBeat)) {
            this._synth.play(playbackPitch, attack.when, { duration: attack.duration, gain });
          }
        }
      } else if (this._synthLoading) {
        // SpessaSynth (SF2) is still loading: stay silent for this measure instead
        // of playing the harsh oscillator. The real instrument takes over within a
        // few seconds — and only on the first page-load, since later songs reuse
        // the already-loaded synth. Brief silence beats a few bars of bad tone.
      } else {
        // Synth definitively unavailable (SpessaSynth + MusyngKite both failed):
        // last-resort oscillator so playback is never completely silent.
        this._scheduleMeasureNotesOscillator(measureIdx, base);
      }
    }

    // Schedule secondary audio channels (same AudioContext time base = perfect sync).
    // Runs even when the primary measure is empty so backing tracks play through rest bars.
    for (const ch of this._secondaryChannels) {
      if (!ch.enabled || !ch.synth) continue;
      this._scheduleChannelNotes(ch, measureIdx, base, skipBeforeMeasureSec);
    }
  }

  /** Schedule notes for a single secondary channel at a given measure.
   * @param {Object} ch - secondary channel object
   * @param {number} measureIdx
   * @param {number} absStart — AudioContext time of the measure's first beat
   * @param {number} [skipBeforeMeasureSec=0]
   */
  _scheduleChannelNotes(ch, measureIdx, absStart, skipBeforeMeasureSec = 0) {
    if (!ch.synth || !ch.enabled || !this._audioCtx || !this.audioEnabled) return;
    const base = Number.isFinite(absStart) ? absStart : this._audioCtx.currentTime;
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
    const chSpb = this._measureSecPerBeat(measureIdx);

    if (this._spessa) {
      // Percussion never needs an auxiliary pitch-bend channel — GM channel 9
      // keys are fixed drum-kit slots, pitch automation is musically meaningless
      // there, and ch.midiProgram for a drum track is a meaningless placeholder
      // (typically 0 = Acoustic Piano) that must never be programChange'd onto a
      // shared auxiliary channel another (melodic) track's chord bends are using.
      // Defense in depth alongside the _hasPitchExpression null-coercion fix.
      const pitchChannelFor = ch.percussion
        ? (() => null)
        : this._createPitchChannelAllocator(ch.midiChannel, ch.midiProgram, ch.gain);
      for (const note of chNotes) {
        const noteOffsetInMeasure = (note.onset - chMeasureOnset) * chSpb;
        if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
        const playbackPitch = this._playbackPitch(note);
        const strumOffset = this._strumOffsetSec(note, chNotes, chSpb);
        const when = base + noteOffsetInMeasure + strumOffset;
        const perfDur = this._perfDurationSec(note, chSpb);
        const expr = perfDur == null
          ? this._expressionForNote(note, Math.max(0.04, note.duration * chSpb - 0.025))
          : { duration: perfDur, velocityScale: 1 };
        const nextSame = this._nextSamePitchOffsetSec(
          note, chNotes, chMeasureOnset, chSpb, playbackPitch, noteOffsetInMeasure);
        // Drums (channel 9) restrike the same GM key constantly (hi-hat, snare);
        // trimming there would choke the kit, so cap only melodic channels.
        const dur = ch.percussion
          ? expr.duration
          : this._capSamePitchDuration(expr.duration, when, base, nextSame);
        // ch.gain is applied as CC7 channel volume (see _loadChannelInstrument);
        // velocity carries only dynamics × expression so it is not double-counted.
        const perfVel = this._perfVelocity(note);
        const velocity = perfVel != null
          ? perfVel
          : this._clampVelocity(this._dynamicToVelocity(note.dynamic) * expr.velocityScale);
        const pitchChannel = pitchChannelFor(note, chNotes, when, dur);
        const playChannel = Number.isInteger(pitchChannel) ? pitchChannel : ch.midiChannel;
        if (Number.isInteger(pitchChannel)) {
          if (!this._schedulePitchAutomationPerf(pitchChannel, note, when, chSpb)) {
            this._schedulePitchAutomation(pitchChannel, note, chNotes, when, dur);
          }
        }
        for (const attack of this._noteAttacks(note, when, dur, chSpb)) {
          this._spessa.noteOn(playChannel, playbackPitch, velocity, { time: attack.when });
          this._spessa.noteOff(playChannel, playbackPitch, false, { time: attack.when + attack.duration });
        }
      }
      return;
    }

    for (const note of chNotes) {
      const noteOffsetInMeasure = (note.onset - chMeasureOnset) * chSpb;
      if (noteOffsetInMeasure < skipBeforeMeasureSec) continue;
      const playbackPitch = this._playbackPitch(note);
      const strumOffset = this._strumOffsetSec(note, chNotes, chSpb);
      const when = base + noteOffsetInMeasure + strumOffset;
      const perfDur = this._perfDurationSec(note, chSpb);
      const expr = perfDur == null
        ? this._expressionForNote(note, Math.max(0.04, note.duration * chSpb - 0.025))
        : { duration: perfDur, velocityScale: 1 };
      const perfVel = this._perfVelocity(note);
      const gain = perfVel != null
        ? Math.min(1, (perfVel / 127) * ch.gain)
        : Math.min(1, (this._dynamicToVelocity(note.dynamic) / 127) * ch.gain * expr.velocityScale);
      for (const attack of this._noteAttacks(note, when, expr.duration, chSpb)) {
        ch.synth.play(playbackPitch, attack.when, { duration: attack.duration, gain });
      }
    }
  }

  /** Original oscillator-based note scheduler (fallback).
   *  @param {number} measureIdx
   *  @param {number} absStart — AudioContext time of the measure's first beat */
  _scheduleMeasureNotesOscillator(measureIdx, absStart) {
    if (!this._audioCtx || !this.audioEnabled) return;
    const notes = this.renderer.measures[measureIdx];
    if (!notes || !notes.length) return;

    const base = Number.isFinite(absStart) ? absStart : this._audioCtx.currentTime;
    const measureOnset = this._measureOnsetBeats(measureIdx);
    const secPerBeat = this._measureSecPerBeat(measureIdx);

    for (const note of notes) {
      const beatInMeasure = note.onset - measureOnset;
      const playbackPitch = this._playbackPitch(note);
      const strumOffset = this._strumOffsetSec(note, notes, secPerBeat);
      const when = base + beatInMeasure * secPerBeat + strumOffset;
      const expr = this._expressionForNote(note, note.duration * secPerBeat);
      const pitchSamples = this._pitchSamplesForNote(note, notes, when, expr.duration);
      for (const attack of this._noteAttacks(note, when, expr.duration, secPerBeat)) {
        this._scheduleNote(playbackPitch, attack.when, attack.duration, pitchSamples);
      }
    }
  }

  /**
   * Synthesize a plucked-string guitar note using additive synthesis.
   * Multiple sine harmonics with individual decay rates approximate
   * the bright attack and natural decay of a plucked guitar string.
   */
  _scheduleNote(pitch, startTime, durationSec, pitchSamples = []) {
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
      const relevantPitchSamples = pitchSamples
        .filter(sample => sample.time >= startTime - 0.001 && sample.time <= decayEnd + 0.001)
        .sort((a, b) => a.time - b.time);
      if (relevantPitchSamples.length) {
        const firstSemi = relevantPitchSamples[0].semitones || 0;
        osc.frequency.setValueAtTime(harmFreq * Math.pow(2, firstSemi / 12), startTime);
        for (const sample of relevantPitchSamples) {
          const nextFreq = harmFreq * Math.pow(2, (sample.semitones || 0) / 12);
          osc.frequency.linearRampToValueAtTime(nextFreq, Math.max(startTime, sample.time));
        }
      }

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

