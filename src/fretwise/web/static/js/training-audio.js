/**
 * training-audio.js — one-shot SpessaSynth preview player for the training
 * module (hear the current scale run / chord voicing).
 *
 * Deliberately NOT PlaybackEngine: that class is built around a loaded score
 * (measure timeline, multi-track mixing, tempo automation) — dead weight for
 * "play these N pitches once". This is a lazily-initialized Synthetizer that
 * schedules a flat list of noteOn/noteOff calls.
 *
 * Loads the SAME soundfont bank as the main viewer (/api/soundfont — whatever
 * the user configured in Settings), via playback.js's shared ArrayBuffer
 * cache, so a user who already opened a song does not re-download a file that
 * can run to hundreds of MB.
 */

import { SF2_BUFFER_CACHE } from './playback.js';

const DEFAULT_PROGRAM = 25; // GM acoustic steel guitar — matches PlaybackEngine's default

let _ctx = null;
let _spessa = null;
let _presets = [];
let _initPromise = null;
let _activeProgram = null;

/**
 * Resolve a desired GM program to one the loaded bank actually has. Mirrors
 * PlaybackEngine._resolveProgram: a non-GM bank (single-instrument pack,
 * game/arcade soundfont) usually lacks program 25, and SpessaSynth silently
 * falls back to preset 0 — often drums — without this.
 */
function _resolveProgram(desired) {
  if (!_presets.length) return desired;
  const bank0 = _presets.filter((p) => (p.bank ?? 0) === 0);
  const pool = bank0.length ? bank0 : _presets;
  if (pool.some((p) => p.program === desired)) return desired;
  const famStart = Math.floor(Math.max(0, Math.min(127, desired)) / 8) * 8;
  const sameFamily = pool.find((p) => p.program >= famStart && p.program <= famStart + 7);
  if (sameFamily) return sameFamily.program;
  const guitar = pool.find((p) => /guitar|gtr/i.test(p.presetName || p.name || ''));
  return (guitar || pool[0]).program;
}

async function _ensureSynth() {
  if (_spessa) return _spessa;
  if (_initPromise) return _initPromise;
  // AudioContext must be created synchronously within the click handler that
  // triggered this (autoplay policy) — this function's first line runs
  // synchronously before any `await`, so that holds as long as callers invoke
  // it directly from a click listener, not from a deferred callback.
  _initPromise = (async () => {
    _ctx = new (window.AudioContext || window.webkitAudioContext)();
    const { Synthetizer } = await import('/static/js/vendor/spessasynth.esm.js');
    await _ctx.audioWorklet.addModule('/static/js/vendor/synthetizer/worklet_processor.min.js');

    const resp = await fetch('/api/soundfont');
    if (!resp.ok) throw new Error(`SF2 fetch: HTTP ${resp.status}`);
    let buf = SF2_BUFFER_CACHE.get(resp.url);
    if (!buf) {
      buf = await resp.arrayBuffer();
      SF2_BUFFER_CACHE.clear();  // keep at most one bank in memory
      SF2_BUFFER_CACHE.set(resp.url, buf);
    }

    const spessa = new Synthetizer(_ctx.destination, buf);
    const readyCapMs = Math.min(180000, Math.max(8000, (buf.byteLength / 1024) * 0.5));
    try {
      await Promise.race([spessa.isReady, new Promise((r) => setTimeout(r, readyCapMs))]);
    } catch (_) { /* proceed with whatever presets exist */ }
    _presets = Array.isArray(spessa.presetList) ? spessa.presetList.slice() : [];
    _spessa = spessa;
    console.log(`[FretWise] training preview synth ready — ${_presets.length} presets`);
    return spessa;
  })();
  return _initPromise;
}

function _setProgram(program) {
  if (!_spessa || _activeProgram === program) return;
  _activeProgram = program;
  _spessa.programChange(0, _resolveProgram(program));
}

/** Cut everything currently sounding — call before a new preview and on page exit. */
export function stopAudioPreview() {
  if (_spessa) { try { _spessa.stopAll(); } catch (_) { /* ignore */ } }
}

/**
 * Play an ascending run of MIDI pitches, one after another.
 * @param {number[]} midiPitches — sounding pitches, played in the given order
 * @param {object} [opts]
 * @param {number} [opts.gapMs=150] — time between note onsets
 * @param {number} [opts.durMs=280] — how long each note rings
 * @param {number} [opts.program] — GM program (defaults to acoustic steel guitar)
 * @returns {Promise<void>} resolves once the synth is ready and notes are scheduled
 *   (not once they finish sounding — this is fire-and-forget playback)
 */
export async function playScaleRun(midiPitches, opts = {}) {
  if (!midiPitches.length) return;
  const gapMs = opts.gapMs ?? 150;
  const durMs = opts.durMs ?? 280;
  const spessa = await _ensureSynth();
  if (_ctx.state === 'suspended') await _ctx.resume();
  stopAudioPreview();
  _setProgram(opts.program ?? DEFAULT_PROGRAM);
  const t0 = _ctx.currentTime + 0.05;
  midiPitches.forEach((pitch, i) => {
    const when = t0 + (i * gapMs) / 1000;
    spessa.noteOn(0, pitch, 100, { time: when });
    spessa.noteOff(0, pitch, false, { time: when + durMs / 1000 });
  });
}

/**
 * Play a set of MIDI pitches as a strummed chord.
 * @param {number[]} midiPitches — low to high (strum order)
 * @param {object} [opts]
 * @param {number} [opts.strumMs=16] — stagger between adjacent strings
 * @param {number} [opts.durMs=1600] — ring time
 * @param {number} [opts.program]
 * @returns {Promise<void>}
 */
export async function playChordStrum(midiPitches, opts = {}) {
  if (!midiPitches.length) return;
  const strumMs = opts.strumMs ?? 16;
  const durMs = opts.durMs ?? 1600;
  const spessa = await _ensureSynth();
  if (_ctx.state === 'suspended') await _ctx.resume();
  stopAudioPreview();
  _setProgram(opts.program ?? DEFAULT_PROGRAM);
  const t0 = _ctx.currentTime + 0.05;
  midiPitches.forEach((pitch, i) => {
    const when = t0 + (i * strumMs) / 1000;
    spessa.noteOn(0, pitch, 105, { time: when });
    spessa.noteOff(0, pitch, false, { time: when + durMs / 1000 });
  });
}
