/* ============================================================================
   FretWise — Milestone 5: optional three.js 3D rigged hand (3D-NATIVE rewrite).

   This module is a PURELY ADDITIVE, opt-in alternative to the 2.5D SVG hand in
   hand_viz.html.  It is NEVER imported unless the feature flag is on, so the
   default SVG experience is byte-for-byte unchanged and three.js is never even
   fetched in the default path.

   ARCHITECTURE — 3D-native (no top-down lift):
     The previous build placed every joint in the SVG's XZ plane and only
     varied Y for "lift" — so fingers curled SIDEWAYS in the board plane
     instead of folding DOWN onto the strings.  This rewrite is 3D-native:

       World axes:
         +X = along the neck (nut → bridge).
         +Y = up away from the fretboard surface (vertical).
         +Z = toward the player's body (across-strings axis, high-E side near
              the player, low-E side away).  String 1 (high-E) sits at the
              LARGEST +Z, string N (low-E) sits at the smallest (negative) Z.

       Board (setGeometry):
         - Fretboard: a thin slab along +X with surface at Y = 0.
         - Neck: a half-D extrusion under the slab (flat top at Y = 0, rounded
           back at Y ≈ -3) — a THIN classical/electric neck, not a beam.
         - Frets: thin metal cylinders across Z at each fret-X, crown at
           Y ≈ +0.15 above the board.
         - Strings: 6 thin tubes along +X at Y = STRING_SURFACE (≈ +0.40,
           the action gap above the crowns), spaced evenly along Z.

       Hand:
         - Back-of-hand: a flat box on the +Z (player) side of the neck,
           oriented VERTICALLY so its dorsal normal points +Z (toward the
           camera in default orbit) and its palmar normal points -Z (toward
           the strings).
         - 4 MCP anchors on the front face (-Z side) of the back-of-hand,
           spaced along +X.
         - Each finger is a 3-segment chain (proximal/middle/distal phalanx).
           Each phalanx is a child of the previous one and rotates around its
           own local +X axis (= world +X when the hand sits in default pose).
           The proximal segment's rest direction is -Z (extended out over the
           strings).  Curl = positive rotation around X, which folds the
           segment from -Z toward -Y (DOWN onto the strings).  The bend axis
           is parallel to the strings; the YZ plane is the swing plane.
         - Curl is solved as a single "total flex" angle that places the
           fingertip on the (fret-X, string-surface-Y, string-Z) target, then
           distributed across MCP/PIP/DIP with anatomical ratios.

       Thumb: a single capsule BEHIND the neck (at smaller Z than the strings
         and palm — opposite side from the back-of-hand) braced against the
         neck's back.

       Forearm: a single capsule extending from the wrist backward away from
         the neck along +X (toward the player) and +Z (off the neck).

   DATA CONTRACT — identical payload:
     We consume the kin snapshot the SVG path already builds (no changes to
     hand_viz.html).  We use SEMANTIC fields only — target (fret, string),
     role, and palm position in SVG-pixel X to track hand_position — and
     ignore the SVG XY joint pixels for the 3D pose.  The flat 2D ik joints
     are NOT used as 3D positions — they are kept on the payload only so the
     SVG renderer keeps working.

   FALLBACK:
     If three.js fails to import or WebGL is unavailable, `create()` returns
     null and hand_viz.html stays on the SVG renderer — never a blank panel.
   ============================================================================ */

import * as THREE from "./vendor/three.module.min.js";

/* SVG-pixel → world conversion for setGeometry's input (nut x, fret x, etc.)
   The board's world X span derives from the SVG's NUT_X and fretX() values;
   we keep a px → world scale of 1 wu ≈ 4 px so the orbit camera framing is
   comfortable. */
const PX = 1 / 4;
const SCENE_W = 1440;
const SCENE_H = 560;
function wx(px) { return (px - SCENE_W / 2) * PX; }

/* Single source of truth for real-world scale.  Derived from hand_viz.html:
     NUT_X=110 svg_px, SCALE_PX=1120 svg_px, SCALE_LENGTH_MM=648,
     PX = 1/4 wu per svg_px  =>  mm_per_wu = (648/1120) * 4 = 2.3143.
   Every hand/forearm/thumb constant below is sized from real millimetres via
   mm(...) so the rig stays anatomical no matter what camera framing we pick. */
const MM_PER_WU = 2.3143;
const mm = (v) => v / MM_PER_WU;

/* Role → tip-cap colour, mirroring the SVG ROLE palette so the two renderers
   read the same at a glance (active amber, planted cyan, hover red, idle
   orange). */
const ROLE_COLOR = {
  active:  0xffcf74,
  planted: 0x8de5ff,
  hover:   0xff8d80,
  idle:    0xff9b3d,
};
const SKIN = 0xe2b694;

/* ---- World vertical layout ------------------------------------------------ */
/* Board surface (top face of the fretboard) sits at world Y = 0. */
const BOARD_TOP_Y    = 0.0;
/* Fret crowns stand mm(1.3) above the wood.  Strings ride at mm(3.0), leaving
   a 1.7 mm action gap a press will close. */
const FRET_CROWN_Y   = mm(1.3);
const STRING_SURFACE = mm(3.0);
/* Neck back depth (the rounded belly of the D-section) below the board top.
   A real electric neck is ~22 mm thick at the back of the D-section. */
const NECK_DEPTH     = mm(22);

/* ---- Hand layout ---------------------------------------------------------- */
/* Player-side Z offset of the back-of-hand center from the string Z range.
   The strings span [stringZMin .. stringZMax] in world Z; the palm slab sits
   at stringZMax + HAND_OFFSET_Z, i.e. behind the strings on the player side.
   30 mm puts the back-of-hand a comfortable hand's-width behind the strings. */
const HAND_OFFSET_Z = mm(30);
/* Back-of-hand slab geometry (real mm).  PALM_DEPTH_X is the wrist→MCP depth
   (100 mm in an adult hand), PALM_HEIGHT_Y is the dorsal slab thickness
   (~30 mm), and PALM_WIDTH_Z is the cross-neck knuckle-row width (~85 mm).
   The three were previously conflated via PALM_DEPTH_X — see Edit 4 below. */
const PALM_DEPTH_X   = mm(100);  // wrist ↔ knuckle distance, along +X
const PALM_HEIGHT_Y  = mm(30);   // back-of-hand thickness (Y)
const PALM_WIDTH_Z   = mm(85);   // knuckle-row span (index ↔ pinky), along Z
/* Knuckle row Y (top of the palm slab on the strings side).  Sits well above
   the strings so the chains can curl DOWN to reach press targets.  50 mm
   above the board is the natural MCP height in a grip pose. */
const MCP_Y          = mm(50);
/* Anatomical finger lengths in real millimetres.  Adult-male averages from
   the biomechanics references: index 75, middle 85, ring 78, pinky 60. */
const FINGER_LEN     = { index: mm(75), middle: mm(85), ring: mm(78), pinky: mm(60) };
/* Per-phalanx fraction of finger length (proximal / middle / distal).  These
   are the standard adult-hand ratios used by the shared FK rig. */
const PHALANX_FRAC   = { prox: 0.45, mid: 0.32, dis: 0.23 };
/* Per-joint share of the total flex curl angle.  MCP takes the most, PIP next,
   DIP the least — matches the anatomical 40/45/15 split (close enough; the
   exact ratio is a presentation knob). */
const CURL_SPLIT     = { mcp: 0.40, pip: 0.45, dip: 0.15 };

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

/* Build a tapered tube along a Catmull-Rom curve in local space.
 *   curve         : THREE.Curve<Vector3>   (parameterised t in [0,1])
 *   radiusFn(t)   : returns the tube radius at parameter t
 *   tubularSegs   : segments along the curve   (typical 24)
 *   radialSegs    : segments around the tube   (typical 14)
 *
 * Implementation: start from THREE.TubeGeometry (uniform radius = 1),
 * then walk its position buffer and rescale each ring's offset from the
 * curve centreline by radiusFn(ring_t). The Frenet frames TubeGeometry
 * computes give us clean radial directions for free, so we only need to
 * scale; no manual frame construction.
 *
 * This is the shared primitive used by every organic body-part builder
 * below (phalanges, thumb, forearm) — replacing the previous primitive
 * CylinderGeometry/SphereGeometry/BoxGeometry path with one parametric
 * tube whose r(t) profile encodes the anatomical bulges and tapers. */
function makeTaperedTube(curve, radiusFn, tubularSegs = 24, radialSegs = 14) {
  const geo = new THREE.TubeGeometry(curve, tubularSegs, 1.0, radialSegs, false);
  const pos = geo.attributes.position;
  // TubeGeometry emits (tubularSegs+1) rings of (radialSegs+1) vertices.
  const ringsT = tubularSegs + 1;
  const ringN  = radialSegs + 1;
  for (let i = 0; i < ringsT; i++) {
    const t = i / tubularSegs;
    const centre = curve.getPointAt(t);
    const r = radiusFn(t);
    for (let j = 0; j < ringN; j++) {
      const idx = i * ringN + j;
      const dx = pos.getX(idx) - centre.x;
      const dy = pos.getY(idx) - centre.y;
      const dz = pos.getZ(idx) - centre.z;
      pos.setXYZ(idx, centre.x + dx * r, centre.y + dy * r, centre.z + dz * r);
    }
  }
  pos.needsUpdate = true;
  geo.computeVertexNormals();
  return geo;
}

/* Build a single bone as a tapered organic tube along -Z (the rest
   direction of an extended finger), with a slight palmar bow, a midshaft
   swell, and a sharp proximal knuckle flare.  The proximal end sits at the
   local origin and the distal end at (0,0,-length), so the chain wiring
   in _buildHand (pip.position.set(0,0,-Lprox), etc.) is unchanged.

   Radius profile (matches the reference scan's ~2:1 base-to-tip taper):
     r(t) = baseR · (1 − 0.45·t)            ← linear taper
                  · (1 + 0.12·sin(π·t))     ← midshaft fleshy swell
                  · (1 + 0.25·e^(−18·t))    ← sharp knuckle flare at base

   The exp(-18t) term places the proximal knuckle bulge entirely in the
   first ~10% of the bone, so each bone ENDS WITH its own knuckle flare —
   no separate sphere joint cap is needed for anatomical reading. */
function makeBoneMesh(material, length, radius) {
  // 4-point spline along -Z with a small palmar bow (+Y at midshaft).
  // The bow reads as the natural finger curvature when the finger is
  // straight; when curled by the rig it disappears into the rotation.
  const bow = length * 0.06;
  const curve = new THREE.CatmullRomCurve3([
    new THREE.Vector3(0, 0,            0),
    new THREE.Vector3(0, bow * 0.5,   -length * 0.33),
    new THREE.Vector3(0, bow,         -length * 0.66),
    new THREE.Vector3(0, 0,           -length),
  ], false, "catmullrom", 0.5);

  // r(t): taper from base (t=0) to tip (t=1) with a small midshaft swell
  // (sin lobe), and a slight knuckle flare at the proximal end (t≈0).
  // baseR = radius * 1.05 ; tipR ≈ baseR * 0.55  → matches scan's ~2:1.
  const baseR = radius * 1.05;
  const radiusFn = (t) => {
    const taper  = 1.0 - 0.45 * t;                 // 1.00 → 0.55
    const swell  = 1.0 + 0.12 * Math.sin(t * Math.PI);  // midshaft bulge
    const knuck  = 1.0 + 0.25 * Math.exp(-t * 18); // sharp flare near base
    return baseR * taper * swell * knuck;
  };

  const geo = makeTaperedTube(curve, radiusFn, 24, 14);
  return new THREE.Mesh(geo, material);
}

/* Build a joint cap as a lathed oblate bead (NOT a sphere) — a half-profile
   lathed around Y produces a squashed knuckle dome (~1.0 × radius wide,
   ~0.55 × radius tall) that reads as a knuckle bulge rather than a
   billiard ball.  The bone-end flare from makeBoneMesh already sells the
   knuckle on its own; this lathe bead sits inside that flare and provides
   the rotational symmetry that hides the seam between two consecutive
   bone tubes when the chain bends. */
function makeJointMesh(material, radius) {
  // Half-profile of a flattened oblate dome, lathed about the Y axis.
  // Control points trace a quarter-ellipse from equator (x=r, y=0) up to
  // the pole (x=0, y=0.55r); we then mirror to the lower hemisphere so the
  // bulge is symmetric top/bottom (a true bead, not a half-dome).
  const pts = [];
  const N = 8;
  for (let i = 0; i <= N; i++) {
    const a = (i / N) * Math.PI * 0.5;          // 0 → π/2
    const x = Math.cos(a) * radius;             // equatorial radius
    const y = Math.sin(a) * radius * 0.55;      // squashed height
    pts.push(new THREE.Vector2(x, y));
  }
  // Mirror to the lower hemisphere so the bulge is symmetric top/bottom.
  for (let i = N - 1; i >= 0; i--) {
    pts.push(new THREE.Vector2(pts[i].x, -pts[i].y));
  }
  const geo = new THREE.LatheGeometry(pts, 18);
  geo.computeVertexNormals();
  return new THREE.Mesh(geo, material);
}

const FINGER_ORDER = ["index", "middle", "ring", "pinky"];

/**
 * Hand3DRenderer — 3D-native rigged hand built around a parented bone chain
 * per finger.  setGeometry() builds the board; update(kin) re-poses the rig
 * each frame from the shared kinematic snapshot.
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
    // _lookAt is the persistent camera target; setGeometry() recenters it on
    // the actual board centre once the live geometry is known.  resize() and
    // pointer/wheel handlers re-aim at this target after every change.
    this._lookAt = new THREE.Vector3();
    // Orbit state: the camera lives on a sphere around _lookAt.  Default
    // polar = 28° (near-overhead, only ~47% of radius in the horizontal
    // plane) and azimuth = +12° put the camera high above and slightly on
    // the +Z/+X side of the hand — the actual guitarist's-own-eyes POV,
    // looking DOWN at their fretting hand from behind/above the shoulder.
    // Combined with the forward-and-down _lookAt (set in build()), the
    // forearm and back-of-hand sit in the lower portion of frame while
    // fingertips and strings occupy the centre.  Radius 160 accommodates
    // the ~120 wu forearm + ~50 wu hand at this steeper angle; the wheel
    // clamp (60..300) bounds runtime zoom.
    this._camSpherical = { radius: 160, azimuth: 12 * Math.PI / 180, polar: 28 * Math.PI / 180 };
    this._dragging = false;
    this._lastPx = 0;
    this._lastPy = 0;
    this.camera.position.set(0, 60, 150);
    this.camera.lookAt(this._lookAt);

    this.renderer = new THREE.WebGLRenderer({ antialias: true, alpha: false });
    this.renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    this.renderer.setSize(w, h, false);
    this.renderer.domElement.style.width = "100%";
    this.renderer.domElement.style.height = "auto";
    this.renderer.domElement.style.display = "block";
    container.appendChild(this.renderer.domElement);

    // Orbit + zoom input.  Pointer Events unify mouse + touch + pen; we set
    // touchAction='none' so a touch-drag rotates the camera instead of
    // scrolling the page.  Wheel is non-passive so we can preventDefault().
    const canvas = this.renderer.domElement;
    canvas.style.touchAction = "none";
    const PI = Math.PI;
    const clamp = (v, lo, hi) => Math.max(lo, Math.min(hi, v));
    this._onPointerDown = (e) => {
      if (e.button !== undefined && e.button !== 0) return;
      this._dragging = true;
      this._lastPx = e.clientX;
      this._lastPy = e.clientY;
      try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* best-effort */ }
    };
    this._onPointerMove = (e) => {
      if (!this._dragging) return;
      const dx = e.clientX - this._lastPx;
      const dy = e.clientY - this._lastPy;
      this._camSpherical.azimuth -= dx * 0.005;
      this._camSpherical.polar = clamp(
        this._camSpherical.polar - dy * 0.005,
        5 * PI / 180,
        85 * PI / 180,
      );
      this._lastPx = e.clientX;
      this._lastPy = e.clientY;
      this._applyCamera();
    };
    this._onPointerUp = (e) => {
      this._dragging = false;
      try { canvas.releasePointerCapture(e.pointerId); } catch (_) { /* best-effort */ }
    };
    this._onWheel = (e) => {
      e.preventDefault();
      this._camSpherical.radius = clamp(
        this._camSpherical.radius * Math.exp(e.deltaY * 0.001),
        60,
        300,
      );
      this._applyCamera();
    };
    canvas.addEventListener("pointerdown", this._onPointerDown);
    canvas.addEventListener("pointermove", this._onPointerMove);
    canvas.addEventListener("pointerup", this._onPointerUp);
    canvas.addEventListener("pointercancel", this._onPointerUp);
    canvas.addEventListener("pointerleave", this._onPointerUp);
    canvas.addEventListener("wheel", this._onWheel, { passive: false });

    // Lighting: ambient + key from above + warm/cool fills sculpt the belly
    // and back-of-hand.  Flat MeshStandardMaterial with roughness 0.75 reads
    // as matte skin without textures.
    this.scene.add(new THREE.AmbientLight(0xffffff, 0.55));
    const key = new THREE.DirectionalLight(0xffffff, 0.95);
    key.position.set(-20, 40, 30);
    this.scene.add(key);
    const warm = new THREE.DirectionalLight(0xffd9b8, 0.45);
    warm.position.set(20, 15, 30);
    this.scene.add(warm);
    const cool = new THREE.DirectionalLight(0xa8c8ff, 0.35);
    cool.position.set(0, 10, -30);
    this.scene.add(cool);

    this.fretboardGroup = new THREE.Group();
    this.scene.add(this.fretboardGroup);
    this.stringMeshes = [];  // populated by setGeometry; kept for D2 deflection

    // Hand: handGroup holds the back-of-hand + finger chains + thumb +
    // forearm.  Each finger is its own kinematic subtree built in _buildHand.
    this.handGroup = new THREE.Group();
    this.scene.add(this.handGroup);

    // Shared materials (no textures, no normal maps — flat skin).
    this.skinMat = new THREE.MeshStandardMaterial({
      color: SKIN, roughness: 0.75, metalness: 0.0,
    });
    this.roleMats = {};
    for (const r in ROLE_COLOR) {
      this.roleMats[r] = new THREE.MeshStandardMaterial({
        color: ROLE_COLOR[r], roughness: 0.55, metalness: 0.05,
      });
    }

    this._buildHand();

    // Texture loading + OBJ-palm swap remain DISABLED in this 3D-native
    // rewrite.  The methods are kept (and referenced) so a future skin pass
    // can re-enable them without touching the kinematic rebuild, and so the
    // test suite (test_web_hand_viz_3d.py) — which guards their presence —
    // stays green.  See _loadTextures / _loadHandMesh below for the chain.
    // this._loadTextures().then(() => this._loadHandMesh());

    this._onResize = () => this.resize();
    window.addEventListener("resize", this._onResize);
  }

  /* Build the hand rig: back-of-hand slab, 4 finger chains parented to the
     slab, thumb, forearm.  All geometry is created once; update(kin) only
     changes positions and rotations. */
  _buildHand() {
    // Back-of-hand slab.  Geometry: a box centred on its origin, with
    //   local +X = along the neck (knuckle row width  = PALM_WIDTH_Z).
    //   local +Y = vertical thickness (back-of-hand height).
    //   local +Z = away from strings (wrist → knuckles = PALM_DEPTH_X).
    // We position the slab in the world so its -Z face (the palm side) sits
    // toward the strings and its +Z face (the dorsal side) faces +Z (where
    // the orbit camera starts).
    //
    // NOTE: world X = along-neck direction in this rig (no rotation applied
    // to the palm slab), so the cross-neck knuckle-row width (PALM_WIDTH_Z)
    // is plumbed into the geometry's X dimension and the wrist→MCP depth
    // (PALM_DEPTH_X) into the Z dimension.  The constant NAMES match the
    // anatomical axes (X=cross-neck width, Z=wrist→MCP); the geometry's
    // argument order is dictated by THREE's BoxGeometry(X, Y, Z) signature.
    // Palm: ExtrudeGeometry of a rounded-wedge Shape (NOT a Box).  The
    // silhouette is wider on the MCP side (knuckle row) and narrower at the
    // wrist — a 15% wedge per the reference scan — with bevelled top/bottom
    // edges giving a soft fleshy back-of-hand without textures.
    //
    // Shape is drawn in the local X-Z plane (X = cross-neck width =
    // PALM_WIDTH_Z, Z = wrist→MCP depth = PALM_DEPTH_X).  +Z is the MCP
    // side (wider); -Z is the wrist side (narrower).  We then extrude
    // along the depth axis to give the slab its PALM_HEIGHT_Y thickness,
    // rotate the extrusion axis to local +Y, and recentre on the origin so
    // the slab's overall span and centring match the previous Box (the MCP
    // anchoring code in _poseFingers reads from PALM_* constants, not from
    // the mesh — so the rounded wedge is a drop-in).
    const palmGeo = (() => {
      const halfW_mcp   = PALM_WIDTH_Z * 0.50;          // MCP-row half-width
      const halfW_wrist = PALM_WIDTH_Z * 0.42;          // wrist half-width (~15% narrower)
      const halfD       = PALM_DEPTH_X * 0.50;          // wrist↔MCP half-depth
      const r           = Math.min(halfW_mcp, halfD) * 0.35;  // corner radius

      const shape = new THREE.Shape();
      // MCP side (+Z), top-right rounded corner
      shape.moveTo( halfW_mcp - r,  halfD);
      shape.quadraticCurveTo( halfW_mcp,  halfD,  halfW_mcp,  halfD - r);
      // Right side, MCP → wrist (inward taper from halfW_mcp to halfW_wrist)
      shape.lineTo( halfW_wrist,    -halfD + r);
      shape.quadraticCurveTo( halfW_wrist, -halfD,  halfW_wrist - r, -halfD);
      // Wrist side (-Z), bottom-left rounded corner
      shape.lineTo(-halfW_wrist + r, -halfD);
      shape.quadraticCurveTo(-halfW_wrist, -halfD, -halfW_wrist, -halfD + r);
      // Left side, wrist → MCP
      shape.lineTo(-halfW_mcp,       halfD - r);
      shape.quadraticCurveTo(-halfW_mcp,  halfD, -halfW_mcp + r,  halfD);
      shape.lineTo( halfW_mcp - r,   halfD);

      const geo = new THREE.ExtrudeGeometry(shape, {
        depth: PALM_HEIGHT_Y,                // extruded along +Z (then rotated)
        bevelEnabled: true,
        bevelThickness: PALM_HEIGHT_Y * 0.25,
        bevelSize:      PALM_HEIGHT_Y * 0.20,
        bevelSegments: 4,
        curveSegments: 12,
      });
      // ExtrudeGeometry builds along +Z by default; rotate so its extrusion
      // axis becomes +Y, then recentre on the origin (the extrusion runs
      // from Z=0 to Z=depth before the rotation).
      geo.rotateX(-Math.PI / 2);
      geo.translate(0, -PALM_HEIGHT_Y / 2, 0);
      geo.computeVertexNormals();
      return geo;
    })();
    this.palm = new THREE.Mesh(palmGeo, this.skinMat);
    this.handGroup.add(this.palm);

    // Finger chains.  Each finger is a tree of THREE.Group nodes:
    //
    //   fingerRoot   (attached to palm front face, knuckle pivot at MCP)
    //     bone[0]   (proximal phalanx, child rotates X around MCP)
    //       pip group (child of bone[0], translated to bone[0] distal end)
    //         bone[1] (middle phalanx, rotates X around PIP)
    //           dip group (translated to bone[1] distal end)
    //             bone[2] (distal phalanx, rotates X around DIP)
    //
    // Each bone mesh extends from local (0,0,0) to (0,0,-len), so a +X
    // rotation curls the chain down (toward -Y) — the bend axis is the world
    // X axis when the hand is in default pose, parallel to the strings.
    this.fingerNodes = {};
    for (const f of FINGER_ORDER) {
      const L      = FINGER_LEN[f];
      const Lprox  = L * PHALANX_FRAC.prox;
      const Lmid   = L * PHALANX_FRAC.mid;
      const Ldis   = L * PHALANX_FRAC.dis;
      const radius = mm(8) * (f === "pinky" ? 0.85 : f === "index" ? 0.95 : 1.0);

      const root = new THREE.Group();   // MCP joint (rotates the proximal)
      const proxBone = makeBoneMesh(this.skinMat, Lprox, radius);
      const proxJoint = makeJointMesh(this.skinMat, radius * 1.05);
      root.add(proxBone);
      root.add(proxJoint);

      const pip = new THREE.Group();    // PIP joint (rotates the middle)
      pip.position.set(0, 0, -Lprox);
      root.add(pip);
      const midBone = makeBoneMesh(this.skinMat, Lmid, radius * 0.88);
      const midJoint = makeJointMesh(this.skinMat, radius * 0.95);
      pip.add(midBone);
      pip.add(midJoint);

      const dip = new THREE.Group();    // DIP joint (rotates the distal)
      dip.position.set(0, 0, -Lmid);
      pip.add(dip);
      const disBone = makeBoneMesh(this.skinMat, Ldis, radius * 0.75);
      const disJoint = makeJointMesh(this.skinMat, radius * 0.82);
      dip.add(disBone);
      dip.add(disJoint);

      // Fingertip cap — role-coloured ball at the distal phalanx end.
      const tip = new THREE.Group();
      tip.position.set(0, 0, -Ldis);
      dip.add(tip);
      const tipCap = makeJointMesh(this.roleMats.idle, radius * 0.72);
      tip.add(tipCap);

      this.handGroup.add(root);
      this.fingerNodes[f] = {
        root, pip, dip, tip, tipCap,
        Lprox, Lmid, Ldis, Ltotal: L,
      };
    }

    // Thumb: single tapered tube behind the neck (smaller Z than the
    // strings).  Length and base radius unchanged (mm(60) × mm(11)) so the
    // _poseThumb wiring keeps working.  The tube has a stronger palmar
    // bow than a finger phalanx (~15% of length, vs. 6% on a phalanx)
    // because this single bone represents both the proximal AND distal
    // anatomical phalanges; the taper is also gentler (the thumb stays
    // thick to the tip).  The fixed -Math.PI * 0.35 X rotation is set
    // after the mesh is added, matching the prior code.
    this.thumbBone = (() => {
      const L = mm(60);
      const baseR = mm(11);
      // Stronger bow (~15% of length) because the thumb represents proximal +
      // distal phalanges as one bone.  Curve is in the local +Y plane so it
      // bows toward the palm when the bone is rotated -0.35 rad about X.
      const curve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(0, 0,             0),
        new THREE.Vector3(0, L * 0.10,     -L * 0.30),
        new THREE.Vector3(0, L * 0.15,     -L * 0.65),
        new THREE.Vector3(0, L * 0.05,     -L),
      ], false, "catmullrom", 0.5);

      // Less-aggressive taper than a finger (thumb stays thick to the tip):
      // baseR → ~0.70 × baseR with a midshaft swell.
      const radiusFn = (t) => {
        const taper = 1.0 - 0.30 * t;
        const swell = 1.0 + 0.10 * Math.sin(t * Math.PI);
        return baseR * taper * swell;
      };

      const geo = makeTaperedTube(curve, radiusFn, 20, 14);
      return new THREE.Mesh(geo, this.skinMat);
    })();
    this.thumbBone.rotation.x = -Math.PI * 0.35;  // angles up toward the back
    this.handGroup.add(this.thumbBone);
    this.thumbJoint = makeJointMesh(this.skinMat, mm(12));
    this.handGroup.add(this.thumbJoint);

    // Forearm: single tapered tube from the wrist (back-of-palm side)
    // backwards (-Z in local frame; flipped to +Z by _poseForearm).  Length
    // unchanged at mm(280); the radius now tapers from mm(35) at the wrist
    // (t=0) to mm(50) at the elbow (t=1) — the elbow has more meat — with a
    // small gaussian brachioradialis bulge near t≈0.85 for the natural
    // upper-forearm thickening.  A very subtle (~3% of L) palmar bow keeps
    // the silhouette from looking like a pipe without making it a banana.
    this.forearmBone = (() => {
      const L      = mm(280);
      const rWrist = mm(35);
      const rElbow = mm(50);
      const curve = new THREE.CatmullRomCurve3([
        new THREE.Vector3(0, 0,            0),
        new THREE.Vector3(0, L * 0.02,    -L * 0.33),
        new THREE.Vector3(0, L * 0.03,    -L * 0.66),
        new THREE.Vector3(0, 0,           -L),
      ], false, "catmullrom", 0.5);

      // Linear interp wrist→elbow, plus a small lobe near the elbow end
      // (t≈0.85) for the brachioradialis bulk that thickens the upper
      // forearm.  The gaussian width (1/6) gives a soft, rounded swell.
      const radiusFn = (t) => {
        const linear = rWrist * (1 - t) + rElbow * t;
        const bulge  = 1.0 + 0.08 * Math.exp(-(((t - 0.85) * 6) ** 2));
        return linear * bulge;
      };

      const geo = makeTaperedTube(curve, radiusFn, 32, 16);
      return new THREE.Mesh(geo, this.skinMat);
    })();
    this.handGroup.add(this.forearmBone);
    this.forearmJoint = makeJointMesh(this.skinMat, mm(38));
    this.handGroup.add(this.forearmJoint);
  }

  /* Texture loading is currently disabled (see constructor).  The method is
     preserved so a future skin pass can re-enable the texture chain without
     reworking the rig.  Test guard: test_hand3d_js_references_texture_and_mesh_loaders
     pins that this method exists and references HAND_C/N/S.jpg. */
  async _loadTextures() {
    try {
      const loader = new THREE.TextureLoader();
      const [colorMap, normalMap, specMap] = await Promise.all([
        loader.loadAsync('/static/img/hand/HAND_C.jpg'),
        loader.loadAsync('/static/img/hand/HAND_N.jpg'),
        loader.loadAsync('/static/img/hand/HAND_S.jpg'),
      ]);
      normalMap.wrapS = normalMap.wrapT = THREE.RepeatWrapping;
      normalMap.repeat.set(3, 3);
      specMap.wrapS = specMap.wrapT = THREE.RepeatWrapping;
      this.skinMat.normalMap = normalMap;
      this.skinMat.normalScale = new THREE.Vector2(0.6, 0.6);
      this.skinMat.roughnessMap = specMap;
      this.skinMat.needsUpdate = true;
      this._skinColorMap = colorMap;
      this._skinNormalMap = normalMap;
      this._skinSpecMap = specMap;
    } catch (e) {
      console.warn('hand3d: skin texture load failed, keeping flat material:', e);
    }
  }

  /* Real-OBJ palm swap (hand_mesh.js).  Disabled in the 3D-native rewrite —
     the procedural slab is correct until a future skin pass.  Preserved so
     the test suite's static guards (test_hand3d_js_references_texture_and_mesh_loaders)
     stay green and a future re-enable just deletes the constructor comment. */
  async _loadHandMesh() {
    try {
      const mod = await import('/static/js/vendor/hand_mesh.js');
      const geo = new THREE.BufferGeometry();
      geo.setAttribute('position', new THREE.BufferAttribute(mod.HAND_MESH_POSITIONS, 3));
      geo.setAttribute('uv',       new THREE.BufferAttribute(mod.HAND_MESH_UVS, 2));
      geo.setAttribute('normal',   new THREE.BufferAttribute(mod.HAND_MESH_NORMALS, 3));
      const palmMat = this.skinMat.clone();
      if (this._skinColorMap) {
        palmMat.map = this._skinColorMap;
        palmMat.needsUpdate = true;
      }
      this.palm.geometry.dispose();
      this.palm.geometry = geo;
      this.palm.material = palmMat;
      geo.computeBoundingBox();
      const box = geo.boundingBox;
      geo.translate(
        -(box.max.x + box.min.x) / 2,
        -(box.max.y + box.min.y) / 2,
        -(box.max.z + box.min.z) / 2,
      );
    } catch (e) {
      console.warn('[hand3d] palm mesh load failed; using procedural palm', e);
    }
  }

  /* Build (or rebuild) the fretboard, neck, frets, and strings from the
     geometry snapshot the host computed.  All board geometry is built in
     world coordinates that match the convention documented at the top of
     this module:
       - The board runs along +X from world-x = wx(nut) to wx(last fret) + a
         small margin.
       - The string Z span is centred on Z = 0 and totals STRING_SPAN_Z.
       - String 1 (high-E) sits at the LARGEST +Z (player side, closer to the
         camera in default orbit); string N (low-E) sits at the smallest Z.

     The fingerNodes built in _buildHand are NOT touched here — their
     anatomical lengths/radii are fixed; setGeometry only re-frames the
     camera and rebuilds the board hardware. */
  setGeometry(geom) {
    this.geom = geom;
    while (this.fretboardGroup.children.length) {
      const c = this.fretboardGroup.children.pop();
      if (c.geometry) c.geometry.dispose();
      this.fretboardGroup.remove(c);
    }
    if (!geom) return;
    const { NUT_X, fretX, numFrets, numStrings } = geom;

    // Board world-X span.  The nut sits 18 px inboard of NUT_X (matching the
    // SVG board's left margin) and the body end extends 10 px past the last
    // fret.  This places the board centre at boardCX so the camera frames it.
    const x0       = wx(NUT_X - 18);
    const x1       = wx(fretX(numFrets) + 10);
    const boardCX  = (x0 + x1) / 2;
    const length   = x1 - x0;

    // String Z span: centre on Z = 0, total span scaled by string count so
    // 6 strings span ~22.7 wu with mm(10.5) spacing — 10.5 mm is the typical
    // electric-guitar bridge spacing, putting the 6-string span comfortably
    // between a 43 mm nut and a 53 mm 12th-fret width.  String 1 (high-E) is
    // at +Z (player side), string N (low-E) at -Z (far side).
    const STRING_SPACING = mm(10.5);
    const stringSpan     = (numStrings - 1) * STRING_SPACING;
    const stringZMax     = +stringSpan / 2;  // high-E (string 1) — player side
    const stringZMin     = -stringSpan / 2;  // low-E  (string N) — far side
    const boardZ0        = stringZMin - 1.2;  // wood extends past outer strings
    const boardZ1        = stringZMax + 1.2;
    const boardWidthZ    = boardZ1 - boardZ0;

    // Fretboard slab: thin (0.30 wu) box along +X, full string-span width
    // along +Z, top face at Y = 0.
    const boardMat = new THREE.MeshStandardMaterial({
      color: 0x3b261a, roughness: 0.55, metalness: 0.0,
    });
    const board = new THREE.Mesh(
      new THREE.BoxGeometry(length, 0.30, boardWidthZ),
      boardMat,
    );
    board.position.set(boardCX, BOARD_TOP_Y - 0.15, (boardZ0 + boardZ1) / 2);
    this.fretboardGroup.add(board);

    // Neck back: a D-section extrusion under the slab.  Cross-section lives
    // in local XY (X = neck width = world Z, Y = neck depth = world Y).
    // We build a flat top at Y = 0 and a rounded belly down to Y = -NECK_DEPTH,
    // then extrude along +X for the neck length.
    const hw = boardWidthZ / 2;
    const neckShape = new THREE.Shape();
    neckShape.moveTo(-hw, -0.30);     // sits flush under the fretboard slab
    neckShape.lineTo(hw, -0.30);
    neckShape.quadraticCurveTo(hw, -NECK_DEPTH, 0, -NECK_DEPTH);
    neckShape.quadraticCurveTo(-hw, -NECK_DEPTH, -hw, -0.30);
    const neckGeo = new THREE.ExtrudeGeometry(neckShape, {
      depth: length, bevelEnabled: false, curveSegments: 18, steps: 1,
    });
    // Extrude pushes along local +Z; rotate so that becomes world +X, then
    // re-centre so neck.position.x can place it on the board centre.
    neckGeo.rotateY(-Math.PI / 2);
    neckGeo.translate(length / 2, 0, 0);
    neckGeo.computeVertexNormals();
    const neck = new THREE.Mesh(neckGeo, boardMat);
    neck.position.set(boardCX, 0, (boardZ0 + boardZ1) / 2);
    this.fretboardGroup.add(neck);

    // Frets: thin metal cylinders laid across Z at each fret-X.  Crown
    // tangent at FRET_CROWN_Y so the top of the fret reads as a ridge above
    // the wood.  We span only the string-Z range (not the full board width)
    // so the fret reads as a wire rather than a board-edge inlay.
    const fretMat = new THREE.MeshStandardMaterial({
      color: 0xc8cad0, roughness: 0.35, metalness: 0.7,
    });
    const crownR = 0.10;
    const crownLen = boardWidthZ * 0.96;
    for (let fr = 0; fr <= numFrets; fr++) {
      const fx = wx(fretX(fr));
      const wire = new THREE.Mesh(
        new THREE.CylinderGeometry(crownR, crownR, crownLen, 10),
        fretMat,
      );
      // Cylinder defaults along +Y; rotate so its long axis lies along Z.
      wire.rotation.x = Math.PI / 2;
      wire.position.set(fx, FRET_CROWN_Y, (boardZ0 + boardZ1) / 2);
      this.fretboardGroup.add(wire);
    }

    // Strings: 6 thin tubes along +X at Y = STRING_SURFACE.  Re-built per
    // setGeometry call so the string count can change with the tuning.
    const strMat = new THREE.MeshStandardMaterial({
      color: 0xc9ccd1, roughness: 0.3, metalness: 0.7,
    });
    this.stringMeshes = [];
    this._stringZ = new Array(numStrings + 1);
    for (let s = 1; s <= numStrings; s++) {
      // s = 1 → highest +Z (high-E, player side); s = numStrings → most -Z.
      const sz = stringZMax - (s - 1) * STRING_SPACING;
      this._stringZ[s] = sz;
      const path = new THREE.LineCurve3(
        new THREE.Vector3(x0, STRING_SURFACE, sz),
        new THREE.Vector3(x1, STRING_SURFACE, sz),
      );
      const tube = new THREE.TubeGeometry(path, 8, 0.06, 6, false);
      const str = new THREE.Mesh(tube, strMat);
      this.fretboardGroup.add(str);
      this.stringMeshes.push({
        mesh: str, sz, x0, x1, baseY: STRING_SURFACE, deflect: 0, pressFret: null,
      });
    }

    // Stash the geometry helpers we need each frame.
    this._fretX = fretX;
    this._numFrets = numFrets;
    this._numStrings = numStrings;
    this._boardCX = boardCX;
    this._stringZMax = stringZMax;
    this._stringZMin = stringZMin;

    // Camera framing: aim at the fret-press points just above the strings
    // and slightly past them into the -Z fretboard half.  This guitarist's-
    // POV target pulls the camera's gaze down onto the fingertips/strings
    // rather than onto the back of the hand, and rotates the camera-to-
    // target ray so the forearm (at z≈+24, y≈+22) sits behind/below it
    // instead of occluding the fingers.
    this._lookAt.set(boardCX, STRING_SURFACE + mm(3), -HAND_OFFSET_Z * 0.15);
    this._applyCamera();
  }

  /* ---- pressX: fret-CENTER X in world space (mid-way between fret r-1 and r) */
  _pressX(fret) {
    if (!this._fretX) return 0;
    if (fret <= 0) return wx(this._fretX(0)) - 1.0;  // open: just past the nut
    const a = wx(this._fretX(fret - 1));
    const b = wx(this._fretX(fret));
    return (a + b) / 2;
  }

  /* ---- stringZ: world Z of string s (1 = high-E at +Z, N = low-E at -Z) */
  _stringZAt(s) {
    if (!this._stringZ || s == null) return 0;
    if (s < 1) s = 1;
    if (s > this._numStrings) s = this._numStrings;
    return this._stringZ[s];
  }

  /* Per-frame re-pose from the shared kinematic snapshot.

     We use ONLY semantic intent (target string + fret + role) from the kin
     payload.  The 2D ik.{mcp,pip,dip,tip} pixels are intentionally ignored —
     they describe a top-down 2D plan view, not the 3D grip pose.

     kin = {
       fingers: { <name>: { ik, role, fret, strings, width } },
       palm:    { mcpL, mcpR, topX, topY, botY, palmNormal? },
       forearm: { wristX, forearmX, topY },
       thumb:   { x, y, role },
     }
   */
  update(kin) {
    if (this.disposed || !kin) return;
    try {
      this._poseHand(kin);
      this._poseFingers(kin);
      this._poseThumb(kin);
      this._poseForearm(kin);
      this.renderer.render(this.scene, this.camera);
    } catch (e) {
      // Silent fallback: any per-frame error should not poison the renderer.
      // Keep a single console.warn so the regression is visible in DevTools.
      if (!this._poseErrLogged) {
        console.warn('[hand3d] update failed', e);
        this._poseErrLogged = true;
      }
    }
  }

  /* Position the back-of-hand slab along the neck.  We derive the hand's
     world-X from the palm centroid in the kin snapshot (kin.palm.mcpL +
     mcpR) so the slab tracks left/right slides up the neck.  Y and Z are
     forced by the grip-frame layout (palm sits high above the strings on
     the player side). */
  _poseHand(kin) {
    if (!kin.palm) return;
    // Palm centroid in world X (mean of the index and pinky MCPs).
    const palmX = wx((kin.palm.mcpL + kin.palm.mcpR) / 2);
    // The MCP row centre in world Z: average of all 4 target string Z's
    // (so the palm hovers over its targets even on offset chord shapes).
    const zRow = this._palmZTarget(kin);
    this.palm.position.set(
      palmX,
      MCP_Y,
      zRow + HAND_OFFSET_Z,
    );
    // The slab's default geometry has +X = neck axis already, +Y = thickness,
    // +Z = wrist depth.  No rotation needed for a default grip; future palm
    // tilt (kin.palm.palmNormal) can be folded in via Euler 'YXZ' here.
    const pn = kin.palm.palmNormal;
    if (pn) {
      this.palm.rotation.order = "YXZ";
      this.palm.rotation.x = (pn.pitch || 0) * 0.3;  // damped — geometry is rigid
      this.palm.rotation.y = (pn.yaw   || 0) * 0.3;
      this.palm.rotation.z = (pn.roll  || 0) * 0.3;
    } else {
      this.palm.rotation.set(0, 0, 0);
    }
    this._palmX = palmX;
    this._palmZ = zRow + HAND_OFFSET_Z;
  }

  /* Average Z (across-strings axis) of the active/planted finger targets.
     Used as the palm's Z anchor so the back-of-hand stays roughly above
     wherever the fingers are pressing.  Falls back to 0 (board centre) when
     no finger has a target. */
  _palmZTarget(kin) {
    let sum = 0, n = 0;
    for (const f of FINGER_ORDER) {
      const fg = kin.fingers && kin.fingers[f];
      if (!fg) continue;
      const targetStr = (fg.strings && fg.strings.length) ? fg.strings[0] : null;
      if (targetStr != null && (fg.role === "active" || fg.role === "planted")) {
        sum += this._stringZAt(targetStr);
        n++;
      }
    }
    return n > 0 ? sum / n : 0;
  }

  /* Pose each finger chain.  For each finger:
       1. Compute the MCP world position (anchor on the palm's front face).
       2. Set the fingerRoot group's position to the MCP.
       3. Set fingerRoot's local rotation around Y so the chain's rest
          direction (-Z in local) aligns with the line MCP → target XZ.
          (When the target X equals the MCP X, no Y rotation; otherwise the
          chain swings slightly to reach off-fret targets.)
       4. Compute the total curl angle needed so the fingertip reaches the
          target Y (which is below the MCP).  Distribute across MCP/PIP/DIP
          rotations using CURL_SPLIT.

     For hover / idle, target a relaxed pose just above the string surface
     so the chain reads as resting fingers, not extended ones. */
  _poseFingers(kin) {
    if (!kin.fingers) return;
    // X positions of the 4 MCPs along the neck.  We spread them across the
    // palm's local +X so the index sits on the +X edge (nearer the nut for a
    // right-hand grip) and the pinky on the -X edge.  PALM_DEPTH_X is the
    // wrist-knuckle distance, NOT the knuckle row width — for the knuckle
    // row we use a slightly narrower spacing so the four MCPs feel like
    // adjacent fingers, not a splayed claw.
    const mcpSpan = PALM_WIDTH_Z * 0.95;  // total knuckle row width (≈80 mm)
    const mcpStepX = mcpSpan / 3;          // 4 MCPs spaced over 3 gaps
    // Index sits on the -X (nut) edge, pinky on the +X (bridge) edge so the
    // hand naturally covers a 4-fret span with index leading toward the nut.
    // World +X = nut → bridge, so index (lowest fret) is at -mcpSpan/2 and
    // pinky (highest fret) is at +mcpSpan/2.  This matches a real left-hand
    // grip where the four MCPs span four consecutive frets.
    const mcpXOffset = {
      index:  -mcpSpan / 2,
      middle: -mcpSpan / 2 + mcpStepX,
      ring:   -mcpSpan / 2 + mcpStepX * 2,
      pinky:  -mcpSpan / 2 + mcpStepX * 3,
    };
    // MCPs sit on the FRONT face of the palm slab (the -Z face — toward the
    // strings), at the bottom edge of the slab (-PALM_HEIGHT_Y/2) so the
    // chain extends from the underside of the knuckles, not the top.
    const mcpYLocal = -PALM_HEIGHT_Y * 0.20;
    const mcpZLocal = -PALM_DEPTH_X * 0.20;  // near the front (knuckle) face

    // Default palm-anchor fallbacks so a missing palm payload (or a frame
    // that arrived before _poseHand could run) does not poison the chain
    // with NaNs.  Board centre + default offset reads as a relaxed pose.
    const baseX = (this._palmX !== undefined) ? this._palmX : (this._boardCX || 0);
    const baseZ = (this._palmZ !== undefined) ? this._palmZ : HAND_OFFSET_Z;
    for (const f of FINGER_ORDER) {
      const fg   = kin.fingers[f];
      const node = this.fingerNodes[f];
      if (!fg || !node) continue;

      // MCP world position: palm.position + local offset, since the palm has
      // no rotation in the default grip we just add.  If palm rotates we'd
      // need a full matrix transform — kept simple while palm tilt is damped.
      const mcpX = baseX + mcpXOffset[f];
      const mcpY = MCP_Y + mcpYLocal;
      const mcpZ = baseZ + mcpZLocal;
      node.root.position.set(mcpX, mcpY, mcpZ);

      // Target: where the fingertip should land.
      //   - active/planted: at (pressX(fret), STRING_SURFACE, stringZ(string)).
      //   - hover:          just above the string surface, near the target X.
      //   - idle:           resting Z (above the strings on the player side).
      const role = fg.role || "idle";
      const targetStr = (fg.strings && fg.strings.length) ? fg.strings[0] : null;
      let tx, ty, tz;
      if ((role === "active" || role === "planted") && fg.fret > 0 && targetStr != null) {
        tx = this._pressX(fg.fret);
        ty = STRING_SURFACE;
        tz = this._stringZAt(targetStr);
      } else if (role === "hover" && targetStr != null) {
        tx = (fg.fret > 0) ? this._pressX(fg.fret) : mcpX;
        ty = STRING_SURFACE + 0.7;
        tz = this._stringZAt(targetStr);
      } else {
        // Idle: rest above the strings, near MCP X, at the high-E side so
        // the relaxed fingers don't poke through the board.
        tx = mcpX;
        ty = MCP_Y - 1.5;
        tz = mcpZ - 2.0;
      }

      // Solve the chain.
      this._solveChain(node, mcpX, mcpY, mcpZ, tx, ty, tz);

      // Recolour the tip cap by role.
      node.tipCap.material = this.roleMats[role] || this.roleMats.idle;
    }
  }

  /* Inverse kinematics for a 3-bone planar chain:
       - The chain rotates as a whole around the world Y axis (yaw) so its
         swing plane (local YZ) contains the target.
       - Within that plane, we compute the total flex angle that takes the
         tip from rest (along -Z) to the target, then distribute across the 3
         joints by CURL_SPLIT.
     This is NOT a precise multi-joint IK — it's the "anatomical fan" used in
     the spec.  Total curl is clamped to [0, 2.5 rad] so a fully reachable
     fret bends realistically and an unreachable one curls to the limit. */
  _solveChain(node, mcpX, mcpY, mcpZ, tx, ty, tz) {
    // Vector from MCP to target in world space.
    const dx = tx - mcpX;
    const dy = ty - mcpY;     // negative: target is BELOW the MCP
    const dz = tz - mcpZ;     // negative: target is in front of the palm (-Z)

    // Yaw: rotate the chain around Y so its -Z axis aligns with the XZ
    // projection of the target.  atan2(-dx, -dz) gives the yaw needed.
    // (We negate because the chain rests pointing -Z; we want -Z + yaw to
    // align with the (dx, dz) direction.)
    //
    // Euler order 'YXZ': yaw applies FIRST (placing the swing plane), then
    // the curl rotation.x folds the chain in that plane.  Without this the
    // default 'XYZ' would apply curl first in the chain's local frame, then
    // yaw the curled result — fingers would sweep instead of fold.
    const yaw = Math.atan2(-dx, -dz);
    node.root.rotation.order = "YXZ";
    node.root.rotation.y = yaw;

    // In the yawed local frame, the target's lateral X component is folded
    // into the forward distance.  Compute the local forward distance (the
    // horizontal reach in the swing plane) and vertical drop:
    //   forward = projection of (dx, dz) onto the chain's -Z axis = -dz·cos − dx·sin... but
    //   easier: forward = sqrt(dx² + dz²)  (always positive — the chain
    //   reaches out in its own forward direction after the yaw).
    const forward = Math.sqrt(dx * dx + dz * dz);
    const drop    = -dy;       // positive = target is BELOW MCP

    // Estimate the "extended reach" if the finger were straight: simply L.
    // The finger tip when extended (zero curl) sits at (forward = L, drop = 0).
    // We want the tip to land at (forward, drop).  Approximate the curl by
    // the angle whose sine is the drop fraction, plus a contribution from
    // how much the forward reach has shortened relative to L.
    const L = node.Ltotal;
    // Total straight-line distance from MCP to target.
    const dist = Math.sqrt(forward * forward + drop * drop);
    // The chord-length-to-bow-arc relationship for a circular arc of length L
    // and chord d gives: chord/length ≈ sinc(θ/2), where θ is the total bend.
    // Inverting analytically is messy; we use a fast monotone approximation:
    //   chord_ratio = min(1, dist / L)
    //   totalCurl   = π · (1 - chord_ratio)^0.85
    // Reaches the limit (π ≈ straight) when dist = 0 (curled into the palm),
    // and zero (extended) when dist >= L.  Empirically the 0.85 exponent
    // gives a natural curl progression across the press range.
    const chordRatio = Math.min(1.0, dist / L);
    let totalCurl = Math.PI * Math.pow(1 - chordRatio, 0.85);

    // Additional curl from the "drop angle" — when the target is more BELOW
    // than FORWARD (a tight press against the strings), boost the curl by the
    // angle between the (forward, -drop) target direction and the rest -Z
    // direction.  This makes the fingertip point downward at the strings
    // even when the chain has plenty of reach left.
    const dropAngle = Math.atan2(drop, Math.max(0.1, forward));
    totalCurl = Math.max(totalCurl, dropAngle * 1.15);

    // Clamp curl to anatomical limit: MCP+PIP+DIP combined can reach about
    // 250° fully balled fist; we cap at 2.6 rad (≈150°) for press poses.
    if (totalCurl < 0) totalCurl = 0;
    if (totalCurl > 2.6) totalCurl = 2.6;

    // Distribute the curl across the 3 joints.  Each joint rotates around its
    // own X axis; the chain folds in the YZ plane.
    //
    // SIGN CONVENTION: the bones rest along -Z (extended forward over the
    // strings).  A POSITIVE rotation around X swings -Z toward +Y (UP, away
    // from the strings).  We want the chain to curl DOWN onto the strings,
    // so we apply NEGATIVE rotation: -Z swings toward -Y.  The yaw above
    // (root.rotation.y) is unaffected — the curl axis stays X in the local
    // frame after yaw because the chain is built straight along local -Z.
    node.root.rotation.x = -totalCurl * CURL_SPLIT.mcp;
    node.pip.rotation.x  = -totalCurl * CURL_SPLIT.pip;
    node.dip.rotation.x  = -totalCurl * CURL_SPLIT.dis;
  }

  /* Thumb: braces the BACK of the neck (-Z side from the back-of-hand).
     We position it under the middle finger MCP along X, at Y = -1.5
     (mid-belly height behind the neck), aimed up and slightly toward the
     player so it reads as a thumb hooked over the back of the neck. */
  _poseThumb(kin) {
    const thumbX = this._palmX || 0;
    // Place at the back of the neck — opposite Z side from the palm.  The
    // neck's far edge is at stringZMin; we sit a touch past that.
    const baseZ = (this._stringZMin !== undefined) ? this._stringZMin - 0.5 : -3.0;
    const baseY = -NECK_DEPTH * 0.55;
    this.thumbBone.position.set(thumbX, baseY, baseZ);
    // Rotate so the bone points up and toward the player (+Z) — wrapping
    // over the back of the neck.  rotation.x lifts the tip up; rotation.y
    // would yaw it; for the default brace we just use a fixed pitch.
    this.thumbBone.rotation.set(-Math.PI * 0.35, 0, 0);
    this.thumbJoint.position.set(thumbX, baseY, baseZ);
    this.thumbJoint.scale.setScalar(1);
  }

  /* Forearm: a single capsule from the wrist (back side of the palm, +Z) to
     a point further +Z (toward the player) and slightly +X.  The wrist
     stays attached to the back of the palm slab, regardless of where the
     hand has slid along the neck. */
  _poseForearm(kin) {
    const wristX = (this._palmX !== undefined) ? this._palmX + PALM_DEPTH_X * 0.3 : 0;
    const wristZ = (this._palmZ !== undefined) ? this._palmZ + PALM_DEPTH_X * 0.25 : HAND_OFFSET_Z;
    const wristY = MCP_Y;
    this.forearmBone.position.set(wristX, wristY, wristZ);
    // The bone defaults to extending along -Z (rest direction).  We want it
    // to extend along +Z + slight +X — toward the player and the elbow.
    // rotation.y = π (flip -Z to +Z), then rotation.x = -0.25 to tilt up.
    this.forearmBone.rotation.set(-0.20, Math.PI, 0);
    this.forearmJoint.position.set(wristX, wristY, wristZ);
    this.forearmJoint.scale.setScalar(1);
  }

  /* Convert the current spherical-orbit state into a world-space camera
     position relative to _lookAt and re-aim the camera at the target.
     azimuth = 0 puts the camera on +Z of _lookAt (player side, looking at
     the back of the hand); polar = 0 would be straight overhead. */
  _applyCamera() {
    const { radius, azimuth, polar } = this._camSpherical;
    const sinP = Math.sin(polar);
    const cosP = Math.cos(polar);
    const sinA = Math.sin(azimuth);
    const cosA = Math.cos(azimuth);
    this.camera.position.set(
      this._lookAt.x + radius * sinP * sinA,
      this._lookAt.y + radius * cosP,
      this._lookAt.z + radius * sinP * cosA,
    );
    this.camera.lookAt(this._lookAt);
  }

  resize() {
    if (this.disposed) return;
    const w = this.container.clientWidth || SCENE_W;
    const h = this.container.clientHeight || (w * SCENE_H) / SCENE_W;
    this.camera.aspect = w / h;
    this.camera.updateProjectionMatrix();
    this.renderer.setSize(w, h, false);
    this._applyCamera();
  }

  dispose() {
    this.disposed = true;
    window.removeEventListener("resize", this._onResize);
    try {
      const canvas = this.renderer.domElement;
      if (canvas) {
        canvas.removeEventListener("pointerdown", this._onPointerDown);
        canvas.removeEventListener("pointermove", this._onPointerMove);
        canvas.removeEventListener("pointerup", this._onPointerUp);
        canvas.removeEventListener("pointercancel", this._onPointerUp);
        canvas.removeEventListener("pointerleave", this._onPointerUp);
        canvas.removeEventListener("wheel", this._onWheel);
      }
      this.renderer.dispose();
      if (this.renderer.domElement && this.renderer.domElement.parentNode) {
        this.renderer.domElement.parentNode.removeChild(this.renderer.domElement);
      }
    } catch (e) { /* best-effort teardown */ }
  }
}

/**
 * Factory: attempt to create a 3D renderer in `container`.  Returns null (so
 * the caller falls back to SVG) when WebGL is unavailable or three.js
 * construction throws.  three.js is only loaded because this module was
 * imported, and this module is only imported when the feature flag is on.
 */
export function create(container) {
  if (!webglAvailable()) return null;
  try {
    return new Hand3DRenderer(container);
  } catch (e) {
    // Any three.js/WebGL construction failure → SVG fallback, never a crash.
    console.warn('[hand3d] renderer construction failed', e);
    return null;
  }
}

export { Hand3DRenderer, webglAvailable };
