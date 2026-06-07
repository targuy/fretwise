/* ============================================================================
   FretWise — Milestone 5: optional three.js 3D rigged hand.

   This module is a PURELY ADDITIVE, opt-in alternative to the 2.5D SVG hand in
   hand_viz.html.  It is NEVER imported unless the feature flag is on (see
   hand_viz.html: `hand3dRequested()` / dynamic `import()`), so the default SVG
   experience is byte-for-byte unchanged and three.js is never even fetched in
   the default path.

   DESIGN — shared kinematics, no second model:
     The 3D rig does NOT fork a second kinematic solver.  hand_viz.html owns the
     single source of truth: the M3 anatomical rig (handScale, van der Hulst
     phalanx proportions, Shimawaki flexion bounds, DIP/PIP coupling) plus the
     HandSimulator (palm matrix, wrist roll, per-finger tip targets) and the
     solveFinger() IK that turns a tip target into {mcp, pip, dip, tip} joints.
     Each frame, hand_viz.html hands us that SAME solved joint data via
     `Hand3DRenderer.update(kin)`.  We only re-express those 2D joint positions
     as 3D bones — the angles, lengths and proportions all originate upstream.

     The 2.5D scene is laid out in an SVG pixel space (x: nut→bridge, y: high-E
     string at top → low-E at bottom).  We map that plane to the 3D world's XZ
     plane and lift joints off the fretboard by a small, role-driven Y (press =
     on the string, hover/idle = above it) so the same per-frame state reads as
     depth.  No new joint angles are invented here.

   DATA CONTRACT — identical payload:
     We consume nothing new from the network.  hand_viz.html still owns the
     postMessage contract (`fretwise-hand-data` / `fretwise-hand-seek`); the 3D
     renderer is downstream of the SAME frames/sim, so notes, fingers, planted
     barres and the drift-free playhead time-sync (M4) drive it unchanged.

   FALLBACK:
     If three.js fails to import or WebGL is unavailable, `create()` returns null
     and hand_viz.html stays on the SVG renderer — never a blank/broken panel.
   ============================================================================ */

import * as THREE from "./vendor/three.module.min.js";

/* The SVG scene is 1440×560 px.  Map that plane onto a centred XZ world plane
   roughly 1 world-unit ≈ 4 px so the camera framing is comfortable. */
const PX = 1 / 4;
const SCENE_W = 1440;
const SCENE_H = 560;
function wx(px) { return (px - SCENE_W / 2) * PX; }
function wz(py) { return (py - SCENE_H / 2) * PX; }

/* Role → colour, mirroring the SVG ROLE palette so the two renderers read the
   same at a glance (active amber, planted cyan, hover red, idle orange). */
const ROLE_COLOR = {
  active:  0xffcf74,
  planted: 0x8de5ff,
  hover:   0xff8d80,
  idle:    0xff9b3d,
};
const SKIN = 0xe2b694;

/* Lift (world Y, "up" out of the fretboard) per role: a pressed fingertip sits
   on the string plane (~0), a hovering finger floats just above, an idle finger
   curls back further up.  This is presentation only — it re-expresses the SAME
   per-frame role the shared sim already produced as 3D depth. */
const ROLE_LIFT = { active: 0.6, planted: 0.6, hover: 4.0, idle: 6.0 };

/* Detect a usable WebGL context without throwing.  Returning false here makes
   create() fall back to SVG cleanly. */
function webglAvailable() {
  try {
    const canvas = document.createElement("canvas");
    return !!(
      window.WebGLRenderingContext &&
      (canvas.getContext("webgl") || canvas.getContext("experimental-webgl"))
    );
  } catch (e) {
    return false;
  }
}

/* A single bone = a capsule (cylinder + rounded caps approximated by a
   stretched, oriented cylinder) between two world points.  Cheap and faithful
   enough for a "simple rigged hand". */
function makeBoneMesh(material) {
  // Unit cylinder along +Y, radius 1, height 1; scaled/oriented per frame.
  const geo = new THREE.CylinderGeometry(1, 1, 1, 10);
  const mesh = new THREE.Mesh(geo, material);
  mesh.castShadow = false;
  return mesh;
}
function makeJointMesh(material) {
  const geo = new THREE.SphereGeometry(1, 12, 10);
  return new THREE.Mesh(geo, material);
}

const _up = new THREE.Vector3(0, 1, 0);
function orientBone(mesh, a, b, radius) {
  const dir = new THREE.Vector3().subVectors(b, a);
  const len = dir.length() || 0.0001;
  mesh.position.copy(a).add(b).multiplyScalar(0.5);
  mesh.scale.set(radius, len, radius);
  mesh.quaternion.setFromUnitVectors(_up, dir.clone().normalize());
}

const FINGER_ORDER = ["index", "middle", "ring", "pinky"];

/**
 * Hand3DRenderer — builds a palm + 4 fingers × 3 phalanges + thumb in three.js
 * and re-poses them each frame from the shared kinematic snapshot.
 */
class Hand3DRenderer {
  constructor(container) {
    this.container = container;
    this.disposed = false;

    const w = container.clientWidth || SCENE_W;
    const h = container.clientHeight || SCENE_H;

    this.scene = new THREE.Scene();
    this.scene.background = new THREE.Color(0x12141a);

    this.camera = new THREE.PerspectiveCamera(38, w / h, 0.1, 2000);
    // Look down at the fretboard from above & slightly behind the player.
    this.camera.position.set(0, 150, 120);
    this.camera.lookAt(0, 0, 0);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "auto";
    this.renderer.domElement.style.display = "block";
    container.appendChild(this.renderer.domElement);

    this.scene.add(new THREE.AmbientLight(0xffffff, 0.65));
    const key = new THREE.DirectionalLight(0xffffff, 0.9);
    key.position.set(-60, 160, 80);
    this.scene.add(key);

    this.fretboardGroup = new THREE.Group();
    this.scene.add(this.fretboardGroup);

    this.handGroup = new THREE.Group();
    this.scene.add(this.handGroup);

    // Materials keyed by role; reused so we don't churn allocations per frame.
    this.skinMat = new THREE.MeshStandardMaterial({
      color: SKIN, roughness: 0.7, metalness: 0.0,
    });
    this.roleMats = {};
    for (const r in ROLE_COLOR) {
      this.roleMats[r] = new THREE.MeshStandardMaterial({
        color: ROLE_COLOR[r], roughness: 0.5, metalness: 0.05,
      });
    }

    this._buildFingers();
    this._buildPalmAndThumb();

    this._onResize = () => this.resize();
    window.addEventListener("resize", this._onResize);
  }

  /* Build the per-finger meshes once; per frame we only re-orient them.
     Each finger has 3 phalanx bones (proximal/middle/distal) and 4 joint
     spheres (mcp, pip, dip, tip), matching the {mcp,pip,dip,tip} the shared
     solveFinger() returns. */
  _buildFingers() {
    this.fingerMeshes = {};
    for (const f of FINGER_ORDER) {
      const bones = [
        makeBoneMesh(this.skinMat),
        makeBoneMesh(this.skinMat),
        makeBoneMesh(this.skinMat),
      ];
      const joints = [
        makeJointMesh(this.skinMat),
        makeJointMesh(this.skinMat),
        makeJointMesh(this.skinMat),
        makeJointMesh(this.skinMat),
      ];
      const tipCap = makeJointMesh(this.roleMats.idle);  // role-coloured tip
      const group = new THREE.Group();
      bones.forEach((b) => group.add(b));
      joints.forEach((j) => group.add(j));
      group.add(tipCap);
      this.handGroup.add(group);
      this.fingerMeshes[f] = { bones, joints, tipCap, group };
    }
  }

  _buildPalmAndThumb() {
    // Palm: a flattened rounded box spanning the four MCPs.
    const palmGeo = new THREE.BoxGeometry(1, 1, 1);
    this.palm = new THREE.Mesh(palmGeo, this.skinMat);
    this.handGroup.add(this.palm);

    // Forearm stub running back toward the player (off the bottom of the SVG).
    this.forearm = makeBoneMesh(this.skinMat);
    this.handGroup.add(this.forearm);

    // Thumb: two short bones from a thumb base below the neck.
    this.thumbBones = [makeBoneMesh(this.skinMat), makeBoneMesh(this.skinMat)];
    this.thumbBones.forEach((b) => this.handGroup.add(b));
  }

  /* Build (or rebuild) a simple fretboard slab + frets + strings from the
     geometry the host computed.  `geom` carries fretX()/stringY()/NUT_X etc. so
     the 3D board lines up with the same coordinate space as the hand. */
  setGeometry(geom) {
    this.geom = geom;
    // Clear any previous board meshes.
    while (this.fretboardGroup.children.length) {
      const c = this.fretboardGroup.children.pop();
      if (c.geometry) c.geometry.dispose();
      this.fretboardGroup.remove(c);
    }
    if (!geom) return;
    const { NUT_X, fretX, stringY, stringTop, stringBottom, numFrets, numStrings } = geom;

    const boardMat = new THREE.MeshStandardMaterial({
      color: 0x0c0c0d, roughness: 0.85, metalness: 0.0,
    });
    const x0 = wx(NUT_X - 18);
    const x1 = wx(fretX(numFrets) + 10);
    const z0 = wz(stringTop - 24);
    const z1 = wz(stringBottom + 24);
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(Math.abs(x1 - x0), 2, Math.abs(z1 - z0)),
      boardMat
    );
    board.position.set((x0 + x1) / 2, -1.2, (z0 + z1) / 2);
    this.fretboardGroup.add(board);

    const fretMat = new THREE.MeshStandardMaterial({
      color: 0xb5b7bb, roughness: 0.4, metalness: 0.6,
    });
    for (let fr = 0; fr <= numFrets; fr++) {
      const fx = wx(fretX(fr));
      const wire = new THREE.Mesh(
        new THREE.BoxGeometry(0.4, 1.2, Math.abs(z1 - z0)),
        fretMat
      );
      wire.position.set(fx, -0.2, (z0 + z1) / 2);
      this.fretboardGroup.add(wire);
    }

    const strMat = new THREE.MeshStandardMaterial({
      color: 0xc9ccd1, roughness: 0.3, metalness: 0.7,
    });
    for (let s = 1; s <= numStrings; s++) {
      const sz = wz(stringY(s));
      const str = new THREE.Mesh(
        new THREE.CylinderGeometry(0.18, 0.18, Math.abs(x1 - x0), 6),
        strMat
      );
      str.rotation.z = Math.PI / 2;
      str.position.set((x0 + x1) / 2, 0.3, sz);
      this.fretboardGroup.add(str);
    }
  }

  /* Per-frame re-pose from the SHARED kinematic snapshot.  `kin` is produced by
     hand_viz.html from the very same HandSimulator + solveFinger() the SVG path
     uses; this method only converts those 2D joint pixels into 3D bone meshes.

     kin = {
       fingers: { <name>: { ik: {mcp,pip,dip,tip}, role, fret, width } },
       palm:    { mcpL, mcpR, topX, topY, botY },
       forearm: { wristX, forearmX, topY },
       thumb:   { x, y, role },
     }
   */
  update(kin) {
    if (this.disposed || !kin) return;

    for (const f of FINGER_ORDER) {
      const fk = kin.fingers[f];
      const fm = this.fingerMeshes[f];
      if (!fk || !fm) continue;
      const { ik, role, width } = fk;
      const lift = ROLE_LIFT[role] !== undefined ? ROLE_LIFT[role] : ROLE_LIFT.idle;
      const r = Math.max(0.6, (width || 18) * PX * 0.5);

      // Joints in world space.  The proximal phalanx lifts most (knuckle up),
      // the fingertip drops to the string plane when pressing — a small linear
      // ramp along the chain reads as a finger curling down onto the board.
      const pts = [
        this._toWorld(ik.mcp, lift),
        this._toWorld(ik.pip, lift * 0.7),
        this._toWorld(ik.dip, lift * 0.4),
        this._toWorld(ik.tip, role === "active" || role === "planted" ? 0.2 : lift * 0.8),
      ];

      orientBone(fm.bones[0], pts[0], pts[1], r * 0.95);
      orientBone(fm.bones[1], pts[1], pts[2], r * 0.82);
      orientBone(fm.bones[2], pts[2], pts[3], r * 0.66);

      for (let i = 0; i < 4; i++) {
        const jr = r * (0.95 - i * 0.1);
        fm.joints[i].position.copy(pts[i]);
        fm.joints[i].scale.set(jr, jr, jr);
      }
      const tipR = r * 0.7;
      fm.tipCap.position.copy(pts[3]);
      fm.tipCap.scale.set(tipR, tipR, tipR);
      fm.tipCap.material = this.roleMats[role] || this.roleMats.idle;
    }

    // Palm slab across the MCP span.
    if (kin.palm) {
      const L = this._toWorld({ x: kin.palm.mcpL, y: kin.palm.botY }, 6);
      const R = this._toWorld({ x: kin.palm.mcpR, y: kin.palm.botY }, 6);
      const T = this._toWorld({ x: kin.palm.topX, y: kin.palm.topY }, 8);
      const cx = (L.x + R.x) / 2;
      const cz = (L.z + R.z + T.z) / 3;
      const cy = (L.y + R.y + T.y) / 3;
      this.palm.position.set(cx, cy, cz);
      this.palm.scale.set(Math.abs(R.x - L.x) + 6, 5, Math.abs(T.z - L.z) + 6);
    }

    // Forearm: from off-scene (player side) up to the wrist/palm top.
    if (kin.forearm) {
      const wrist = this._toWorld({ x: kin.forearm.wristX, y: kin.forearm.topY }, 8);
      const back = this._toWorld({ x: kin.forearm.forearmX, y: SCENE_H + 60 }, 14);
      orientBone(this.forearm, back, wrist, 9);
    }

    // Thumb: two short bones angling up from below the neck toward the index.
    if (kin.thumb) {
      const base = this._toWorld({ x: kin.thumb.x, y: kin.thumb.y }, 1.5);
      const mid = this._toWorld({ x: kin.thumb.x + 6, y: kin.thumb.y - 14 }, 3);
      const tip = this._toWorld({ x: kin.thumb.x + 10, y: kin.thumb.y - 28 }, 4);
      orientBone(this.thumbBones[0], base, mid, 5);
      orientBone(this.thumbBones[1], mid, tip, 4);
    }

    this.renderer.render(this.scene, this.camera);
  }

  _toWorld(p, lift) {
    return new THREE.Vector3(wx(p.x), lift || 0, wz(p.y));
  }

  resize() {
    if (this.disposed) return;
    const w = this.container.clientWidth || SCENE_W;
    const h = this.container.clientHeight || (w * SCENE_H) / SCENE_W;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
  }

  dispose() {
    this.disposed = true;
    window.removeEventListener("resize", this._onResize);
    try {
      this.renderer.dispose();
      if (this.renderer.domElement && this.renderer.domElement.parentNode) {
        this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
      }
    } catch (e) { /* best-effort teardown */ }
  }
}

/**
 * Factory: attempt to create a 3D renderer in `container`.  Returns null (so the
 * caller falls back to SVG) when WebGL is unavailable or three.js construction
 * throws.  three.js itself is only loaded because this module was imported, and
 * this module is only imported when the feature flag is on.
 */
export function create(container) {
  if (!webglAvailable()) return null;
  try {
    return new Hand3DRenderer(container);
  } catch (e) {
    // Any three.js/WebGL construction failure → SVG fallback, never a crash.
    return null;
  }
}

export { Hand3DRenderer, webglAvailable };
