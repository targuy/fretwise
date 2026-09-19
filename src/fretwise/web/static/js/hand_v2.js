/* Reference hand view: production transport + Notion reference skin/contact rig.
 * No local playback clock, note optimiser, message listener, or audio source.
 */
import * as THREE from "./vendor/three.module.min.js";
import {sampleMotion, MOTION_CAPABILITIES} from "./hand_motion.js";
import {HandPlanCompiler} from "./hand_compiler.js";
import {createReferenceRig} from "./hand_reference_rig.js";

const V = (x = 0, y = 0, z = 0) => new THREE.Vector3(x, y, z);
const toInternal = p => V(p[0] * 1000, p[2] * 1000, p[1] * 1000);

function disposeTree(object) {
  const geometries = new Set(), materials = new Set(), textures = new Set();
  object.traverse(o => {
    if (o.geometry) geometries.add(o.geometry);
    for (const m of [o.material, o.customDepthMaterial, o.customDistanceMaterial].flat().filter(Boolean)) {
      materials.add(m);
      for (const value of Object.values(m)) if (value?.isTexture) textures.add(value);
    }
  });
  geometries.forEach(g => g.dispose()); materials.forEach(m => m.dispose());
  textures.forEach(t => t.dispose());
}

/** Piecewise string path with explicit finger pins and supporting fret crowns. */
export function makeStringPath(geometry, stringNo, contacts) {
  const r = geometry.stringRadius(stringNo);
  const x0 = geometry.fretX(geometry.capo);
  const endpoint = x => [x, geometry.stringY(stringNo, x),
    geometry.surfaceZ(x, geometry.stringY(stringNo, x)) + geometry.freeHeight(x)];
  const pins = [endpoint(x0), ...contacts.map(c => {
    const p = c.targetM.slice(); p[2] -= r; return p;
  }).filter(p => p[0] > x0 && p[0] < geometry.scale).sort((a, b) => a[0] - b[0]), endpoint(geometry.scale)];
  const path = [];
  for (let i = 1; i < pins.length; i++) {
    const a = pins[i - 1], b = pins[i], points = [a];
    for (let f = geometry.capo + 1; f <= 24; f++) {
      const x = geometry.fretX(f);
      if (x > a[0] && x < b[0]) {
        const t = (x - a[0]) / (b[0] - a[0]);
        const y = a[1] + (b[1] - a[1]) * t;
        points.push([x, y, geometry.surfaceZ(x, y) + geometry.profile.fretHeight + r]);
      }
    }
    points.push(b);
    const hull = [];
    for (const p of points) {
      while (hull.length > 1) {
        const l = hull[hull.length - 2], m = hull[hull.length - 1];
        if ((m[2] - l[2]) * (p[0] - m[0]) > (p[2] - m[2]) * (m[0] - l[0])) break;
        hull.pop();
      }
      hull.push(p);
    }
    path.push(...(i > 1 ? hull.slice(1) : hull));
  }
  return path;
}

function stringTube(radius) {
  const capacity = 192, sides = 8;
  const positions = new Float32Array(capacity * sides * 3);
  const normals = new Float32Array(capacity * sides * 3);
  const indices = [];
  for (let i = 0; i < capacity - 1; i++) for (let s = 0; s < sides; s++) {
    const a = i * sides + s, b = i * sides + (s + 1) % sides;
    indices.push(a, b, a + sides, b, b + sides, a + sides);
  }
  const geometry = new THREE.BufferGeometry();
  geometry.setAttribute("position", new THREE.BufferAttribute(positions, 3).setUsage(THREE.DynamicDrawUsage));
  geometry.setAttribute("normal", new THREE.BufferAttribute(normals, 3).setUsage(THREE.DynamicDrawUsage));
  geometry.setIndex(indices);
  const mesh = new THREE.Mesh(geometry, new THREE.MeshStandardMaterial({color: 0xc6c2b4, metalness: .7, roughness: .34}));
  mesh.frustumCulled = false;
  let previousKey = "";
  return {mesh, update(path) {
    const key = path.map(p => p.map(x => x.toFixed(6)).join(",")).join(";");
    if (key === previousKey) return;
    previousKey = key;
    const nodes = [];
    for (let i = 1; i < path.length; i++) {
      const a = toInternal(path[i - 1]), b = toInternal(path[i]);
      const count = Math.max(1, Math.ceil(a.distanceTo(b) / 8));
      for (let k = 0; k < count; k++) nodes.push(a.clone().lerp(b, k / count));
    }
    nodes.push(toInternal(path.at(-1)));
    const count = Math.min(capacity, nodes.length);
    for (let i = 0; i < count; i++) {
      const tangent = nodes[Math.min(i + 1, count - 1)].clone().sub(nodes[Math.max(0, i - 1)]).normalize();
      const a = V(0, 0, 1), b = tangent.clone().cross(a).normalize();
      for (let s = 0; s < sides; s++) {
        const angle = s * Math.PI * 2 / sides;
        const normal = a.clone().multiplyScalar(Math.cos(angle)).addScaledVector(b, Math.sin(angle));
        const point = nodes[i].clone().addScaledVector(normal, radius * 1000);
        positions.set(point.toArray(), (i * sides + s) * 3);
        normals.set(normal.toArray(), (i * sides + s) * 3);
      }
    }
    geometry.setDrawRange(0, Math.max(0, count - 1) * sides * 6);
    geometry.attributes.position.needsUpdate = true; geometry.attributes.normal.needsUpdate = true;
  }};
}

/** Three.js component driven by renderAt(nominalScoreSec). */
export class HandV2View {
  constructor(container, options = {}) {
    this.container = container; this.options = options; this.disposed = false;
    this.compiler = new HandPlanCompiler();
    this.rate = 1; this.time = 0; this.generation = 0; this.plan = null;
    this.diagnostics = []; this.poseDiagnostics = []; this.cameraView = "fingers";
    this.theta = .9; this.phi = 1.1; this.zoom = 1; this.visible = true;
    this.renderer = new THREE.WebGLRenderer({antialias: true, alpha: false, powerPreference: "high-performance"});
    this.renderer.setPixelRatio(Math.min(globalThis.devicePixelRatio || 1, 1.6));
    this.renderer.outputColorSpace = THREE.SRGBColorSpace;
    this.renderer.toneMapping = THREE.ACESFilmicToneMapping;
    this.renderer.toneMappingExposure = 1.12;
    this.renderer.shadowMap.enabled = true; this.renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    this.renderer.domElement.style.cssText = "width:100%;height:100%;display:block;touch-action:none";
    this.renderer.domElement.setAttribute("aria-label", "Main gauche de référence, aperçu 3D illustratif");
    container.append(this.renderer.domElement);
    this.scene = new THREE.Scene(); this.scene.background = new THREE.Color(0x222b28);
    this.camera = new THREE.PerspectiveCamera(36, 1, 1, 2500);
    this.world = new THREE.Group(); this.scene.add(this.world);
    // The canonical bake is reflective; world correction retains LEFT laterality.
    this.world.scale.x = -1; this.world.rotation.set(Math.PI / 2 - .08, 0, .20, "ZYX");
    this.scene.add(new THREE.HemisphereLight(0xe9f1ed, 0x695449, 2));
    this.keyLight = new THREE.DirectionalLight(0xffead8, 2.6);
    this.keyLight.position.set(-100, 230, 220); this.keyLight.castShadow = true;
    this.keyLight.shadow.mapSize.set(1024, 1024);
    Object.assign(this.keyLight.shadow.camera, {left: -220, right: 220, top: 220, bottom: -220, near: 1, far: 900});
    this.keyLight.shadow.normalBias = .7; this.keyLight.shadow.bias = -.0002;
    this.scene.add(this.keyLight, this.keyLight.target);
    const fill = new THREE.DirectionalLight(0xc9e2ef, 1.6); fill.position.set(140, -100, -180); this.scene.add(fill);
    this.rig = createReferenceRig(this.world);
    this.instrumentGroup = new THREE.Group(); this.world.add(this.instrumentGroup);
    this.strings = [];
    this.badge = document.createElement("div");
    this.badge.setAttribute("role", "status");
    this.badge.style.cssText = "position:absolute;bottom:8px;left:8px;right:8px;font:11px/1.35 system-ui;color:#edece4;background:#19251dde;padding:5px 8px;border-radius:5px;pointer-events:none";
    this.badge.textContent = "Main v2 · modèle de référence · en attente de partition";
    container.append(this.badge);
    this.resizeObserver = new ResizeObserver(() => this.resize()); this.resizeObserver.observe(container);
    this.intersectionObserver = new IntersectionObserver(entries => {
      this.visible = entries[0]?.isIntersecting ?? true;
      if (this.visible) this.renderAt(this.time);
    }); this.intersectionObserver.observe(container);
    this.abort = new AbortController(); const signal = this.abort.signal;
    let point = null;
    this.renderer.domElement.addEventListener("pointerdown", e => {
      point = [e.clientX, e.clientY]; this.renderer.domElement.setPointerCapture(e.pointerId);
    }, {signal});
    this.renderer.domElement.addEventListener("pointermove", e => {
      if (!point) return;
      this.theta -= (e.clientX - point[0]) * .007;
      this.phi = Math.max(.1, Math.min(3, this.phi + (e.clientY - point[1]) * .006));
      point = [e.clientX, e.clientY]; this.renderAt(this.time);
    }, {signal});
    for (const name of ["pointerup", "pointercancel"]) this.renderer.domElement.addEventListener(name, () => { point = null; }, {signal});
    this.renderer.domElement.addEventListener("wheel", e => {
      e.preventDefault(); this.zoom = Math.max(.55, Math.min(2, this.zoom * Math.exp(e.deltaY * .001))); this.renderAt(this.time);
    }, {signal, passive: false});
    this.renderer.domElement.addEventListener("webglcontextlost", e => {
      e.preventDefault(); this.contextLost = true; this.badge.textContent = "WebGL interrompu · restauration en attente";
    }, {signal});
    this.renderer.domElement.addEventListener("webglcontextrestored", () => {
      this.contextLost = false; this.rig.clearCaches(); this.renderAt(this.time);
    }, {signal});
    this.resize();
  }

  getCapabilities() {
    return {protocolVersion: 1, schemaVersions: ["1.0", "1.1"], renderer: "v2-reference",
      status: "illustrative", techniques: [...MOTION_CAPABILITIES],
      handProfiles: [{id: "adult-reference-left", revision: "1"}],
      instrumentProfiles: [{id: "six-string-648", revision: "1"}],
      deformation: "dual-quaternion", handSides: ["left"],
      limitations: ["thumb-reference-pose", "barre-surface-unqualified", "global-collisions-unqualified", "bend-uncalibrated"]};
  }

  async setPerformance(performance) {
    this.clearPerformance("Main v2 · préparation des contacts…");
    const generation = ++this.generation;
    this.performance = performance;
    let plan;
    try {
      plan = await this.compiler.compile(performance,
        {playbackRate: this.rate, rigRevision: "generic-left-2026-09-14"});
    } catch (error) {
      if (error.name === "AbortError") return null;
      if (!this.disposed && generation === this.generation) {
        this.badge.textContent = `Main v2 indisponible · ${error.message}`;
      }
      throw error;
    }
    if (this.disposed || generation !== this.generation) return null;
    this.plan = plan; this.rig.clearCaches(); this.rig.hand.visible = true;
    this.rig.setDiagnostics(Boolean(this.diagnosticsEnabled));
    this.diagnostics = [...plan.diagnostics, {code: "REFERENCE_ASSET_ILLUSTRATIVE", severity: "info",
      message: "Modèle de référence : pouce, collisions globales et barrés non qualifiés.", noteIds: []}];
    this.buildInstrument(plan.geometry, performance.instrument.fretCount);
    this.options.onDiagnostics?.(this.getDiagnostics());
    this.renderAt(this.time);
    return {planId: plan.key, status: plan.status, diagnostics: this.getDiagnostics(), capabilities: this.getCapabilities()};
  }

  clearPerformance(message = "Main v2 · aucune performance disponible") {
    if (this.disposed) return;
    this.generation++; this.compiler.cancel(); this.rig.clearCaches();
    this.performance = null; this.plan = null; this.metrics = []; this.lastSample = null;
    this.diagnostics = []; this.poseDiagnostics = []; this.rig.hand.visible = false;
    this.rig.setDiagnostics(false);
    this.badge.textContent = message;
    this.options.onDiagnostics?.([]);
    // Render the cleared scene immediately: the canvas must not retain an old hand.
    if (!this.contextLost) this.renderer.render(this.scene, this.camera);
  }

  async setPlaybackRate(rate) {
    if (!Number.isFinite(rate) || rate <= 0) throw new Error("INVALID_PLAYBACK_RATE");
    if (rate === this.rate) return this.plan?.key;
    this.rate = rate;
    return this.performance ? this.setPerformance(this.performance) : null;
  }

  buildInstrument(geometry, fretCount) {
    disposeTree(this.instrumentGroup); this.instrumentGroup.clear(); this.strings = [];
    const boardMaterial = new THREE.MeshStandardMaterial({color: 0x4d3021, roughness: .62});
    const neckMaterial = new THREE.MeshStandardMaterial({color: 0x96724e, roughness: .5});
    const metal = new THREE.MeshStandardMaterial({color: 0xd7d6cf, metalness: .88, roughness: .28});
    const ivory = new THREE.MeshStandardMaterial({color: 0xe8dac0, roughness: .55});
    const add = (shape, material) => {const m = new THREE.Mesh(shape, material); m.castShadow = m.receiveShadow = true; this.instrumentGroup.add(m); return m;};
    const length = geometry.fretX(fretCount) * 1000 + 8;
    const width = geometry.profile.nutSpacing * 1000 + 10;
    const board = add(new THREE.BoxGeometry(length, 5, width), boardMaterial); board.position.set(length / 2, -3, 0);
    const shape = new THREE.Shape(); shape.moveTo(-width / 2, -5); shape.lineTo(width / 2, -5);
    for (let i = 0; i <= 48; i++) {const a = Math.PI * i / 48; shape.lineTo(width / 2 * Math.cos(a), -5 - 19 * Math.sin(a));}
    shape.closePath();
    const back = new THREE.ExtrudeGeometry(shape, {depth: length, bevelEnabled: false, steps: 1});
    // Rotate (u,v,w) -> (w,v,-u): orientation preserving.
    back.rotateY(Math.PI / 2); add(back, neckMaterial);
    for (let f = geometry.capo; f <= fretCount; f++) {
      const x = geometry.fretX(f);
      const radius = f === geometry.capo ? .0014 : .00065;
      const points = Array.from({length: 25}, (_, i) => {
        const y = (i / 24 - .5) * width / 1000;
        return toInternal([x, y, geometry.surfaceZ(x, y) + geometry.profile.fretHeight - radius]);
      });
      add(new THREE.TubeGeometry(new THREE.CatmullRomCurve3(points), 24, radius * 1000, 8, false), f === geometry.capo ? ivory : metal);
      if ([3, 5, 7, 9, 12, 15, 17, 19, 21, 24].includes(f)) {
        const dot = add(new THREE.CylinderGeometry(2, 2, .3, 16), ivory);
        dot.position.set((geometry.fretX(f - 1) + x) * 500, .1, 0);
      }
    }
    for (let s = 1; s <= geometry.count; s++) {
      const tube = stringTube(geometry.stringRadius(s)); tube.update(makeStringPath(geometry, s, []));
      this.instrumentGroup.add(tube.mesh); this.strings.push(tube);
    }
  }

  renderAt(nominalScoreSec) {
    if (this.disposed || !Number.isFinite(nominalScoreSec)) return;
    this.time = nominalScoreSec;
    if (!this.plan || !this.visible || this.contextLost || document.visibilityState === "hidden") return;
    const sample = sampleMotion(this.plan, nominalScoreSec);
    const measurements = this.rig.pose(sample, this.plan.geometry);
    this.poseDiagnostics = measurements.filter(m => m.active && !m.valid).map(m => ({
      code: "CONTACT_RESIDUAL", severity: "error", finger: m.finger, noteIds: m.noteIds,
      message: `Contact ${m.finger} : résidu ${m.errorMm.toFixed(2)} mm ; pose non qualifiée.`, errorMm: m.errorMm,
    }));
    this.lastSample = sample; this.metrics = measurements;
    for (let s = 1; s <= this.strings.length; s++) {
      const contacts = Object.values(sample.fingers).filter(f => f.stringNo === s && f.pressure01 > 0);
      this.strings[s - 1].update(makeStringPath(this.plan.geometry, s, contacts));
    }
    this.world.updateMatrixWorld(true);
    const active = measurements.filter(m => m.active);
    const center = active.length ? active.reduce((v, m) => v.add(toInternal(m.targetM)), V())
      .multiplyScalar(1 / active.length).add(V(8, -15, 16))
      : V(this.rig.hand.position.x + 20, -18, 35);
    const focus = this.world.localToWorld(center);
    const dist = (this.container.clientWidth < 480 ? 312 : 264) * this.zoom;
    this.camera.position.set(focus.x + dist * Math.sin(this.phi) * Math.sin(this.theta),
      focus.y + dist * Math.cos(this.phi), focus.z + dist * Math.sin(this.phi) * Math.cos(this.theta));
    this.camera.lookAt(focus); this.keyLight.target.position.copy(focus); this.keyLight.target.updateMatrixWorld();
    const issues = this.poseDiagnostics.length + sample.diagnostics.length;
    this.badge.textContent = `Main v2 · modèle de référence${issues ? ` · ${issues} contrainte(s) non résolue(s)` : " · pouce et collisions non qualifiés"}`;
    this.renderer.render(this.scene, this.camera);
  }

  setCamera(view) {
    const cameras = {fingers: [.9, 1.1], thumb: [3, 1.65], palm: [.25, 1.30], profile: [1.48, 1.25]};
    if (!cameras[view]) return;
    this.cameraView = view; [this.theta, this.phi] = cameras[view]; this.renderAt(this.time);
  }
  setCameraView(view) { this.setCamera(view); }
  getCameraView() { return this.cameraView; }
  setDiagnostics(enabled) {
    this.diagnosticsEnabled = Boolean(enabled);
    this.rig.setDiagnostics(this.diagnosticsEnabled && Boolean(this.plan)); this.renderAt(this.time);
  }
  getDiagnostics() { return [...this.diagnostics, ...this.poseDiagnostics]; }
  getMetrics() { return {fingers: this.metrics || [], planId: this.plan?.key,
    vertices: this.rig.geometry.attributes.position.count, triangles: this.rig.geometry.index.count / 3}; }
  resize() {
    if (this.disposed) return;
    const width = Math.max(1, this.container.clientWidth), height = Math.max(1, this.container.clientHeight);
    this.renderer.setSize(width, height, false); this.camera.aspect = width / height;
    this.camera.updateProjectionMatrix(); this.renderAt(this.time);
  }
  dispose() {
    if (this.disposed) return;
    this.disposed = true; this.generation++; this.abort.abort(); this.compiler.dispose();
    this.resizeObserver.disconnect(); this.intersectionObserver.disconnect();
    disposeTree(this.scene); this.rig.dispose(); this.renderer.dispose();
    this.renderer.domElement.remove(); this.badge.remove(); this.plan = null; this.performance = null;
  }
}

/** A construction error is surfaced to the host, which retains its SVG fallback. */
export function create(container, options = {}) { return new HandV2View(container, options); }
