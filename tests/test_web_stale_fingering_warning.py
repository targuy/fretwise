"""Behavioral checks for the real viewer's saved-fingering warning and save flow."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

_STATIC = Path(__file__).parents[1] / "src/fretwise/web/static"

_HARNESS = r"""
const fs = require('fs');
const vm = require('vm');
const assert = require('assert/strict');
const source = fs.readFileSync(process.argv[1], 'utf8').replace(/\r\n/g,'\n');
function declaration(name, next) {
  const start = source.indexOf(name);
  assert.ok(start >= 0, name);
  const end = source.indexOf(next || '\n}\n', start);
  assert.ok(end > start, name);
  return source.slice(start, end + (next ? 0 : 3));
}
const ids = ['stale-fingering-warning', 'stale-fingering-recalculate',
  'stale-fingering-later', 'stale-fingering-message', 'stale-fingering-status'];
function element() {
  const classes = new Set();
  return {hidden:true, disabled:false, textContent:'', title:'', attrs:{}, listeners:{},
    classList:{add:v=>classes.add(v),remove:v=>classes.delete(v),
      toggle:(v,on)=>on?classes.add(v):classes.delete(v)},
    setAttribute(k,v){this.attrs[k]=v;}, removeAttribute(k){delete this.attrs[k];},
    addEventListener(k,f){this.listeners[k]=f;}};
}
const elements = Object.fromEntries(ids.map(id=>[id,element()]));
const calls = {save:[], reload:[], background:[], status:[]};
const context = vm.createContext({console:{error(){}}, Set, Map,
  document:{getElementById:id=>elements[id] || null},
  currentFile:'song.gp', currentTrackId:3, _reviewTrackName:'Guitare',
  _selectFileToken:1, _selectTrackToken:1, _solveInFlight:false,
  _bgComputeRunning:false,
  _solveCache:new Map(), _solveCacheRevision:0,
  btnInsertFingerings:element(),
  fetchSaveGp:async (...args)=>{calls.save.push(args);return {sidecar_saved:true};},
  selectTrack:async (...args)=>{calls.reload.push(args);context._selectTrackToken++;},
  _computeOtherGuitarTracks:(...args)=>calls.background.push(args),
  _setPdfExportStatus:(...args)=>calls.status.push(args),
  _solveCacheKey:(file,track,mode)=>`${file}#${track}#${mode}`,
});
vm.runInContext(declaration('// ── Saved fingering version warning',
  'let _bgComputeRunning') + '\n'
  + declaration('function _updateInsertFingeringsBtn') + '\n'
  + declaration('async function _cachedSolve') + '\n'
  + declaration('async function _computeOtherGuitarTracks') + '\n'
  + `globalThis.ui = {show:_showStaleFingeringWarning,reset:_resetStaleFingeringWarning,
    dismiss:_dismissStaleFingeringWarning,recalculate:_recalculateStaleFingerings,
    insert:_insertFingerings,updateButton:_updateInsertFingeringsBtn,
    cachedSolve:_cachedSolve,
    refresh:_refreshStaleFingeringControls,background:_computeOtherGuitarTracks};`, context);
context._computeOtherGuitarTracks=(...args)=>calls.background.push(args);
const ui = context.ui;
const banner = elements['stale-fingering-warning'];
const save = elements['stale-fingering-recalculate'];
const later = elements['stale-fingering-later'];
const status = elements['stale-fingering-status'];
const stale = {has_saved_fingering:true,fingering_is_current:false,
  fingering_is_outdated:true,fingering_algo_version:'2.1',
  fingering_current_algo_version:'2.2'};
function deferred(){let resolve,reject;const promise=new Promise((a,b)=>{resolve=a;reject=b;});
  return {promise,resolve,reject};}
async function run() {
"""


@pytest.mark.parametrize(
    "case",
    [
        pytest.param(
            r"""
for (const data of [null,{}, {...stale,has_saved_fingering:false},
  {...stale,fingering_is_outdated:false}, {...stale,fingering_is_outdated:undefined}]) {
  ui.show(data); assert.equal(banner.hidden,true);
}
context._reviewTrackName='<img src=x onerror=alert(1)>';
ui.show(stale);
assert.equal(banner.hidden,false);
assert.match(elements['stale-fingering-message'].textContent,/2\.1/);
assert.match(elements['stale-fingering-message'].textContent,/2\.2/);
assert.match(elements['stale-fingering-message'].textContent,/<img/);
assert.equal(elements['stale-fingering-message'].innerHTML,undefined);
ui.updateButton({...stale,fingering_is_outdated:false});
assert.doesNotMatch(context.btnInsertFingerings.title,/antérieure/);
assert.equal(calls.save.length,0);
""",
            id="only-authoritative-old-engine-version-warns",
        ),
        pytest.param(
            r"""
ui.show(stale); later.listeners.click();
assert.equal(banner.hidden,true);
ui.show(stale); assert.equal(banner.hidden,true);
context.currentTrackId=4; context._selectTrackToken++;
ui.show(stale); assert.equal(banner.hidden,false);
context.currentTrackId=3; context._selectTrackToken++;
ui.show(stale); assert.equal(banner.hidden,true);
ui.reset(true); context._selectFileToken++; ui.show(stale);
assert.equal(banner.hidden,false);
assert.equal(calls.save.length,0);
assert.equal(calls.reload.length,0);
""",
            id="later-never-writes-and-next-opening-warns-again",
        ),
        pytest.param(
            r"""
const pending=deferred();
context.fetchSaveGp=(...args)=>{calls.save.push(args);return pending.promise;};
context._solveCache.set('song.gp#3#tablature',stale);
context._solveCache.set('song.gp#4#tablature',stale);
ui.show(stale);
const action=save.listeners.click();
await save.listeners.click();
assert.equal(calls.save.length,1);
assert.equal(JSON.stringify(calls.save[0]),JSON.stringify(['song.gp',3,{stream:true}]));
assert.equal(save.disabled,true); assert.equal(later.disabled,true);
assert.equal(context.btnInsertFingerings.disabled,true);
assert.match(status.textContent,/en cours/);
ui.dismiss(); assert.equal(banner.hidden,false);
pending.resolve({sidecar_saved:true}); await action;
assert.equal(banner.hidden,true);
assert.deepEqual(calls.reload,[[3,'Guitare']]);
assert.equal(calls.background.length,0);
assert.equal(context._solveCache.has('song.gp#3#tablature'),false);
assert.equal(context._solveCache.has('song.gp#4#tablature'),true);
assert.equal(context.btnInsertFingerings.disabled,false);
assert.match(calls.status.at(-1)[0],/recalculés et enregistrés/);
""",
            id="cta-saves-active-track-once-and-refreshes-without-background",
        ),
        pytest.param(
            r"""
context.fetchSaveGp=async (...args)=>{
  calls.save.push(args);throw new Error('Serveur indisponible');};
ui.show(stale); await ui.recalculate();
assert.equal(banner.hidden,false); assert.equal(save.disabled,false);
assert.equal(later.disabled,false); assert.equal(banner.attrs['aria-busy'],'false');
assert.match(status.textContent,/Serveur indisponible/);
assert.equal(calls.reload.length,0);
context.fetchSaveGp=async (...args)=>{calls.save.push(args);return {sidecar_saved:true};};
await ui.recalculate();
assert.equal(calls.save.length,2); assert.equal(banner.hidden,true);
""",
            id="failed-save-remains-visible-and-retry-works",
        ),
        pytest.param(
            r"""
context.fetchSaveGp=async ()=>({sidecar_saved:false});
ui.show(stale); await ui.recalculate();
assert.equal(banner.hidden,false); assert.match(status.textContent,/incomplet/);
assert.equal(calls.reload.length,0); assert.equal(save.disabled,false);
context.fetchSaveGp=async ()=>({sidecar_saved:true,gp_embed_skipped:true});
await ui.recalculate();
assert.equal(banner.hidden,true);
assert.match(calls.status.at(-1)[0],/FretWise.*Guitar Pro inchangé/);
""",
            id="partial-persistence-is-error-and-sidecar-only-save-is-explained",
        ),
        pytest.param(
            r"""
for (const next of [{currentFile:'other.gp',currentTrackId:8},
  {currentFile:'song.gp',currentTrackId:4},{currentFile:'song.gp',currentTrackId:3}]) {
  context.currentFile='song.gp'; context.currentTrackId=3;
  const pending=deferred(); context.fetchSaveGp=()=>pending.promise;
  ui.reset(true); ui.show(stale); const action=ui.recalculate();
  Object.assign(context,next); context._selectFileToken++; context._selectTrackToken++;
  ui.reset(true); ui.show(stale);
  const nextMessage=elements['stale-fingering-message'].textContent;
  pending.resolve({sidecar_saved:true}); await action;
  assert.equal(calls.reload.length,0); assert.equal(calls.background.length,0);
  assert.equal(banner.hidden,false); assert.equal(save.disabled,false);
  assert.equal(elements['stale-fingering-message'].textContent,nextMessage);
}
""",
            id="late-save-never-switches-new-file-track-or-reopened-same-file",
        ),
        pytest.param(
            r"""
context.currentFile='song.musicxml'; ui.show(stale);
assert.equal(banner.hidden,false); assert.equal(save.disabled,true);
assert.match(status.textContent,/uniquement.*Guitar Pro 7\/8/);
await ui.recalculate(); assert.equal(calls.save.length,0);
assert.equal(later.disabled,false); ui.dismiss(); assert.equal(banner.hidden,true);
context.currentFile='song.GP'; ui.reset(true); ui.show(stale);
await ui.recalculate(); assert.equal(calls.save.length,1);
""",
            id="unsupported-format-explains-disabled-save",
        ),
        pytest.param(
            r"""
const pending=deferred(); context.fetchSolve=()=>pending.promise;
const oldRequest=ui.cachedSolve('song.gp',3,'tablature',{});
ui.show(stale); await ui.recalculate();
pending.resolve(stale); await oldRequest;
assert.equal(context._solveCache.size,0);
context.fetchSolve=async ()=>({...stale,fingering_is_outdated:false});
await ui.cachedSolve('song.gp',3,'tablature',{});
assert.equal(context._solveCache.size,1);
assert.equal(context._solveCache.values().next().value.fingering_is_outdated,false);
""",
            id="pre-save-solve-response-cannot-recache-old-fingerings",
        ),
        pytest.param(
            r"""
context._bgComputeRunning=true; ui.show(stale);
assert.equal(save.disabled,true); assert.match(status.textContent,/déjà en cours/);
await ui.recalculate(); await ui.insert(); assert.equal(calls.save.length,0);
context._bgComputeRunning=false; ui.refresh();
assert.equal(save.disabled,false); assert.equal(status.textContent,'');
context._solveInFlight=true; ui.show(stale);
assert.equal(save.disabled,true); await ui.recalculate(); assert.equal(calls.save.length,0);
context._solveInFlight=false; ui.refresh();
assert.equal(save.disabled,false); await ui.recalculate(); assert.equal(calls.save.length,1);
""",
            id="existing-background-save-and-loading-disable-new-save",
        ),
        pytest.param(
            r"""
const pending=deferred();
context.currentTracks=[{id:3,kind:'guitar'},{id:4,kind:'guitar'}];
context.isGuitarKind=()=>true;
context.fetchSaveGp=(...args)=>{calls.save.push(args);return pending.promise;};
const background=ui.background('song.gp',3);
context.currentTrackId=4; context._selectTrackToken++; ui.show(stale);
assert.equal(save.disabled,true); await ui.recalculate();
assert.equal(calls.save.length,1);
pending.resolve({sidecar_saved:true}); await background;
assert.equal(save.disabled,false); assert.equal(status.textContent,'');
""",
            id="actual-background-track-save-excludes-cta-until-settled",
        ),
        pytest.param(
            r"""
await ui.insert();
assert.equal(calls.save.length,1); assert.equal(calls.reload.length,1);
assert.deepEqual(calls.background,[['song.gp',3]]);
""",
            id="existing-toolbar-background-option-preserved",
        ),
    ],
)
def test_stale_fingering_warning_behavior(case: str) -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for real viewer JavaScript checks")
    script = _HARNESS + case + "\n}\nrun().catch(e=>{console.error(e);process.exit(1);});"
    result = subprocess.run(
        [node, "-e", script, str(_STATIC / "js/main.js")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_warning_lifecycle_is_wired_to_viewer_and_accessible_markup() -> None:
    source = (_STATIC / "js/main.js").read_text(encoding="utf-8")
    html = (_STATIC / "index.html").read_text(encoding="utf-8")
    css = (_STATIC / "css/style.css").read_text(encoding="utf-8")
    select_file = source.split("async function selectFile(filename) {", 1)[1].split(
        "async function selectTrack(trackId, trackName) {", 1
    )[0]
    select_track = source.split("async function selectTrack(trackId, trackName) {", 1)[1].split(
        "// ── Loading feedback", 1
    )[0]
    leave = source.split("function _backToLibrary() {", 1)[1].split("\n}", 1)[0]
    assert "_resetStaleFingeringWarning(true)" in select_file
    assert "_resetStaleFingeringWarning(true)" in leave
    assert select_track.index("myToken !== _selectTrackToken") < select_track.index(
        "_showStaleFingeringWarning(viewData)"
    )
    assert 'aria-labelledby="stale-fingering-title"' in html
    assert 'id="stale-fingering-status" role="status" aria-live="polite"' in html
    assert ".stale-fingering-warning[hidden] { display: none; }" in css
