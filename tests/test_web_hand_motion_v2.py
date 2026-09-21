"""Execute deterministic contact planning and the actual reference skin in Node."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).parents[1] / "src/fretwise/web/static/js"
pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="Node unavailable")

FIXTURE = """
const instrument={profileId:'six-string-648',profileRevision:'1',scaleLengthM:.648,
  fretCount:24,capoFret:0,strings:[64,59,55,50,45,40].map((openPitchMidi,i)=>({number:i+1,openPitchMidi}))};
function note(id,finger,stringNo,fretAbs,onTick,endTick) {
  return {occurrenceId:id,sourceNoteId:id,voiceId:'1',onTick,notatedEndTick:endTick,
    soundEndTick:endTick,basePitchMidi:60,velocity:90,expressionIds:[],
    fingering:{finger,stringNo,fretAbs,provenance:'source',locked:true}};
}
function performance(notes,expressions=[]) {
  return {schemaVersion:'1.1',scoreId:'test',trackId:'1',scoreRevision:'a',fingeringRevision:'b',
    performanceTimingRevision:'source-1',ppq:960,range:{startTick:0,endTick:7680},
    tempoMap:[{tick:0,usPerQuarter:500000}],hand:{side:'left',profileId:'adult-reference-left',profileRevision:'1'},
    instrument,notes,expressions,holds:[],barres:[],diagnostics:[],
    noteExecution:notes.map(n=>({occurrenceId:n.occurrenceId,attackKind:'pick',
      excitationGroupId:n.occurrenceId,sustainRequiredUntilTick:n.soundEndTick,timingProvenance:'source'}))};
}
"""


def run_js(script: str) -> dict:
    """Run shipped ES modules, returning only explicit JSON output."""
    source = (
        f"import {{compilePerformance,sampleMotion,makeTempoClock,sampleCurve}} from "
        f"{json.dumps((JS / 'hand_motion.js').as_uri())};\n"
        + FIXTURE + script
    )
    result = subprocess.run(
        ["node", "--input-type=module", "-e", source],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_tempo_map_example_initial_rest_and_rate_once() -> None:
    result = run_js("""
const clock=makeTempoClock(960,[{tick:0,usPerQuarter:500000},{tick:1920,usPerQuarter:1000000}]);
const p=performance([note('n','index',2,1,1920,3840)]);
p.tempoMap=[{tick:0,usPerQuarter:500000},{tick:1920,usPerQuarter:1000000}];
const slow=compilePerformance(p),fast=compilePerformance(p,{playbackRate:2});
console.log(JSON.stringify({sec:clock.tickToSeconds(3840),tick:clock.secondsToTick(3),
 initial:sampleMotion(slow,0).activeContactIds,active:sampleMotion(fast,1).activeContactIds,
 fastOn:fast.byFinger.index[0].on,fastEnd:fast.byFinger.index[0].end,
 durationRatio:(fast.byFinger.index[0].on-fast.byFinger.index[0].prepareStart)
 /(slow.byFinger.index[0].on-slow.byFinger.index[0].prepareStart)}));
""")
    assert result["sec"] == 3
    assert result["tick"] == 3840
    assert result["initial"] == []
    assert result["active"] == ["contact:n"]
    assert result["fastOn"] == 1
    assert result["fastEnd"] == 3
    assert result["durationRatio"] == pytest.approx(2)


def test_held_notes_and_repeated_attacks_do_not_pump() -> None:
    result = run_js("""
const p=performance([note('a','index',2,1,0,960),note('b','index',2,1,960,1920),
 note('c','ring',3,3,2880,3840)]),plan=compilePerformance(p);
console.log(JSON.stringify({count:plan.byFinger.index.length,
 before:sampleMotion(plan,.499).fingers.index,after:sampleMotion(plan,.501).fingers.index,
 end:plan.byFinger.index[0].end}));
""")
    assert result["count"] == 1
    assert result["before"]["targetM"] == result["after"]["targetM"]
    assert result["before"]["state"] == result["after"]["state"] == "HOLD"
    assert result["end"] == 1


def test_conflicting_sustain_is_reported_without_shortening_note() -> None:
    result = run_js("""
const p=performance([note('a','index',2,1,0,3840),note('b','index',3,5,1920,4800)]);
const plan=compilePerformance(p);
console.log(JSON.stringify({end:plan.byFinger.index[0].end,codes:plan.diagnostics.map(d=>d.code),
 valid:sampleMotion(plan,1.2).valid,firstTarget:sampleMotion(plan,1.2).fingers.index.fretAbs}));
""")
    assert result["end"] == 2
    assert "FINGER_CONTACT_CONFLICT" in result["codes"]
    assert result["valid"] is False
    assert result["firstTarget"] == 1


def test_seek_pause_and_direct_sampling_return_identical_states() -> None:
    result = run_js("""
const p=performance([note('a','index',2,1,0,960),note('b','index',4,3,1920,3840)]);
const plan=compilePerformance(p);const direct=sampleMotion(plan,.96);
for(let t=0;t<4;t+=.017)sampleMotion(plan,t);
const seek=sampleMotion(plan,.96),pause=sampleMotion(plan,.96);
console.log(JSON.stringify({direct,seek,pause,state:direct.fingers.index.state}));
""")
    assert result["direct"] == result["seek"] == result["pause"]
    assert result["state"] in {"PREPARE", "TRANSFER", "LAND"}


def test_pull_off_prepares_lower_finger_and_bend_keeps_absolute_curve() -> None:
    result = run_js("""
const notes=[note('a','ring',2,7,0,1920),note('b','index',2,5,1920,3840)];
notes[0].expressionIds=['pull','bend']; notes[1].expressionIds=['pull'];
const expressions=[{id:'pull',kind:'pull_off',fromId:'a',toId:'b',noteIds:['a','b'],
 startTick:0,endTick:1920},{id:'bend',kind:'bend',noteIds:['a'],startTick:0,endTick:1920,
 cents:{interpolation:'linear',points:[{tick:0,value:200},{tick:960,value:200},{tick:1920,value:0}]},
 direction:'toward_bass',preBend:true}];
const plan=compilePerformance(performance(notes,expressions));
console.log(JSON.stringify({support:sampleMotion(plan,.95).fingers.index,
 initial:sampleMotion(plan,0).fingers.ring,
 curve:sampleCurve(expressions[1].cents,1440),codes:plan.diagnostics.map(d=>d.code)}));
""")
    assert result["support"]["state"] == "HOLD"
    assert result["support"]["pressure01"] == 1
    assert result["initial"]["pitch"] == [{"expressionId": "bend", "cents": 200}]
    assert result["curve"] == 100
    assert "BEND_CALIBRATION_MISSING" in result["codes"]


def test_actual_dual_quaternion_skin_contacts_and_lengths() -> None:
    result = run_js(f"""
const T=await import({json.dumps((JS / 'vendor/three.module.min.js').as_uri())});
const {{createReferenceRig}}=await import({json.dumps((JS / 'hand_reference_rig.js').as_uri())});
const rig=createReferenceRig(new T.Group());
const cases=[
 [note('i','index',2,1,0,1920),note('m','middle',4,2,0,1920),note('r','ring',3,2,0,1920)],
 [note('i','index',2,1,0,1920),note('m','middle',4,2,0,1920),note('r','ring',5,3,0,1920)],
 ...['index','middle','ring','pinky'].map((f,i)=>[note(f,f,3,5+i,0,1920)])];
// Source import can use note fret as handPositionHint. Treat it as a preference.
cases[0].forEach(n=>n.fingering.handPositionHint=n.fingering.fretAbs);
const output=[];
for(const notes of cases){{const plan=compilePerformance(performance(notes));
const sample=sampleMotion(plan,.3);output.push(rig.pose(sample,plan.geometry).filter(m=>m.active));}}
console.log(JSON.stringify({{output,vertices:rig.geometry.attributes.position.count,
 triangles:rig.geometry.index.count/3}}));
""")
    assert result["vertices"] == 18514
    assert result["triangles"] == 37024
    for case in result["output"]:
        for finger in case:
            assert finger["errorMm"] < 0.5, finger
            assert finger["lengthsMm"] == pytest.approx(finger["restLengthsMm"], abs=1e-10)
            assert finger["valid"] is True


def test_reference_hand_does_not_add_unanchored_procedural_nails() -> None:
    """Finger skin remains authoritative until nail anatomy is part of the asset."""
    source = (JS / "hand_reference_rig.js").read_text(encoding="utf-8")
    assert "putNail(" not in source
    assert "const nails=" not in source
    assert "nailMat=" not in source
    assert "SphereGeometry(1,20,12)" not in source


def test_reference_forearm_bends_below_and_across_neck_without_moving_contacts() -> None:
    result = run_js(f"""
const T=await import({json.dumps((JS / 'vendor/three.module.min.js').as_uri())});
const {{createReferenceRig}}=await import({json.dumps((JS / 'hand_reference_rig.js').as_uri())});
const rig=createReferenceRig(new T.Group());
const plan=compilePerformance(performance([note('i','index',2,1,0,1920)]));
const contacts=rig.pose(sampleMotion(plan,.3),plan.geometry).filter(m=>m.active);
// The diagnostic axis and rendered wrist skin share the same rest-shape bake.
const axis=rig.hand.getObjectByName('reference-forearm-axis').geometry.attributes.position;
const points=Array.from({{length:24}},(_,i)=>new T.Vector3().fromBufferAttribute(axis,i));
const wrist=points[23],elbow=points[0];
const palm=points[23].clone().sub(new T.Vector3().fromBufferAttribute(axis,25)).normalize();
const arm=points[0].clone().sub(points[1]).normalize();
const world=points.map(p=>p.clone().add(rig.hand.position));
const position=rig.geometry.attributes.position;
const distalSkin=[];
for(let i=0;i<position.count;i++){{
 const p=new T.Vector3().fromBufferAttribute(position,i).add(rig.hand.position);
 if(p.y < -170)distalSkin.push(p.toArray());
}}
console.log(JSON.stringify({{contacts,wrist:wrist.toArray(),
 bendDegrees:T.MathUtils.radToDeg(palm.angleTo(arm)),
 axis:world.map(p=>p.toArray()),distalSkin}}));
""")
    assert result["wrist"] == pytest.approx([0, 0, 0], abs=1e-5)
    # Clear flexion, with the elbow side going under the board rather than
    # extending out behind the hand as a flat keyboard wrist would.
    assert 55 < result["bendDegrees"] < 85
    axis = result["axis"]
    assert all(p[1] < -70 for p in axis)
    assert any(abs(p[2]) < 25 and p[1] < -120 for p in axis)
    assert axis[0][2] < axis[-1][2] - 100
    # Check the actual mesh too: an axis-only correction must not pass.
    assert len(result["distalSkin"]) > 100
    assert max(p[2] for p in result["distalSkin"]) < 85
    assert min(p[2] for p in result["distalSkin"]) < 0
    assert result["contacts"][0]["errorMm"] < 0.5
    assert result["contacts"][0]["valid"] is True


def test_dead_note_keeps_x_semantics_without_an_ordinary_press() -> None:
    """The rig does not turn a source dead note into a fretted contact."""
    result = run_js("""
const muted=note('muted','index',3,5,0,960);
muted.expressionIds=['dead'];
const p=performance([muted],[{id:'dead',kind:'dead_note',noteIds:['muted'],startTick:0,endTick:960}]);
const plan=compilePerformance(p);
console.log(JSON.stringify({contacts:plan.byFinger.index.length,
  active:sampleMotion(plan,.2).activeContactIds,
  codes:plan.diagnostics.map(d=>d.code)}));
""")
    assert result == {
        "contacts": 0,
        "active": [],
        "codes": ["DEAD_NOTE_DAMPING_NOT_RENDERED"],
    }


def test_unknown_major_version_and_required_capability_fail_explicitly() -> None:
    result = run_js("""
const p=performance([]);p.schemaVersion='2.0';let major;
try{compilePerformance(p)}catch(e){major=e.message}
p.schemaVersion='1.1';p.requiredCapabilities=['motion.shoulder'];
console.log(JSON.stringify({major,codes:compilePerformance(p).diagnostics.map(d=>d.code)}));
""")
    assert result["major"] == "UNSUPPORTED_SCHEMA_VERSION"
    assert result["codes"] == ["CAPABILITY_UNSUPPORTED"]


def test_worker_result_is_cloneable_and_obsolete_jobs_are_cancelled() -> None:
    result = run_js(f"""
const {{compileWorkerMessage}}=await import({json.dumps((JS / 'hand_motion_worker.js').as_uri())});
const {{HandPlanCompiler}}=await import({json.dumps((JS / 'hand_compiler.js').as_uri())});
const workers=[];
const compiler=new HandPlanCompiler({{workerFactory:()=>{{
 const w={{terminate(){{this.terminated=true}},postMessage(m){{this.message=m}}}};
 workers.push(w);return w;
}}}});
const p=performance([note('a','index',2,1,0,960)]);
const first=compiler.compile(p).catch(e=>e.name);
const second=compiler.compile(p,{{playbackRate:2}});
const obsolete=structuredClone(compileWorkerMessage(workers[0].message));
workers[0].onmessage({{data:obsolete}});
const latest=structuredClone(compileWorkerMessage(workers[1].message));
workers[1].onmessage({{data:latest}});
const plan=await second;
console.log(JSON.stringify({{first:await first,rate:plan.playbackRate,
 sec:plan.clock.tickToSeconds(960),active:sampleMotion(plan,.1).activeContactIds,
 terminated:workers.map(w=>w.terminated),clonedDetails:plan.details instanceof Map}}));
compiler.dispose();
""")
    assert result == {
        "first": "AbortError", "rate": 2, "sec": 0.5,
        "active": ["contact:a"], "terminated": [True, True], "clonedDetails": True,
    }


def test_unknown_profile_is_not_silently_approximated() -> None:
    result = run_js("""
const p=performance([]);let hand,instrumentProfile;
p.hand.profileId='child';try{compilePerformance(p)}catch(e){hand=e.message}
p.hand.profileId='adult-reference-left';p.instrument.profileRevision='unknown';
try{compilePerformance(p)}catch(e){instrumentProfile=e.message}
console.log(JSON.stringify({hand,instrumentProfile}));
""")
    assert result == {
        "hand": "HAND_PROFILE_UNSUPPORTED", "instrumentProfile": "INSTRUMENT_PROFILE_UNSUPPORTED",
    }


def test_release_prepare_and_land_join_without_position_jumps() -> None:
    result = run_js("""
const p=performance([note('a','index',2,1,960,1920),note('b','index',3,5,3840,4800)]);
const plan=compilePerformance(p),jumps=[];
for(const c of plan.byFinger.index)for(const t of [c.prepareStart,c.on,c.end]){
 const a=sampleMotion(plan,t-1e-7).fingers.index.targetM;
 const b=sampleMotion(plan,t+1e-7).fingers.index.targetM;
 jumps.push(Math.hypot(...a.map((x,i)=>x-b[i])));
}
console.log(JSON.stringify({jumps}));
""")
    assert max(result["jumps"]) < 1e-5


def test_unexpanded_repeats_are_partial_and_invalid() -> None:
    result = run_js("""
const p=performance([note('a','index',2,1,0,1920)]);
p.diagnostics=[{code:'REPEAT_UNFOLDING_REQUIRED',message:'Repeat pending',noteIds:[]}];
const plan=compilePerformance(p);console.log(JSON.stringify({status:plan.status,valid:sampleMotion(plan,.1).valid}));
""")
    assert result == {"status": "partial", "valid": False}


def test_missed_deadline_shows_invalid_continuous_motion_instead_of_teleport() -> None:
    result = run_js("""
const p=performance([note('a','ring',3,2,0,960),note('b','ring',5,3,960,1920)]);
const plan=compilePerformance(p),a=sampleMotion(plan,.5-1e-7),b=sampleMotion(plan,.5+1e-7);
console.log(JSON.stringify({jump:Math.hypot(...a.fingers.ring.targetM.map((x,i)=>x-b.fingers.ring.targetM[i])),
 valid:b.valid,state:b.fingers.ring.state,pressure:b.fingers.ring.pressure01,
 attack:plan.performance.notes[1].onTick,previousEnd:plan.byFinger.ring[0].end}));
""")
    assert result["jump"] < 1e-5
    assert result["valid"] is False
    assert result["state"] == "PREPARE"
    assert result["pressure"] == 0
    assert result["attack"] == 960
    assert result["previousEnd"] == 0.5
