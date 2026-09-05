/**
 * listening.js — « Écouter mon jeu » : notation en direct contre la partition.
 *
 * Mode guidé : le playback tourne, la position dans le morceau est donc connue,
 * et il n'y a pas de suivi à faire. Le navigateur capte, analyse (worklet YIN)
 * et transmet ; toute la décision musicale — segmentation en notes, appariement,
 * score — vit dans `fretwise.listening` côté Python, où elle est testée. Voir
 * `docs/ecoute.md`.
 *
 * Ce module porte les trois choses que le serveur ne peut pas faire :
 *
 * 1. **Les notes attendues**, tirées de la partition affichée et placées sur la
 *    carte de tempo réelle du playback (et non un tempo moyen, qui dériverait
 *    d'un temps entier sur un morceau à changement de tempo).
 * 2. **La conversion des horloges.** Une trame est datée sur l'horloge de
 *    l'AudioContext de capture ; le serveur veut une position dans le morceau.
 *    Ces deux horloges n'ont aucun rapport, et le serveur n'a aucun moyen de
 *    les relier.
 * 3. **La compensation de latence**, mesurée par périphérique (voir
 *    `latency.js`) — sans elle un joueur en place serait noté en retard.
 */

import { captureContext, captureInfo, isSupported, onFrame, startCapture, stopCapture } from './audio-input.js';
import { storedLatency } from './latency.js';

// Saut d'analyse en mode notation : ~125 trames/s. L'accordeur se contente de
// 21 ms, mais dater un jeu à 21 ms près rendrait indiscernables « en place » et
// « approximatif ».
const HOP_SEC = 0.008;

// Les trames partent par paquets : une socket sollicitée 125 fois par seconde
// coûterait plus en va-et-vient qu'en données.
const BATCH_MS = 100;

const STATUS_LABEL = {
  correct: 'juste',
  wrong_pitch: 'mauvaise note',
  missed: 'manquée',
  extra: 'en trop',
};

let ctx = null;
let panel = null;
let overlay = null;
let socket = null;
let unsubFrame = null;
let batchTimer = null;

const state = {
  running: false,
  latencySec: 0,
  pending: [],        // trames en attente d'envoi
  verdicts: [],
  events: [],         // notes attendues, telles qu'envoyées
  score: null,
  eventCount: 0,
};

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

/** Nom scientifique d'une hauteur MIDI — miroir de fretwise/listening/pitch.py. */
function noteName(midi) {
  if (!Number.isFinite(midi)) return '—';
  return `${NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
}

// ── Notes attendues ──────────────────────────────────────────────────────

/**
 * Extrait de la partition affichée les notes à jouer, datées sur l'horloge du
 * playback.
 *
 * @returns {Array<{id: *, onset: number, duration: number, midi: number, beats: number}>}
 */
function _expectedNotes() {
  const renderer = ctx.getRenderer();
  const playback = ctx.getPlayback();
  const results = (renderer && renderer.data && renderer.data.results) || [];
  const notes = [];
  for (const r of results) {
    if (!Number.isFinite(r.pitch)) continue;
    const beats = r.onset || 0;
    const onset = playback.songSecForOnsetBeats(beats);
    const durBeats = r.duration || 0.25;
    notes.push({
      id: r.note_id,
      onset,
      duration: Math.max(0.05, playback.songSecForOnsetBeats(beats + durBeats) - onset),
      midi: r.pitch,
      beats,
    });
  }
  notes.sort((a, b) => a.onset - b.onset);
  return notes;
}

// ── Conversion d'horloge ─────────────────────────────────────────────────

/**
 * Position d'une trame dans le morceau.
 *
 * On ne compare pas les deux horloges dans l'absolu — elles n'ont pas d'origine
 * commune — mais **l'âge** de la trame, mesuré sur l'horloge de capture, qu'on
 * retranche à la position courante du playback. Reste la latence matérielle,
 * calibrée.
 *
 * @param {{time: number}} frame
 * @returns {number|null} secondes de position, ou null si les horloges manquent.
 */
function _frameSongSec(frame) {
  const capture = captureContext();
  const playback = ctx.getPlayback();
  if (!capture || !playback) return null;
  const age = capture.currentTime - frame.time;
  return playback.getCurrentTimeSec() - age - state.latencySec;
}

// ── Socket ───────────────────────────────────────────────────────────────

function _openSocket(notes) {
  return new Promise((resolve, reject) => {
    const scheme = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${scheme}://${location.host}/ws/listen`);
    ws.onopen = () => {
      ws.send(JSON.stringify({
        type: 'start',
        hop_sec: HOP_SEC,
        notes: notes.map((n) => ({
          id: n.id, onset: n.onset, duration: n.duration, midi: n.midi,
        })),
      }));
    };
    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch (_e) { return; }
      if (msg.type === 'ready') {
        state.eventCount = msg.events;
        resolve(ws);
      } else if (msg.type === 'verdicts') {
        _onVerdicts(msg.verdicts);
      } else if (msg.type === 'score') {
        _onVerdicts(msg.verdicts);
        state.score = msg.score;
        _renderPanel();
      } else if (msg.type === 'error') {
        _setStatus(`Serveur : ${msg.message}`, 'error');
      }
    };
    ws.onerror = () => reject(new Error('connexion au serveur impossible'));
    ws.onclose = () => {
      if (state.running) _setStatus('Connexion interrompue.', 'error');
    };
  });
}

function _flushBatch() {
  if (!socket || socket.readyState !== WebSocket.OPEN || !state.pending.length) return;
  socket.send(JSON.stringify({ type: 'frames', frames: state.pending }));
  state.pending = [];
}

function _onFrame(frame) {
  if (!state.running || frame.type !== 'pitch') return;
  const songSec = _frameSongSec(frame);
  if (songSec == null) return;
  state.pending.push([songSec, frame.hz, frame.confidence, frame.rms, frame.voiced]);
}

// ── Cycle d'une prise ────────────────────────────────────────────────────

/**
 * Démarre une prise : capture, socket, puis playback depuis le début.
 * @returns {Promise<void>}
 */
async function start() {
  if (state.running) return;
  if (!isSupported()) {
    _setStatus("Ce navigateur ne sait pas capter d'entrée audio.", 'error');
    return;
  }
  const notes = _expectedNotes();
  if (!notes.length) {
    _setStatus('Cette piste ne contient aucune note à écouter.', 'error');
    return;
  }
  _setStatus('Ouverture de l\'entrée…');
  try {
    const info = await startCapture({ hopSec: HOP_SEC });
    const stored = storedLatency(info.deviceId);
    state.latencySec = stored == null ? 0 : stored;
    socket = await _openSocket(notes);
  } catch (err) {
    await stopCapture();
    _setStatus(`Démarrage impossible : ${err.message}`, 'error');
    return;
  }

  state.running = true;
  state.verdicts = [];
  state.score = null;
  state.events = notes;
  state.pending = [];
  unsubFrame = onFrame(_onFrame);
  batchTimer = setInterval(_flushBatch, BATCH_MS);
  _clearMarkers();
  _renderPanel();
  _setStatus(
    state.latencySec > 0
      ? `À toi de jouer — latence compensée : ${(state.latencySec * 1000).toFixed(0)} ms.`
      : 'À toi de jouer. Aucune latence calibrée : le rythme sera jugé trop sévèrement '
        + '(calibre depuis l\'accordeur).',
    state.latencySec > 0 ? '' : 'warn',
  );

  const playback = ctx.getPlayback();
  playback.goToMeasure(0);
  playback.play();
  _syncToggle();
}

/**
 * Termine la prise et demande le bilan.
 * @returns {Promise<void>}
 */
async function stop() {
  if (!state.running) return;
  state.running = false;
  if (unsubFrame) { unsubFrame(); unsubFrame = null; }
  clearInterval(batchTimer);
  batchTimer = null;
  _flushBatch();
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'stop' }));
    // Laisser au serveur le temps de renvoyer le bilan avant de fermer.
    setTimeout(() => {
      if (socket) {
        try { socket.send(JSON.stringify({ type: 'close' })); socket.close(); } catch (_e) { /* déjà fermée */ }
        socket = null;
      }
    }, 600);
  }
  await stopCapture();
  ctx.getPlayback().pause();
  _setStatus('');
  _syncToggle();
}

/** Bascule écoute/arrêt — point d'entrée du bouton de barre d'outils. */
export function toggleListening() {
  if (state.running) stop();
  else start();
}

// ── Verdicts ─────────────────────────────────────────────────────────────

function _onVerdicts(verdicts) {
  if (!Array.isArray(verdicts) || !verdicts.length) return;
  for (const verdict of verdicts) {
    state.verdicts.push(verdict);
    if (verdict.status !== 'correct') _placeMarker(verdict);
  }
  _renderPanel();
}

// ── Marquage sur la partition ────────────────────────────────────────────

/**
 * Crée (une fois) la couche de marqueurs, superposée au canevas de partition.
 *
 * Couche DOM plutôt que dessin dans le renderer : la partition se rend en
 * quatre représentations différentes, et greffer un état de notation dans
 * chacune multiplierait par quatre la surface à maintenir pour le même
 * résultat visuel.
 */
function _ensureOverlay() {
  const container = document.getElementById('tab-container');
  const canvas = document.getElementById('tab-canvas');
  if (!container || !canvas) return null;
  if (!overlay) {
    overlay = document.createElement('div');
    overlay.id = 'listen-overlay';
    overlay.className = 'listen-overlay';
    container.appendChild(overlay);
  }
  overlay.style.left = `${canvas.offsetLeft}px`;
  overlay.style.top = `${canvas.offsetTop}px`;
  overlay.style.width = `${canvas.clientWidth}px`;
  overlay.style.height = `${canvas.clientHeight}px`;
  return overlay;
}

function _clearMarkers() {
  if (overlay) overlay.innerHTML = '';
}

function _placeMarker(verdict) {
  const layer = _ensureOverlay();
  const renderer = ctx.getRenderer();
  if (!layer || !renderer || verdict.event_index == null) return;
  const note = state.events[verdict.event_index];
  if (!note) return;
  const line = renderer.getCursorLine(note.beats);
  if (!line) return;
  const mark = document.createElement('span');
  mark.className = `listen-mark listen-mark-${verdict.status}`;
  mark.style.left = `${line.x}px`;
  mark.style.top = `${line.yTop}px`;
  mark.title = _verdictText(verdict);
  layer.appendChild(mark);
}

function _verdictText(verdict) {
  if (verdict.status === 'missed') return `Manquée — ${noteName(verdict.expected_midi)}`;
  if (verdict.status === 'extra') return `En trop — ${noteName(verdict.detected_midi)}`;
  if (verdict.status === 'wrong_pitch') {
    return `Attendu ${noteName(verdict.expected_midi)}, joué ${noteName(verdict.detected_midi)}`;
  }
  const ms = verdict.timing_error_ms;
  return `Juste${ms == null ? '' : ` (${ms > 0 ? '+' : ''}${ms.toFixed(0)} ms)`}`;
}

// ── Panneau ──────────────────────────────────────────────────────────────

function _buildPanel() {
  panel = document.createElement('div');
  panel.id = 'listen-panel';
  panel.className = 'listen-panel';
  panel.hidden = true;
  panel.innerHTML = `
    <div class="listen-panel-head">
      <span class="listen-panel-title">Écoute</span>
      <button id="listen-close" class="tx-btn listen-close" type="button"
        title="Fermer" aria-label="Fermer">&times;</button>
    </div>
    <p id="listen-status" class="listen-status"></p>
    <div id="listen-score" class="listen-score"></div>
    <div id="listen-list" class="listen-list"></div>
  `;
  document.body.appendChild(panel);
  panel.querySelector('#listen-close').addEventListener('click', () => {
    if (state.running) stop();
    panel.hidden = true;
  });
}

function _setStatus(text, kind = '') {
  if (!panel) return;
  panel.hidden = false;
  const el = panel.querySelector('#listen-status');
  el.textContent = text || '';
  el.className = `listen-status${kind ? ` listen-status-${kind}` : ''}`;
}

function _renderPanel() {
  if (!panel) return;
  panel.hidden = false;
  _renderScore();
  _renderList();
}

function _renderScore() {
  const host = panel.querySelector('#listen-score');
  const live = state.verdicts.filter((v) => v.status !== 'extra').length;
  if (!state.score) {
    host.innerHTML = `
      <div class="listen-progress">${live} / ${state.eventCount} événements jugés</div>
    `;
    return;
  }
  const s = state.score;
  const bias = s.timing_bias_ms;
  // Le biais et l'écart-type appellent des conseils opposés : décalé se
  // corrige en anticipant, imprécis se corrige en ralentissant.
  const rhythm = Math.abs(bias) > 25 && Math.abs(bias) > s.timing_rms_ms * 0.7
    ? `${bias > 0 ? 'systématiquement en retard' : 'systématiquement en avance'} de ${Math.abs(bias).toFixed(0)} ms`
    : `dispersion ±${s.timing_rms_ms.toFixed(0)} ms`;
  host.innerHTML = `
    <div class="listen-score-value">${s.score.toFixed(0)}<span>/100</span></div>
    <div class="listen-score-grid">
      <div><b>${s.correct}</b> justes</div>
      <div><b>${s.wrong_pitch}</b> fausses</div>
      <div><b>${s.missed}</b> manquées</div>
      <div><b>${s.extra}</b> en trop</div>
    </div>
    <div class="listen-score-line">Rythme : ${esc(rhythm)}</div>
    <div class="listen-score-line">Justesse : ±${s.mean_abs_cents.toFixed(0)} cents en moyenne</div>
  `;
}

function _renderList() {
  const host = panel.querySelector('#listen-list');
  const faults = state.verdicts.filter((v) => v.status !== 'correct');
  if (!faults.length) {
    host.innerHTML = state.score
      ? '<p class="listen-empty">Aucune erreur relevée.</p>'
      : '';
    return;
  }
  // Les plus récentes en tête : en cours de jeu, c'est ce qui vient de se
  // passer qui intéresse, pas le début du morceau.
  host.innerHTML = faults.slice(-40).reverse().map((v) => {
    const note = v.event_index == null ? null : state.events[v.event_index];
    const at = note ? `${(note.onset).toFixed(1)} s` : '';
    return `<button type="button" class="listen-row listen-row-${v.status}"
      data-sec="${note ? note.onset : ''}">
      <span class="listen-row-at">${esc(at)}</span>
      <span class="listen-row-kind">${esc(STATUS_LABEL[v.status] || v.status)}</span>
      <span class="listen-row-detail">${esc(_verdictText(v))}</span>
    </button>`;
  }).join('');
  host.querySelectorAll('.listen-row').forEach((row) => {
    row.addEventListener('click', () => {
      const sec = parseFloat(row.dataset.sec);
      if (Number.isFinite(sec)) ctx.goToSongSec(sec);
    });
  });
}

function _syncToggle() {
  const btn = document.getElementById('btn-listen');
  if (!btn) return;
  btn.classList.toggle('active', state.running);
  btn.title = state.running ? 'Arrêter l\'écoute' : 'Écouter mon jeu et le noter';
}

// ── Cycle de vie ─────────────────────────────────────────────────────────

/**
 * Branche le module sur le reste de l'application.
 *
 * @param {object} context
 * @param {() => object} context.getRenderer — renderer courant (partition affichée).
 * @param {() => object} context.getPlayback — PlaybackEngine courant.
 * @param {(sec: number) => void} context.goToSongSec — amène le curseur à une
 *   position du morceau, pour que cliquer une erreur y saute.
 */
export function initListening(context) {
  ctx = context;
  _buildPanel();
  _syncToggle();
}

/** Coupe tout — appelé au changement de morceau ou de piste. */
export function resetListening() {
  if (state.running) stop();
  state.verdicts = [];
  state.score = null;
  state.events = [];
  _clearMarkers();
  if (panel) panel.hidden = true;
}

/** @returns {boolean} true si une prise est en cours. */
export function isListening() {
  return state.running;
}

/** Réaligne les marqueurs après un rendu (redimensionnement, changement de vue). */
export function refreshListeningMarkers() {
  if (!overlay || !state.verdicts.length) return;
  _clearMarkers();
  for (const verdict of state.verdicts) {
    if (verdict.status !== 'correct') _placeMarker(verdict);
  }
}

/** @returns {object|null} périphérique de capture en cours, pour diagnostic. */
export function listeningDevice() {
  return captureInfo();
}
