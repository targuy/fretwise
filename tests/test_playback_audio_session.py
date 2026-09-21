"""Exercise real browser audio lifecycle with deterministic Node Web Audio doubles.

The production module is evaluated unchanged. Only browser boundaries and the
dynamically imported synthesizer are replaced; no soundfont or network is used.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => {resolve = yes; reject = no;});
  return {promise, resolve, reject};
};
const flush = async () => {for (let i = 0; i < 4; ++i) await new Promise(setImmediate);};
const until = async predicate => {
  for (let i = 0; i < 30; ++i) {
    if (predicate()) return;
    await flush();
  }
  assert.fail('Expected audio stage was never reached');
};
function eventTarget() {
  const listeners = [];
  return {
    listeners,
    addEventListener(type, fn, options) {listeners.push({type, fn, options});},
    removeEventListener(type, fn, options) {
      const capture = value => value === true || !!value?.capture;
      const i = listeners.findIndex(x => x.type === type && x.fn === fn
        && capture(x.options) === capture(options));
      if (i >= 0) listeners.splice(i, 1);
    },
  };
}
async function harness() {
  const h = {contexts: [], synths: [], requests: [], statuses: [], timers: new Map(),
    moduleLoads: [], responses: [], fallbackCalls: [], logs: [], nextTimer: 1};
  h.response = (url = '/api/soundfont?name=bank-a.sf2&v=1', options = {}) => {
    const bytes = options.bytes || new Uint8Array([1, 2, 3, 4]).buffer;
    const response = {
      ok: options.ok !== false, status: options.status || 200, url,
      reads: 0, cancels: 0,
      headers: {get: () => null},
      body: {
        locked: false,
        cancel: async () => {response.cancels++;},
        getReader() {
          this.locked = true;
          let done = false;
          return {
            read: async () => {
              response.reads++;
              if (done) return {done: true};
              done = true;
              const buffer = await (options.body || Promise.resolve(bytes));
              return {done: false, value: new Uint8Array(buffer)};
            },
            cancel: async () => {response.cancels++;},
            releaseLock: () => {response.body.locked = false;},
          };
        },
      },
      arrayBuffer: () => {response.reads++; return options.body || Promise.resolve(bytes);},
    };
    return response;
  };
  h.fetch = async (url, options = {}) => {
    h.requests.push({url, options});
    const response = h.responses.length ? h.responses.shift() : h.response();
    return await response;
  };
  class AudioContext {
    constructor() {
      this.currentTime = 0; this.state = 'running'; this.destination = {context: this};
      this.closeCalls = 0; this.resumeCalls = 0; this.gains = [];
      this.audioWorklet = {addModule: async path => {h.moduleLoads.push(path);}};
      h.contexts.push(this);
    }
    createGain() {
      const gain = {context: this,
        gain: {value: 1, setTargetAtTime(value) {this.value = value;}}, disconnectCalls: 0,
        connect() {}, disconnect() {this.disconnectCalls++;}};
      this.gains.push(gain); return gain;
    }
    resume() {this.resumeCalls++; this.state = 'running'; return Promise.resolve();}
    close() {this.closeCalls++; this.state = 'closed'; return Promise.resolve();}
  }
  class Synthetizer {
    constructor(destination, bytes) {
      this.destination = destination; this.bytes = bytes;
      this.ready = deferred(); this.isReady = this.ready.promise;
      this.presetList = Array.from({length: 128}, (_, program) => ({program, bank: 0}));
      this.programs = []; this.stopCalls = 0; this.destroyCalls = 0;
      this.disconnectCalls = 0;
      this.eventHandler = {
        events: new Map(),
        addEvent(type, key, handler) {this.events.set(`${type}:${key}`, handler);},
        removeEvent(type, key) {this.events.delete(`${type}:${key}`);},
        emit(type, value) {
          for (const [key, handler] of this.events) {
            if (key.startsWith(`${type}:`)) handler(value);
          }
        },
      };
      this.worklet = {disconnect: () => {this.disconnectCalls++;},
        port: {close() {}, postMessage() {}}};
      h.synths.push(this);
    }
    programChange(channel, program) {this.programs.push([channel, program]);}
    controllerChange() {}
    pitchWheel() {}
    stopAll() {this.stopCalls++;}
    destroy() {this.destroyCalls++; this.disconnectCalls++;}
    disconnect() {this.disconnectCalls++;}
  }
  const document = Object.assign(eventTarget(), {hidden: false,
    getElementById: () => null, querySelector: () => null,
    createElement: () => ({remove() {}}),
    head: {appendChild: node => queueMicrotask(() => node.onerror?.())}});
  const window = Object.assign(eventTarget(), {AudioContext, Soundfont: {
    instrument: async (...args) => {
      h.fallbackCalls.push(args);
      if (h.fallback) return await h.fallback(...args);
      throw new Error('Fallback unavailable in this test');
    },
  }});
  const timer = (fn, delay, interval = false) => {
    const id = h.nextTimer++; h.timers.set(id, {fn, delay, interval}); return id;
  };
  h.fire = delay => {
    const pending = [...h.timers].filter(([, task]) => task.delay === delay && !task.interval);
    assert.ok(pending.length, `No pending timeout at ${delay}ms`);
    for (const [id, task] of pending) {h.timers.delete(id); task.fn();}
  };
  const context = vm.createContext({document, window, AbortController, DOMException,
    performance: {now: () => 1000}, fetch: (...args) => h.fetch(...args),
    console: Object.fromEntries(['log', 'warn', 'error'].map(level =>
      [level, (...args) => h.logs.push([level, ...args])])),
    setTimeout: (fn, delay) => timer(fn, delay), clearTimeout: id => h.timers.delete(id),
    setInterval: (fn, delay) => timer(fn, delay, true),
    clearInterval: id => h.timers.delete(id),
    requestAnimationFrame: fn => timer(fn, 16), cancelAnimationFrame: id => h.timers.delete(id),
  });
  const vendor = new vm.SyntheticModule(['Synthetizer'], function () {
    this.setExport('Synthetizer', Synthetizer);
  }, {context});
  await vendor.link(() => {throw new Error('Unexpected vendor import');});
  await vendor.evaluate();
  const module = new vm.SourceTextModule(fs.readFileSync(process.argv[1], 'utf8'), {
    context, identifier: 'playback.js', importModuleDynamically: async specifier => {
      assert.equal(specifier, '/static/js/vendor/spessasynth.esm.js');
      return vendor;
    },
  });
  await module.link(() => {throw new Error('Unexpected static import');});
  await module.evaluate();
  h.renderer = (tempo = 120) => ({tempo, bpm: 4, cursorMeasure: 0,
    measureNumbers: [1, 2], measures: [[], []], render() {}, scrollToCursor() {}});
  h.engine = new module.namespace.PlaybackEngine(h.renderer());
  h.cache = module.namespace.SF2_BUFFER_CACHE;
  h.engine.onSynthStatusChange = status => h.statuses.push(status);
  h.document = document; h.window = window;
  h.start = async () => {
    h.engine.enableAudio();
    const promise = h.engine._initSynth();
    try {await until(() => h.synths.length === 1);}
    catch (error) {error.message += '\nAudio log: ' + JSON.stringify(h.logs); throw error;}
    return {promise, synth: h.synths[0]};
  };
  return h;
}
(async () => {
"""


def _run(scenario: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for audio lifecycle regressions")
    source = Path(__file__).parents[1] / "src/fretwise/web/static/js/playback.js"
    script = _HARNESS + scenario + r"""
})().then(() => console.log('AUDIO_SESSION_OK'))
  .catch(error => {console.error(error.stack); process.exitCode = 1;});
"""
    result = subprocess.run(
        [node, "--experimental-vm-modules", "-e", script, str(source)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "AUDIO_SESSION_OK" in result.stdout, "Audio scenario left unresolved: " + result.stderr


def test_loading_tracks_share_one_initialization_and_apply_latest_program() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  p.setInstrument('Bass'); p.setMidiProgram(33);
  assert.strictEqual(p._initSynth(), promise);
  p.rebind(h.renderer(90));
  p.setInstrument('Piano'); p.setMidiProgram(0);
  assert.strictEqual(p._initSynth(), promise);
  await flush();
  assert.equal(h.contexts.length, 1);
  assert.equal(h.moduleLoads.length, 1);
  assert.equal(h.requests.length, 1);
  assert.equal(h.synths.length, 1);
  assert.deepEqual(h.statuses, ['loading']);
  synth.ready.resolve(); await promise;
  assert.strictEqual(p._spessa, synth);
  assert.deepEqual(synth.programs.filter(([channel]) => channel === 0).at(-1), [0, 0]);
  assert.deepEqual(h.statuses, ['loading', 'ready']);
  assert.equal(p._synthLoading, false);
  await p.destroy();
""")


def test_prepare_audio_for_playback_waits_for_soundfont_readiness() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const ready = p.prepareAudioForPlayback();
  await until(() => h.synths.length === 1);
  assert.equal(p.isPlaying, false);
  let settled = false;
  ready.then(() => { settled = true; });
  await flush();
  assert.equal(settled, false);
  h.synths[0].ready.resolve();
  assert.equal(await ready, true);
  assert.strictEqual(p._spessa, h.synths[0]);
  assert.equal(p.isPlaying, false);
  await p.destroy();
""")


def test_soundfont_parse_error_exits_wait_and_uses_existing_fallback() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  synth.eventHandler.emit('soundfonterror', 'unsupported soundfont data');
  await promise; await flush();
  assert.equal(p._spessa, null);
  assert.equal(p._synthLoading, false);
  assert.deepEqual(h.statuses, ['loading', 'error']);
  assert.equal(h.fallbackCalls.length, 1);
  await p.destroy();
""")


def test_library_and_new_song_reuse_ready_context_and_decoded_soundfont() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  synth.ready.resolve(); await promise;
  const ctx = p._audioCtx, gain = p._masterGain;
  p.setVolume(.42); p.speed = .5; p.loopStart = 1; p.loopEnd = 2;
  p._secondaryChannels.push({trackId: 7, synth: 'spessa', midiChannel: 2});
  p.detachRenderer();
  assert.equal(p.renderer, null);
  assert.equal(p._secondaryChannels.length, 0);
  assert.strictEqual(p._spessa, synth);
  assert.equal(ctx.closeCalls, 0);
  const next = h.renderer(80);
  p.rebind(next); p.setInstrument('Bass'); p.setMidiProgram(34); p.enableAudio();
  await p._initSynth();
  assert.strictEqual(p.renderer, next);
  assert.strictEqual(p._audioCtx, ctx);
  assert.strictEqual(p._masterGain, gain);
  assert.strictEqual(p._spessa, synth);
  assert.equal(p.tempo, 80); assert.equal(p.speed, 1);
  assert.equal(p.loopStart, -1); assert.equal(p.loopEnd, -1);
  assert.equal(p._volume, .42);
  assert.equal(h.synths.length, 1); assert.equal(h.requests.length, 1);
  assert.deepEqual(h.statuses, ['loading', 'ready']);
  assert.deepEqual(synth.programs.at(-1), [0, 34]);
  await p.destroy();
""")


@pytest.mark.parametrize("ready", [False, True], ids=["pending", "ready"])
def test_destroy_releases_audio_listeners_timers_and_blocks_late_publish(ready: bool) -> None:
    _run(f"const finishBeforeDestroy = {str(ready).lower()};" + r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  if (finishBeforeDestroy) {synth.ready.resolve(); await promise;}
  assert.ok(h.document.listeners.length + h.window.listeners.length >= 4);
  const ctx = p._audioCtx, statuses = [...h.statuses];
  await p.destroy(); await p.destroy();
  synth.ready.resolve(); await promise; await flush();
  assert.equal(ctx.closeCalls, 1);
  assert.equal(h.document.listeners.length, 0);
  assert.equal(h.window.listeners.length, 0);
  assert.equal(h.timers.size, 0);
  assert.ok(synth.destroyCalls > 0 || synth.disconnectCalls > 0);
  assert.equal(p._spessa, null);
  assert.equal(p._synth, null);
  assert.deepEqual(h.statuses, statuses);
  p.enableAudio(); await p._initSynth();
  p.play(); p.toggleMetronome();
  assert.equal(h.contexts.length, 1);
  assert.equal(h.requests.length, 1);
  assert.equal(h.timers.size, 0);
""")


@pytest.mark.parametrize("failure", ["rejection", "timeout"])
def test_decode_failure_never_reports_ready_or_publishes_half_built_synth(failure: str) -> None:
    _run(f"const failure = '{failure}';" + r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  if (failure === 'rejection') synth.ready.reject(new Error('Invalid soundfont'));
  else h.fire(15000);
  await promise; await flush();
  assert.equal(p._spessa, null);
  assert.equal(p._synth, null);
  assert.equal(p._synthLoading, false);
  assert.deepEqual(h.statuses, ['loading', 'error']);
  assert.equal(h.fallbackCalls.length, 1);
  assert.ok(synth.destroyCalls > 0 || synth.disconnectCalls > 0);
  synth.ready.resolve(); await flush();
  assert.equal(p._spessa, null);
  assert.deepEqual(h.statuses, ['loading', 'error']);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


@pytest.mark.parametrize("stage", ["headers", "body"])
def test_soundfont_fetch_and_body_have_real_timeout_and_ignore_late_response(stage: str) -> None:
    _run(f"const stage = '{stage}';" + r"""
  const h = await harness(), p = h.engine, pending = deferred();
  const response = h.response('/api/soundfont?name=slow.sf2&v=1',
    stage === 'body' ? {body: pending.promise} : {});
  h.responses.push(stage === 'headers' ? pending.promise : response);
  p.enableAudio(); const promise = p._initSynth();
  await until(() => stage === 'headers' ? h.requests.length : response.reads);
  h.fire(180000); await promise; await flush();
  assert.equal(h.synths.length, 0);
  assert.deepEqual(h.statuses, ['loading', 'error']);
  assert.equal(h.requests[0].options.signal.aborted, true);
  pending.resolve(stage === 'headers' ? response : new ArrayBuffer(8));
  await flush();
  assert.equal(h.cache.size, 0);
  assert.equal(h.synths.length, 0);
  assert.deepEqual(h.statuses, ['loading', 'error']);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


def test_cached_bank_cancels_unused_response_body() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const bytes = new Uint8Array([5, 6, 7]).buffer;
  const response = h.response();
  h.cache.set(response.url, bytes); h.responses.push(response);
  const {promise, synth} = await h.start();
  synth.ready.resolve(); await promise;
  assert.strictEqual(synth.bytes, bytes);
  assert.equal(response.reads, 0);
  assert.equal(response.cancels, 1);
  await p.destroy();
""")


def test_reload_bank_invalidates_old_decode_without_replacing_audio_context() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const {promise: oldPromise, synth: oldSynth} = await h.start();
  const ctx = p._audioCtx;
  const bytes = new Uint8Array([9, 8, 7]).buffer;
  const response = h.response('/api/soundfont?name=bank-b.sf2&v=2', {bytes});
  h.responses.push(response);
  const newPromise = p.reloadSoundfont();
  await until(() => h.synths.length === 2);
  const newSynth = h.synths[1];
  newSynth.ready.resolve(); await newPromise;
  oldSynth.ready.resolve(); await oldPromise; await flush();
  assert.strictEqual(p._audioCtx, ctx);
  assert.equal(h.contexts.length, 1);
  assert.equal(ctx.closeCalls, 0);
  assert.strictEqual(p._spessa, newSynth);
  assert.deepEqual([...new Uint8Array(newSynth.bytes)], [...new Uint8Array(bytes)]);
  assert.equal(p._lastSf2Url, response.url);
  assert.ok(oldSynth.destroyCalls > 0 || oldSynth.disconnectCalls > 0);
  assert.equal(h.cache.size, 1);
  assert.ok(h.cache.has(response.url));
  assert.equal(h.statuses.filter(status => status === 'ready').length, 1);
  assert.equal(h.statuses.filter(status => status === 'error').length, 0);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


def test_reload_does_not_publish_a_late_fallback_from_previous_bank() -> None:
    _run(r"""
  const h = await harness(), p = h.engine, fallback = deferred();
  h.fallback = () => fallback.promise;
  const {promise: oldPromise, synth: oldSynth} = await h.start();
  oldSynth.ready.reject(new Error('Invalid old bank'));
  await until(() => h.fallbackCalls.length === 1);
  h.responses.push(h.response('/api/soundfont?name=bank-b.sf2&v=2'));
  const newPromise = p.reloadSoundfont();
  await until(() => h.synths.length === 2);
  h.synths[1].ready.resolve(); await newPromise;
  const player = {stopCalls: 0, playCalls: 0,
    stop() {this.stopCalls++;}, play() {this.playCalls++;}};
  fallback.resolve(player); await oldPromise; await flush();
  assert.strictEqual(p._spessa, h.synths[1]);
  assert.equal(p._synth, 'spessa');
  assert.ok(player.stopCalls > 0);
  assert.equal(player.playCalls, 0);
  assert.equal(h.statuses.filter(status => status === 'ready').length, 1);
  await p.destroy();
""")


def test_fallback_finishes_with_latest_instrument_after_track_change() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const first = deferred(), second = deferred();
  h.fallback = () => h.fallbackCalls.length === 1 ? first.promise : second.promise;
  const {promise, synth} = await h.start();
  synth.ready.reject(new Error('Invalid soundfont'));
  await until(() => h.fallbackCalls.length === 1);
  p.setInstrument('Bass'); p.setMidiProgram(33);
  assert.strictEqual(p._initSynth(), promise);
  const oldPlayer = {stops: 0, stop() {this.stops++;}};
  const currentPlayer = {stop() {}};
  first.resolve(oldPlayer);
  await until(() => h.fallbackCalls.length === 2);
  assert.notEqual(h.fallbackCalls[0][1], h.fallbackCalls[1][1]);
  assert.equal(h.fallbackCalls[1][1], p._instrumentName);
  assert.ok(oldPlayer.stops > 0);
  assert.equal(p._synth, null);
  assert.deepEqual(h.statuses, ['loading']);
  second.resolve(currentPlayer); await promise;
  assert.strictEqual(p._synth, currentPlayer);
  assert.deepEqual(h.statuses, ['loading', 'ready']);
  assert.equal(h.requests.length, 1);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


def test_secondary_fallback_finishing_after_track_removal_is_stopped() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const primary = {stop() {}}, pending = deferred();
  h.fallback = () => h.fallbackCalls.length === 1 ? primary : pending.promise;
  const {promise, synth} = await h.start();
  synth.ready.reject(new Error('Invalid soundfont')); await promise;
  p.addSecondaryChannel(7, 'Bass', [], 4, 33, 'bass');
  await until(() => h.fallbackCalls.length === 2);
  const removedChannel = p._secondaryChannels[0];
  p.removeSecondaryChannel(7);
  const latePlayer = {stops: 0, stop() {this.stops++;}};
  pending.resolve(latePlayer); await flush();
  assert.equal(p._secondaryChannels.length, 0);
  assert.equal(removedChannel.synth, null);
  assert.ok(latePlayer.stops > 0);
  assert.strictEqual(p._synth, primary);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


def test_reload_during_fallback_script_load_starts_fresh_loader() -> None:
    _run(r"""
  const h = await harness(), p = h.engine, scripts = [];
  const soundfont = h.window.Soundfont;
  h.fallback = () => ({stop() {}});
  delete h.window.Soundfont;
  h.document.head.appendChild = script => scripts.push(script);
  const {promise: oldPromise, synth: oldSynth} = await h.start();
  oldSynth.ready.reject(new Error('Old bank failed'));
  await until(() => scripts.length === 1);
  h.responses.push(h.response('/api/soundfont?name=bank-b.sf2&v=2'));
  const newPromise = p.reloadSoundfont();
  await until(() => h.synths.length === 2);
  h.synths[1].ready.reject(new Error('New bank failed'));
  await until(() => scripts.length === 2);
  assert.equal(scripts[0].onload, null);
  h.window.Soundfont = soundfont;
  scripts[1].onload();
  await newPromise; await oldPromise;
  assert.equal(h.fallbackCalls.length, 1);
  assert.equal(h.statuses.filter(status => status === 'ready').length, 1);
  assert.equal(h.statuses.filter(status => status === 'error').length, 0);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")


def test_library_during_decode_keeps_load_but_detaches_old_song_callbacks() -> None:
    _run(r"""
  const h = await harness(), p = h.engine;
  const {promise, synth} = await h.start();
  const ctx = p._audioCtx;
  p.detachRenderer();
  p.play(); p.toggleMetronome(); p.enableAudio();
  assert.equal(p.renderer, null);
  assert.equal(p.isPlaying, false);
  assert.equal(p.audioEnabled, false);
  assert.equal(p.metronome, false);
  synth.ready.resolve(); await promise;
  assert.strictEqual(p._spessa, synth);
  assert.deepEqual(h.statuses, ['loading']);
  assert.equal(h.contexts.length, 1);
  p.rebind(h.renderer(100)); p.enableAudio(); await p._initSynth();
  assert.strictEqual(p._audioCtx, ctx);
  assert.strictEqual(p._spessa, synth);
  assert.equal(h.synths.length, 1);
  assert.equal(h.requests.length, 1);
  await p.destroy();
  assert.equal(h.timers.size, 0);
""")
