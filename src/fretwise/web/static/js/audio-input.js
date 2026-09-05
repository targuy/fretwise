/**
 * audio-input.js — couche de capture générique de l'entrée guitare.
 *
 * Une seule chaîne pour toutes les sources : micro de la carte son interne,
 * interface audio USB (Valeton GP-180, boîtier d'enregistrement…), micro de
 * webcam. Tout ce que l'OS expose comme entrée arrive ici de la même façon —
 * rien dans ce module ne connaît un modèle d'appareil en particulier.
 *
 * Chaîne : getUserMedia → MediaStreamSource → AudioWorklet (`fretwise-pitch`)
 *          → gain 0 → destination.
 *
 * Le gain nul n'est pas décoratif. D'abord il évite le larsen : sur un micro
 * acoustique, renvoyer l'entrée dans les haut-parleurs suffit à faire hurler la
 * pièce. Ensuite il garantit que le worklet est bien tiré par le graphe — un
 * nœud qui n'atteint jamais la destination n'est pas nécessairement traité.
 *
 * Trois contraintes sont posées à `false` et c'est le cœur du sujet : le
 * navigateur applique par défaut annulation d'écho, réduction de bruit et gain
 * automatique, réglés pour la voix. Sur une guitare, la réduction de bruit
 * mange les fins de notes, et le gain automatique fait dériver le niveau en
 * plein sustain. Le détecteur de hauteur devient inutilisable.
 */

const WORKLET_URL = '/static/js/worklets/pitch-worklet.js';
const DEVICE_KEY = 'fretwise.audioInput.deviceId';

let _ctx = null;
let _stream = null;
let _source = null;
let _worklet = null;
let _sink = null;
let _info = null;
const _frameSubs = new Set();
const _onsetSubs = new Set();
const _deviceSubs = new Set();
let _deviceWatcherInstalled = false;

/** Erreur de capture portant un code stable, pour que l'UI choisisse son message. */
export class AudioInputError extends Error {
  constructor(code, message, cause) {
    super(message);
    this.name = 'AudioInputError';
    this.code = code;   // permission | no-device | insecure | unsupported | failed
    this.cause = cause;
  }
}

/** @returns {boolean} true si le navigateur peut capter une entrée ici. */
export function isSupported() {
  return !!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia && window.AudioWorkletNode);
}

/** Dernier périphérique choisi, mémorisé entre deux sessions. */
export function savedDeviceId() {
  try {
    return localStorage.getItem(DEVICE_KEY) || '';
  } catch (_e) {
    return '';
  }
}

function _rememberDevice(deviceId) {
  try {
    if (deviceId) localStorage.setItem(DEVICE_KEY, deviceId);
    else localStorage.removeItem(DEVICE_KEY);
  } catch (_e) { /* stockage indisponible (navigation privée) — tant pis */ }
}

function _wrapGumError(err) {
  const name = err && err.name;
  if (name === 'NotAllowedError' || name === 'SecurityError') {
    return new AudioInputError('permission', 'Accès au microphone refusé.', err);
  }
  if (name === 'NotFoundError' || name === 'DevicesNotFoundError') {
    return new AudioInputError('no-device', 'Aucune entrée audio détectée.', err);
  }
  if (name === 'NotReadableError' || name === 'TrackStartError') {
    return new AudioInputError('failed', "L'entrée est déjà utilisée par une autre application.", err);
  }
  return new AudioInputError('failed', err && err.message ? err.message : 'Capture impossible.', err);
}

/**
 * Demande la permission micro, sans démarrer d'analyse.
 *
 * À appeler depuis un vrai clic : certains navigateurs refusent getUserMedia
 * hors geste utilisateur. Sert aussi à débloquer les *libellés* de
 * `listInputDevices()` — tant que la permission n'est pas accordée, la liste
 * arrive anonymisée.
 *
 * @returns {Promise<void>}
 * @throws {AudioInputError}
 */
export async function ensurePermission() {
  if (!isSupported()) {
    const why = window.isSecureContext === false
      ? new AudioInputError('insecure', "La capture audio exige une page sécurisée (localhost ou HTTPS).")
      : new AudioInputError('unsupported', "Ce navigateur ne sait pas capter d'entrée audio.");
    throw why;
  }
  try {
    const probe = await navigator.mediaDevices.getUserMedia({ audio: true });
    probe.getTracks().forEach((t) => t.stop());
  } catch (err) {
    throw _wrapGumError(err);
  }
}

/**
 * Liste les entrées audio exposées par l'OS.
 *
 * @returns {Promise<Array<{deviceId: string, label: string, isDefault: boolean}>>}
 *   Les libellés sont vides tant que la permission micro n'a pas été accordée
 *   — c'est une protection du navigateur contre le pistage, pas un bug.
 */
export async function listInputDevices() {
  if (!isSupported()) return [];
  const devices = await navigator.mediaDevices.enumerateDevices();
  return devices
    .filter((d) => d.kind === 'audioinput')
    .map((d) => ({
      deviceId: d.deviceId,
      label: d.label || '',
      isDefault: d.deviceId === 'default' || d.deviceId === '',
    }));
}

/**
 * S'abonne au branchement/débranchement d'une interface audio.
 * @param {() => void} cb
 * @returns {() => void} désabonnement
 */
export function onDeviceChange(cb) {
  _deviceSubs.add(cb);
  if (!_deviceWatcherInstalled && navigator.mediaDevices) {
    navigator.mediaDevices.addEventListener('devicechange', () => {
      _deviceSubs.forEach((fn) => {
        try { fn(); } catch (e) { console.error('[FretWise] devicechange', e); }
      });
    });
    _deviceWatcherInstalled = true;
  }
  return () => _deviceSubs.delete(cb);
}

/**
 * S'abonne aux trames d'analyse du worklet.
 *
 * @param {(frame: {hz: number, confidence: number, rms: number, peak: number,
 *   voiced: boolean, time: number}) => void} cb
 * @returns {() => void} désabonnement
 */
export function onFrame(cb) {
  _frameSubs.add(cb);
  return () => _frameSubs.delete(cb);
}

/**
 * S'abonne aux attaques datées par le worklet (calibration de latence).
 *
 * @param {(onset: {type: 'onset', time: number}) => void} cb — `time` est
 *   l'horloge de l'AudioContext de capture, précise à l'échantillon.
 * @returns {() => void} désabonnement
 */
export function onOnset(cb) {
  _onsetSubs.add(cb);
  return () => _onsetSubs.delete(cb);
}

/**
 * Arme (ou désarme) le détecteur d'attaque.
 *
 * Armer réinitialise l'estimation du bruit de fond : il faut donc laisser
 * ~50 ms d'écoute au calme avant d'émettre le son à dater.
 *
 * @param {boolean} [on=true]
 */
export function armOnset(on = true) {
  if (!_worklet) return;
  _worklet.port.postMessage({ type: on ? 'arm' : 'disarm' });
}

/**
 * AudioContext de la capture.
 *
 * La calibration doit émettre son clic sur **ce** contexte : deux
 * AudioContext ont deux horloges indépendantes, et comparer une date d'émission
 * de l'un à une date de captation de l'autre ne mesurerait rien.
 *
 * @returns {AudioContext|null}
 */
export function captureContext() {
  return _ctx;
}

/** @returns {boolean} true si une capture est en cours. */
export function isCapturing() {
  return !!_worklet;
}

/**
 * Décrit la capture en cours.
 * @returns {{deviceId: string, label: string, sampleRate: number,
 *   channels: number, processing: boolean}|null} null hors capture.
 *   `processing` signale que le navigateur a imposé un traitement voix malgré
 *   les contraintes — l'UI doit alors avertir que la détection sera dégradée.
 */
export function captureInfo() {
  return _info;
}

/**
 * Démarre la capture et l'analyse.
 *
 * @param {object} [opts]
 * @param {string} [opts.deviceId] — entrée à ouvrir ; par défaut, la dernière retenue.
 * @param {number} [opts.hopSec] — période entre deux analyses (défaut ~21 ms).
 * @returns {Promise<{deviceId: string, label: string, sampleRate: number,
 *   channels: number, processing: boolean}>}
 * @throws {AudioInputError}
 */
export async function startCapture(opts = {}) {
  if (!isSupported()) {
    throw new AudioInputError('unsupported', "Ce navigateur ne sait pas capter d'entrée audio.");
  }
  await stopCapture();

  const wanted = opts.deviceId || savedDeviceId();
  const audio = {
    // Réglages voix désactivés : ils détruisent la queue des notes et font
    // dériver le niveau. Voir l'en-tête du module.
    echoCancellation: false,
    noiseSuppression: false,
    autoGainControl: false,
    channelCount: 1,
  };
  if (wanted) audio.deviceId = { exact: wanted };

  try {
    _stream = await navigator.mediaDevices.getUserMedia({ audio });
  } catch (err) {
    // L'interface mémorisée a disparu (débranchée entre deux sessions) :
    // retomber sur l'entrée par défaut plutôt que d'échouer sèchement.
    if (wanted && (err.name === 'OverconstrainedError' || err.name === 'NotFoundError')) {
      _rememberDevice('');
      try {
        _stream = await navigator.mediaDevices.getUserMedia({ audio: { ...audio, deviceId: undefined } });
      } catch (err2) {
        throw _wrapGumError(err2);
      }
    } else {
      throw _wrapGumError(err);
    }
  }

  try {
    _ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: 'interactive' });
    if (_ctx.state === 'suspended') await _ctx.resume();
    await _ctx.audioWorklet.addModule(WORKLET_URL);

    _source = _ctx.createMediaStreamSource(_stream);
    _worklet = new AudioWorkletNode(_ctx, 'fretwise-pitch', {
      numberOfInputs: 1,
      numberOfOutputs: 1,
      outputChannelCount: [1],
      processorOptions: { hopSec: opts.hopSec },
    });
    _worklet.port.onmessage = (ev) => {
      // Deux flux partagent le port : l'analyse de hauteur et la datation
      // d'attaque de la calibration. Le tri se fait ici, pour qu'aucun abonné
      // n'ait à reconnaître un message à la forme de ses champs.
      const subs = ev.data && ev.data.type === 'onset' ? _onsetSubs : _frameSubs;
      subs.forEach((fn) => {
        try { fn(ev.data); } catch (e) { console.error('[FretWise] audio-input', e); }
      });
    };
    _sink = _ctx.createGain();
    _sink.gain.value = 0;   // anti-larsen : jamais de retour vers les haut-parleurs
    _source.connect(_worklet).connect(_sink).connect(_ctx.destination);
  } catch (err) {
    await stopCapture();
    throw new AudioInputError('failed', err && err.message ? err.message : 'Analyse impossible.', err);
  }

  const track = _stream.getAudioTracks()[0];
  const settings = track ? track.getSettings() : {};
  _rememberDevice(settings.deviceId || wanted);
  _info = {
    deviceId: settings.deviceId || wanted || 'default',
    label: (track && track.label) || '',
    sampleRate: _ctx.sampleRate,
    channels: settings.channelCount || 1,
    processing: !!(settings.echoCancellation || settings.noiseSuppression || settings.autoGainControl),
  };
  // Une interface branchée puis retirée en pleine session coupe la piste : sans
  // ce relais, l'UI resterait figée sur la dernière valeur affichée.
  if (track) {
    track.addEventListener('ended', () => {
      stopCapture();
      _deviceSubs.forEach((fn) => {
        try { fn(); } catch (_e) { /* déjà signalé */ }
      });
    });
  }
  return _info;
}

/**
 * Arrête la capture et libère l'entrée pour les autres applications.
 * @returns {Promise<void>}
 */
export async function stopCapture() {
  if (_worklet) {
    try { _worklet.port.postMessage({ type: 'stop' }); } catch (_e) { /* déjà mort */ }
    try { _worklet.disconnect(); } catch (_e) { /* idem */ }
  }
  if (_source) { try { _source.disconnect(); } catch (_e) { /* idem */ } }
  if (_sink) { try { _sink.disconnect(); } catch (_e) { /* idem */ } }
  if (_stream) _stream.getTracks().forEach((t) => t.stop());
  if (_ctx) { try { await _ctx.close(); } catch (_e) { /* idem */ } }
  _worklet = null;
  _source = null;
  _sink = null;
  _stream = null;
  _ctx = null;
  _info = null;
}
