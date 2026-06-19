#!/usr/bin/env node
/* ===========================================================================
 * bake_hand_scale.cjs — offline scale bake for the 3D fretting-hand GLB
 * ===========================================================================
 *
 * WHY
 *   The vendored `rigged_hand.glb` is authored at ~0.063 wu knuckle-row width.
 *   The fretboard scene needs the hand at a real ~95 mm (≈41 world units), i.e.
 *   roughly 648× bigger.  Scaling the SkinnedMesh's parent group AT RUNTIME does
 *   not work: GLTFLoader freezes the inverse-bind matrices at load (unscaled),
 *   so a post-bind node scale S flings skinned vertices off-screen by S² (≈648²
 *   → ~42000 wu).  The fix is to bake the scale into the asset so the runtime
 *   only ever rotates/translates the hand (both bind-safe).
 *
 * WHAT
 *   A uniform scale S is consistent across a skinned glTF iff it is applied to
 *   ALL THREE of:
 *     1. every node TRANSLATION          (the skeleton's bone offsets)
 *     2. every mesh POSITION accessor    (the bind-pose vertices)
 *     3. every inverse-bind-matrix translation column (idx 12,13,14 / 16)
 *   Rotations in the IBMs and node TRS are scale-invariant and untouched.
 *
 * USAGE
 *   npm i @gltf-transform/core
 *   node scripts/bake_hand_scale.cjs \
 *     src/fretwise/web/static/models/rigged_hand.glb \
 *     src/fretwise/web/static/models/rigged_hand_baked.glb [scale]
 *
 *   `scale` defaults to 647 (= mm(95) / 0.0634).  The runtime (_measureRig)
 *   then reads rigScale = 1 and self-anchors the grip, so re-baking at a
 *   different S only changes the hand's world size, nothing else.
 * =========================================================================== */
const { NodeIO } = require("@gltf-transform/core");

async function main() {
  const [src, dst, scaleArg] = process.argv.slice(2);
  if (!src || !dst) {
    console.error("usage: node bake_hand_scale.cjs <in.glb> <out.glb> [scale]");
    process.exit(2);
  }
  const S = Number(scaleArg) || 647.0;
  const io = new NodeIO();
  const doc = await io.read(src);
  const root = doc.getRoot();

  // 1. node translations
  for (const n of root.listNodes()) {
    const t = n.getTranslation();
    n.setTranslation([t[0] * S, t[1] * S, t[2] * S]);
  }
  // 2. mesh POSITION accessors
  for (const m of root.listMeshes()) {
    for (const p of m.listPrimitives()) {
      const pos = p.getAttribute("POSITION");
      if (!pos) continue;
      const a = pos.getArray().slice();
      for (let i = 0; i < a.length; i++) a[i] *= S;
      pos.setArray(a);
    }
  }
  // 3. inverse-bind-matrix translation columns
  for (const skin of root.listSkins()) {
    const ibm = skin.getInverseBindMatrices();
    if (!ibm) continue;
    const a = ibm.getArray().slice();
    for (let j = 0; j < a.length; j += 16) {
      a[j + 12] *= S;
      a[j + 13] *= S;
      a[j + 14] *= S;
    }
    ibm.setArray(a);
  }

  await io.write(dst, doc);
  console.log(`baked ${src} -> ${dst} (scale ${S} into geometry + bones + IBMs)`);
}

main().catch((e) => {
  console.error("bake failed:", e.message);
  process.exit(1);
});
