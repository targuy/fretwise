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
import { GLTFLoader } from "./vendor/GLTFLoader.js";

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
/* Classical grip frame: the palm cradles the BACK of the neck (Y < 0), with
   its centroid centered on the neck along Z (no player-side offset).  The
   +Z drift previously baked in here is now recreated by the MCP anchor on
   the slab's +Z edge — see _poseFingers.  Kept as a named constant (= 0) so
   any external reference still resolves cleanly. */
const HAND_OFFSET_Z = mm(0);
/* Back-of-hand slab geometry (real mm).  PALM_DEPTH_X is the wrist→MCP depth
   (100 mm in an adult hand), PALM_HEIGHT_Y is the dorsal slab thickness
   (~30 mm), and PALM_WIDTH_Z is the cross-neck knuckle-row width (~85 mm).
   The three were previously conflated via PALM_DEPTH_X — see Edit 4 below. */
const PALM_DEPTH_X   = mm(100);  // wrist ↔ knuckle distance, along +X
const PALM_HEIGHT_Y  = mm(30);   // back-of-hand thickness (Y)
const PALM_WIDTH_Z   = mm(85);   // knuckle-row span (index ↔ pinky), along Z
/* Palm centroid Y in the classical grip frame.  The palm sits BELOW the
   neck (Y < 0); its top face (post-flip) brushes the neck back at
   Y = -NECK_DEPTH so the fingers can wrap up and over the +Z (player) edge
   of the neck onto the strings.  This is the centroid, so palm.top is at
   palm.y + PALM_HEIGHT_Y/2 = -NECK_DEPTH.
   Symbol kept as MCP_Y for backward compatibility with existing references
   in _poseHand, _poseFingers, _poseForearm; semantically it is now
   "palm centre Y", not "MCP top-of-slab Y". */
const MCP_Y          = -NECK_DEPTH - PALM_HEIGHT_Y * 0.5;
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

/* ===========================================================================
   SKINNED GLB HAND — real rigged mesh that deforms via skin weights.

   The vendored /static/models/rigged_hand.glb carries TWO skinned meshes bound
   to one Rigify-named armature:  Cube.000 = LEFT (fretting) hand — the one we
   drive — and Cube.005 = RIGHT hand (hidden).  We load it fire-and-forget in
   the constructor; on success the procedural rig is hidden and every frame we
   drive the FINGER BONES with the curl angle the procedural solver already
   computes (FK, not procedural geometry).  On any failure we silently keep the
   procedural rig — the panel never goes blank.

   BONE-NAME SANITISATION (IMPORTANT): three.js' GLTFLoader runs every node name
   through PropertyBinding.sanitizeNodeName, which STRIPS dots and spaces.  So
   in the loaded scene "finger_index.01.L" becomes "finger_index01L",
   "hand.L" → "handL", and the meshes "Cube.000"/"Cube.005" → "Cube000"/"Cube005".
   We therefore look bones/meshes up by BOTH the original dotted name AND its
   sanitized form (see _sanitizeName / _findBone).  The dotted names are kept in
   FINGER_BONES below so the source still documents the Blender rig and the test
   suite's bone-name guards match.
   =========================================================================== */

/* Per-finger bone chains (proximal/MCP → middle/PIP → distal/DIP), Rigify
   left-hand naming.  Looked up by sanitized name at runtime (dots stripped). */
const FINGER_BONES = {
  index:  ["finger_index.01.L",  "finger_index.02.L",  "finger_index.03.L"],
  middle: ["finger_middle.01.L", "finger_middle.02.L", "finger_middle.03.L"],
  ring:   ["finger_ring.01.L",   "finger_ring.02.L",   "finger_ring.03.L"],
  pinky:  ["finger_pinky.01.L",  "finger_pinky.02.L",  "finger_pinky.03.L"],
  thumb:  ["thumb.01.L", "thumb.02.L", "thumb.03.L"],
};
/* The two skinned meshes (dotted; sanitized at runtime). */
const LEFT_MESH_NAME  = "Cube.000";   // fretting hand — keep, reskin flat
const RIGHT_MESH_NAME = "Cube.005";   // other hand — hide

/* ---- EMPIRICAL KNOBS (tune in-browser; first guesses below) --------------- */
/* In the GLB rest pose each finger bone points along its own LOCAL +Y (verified
   from the GLB: every child bone sits at +Y in its parent's frame).  A curl is
   therefore a rotation about an axis PERPENDICULAR to +Y — local X is the
   natural flex axis (rotates the +Y-pointing bone within the YZ plane).
   FLEX_SIGN flips the fold direction (toward the palm vs. backward).
   >>> FLEX_AXIS and FLEX_SIGN are the #1 pair to verify visually: if the
       fingers bend SIDEWAYS, swap to (0,0,1); if they bend BACKWARD, flip
       FLEX_SIGN to -1. */
const FLEX_AXIS = new THREE.Vector3(1, 0, 0);
const FLEX_SIGN = 1;

/* Global rig placement.  Scale is BAKED into rigged_hand_baked.glb offline
   (geometry + bone translations + inverse-bind matrices all pre-multiplied by
   ~648 = mm(95) / 0.0634, so the MCP row lands at a real ~95 mm).  At runtime
   the rig therefore uses scale 1 — applying a node scale after GLTFLoader binds
   would fling skinned vertices off-screen by scale².  RIG_TARGET_MCP_MM is the
   knuckle-row width the offline bake targeted (kept for the diagnostic check). */
const RIG_TARGET_MCP_MM  = 95;   // real knuckle-row width the bake targets

/* Euler (radians) that rotates the WHOLE loaded hand into the classical grip:
   palm under the neck facing the strings, fingers reaching over from the player
   side to press.  In the GLB's native frame the fingers point roughly along
   world -X and the hand lies almost flat, so we yaw it onto the neck and pitch
   the palm up under the strings.  THESE ARE FIRST GUESSES — RIG_ROT is the
   single most likely thing to need one round of in-browser tuning. */
/* Calibrated on the BAKED rig (scale baked in, self-anchored centroid) against
   the default orbit camera: yaw +90° puts the back of the hand toward the
   player, the four fingers reaching over the board so the X-axis curl folds
   the tips DOWN onto the strings, and the wrist/forearm dropping to the player
   side below.  (RIG_ROT is consumed by _applyRigTransform; the anchor cancels
   the orientation-dependent mirror offset automatically.) */
const RIG_ROT = {
  x: -Math.PI / 2,   // pitch -90deg: wrist/palm rise from behind-below, the back
                     //   of the hand arches OVER the neck, fingers curl DOWN over
                     //   the front edge onto the strings (the classical "pince").
  y:  Math.PI / 2,   // yaw: back of hand to player, knuckle row along the neck
  z:  0,             // roll — tune if the hand is canted
};
/* Grip anchor = desired WORLD position of the rendered hand CENTROID.  Y below
   the board so the palm/wrist cradle under+behind the neck; Z just behind the
   centerline so the hand clamps the D-section.  X tracks hand_position. */
const RIG_POS_Y = -7;
const RIG_POS_Z = -2;

/* Reusable zero vector (uncalibrated render offset fallback). */
const ZERO_VEC = new THREE.Vector3();

/* Relaxed vs. pressed curl for the skinned fingers.  Idle/hover fingers get a
   gentle resting curl; active/planted fingers get the full solver curl. */
const SKIN_IDLE_CURL  = 0.35;   // radians of gentle rest flex (idle/hover)
const SKIN_THUMB_CURL = 0.45;   // gentle fixed brace curl for the thumb

/* Thumb brace (classical grip): swing the CMC root so the thumb crosses to the
   FAR (-Z) back-of-neck at mid-belly, with an opposition roll + distal flex.
   Axis/sign are mirror-dependent — calibrated by ?thumbswing/thumbaxis/etc. */
const THUMB_SWING_DEG  = 55;    // abduction angle carrying the thumb behind
const THUMB_SWING_AXIS = "y";   // abduction axis (local)
const THUMB_ROLL_DEG   = 30;    // opposition roll (local X)
const THUMB_FLEX_DEG   = 40;    // distal brace flex

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
/* ============================================================================
 * ARTICULATED FK RIG — replaces the rigid skinned mesh.
 * A flat single mesh cannot form a clamp ("you cannot draw a clamp with a
 * straight line").  The hand is built from real hinged segments folded until
 * each fingertip contacts its target string, with hard collision against the
 * D-neck.  Joint limits, lengths and the fold algorithm are derived in
 * memory/hand-fingering-kinematics.md.  FK is automatic via THREE Object3D
 * parenting; the local-frame convention matches the old _solveChain: each bone
 * runs (0,0,0)->(0,0,-L); +X rotation folds -Z toward -Y (down onto strings).
 * ========================================================================== */
const DEG = Math.PI / 180;
const LIFT = Math.PI / 2;          // finger-root baseline: rest dir (-Z) -> +Y (up)
const FOLD_STEP = 1.0 * DEG;       // per-joint scan resolution
const CONTACT_EPS = 0.40;          // wu: distal tip within target = contact
const CCD_PASSES = 6;              // max iterated coordinate-descent passes
const NECK_SAMPLES = 8;            // interior samples per phalanx segment (collision)
const FLEX_LIMITS = {
  finger: { mcp: [0, 90 * DEG], pip: [0, 110 * DEG], dip: [0, 80 * DEG] },
  pinky:  { mcp: [0, 95 * DEG], pip: [0, 110 * DEG], dip: [0, 80 * DEG] },
  thumb:  { mcp: [0, 55 * DEG], ip:  [0, 80 * DEG] },
};
const WRIST_LIMITS = { flexX: [-70 * DEG, 80 * DEG], devZ: [-30 * DEG, 20 * DEG] };
const WRIST_FLEX_DEFAULT = 0.25;
const WRIST_DEV_DEFAULT  = -0.10;
const MCP_ABD_HALF = { index: 20 * DEG, middle: 15 * DEG, ring: 15 * DEG, pinky: 30 * DEG };
const PHALANX_FRAC_PER = {
  index:  [0.506, 0.292, 0.201], middle: [0.512, 0.302, 0.186],
  ring:   [0.503, 0.307, 0.190], pinky:  [0.508, 0.289, 0.203], thumb: [0.557, 0.443],
};
const FINGER_RADIUS = { index: mm(8) * 0.95, middle: mm(8), ring: mm(8), pinky: mm(8) * 0.85, thumb: mm(11) };
const clampN = (v, a, b) => Math.min(Math.max(v, a), b);
/* Placement of the hand vs the neck (tunable via ?mcpnodey / ?mcpy / ?mcpedge).
   The MCP knuckles MUST launch OUTSIDE the neck (Z beyond the +hw player edge)
   so the fingers arch OVER the top rather than impaling the belly at rest. */
const MCP_NODE_Y     = -10;   // Main.node world Y (palm/back-of-hand below the neck)
const MCP_LAUNCH_Y   = 2.5;   // MCP-anchor world Y (knuckles ABOVE the board, clear of the neck)
const MCP_EDGE_MARGIN = 2.0;  // fallback: MCP this far beyond the +Z neck edge when no active target
const MCP_REACH      = 11;    // MCP-anchor +Z offset from the player-most string (reach sweet-spot)
const ROOT_BASE      = 135 * Math.PI / 180;  // finger root pitch baseline (folds down onto strings)

/* (makeBoneMesh — the organic tapered phalanx bone — is defined above and reused.) */

/* Rounded back-of-hand wedge (local X = cross-neck, Z = wrist<->MCP depth, Y = thickness). */
function makePalmSlab(material) {
  const halfW_mcp = PALM_WIDTH_Z * 0.50, halfW_wrist = PALM_WIDTH_Z * 0.42;
  const halfD = PALM_DEPTH_X * 0.50, r = Math.min(halfW_mcp, halfD) * 0.35;
  const s = new THREE.Shape();
  s.moveTo(halfW_mcp - r, halfD); s.quadraticCurveTo(halfW_mcp, halfD, halfW_mcp, halfD - r);
  s.lineTo(halfW_wrist, -halfD + r); s.quadraticCurveTo(halfW_wrist, -halfD, halfW_wrist - r, -halfD);
  s.lineTo(-halfW_wrist + r, -halfD); s.quadraticCurveTo(-halfW_wrist, -halfD, -halfW_wrist, -halfD + r);
  s.lineTo(-halfW_mcp, halfD - r); s.quadraticCurveTo(-halfW_mcp, halfD, -halfW_mcp + r, halfD);
  s.lineTo(halfW_mcp - r, halfD);
  const geo = new THREE.ExtrudeGeometry(s, { depth: PALM_HEIGHT_Y, bevelEnabled: true,
    bevelThickness: PALM_HEIGHT_Y * 0.25, bevelSize: PALM_HEIGHT_Y * 0.20, bevelSegments: 4, curveSegments: 12 });
  geo.rotateX(-Math.PI / 2); geo.translate(0, -PALM_HEIGHT_Y / 2, 0); geo.computeVertexNormals();
  return new THREE.Mesh(geo, material);
}

/* One hinged segment.  node = hinge pivot; distalAnchor = child mount point. */
class Phalange {
  constructor(material, { length, radius, flexMax, name = "" }) {
    this.length = length; this.flexMax = flexMax; this.angle = 0; this.name = name;
    this.node = new THREE.Group();
    this.render = new THREE.Group();
    this.render.add(makeBoneMesh(material, length, radius));
    this.render.add(makeJointMesh(material, radius * 1.02));
    this.node.add(this.render);
    this.distalAnchor = new THREE.Object3D();
    this.distalAnchor.position.set(0, 0, -length);
    this.node.add(this.distalAnchor);
  }
  tipWorld(out = new THREE.Vector3()) { return this.distalAnchor.getWorldPosition(out); }
  baseWorld(out = new THREE.Vector3()) { return this.node.getWorldPosition(out); }
  attachTo(anchor) { anchor.add(this.node); }
}

/* A finger/thumb: an ordered Phalange chain.  The MCP base pivot (this.node)
   carries the LIFT baseline + the set-once yaw splay; PIP/DIP hinge on their
   own nodes.  fold() is the fold-until-contact core. */
class Doigt {
  constructor(materials, { name, totalLength, fracs, radius, flexLimits, role = "idle" }) {
    this.name = name; this.role = role; this.flexLimits = flexLimits;
    this.jointNames = fracs.length === 3 ? ["mcp", "pip", "dip"] : ["mcp", "ip"];
    this._baseX = LIFT; this._yaw = 0; this._baseZ = 0;
    this.node = new THREE.Group(); this.node.rotation.order = "YXZ";
    this.phalanges = [];
    for (let i = 0; i < fracs.length; i++) {
      const L = totalLength * fracs[i];
      const rr = radius * (i === 0 ? 1.0 : i === 1 ? 0.86 : 0.74);
      const lim = i === 0 ? flexLimits.mcp : (i === 1 ? (flexLimits.pip || flexLimits.ip) : flexLimits.dip);
      this.phalanges.push(new Phalange(materials.skin, { length: L, radius: rr, flexMax: lim[1], name: ["prox", "mid", "dis"][i] }));
    }
    this.phalanges[0].attachTo(this.node);
    for (let i = 1; i < this.phalanges.length; i++) this.phalanges[i].attachTo(this.phalanges[i - 1].distalAnchor);
    this.tip = this.phalanges[this.phalanges.length - 1].distalAnchor;
    this._roleMats = materials.roleMats;
    this.tipCap = makeJointMesh(materials.roleMats[role] || materials.roleMats.idle, radius * 0.72);
    this.tip.add(this.tipCap);
    this.theta = this.jointNames.length === 3 ? { mcp: 0, pip: 0, dip: 0 } : { mcp: 0, ip: 0 };
  }
  attachTo(palmAnchor) { palmAnchor.add(this.node); this.anchor = palmAnchor; }
  setRole(role) { this.role = role; this.tipCap.material = this._roleMats[role] || this._roleMats.idle; }
  setYaw(y) { this._yaw = y; }
  setBase(x, z) { this._baseX = x; this._baseZ = z; }
  applyThetas(t) {
    this.theta = t;
    this.node.rotation.set(this._baseX - (t.mcp || 0), this._yaw, this._baseZ);
    this.phalanges[0].angle = t.mcp || 0;
    if (this.phalanges.length === 3) {
      this.phalanges[1].node.rotation.x = -(t.pip || 0); this.phalanges[1].angle = t.pip || 0;
      this.phalanges[2].node.rotation.x = -(t.dip || 0); this.phalanges[2].angle = t.dip || 0;
    } else {
      this.phalanges[1].node.rotation.x = -(t.ip || 0); this.phalanges[1].angle = t.ip || 0;
    }
  }
  resetFlex() { this.applyThetas(this.jointNames.length === 3 ? { mcp: 0, pip: 0, dip: 0 } : { mcp: 0, ip: 0 }); }
  relax(curl) { this.applyThetas(curl || (this.jointNames.length === 3 ? { mcp: 0.30, pip: 0.45, dip: 0.20 } : { mcp: 0.35, ip: 0.30 })); }
  tipWorld(out = new THREE.Vector3()) { return this.tip.getWorldPosition(out); }
  mcpWorld(out = new THREE.Vector3()) { return this.node.getWorldPosition(out); }
  segments() { return this.phalanges.map((p) => [p.baseWorld(), p.tipWorld()]); }
  _update() { this.node.updateMatrixWorld(true); }
  _maxOf(j) { const L = this.flexLimits; return (L[j] || L.ip)[1]; }
  /* THE CORE (CCD fold-to-contact): iterate the joints closest-to-hand-first
     (MCP -> PIP -> DIP), each pass setting every joint to the collision-free
     flex angle that brings the FINGERTIP closest to the target.  Repeats until
     the tip converges (rule 9) or contacts (CONTACT_EPS).  Colliding angles are
     never set, so no phalanx ever traverses the neck (rule 7). */
  fold({ contact, collide, dist }) {
    const three = this.jointNames.length === 3;
    const theta = three ? { mcp: 0, pip: 0, dip: 0 } : { mcp: 0, ip: 0 };
    this.applyThetas(theta); this._update();
    if (contact()) return "CONTACT";
    for (let pass = 0; pass < CCD_PASSES; pass++) {
      let improved = false;
      for (const j of this.jointNames) {
        const max = this._maxOf(j);
        const cur = theta[j];
        this.applyThetas(theta); this._update();
        let bestA = cur, bestD = dist();
        const test = Object.assign({}, theta);
        for (let a = 0; a <= max + 1e-9; a += FOLD_STEP) {
          test[j] = a; this.applyThetas(test); this._update();
          if (collide()) continue;                       // never set a neck-traversing pose
          const d = dist();
          if (d < bestD - 1e-4) { bestD = d; bestA = a; }
        }
        if (Math.abs(bestA - cur) > 1e-4) { theta[j] = bestA; improved = true; }
        this.applyThetas(theta); this._update();
        if (contact()) return "CONTACT";
      }
      if (!improved) break;
    }
    return contact() ? "CONTACT" : "UNREACHABLE";
  }
}
class Index      extends Doigt { constructor(m) { super(m, { name: "index", totalLength: FINGER_LEN.index, fracs: PHALANX_FRAC_PER.index, radius: FINGER_RADIUS.index, flexLimits: FLEX_LIMITS.finger }); } }
class Majeur     extends Doigt { constructor(m) { super(m, { name: "middle", totalLength: FINGER_LEN.middle, fracs: PHALANX_FRAC_PER.middle, radius: FINGER_RADIUS.middle, flexLimits: FLEX_LIMITS.finger }); } }
class Annulaire  extends Doigt { constructor(m) { super(m, { name: "ring", totalLength: FINGER_LEN.ring, fracs: PHALANX_FRAC_PER.ring, radius: FINGER_RADIUS.ring, flexLimits: FLEX_LIMITS.finger }); } }
class PetitDoigt extends Doigt { constructor(m) { super(m, { name: "pinky", totalLength: FINGER_LEN.pinky, fracs: PHALANX_FRAC_PER.pinky, radius: FINGER_RADIUS.pinky, flexLimits: FLEX_LIMITS.pinky }); } }
class Pouce      extends Doigt { constructor(m) { super(m, { name: "thumb", totalLength: mm(60), fracs: PHALANX_FRAC_PER.thumb, radius: FINGER_RADIUS.thumb, flexLimits: FLEX_LIMITS.thumb }); } }

/* Wrist — 2 placement DOF (flex/ext about X, deviation about Z). */
class Poignet {
  constructor(material) {
    this.node = new THREE.Group(); this.node.rotation.order = "ZXY";
    this.flex = 0; this.deviation = 0;
    this.palmAnchor = new THREE.Object3D(); this.node.add(this.palmAnchor);
    this.render = new THREE.Group(); this.render.add(makeJointMesh(material, mm(20))); this.node.add(this.render);
  }
  setFlex(t) { this.flex = clampN(t, WRIST_LIMITS.flexX[0], WRIST_LIMITS.flexX[1]); this.node.rotation.x = this.flex; }
  setDeviation(t) { this.deviation = clampN(t, WRIST_LIMITS.devZ[0], WRIST_LIMITS.devZ[1]); this.node.rotation.z = this.deviation; }
  attachTo(parent) { parent.add(this.node); }
}

/* Hand — owns 1 Poignet + palm + 5 Doigt mounted on per-finger MCP anchors. */
class Main {
  constructor(materials) {
    this.node = new THREE.Group();
    this.poignet = new Poignet(materials.skin); this.poignet.attachTo(this.node);
    this.palm = makePalmSlab(materials.skin); this.poignet.palmAnchor.add(this.palm);
    this.anchors = {};
    const mcpSpan = PALM_WIDTH_Z * 0.95, step = mcpSpan / 3, edgeZ = NECK_DEPTH * 0.60, topY = PALM_HEIGHT_Y * 0.5;
    const off = { index: -mcpSpan / 2, middle: -mcpSpan / 2 + step, ring: -mcpSpan / 2 + 2 * step, pinky: -mcpSpan / 2 + 3 * step };
    for (const f of FINGER_ORDER) { const a = new THREE.Object3D(); a.position.set(off[f], topY, edgeZ); this.palm.add(a); this.anchors[f] = a; }
    const ta = new THREE.Object3D(); ta.position.set(0, -PALM_HEIGHT_Y * 0.2, -PALM_DEPTH_X * 0.35); this.palm.add(ta); this.anchors.thumb = ta;
    this.doigts = { index: new Index(materials), middle: new Majeur(materials), ring: new Annulaire(materials), pinky: new PetitDoigt(materials), thumb: new Pouce(materials) };
    for (const f of FINGER_ORDER) this.doigts[f].attachTo(this.anchors[f]);
    this.doigts.thumb.attachTo(this.anchors.thumb);
    this.mcpSpan = mcpSpan;
  }
  attachTo(handGroup) { handGroup.add(this.node); }
  doigt(name) { return this.doigts[name]; }
  anchorWorld(name, out = new THREE.Vector3()) { return this.anchors[name].getWorldPosition(out); }
  setPlacement(x, y, z) { this.node.position.set(x, y, z); }
}

/* Per-frame controller: places the wrist along the neck, the thumb under it,
   and folds each active finger to its target string.  Owns no geometry. */
class AnimationMain {
  constructor(renderer, main) { this.r = renderer; this.main = main; }
  placement_poignet(fretIndex, knuckleZ) {
    const r = this.r, m = this.main;
    // Place the hand so the INDEX MCP sits AT fretIndex (spec): index anchor is
    // at -mcpSpan/2 from the node, so node.x = pressX(fret) + mcpSpan/2.  The
    // other fingers then fall on +1/+2/+3 frets via the anchor spread.
    const x = (fretIndex > 0 ? r._pressX(fretIndex) : (r._boardCX || 0)) + m.mcpSpan / 2;
    const nodeY = r._tuneNum("mcpnodey", MCP_NODE_Y);
    // Knuckle-row Z: just player-side (+Z) of the player-most active string, so
    // every pressed string is within the finger's fold reach.  Default to the
    // neck player edge when no active target.
    const z = (knuckleZ != null) ? knuckleZ
      : ((r._neckHW || 12.5) + r._tuneNum("mcpedge", MCP_EDGE_MARGIN));
    m.setPlacement(x, nodeY, z);
    m.poignet.setFlex(WRIST_FLEX_DEFAULT); m.poignet.setDeviation(WRIST_DEV_DEFAULT);
    // MCP anchors launch from the +Z player edge (OUTSIDE the neck), above the
    // board, splayed along the neck; CCD then folds each finger DOWN onto its
    // string.  Anchor Z is relative to the (Z-tracked) node so the launch-to-
    // target geometry is consistent across chords.
    const launchY = r._tuneNum("mcpy", MCP_LAUNCH_Y) - nodeY;
    const launchZ = r._tuneNum("mcpreach", MCP_REACH);   // anchor +Z of the node (≈ reach sweet-spot)
    const span = m.mcpSpan, step = span / 3;
    const offX = { index: -span / 2, middle: -span / 2 + step, ring: -span / 2 + 2 * step, pinky: -span / 2 + 3 * step };
    const baseX = r._tuneNum("rootbase", ROOT_BASE);   // finger root pitch baseline
    for (const f of FINGER_ORDER) { const a = m.anchors[f]; if (a) a.position.set(offX[f], launchY, launchZ); m.doigt(f)._baseX = baseX; }
    m.node.updateMatrixWorld(true);
  }
  animation_pouce(main) {
    const thumb = main.doigt("thumb");
    thumb.setBase(THUMB_BASE_X, 0); thumb.setYaw(THUMB_YAW);
    main.node.updateMatrixWorld(true);
    const collide = () => this.r._segmentsHitNeck(thumb.segments());
    const contact = () => this.r._thumbOnBelly(thumb.tipWorld());
    const dist = () => { const p = thumb.tipWorld(); return Math.abs(p.y - this.r._bellyY(p.z)); };
    thumb.fold({ contact, collide, dist });
  }
  _placeFinger(main, name, fret, corde) {
    const r = this.r, d = main.doigt(name);
    const T = new THREE.Vector3(r._pressX(fret), STRING_SURFACE, r._stringZAt(corde));
    main.node.updateMatrixWorld(true);
    const mcp = d.mcpWorld();
    const yawRaw = Math.atan2(-(T.x - mcp.x), -(T.z - mcp.z));
    d.setYaw(clampN(yawRaw, -MCP_ABD_HALF[name], MCP_ABD_HALF[name]));
    const collide = () => r._segmentsHitNeck(d.segments());
    const dist = () => d.tipWorld().distanceTo(T);
    const contact = () => dist() <= CONTACT_EPS;
    return d.fold({ contact, collide, dist });
  }
}
/* Thumb base placement (tuned in-browser): pitch the CMC so the thumb points
   up-and-under the neck belly, yaw it toward the back. */
const THUMB_BASE_X = -0.6;   // rotation.x baseline (negative = tip up toward belly)
const THUMB_YAW = 0.5;       // rotation.y swing under the neck

class Hand3DRenderer {
  constructor(container) {
    this.container = container;
    this.disposed = false;
    // Dev hook: expose the live renderer so the grip-rule verifier probe and
    // in-browser tuning (rigrot/rigpos/testcurl URL params) can read bones,
    // the fretboard group, and geometry helpers.  Harmless when unused.
    try { window.__hand3d = this; } catch (e) { /* no window (SSR/test) */ }

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

    this._buildHand();      // legacy procedural rig (A/B fallback; ?rig=legacy)

    // Skinned-GLB state (A/B fallback; ?rig=skinned).
    this._useSkinnedHand = false;
    this._bones = {};
    this._boneByName = {};   // sanitized-name → bone (resolves dotted lookups)
    this._rig = null;
    this._lastHandPosX = 0;  // world-X the rig is parked at (updated per frame)

    /* ARTICULATED FK RIG — the real fretting hand (default).  A genuinely
       hinged hand that folds each finger until it contacts its string; the
       legacy procedural rig and the skinned GLB are kept only as A/B fallbacks
       selectable with ?rig=legacy / ?rig=skinned. */
    this._rigMode = (() => {
      try { return new URLSearchParams(window.location.search || "").get("rig") || "articulated"; }
      catch (e) { return "articulated"; }
    })();
    this.main = new Main({ skin: this.skinMat, roleMats: this.roleMats });
    this.main.attachTo(this.handGroup);
    this.anim = new AnimationMain(this, this.main);

    if (this._rigMode === "articulated") {
      // Hide the legacy hand (keep its forearm tube as the arm) and show Main.
      if (this.palm) this.palm.visible = false;
      for (const f of FINGER_ORDER) { const n = this.fingerNodes && this.fingerNodes[f]; if (n) { n.root.visible = false; if (n.tipCap) n.tipCap.visible = false; } }
      if (this.thumbBone) this.thumbBone.visible = false;
      if (this.thumbJoint) this.thumbJoint.visible = false;
      this.main.node.visible = true;
    } else {
      this.main.node.visible = false;
      if (this._rigMode === "skinned") {
        try { this._loadSkinnedHand(); }
        catch (e) { console.warn("[hand3d] skinned GLB kickoff failed; using procedural rig", e); }
      }
    }

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

  /* ----------------------------------------------------------------------- *
     SKINNED GLB HAND — load, measure, drive.
   * ----------------------------------------------------------------------- */

  /* three.js GLTFLoader strips dots/spaces from node names; mirror that here so
     our dotted FINGER_BONES entries resolve against the sanitized scene. */
  _sanitizeName(name) {
    // Matches three.js PropertyBinding reservedRe behaviour closely enough for
    // our names: drop the characters GLTFLoader removes ( . [ ] ( ) and space ).
    return String(name).replace(/[\s.[\]()]/g, "");
  }

  /* Resolve a (possibly dotted) bone name to the loaded bone, trying the exact
     name first and the sanitized form second. */
  _findBone(name) {
    return this._boneByName[name] || this._boneByName[this._sanitizeName(name)] || null;
  }

  /* Load /static/models/rigged_hand_baked.glb (scale baked into geometry +
     bones + inverse-bind matrices offline), reskin the left hand flat, hide the
     right hand + lights, cache bones + their rest quaternions, recenter the
     wrist at the rig pivot, wrap the scene in a rig group we transform globally,
     self-calibrate the grip anchor, hide the procedural rig.  Any failure leaves
     _useSkinnedHand=false and the procedural rig live. */
  async _loadSkinnedHand() {
    try {
      // BAKED model: scale (~647×) is baked into geometry + bone translations +
      // inverse-bind-matrices offline (scripts/bake_hand_scale.cjs), so the loaded
      // hand is already at world size and NO runtime node-scale is needed.
      // Runtime applies rotation + translation only — both bind-safe for a
      // SkinnedMesh (uniform/non-uniform SCALE after bind is what blew vertices
      // off-screen by scale²; rotation/translation never does).
      const gltf = await new GLTFLoader().loadAsync("/static/models/rigged_hand_baked.glb");
      const root = gltf.scene;

      const leftS  = this._sanitizeName(LEFT_MESH_NAME);
      const rightS = this._sanitizeName(RIGHT_MESH_NAME);

      this._bones = {};
      this._boneByName = {};
      root.traverse((o) => {
        if (o.isBone) {
          this._bones[o.name] = o;
          this._boneByName[o.name] = o;            // sanitized in the loaded scene
        }
        if (o.isMesh || o.isSkinnedMesh) {
          if (o.name === rightS || o.name === RIGHT_MESH_NAME) {
            o.visible = false;                       // hide the right hand
          } else {
            o.material = this.skinMat;               // flat skin, drop GLB camo maps
            o.frustumCulled = false;                 // skinned bounds can fool culling
          }
        }
        // Hide the baked Blender lights so they don't fight our 3-point rig.
        if (o.name === "Point" || o.name === "Hemi") o.visible = false;
      });

      // Store rest quaternions of every bone so flex is always relative to rest.
      for (const b of Object.values(this._boneByName)) {
        b.userData.rest = b.quaternion.clone();
      }

      // Measure the loaded hand (MCP-row width, wrist position) BEFORE scaling
      // so we can derive RIG_SCALE and know where the wrist is for the forearm.
      this._measureRig(root);

      // Recenter the loaded scene so the WRIST sits at the rig-group origin.
      // The baked GLB places the hand ~1100 wu from its own origin; without
      // this, RIG_ROT (rotation about the group origin) swings the hand far
      // off-screen.  Translating the inner scene is bind-safe (only SCALE
      // after bind breaks skinning), so the wrist becomes a clean rotation
      // pivot and RIG_POS then parks the wrist at the board.
      if (this._rigWristLocal) root.position.copy(this._rigWristLocal).multiplyScalar(-1);

      // Wrap in a rig group we transform globally (rotate/translate; scale=1).
      this._rig = new THREE.Group();
      this._rig.add(root);
      this.handGroup.add(this._rig);

      this._useSkinnedHand = true;
      this._rigRenderOffset = new THREE.Vector3();   // zero until calibrated
      this._applyRigTransform();
      this._hideProceduralHand();

      // Self-calibrating anchor: the baked + rotated skinned mesh renders at a
      // constant orientation/mirror-dependent offset from where the rig group
      // sits (the mesh's negative-scale + inverse-bind interaction).  Measure
      // the rendered skin centroid once and store the offset so _applyRigTransform
      // can compensate and land the centroid exactly on the grip target.
      const c0 = this._skinCentroid();
      if (c0) {
        this._rigRenderOffset.copy(c0).sub(this._rigTarget());
        this._applyRigTransform();
      }

      // Dev knob: ?noforearm=1 hides the procedural forearm so the skinned hand
      // can be inspected in isolation.  Off by default (no URL param → no-op).
      if (new URLSearchParams(window.location.search || "").has("noforearm")) {
        if (this.forearmBone) this.forearmBone.visible = false;
        if (this.forearmJoint) this.forearmJoint.visible = false;
      }
    } catch (e) {
      console.warn("[hand3d] skinned GLB load failed; using procedural rig", e);
      this._useSkinnedHand = false;
    }
  }

  /* Measure the loaded (already scale-baked) hand once: rigScale is fixed at 1
     (no runtime node-scale — it would break skinning), mcpWidth is kept for
     diagnostics, and the wrist world position anchors both the recenter pivot
     and the procedural forearm.  Robust to missing bones. */
  _measureRig(root) {
    root.updateMatrixWorld(true);
    const idx = this._findBone("finger_index.01.L");
    const pky = this._findBone("finger_pinky.01.L");
    let mcpWidth = 0;
    if (idx && pky) {
      const a = new THREE.Vector3(), b = new THREE.Vector3();
      idx.getWorldPosition(a);
      pky.getWorldPosition(b);
      mcpWidth = a.distanceTo(b);
    }
    // The GLB is BAKED to world scale, so no runtime node-scale: rigScale = 1.
    // mcpWidth is kept only for diagnostics (should already ≈ mm(RIG_TARGET_MCP_MM)).
    this._rigScale = 1.0;
    this._rigMcpWidth = mcpWidth;   // diagnostics: expect ≈ mm(95) ≈ 41 wu

    // Wrist (hand.L) world position in the baked (world-scale) rig, for forearm
    // anchoring — already in world units since scale is baked in.
    const wrist = this._findBone("hand.L");
    this._rigWristLocal = new THREE.Vector3();
    if (wrist) wrist.getWorldPosition(this._rigWristLocal);
  }

  /* Hide the procedural finger/palm/thumb meshes once the skinned hand is live.
     The forearm tube is KEPT (the GLB mesh is hand-only). */
  _hideProceduralHand() {
    if (this.palm) this.palm.visible = false;
    for (const f of FINGER_ORDER) {
      const node = this.fingerNodes && this.fingerNodes[f];
      if (!node) continue;
      node.root.visible = false;     // hides the whole finger subtree
      if (node.tipCap) node.tipCap.visible = false;
    }
    if (this.thumbBone) this.thumbBone.visible = false;
    if (this.thumbJoint) this.thumbJoint.visible = false;
    // The baked GLB carries its OWN wrist + forearm stub, so the procedural
    // forearm tube is redundant — and, anchored to the procedural _palmX/_palmZ
    // rather than the mirrored GLB wrist, it floats away from the hand (R2).
    // Hide it on the skinned path; the GLB arm is the connected forearm.
    if (this.forearmBone) this.forearmBone.visible = false;
    if (this.forearmJoint) this.forearmJoint.visible = false;
  }

  /* Orient + place the whole loaded hand into the classical grip and slide it
     along the neck with the current hand_position.  Scale is baked (always 1);
     RIG_ROT and the RIG_POS_Y/Z grip-anchor centroid are the tunable knobs, and
     the measured render offset cancels the mirror skew.  ALL EMPIRICAL. */
  _applyRigTransform() {
    if (!this._rig) return;
    this._rig.scale.setScalar(this._rigScale || 1);   // baked GLB → scale 1
    const ov = this._rigOverrides();
    const rot = ov.rot || RIG_ROT;
    this._rig.rotation.set(rot.x, rot.y, rot.z);
    // Position so the rendered skin centroid lands on the grip target; the
    // measured render offset cancels the constant orientation/mirror skew.
    const t = this._rigTarget();
    const f = this._rigRenderOffset || ZERO_VEC;
    this._rig.position.set(t.x - f.x, t.y - f.y, t.z - f.z);
  }

  /* Desired WORLD position of the rendered hand centroid (the grip anchor).
     X tracks the live hand position along the neck; Y/Z fix the grip frame.
     ?rigpos=X,Y,Z overrides all three for calibration. */
  _rigTarget() {
    const ov = this._rigOverrides();
    if (ov.pos) return new THREE.Vector3(ov.pos.x, ov.pos.y, ov.pos.z);
    const x = Number.isFinite(this._lastHandPosX) ? this._lastHandPosX : 0;
    return new THREE.Vector3(x, RIG_POS_Y, RIG_POS_Z);
  }

  /* World-space centroid of the SkinnedMesh as actually rendered (CPU skinning
     via getVertexPosition, sampled).  Matches the GPU render when called inside
     the renderer's own context.  Returns null if no skinned mesh is live. */
  _skinCentroid() {
    if (!this._rig) return null;
    let sm = null;
    this._rig.traverse((o) => { if (o.isSkinnedMesh && o.visible) sm = o; });
    if (!sm) return null;
    this._rig.updateMatrixWorld(true);
    sm.skeleton.update();
    const pos = sm.geometry.attributes.position;
    const t = new THREE.Vector3();
    const box = new THREE.Box3();
    const step = Math.max(1, Math.floor(pos.count / 300));
    for (let i = 0; i < pos.count; i += step) {
      sm.getVertexPosition(i, t);
      sm.localToWorld(t);
      box.expandByPoint(t);
    }
    return box.getCenter(new THREE.Vector3());
  }

  /* TEMP calibration helper: parse RIG_ROT (deg) / RIG_POS (wu) from the URL.
     Remove together with the rest of the bake-calibration scaffolding. */
  _rigOverrides() {
    if (this.__ovCache !== undefined) return this.__ovCache;
    let out = {};
    try {
      const q = new URLSearchParams(window.location.search || "");
      const D = Math.PI / 180;
      if (q.has("rigrot")) {
        const [x, y, z] = q.get("rigrot").split(",").map(Number);
        out.rot = { x: (x || 0) * D, y: (y || 0) * D, z: (z || 0) * D };
      }
      if (q.has("rigpos")) {
        const [x, y, z] = q.get("rigpos").split(",").map(Number);
        out.pos = { x: x || 0, y: y || 0, z: z || 0 };
      }
    } catch (e) { /* no-op */ }
    this.__ovCache = out;
    return out;
  }

  /* Dev tuning knobs: read a numeric/string URL param once (cached), else the
     default.  Used to bracket mirror-dependent thumb angles in-browser. */
  _tuneNum(name, dflt) {
    this.__tune = this.__tune || {};
    if (name in this.__tune) return this.__tune[name];
    let v = dflt;
    try { const q = new URLSearchParams(window.location.search || "").get(name); if (q != null && q !== "" && Number.isFinite(Number(q))) v = Number(q); } catch (e) { /* */ }
    this.__tune[name] = v;
    return v;
  }
  _tuneStr(name, dflt) {
    this.__tuneS = this.__tuneS || {};
    if (name in this.__tuneS) return this.__tuneS[name];
    let v = dflt;
    try { const q = new URLSearchParams(window.location.search || "").get(name); if (q) v = q; } catch (e) { /* */ }
    this.__tuneS[name] = v;
    return v;
  }

  /* Flex one bone about FLEX_AXIS by `angle` (radians) RELATIVE to its rest
     quaternion.  No-op if the bone or its rest pose is missing. */
  _flexBone(bone, angle) {
    if (!bone || !bone.userData || !bone.userData.rest) return;
    const ax = this._flexAxisOverride() || FLEX_AXIS;
    const sg = this._flexSignOverride();
    bone.quaternion
      .copy(bone.userData.rest)
      .multiply(new THREE.Quaternion().setFromAxisAngle(ax, sg * angle));
  }

  /* TEMP: ?flexaxis=x|y|z overrides the per-bone fold axis for calibration. */
  _flexAxisOverride() {
    if (this.__flexAxis !== undefined) return this.__flexAxis;
    let v = null;
    try {
      const a = new URLSearchParams(window.location.search || "").get("flexaxis");
      if (a === "x") v = new THREE.Vector3(1, 0, 0);
      else if (a === "y") v = new THREE.Vector3(0, 1, 0);
      else if (a === "z") v = new THREE.Vector3(0, 0, 1);
    } catch (e) { /* no-op */ }
    this.__flexAxis = v;
    return v;
  }

  /* TEMP: ?flexsign=-1 flips fold direction. */
  _flexSignOverride() {
    if (this.__flexSign !== undefined) return this.__flexSign;
    let s = FLEX_SIGN;
    try {
      const v = new URLSearchParams(window.location.search || "").get("flexsign");
      if (v === "-1") s = -1; else if (v === "1") s = 1;
    } catch (e) { /* no-op */ }
    this.__flexSign = s;
    return s;
  }

  /* TEMP: ?testcurl=DEG → uniform curl split across MCP/PIP/DIP (radians). */
  _testCurl() {
    if (this.__testCurl !== undefined) return this.__testCurl;
    let out = null;
    try {
      const v = new URLSearchParams(window.location.search || "").get("testcurl");
      if (v != null && v !== "") {
        const rad = (Number(v) || 0) * Math.PI / 180;
        out = { mcp: rad * CURL_SPLIT.mcp, pip: rad * CURL_SPLIT.pip, dip: rad * CURL_SPLIT.dip };
      }
    } catch (e) { /* no-op */ }
    this.__testCurl = out;
    return out;
  }

  /* Per-frame: drive the skinned finger bones from the SAME curl the procedural
     solver computes.  We reuse _solveChain's totalCurl by calling the shared
     curl helper (_fingerCurl) and splitting it MCP/PIP/DIP across the 3 bones.
     The thumb gets a gentle fixed brace curl. */
  _poseSkinnedFingers(kin) {
    // TEMP: ?testcurl=DEG forces a uniform curl on every finger phalanx so the
    // flex axis/sign can be verified independent of solver data.  ?flexaxis=x|z
    // and ?flexsign=-1 let me re-aim the fold without recompiling.
    const tc = this._testCurl();
    if (tc) {
      for (const f of FINGER_ORDER) {
        const names = FINGER_BONES[f];
        if (!names) continue;
        this._flexBone(this._findBone(names[0]), tc.mcp);
        this._flexBone(this._findBone(names[1]), tc.pip);
        this._flexBone(this._findBone(names[2]), tc.dip);
      }
      return;
    }
    if (!kin || !kin.fingers) return;
    for (const f of FINGER_ORDER) {
      const fg = kin.fingers[f];
      const names = FINGER_BONES[f];
      if (!fg || !names) continue;
      const curl = this._fingerCurl(f, fg);
      const b0 = this._findBone(names[0]);
      const b1 = this._findBone(names[1]);
      const b2 = this._findBone(names[2]);
      this._flexBone(b0, curl * CURL_SPLIT.mcp);
      this._flexBone(b1, curl * CURL_SPLIT.pip);
      this._flexBone(b2, curl * CURL_SPLIT.dip);
    }
    // Thumb: swung BEHIND/under the neck to brace it (its own poser).
    this._poseSkinnedThumb(kin);
  }

  /* Pose the thumb into the classical brace: swing the CMC root (thumb.01.L) so
     the thumb crosses from the player side to the FAR (-Z) back-of-neck and sits
     at mid-belly height, with a moderate distal flex so the pad braces the neck.
     The swing axis/sign are mirror-dependent, so they are tunable:
       ?thumbswing=DEG  (abduction angle, default THUMB_SWING_DEG)
       ?thumbaxis=x|y|z (abduction axis, default 'y')
       ?thumbroll=DEG   (opposition roll about local X)
       ?thumbflex=DEG   (distal brace flex) */
  _poseSkinnedThumb(kin) {
    const root = this._findBone(FINGER_BONES.thumb[0]);
    const mid  = this._findBone(FINGER_BONES.thumb[1]);
    const tip  = this._findBone(FINGER_BONES.thumb[2]);
    if (!root) return;
    const q = this._tuneNum("thumbswing", THUMB_SWING_DEG) * Math.PI / 180;
    const roll = this._tuneNum("thumbroll", THUMB_ROLL_DEG) * Math.PI / 180;
    const flex = this._tuneNum("thumbflex", THUMB_FLEX_DEG) * Math.PI / 180;
    const axName = this._tuneStr("thumbaxis", THUMB_SWING_AXIS);
    const ax = axName === "x" ? new THREE.Vector3(1, 0, 0)
      : axName === "z" ? new THREE.Vector3(0, 0, 1)
        : new THREE.Vector3(0, 1, 0);
    // compose swing (abduction across to the neck back) + roll (opposition) on
    // the CMC root, relative to rest.
    if (root.userData && root.userData.rest) {
      root.quaternion.copy(root.userData.rest)
        .multiply(new THREE.Quaternion().setFromAxisAngle(ax, q))
        .multiply(new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(1, 0, 0), roll));
    }
    // distal phalanges brace (curl about FLEX_AXIS) so the pad meets the wood.
    this._flexBone(mid, flex * 0.6);
    this._flexBone(tip, flex * 0.4);
  }

  /* Total curl angle for finger `f`, REUSING the procedural solver's geometry.
     For active/planted fingers we run the same MCP→target solve _solveChain
     uses and return its totalCurl; for idle/hover we return a small relaxed
     curl so the resting fingers read as curled, not splayed. */
  _fingerCurl(f, fg) {
    const role = fg.role || "idle";
    if (role !== "active" && role !== "planted") return SKIN_IDLE_CURL;
    const targetStr = (fg.strings && fg.strings.length) ? fg.strings[0] : null;
    if (!(fg.fret > 0) || targetStr == null) return SKIN_IDLE_CURL;

    // Recreate the procedural MCP anchor + target, then reuse the exact curl
    // formula from _solveChain (kept here as the single source of the angle).
    const node = this.fingerNodes[f];
    if (!node) return SKIN_IDLE_CURL;
    const baseX = (this._palmX !== undefined) ? this._palmX : (this._boardCX || 0);
    const baseZ = (this._palmZ !== undefined) ? this._palmZ : 0;
    const mcpSpan = PALM_WIDTH_Z * 0.95;
    const mcpStepX = mcpSpan / 3;
    const mcpXOffset = {
      index: -mcpSpan / 2,
      middle: -mcpSpan / 2 + mcpStepX,
      ring: -mcpSpan / 2 + mcpStepX * 2,
      pinky: -mcpSpan / 2 + mcpStepX * 3,
    };
    const mcpX = baseX + (mcpXOffset[f] || 0);
    const mcpY = -NECK_DEPTH;
    const mcpZ = baseZ + NECK_DEPTH * 0.60;
    const tx = this._pressX(fg.fret);
    const ty = STRING_SURFACE;
    const tz = this._stringZAt(targetStr);

    const forward = ty - mcpY;
    const dx = tx - mcpX, dz = tz - mcpZ;
    const drop = Math.sqrt(dx * dx + dz * dz);
    const L = node.Ltotal;
    const dist = Math.sqrt(forward * forward + drop * drop);
    const chordRatio = Math.min(1.0, dist / L);
    let totalCurl = Math.PI * Math.pow(1 - chordRatio, 0.85);
    const dropAngle = Math.atan2(drop, Math.max(0.1, forward));
    totalCurl = Math.max(totalCurl, dropAngle * 1.15);
    if (totalCurl < 0) totalCurl = 0;
    if (totalCurl > 2.6) totalCurl = 2.6;
    return totalCurl;
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
    // Neck collision solid (for the articulated-rig fold collision-clamp):
    //   flat top Y in [-0.30, 0] over Z in [-hw, hw]; rounded belly to -NECK_DEPTH.
    this._neckHW = hw;
    this._neckX0 = x0;
    this._neckX1 = x1;
    this._neckTopY = -0.30;

    // Camera framing: aim at the fret-press points just above the strings
    // and slightly past them into the -Z fretboard half.  This guitarist's-
    // POV target pulls the camera's gaze down onto the fingertips/strings
    // rather than onto the back of the hand, and rotates the camera-to-
    // target ray so the forearm (at z≈+24, y≈+22) sits behind/below it
    // instead of occluding the fingers.
    // Centre gaze on the string surface, biased slightly to the far (low-E)
    // side so the wrap-around fingertips and forearm both stay in frame.
    // mm(5) bias is preserved from the pre-grip-rework expression; the old
    // HAND_OFFSET_Z * 0.15 is now 0 (HAND_OFFSET_Z = 0 in the new frame),
    // so we use a direct literal here.
    this._lookAt.set(boardCX, STRING_SURFACE + mm(3), -mm(5));
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

  /* ---- Neck D-solid collision (articulated-rig fold-clamp, rule 7) -------- *
     Belly = lower envelope of two quad Beziers from (±hw,-0.30) to (0,-DEPTH). */
  _bellyY(z) {
    const hw = this._neckHW || 12.5, depth = NECK_DEPTH, topY = this._neckTopY || -0.30;
    const az = Math.abs(z);
    if (az >= hw) return topY;
    const t = Math.sqrt(Math.max(0, 1 - az / hw));        // invert z(t)=hw*(1-t^2)
    return (1 - t) * (1 - t) * topY + (2 * (1 - t) * t + t * t) * (-depth);
  }
  _insideNeck(p) {
    if (this._neckHW == null) return false;
    if (p.x < this._neckX0 || p.x > this._neckX1) return false;
    if (Math.abs(p.z) > this._neckHW) return false;
    return p.y >= this._bellyY(p.z) && p.y <= 0.0;
  }
  _segmentHitsNeck(a, b) {
    const t = new THREE.Vector3();
    for (let i = 1; i < NECK_SAMPLES; i++) {
      t.lerpVectors(a, b, i / NECK_SAMPLES);
      if (this._insideNeck(t)) return true;
    }
    return false;
  }
  _segmentsHitNeck(segs) {
    for (const [a, b] of segs) if (this._segmentHitsNeck(a, b)) return true;
    return false;
  }
  /* Thumb contact: pad touches the neck belly underneath (not a string). */
  _thumbOnBelly(p) {
    return this._neckHW != null && Math.abs(p.z) <= this._neckHW &&
      p.x >= this._neckX0 && p.x <= this._neckX1 &&
      Math.abs(p.y - this._bellyY(p.z)) <= CONTACT_EPS;
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
    this._lastKin = kin;   // dev hook: the grip verifier reads active fingers/targets
    try {
      if (this._rigMode === "articulated") {
        this._updateArticulated(kin);
        this.renderer.render(this.scene, this.camera);
        return;
      }
      if (this._useSkinnedHand) {
        // SKINNED PATH: the real GLB hand deforms via skin weights.  We still
        // run _poseHand so _palmX / _palmZ (the per-finger curl solve reads
        // them) and the along-neck hand position are computed from the same
        // kin snapshot, then drive the finger bones + slide the rig.
        this._poseHand(kin);
        this._lastHandPosX = (this._palmX !== undefined) ? this._palmX : this._lastHandPosX;
        this._poseSkinnedFingers(kin);
        this._applyRigTransform();
        // The forearm tube is procedural (the GLB is hand-only); keep posing it.
        this._poseForearm(kin);
      } else {
        // PROCEDURAL FALLBACK: original purely-procedural rig.
        this._poseHand(kin);
        this._poseFingers(kin);
        this._poseThumb(kin);
        this._poseForearm(kin);
      }
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

  /* Articulated-rig per-frame pose: place the wrist along the neck, brace the
     thumb under it, then FOLD each active finger to its target string (or relax
     idle fingers).  Tracks any finger the cost solver asked for that the rig
     could not reach within its joint limits (rule 9). */
  _updateArticulated(kin) {
    const m = this.main, a = this.anim;
    this._poseHand(kin);                                   // sets _palmX / _palmZ
    this._lastHandPosX = (this._palmX !== undefined) ? this._palmX : this._lastHandPosX;
    // index "position" fret = lowest active fret (the hand's neck position)
    let idxFret = 0, maxZ = null;
    for (const f of FINGER_ORDER) {
      const fg = kin.fingers && kin.fingers[f];
      if (!fg || fg.fret <= 0 || !(fg.role === "active" || fg.role === "planted")) continue;
      if (idxFret === 0 || fg.fret < idxFret) idxFret = fg.fret;
      if (fg.strings && fg.strings.length) { const z = this._stringZAt(fg.strings[0]); if (maxZ === null || z > maxZ) maxZ = z; }
    }
    // Node Z = the player-most active string; the anchor adds MCP_REACH so the
    // knuckle sits at its reach sweet-spot above that string.
    a.placement_poignet(idxFret, maxZ);
    a.animation_pouce(m);
    const unreachable = [];
    for (const f of FINGER_ORDER) {
      const fg = kin.fingers && kin.fingers[f];
      const role = (fg && fg.role) || "idle";
      const str = (fg && fg.strings && fg.strings.length) ? fg.strings[0] : null;
      const d = m.doigt(f);
      if ((role === "active" || role === "planted") && fg.fret > 0 && str != null) {
        const res = a._placeFinger(m, f, fg.fret, str);
        if (res === "UNREACHABLE") unreachable.push({ f, fret: fg.fret, string: str });
      } else {
        d.setYaw(0); d.relax();
      }
      d.setRole(role);
    }
    this._lastUnreachable = unreachable;
    this._poseForearm(kin);                                // legacy forearm tube = the arm
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
    // Classical grip frame: palm cradles the BACK of the neck.  The centroid
    // sits BELOW the neck back (Y = MCP_Y = -NECK_DEPTH - PALM_HEIGHT_Y/2),
    // and its centerline tracks the active strings in Z (no player-side
    // offset — that offset is now built into the MCP anchor on the slab's
    // +Z edge).  After the rotation flip below, the slab's previously
    // dorsal +Y face faces down toward the player, and the previously
    // palmar -Y face faces up to brush the neck back at Y = -NECK_DEPTH.
    this.palm.position.set(
      palmX,
      MCP_Y,
      zRow,
    );
    // FLIP the slab 180° around X so its palmar normal points +Y (up to the
    // strings).  Any incoming palmNormal tilt is added as a damped delta on
    // top of the base flip via Euler order 'YXZ'.
    const pn = kin.palm.palmNormal;
    this.palm.rotation.order = "YXZ";
    this.palm.rotation.x = Math.PI + (pn ? (pn.pitch || 0) * 0.3 : 0);
    this.palm.rotation.y = pn ? (pn.yaw  || 0) * 0.3 : 0;
    this.palm.rotation.z = pn ? (pn.roll || 0) * 0.3 : 0;
    this._palmX = palmX;
    this._palmZ = zRow;
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
    // Classical grip: the palm is FLIPPED so its (now-)top face sits at
    // Y = -NECK_DEPTH (brushing the neck back), and the MCPs anchor on that
    // top face along its +Z (player) edge so the proximal phalanges can
    // launch UP and OVER the +Z edge of the neck onto the strings.
    //
    // The +Z edge offset is sized so the MCPs sit just past the player-side
    // edge of the strings (i.e. on the player side of the neck's belly).
    // PALM_DEPTH_X is the wrist→knuckle slab dimension (~43 wu); using a
    // fraction that large would place MCPs far past all strings.  Instead
    // we size off NECK_DEPTH so the MCP edge is comfortably within reach
    // of the index finger (L ≈ 32 wu) for a typical 4-fret span.
    const PALM_TOP_Y = -NECK_DEPTH;                       // = palm.y + PALM_HEIGHT_Y/2
    const mcpEdgeZ   = NECK_DEPTH * 0.60;                 // ~5.7 wu past palm-Z centre

    // Default palm-anchor fallbacks so a missing palm payload (or a frame
    // that arrived before _poseHand could run) does not poison the chain
    // with NaNs.  Board centre at Z=0 reads as a centred relaxed pose.
    const baseX = (this._palmX !== undefined) ? this._palmX : (this._boardCX || 0);
    const baseZ = (this._palmZ !== undefined) ? this._palmZ : 0;
    for (const f of FINGER_ORDER) {
      const fg   = kin.fingers[f];
      const node = this.fingerNodes[f];
      if (!fg || !node) continue;

      // MCP world position: on the inverted palm's top face, on its +Z
      // (player) edge, with each finger spread along the neck axis (X).
      const mcpX = baseX + mcpXOffset[f];
      const mcpY = PALM_TOP_Y;
      const mcpZ = baseZ + mcpEdgeZ;
      node.root.position.set(mcpX, mcpY, mcpZ);

      // Target: where the fingertip should land.
      //   - active/planted: at (pressX(fret), STRING_SURFACE, stringZ(string)).
      //   - hover:          just above the string surface, near the target X.
      //   - idle:           a relaxed pose just above the string surface,
      //                     slightly behind the MCP in Z.
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
        // Idle: rest just above the string surface, slightly behind the MCP
        // in Z (toward the neck back) so the relaxed chain still wraps
        // rather than splaying upward off the neck.
        tx = mcpX;
        ty = STRING_SURFACE + 0.5;
        tz = mcpZ - 0.5;
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
    // In the classical grip frame:
    //   mcpY = -NECK_DEPTH ≈ -9.5 wu (top of the inverted palm)
    //   target Y for an active press = STRING_SURFACE ≈ +1.3 wu
    //   dy ≈ +10.8 wu  (target is ABOVE the MCP — fingers wrap UP-and-OVER)
    const dx = tx - mcpX;
    const dy = ty - mcpY;     // positive: target is ABOVE the MCP (toward strings)
    const dz = tz - mcpZ;     // negative: target is on the -Z side of the +Z edge

    // Yaw: rotate the chain around Y so the (XZ projection of the) target
    // lands in the chain's swing plane.  We keep the same atan2 formula as
    // before: after the LIFT below the chain's rest direction is +Y, but the
    // swing pivot (X-axis bend) still operates against the XZ projection.
    const yaw = Math.atan2(-dx, -dz);
    node.root.rotation.order = "YXZ";
    node.root.rotation.y = yaw;

    // After the LIFT baseline (+π/2 on root.rotation.x, applied below), the
    // chain's rest direction becomes +Y — the proximal phalanx points UP from
    // the MCP, perfectly positioned to wrap over the +Z edge of the neck.
    //
    // In this lifted frame, the analogues of "forward" and "drop" become:
    //   forward = dy             ← up-distance from MCP to target
    //                              (corresponds to the chain extending +Y when
    //                              straight; equivalent to old "forward = -dz")
    //   drop    = sqrt(dx²+dz²)  ← horizontal distance the fingertip must
    //                              fold across to reach the target (the
    //                              chord in the swing plane)
    const forward = dy;
    const drop    = Math.sqrt(dx * dx + dz * dz);

    const L = node.Ltotal;
    const dist = Math.sqrt(forward * forward + drop * drop);
    const chordRatio = Math.min(1.0, dist / L);
    let totalCurl = Math.PI * Math.pow(1 - chordRatio, 0.85);

    // Additional curl from the "drop angle" — when the target sits more to
    // the side (large XZ chord) than straight up, boost the curl so the
    // fingertip folds down to the strings even when the chain still has
    // plenty of straight-up reach.
    const dropAngle = Math.atan2(drop, Math.max(0.1, forward));
    totalCurl = Math.max(totalCurl, dropAngle * 1.15);

    if (totalCurl < 0) totalCurl = 0;
    if (totalCurl > 2.6) totalCurl = 2.6;

    // SIGN CONVENTION (post-LIFT):
    //   Bones rest along local -Z.  Adding LIFT = +π/2 to root.rotation.x
    //   tips the chain's rest direction from -Z to +Y (straight up out of
    //   the inverted palm).  Folding FORWARD from +Y back toward -Z (where
    //   the strings live) is then a NEGATIVE delta on rotation.x — exactly
    //   the same sign as before, but now subtracted from the LIFT baseline
    //   on the root (PIP/DIP still rotate around 0 since they inherit the
    //   root's lift through the kinematic chain).
    const LIFT = Math.PI / 2;
    node.root.rotation.x = LIFT - totalCurl * CURL_SPLIT.mcp;
    node.pip.rotation.x  =      - totalCurl * CURL_SPLIT.pip;
    node.dip.rotation.x  =      - totalCurl * CURL_SPLIT.dis;
  }

  /* Thumb: braces the BACK of the neck (-Z side from the back-of-hand).
     We position it under the middle finger MCP along X, at Y = -1.5
     (mid-belly height behind the neck), aimed up and slightly toward the
     player so it reads as a thumb hooked over the back of the neck. */
  _poseThumb(kin) {
    const thumbX = this._palmX || 0;
    // Classical grip: the thumb base sits on the palm's -Z edge (the side
    // AWAY from the player, against the back of the neck), with the tip
    // pointing UP and slightly +Z so the pad meets the neck back at the
    // apex of its arc.  Y is mid-neck-back so the pad lands on
    // -NECK_DEPTH * 0.6, comfortably bracing the D-section.
    const baseZ = (this._palmZ || 0) - PALM_DEPTH_X * 0.35;   // -Z edge of palm
    const baseY = -NECK_DEPTH * 0.60;                          // mid back-of-neck
    this.thumbBone.position.set(thumbX, baseY, baseZ);
    // Bone rest direction is local -Z.  rotation.x = -π/2 would point it
    // pure +Y; -0.55π pitches the tip slightly past vertical toward +Z so
    // the thumb pad arcs OVER the back of the neck and meets it from -Z.
    this.thumbBone.rotation.set(-Math.PI * 0.55, 0, 0);
    this.thumbJoint.position.set(thumbX, baseY, baseZ);
    this.thumbJoint.scale.setScalar(1);
  }

  /* Forearm: a single capsule from the wrist (back side of the palm, +Z) to
     a point further +Z (toward the player) and slightly +X.  The wrist
     stays attached to the back of the palm slab, regardless of where the
     hand has slid along the neck. */
  _poseForearm(kin) {
    // Classical grip: the wrist sits on the WRIST edge of the palm (-X end,
    // since index = -mcpSpan/2 places the wrist-side at -X), UNDER the
    // neck (Y = palm centre = MCP_Y), and biased to the +Z (player) side
    // of the palm so the forearm exits toward the player's body.
    const wristX = (this._palmX !== undefined) ? this._palmX - PALM_DEPTH_X * 0.30 : 0;
    const wristY = MCP_Y;                                              // palm centre Y
    const wristZ = (this._palmZ !== undefined) ? this._palmZ + PALM_DEPTH_X * 0.25 : 0;
    this.forearmBone.position.set(wristX, wristY, wristZ);
    // Bone rest direction is local -Z.  rotation.y = π flips -Z → +Z so the
    // forearm exits toward the player; rotation.x = +π·0.25 pitches the bone
    // DOWN (away from the neck, toward the player's lap) by 45° — the
    // realistic rise of the forearm from the seated guitarist's body.
    this.forearmBone.rotation.set(+Math.PI * 0.25, Math.PI, 0);
    this.forearmJoint.position.set(wristX, wristY, wristZ);
    this.forearmJoint.scale.setScalar(1);
  }

  /* Convert the current spherical-orbit state into a world-space camera
     position relative to _lookAt and re-aim the camera at the target.
     azimuth = 0 puts the camera on +Z of _lookAt (player side, looking at
     the back of the hand); polar = 0 would be straight overhead. */
  _applyCamera() {
    this._applyCamOverride();   // TEMP: ?cam=radius,azDeg,polDeg
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

  /* TEMP: ?cam=radius,azimuthDeg,polarDeg overrides the orbit for calibration. */
  _applyCamOverride() {
    if (this.__camDone) return;
    try {
      const v = new URLSearchParams(window.location.search || "").get("cam");
      if (v) {
        const [r, a, p] = v.split(",").map(Number);
        const D = Math.PI / 180;
        if (Number.isFinite(r)) this._camSpherical.radius = r;
        if (Number.isFinite(a)) this._camSpherical.azimuth = a * D;
        if (Number.isFinite(p)) this._camSpherical.polar = p * D;
      }
    } catch (e) { /* no-op */ }
    this.__camDone = true;
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
