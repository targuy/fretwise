/**
 * tuner.js — page « Accordeur » : accorde la guitare depuis n'importe quelle
 * entrée audio (micro de la carte son, interface USB, webcam).
 *
 * Construit sa propre page et l'accroche à <body>, comme training.js et
 * review.js ; showPage('tuner') ne fait que basculer son affichage.
 *
 * Deux modes de cible :
 *  - « Morceau » : les cordes à vide du morceau ouvert (l'accordage réel de la
 *    piste, drop D et 7-cordes compris — il arrive tel quel de /api/tracks) ;
 *  - « Chromatique » : le demi-ton tempéré le plus proche.
 *
 * Les fonctions de conversion en bas de fichier sont un miroir de
 * `fretwise/listening/pitch.py` (mêmes formules, mêmes noms) : c'est là que le
 * comportement est testé.
 */

import {
  AudioInputError, captureInfo, isSupported, listInputDevices, onDeviceChange,
  onFrame, savedDeviceId, startCapture, stopCapture,
} from './audio-input.js';
import {
  LatencyError, clearLatency, measureRoundTrip, saveLatency, storedLatency,
} from './latency.js';

const A4_KEY = 'fretwise.tuner.a4';
const MODE_KEY = 'fretwise.tuner.mode';

const STANDARD_TUNING_MIDI = [40, 45, 50, 55, 59, 64];
const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

// Une trame moins périodique que ça est du bruit de manche ou une note qui
// meurt : l'aiguille ne doit pas la suivre.
const MIN_CONFIDENCE = 0.85;
// Médiane glissante : rejette les sauts d'octave isolés là où une moyenne les
// étalerait sur toute la fenêtre.
const SMOOTHING_FRAMES = 7;
// Sans trame retenue pendant ce délai, l'affichage repasse au repos.
const HOLD_MS = 600;
// Tolérances d'affichage. 5 cents est le seuil au-delà duquel un intervalle
// commence à battre de façon audible sur une guitare.
const IN_TUNE_CENTS = 5;
const CLOSE_CENTS = 15;
// En mode « Morceau », on ne change de corde cible que si l'écart à la corde
// courante dépasse ça — sinon l'affichage saute de corde en corde pendant
// qu'on remonte une corde très détendue.
const STRING_SWITCH_CENTS = 175;

let ctx = null;
let page = null;
let active = false;
let unsubFrame = null;
let unsubDevices = null;

const state = {
  mode: 'song',        // song | chromatic
  a4: 440,
  history: [],         // dernières fréquences retenues (Hz)
  lastVoicedAt: 0,
  lockedString: null,  // index verrouillé par un clic sur une pastille
  activeString: null,  // corde suivie automatiquement
  level: 0,
  clipped: false,
  calibrating: false,
};

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

// ── Cibles ───────────────────────────────────────────────────────────────

/** Accordage courant : celui du morceau ouvert, sinon EADGBE. */
function _tuning() {
  const fromSong = ctx && typeof ctx.getTuning === 'function' ? ctx.getTuning() : null;
  return (Array.isArray(fromSong) && fromSong.length) ? fromSong : STANDARD_TUNING_MIDI;
}

/** true si l'accordage affiché vient réellement du morceau ouvert. */
function _tuningFromSong() {
  const fromSong = ctx && typeof ctx.getTuning === 'function' ? ctx.getTuning() : null;
  return Array.isArray(fromSong) && fromSong.length > 0;
}

// ── Construction de la page ──────────────────────────────────────────────

function _buildPage() {
  page = document.createElement('div');
  page.id = 'tuner-page';
  page.className = 'page tuner-page';
  page.style.display = 'none';
  page.innerHTML = `
    <div class="tuner-wrap">
      <nav class="settings-nav">
        <button id="tu-back-viewer" class="tx-btn settings-nav-btn" type="button">&larr; Retour au morceau</button>
        <button id="tu-back-files" class="tx-btn settings-nav-btn" type="button">&#8962; Liste des morceaux</button>
      </nav>

      <div class="tuner-header-row">
        <h2 class="settings-title" style="margin:0">Accordeur</h2>
        <div class="tuner-mode-seg" role="tablist">
          <button class="view-seg-btn view-seg-active" data-mode="song" type="button" role="tab">Morceau</button>
          <button class="view-seg-btn" data-mode="chromatic" type="button" role="tab">Chromatique</button>
        </div>
      </div>

      <div class="tuner-source-row">
        <label class="tuner-source-label" for="tu-device">Entrée</label>
        <select id="tu-device" class="tuner-device-select"></select>
        <button id="tu-toggle" class="tx-btn tuner-toggle" type="button">Écouter</button>
        <label class="tuner-a4">
          La<sub>3</sub>
          <input id="tu-a4" type="number" min="415" max="466" step="1" value="440">
          Hz
        </label>
      </div>

      <div class="tuner-latency-row">
        <span class="tuner-latency-label">Latence</span>
        <span id="tu-latency-value" class="tuner-latency-value">non calibrée</span>
        <button id="tu-calibrate" class="tx-btn tuner-latency-btn" type="button">Calibrer</button>
        <button id="tu-latency-clear" class="tx-btn tuner-latency-btn" type="button"
          title="Oublier la mesure de ce périphérique">Oublier</button>
      </div>
      <p class="tuner-latency-help">
        Mesure l'aller-retour audio, indispensable pour noter le jeu en rythme. Ferme la boucle :
        micro devant les haut-parleurs, ou sortie de l'interface renvoyée vers son entrée. Sept
        clics brefs sont émis — monte un peu le volume.
      </p>

      <p id="tu-status" class="tuner-status"></p>

      <div class="tuner-gauge">
        <div class="tuner-readout">
          <span id="tu-note" class="tuner-note">—</span>
          <span id="tu-cents" class="tuner-cents"></span>
        </div>
        <div class="tuner-needle-track">
          <div class="tuner-needle-zone"></div>
          <div class="tuner-needle-centre"></div>
          <div id="tu-needle" class="tuner-needle"></div>
        </div>
        <div class="tuner-scale-row">
          <span>&minus;50</span><span>&minus;25</span><span>juste</span><span>+25</span><span>+50</span>
        </div>
        <p id="tu-freq" class="tuner-freq"></p>
      </div>

      <div id="tu-strings" class="tuner-strings"></div>
      <p id="tu-tuning-src" class="tuner-tuning-src"></p>

      <div class="tuner-level-row">
        <span class="tuner-level-label">Niveau</span>
        <div class="tuner-level-track"><div id="tu-level" class="tuner-level-fill"></div></div>
        <span id="tu-clip" class="tuner-clip">saturation</span>
      </div>

      <p class="tuner-hint">
        Branche l'interface (GP-180, carte son, webcam), choisis-la ci-dessus, joue une corde à vide.
        Clique une pastille pour verrouiller la cible sur cette corde.
      </p>
    </div>
  `;
  document.body.appendChild(page);

  page.querySelector('#tu-back-files').addEventListener('click', () => {
    _stop();
    ctx.goBackToFiles();
  });
  page.querySelector('#tu-back-viewer').addEventListener('click', () => {
    if (!ctx.hasActiveSong()) return;
    _stop();
    ctx.goBackToViewer();
  });
  page.querySelectorAll('.tuner-mode-seg .view-seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setMode(btn.dataset.mode));
  });
  page.querySelector('#tu-toggle').addEventListener('click', _toggleCapture);
  page.querySelector('#tu-device').addEventListener('change', _onDeviceChosen);
  page.querySelector('#tu-calibrate').addEventListener('click', _runCalibration);
  page.querySelector('#tu-latency-clear').addEventListener('click', () => {
    clearLatency(_currentDeviceId());
    _renderLatency();
  });
  const a4Input = page.querySelector('#tu-a4');
  a4Input.value = String(state.a4);
  a4Input.addEventListener('change', () => {
    const v = parseFloat(a4Input.value);
    state.a4 = Number.isFinite(v) && v >= 415 && v <= 466 ? v : 440;
    a4Input.value = String(state.a4);
    try { localStorage.setItem(A4_KEY, String(state.a4)); } catch (_e) { /* privé */ }
    _renderStrings();
  });
}

// ── Périphériques ────────────────────────────────────────────────────────

async function _refreshDevices() {
  const select = page.querySelector('#tu-device');
  if (!select) return;
  let devices = [];
  try {
    devices = await listInputDevices();
  } catch (_e) {
    devices = [];
  }
  const current = captureInfo();
  const chosen = (current && current.deviceId) || select.value || savedDeviceId();
  if (!devices.length) {
    select.innerHTML = '<option value="">Aucune entrée détectée</option>';
    return;
  }
  select.innerHTML = devices.map((d, i) => {
    // Les libellés n'arrivent qu'une fois la permission accordée — avant, le
    // navigateur renvoie une liste anonyme, d'où le repli numéroté.
    const label = d.label || (d.isDefault ? 'Entrée par défaut' : `Entrée ${i + 1}`);
    return `<option value="${esc(d.deviceId)}">${esc(label)}</option>`;
  }).join('');
  if (chosen && devices.some((d) => d.deviceId === chosen)) select.value = chosen;
}

async function _onDeviceChosen() {
  // La latence est propre au périphérique : l'affichage doit suivre le choix,
  // même hors capture.
  _renderLatency();
  if (!isCapturingNow()) return;
  await _start();   // rebranche sur la nouvelle entrée sans quitter la page
}

function isCapturingNow() {
  return !!captureInfo();
}

// ── Capture ──────────────────────────────────────────────────────────────

function _setStatus(text, kind = '') {
  const el = page && page.querySelector('#tu-status');
  if (!el) return;
  el.textContent = text || '';
  el.className = `tuner-status${kind ? ` tuner-status-${kind}` : ''}`;
}

async function _toggleCapture() {
  if (isCapturingNow()) _stop();
  else await _start();
}

async function _start() {
  const select = page.querySelector('#tu-device');
  const toggle = page.querySelector('#tu-toggle');
  if (!isSupported()) {
    _setStatus("Ce navigateur ne sait pas capter d'entrée audio.", 'error');
    return;
  }
  toggle.disabled = true;
  _setStatus('Ouverture de l\'entrée…');
  try {
    const info = await startCapture({ deviceId: select.value || undefined });
    await _refreshDevices();          // les libellés arrivent après la permission
    select.value = info.deviceId;
    _resetReading();
    _renderLatency();
    if (!unsubFrame) unsubFrame = onFrame(_onFrame);
    toggle.textContent = 'Arrêter';
    toggle.classList.add('tuner-toggle-on');
    if (info.processing) {
      _setStatus(
        "Le navigateur impose un traitement voix sur cette entrée (réduction de bruit / gain auto) : "
        + 'la détection sera instable. Essaie une autre entrée ou désactive les effets du pilote.',
        'warn',
      );
    } else {
      _setStatus(`${info.label || 'Entrée'} — ${Math.round(info.sampleRate)} Hz. Joue une corde.`);
    }
  } catch (err) {
    const code = err instanceof AudioInputError ? err.code : 'failed';
    const messages = {
      permission: "Accès au micro refusé. Autorise-le dans la barre d'adresse, puis réessaie.",
      'no-device': 'Aucune entrée audio détectée. Branche une interface ou un micro.',
      insecure: 'La capture exige localhost ou HTTPS.',
      unsupported: "Ce navigateur ne sait pas capter d'entrée audio.",
    };
    _setStatus(messages[code] || `Capture impossible : ${err.message}`, 'error');
  } finally {
    toggle.disabled = false;
  }
}

function _stop() {
  stopCapture();
  if (unsubFrame) { unsubFrame(); unsubFrame = null; }
  _resetReading();
  const toggle = page && page.querySelector('#tu-toggle');
  if (toggle) {
    toggle.textContent = 'Écouter';
    toggle.classList.remove('tuner-toggle-on');
  }
  _setStatus('');
  _renderIdle();
  _renderLatency();
}

function _resetReading() {
  state.history = [];
  state.lastVoicedAt = 0;
  state.activeString = null;
  state.level = 0;
  state.clipped = false;
}

// ── Calibration de latence ───────────────────────────────────────────────

/** Périphérique auquel rattacher une mesure : celui capté, sinon celui choisi. */
function _currentDeviceId() {
  const info = captureInfo();
  if (info && info.deviceId) return info.deviceId;
  const select = page && page.querySelector('#tu-device');
  return (select && select.value) || savedDeviceId() || 'default';
}

function _renderLatency() {
  if (!page) return;
  const value = page.querySelector('#tu-latency-value');
  const calibrate = page.querySelector('#tu-calibrate');
  const clear = page.querySelector('#tu-latency-clear');
  const stored = storedLatency(_currentDeviceId());
  value.textContent = stored == null ? 'non calibrée' : `${(stored * 1000).toFixed(1)} ms`;
  value.classList.toggle('tuner-latency-unset', stored == null);
  clear.style.display = stored == null ? 'none' : '';
  calibrate.disabled = !isCapturingNow() || state.calibrating;
  calibrate.title = isCapturingNow()
    ? "Mesurer l'aller-retour audio de ce périphérique"
    : 'Démarre l\'écoute avant de calibrer';
  clear.disabled = state.calibrating;
}

async function _runCalibration() {
  if (!isCapturingNow() || state.calibrating) return;
  state.calibrating = true;
  // Couper la capture en pleine série fermerait l'AudioContext sous les pieds
  // de la mesure : le bouton d'écoute est neutralisé le temps des sept clics.
  page.querySelector('#tu-toggle').disabled = true;
  _renderLatency();
  _setStatus('Calibration… reste silencieux.');
  try {
    const result = await measureRoundTrip({
      onProgress: (done, total) => _setStatus(`Calibration… essai ${done}/${total}`),
    });
    saveLatency(_currentDeviceId(), result.seconds);
    const ms = (result.seconds * 1000).toFixed(1);
    const jitter = (result.jitterSeconds * 1000).toFixed(1);
    // Au-delà de ~5 ms de gigue la médiane ne résume plus rien de stable :
    // mieux vaut le dire que de laisser croire à une mesure fiable.
    if (result.jitterSeconds > 0.005) {
      _setStatus(
        `Aller-retour ${ms} ms, mais gigue élevée (±${jitter} ms). Mesure peu fiable : `
        + 'éloigne les sources de bruit ou passe par une boucle câblée, puis recommence.',
        'warn',
      );
    } else {
      _setStatus(`Aller-retour mesuré : ${ms} ms (gigue ±${jitter} ms) sur `
        + `${result.samples.length} essais retenus.`);
    }
  } catch (err) {
    const code = err instanceof LatencyError ? err.code : 'failed';
    const messages = {
      'no-capture': "Démarre l'écoute avant de calibrer.",
      timeout: 'Aucun clic capté. Rapproche le micro des haut-parleurs (ou câble la sortie '
        + "vers l'entrée) et monte le volume.",
      unreliable: `${err.message} Monte le volume ou rapproche le micro, puis recommence.`,
    };
    _setStatus(messages[code] || `Calibration impossible : ${err.message}`, 'error');
  } finally {
    state.calibrating = false;
    page.querySelector('#tu-toggle').disabled = false;
    _renderLatency();
  }
}

// ── Boucle d'analyse ─────────────────────────────────────────────────────

function _onFrame(frame) {
  if (!active) return;
  state.level = frame.rms;
  state.clipped = frame.peak >= 0.98;
  if (frame.voiced && frame.confidence >= MIN_CONFIDENCE) {
    state.history.push(frame.hz);
    if (state.history.length > SMOOTHING_FRAMES) state.history.shift();
    state.lastVoicedAt = performance.now();
  } else if (performance.now() - state.lastVoicedAt > HOLD_MS) {
    state.history = [];
  }
  _render();
}

/** Médiane des dernières trames retenues, ou 0 si l'affichage doit être au repos. */
function _smoothedHz() {
  if (!state.history.length) return 0;
  if (performance.now() - state.lastVoicedAt > HOLD_MS) return 0;
  const sorted = state.history.slice().sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)];
}

// ── Rendu ────────────────────────────────────────────────────────────────

function _render() {
  const hz = _smoothedHz();
  _renderLevel();
  if (!hz) {
    _renderIdle();
    return;
  }

  let targetMidi;
  let stringIndex = null;
  if (state.mode === 'song') {
    const tuning = _tuning();
    // Le verrou peut pointer hors de l'accordage courant : on verrouille la 7e
    // corde sur un morceau 7-cordes, puis on ouvre un morceau à 6 cordes.
    if (state.lockedString != null && state.lockedString >= tuning.length) state.lockedString = null;
    stringIndex = state.lockedString != null ? state.lockedString : _autoString(hz, tuning);
    state.activeString = stringIndex;
    targetMidi = tuning[stringIndex];
  } else {
    targetMidi = Math.round(hzToMidi(hz, state.a4));
    state.activeString = null;
  }
  const cents = centsBetween(hz, midiToHz(targetMidi, state.a4));
  _renderReadout(targetMidi, cents, hz);
  _renderStrings(stringIndex, cents);
}

/**
 * Corde suivie en mode automatique.
 *
 * Comparer en cents et non en Hz : à 82 Hz trois hertz sont un demi-ton, à
 * 330 Hz ils sont marginaux, et un tri en Hz colle la mi grave à la corde
 * voisine. La cible courante est conservée tant que l'écart reste plausible,
 * pour qu'une corde très détendue ne fasse pas sauter l'affichage de corde en
 * corde pendant qu'on la remonte.
 */
function _autoString(hz, tuning) {
  const prev = state.activeString;
  if (prev != null && prev < tuning.length) {
    const held = Math.abs(centsBetween(hz, midiToHz(tuning[prev], state.a4)));
    if (held < STRING_SWITCH_CENTS) return prev;
  }
  let best = 0;
  let bestDev = Infinity;
  for (let i = 0; i < tuning.length; i++) {
    const dev = Math.abs(centsBetween(hz, midiToHz(tuning[i], state.a4)));
    if (dev < bestDev) { bestDev = dev; best = i; }
  }
  return best;
}

function _renderIdle() {
  if (!page) return;
  page.querySelector('#tu-note').textContent = '—';
  page.querySelector('#tu-note').className = 'tuner-note';
  page.querySelector('#tu-cents').textContent = '';
  page.querySelector('#tu-freq').textContent = isCapturingNow() ? 'En attente d\'une note…' : '';
  const needle = page.querySelector('#tu-needle');
  needle.style.left = '50%';
  needle.className = 'tuner-needle';
  _renderStrings(state.lockedString, null);
}

function _renderReadout(targetMidi, cents, hz) {
  const noteEl = page.querySelector('#tu-note');
  const centsEl = page.querySelector('#tu-cents');
  const needle = page.querySelector('#tu-needle');
  const quality = _quality(cents);
  noteEl.textContent = noteName(targetMidi);
  noteEl.className = `tuner-note tuner-${quality}`;
  const rounded = Math.round(cents);
  centsEl.textContent = quality === 'ok' && Math.abs(rounded) <= 1
    ? 'juste'
    : `${rounded > 0 ? '+' : ''}${rounded} cents`;
  centsEl.className = `tuner-cents tuner-${quality}`;
  const clamped = Math.max(-50, Math.min(50, cents));
  needle.style.left = `${50 + clamped}%`;
  needle.className = `tuner-needle tuner-needle-${quality}`;
  page.querySelector('#tu-freq').textContent =
    `${hz.toFixed(2)} Hz — cible ${midiToHz(targetMidi, state.a4).toFixed(2)} Hz`;
}

function _quality(cents) {
  const abs = Math.abs(cents);
  if (abs <= IN_TUNE_CENTS) return 'ok';
  if (abs <= CLOSE_CENTS) return 'close';
  return cents > 0 ? 'sharp' : 'flat';
}

/**
 * (Re)construit les pastilles de cordes.
 *
 * Séparé de la mise à jour d'état parce que le rendu tourne ~47 fois par
 * seconde : reconstruire l'innerHTML à cette cadence rebranche six écouteurs
 * par trame, casse le survol et le focus clavier, et fait travailler le layout
 * pour rien. Ici on ne reconstruit que si l'accordage change.
 */
function _buildStrings() {
  const wrap = page && page.querySelector('#tu-strings');
  if (!wrap) return;
  const tuning = _tuning();
  const signature = `${state.mode}:${tuning.join(',')}`;
  if (wrap.dataset.signature === signature) return;
  wrap.dataset.signature = signature;

  if (state.mode !== 'song') {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    const srcHidden = page.querySelector('#tu-tuning-src');
    if (srcHidden) srcHidden.textContent = '';
    return;
  }
  wrap.style.display = '';
  // Numérotation guitaristique : la corde 6 est la plus grave, donc l'index 0.
  wrap.innerHTML = tuning.map((midi, i) => `
    <button type="button" class="tuner-string" data-string="${i}"
      title="Corde ${tuning.length - i} — ${esc(noteName(midi))}">
      <span class="tuner-string-num">${tuning.length - i}</span>
      <span class="tuner-string-note">${esc(noteName(midi))}</span>
    </button>
  `).join('');
  wrap.querySelectorAll('.tuner-string').forEach((btn) => {
    btn.addEventListener('click', () => {
      const idx = parseInt(btn.dataset.string, 10);
      // Re-cliquer la corde verrouillée rend la main au suivi automatique.
      state.lockedString = state.lockedString === idx ? null : idx;
      state.activeString = state.lockedString;
      _render();
    });
  });

  const src = page.querySelector('#tu-tuning-src');
  if (src) {
    src.textContent = _tuningFromSong()
      ? `Accordage de la piste ouverte : ${tuning.map(noteName).join(' ')}`
      : 'Accordage standard EADGBE — ouvre un morceau pour accorder sur le sien.';
  }
}

/** Met à jour l'état visuel des pastilles — classes seulement, pas de DOM neuf. */
function _renderStrings(activeIndex = state.activeString, cents = null) {
  _buildStrings();
  const wrap = page && page.querySelector('#tu-strings');
  if (!wrap || state.mode !== 'song') return;
  const quality = cents != null ? _quality(cents) : '';
  wrap.querySelectorAll('.tuner-string').forEach((btn) => {
    const i = parseInt(btn.dataset.string, 10);
    const isActive = i === activeIndex;
    btn.classList.toggle('tuner-string-active', isActive);
    btn.classList.toggle('tuner-string-locked', state.lockedString === i);
    ['ok', 'close', 'sharp', 'flat'].forEach((q) => {
      btn.classList.toggle(`tuner-${q}`, isActive && quality === q);
    });
  });
}

function _renderLevel() {
  const fill = page && page.querySelector('#tu-level');
  const clip = page && page.querySelector('#tu-clip');
  if (!fill) return;
  // RMS → échelle perceptive : en linéaire, un signal parfaitement exploitable
  // occupe 3 % de la barre et le vu-mètre a l'air mort.
  const db = state.level > 0 ? 20 * Math.log10(state.level) : -100;
  const pct = Math.max(0, Math.min(100, ((db + 60) / 60) * 100));
  fill.style.width = `${pct}%`;
  fill.classList.toggle('tuner-level-weak', pct < 12);
  if (clip) clip.style.visibility = state.clipped ? 'visible' : 'hidden';
}

// ── Modes ────────────────────────────────────────────────────────────────

function _setMode(mode) {
  if (mode === state.mode) return;
  state.mode = mode;
  state.lockedString = null;
  state.activeString = null;
  try { localStorage.setItem(MODE_KEY, mode); } catch (_e) { /* privé */ }
  page.querySelectorAll('.tuner-mode-seg .view-seg-btn').forEach((btn) => {
    btn.classList.toggle('view-seg-active', btn.dataset.mode === mode);
  });
  _render();
}

// ── Cycle de vie ─────────────────────────────────────────────────────────

/**
 * Construit la page et branche les dépendances du reste de l'application.
 *
 * @param {object} context
 * @param {() => void} context.goBackToFiles
 * @param {() => void} context.goBackToViewer
 * @param {() => boolean} context.hasActiveSong
 * @param {() => number[]|null} context.getTuning — hauteurs MIDI des cordes à
 *   vide de la piste ouverte (grave → aiguë), ou null hors morceau.
 */
export function initTuner(context) {
  ctx = context;
  try {
    const savedA4 = parseFloat(localStorage.getItem(A4_KEY));
    if (Number.isFinite(savedA4) && savedA4 >= 415 && savedA4 <= 466) state.a4 = savedA4;
    const savedMode = localStorage.getItem(MODE_KEY);
    if (savedMode === 'song' || savedMode === 'chromatic') state.mode = savedMode;
  } catch (_e) { /* stockage indisponible — valeurs par défaut */ }
  _buildPage();
  page.querySelectorAll('.tuner-mode-seg .view-seg-btn').forEach((btn) => {
    btn.classList.toggle('view-seg-active', btn.dataset.mode === state.mode);
  });
  _renderIdle();
  _renderLatency();
}

/**
 * Active ou désactive la page — appelé par showPage().
 *
 * Quitter la page coupe la capture : garder l'entrée ouverte retiendrait
 * l'interface audio (certains pilotes ASIO sont exclusifs) et laisserait le
 * témoin micro allumé dans l'onglet.
 *
 * @param {boolean} isActive
 */
export function setTunerActive(isActive) {
  active = isActive;
  if (!page) return;
  if (isActive) {
    _refreshDevices();
    if (!unsubDevices) unsubDevices = onDeviceChange(() => _refreshDevices());
    const backViewer = page.querySelector('#tu-back-viewer');
    if (backViewer) backViewer.disabled = !(ctx && ctx.hasActiveSong());
    _renderStrings();
    _renderLatency();
  } else {
    _stop();
    if (unsubDevices) { unsubDevices(); unsubDevices = null; }
  }
}

// ── Conversions — miroir de fretwise/listening/pitch.py ──────────────────

/** Fréquence → hauteur MIDI fractionnaire. */
function hzToMidi(hz, a4 = 440) {
  return 69 + 12 * Math.log2(hz / a4);
}

/** Hauteur MIDI → fréquence. */
function midiToHz(midi, a4 = 440) {
  return a4 * 2 ** ((midi - 69) / 12);
}

/** Nom scientifique d'une hauteur MIDI entière (dièses uniquement). */
function noteName(midi) {
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

/** Écart en cents entre une fréquence mesurée et sa cible. */
function centsBetween(hz, targetHz) {
  return 1200 * Math.log2(hz / targetHz);
}
