/** Import the user-supplied September 14 reference hand, without its demo UI.
 * Usage: node scripts/import_reference_hand.cjs <extracted fretwise directory>
 * The imported runtime files are committed; this is not a build-time dependency.
 */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const source = path.resolve(process.argv[2] || 'output/notion-prototype/fretwise');
const staticRoot = path.resolve(__dirname, '../src/fretwise/web/static');
const app = fs.readFileSync(path.join(source, 'app.js'), 'utf8');
function excerpt(start, end) {
  const a = app.indexOf(start), b = app.indexOf(end, a + start.length);
  if (a < 0 || b < 0) throw new Error(`Unknown reference source: ${start}`);
  return app.slice(a, b);
}
const setup = excerpt('const rad=T.MathUtils.degToRad', 'const smooth=t=>');
const contact = excerpt('const padSamples=chains.map', 'function upperHull');
const thumb = excerpt('function thumbPose()', '// Illustrative bounded movements');
const sha = data => crypto.createHash('sha256').update(data).digest('hex');
const banner = `/* Adapted from user-supplied FretWise reference, 2026-09-14.
 * Generic hand mesh: Copyright (c) 2019 Amazon, MIT (models/hand-reference/LICENSE.txt).
 * Source app.js SHA-256: ${sha(app)}
 * Reference skin/contact model, NOT a calibrated anatomical or force simulation.
 * Millimetres internal: x along neck, y up, z toward treble. Public adapter converts metres.
 */\n`;
let core = setup + contact + thumb;
core = core.replace('subdivide();subdivide();', 'subdivide();subdivide();');
core = core.replace('const cacheKey=base.x.toFixed(3)+":"+target.toArray().map(v=>v.toFixed(3)).join(":");',
  'const cacheKey=[...base.toArray(),...target.toArray(),...lengths].map(v=>v.toFixed(6)).join(":");');
// Preserve lengths when an exact constrained IK solution does not exist. Select
// the nearest bounded FK candidate and report residual; never claim a valid pose.
core = core.replace('if(!best)best=[.7,1.45,.8];', `if(!best){let residual=Infinity;
 for(let m=0;m<=8;m++)for(let p=0;p<=8;p++)for(let d=0;d<=6;d++){
  const q=[lower[0]+(upper[0]-lower[0])*m/8,upper[1]*p/8,upper[2]*d/6];
  const error=fk(base,lengths,h,q)[3].distanceToSquared(target);
  if(error<residual){residual=error;best=q;}
 }
}`);
const moduleSource = banner + `import * as T from './vendor/three.module.min.js';
import { HAND_REFERENCE_ASSET as handAsset } from './hand_reference_asset.js';
export function createReferenceRig(world) {
const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z),up=V(0,1,0);
const mesh=(g,m,parent=world)=>{const o=new T.Mesh(g,m);o.castShadow=o.receiveShadow=true;parent.add(o);return o;};
` + core + `
let lastMetrics=[];
return {
  hand, geometry, rest, lens, strings: null,
  setDiagnostics(enabled){jointGroup.visible=enabled;contactGroup.visible=enabled;},
  pose(sample, geometryProfile) {
    const values=Object.values(sample.fingers);
    const shift=sample.rootPositionM[0]*1000-rest[chains[0][1]].x+18;
    hand.position.set(shift,-74,84);
    for(let j=0;j<25;j++)setBone(j,rest[j],new T.Quaternion());
    lastMetrics=[];
    for(let f=0;f<4;f++){
      const value=values[f];
      const tg=value.noteIds.length
        ? V(value.targetM[0]*1000,value.targetM[2]*1000,value.targetM[1]*1000)
        : V(shift+rest[chains[f][1]].x+3,12,16+f*1.5);
      const result=solveContact(f,tg.clone().sub(hand.position)),sol=result.sol;
      const endAngle=A-sol.q.reduce((a,b)=>a+b,0);
      const pad=sol.h.clone().multiplyScalar(Math.sin(endAngle)).addScaledVector(up,-Math.cos(endAngle));
      putNail(nails[f],sol.points[2],sol.points[3],pad,[4.3,4.7,4.4,3.6][f],[4.5,4.8,4.5,4][f]);
      const point=result.point.clone().add(hand.position);
      rings[f].position.copy(point);rings[f].visible=value.pressure01>0&&result.error<.5;
      fretRings[f].visible=rings[f].visible;
      if(value.fretAbs!==null)fretRings[f].position.set(
        geometryProfile.fretX(value.fretAbs)*1000,
        geometryProfile.profile.fretHeight*1000+2*geometryProfile.stringRadius(value.stringNo)*1000,
        geometryProfile.stringY(value.stringNo,geometryProfile.fretX(value.fretAbs))*1000);
      foldAmount.value[f]=T.MathUtils.clamp(sol.q[1]/rad(110),0,1);
      lastMetrics.push({finger:value.finger,active:value.pressure01>0,errorMm:result.error,
        pointM:[point.x/1000,point.z/1000,point.y/1000],targetM:value.targetM,
        lengthsMm:sol.points.slice(1).map((p,j)=>p.distanceTo(sol.points[j])),
        restLengthsMm:lens[f],noteIds:value.noteIds,valid:result.error<.5&&value.valid});
    }
    thumbPose();foldAmount.value[4]=.1;
    dots.forEach((d,j)=>d.position.copy(bonePos[j]));
    [...chains,tc].forEach((c,j)=>lines[j].geometry.setFromPoints(c.map(i=>bonePos[i])));
    // A failed pose is visible as a diagnostic illustration, never a frozen old pose.
    skin.opacity=sample.valid&&lastMetrics.every(m=>!m.active||m.valid)?1:.42;
    skin.transparent=skin.opacity<1;
    return lastMetrics;
  },
  getMetrics(){return lastMetrics;},
  clearCaches(){solveCache.clear();contactCache.clear();},
  dispose(){solveCache.clear();contactCache.clear();world.remove(hand,contactGroup);}
};
}
`;
fs.writeFileSync(path.join(staticRoot, 'js/hand_reference_rig.js'), moduleSource);
const data = fs.readFileSync(path.join(source, 'hand-data.js'), 'utf8');
if (!data.includes('window.FRETWISE_HAND_ASSET=')) throw new Error('Unknown mesh data wrapper');
fs.writeFileSync(path.join(staticRoot, 'js/hand_reference_asset.js'),
  banner + data.replace('window.FRETWISE_HAND_ASSET=', 'export const HAND_REFERENCE_ASSET='));
const output = path.join(staticRoot, 'models/hand-reference');
fs.mkdirSync(output, {recursive:true});
fs.copyFileSync(path.join(source, 'LICENSE-HAND.txt'), path.join(output, 'LICENSE.txt'));
fs.copyFileSync(path.join(source, 'hand.glb'), path.join(output, 'source.glb'));
const manifest = {
  schemaVersion:'1.0', id:'generic-left-reference', revision:'2026-09-14', status:'illustrative',
  license:'MIT', copyright:'Copyright (c) 2019 Amazon',
  sourceArchiveSha256:'d7da4707de2d34978b7e0e0dc84bdffa087eacc722ef59138139473cc8ae6470',
  sourceAppSha256:sha(app), sourceDataSha256:sha(data),
  glbSha256:sha(fs.readFileSync(path.join(output,'source.glb'))),
  runtimeDataSha256:sha(fs.readFileSync(path.join(staticRoot,'js/hand_reference_asset.js'))),
  handSide:'left', sourceUnits:'metres', solverUnits:'millimetres', deformation:'dual-quaternion',
  sourceToWorldDeterminant:1, joints:25, expectedVertices:18514, expectedTriangles:37024,
  limitations:['thumb-reference-pose','no-global-collision-certification',
    'no-force-estimation','no-sculpted-anatomical-correctives','no-hardware-performance-qualification'],
};
fs.writeFileSync(path.join(output,'manifest.json'),JSON.stringify(manifest,null,2)+'\n');
console.log(JSON.stringify(manifest,null,2));
