/**
 * pitch-worklet.js — détection de hauteur (YIN) sur le thread audio.
 *
 * MIROIR de `src/fretwise/listening/pitch.py`, qui est l'implémentation de
 * référence : mêmes constantes, mêmes trois étapes dans le même ordre
 * (décimation anti-repliement → YIN sur le signal décimé → raffinement de la
 * période au taux d'origine). Les tests qui épinglent le comportement vivent
 * côté Python (`tests/test_listening_pitch.py`) ; toute évolution algorithmique
 * commence là-bas puis est répercutée ici.
 *
 * Pourquoi un worklet et pas le main thread : l'analyse tourne ~47 fois par
 * seconde sur des fenêtres de 64 ms. Sur le main thread elle entrerait en
 * concurrence avec le rendu de la partition (canvas + SVG), et c'est le rendu
 * qui saccaderait — ou l'analyse qui sauterait des trames, ce qui se voit
 * immédiatement sur une aiguille d'accordeur.
 *
 * Sortie : un message par saut d'analyse,
 *   { type: 'pitch', hz, confidence, rms, peak, voiced, time }
 * où `time` est l'horloge de l'AudioContext au moment de l'analyse (elle
 * servira d'ancre commune avec le PlaybackEngine pour la notation du jeu).
 *
 * Second rôle : la mesure de latence. Sur message `{ type: 'arm' }`, le
 * processeur guette une attaque et répond `{ type: 'onset', time }` avec une
 * précision à l'échantillon — l'analyse de hauteur, elle, n'a qu'une
 * résolution de 21 ms, sans commune mesure avec ce qu'exige un chiffrage de
 * latence.
 */

// ── Constantes miroir de pitch.py ────────────────────────────────────────
const F_MIN_HZ = 60.0;            // laisse passer le B1 (61,7 Hz) d'une 7-cordes
const F_MAX_HZ = 1400.0;          // couvre la 24e case de la mi aiguë (1318,5 Hz)
const YIN_THRESHOLD = 0.15;       // seuil absolu de YIN
const SILENCE_RMS = 0.004;        // plancher de silence
const DECIMATED_RATE_HZ = 12000.0;

// Fenêtre d'analyse : 64 ms ≈ 5 périodes du E2, le minimum pour que YIN tienne
// la corde la plus grave. Saut par défaut : ~21 ms, soit ~47 analyses/seconde.
const FRAME_SEC = 0.064;
const DEFAULT_HOP_SEC = 0.021;

// ── Détection d'attaque (mesure de latence) ──────────────────────────────
// Temps d'observation du bruit de fond avant d'autoriser un déclenchement.
const ONSET_WARMUP_SEC = 0.05;
// Une attaque doit dépasser le plancher de bruit d'un facteur 8 (≈ +18 dB) :
// en dessous, on daterait un froissement de vêtement plutôt que le clic.
const ONSET_RISE_FACTOR = 8;
// Bornes du seuil : plancher absolu contre une pièce anormalement calme,
// plafond contre une pièce si bruyante que le seuil deviendrait inatteignable.
const ONSET_MIN_ABS = 0.02;
const ONSET_MAX_ABS = 0.5;

/** sinc normalisé, convention numpy : sin(πx)/(πx). */
function sinc(x) {
  if (x === 0) return 1.0;
  const px = Math.PI * x;
  return Math.sin(px) / px;
}

/** FIR passe-bas (sinc fenêtré Hamming) pour la décimation — cf. _lowpass_taps. */
function lowpassTaps(decim) {
  const numTaps = 8 * decim + 1;
  const cutoff = 0.45 / decim;
  const centre = (numTaps - 1) / 2;
  const taps = new Float64Array(numTaps);
  let sum = 0;
  for (let n = 0; n < numTaps; n++) {
    const hamming = 0.54 - 0.46 * Math.cos((2 * Math.PI * n) / (numTaps - 1));
    taps[n] = 2 * cutoff * sinc(2 * cutoff * (n - centre)) * hamming;
    sum += taps[n];
  }
  for (let n = 0; n < numTaps; n++) taps[n] /= sum;
  return taps;
}

/** Minimum sous-échantillonné par interpolation parabolique — cf. _parabolic. */
function parabolic(values, index, length) {
  if (index <= 0 || index >= length - 1) return index;
  const a = values[index - 1];
  const b = values[index];
  const c = values[index + 1];
  const denom = a - 2 * b + c;
  if (denom === 0) return index;
  return index + (0.5 * (a - c)) / denom;
}

class PitchProcessor extends AudioWorkletProcessor {
  constructor(options) {
    super();
    const opts = (options && options.processorOptions) || {};
    this._threshold = opts.threshold ?? YIN_THRESHOLD;
    this._minRms = opts.minRms ?? SILENCE_RMS;

    this._frameLen = Math.round(FRAME_SEC * sampleRate);
    this._hop = Math.max(128, Math.round((opts.hopSec ?? DEFAULT_HOP_SEC) * sampleRate));

    // Tampon circulaire : le worklet reçoit 128 échantillons à la fois, mais
    // l'analyse en veut 3072 d'un bloc. On accumule ici et on linéarise au
    // moment de l'analyse (une seule copie, pas de réallocation).
    this._ring = new Float32Array(this._frameLen);
    this._write = 0;
    this._filled = 0;
    this._sinceHop = 0;
    this._peak = 0;

    this._frame = new Float64Array(this._frameLen);
    this._decim = Math.max(1, Math.round(sampleRate / DECIMATED_RATE_HZ));
    this._taps = lowpassTaps(this._decim);
    this._decLen = Math.ceil(this._frameLen / this._decim);
    this._xd = new Float64Array(this._decLen);

    const rateDec = sampleRate / this._decim;
    this._tauMin = Math.max(1, Math.floor(rateDec / F_MAX_HZ));
    this._tauMax = Math.ceil(rateDec / F_MIN_HZ);
    this._yinWindow = this._decLen - this._tauMax;
    this._d = new Float64Array(this._tauMax + 1);
    this._dp = new Float64Array(this._tauMax + 1);
    this._refine = new Float64Array(2 * (this._decim + 1) + 1);

    // État du détecteur d'attaque (inactif tant qu'on n'a pas armé).
    this._armed = false;
    this._onsetFloorSum = 0;
    this._onsetFloorCount = 0;
    this._onsetWarmup = Math.round(ONSET_WARMUP_SEC * sampleRate);

    this._alive = true;
    this.port.onmessage = (ev) => {
      const msg = ev.data || {};
      if (msg.type === 'stop') this._alive = false;
      else if (msg.type === 'arm') {
        this._armed = true;
        this._onsetFloorSum = 0;
        this._onsetFloorCount = 0;
      } else if (msg.type === 'disarm') {
        this._armed = false;
      }
    };
  }

  /**
   * Cherche une attaque dans le quantum courant.
   *
   * Le seuil se calcule sur le bruit de fond mesuré depuis l'armement, et non
   * sur une valeur figée : entre un micro à condensateur dans une pièce calme
   * et une entrée d'interface avec un ampli en veille, le plancher varie de
   * plusieurs dizaines de dB.
   *
   * @param {Float32Array} channel — quantum d'entrée.
   * @returns {number} indice de l'échantillon déclencheur, ou -1.
   */
  _scanOnset(channel) {
    for (let i = 0; i < channel.length; i++) {
      const a = channel[i] < 0 ? -channel[i] : channel[i];
      if (this._onsetFloorCount >= this._onsetWarmup) {
        const mean = this._onsetFloorSum / this._onsetFloorCount;
        const thr = Math.min(ONSET_MAX_ABS, Math.max(ONSET_MIN_ABS, mean * ONSET_RISE_FACTOR));
        if (a > thr) return i;
      }
      this._onsetFloorSum += a;
      this._onsetFloorCount++;
    }
    return -1;
  }

  /** Décime la fenêtre courante — mirror de _decimate (convolution centrée, bords nuls). */
  _decimate() {
    const decim = this._decim;
    if (decim <= 1) {
      this._xd.set(this._frame.subarray(0, this._decLen));
      return;
    }
    const taps = this._taps;
    const numTaps = taps.length;
    const centre = (numTaps - 1) / 2;
    const x = this._frame;
    const n = this._frameLen;
    for (let j = 0; j < this._decLen; j++) {
      const base = j * decim + centre;
      let acc = 0;
      for (let m = 0; m < numTaps; m++) {
        const idx = base - m;
        if (idx >= 0 && idx < n) acc += taps[m] * x[idx];
      }
      this._xd[j] = acc;
    }
  }

  /** d(τ) puis d'(τ) — mirror de _difference_function + _cumulative_mean_normalized. */
  _differenceFunction() {
    const x = this._xd;
    const w = this._yinWindow;
    const d = this._d;
    d[0] = 0;
    for (let tau = 1; tau <= this._tauMax; tau++) {
      let acc = 0;
      for (let j = 0; j < w; j++) {
        const diff = x[j] - x[j + tau];
        acc += diff * diff;
      }
      d[tau] = acc;
    }
    const dp = this._dp;
    dp[0] = 1;
    let running = 0;
    for (let tau = 1; tau <= this._tauMax; tau++) {
      running += d[tau];
      dp[tau] = running > 0 ? (d[tau] * tau) / running : 1;
    }
  }

  /** Premier τ sous le seuil puis descente au minimum local — mirror de _absolute_threshold. */
  _absoluteThreshold(tauFloor) {
    const dp = this._dp;
    let tau = tauFloor;
    while (tau <= this._tauMax) {
      if (dp[tau] < this._threshold) {
        while (tau + 1 <= this._tauMax && dp[tau + 1] < dp[tau]) tau++;
        return { tau, crossed: true };
      }
      tau++;
    }
    let best = tauFloor;
    for (let t = tauFloor; t <= this._tauMax; t++) if (dp[t] < dp[best]) best = t;
    return { tau: best, crossed: false };
  }

  /** Raffinement de la période au taux d'origine — mirror de _refine_period. */
  _refinePeriod(guess) {
    const span = this._decim + 1;
    const centre = Math.round(guess);
    const lo = Math.max(2, centre - span);
    const hi = centre + span;
    const window = this._frameLen - hi;
    if (window < 64) return guess;
    const x = this._frame;
    const vals = this._refine;
    const count = hi - lo + 1;
    let bestIdx = 0;
    for (let i = 0; i < count; i++) {
      const tau = lo + i;
      let acc = 0;
      for (let j = 0; j < window; j++) {
        const diff = x[j] - x[j + tau];
        acc += diff * diff;
      }
      vals[i] = acc;
      if (vals[i] < vals[bestIdx]) bestIdx = i;
    }
    return lo + parabolic(vals, bestIdx, count);
  }

  /** Une analyse complète sur la fenêtre courante — mirror de detect_pitch. */
  _analyze() {
    // Linéarise le tampon circulaire, le plus ancien échantillon d'abord.
    const n = this._frameLen;
    const start = this._write;
    let sumSq = 0;
    for (let i = 0; i < n; i++) {
      const v = this._ring[(start + i) % n];
      this._frame[i] = v;
      sumSq += v * v;
    }
    const rms = Math.sqrt(sumSq / n);
    const peak = this._peak;
    this._peak = 0;
    if (rms < this._minRms) return { hz: 0, confidence: 0, rms, peak, voiced: false };

    this._decimate();
    if (this._tauMax <= this._tauMin || this._yinWindow < 2 * this._tauMin) {
      return { hz: 0, confidence: 0, rms, peak, voiced: false };
    }
    this._differenceFunction();

    // Recherche démarrée sous tauMin : une périodicité plus rapide que f_max
    // signale une fondamentale hors bande, et repartir à tauMin renverrait une
    // sous-harmonique (2 kHz lu 1 kHz). Cf. le même garde-fou dans pitch.py.
    const tauFloor = Math.max(1, Math.floor(this._tauMin / 2));
    const { tau, crossed } = this._absoluteThreshold(tauFloor);
    const confidence = Math.min(1, Math.max(0, 1 - this._dp[tau]));
    if (!crossed || tau < this._tauMin) {
      return { hz: 0, confidence: tau < this._tauMin ? 0 : confidence, rms, peak, voiced: false };
    }

    const period = this._refinePeriod(parabolic(this._dp, tau, this._tauMax + 1) * this._decim);
    if (period <= 0) return { hz: 0, confidence, rms, peak, voiced: false };
    const hz = sampleRate / period;
    if (hz < F_MIN_HZ || hz > F_MAX_HZ) {
      return { hz: 0, confidence, rms, peak, voiced: false };
    }
    return { hz, confidence, rms, peak, voiced: true };
  }

  process(inputs) {
    if (!this._alive) return false;
    const channel = inputs[0] && inputs[0][0];
    // Pas d'entrée sur ce quantum (piste pas encore branchée) : rester vivant,
    // renvoyer false détruirait le processeur pour de bon.
    if (!channel) return true;

    if (this._armed) {
      const hit = this._scanOnset(channel);
      if (hit >= 0) {
        this._armed = false;
        // `currentTime` date le DÉBUT du quantum : ajouter la position exacte
        // de l'échantillon déclencheur donne une datation à l'échantillon près,
        // soit ~0,02 ms, là où le message d'analyse est granulaire à 21 ms.
        this.port.postMessage({ type: 'onset', time: currentTime + hit / sampleRate });
      }
    }

    const n = this._frameLen;
    for (let i = 0; i < channel.length; i++) {
      const v = channel[i];
      this._ring[this._write] = v;
      this._write = (this._write + 1) % n;
      const a = v < 0 ? -v : v;
      if (a > this._peak) this._peak = a;
    }
    this._filled = Math.min(n, this._filled + channel.length);
    this._sinceHop += channel.length;

    if (this._sinceHop >= this._hop && this._filled >= n) {
      this._sinceHop = 0;
      const result = this._analyze();
      result.type = 'pitch';
      result.time = currentTime;
      this.port.postMessage(result);
    }
    return true;
  }
}

registerProcessor('fretwise-pitch', PitchProcessor);
