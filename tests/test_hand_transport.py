"""Executable transport/clock regressions without WebGL or audio hardware."""

import shutil
import subprocess
from pathlib import Path

import pytest


def test_transport_and_playback_keep_nominal_time_and_reject_stale_messages() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for browser transport contract")
    script = r"""
const fs = require('fs');
const assert = require('assert/strict');
async function moduleAt(path) {
  return import('data:text/javascript;base64,' + fs.readFileSync(path).toString('base64'));
}
(async () => {
  const {HandTransportReceiver} = await moduleAt(process.argv[1]);
  const source = {};
  const receiver = new HandTransportReceiver('https://fretwise.test', source);
  const base = {protocolVersion:1,sessionId:'s',planId:'p',sequence:1};
  const event = data => ({origin:'https://fretwise.test',source,data});
  const load = {...base,type:'fretwise:load',payload:{frames:[]}};
  assert.equal(receiver.accept({...event(load),origin:'https://evil.test'}), null);
  assert.equal(receiver.accept({...event(load),source:{}}), null);
  assert.ok(receiver.accept(event(load)));
  const play = {...base,type:'fretwise:transport',sequence:2,status:'playing',
    nominalScoreSec:3,rate:1.5,anchorEpochMs:1000,discontinuityId:0};
  assert.ok(receiver.accept(event(play)));
  assert.equal(receiver.timeAt(1100),3.15);
  assert.equal(receiver.timeAt(999999),3.375);
  assert.equal(receiver.isDesynced(1100),false);
  assert.equal(receiver.isDesynced(1300),true);
  assert.equal(receiver.accept(event({...play,planId:'old',sequence:3})),null);
  assert.equal(receiver.accept(event(play)),null);
  assert.ok(receiver.accept(event({...play,sequence:3,status:'paused',nominalScoreSec:3.1})));
  assert.equal(receiver.timeAt(50000),3.1);
  assert.equal(receiver.isDesynced(50000),false);
  assert.ok(receiver.accept(event({...play,sequence:4,nominalScoreSec:0.5,discontinuityId:1})));
  assert.equal(receiver.accept(event({...play,sequence:5,discontinuityId:0})),null);
  const {PlaybackEngine} = await moduleAt(process.argv[2]);
  const renderer = {tempo:120,bpm:4,cursorMeasure:0,measureNumbers:[1,2],
    measures:[[],[]],render(){}};
  const p = new PlaybackEngine(renderer,{measureBeats:[4,4],measureTempos:[120,60]});
  p._audioCtx = {currentTime:10.375,state:'running'};
  p.audioEnabled = true;
  p._audioAnchorSongSec = 0;
  p._audioAnchorTime = 10;
  p._startTime = performance.now()-9000;
  p.isPlaying = true;
  assert.equal(p.getCurrentTimeSec(),0.375); // audio owns time, not perf.now
  p.pause();
  assert.equal(p.getCurrentTimeSec(),0.375); // pause must not snap to bar
  p.setSpeed(1.5);
  assert.equal(p.getNominalTimeSec(),0.375);
  assert.equal(p.songSecForOnsetBeats(6)*p.speed,4);
  p.goToMeasure(1);
  assert.equal(p.getNominalTimeSec(),2);
  p.stop();
  assert.equal(p.getNominalTimeSec(),0);
  renderer.data = {hand_performance:{ppq:960,tempoMap:[
    {tick:0,usPerQuarter:500000},{tick:1920,usPerQuarter:1000000}]}};
  p.setSpeed(1);
  assert.equal(p.songSecForOnsetBeats(4),3);
  assert.equal(p._noteOffsetSec(3,0),2);
  assert.equal(p._perfDurationSec({onset:1,perf:{dur_beats:2}},0.5),1.5);
  assert.equal(p._measureStartSec(1),3);
})().catch(e=>{console.error(e.name + ': ' + e.message);process.exit(1);});
"""
    static = Path(__file__).parents[1] / "src/fretwise/web/static/js"
    completed = subprocess.run(
        [node, "-e", script, str(static / "hand_transport.js"), str(static / "playback.js")],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
    )
    assert completed.returncode == 0, completed.stderr
