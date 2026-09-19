"""Clock-authority switches must not rewind a playing score or replay attacks."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


def test_clock_switches_preserve_song_position_and_scheduler_context() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for playback clock regressions")
    script = r"""
const fs = require('fs');
const assert = require('assert/strict');
(async () => {
  const {PlaybackEngine} = await import('data:text/javascript;base64,'
    + fs.readFileSync(process.argv[1]).toString('base64'));
  let wall = 10000;
  globalThis.performance = {now: () => wall};
  class AudioContext {
    constructor() {this.currentTime = 0; this.state = 'running'; this.destination = {};}
    createGain() {return {gain:{value:1}, connect(){}};}
    resume() {this.state = 'running'; return Promise.resolve();}
  }
  globalThis.window = {AudioContext};
  const renderer = () => ({tempo:120,bpm:4,cursorMeasure:5,
    measureNumbers:Array.from({length:20},(_,i)=>i+1),
    measures:Array.from({length:20},()=>[]),render(){}});
  const running = () => {
    const p = new PlaybackEngine(renderer());
    p._startTime = 0; p._startMeasure = 0; p.isPlaying = true;
    p._initSynth = async () => {};
    return p;
  };
  let p = running();
  assert.equal(p.getCurrentTimeSec(),10);
  p.toggleMetronome();
  assert.equal(p.getCurrentTimeSec(),10);
  assert.equal(p._schedulerMeasure,5);
  assert.equal(p._skipMeasure,5);
  p._audioCtx.currentTime = .375;
  wall = 20000; // a delayed UI frame must not advance the audio authority
  assert.equal(p.getCurrentTimeSec(),10.375);
  p.toggleMetronome();
  assert.equal(p.getCurrentTimeSec(),10.375);
  wall += 250;
  assert.equal(p.getCurrentTimeSec(),10.625);

  wall = 10375;
  p = running();
  p.enableAudio();
  assert.equal(p.getCurrentTimeSec(),10.375);
  assert.equal(p._schedulerMeasure,5);
  assert.equal(p._firstScheduleSkipSec,.375);
  p._audioCtx.currentTime = .5;
  wall = 40000;
  p.disableAudio();
  assert.equal(p.getCurrentTimeSec(),10.875);
  wall += 250;
  assert.equal(p.getCurrentTimeSec(),11.125);

  // Adding a metronome to already playing audio must not reset queued notes.
  p = running();
  p.enableAudio();
  p._schedulerMeasure = 17;
  p._audioCtx.currentTime = .125;
  const before = p.getCurrentTimeSec();
  p.toggleMetronome();
  assert.equal(p.getCurrentTimeSec(),before);
  assert.equal(p._schedulerMeasure,17);

  // A first query on a track beginning after initial rests uses its real origin.
  const late = renderer();
  late.cursorMeasure = 0; late.measureNumbers = [5]; late.measures = [[]];
  late.data = {hand_performance:{ppq:960,tempoMap:[{tick:0,usPerQuarter:500000}]}};
  p = new PlaybackEngine(late);
  assert.equal(p.getNominalTimeSec(),8);
  assert.equal(p.getNominalTimeSec(),8);
})().catch(e=>{console.error(e.name + ': ' + e.message);process.exit(1);});
"""
    source = Path(__file__).parents[1] / "src/fretwise/web/static/js/playback.js"
    result = subprocess.run(
        [node, "-e", script, str(source)], capture_output=True, text=True,
        encoding="utf-8", timeout=30,
    )
    assert result.returncode == 0, result.stderr
