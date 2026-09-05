/**
 * latency.js — mesure et mémorise la latence aller-retour de la chaîne audio.
 *
 * Pourquoi c'est un prérequis dur de la notation du jeu : entre l'instant où
 * FretWise décide qu'une note sonne et l'instant où le worklet date la note
 * jouée en réponse, il s'écoule 20 à 40 ms sous Windows en WASAPI partagé. À
 * 180 BPM c'est une double-croche. Sans compensation, un joueur parfaitement en
 * place serait noté systématiquement en retard.
 *
 * **C'est bien l'aller-retour qu'il faut mesurer, pas la seule entrée.** En
 * mode guidé, le joueur se cale sur ce qu'il *entend* : la note prévue à la
 * position `t` atteint ses oreilles à `t + L_sortie`, il attaque donc la corde
 * à `t + L_sortie`, et on la date à `t + L_sortie + L_entrée`. Retrancher
 * l'aller-retour complet de l'horodatage redonne exactement la position
 * voulue — une mesure, une correction.
 *
 * Protocole : un clic bref est émis sur l'AudioContext **de la capture** (deux
 * contextes ont deux horloges, les comparer ne mesurerait rien), le worklet
 * date son arrivée à l'échantillon près, on recommence N fois et on garde la
 * médiane. La médiane, pas la moyenne : un seul essai pollué par un bruit de
 * chaise décalerait une moyenne, alors qu'il glisse en bout de tri sans effet.
 *
 * L'utilisateur doit fermer la boucle physiquement : micro devant les
 * haut-parleurs, ou sortie de l'interface renvoyée vers son entrée.
 */

import { armOnset, captureContext, onOnset } from './audio-input.js';

const STORE_KEY = 'fretwise.listening.latency';

// Délai entre l'armement et le clic : laisse au détecteur le temps d'établir
// son plancher de bruit (50 ms lui suffisent) avec une marge confortable.
const LEAD_SEC = 0.25;
// Repos entre deux essais, le temps que la réverbération du clic retombe.
const SETTLE_SEC = 0.2;
// Bornes de plausibilité d'un aller-retour. Sous 1 ms on a daté le clic
// lui-même par un chemin interne ; au-delà de 500 ms ce n'est plus notre clic.
const MIN_RTT_SEC = 0.001;
const MAX_RTT_SEC = 0.5;
const DEFAULT_TRIALS = 7;
const CLICK_SEC = 0.004;
const CLICK_GAIN = 0.7;

/** Erreur de calibration portant un code stable, pour que l'UI choisisse son message. */
export class LatencyError extends Error {
  constructor(code, message) {
    super(message);
    this.name = 'LatencyError';
    this.code = code;   // no-capture | timeout | unreliable | cancelled
  }
}

// ── Persistance (par périphérique) ───────────────────────────────────────

function _load() {
  try {
    const raw = localStorage.getItem(STORE_KEY);
    const parsed = raw ? JSON.parse(raw) : {};
    return parsed && typeof parsed === 'object' ? parsed : {};
  } catch (_e) {
    return {};
  }
}

/**
 * Latence mémorisée pour un périphérique.
 *
 * Le stockage est par périphérique parce que la latence est une propriété du
 * pilote : une interface USB dédiée et le micro intégré d'une webcam n'ont rien
 * de comparable, et l'utilisateur passe de l'un à l'autre.
 *
 * @param {string} deviceId
 * @returns {number|null} secondes, ou null si jamais calibré.
 */
export function storedLatency(deviceId) {
  const value = _load()[deviceId || 'default'];
  return typeof value === 'number' && Number.isFinite(value) ? value : null;
}

/**
 * Mémorise une latence mesurée.
 * @param {string} deviceId
 * @param {number} seconds
 */
export function saveLatency(deviceId, seconds) {
  const all = _load();
  all[deviceId || 'default'] = seconds;
  try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch (_e) { /* privé */ }
}

/**
 * Oublie la latence d'un périphérique.
 * @param {string} deviceId
 */
export function clearLatency(deviceId) {
  const all = _load();
  delete all[deviceId || 'default'];
  try { localStorage.setItem(STORE_KEY, JSON.stringify(all)); } catch (_e) { /* privé */ }
}

// ── Mesure ───────────────────────────────────────────────────────────────

/**
 * Construit le clic de test : bruit large bande à attaque instantanée.
 *
 * Large bande et non sinusoïdal, parce qu'un haut-parleur, une pièce et un
 * micro déforment chacun la réponse en fréquence : sur une bande étroite, un
 * creux de réponse peut avaler le clic. L'enveloppe décroît en 4 ms — assez
 * court pour que le front d'attaque soit net, assez long pour être capté.
 *
 * @param {BaseAudioContext} ctx
 * @returns {AudioBuffer}
 */
function _clickBuffer(ctx) {
  const n = Math.max(8, Math.round(CLICK_SEC * ctx.sampleRate));
  const buffer = ctx.createBuffer(1, n, ctx.sampleRate);
  const data = buffer.getChannelData(0);
  for (let i = 0; i < n; i++) {
    const env = (1 - i / n) ** 2;
    data[i] = (Math.random() * 2 - 1) * env;
  }
  data[0] = 1;   // front d'attaque franc, pour une datation nette
  return buffer;
}

/**
 * Attend la prochaine attaque postérieure à `after`.
 *
 * @param {number} after — horloge AudioContext du clic émis.
 * @param {number} timeoutMs
 * @returns {Promise<number>} date de l'attaque.
 */
function _awaitOnset(after, timeoutMs) {
  return new Promise((resolve, reject) => {
    let unsub = null;
    const timer = setTimeout(() => {
      if (unsub) unsub();
      reject(new LatencyError('timeout', "Aucun son capté : la boucle n'est pas fermée."));
    }, timeoutMs);
    unsub = onOnset((onset) => {
      // Attaque antérieure au clic : un bruit parasite a déclenché le
      // détecteur. On le réarme et on continue d'attendre le vrai clic.
      if (onset.time < after) {
        armOnset(true);
        return;
      }
      clearTimeout(timer);
      unsub();
      resolve(onset.time);
    });
  });
}

const _sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/** Médiane d'un tableau non vide. */
function _median(values) {
  const sorted = values.slice().sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

/**
 * Mesure la latence aller-retour de la chaîne audio.
 *
 * La capture doit déjà tourner : la mesure emprunte son AudioContext et son
 * worklet, pour que l'émission et la datation partagent une horloge.
 *
 * @param {object} [opts]
 * @param {number} [opts.trials=7] — nombre d'essais.
 * @param {(done: number, total: number, rttSec: number|null) => void} [opts.onProgress]
 * @returns {Promise<{seconds: number, jitterSeconds: number, samples: number[],
 *   outputLatencySec: number, baseLatencySec: number}>}
 *   `jitterSeconds` est l'écart absolu médian : au-delà de ~5 ms, la mesure est
 *   instable et mérite d'être refaite plutôt que d'être crue.
 * @throws {LatencyError}
 */
export async function measureRoundTrip(opts = {}) {
  const ctx = captureContext();
  if (!ctx) {
    throw new LatencyError('no-capture', "La capture doit être démarrée avant de calibrer.");
  }
  const trials = Math.max(3, opts.trials || DEFAULT_TRIALS);
  const onProgress = typeof opts.onProgress === 'function' ? opts.onProgress : () => {};
  const buffer = _clickBuffer(ctx);
  const samples = [];

  try {
    for (let i = 0; i < trials; i++) {
      armOnset(true);
      const emitAt = ctx.currentTime + LEAD_SEC;
      const source = ctx.createBufferSource();
      const gain = ctx.createGain();
      gain.gain.value = CLICK_GAIN;
      source.buffer = buffer;
      source.connect(gain).connect(ctx.destination);
      source.start(emitAt);

      let rtt = null;
      try {
        const heardAt = await _awaitOnset(emitAt, (LEAD_SEC + MAX_RTT_SEC + 0.4) * 1000);
        const candidate = heardAt - emitAt;
        if (candidate >= MIN_RTT_SEC && candidate <= MAX_RTT_SEC) {
          rtt = candidate;
          samples.push(rtt);
        }
      } catch (err) {
        if (!(err instanceof LatencyError)) throw err;
        // Un essai muet ne condamne pas la série : le verdict est rendu sur le
        // nombre d'essais exploitables, une fois la série terminée.
      }
      onProgress(i + 1, trials, rtt);
      try { source.disconnect(); gain.disconnect(); } catch (_e) { /* déjà libéré */ }
      await _sleep(SETTLE_SEC * 1000);
    }
  } finally {
    armOnset(false);
  }

  if (samples.length < Math.ceil(trials / 2)) {
    throw new LatencyError(
      'unreliable',
      `Seulement ${samples.length} essai(s) sur ${trials} exploitable(s).`,
    );
  }
  const seconds = _median(samples);
  const jitterSeconds = _median(samples.map((s) => Math.abs(s - seconds)));
  return {
    seconds,
    jitterSeconds,
    samples,
    outputLatencySec: typeof ctx.outputLatency === 'number' ? ctx.outputLatency : 0,
    baseLatencySec: typeof ctx.baseLatency === 'number' ? ctx.baseLatency : 0,
  };
}
