"""The real API client consumes long save responses once, without silent success."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            r"""
const expected={sidecar_saved:true,saved:'été 🎸.gp'};
const bytes=new TextEncoder().encode(JSON.stringify({type:'started'})+'\r\n'
  + Array.from({length:40},()=>JSON.stringify({type:'heartbeat'})).join('\n')+'\n'
  + JSON.stringify({type:'result',result:expected}));
let cursor=0;
globalThis.fetch=async (url,options)=>{
  calls.push([url,options]);
  return new Response(new ReadableStream({pull(controller){
    if(cursor===bytes.length){controller.close();return;}
    controller.enqueue(bytes.slice(cursor,++cursor));
  }}),{headers:{'Content-Type':'application/x-ndjson'}});
};
assert.deepEqual(await fetchSaveGp('été 🎸.gp',3,{stream:true}),expected);
assert.equal(calls.length,1);
assert.equal(calls[0][0],'/api/save/gp/'+encodeURIComponent('été 🎸.gp')+'?track_id=3&stream=true');
assert.equal(calls[0][1].method,'POST');
""",
            id="utf8-byte-fragments-heartbeats-and-final-line-without-newline",
        ),
        pytest.param(
            r"""
for (const input of ['{"type":"started"}\n{"type":"heartbeat"}\n',
  '{"type":"result","result":null}\n', '{"type":"result","result":[]}\n',
  'not json\n', '{"type":"unknown"}\n', 'x'.repeat(1024*1024+1)]) {
  globalThis.fetch=async (...args)=>{calls.push(args);return new Response(input);};
  const before=calls.length;
  await assert.rejects(fetchSaveGp('song.gp',3,{stream:true}),/interrompue|invalide/);
  assert.equal(calls.length,before+1);
}
""",
            id="eof-malformed-or-missing-result-reject-without-retry",
        ),
        pytest.param(
            r"""
globalThis.fetch=async (...args)=>{calls.push(args);return new Response(
  '{"type":"started"}\n{"type":"error","error":"Écriture refusée","status":409}\n');};
await assert.rejects(fetchSaveGp('song.gp',null,{stream:true}),/Écriture refusée/);
assert.equal(calls.length,1); assert.match(calls[0][0],/\?stream=true$/);
globalThis.fetch=async (...args)=>{calls.push(args);return new Response(
  JSON.stringify({detail:'Accès refusé'}),{status:403});};
await assert.rejects(fetchSaveGp('song.gp',3,{stream:true}),/Accès refusé/);
assert.equal(calls.length,2);
""",
            id="stream-and-http-errors-preserve-message-and-single-request",
        ),
        pytest.param(
            r"""
let cancelled=0,released=0;
globalThis.fetch=async (...args)=>{calls.push(args);return {ok:true,body:{getReader(){return {
  read:async ()=>{throw new Error('Network lost');},
  cancel:async ()=>{cancelled++;},releaseLock(){released++;},
};}}};};
await assert.rejects(fetchSaveGp('song.gp',3,{stream:true}),/Network lost/);
assert.equal(calls.length,1); assert.equal(cancelled,1); assert.equal(released,1);
globalThis.fetch=async (...args)=>{calls.push(args);return {ok:true,body:null};};
await assert.rejects(fetchSaveGp('song.gp',3,{stream:true}),/interrompue/);
assert.equal(calls.length,2);
""",
            id="network-break-releases-reader-and-does-not-replay-save",
        ),
        pytest.param(
            r"""
const expected={sidecar_saved:true,annotated_notes:8};
globalThis.fetch=async (...args)=>{calls.push(args);return new Response(JSON.stringify(expected));};
assert.deepEqual(await fetchSaveGp('song.gp',3),expected);
assert.equal(calls.length,1); assert.equal(calls[0][0],'/api/save/gp/song.gp?track_id=3');
""",
            id="existing-json-save-call-compatible",
        ),
    ],
)
def test_save_gp_client_stream(case: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for API client checks")
    source = Path(__file__).parents[1] / "src/fretwise/web/static/js/api.js"
    script = r"""
const fs=require('fs');
const assert=require('assert/strict');
(async ()=>{
const {fetchSaveGp}=await import('data:text/javascript;base64,'
  +fs.readFileSync(process.argv[1]).toString('base64'));
const calls=[];
""" + case + "\n})().catch(e=>{console.error(e);process.exit(1);});"
    result = subprocess.run(
        [node, "-e", script, str(source)], capture_output=True, text=True,
        encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
