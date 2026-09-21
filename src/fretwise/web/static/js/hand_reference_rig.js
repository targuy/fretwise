/* Adapted from user-supplied FretWise reference, 2026-09-14.
 * Generic hand mesh: Copyright (c) 2019 Amazon, MIT (models/hand-reference/LICENSE.txt).
 * Source app.js SHA-256: cb5138288bf730e6f19cb27330311dd377523acd0f31d4c267886ef9e147d7a4
 * Reference skin/contact model, NOT a calibrated anatomical or force simulation.
 * Millimetres internal: x along neck, y up, z toward treble. Public adapter converts metres.
 */
import * as T from './vendor/three.module.min.js';
import { HAND_REFERENCE_ASSET as handAsset } from './hand_reference_asset.js';
export function createReferenceRig(world) {
const V=(x=0,y=0,z=0)=>new T.Vector3(x,y,z),up=V(0,1,0);
const mesh=(g,m,parent=world)=>{const o=new T.Mesh(g,m);o.castShadow=o.receiveShadow=true;parent.add(o);return o;};
const rad=T.MathUtils.degToRad,A=rad(75),U=V(1,0,0),L=V(0,Math.sin(A),-Math.cos(A)),P=V(0,-Math.cos(A),-Math.sin(A));
function canonical(p,extend=false){let a=(p[2]-.00811395)*1000,b=(.05598624-p[1])*1000,c=(p[0]+.03732416)*1000;
 if(extend&&b<0){
  // Guitar reference: curl away from the palm around the wrist, then descend
  // below and across the neck toward the elbow (negative y AND negative z).
  // Positive z here puts the arm behind the hand in the fretboard plane, giving
  // a keyboard posture from above. Keep the wrist seam and all finger rest
  // positions unchanged; this is an illustrative pose, not an ergonomic limit.
  const s=-b*(245/22.35756865),near=L.clone().negate(),far=V(.12,-.60,-.79).normalize(),w=22;
  const delta=far.clone().sub(near),k=1-Math.exp(-s/w),center=near.clone().multiplyScalar(s).addScaledVector(delta,s-w*k);
  const tangent=near.clone().addScaledVector(delta,k).normalize(),q=new T.Quaternion().setFromUnitVectors(near,tangent),thick=1+.34*T.MathUtils.smoothstep(s,0,245);
  return center.add(U.clone().multiplyScalar(a*thick).addScaledVector(P,c*thick).applyQuaternion(q));
 }
 return U.clone().multiplyScalar(a).addScaledVector(L,b).addScaledVector(P,c);
}
function unpack(s,C){return new C(Uint8Array.from(atob(s),c=>c.charCodeAt(0)).buffer);}
const rawP=unpack(handAsset.arrays[0],Float32Array),rawUV=unpack(handAsset.arrays[2],Float32Array),rawI=unpack(handAsset.arrays[3],Uint8Array),rawW=unpack(handAsset.arrays[4],Float32Array),rawT=unpack(handAsset.arrays[5],Uint16Array);
const names=handAsset.nodes.map(n=>n.name),by=Object.fromEntries(names.map((n,i)=>[n,i])),rest=handAsset.nodes.map(n=>canonical(n.translation)),chains=['index','middle','ring','pinky'].map(n=>['metacarpal','phalanx-proximal','phalanx-intermediate','phalanx-distal','tip'].map(x=>by[n+'-finger-'+x])),tc=['thumb-metacarpal','thumb-phalanx-proximal','thumb-phalanx-distal','thumb-tip'].map(x=>by[x]);
let verts=[],tris=[],weld=new Map(),remap=[];
for(let i=0;i<rawP.length/3;i++){const q=canonical(rawP.slice(i*3,i*3+3),true),key=q.toArray().map(x=>x.toFixed(4)).join(',');if(weld.has(key)){remap.push(weld.get(key));continue;}const w=new Float32Array(25);for(let k=0;k<4;k++)w[rawI[4*i+k]]+=rawW[4*i+k];const axis=rest[tc[1]].clone().sub(rest[tc[0]]),along=q.clone().sub(rest[tc[0]]).dot(axis)/axis.lengthSq(),keep=T.MathUtils.smoothstep(along,-.05,.9),removed=w[tc[0]]*(1-keep)*.7;w[tc[0]]-=removed;w[by.wrist]+=removed;const id=verts.length;weld.set(key,id);remap.push(id);verts.push({p:q,w,uv:[rawUV[2*i],rawUV[2*i+1]]});}
for(let i=0;i<rawT.length;i+=3)tris.push([remap[rawT[i]],remap[rawT[i+2]],remap[rawT[i+1]]]); // handed coordinate bake
function blend(items){const r={p:V(),w:new Float32Array(25),uv:[0,0]};for(const [id,a] of items){const v=verts[id];r.p.addScaledVector(v.p,a);for(let k=0;k<25;k++)r.w[k]+=v.w[k]*a;r.uv[0]+=v.uv[0]*a;r.uv[1]+=v.uv[1]*a;}return r;}
function subdivide(){const edges=new Map(),adj=verts.map(()=>new Set());const ek=(a,b)=>a<b?a+':'+b:b+':'+a;for(const t of tris)for(let k=0;k<3;k++){let a=t[k],b=t[(k+1)%3],c=t[(k+2)%3],key=ek(a,b);if(!edges.has(key))edges.set(key,{a,b,op:[]});edges.get(key).op.push(c);adj[a].add(b);adj[b].add(a);}let boundary=verts.map(()=>[]);for(const e of edges.values())if(e.op.length===1){boundary[e.a].push(e.b);boundary[e.b].push(e.a);}const nv=verts.map((v,i)=>{const b=boundary[i];if(b.length===2)return blend([[i,.75],[b[0],.125],[b[1],.125]]);const n=adj[i].size,beta=n===3?3/16:3/(8*n);return blend([[i,1-n*beta],...[...adj[i]].map(j=>[j,beta])]);});for(const e of edges.values()){e.id=nv.length;nv.push(e.op.length===2?blend([[e.a,.375],[e.b,.375],[e.op[0],.125],[e.op[1],.125]]):blend([[e.a,.5],[e.b,.5]]));}let nt=[];for(const [a,b,c] of tris){const ab=edges.get(ek(a,b)).id,bc=edges.get(ek(b,c)).id,ca=edges.get(ek(c,a)).id;nt.push([a,ab,ca],[ab,b,bc],[ca,bc,c],[ab,bc,ca]);}verts=nv;tris=nt;}
subdivide();subdivide();
const geometry=new T.BufferGeometry(),ps=[],uvs=[],ids=[],weights=[];for(const v of verts){ps.push(...v.p.toArray());uvs.push(...v.uv);const ws=[...v.w].map((w,i)=>({w,i})).sort((a,b)=>b.w-a.w).slice(0,4),sum=ws.reduce((s,v)=>s+v.w,0);for(const a of ws){ids.push(a.i);weights.push(a.w/sum);}}geometry.setAttribute('position',new T.Float32BufferAttribute(ps,3));geometry.setAttribute('uv',new T.Float32BufferAttribute(uvs,2));geometry.setAttribute('skinIndex',new T.Uint8BufferAttribute(ids,4));geometry.setAttribute('skinWeight',new T.Float32BufferAttribute(weights,4));geometry.setIndex(tris.flat());geometry.computeVertexNormals();
const hand=new T.Group();world.add(hand);const real=Array.from({length:25},()=>new T.Vector4(0,0,0,1)),dual=Array.from({length:25},()=>new T.Vector4());
const shaderDecl=`attribute vec4 skinIndex; attribute vec4 skinWeight; uniform vec4 boneR[25]; uniform vec4 boneD[25]; vec3 dqRotate(vec4 q,vec3 v){return v+2.0*cross(q.xyz,cross(q.xyz,v)+q.w*v);}`;
const shaderMain=`vec4 rr=vec4(0.0),dd=vec4(0.0);vec4 ref=boneR[int(skinIndex.x)];for(int k=0;k<4;k++){int id=int(skinIndex[k]);float w=skinWeight[k]*(dot(ref,boneR[id])<0.0?-1.0:1.0);rr+=w*boneR[id];dd+=w*boneD[id];}float ln=length(rr);rr/=ln;dd/=ln;dd-=rr*dot(rr,dd);vec3 trans=2.0*(rr.w*dd.xyz-dd.w*rr.xyz+cross(rr.xyz,dd.xyz));`;
function hook(m){m.onBeforeCompile=s=>{s.uniforms.boneR={value:real};s.uniforms.boneD={value:dual};s.vertexShader=s.vertexShader.replace('#include <common>','#include <common>\n'+shaderDecl).replace('void main() {','void main() {\n'+shaderMain).replace('#include <beginnormal_vertex>','#include <beginnormal_vertex>\nobjectNormal=dqRotate(rr,objectNormal);').replace('#include <begin_vertex>','vec3 transformed=dqRotate(rr,position)+trans;');};m.customProgramCacheKey=()=> 'fw-dqs-2';return m;}
const skin=hook(new T.MeshStandardMaterial({color:0xc9947a,roughness:.68,metalness:0}));const skinned=mesh(geometry,skin,hand);skinned.frustumCulled=false;skinned.customDepthMaterial=hook(new T.MeshDepthMaterial({depthPacking:T.RGBADepthPacking}));
// Rest-space material: creases travel with the skin; no photographed lighting is baked in.
const foldAmount={value:[.5,.5,.5,.5,.2]};
const skinCompile=skin.onBeforeCompile;
const glv=v=>'vec3('+v.toArray().map(x=>x.toFixed(6)).join(',')+')';
let creaseCalls='';
for(let f=0;f<5;f++){
 const c=f<4?chains[f].slice(1):tc.slice(1);
 for(let j=0;j<c.length-1;j++){
  const p=rest[c[j]],axis=rest[c[j+1]].clone().sub(p).normalize(),r=f===4?10:[8.5,9,8.3,6.8][f];
  creaseCalls+=`jointFold(p,${glv(p)},${glv(axis)},${r.toFixed(2)},foldAmount[${f}],creases);\n`;
 }
}
const skinDetail=`
varying vec3 vSkinRest; varying vec3 vSkinNormal; uniform float foldAmount[5];
float hashSkin(vec3 p){p=fract(p*.1031);p+=dot(p,p.yzx+33.33);return fract((p.x+p.y)*p.z);}
float noiseSkin(vec3 p){vec3 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);return mix(mix(mix(hashSkin(i),hashSkin(i+vec3(1,0,0)),f.x),mix(hashSkin(i+vec3(0,1,0)),hashSkin(i+vec3(1,1,0)),f.x),f.y),mix(mix(hashSkin(i+vec3(0,0,1)),hashSkin(i+vec3(1,0,1)),f.x),mix(hashSkin(i+vec3(0,1,1)),hashSkin(i+vec3(1,1,1)),f.x),f.y),f.z);}
void jointFold(vec3 p,vec3 center,vec3 axis,float radius,float bend,inout float crease){
 vec3 rel=p-center;float axial=dot(rel,axis);float radial=length(rel-axis*axial);
 float mask=(1.0-smoothstep(radius,radius+3.0,radial))*(1.0-smoothstep(3.0,5.0,abs(axial)));
 float palmar=smoothstep(-.3,.55,dot(normalize(vSkinNormal),${glv(P)}));
 float width=mix(.30,.52,bend),w=exp(-pow(axial/width,2.0));
 w+=.35*exp(-pow((axial-1.4)/(width*.7),2.0));
 crease+=w*mask*mix(.30,.75,palmar)*mix(.55,1.0,bend);
}
float palmFolds(vec3 p){
 float a=p.x,b=dot(p,${glv(L)}),palmar=smoothstep(.05,.6,dot(normalize(vSkinNormal),${glv(P)}));
 float region=smoothstep(3.0,12.0,b)*(1.0-smoothstep(80.0,94.0,b));
 float thenar=exp(-pow((a-(-5.0-24.0*pow((b-40.0)/47.0,2.0)))/.55,2.0));
 thenar*=smoothstep(8.0,18.0,b)*(1.0-smoothstep(65.0,76.0,b));
 float cross1=exp(-pow((b-(52.0+.30*a+.002*a*a))/.55,2.0));
 float cross2=exp(-pow((b-(72.0-.10*a-.004*a*a))/.45,2.0));
 float wrist=exp(-pow((b-5.0-.02*a*a)/.50,2.0))+.4*exp(-pow((b+1.0-.015*a*a)/.35,2.0));
 float crease=(thenar*.75+cross1*.6+cross2*.55)*region+wrist*.55;
 return crease*palmar*(1.0-smoothstep(34.0,45.0,abs(a)));
}
float skinHeight(vec3 p){float creases=palmFolds(p);${creaseCalls}
 float grain=(noiseSkin(p*3.5)-.5)*.016+(noiseSkin(p*9.0)-.5)*.007;
 return grain-min(creases,1.4)*.14;
}
`;
skin.onBeforeCompile=s=>{
 skinCompile(s);s.uniforms.foldAmount=foldAmount;
 s.vertexShader=s.vertexShader.replace('#include <common>','#include <common>\nvarying vec3 vSkinRest; varying vec3 vSkinNormal;').replace('void main() {','void main() {\nvSkinRest=position;vSkinNormal=normal;');
 s.fragmentShader=s.fragmentShader.replace('#include <common>','#include <common>\n'+skinDetail).replace('#include <color_fragment>',`#include <color_fragment>
 float palmarSkin=smoothstep(-.2,.7,dot(normalize(vSkinNormal),${glv(P)}));
 float mottle=noiseSkin(vSkinRest*.23)-.5;
 diffuseColor.rgb*=mix(vec3(.86,.88,.88),vec3(1.05,1.0,.97),palmarSkin);
 diffuseColor.rgb*=1.0+mottle*.075;
 float hSkin=skinHeight(vSkinRest);diffuseColor.rgb*=1.0+min(hSkin,0.0)*.8;
 `).replace('#include <normal_fragment_maps>',`#include <normal_fragment_maps>
 // Surface gradient uses the posed tangent basis, keeping pores and folds attached.
 vec3 surfX=dFdx(vViewPosition),surfY=dFdy(vViewPosition);
 vec3 r1=cross(surfY,normal),r2=cross(normal,surfX);
 float det=dot(surfX,r1);vec3 grad=sign(det)*(dFdx(hSkin)*r1+dFdy(hSkin)*r2);
 normal=normalize(abs(det)*normal+grad);
 `);
};skin.customProgramCacheKey=()=> 'fw-dqs-skin-rest-3';
const bonePos=rest.map(p=>p.clone()),boneQ=rest.map(()=>new T.Quaternion()),lens=chains.map(c=>[1,2,3].map(i=>rest[c[i]].distanceTo(rest[c[i+1]]))),tl=[0,1,2].map(i=>rest[tc[i]].distanceTo(rest[tc[i+1]]));
function setBone(i,p,q){bonePos[i].copy(p);boneQ[i].copy(q);const d=p.clone().sub(rest[i].clone().applyQuaternion(q)),qr=new T.Quaternion(d.x,d.y,d.z,0).multiply(q);real[i].set(q.x,q.y,q.z,q.w);dual[i].set(qr.x*.5,qr.y*.5,qr.z*.5,qr.w*.5);}
function orient(i,start,end,oldEnd){const q=new T.Quaternion().setFromUnitVectors(oldEnd.clone().sub(rest[i]).normalize(),end.clone().sub(start).normalize());setBone(i,start,q);return q;}
const lower=[-.15,0,0],upper=[rad(95),rad(115),rad(85)];
function fk(base,lengths,h,q){let a=A;const points=[base.clone()];for(let j=0;j<3;j++){a-=q[j];points.push(points[j].clone().addScaledVector(h,Math.cos(a)*lengths[j]).addScaledVector(up,Math.sin(a)*lengths[j]));}return points;}
const solveCache=new Map();function solve(base,target,lengths){const cacheKey=[...base.toArray(),...target.toArray(),...lengths].map(v=>v.toFixed(6)).join(":");if(solveCache.has(cacheKey))return solveCache.get(cacheKey);const dx=target.x-base.x,dz=target.z-base.z,spread=T.MathUtils.clamp(Math.atan2(dx,-dz),-.68,.68),h=V(Math.sin(spread),0,-Math.cos(spread)),radial=V(dx,0,dz).dot(h),height=target.y-base.y;let best=null,score=Infinity;for(let d=-160;d<=75;d+=1){const end=rad(d),u=radial-lengths[2]*Math.cos(end),v=height-lengths[2]*Math.sin(end),cos=(u*u+v*v-lengths[0]**2-lengths[1]**2)/(2*lengths[0]*lengths[1]);if(cos<-1||cos>1)continue;const pip=Math.acos(cos),a=Math.atan2(v,u)+Math.atan2(lengths[1]*Math.sin(pip),lengths[0]+lengths[1]*Math.cos(pip)),q=[A-a,pip,a-pip-end];if(q.some((v,j)=>v<lower[j]||v>upper[j]))continue;const cost=(q[2]-.65*q[1])**2*.8+(end+1.10)**2*.1;if(cost<score){score=cost;best=q;}}
if(!best){let residual=Infinity;
 for(let m=0;m<=8;m++)for(let p=0;p<=8;p++)for(let d=0;d<=6;d++){
  const q=[lower[0]+(upper[0]-lower[0])*m/8,upper[1]*p/8,upper[2]*d/6];
  const error=fk(base,lengths,h,q)[3].distanceToSquared(target);
  if(error<residual){residual=error;best=q;}
 }
}const points=fk(base,lengths,h,best);const result={points,q:best,h,error:points[3].distanceTo(target)};if(solveCache.size>700)solveCache.delete(solveCache.keys().next().value);solveCache.set(cacheKey,result);return result;}
const jointGroup=new T.Group();hand.add(jointGroup);jointGroup.visible=false;const jmat=new T.MeshBasicMaterial({color:0x459379,depthTest:false}),jgeo=new T.SphereGeometry(1.1,10,8),dots=bonePos.map(()=>mesh(jgeo,jmat,jointGroup)),lines=[...chains,tc].map(c=>{const l=new T.Line(new T.BufferGeometry().setFromPoints(c.map(i=>rest[i])),new T.LineBasicMaterial({color:0x459379,depthTest:false}));jointGroup.add(l);return l;});
const armAxisPoints=Array.from({length:24},(_,i)=>canonical([-.03732416,.05598624+(23-i)/23*.02235756865,.00811395],true));armAxisPoints.push(rest[chains[1][0]],rest[chains[1][1]]);
const armAxis=new T.Line(new T.BufferGeometry().setFromPoints(armAxisPoints),new T.LineBasicMaterial({color:0x459379,depthTest:false}));armAxis.name='reference-forearm-axis';jointGroup.add(armAxis);
const contactGroup=new T.Group();world.add(contactGroup);contactGroup.visible=false;const contactMat=new T.MeshBasicMaterial({color:0x57bd94,transparent:true,opacity:.95,depthTest:false}),rings=Array.from({length:4},()=>{const o=mesh(new T.TorusGeometry(2.1,.32,8,20),contactMat,contactGroup);o.rotation.x=-Math.PI/2;o.renderOrder=6;return o;});
const fretContactMat=new T.MeshBasicMaterial({color:0xc78936,depthTest:false});const fretRings=Array.from({length:4},()=>{const o=mesh(new T.TorusGeometry(1.2,.25,8,20),fretContactMat,contactGroup);o.rotation.x=-Math.PI/2;o.renderOrder=5;return o;});
const nailMat=new T.MeshPhysicalMaterial({color:0xe8c5b2,roughness:.38,clearcoat:.25});const nails=Array.from({length:5},()=>mesh(new T.SphereGeometry(1,20,12),nailMat,hand));
function putNail(n,a,b,padNormal,width,length){const d=b.clone().sub(a).normalize(),normal=padNormal.clone().addScaledVector(d,-padNormal.dot(d)).normalize().negate(),x=d.clone().cross(normal).normalize(),y=normal.clone().cross(x);n.position.copy(a).lerp(b,.52).addScaledVector(normal,4.8);n.quaternion.setFromRotationMatrix(new T.Matrix4().makeBasis(x,y,normal));n.scale.set(width,length,.55);}
const padSamples=chains.map(c=>{
 const axis=rest[c[4]].clone().sub(rest[c[3]]),length=axis.length();axis.normalize();
 return verts.map((v,i)=>({v,i})).filter(({v})=>{const d=v.p.clone().sub(rest[c[3]]);return d.dot(axis)>length*.25&&v.p.distanceTo(rest[c[4]])<18;}).map(({i})=>i);
});
function skinVertex(i){
 let rx=0,ry=0,rz=0,rw=0,dx=0,dy=0,dz=0,dw=0;const ref=real[ids[i*4]];
 for(let k=0;k<4;k++){const j=ids[i*4+k],r=real[j],d=dual[j],w=weights[i*4+k]*(ref.dot(r)<0?-1:1);rx+=r.x*w;ry+=r.y*w;rz+=r.z*w;rw+=r.w*w;dx+=d.x*w;dy+=d.y*w;dz+=d.z*w;dw+=d.w*w;}
 const n=Math.hypot(rx,ry,rz,rw);rx/=n;ry/=n;rz/=n;rw/=n;dx/=n;dy/=n;dz/=n;dw/=n;const dot=rx*dx+ry*dy+rz*dz+rw*dw;dx-=rx*dot;dy-=ry*dot;dz-=rz*dot;dw-=rw*dot;
 const p=V(ps[i*3],ps[i*3+1],ps[i*3+2]).applyQuaternion(new T.Quaternion(rx,ry,rz,rw));
 return p.add(V(2*(rw*dx-dw*rx+ry*dz-rz*dy),2*(rw*dy-dw*ry+rz*dx-rx*dz),2*(rw*dz-dw*rz+rx*dy-ry*dx)));
}
function applyFinger(f,sol){const c=chains[f];for(let j=0;j<3;j++)orient(c[j+1],sol.points[j],sol.points[j+1],rest[c[j+2]]);setBone(c[4],sol.points[3],boneQ[c[3]]);}
function skinSupport(f){
 const samples=padSamples[f].map(i=>skinVertex(i));let min=Infinity;for(const p of samples)min=Math.min(min,p.y);
 // Smooth support patch (0.10 mm band) avoids jumps between mesh vertices.
 const p=V();let sum=0;for(const v of samples){const w=Math.exp(-(v.y-min)/.10);sum+=w;p.addScaledVector(v,w);}return p.multiplyScalar(1/sum);
}
const contactCache=new Map();
function solveContact(f,goal){
 const key=f+':'+goal.toArray().map(v=>v.toFixed(4)).join(':');if(contactCache.has(key)){const r=contactCache.get(key);applyFinger(f,r.sol);return r;}
 const tipGoal=goal.clone().addScaledVector(up,5);let sol,point,error=Infinity;
 for(let pass=0;pass<10;pass++){sol=solve(rest[chains[f][1]],tipGoal,lens[f]);applyFinger(f,sol);point=skinSupport(f);const delta=goal.clone().sub(point);error=delta.length();if(error<.025)break;tipGoal.addScaledVector(delta,.85);}
 const result={sol,point,error};if(contactCache.size>750)contactCache.delete(contactCache.keys().next().value);contactCache.set(key,result);return result;
}
function thumbPose(){const base=rest[tc[0]].clone(),baseWorld=base.clone().add(hand.position),dy=8,dx=-15,dz=-Math.sqrt(Math.max(.1,tl[0]**2-dy**2-dx**2)),mcp=base.clone().add(V(dx,dy,dz)),direction=V(-.20,.19,-.961).normalize(),ip=mcp.clone().addScaledVector(direction,tl[1]),tip=ip.clone().addScaledVector(direction,tl[2]),points=[base,mcp,ip,tip];
function frame(d,n){const y=d.clone().normalize(),z=n.clone().addScaledVector(y,-n.dot(y)).normalize(),x=y.clone().cross(z).normalize();return new T.Matrix4().makeBasis(x,y,z);}for(let j=0;j<3;j++){const i=tc[j],d=points[j+1].clone().sub(points[j]),old=rest[tc[j+1]].clone().sub(rest[i]);let q;if(j===0)q=new T.Quaternion().setFromUnitVectors(old.normalize(),d.normalize());else {const swing=new T.Quaternion().setFromUnitVectors(old.clone().normalize(),d.clone().normalize()),facing=new T.Quaternion().setFromRotationMatrix(frame(d,up).multiply(frame(old,P).invert()));q=swing.slerp(facing,Math.min(1,rad(20)/Math.max(.001,swing.angleTo(facing))));}setBone(i,points[j],q);}setBone(tc[3],tip,boneQ[tc[2]]);const thumbNormal=P.clone().applyQuaternion(boneQ[tc[2]]);putNail(nails[4],ip,tip,thumbNormal,5.0,5.4);return points;}

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
