"""Real viewer handlers keep invalidity visible beside freshness and save state."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from tests.test_web_stale_fingering_warning import _HARNESS


def test_invalid_warning_survives_dismiss_save_and_tracks_audit_truth() -> None:
    node = shutil.which("node")
    if not node:
        pytest.skip("Node required for viewer behavior checks")
    script = _HARNESS + r"""
for (const id of ['fingering-validity-warning','fingering-validity-title',
  'fingering-validity-message','audit-banner','audit-text','audit-dot',
  'audit-review-open','audit-toggle','audit-details']) {
  elements[id]=element();elements[id].style={};elements[id].appendChild=()=>{};
}
vm.runInContext(declaration('function _updateFingeringValidity')
  + ';globalThis.updateValidity=_updateFingeringValidity;',context);
const invalid={...stale,fingering_validity:'invalid',biomechanical_fatal:165,
  fatal_measures:[21,22,77],fatal_measure_count:3,fingering_validation_scope:'saved'};
const warning=elements['fingering-validity-warning'];
ui.show(invalid); context.updateValidity(invalid);
assert.equal(banner.hidden,false);assert.equal(warning.hidden,false);
assert.match(elements['fingering-validity-title'].textContent,/ancienne version.*non validés/);
assert.match(elements['fingering-validity-message'].textContent,/165.*21, 22, 77/);
assert.match(elements['fingering-validity-message'].textContent,/partition reste consultable/);
ui.dismiss();assert.equal(banner.hidden,true);assert.equal(warning.hidden,false);
ui.updateButton({...invalid,fingering_is_current:true});
assert.match(context.btnInsertFingerings.title,/non validés/);
context.updateValidity(null);assert.equal(warning.hidden,true);
context.updateValidity({fingering_validity:'valid',biomechanical_fatal:0});
assert.equal(warning.hidden,true);
context.updateValidity({fingering_validity:'unknown'});
assert.equal(warning.hidden,false);
assert.match(elements['fingering-validity-title'].textContent,/non disponible/);
ui.reset(true);ui.show(invalid);
context.fetchSaveGp=async ()=>({...invalid,sidecar_saved:true});
context.selectTrack=async ()=>{context.updateValidity(invalid);context._selectTrackToken++;};
await ui.recalculate();
assert.equal(warning.hidden,false);assert.equal(calls.status.at(-1)[1],'warn');
assert.match(calls.status.at(-1)[0],/contraintes biomécaniques à corriger/);

context.btnHeaderSave=element();
vm.runInContext(declaration('async function saveGP')
  + ';globalThis.saveHeader=saveGP;',context);
let displayed=invalid;
for (const next of [{fingering_validity:'valid',biomechanical_fatal:0},invalid]) {
  context.fetchSaveGp=async ()=>({...next,sidecar_saved:true});
  context.selectTrack=async ()=>{
    displayed=next;context.updateValidity(next);context._selectTrackToken++;
  };
  await context.saveHeader();
  assert.equal(displayed,next);
  assert.equal(warning.hidden,next.fingering_validity==='valid');
  assert.equal(context.btnHeaderSave.disabled,false);
}
const pending=deferred();context.fetchSaveGp=()=>pending.promise;
const headerSave=context.saveHeader();
context.currentFile='new.gp';context._selectFileToken++;context._selectTrackToken++;
displayed={fingering_validity:'valid',biomechanical_fatal:0};context.updateValidity(displayed);
pending.resolve({...invalid,sidecar_saved:true});await headerSave;
assert.equal(displayed.fingering_validity,'valid');assert.equal(warning.hidden,true);
assert.equal(context.btnHeaderSave.disabled,false);

globalThis.document=context.document;
document.createElement=()=>({style:{},appendChild(){}});
const auditFile=process.argv[1].replace(/main\.js$/,'audit.js');
const {renderAuditBanner}=await import('data:text/javascript;base64,'
  +fs.readFileSync(auditFile).toString('base64'));
const clean={available:true,overall:'clean',movements:[],ml_signal_available:true};
renderAuditBanner(clean,{fingeringValidity:'invalid',biomechanicalFatal:1});
assert.match(elements['audit-text'].textContent,/non validés/);
assert.doesNotMatch(elements['audit-text'].textContent,/tous les mouvements OK/);
renderAuditBanner(clean,{fingeringValidity:'unknown'});
assert.match(elements['audit-text'].textContent,/non disponible/);
renderAuditBanner(clean,{fingeringValidity:'valid',biomechanicalFatal:0});
assert.match(elements['audit-text'].textContent,/tous les mouvements OK/);
}
run().catch(e=>{console.error(e);process.exit(1);});
"""
    # The harness executes unmodified handler bodies, normalizing only CRLF.
    source = Path(__file__).parents[1] / "src/fretwise/web/static/js/main.js"
    result = subprocess.run(
        [node, "-e", script, str(source)], capture_output=True, text=True,
        encoding="utf-8", timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
