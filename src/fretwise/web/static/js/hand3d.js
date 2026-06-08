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
/* Mid of the string band in SVG-pixel Y, mirroring the 2D board's
   (STRING_Y_TOP + STRING_Y_BOTTOM) / 2 = (230 + 350) / 2.  Used as the SVG-space
   anchor the tucked thumb runs *across* (in +Z) behind the neck, so the thumb
   sits opposite the middle finger regardless of the live hand position. */
const STRING_MID_Y = 290;
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

/* Vertical staging of the board hardware, measured against the confirmed D-neck
   flat fretboard top at y=-0.2 (see setGeometry TOP_Y).  Real frets stand proud
   of the wood and the strings float above the crowns, leaving an "action gap"
   the pressing fingertip must close.
     - FRET_TOP_Y = 0.55  → the crown tops sit 0.75 above the -0.2 wood top.
     - STRING_REST_Y = 1.1 → resting strings ride 0.55 above the crowns,
       i.e. the action gap a deflection animation (D2) will close. */
const FRET_TOP_Y = 0.55;
const STRING_REST_Y = 1.1;

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

/* Build-once tapered, rounded palm geometry (back-of-hand).  Replaces the old
   BoxGeometry(1,1,1): a unit-ish slab the palm POSE block in update() rescales to
   the live MCP span / depth / dome-thickness, so this stays a STATIC-geometry
   change — the rigid-palm kinematic contract (mcpL/mcpR/topX/topY/botY binding)
   is untouched.

   The cross-section is drawn in the Shape's local XY plane:
     - local X  = MCP span (palm width).  Half-width tapers from a WIDE knuckle
       edge to a NARROW wrist edge, with rounded corners (quadraticCurveTo).
     - local Y  = palm length (knuckle ↔ wrist depth).  The knuckle (wide) edge
       is placed at local -Y on purpose: after rotateX(-PI/2) local +Y maps to
       world +Z (the forearm side), so the wide edge lands on world -Z, the MCP /
       fingers side.  ORIENTATION INVARIANT — if it reads reversed in-browser,
       flip the Y sign of the knuckle/wrist edges (or add rotateY(PI)).
   ExtrudeGeometry then gives the slab its thickness (depth) + a soft bevel; a
   slight top dome rounds the back of the hand before normals are recomputed.

   Because update() rescales by (spanX, domeY, depthZ), the source slab is sized
   ~1 unit in each axis so those scales read as world units, exactly as the old
   box did. */
function makePalmGeometry() {
  // Half extents in the Shape's local XY plane (pre-rescale, ~unit slab).
  const KNUCKLE_HW = 0.5;   // wide edge half-width (MCP row, fingers side)
  const WRIST_HW = 0.32;    // narrow edge half-width (forearm side)
  const HALF_LEN = 0.5;     // half palm length along local Y
  const R = 0.16;           // corner rounding radius
  const yKnuckle = -HALF_LEN; // wide edge at -Y → world -Z (fingers) post-rotate
  const yWrist = HALF_LEN;    // narrow edge at +Y → world +Z (forearm)

  const shape = new THREE.Shape();
  // Start just inboard of the knuckle-left corner and trace clockwise:
  // knuckle (wide) edge → right side taper → wrist (narrow) edge → left taper.
  shape.moveTo(-KNUCKLE_HW + R, yKnuckle);
  shape.lineTo(KNUCKLE_HW - R, yKnuckle);
  shape.quadraticCurveTo(KNUCKLE_HW, yKnuckle, KNUCKLE_HW, yKnuckle + R);
  shape.lineTo(WRIST_HW, yWrist - R);
  shape.quadraticCurveTo(WRIST_HW, yWrist, WRIST_HW - R, yWrist);
  shape.lineTo(-WRIST_HW + R, yWrist);
  shape.quadraticCurveTo(-WRIST_HW, yWrist, -WRIST_HW, yWrist - R);
  shape.lineTo(-KNUCKLE_HW, yKnuckle + R);
  shape.quadraticCurveTo(-KNUCKLE_HW, yKnuckle, -KNUCKLE_HW + R, yKnuckle);

  const geo = new THREE.ExtrudeGeometry(shape, {
    depth: 0.7,
    bevelEnabled: true,
    bevelThickness: 0.18,
    bevelSize: 0.12,
    bevelSegments: 2,
    curveSegments: 8,
    steps: 1,
  });
  // Extrude pushes along local +Z; rotate so that axis becomes world thickness
  // (Y) and the cross-section's local Y (the taper) becomes world Z.
  geo.rotateX(-Math.PI / 2);
  geo.center();

  // Slight top dome: nudge vertices on the upper (back-of-hand) face outward in
  // +Y, peaking near the centre, so the back reads rounded rather than flat.
  const pos = geo.attributes.position;
  let maxY = -Infinity, minY = Infinity;
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i);
    if (y > maxY) maxY = y;
    if (y < minY) minY = y;
  }
  const yMid = (maxY + minY) / 2;
  const halfX = 0.5, halfZ = 0.5;
  for (let i = 0; i < pos.count; i++) {
    const y = pos.getY(i);
    if (y <= yMid) continue; // only lift the top face
    const nx = pos.getX(i) / halfX;
    const nz = pos.getZ(i) / halfZ;
    const dome = Math.max(0, 1 - (nx * nx + nz * nz)); // 0 at edges, 1 at centre
    pos.setY(i, y + dome * 0.18);
  }
  pos.needsUpdate = true;
  geo.computeVertexNormals();
  return geo;
}

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

    // Addressable string handles, (re)built by setGeometry().  D2 reads/writes
    // these per frame to deflect a pressed string toward the crown; the build
    // loop must be the ONLY place they are created.
    this.stringMeshes = [];

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

    // Fire-and-forget: load skin textures, then swap in the real hand mesh.
    // Both steps degrade gracefully (procedural fallback on any failure).
    this._loadTextures().then(() => this._loadHandMesh());

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
    // Palm: a tapered, rounded back-of-hand mesh spanning the four MCPs.  Built
    // once (static geometry); the POSE block in update() rescales it to the live
    // MCP span / depth / dome-thickness, exactly as it rescaled the old box.
    const palmGeo = makePalmGeometry();
    this.palm = new THREE.Mesh(palmGeo, this.skinMat);
    this.handGroup.add(this.palm);

    // Forearm stub running back toward the player (off the bottom of the SVG).
    this.forearm = makeBoneMesh(this.skinMat);
    this.handGroup.add(this.forearm);

    // Thumb: two short bones from a thumb base below the neck.
    this.thumbBones = [makeBoneMesh(this.skinMat), makeBoneMesh(this.skinMat)];
    this.thumbBones.forEach((b) => this.handGroup.add(b));
  }

  /* Load the three skin texture maps (color / normal / specular) and apply them
     to the shared skinMat.  The normal map is tiled 3× for skin micro-detail on
     the procedural capsule bones; the specular map drives roughness.  A reference
     to each loaded texture is kept so _loadHandMesh() can reuse them on the real
     palm mesh without a second network fetch. */
  async _loadTextures() {
    try {
      const loader = new THREE.TextureLoader();
      const [colorMap, normalMap, specMap] = await Promise.all([
        loader.loadAsync('/static/img/hand/HAND_C.jpg'),
        loader.loadAsync('/static/img/hand/HAND_N.jpg'),
        loader.loadAsync('/static/img/hand/HAND_S.jpg'),
      ]);
      // Normal map: tile at 3× for skin micro-detail on procedural capsule geometry.
      normalMap.wrapS = normalMap.wrapT = THREE.RepeatWrapping;
      normalMap.repeat.set(3, 3);
      // Specular map encodes roughness (bright = smooth, dark = rough for skin).
      specMap.wrapS = specMap.wrapT = THREE.RepeatWrapping;
      this.skinMat.normalMap = normalMap;
      this.skinMat.normalScale = new THREE.Vector2(0.6, 0.6);
      this.skinMat.roughnessMap = specMap;
      this.skinMat.roughness = 0.8;
      this.skinMat.needsUpdate = true;
      // Store for palm mesh UV-mapped texture (different from tiled normal).
      this._skinColorMap = colorMap;
      this._skinNormalMap = normalMap;
      this._skinSpecMap = specMap;
    } catch (e) {
      console.warn('hand3d: skin texture load failed, keeping flat material:', e);
    }
  }

  /* Replace the procedural ExtrudeGeometry palm with the real OBJ hand mesh
     (hand_mesh.js).  The mesh carries correct UV coordinates for the skin texture.
     We swap geometry + material on the EXISTING this.palm mesh so the update()
     pose block (position.set / scale.set) continues to work unchanged. */
  async _loadHandMesh() {
    try {
      const mod = await import('/static/js/vendor/hand_mesh.js');
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(mod.HAND_MESH_POSITIONS, 3));
      geo.setAttribute('uv',       new THREE.BufferAttribute(mod.HAND_MESH_UVS, 2));
      geo.setAttribute('normal',   new THREE.BufferAttribute(mod.HAND_MESH_NORMALS, 3));

      // Create a SEPARATE material for the palm that uses the color map (proper UVs).
      const palmMat = this.skinMat.clone();
      if (this._skinColorMap) {
        palmMat.map = this._skinColorMap;
        // Normal map for the real mesh: NOT tiled (use 1:1 UV mapping).
        if (this._skinNormalMap) {
          const nm = this._skinNormalMap.clone();
          nm.repeat.set(1, 1);
          palmMat.normalMap = nm;
        }
        palmMat.needsUpdate = true;
      }

      this.palm.geometry.dispose();
      this.palm.geometry = geo;
      this.palm.material = palmMat;

      // Normalise the cropped OBJ to the same unit-slab contract as
      // makePalmGeometry: center on the origin, then squash each axis
      // independently to span [-0.5, +0.5].  The per-frame update() block
      // applies the live MCP-derived palm scale, so the geometry itself must
      // arrive as a unit slab — any baked-in scale would compound with it and
      // produce the flat-pancake look.
      geo.computeBoundingBox();
      const box = geo.boundingBox;
      geo.translate(-(box.max.x + box.min.x) / 2, -(box.max.y + box.min.y) / 2, -(box.max.z + box.min.z) / 2);
      const sx = (box.max.x - box.min.x) || 1;
      const sy = (box.max.y - box.min.y) || 1;
      const sz = (box.max.z - box.min.z) || 1;
      geo.scale(1 / sx, 1 / sy, 1 / sz);
      // Re-orient OBJ axes into the slab convention used by the procedural palm:
      //   OBJ +X (wrist → knuckle)  → world +Z (palm depth)
      //   OBJ +Z (index → pinky)    → world +X (MCP span across strings)
      //   OBJ +Y (dorsal up)        → world +Y (unchanged)
      // A single rotateY(+π/2) realises this swap.
      //
      // ORIENTATION INVARIANT (load-time): if the dorsal side renders downward
      // or the thumb appears on the wrong side, flip to -Math.PI/2 or add a
      // geo.rotateZ(Math.PI) — this is the single knob for left-handed-grip
      // orientation of the cropped palm slab.
      geo.rotateY(Math.PI / 2);
      geo.computeVertexNormals();
      this._palmIsMesh = true;
    } catch (e) {
      // Silently fall back to the procedural palm slab on any failure (network,
      // parse, missing exports).  The procedural makePalmGeometry path keeps
      // the rig visually consistent — just untextured.
      console.warn('[hand3d] palm mesh load failed; using procedural palm', e);
      this._palmIsMesh = false;
      return;
    }
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
    // Board-edge inset: prefer the explicit slab edges the host exports so the
    // outer strings sit inboard of the neck edge identically to the SVG board.
    // Fall back to the historical stringTop/Bottom ± 24 when an older host ships
    // no boardTop/boardBot pair.
    const boardTop = (geom.boardTop !== undefined) ? geom.boardTop : (stringTop - 24);
    const boardBot = (geom.boardBot !== undefined) ? geom.boardBot : (stringBottom + 24);

    const boardMat = new THREE.MeshStandardMaterial({
      color: 0x0c0c0d, roughness: 0.85, metalness: 0.0,
    });
    const x0 = wx(NUT_X - 18);
    const x1 = wx(fretX(numFrets) + 10);
    const z0 = wz(boardTop);
    const z1 = wz(boardBot);
    // D cross-section neck: a flat fretboard top with a rounded belly behind it.
    // The cross-section lives in the Shape's local XY plane — local X = neck width
    // (mapped to world Z), local Y = neck depth.  ExtrudeGeometry pushes it along
    // local +Z by `length`, then rotateY(-PI/2) lays that extrude axis onto world X.
    //   - TOP_Y stays at -0.2 so the flat fretboard surface sits in the SAME plane
    //     the frets (~:249, y=-0.2) and strings and the hand's ROLE_LIFT assume.
    //   - BOTTOM_Y = -2.2 preserves the old slab's 2-unit thickness for the belly.
    const length = Math.abs(x1 - x0);
    const hw = Math.abs(z1 - z0) / 2; // half neck width (local X)
    const TOP_Y = -0.2;
    const BOTTOM_Y = -2.2;
    const profile = new THREE.Shape();
    profile.moveTo(-hw, TOP_Y);           // top-left corner of the flat fretboard
    profile.lineTo(hw, TOP_Y);            // flat fretboard surface (top edge)
    // Rounded belly: bulge down through the centre back to the left edge.
    profile.quadraticCurveTo(hw, BOTTOM_Y, 0, BOTTOM_Y);
    profile.quadraticCurveTo(-hw, BOTTOM_Y, -hw, TOP_Y);
    const boardGeom = new THREE.ExtrudeGeometry(profile, {
      depth: length, bevelEnabled: false, curveSegments: 24, steps: 1,
    });
    // Map the extrude axis (local +Z) onto world X.  After rotateY(-PI/2) the
    // solid spans world X from 0 to -length; translate(+length/2) recentres it
    // on its own midpoint so board.position.x can place it on the board centre.
    boardGeom.rotateY(-Math.PI / 2);
    boardGeom.translate(length / 2, 0, 0);
    boardGeom.computeVertexNormals();
    const board = new THREE.Mesh(boardGeom, boardMat);
    board.position.set((x0 + x1) / 2, 0, (z0 + z1) / 2);
    this.fretboardGroup.add(board);

    const fretMat = new THREE.MeshStandardMaterial({
      color: 0xb5b7bb, roughness: 0.4, metalness: 0.6,
    });
    // Wire bar width tracks the SVG fret-wire width (px → world via PX); keep the
    // historical 0.4 world-unit bar when the host exports no fretWireW.
    const wireW = (geom.fretWireW !== undefined) ? geom.fretWireW * PX : 0.4;
    // Raised, rounded crown: a thin cylinder laid across Z (the neck-width axis)
    // so its arc reads as a fret-wire crown standing proud of the wood.  Sized so
    // the crown top reaches FRET_TOP_Y above the -0.2 board top.  Radius = half
    // the wire bar width keeps the crown's footprint identical to the old box.
    const crownR = Math.max(0.2, wireW / 2);
    const crownCY = FRET_TOP_Y - crownR; // centre so the top tangent sits at FRET_TOP_Y
    for (let fr = 0; fr <= numFrets; fr++) {
      const fx = wx(fretX(fr));
      const wire = new THREE.Mesh(
        // Cylinder along +Y by default; rotate.x = PI/2 lays its long axis on Z
        // to span the neck width (z0..z1).
        new THREE.CylinderGeometry(crownR, crownR, Math.abs(z1 - z0), 12),
        fretMat
      );
      wire.rotation.x = Math.PI / 2;
      wire.position.set(fx, crownCY, (z0 + z1) / 2);
      this.fretboardGroup.add(wire);
    }

    const strMat = new THREE.MeshStandardMaterial({
      color: 0xc9ccd1, roughness: 0.3, metalness: 0.7,
    });
    // ADDRESSABLE STRINGS (scaffold for D2 deflection).  Each string is a thin
    // TubeGeometry following a straight rest path at STRING_REST_Y, floating the
    // action gap above the fret crowns (FRET_TOP_Y).  We keep a handle per string
    // — { mesh, sz, x0, x1, baseY, deflect, pressFret } — so D2 can re-path the
    // tube each frame WITHOUT re-touching this build loop.  The 12-segment tube
    // gives D2 enough vertices to bend the string toward a pressed crown.
    this.stringMeshes = [];
    const strX0 = (x0 < x1) ? x0 : x1;
    const strX1 = (x0 < x1) ? x1 : x0;
    for (let s = 1; s <= numStrings; s++) {
      const sz = wz(stringY(s));
      const path = new THREE.LineCurve3(
        new THREE.Vector3(strX0, STRING_REST_Y, sz),
        new THREE.Vector3(strX1, STRING_REST_Y, sz)
      );
      const tube = new THREE.TubeGeometry(path, 12, 0.18, 6, false);
      const str = new THREE.Mesh(tube, strMat);
      this.fretboardGroup.add(str);
      this.stringMeshes.push({
        mesh: str,
        sz,
        x0: strX0,
        x1: strX1,
        baseY: STRING_REST_Y,
        deflect: 0,
        pressFret: null,
      });
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
    //
    // CLEARANCE (B3): the old pose dropped the wrist to world Y=8 with a fat
    // radius-9 bone, so the underside (8 − 9 = −1) sank below the raised string
    // plane (STRING_REST_Y = 1.1) and the fret crowns (0.55) — the thick bone
    // visibly clipped UNDER / through the neck.  We now:
    //   1. Raise the wrist to Y≈14 and the elbow/back to Y≈18 so the underside
    //      (14 − 8 = 6) stays well above STRING_REST_Y; the whole bone rides
    //      over the strings rather than under the wood.
    //   2. Slim the radius 9 → 8 so the bone is less of a slab.
    //   3. Clamp the wrist to sit IN FRONT of the neck's near (low-E) edge in
    //      world Z.  SVG-y maps to world Z (wz), and larger SVG-y = larger Z =
    //      the near/player side; the neck's near edge is z1 = wz(boardBot)
    //      (the most-positive neck Z).  Pinning the wrist's effective SVG-y to
    //      ≥ that near edge keeps both forearm endpoints on the near side, so
    //      the bone never crosses under the neck width.
    if (kin.forearm) {
      const g = this.geom;
      // Near (low-E) edge of the neck in SVG-pixel Y.  Prefer the host's
      // explicit slab bottom; fall back to the same stringBottom+24 the board
      // build (setGeometry) uses when the host ships no boardBot.
      const nearEdgeY = g
        ? (g.boardBot !== undefined
            ? g.boardBot
            : (g.stringBottom !== undefined ? g.stringBottom + 24 : SCENE_H / 2))
        : SCENE_H / 2;
      // Keep the wrist on the near side of that edge (a few px of margin so the
      // forearm sits clearly in front of, not flush against, the low-E edge).
      const wristY = Math.max(kin.forearm.topY, nearEdgeY + 8);
      const wrist = this._toWorld({ x: kin.forearm.wristX, y: wristY }, 14);
      const back = this._toWorld({ x: kin.forearm.forearmX, y: SCENE_H + 60 }, 18);
      orientBone(this.forearm, back, wrist, 8);
    }

    // Thumb: two short, finger-gauge bones TUCKED BEHIND the neck (negative world
    // Y, i.e. on the far side of the -2.2 belly) and running mostly across +Z so
    // the pad opposes the strings the way a real thumb braces the neck.  We anchor
    // it laterally on the MIDDLE finger's MCP (read straight from the shared
    // snapshot) and run it across STRING_MID_Y, the mirror of the 2D string-band
    // mid, so the knuckle sits opposite the middle finger.  NOTE: this 3D thumb X
    // intentionally diverges from the 2D thumb stylization (kin.thumb.x); the 3D
    // rig brings it behind/under the neck instead of the SVG's side-on caricature.
    if (kin.thumb) {
      const midFk = kin.fingers && kin.fingers.middle;
      const lateralX = (midFk && midFk.ik && midFk.ik.mcp)
        ? midFk.ik.mcp.x          // align across from the middle MCP
        : kin.thumb.x;            // fallback if the middle finger is absent
      // Finger gauge with a slight proximal→distal taper (×1.05 / ×0.85), so the
      // tucked thumb reads finger-sized rather than the old 5/4 (~2× finger) club.
      const tr = Math.max(0.6, 22 * PX * 0.5);
      // Behind the slab: world Y descends -1.0 → -3.6 (the `lift` arg of
      // _toWorld IS world Y); SVG-y runs across the string band in +Z, with the
      // knuckle landing on STRING_MID_Y opposite the middle finger.
      const base = this._toWorld({ x: lateralX, y: STRING_MID_Y - 24 }, -1.0);
      const mid  = this._toWorld({ x: lateralX, y: STRING_MID_Y },      -2.3);
      const tip  = this._toWorld({ x: lateralX, y: STRING_MID_Y + 28 }, -3.6);
      orientBone(this.thumbBones[0], base, mid, tr * 1.05);
      orientBone(this.thumbBones[1], mid, tip, tr * 0.85);
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
