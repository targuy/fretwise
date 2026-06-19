import fs from 'node:fs';
import { pathToFileURL } from 'node:url';

const path = process.argv[2];
const core = await import(pathToFileURL('src/fretwise/web/static/js/vendor/spessasynth_core.esm.js').href);
const buf = fs.readFileSync(path);
const bank = core.loadSoundFont(new Uint8Array(buf.buffer, buf.byteOffset, buf.byteLength));

console.log(`${path}: ${bank.presets.length} presets, ${bank.samples.length} samples`);
const compressed = bank.samples.filter((s) => s.isCompressed).length;
console.log(`compressed samples: ${compressed}/${bank.samples.length}`);

// Decode a compressed sample → exercises the Vorbis decoder the browser uses.
const s = bank.samples.find((x) => x.isCompressed) || bank.samples[0];
const audio = s.getAudioData();
console.log(`decode "${s.sampleName}" @${s.sampleRate}Hz → ${audio?.constructor?.name} len=${audio?.length}`);

// GM guitar presets must survive (bank 0).
const want = [[0, 25, 'Steel'], [0, 30, 'Distortion'], [0, 33, 'Bass']];
for (const [bk, pr, label] of want) {
  const p = bank.presets.find((x) => (x.bank ?? 0) === bk && x.program === pr);
  console.log(`  GM ${pr} (${label}): ${p ? (p.presetName || p.name) : '*** MISSING ***'}`);
}
