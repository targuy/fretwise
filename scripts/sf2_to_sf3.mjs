/**
 * sf2_to_sf3.mjs — Convert an SF2 soundfont to SF3 (Ogg-Vorbis compressed) using
 * the vendored spessasynth_core for SF2 parse/write and ffmpeg (libvorbis) as the
 * per-sample encoder. SF3 keeps the same instrument structure but stores samples
 * as Ogg Vorbis, cutting size ~8-12x with negligible audible loss — so a 178 MB
 * guitar pack becomes ~15-25 MB that loads fast and never freezes the browser.
 *
 * Usage:
 *   node scripts/sf2_to_sf3.mjs <input.sf2> <output.sf3> [vorbisQuality 0-10]
 *   (FFMPEG env var overrides the ffmpeg executable path)
 */
import fs from 'node:fs';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const [, , inPath, outPath, qArg] = process.argv;
if (!inPath || !outPath) {
  console.error('usage: node scripts/sf2_to_sf3.mjs <input.sf2> <output.sf3> [quality 0-10]');
  process.exit(1);
}
const FFMPEG = process.env.FFMPEG || 'ffmpeg';
const QUALITY = qArg != null ? Number(qArg) : 6;  // libvorbis -q:a; 6 ≈ ~192 kbps VBR

const coreUrl = pathToFileURL('src/fretwise/web/static/js/vendor/spessasynth_core.esm.js').href;
const core = await import(coreUrl);

/** Encode mono Float32 PCM → Ogg Vorbis bytes via ffmpeg/libvorbis. */
function encodeOggVorbis(float32, sampleRate) {
  const input = Buffer.from(float32.buffer, float32.byteOffset, float32.byteLength);
  const r = spawnSync(FFMPEG, [
    '-hide_banner', '-loglevel', 'error',
    '-f', 'f32le', '-ar', String(sampleRate), '-ac', '1', '-i', 'pipe:0',
    '-c:a', 'libvorbis', '-q:a', String(QUALITY),
    '-f', 'ogg', 'pipe:1',
  ], { input, maxBuffer: 1 << 30 });
  if (r.error) throw new Error(`ffmpeg spawn failed (${FFMPEG}): ${r.error.message}`);
  if (r.status !== 0) throw new Error(`ffmpeg exit ${r.status}: ${r.stderr?.toString().slice(0, 300)}`);
  return new Uint8Array(r.stdout);
}

const srcBytes = fs.readFileSync(inPath);
const bank = core.loadSoundFont(new Uint8Array(srcBytes.buffer, srcBytes.byteOffset, srcBytes.byteLength));
console.log(`[sf2->sf3] ${inPath}: ${bank.presets.length} presets, ${bank.samples.length} samples, q=${QUALITY}`);

let done = 0;
const out = await bank.write({
  compress: true,
  compressionFunction: async (audioData, sampleRate) => encodeOggVorbis(audioData, sampleRate),
  progressFunction: (name, i, total) => {
    done = i;
    if (i % 25 === 0 || i === total) process.stdout.write(`\r  encoding samples ${i}/${total}…   `);
  },
});
process.stdout.write('\n');

const outBytes = out instanceof Uint8Array ? out : new Uint8Array(out);
fs.writeFileSync(outPath, outBytes);
const inMB = (srcBytes.length / 1048576).toFixed(1);
const outMB = (outBytes.length / 1048576).toFixed(1);
console.log(`[sf2->sf3] wrote ${outPath}: ${inMB} MB → ${outMB} MB (${(outBytes.length / srcBytes.length * 100).toFixed(0)}%), ${done} samples encoded`);
