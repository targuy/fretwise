/** Browser-local Web MIDI transport for USB devices attached to operator PC. */

export const MIDI_MESSAGE_DELAY_MS = 200;

export function supportsWebMidi(navigatorObject = globalThis.navigator) {
  return typeof navigatorObject?.requestMIDIAccess === 'function';
}

export async function requestWebMidiAccess(navigatorObject = globalThis.navigator) {
  if (!supportsWebMidi(navigatorObject)) {
    throw new Error('Web MIDI indisponible dans ce navigateur.');
  }
  return await navigatorObject.requestMIDIAccess({ sysex: false });
}

export function connectedMidiOutputs(access) {
  return Array.from(access?.outputs?.values?.() || [])
    .filter((output) => output?.state === 'connected');
}

export function chooseMidiOutput(outputs, requestedId = '') {
  const remembered = outputs.find((output) => output.id === requestedId);
  if (remembered) return remembered;
  const valeton = outputs.find((output) => /valeton|gp-?180/i.test(
    `${output.manufacturer || ''} ${output.name || ''}`,
  ));
  if (valeton) return valeton;
  return outputs.length === 1 ? outputs[0] : null;
}

export async function sendMidiMessages(
  output,
  messages,
  startTimeMs = globalThis.performance.now(),
  delayMs = MIDI_MESSAGE_DELAY_MS,
) {
  if (!output || typeof output.send !== 'function') {
    throw new Error('Sortie MIDI invalide.');
  }
  const validated = messages.map((message) => {
    if (!Array.isArray(message)
        || !message.length
        || message.some((value) => !Number.isInteger(value) || value < 0 || value > 255)) {
      throw new Error('Réponse MIDI invalide reçue du serveur.');
    }
    return new Uint8Array(message);
  });
  if (typeof output.open === 'function') await output.open();
  validated.forEach((message, index) => {
    output.send(message, startTimeMs + index * delayMs);
  });
}
