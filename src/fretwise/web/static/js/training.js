/**
 * training.js — "Entraînement" page: scale/chord warm-up navigator.
 *
 * Builds its own page DOM (same pattern as review.js's floating panel) and
 * appends it to <body>; main.js's showPage('training') just toggles its
 * display. Navigation is picker + carousel: a root-note strip, a type list
 * (scales or chord qualities), and prev/next box-position arrows — plus full
 * keyboard control (←/→ position, ↑/↓ type, Shift+←/→ root, Esc back) so a
 * practice session never needs the mouse once a starting point is picked.
 */

import { fetchTrainingChord, fetchTrainingScaleBoxes, fetchTrainingScales } from './api.js';
import {
  FINGER_LABELS, chordDiagramSVG, midiAt, scaleDiagramSVG, scaleRun, staffScaleSVG,
} from './fretboard-diagram.js';
import { playChordStrum, playScaleRun, stopAudioPreview } from './training-audio.js';

function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;').replace(/'/g, '&#39;');
}

const ROOTS = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

const CHORD_QUALITIES = [
  { suffix: '', label: 'Majeur' },
  { suffix: 'm', label: 'Mineur' },
  { suffix: '7', label: '7' },
  { suffix: 'maj7', label: 'Maj7' },
  { suffix: 'm7', label: 'Min7' },
  { suffix: 'dim', label: 'Diminué' },
  { suffix: 'aug', label: 'Augmenté' },
  { suffix: 'sus2', label: 'Sus2' },
  { suffix: 'sus4', label: 'Sus4' },
];

const RECENT_KEY = 'fretwise.training.recent';
const MAX_RECENT = 8;

let ctx = null;
let page = null;
let scaleTypes = [];
let scaleTypesLoaded = false;

const state = {
  mode: 'scale',   // 'scale' | 'chord'
  rootIndex: 4,    // E
  typeIndex: 0,
  boxIndex: 0,
  labels: 'fingers', // 'fingers' | 'notes' — what each dot prints
  diagrams: [],    // scale: list of boxes; chord: single-item list [chordDiagram]
};

/** Wire up the training page. Call once at startup. */
export function initTraining(context) {
  ctx = context;
  _buildPage();
  document.addEventListener('keydown', _onKeydown);
  _loadScaleTypes().then(() => {
    _renderTypeList();
    _refreshDiagrams();
  });
}

function _isActive() {
  return !!page && page.style.display !== 'none';
}

async function _loadScaleTypes() {
  if (scaleTypesLoaded) return;
  try {
    scaleTypes = await fetchTrainingScales();
  } catch (_e) {
    scaleTypes = [];
  }
  scaleTypesLoaded = true;
}

function _currentTypeList() {
  return state.mode === 'scale' ? scaleTypes : CHORD_QUALITIES;
}

function _currentTypeKey(item) {
  return state.mode === 'scale' ? item.name : item.suffix;
}

// ── DOM construction ────────────────────────────────────────────────────

function _buildPage() {
  page = document.createElement('div');
  page.id = 'training-page';
  page.className = 'page training-page';
  page.style.display = 'none';
  page.innerHTML = `
    <div class="training-wrap">
      <nav class="settings-nav">
        <button id="tr-back-viewer" class="tx-btn settings-nav-btn" type="button">&larr; Retour au morceau</button>
        <button id="tr-back-files" class="tx-btn settings-nav-btn" type="button">&#8962; Liste des morceaux</button>
      </nav>
      <div class="training-header-row">
        <h2 class="settings-title" style="margin:0">Entraînement</h2>
        <div class="training-mode-seg" role="tablist">
          <button class="view-seg-btn view-seg-active" data-mode="scale" type="button" role="tab">Gammes</button>
          <button class="view-seg-btn" data-mode="chord" type="button" role="tab">Accords</button>
        </div>
      </div>
      <div class="training-root-strip" id="tr-root-strip"></div>
      <div class="training-body">
        <div class="training-type-col">
          <div class="training-recent" id="tr-recent" style="display:none"></div>
          <div class="training-type-list" id="tr-type-list"></div>
        </div>
        <div class="training-diagram-col">
          <div class="training-diagram-head">
            <h3 id="tr-title" class="training-diagram-title"></h3>
            <div class="training-diagram-head-right">
              <button id="tr-play" class="training-play-btn" type="button"
                title="Écouter cette position" aria-label="Écouter cette position">&#9654;</button>
              <div class="training-label-seg" role="group" aria-label="Contenu des pastilles">
                <button class="view-seg-btn view-seg-active" data-labels="fingers" type="button">Doigts</button>
                <button class="view-seg-btn" data-labels="notes" type="button">Notes</button>
              </div>
            </div>
          </div>
          <div class="training-carousel">
            <button id="tr-box-prev" class="tx-btn training-carousel-btn" type="button"
              title="Position précédente — vers le grave (manche bas)"
              aria-label="Position précédente, vers le grave">&larr; grave</button>
            <span id="tr-box-counter" class="training-box-counter"></span>
            <button id="tr-box-next" class="tx-btn training-carousel-btn" type="button"
              title="Position suivante — la même gamme plus haut sur le manche"
              aria-label="Position suivante, vers l'aigu">aigu &rarr;</button>
          </div>
          <div id="tr-diagram" class="training-diagram"></div>
          <div id="tr-legend" class="training-legend"></div>
          <div id="tr-staff" class="training-staff"></div>
          <p id="tr-howto" class="training-howto"></p>
          <p class="training-kbd-hint">&larr;&rarr; position &nbsp;&middot;&nbsp; &uarr;&darr; type &nbsp;&middot;&nbsp; Maj+&larr;/&rarr; racine &nbsp;&middot;&nbsp; Échap retour</p>
        </div>
      </div>
    </div>
  `;
  document.body.appendChild(page);

  page.querySelector('#tr-back-files').addEventListener('click', () => {
    stopAudioPreview();
    ctx.goBackToFiles();
  });
  page.querySelector('#tr-back-viewer').addEventListener('click', () => {
    if (!ctx.hasActiveSong()) return;
    stopAudioPreview();
    ctx.goBackToViewer();
  });
  page.querySelectorAll('.training-mode-seg .view-seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setMode(btn.dataset.mode));
  });
  page.querySelector('#tr-box-prev').addEventListener('click', () => _stepBox(-1));
  page.querySelector('#tr-box-next').addEventListener('click', () => _stepBox(1));
  page.querySelectorAll('.training-label-seg .view-seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setLabels(btn.dataset.labels));
  });
  page.querySelector('#tr-play').addEventListener('click', _playCurrent);

  _renderRootStrip();
  _renderTypeList();
  _renderRecent();
}

function _renderRootStrip() {
  const strip = document.getElementById('tr-root-strip');
  if (!strip) return;
  strip.innerHTML = ROOTS.map((name, i) => `
    <button type="button" class="training-root-btn${i === state.rootIndex ? ' training-root-active' : ''}"
      data-root-index="${i}">${esc(name)}</button>
  `).join('');
  strip.querySelectorAll('.training-root-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setRoot(parseInt(btn.dataset.rootIndex, 10)));
  });
}

function _renderTypeList() {
  const list = document.getElementById('tr-type-list');
  if (!list) return;
  if (state.mode === 'scale' && !scaleTypesLoaded) {
    list.innerHTML = '<p class="training-empty">Chargement…</p>';
    return;
  }
  const items = _currentTypeList();
  if (!items.length) {
    list.innerHTML = '<p class="training-empty">Indisponible.</p>';
    return;
  }
  list.innerHTML = items.map((item, i) => `
    <button type="button" class="training-type-btn${i === state.typeIndex ? ' training-type-active' : ''}"
      data-type-index="${i}">${esc(item.label)}</button>
  `).join('');
  list.querySelectorAll('.training-type-btn').forEach((btn) => {
    btn.addEventListener('click', () => _setType(parseInt(btn.dataset.typeIndex, 10)));
  });
}

// ── Recent picks (localStorage) ─────────────────────────────────────────

function _loadRecent() {
  try {
    const raw = localStorage.getItem(RECENT_KEY);
    return raw ? JSON.parse(raw) : [];
  } catch (_e) {
    return [];
  }
}

function _saveRecent(list) {
  try {
    localStorage.setItem(RECENT_KEY, JSON.stringify(list.slice(0, MAX_RECENT)));
  } catch (_e) {
    // Storage unavailable (private mode, quota) — recents just won't persist.
  }
}

// Recents record interest, not passing traffic: arrow-key navigation walks
// through many selections per second, and pushing each one would bury the
// entries the user actually settled on. Only a selection held this long lands.
const RECENT_DWELL_MS = 1500;
let _recentTimer = null;

function _scheduleRecent() {
  clearTimeout(_recentTimer);
  _recentTimer = setTimeout(_pushRecent, RECENT_DWELL_MS);
}

function _pushRecent() {
  const items = _currentTypeList();
  const item = items[state.typeIndex];
  if (!item) return;
  const entry = {
    mode: state.mode,
    rootIndex: state.rootIndex,
    typeKey: _currentTypeKey(item),
    label: item.label,
  };
  let list = _loadRecent().filter(
    (e) => !(e.mode === entry.mode && e.rootIndex === entry.rootIndex && e.typeKey === entry.typeKey),
  );
  list.unshift(entry);
  _saveRecent(list);
  _renderRecent();
}

function _renderRecent() {
  const wrap = document.getElementById('tr-recent');
  if (!wrap) return;
  const list = _loadRecent();
  if (!list.length) {
    wrap.style.display = 'none';
    wrap.innerHTML = '';
    return;
  }
  wrap.style.display = '';
  wrap.innerHTML = '<div class="training-recent-label">Récents</div>' + list.map((e, i) => `
    <button type="button" class="training-recent-chip" data-recent-index="${i}">
      ${esc(ROOTS[e.rootIndex] || '?')} ${esc(e.label)}</button>
  `).join('');
  wrap.querySelectorAll('.training-recent-chip').forEach((btn) => {
    btn.addEventListener('click', () => {
      const entry = _loadRecent()[parseInt(btn.dataset.recentIndex, 10)];
      if (entry) _selectRecent(entry);
    });
  });
}

async function _selectRecent(entry) {
  state.mode = entry.mode;
  _syncModeButtons();
  if (state.mode === 'scale') await _loadScaleTypes();
  const items = _currentTypeList();
  const idx = items.findIndex((it) => _currentTypeKey(it) === entry.typeKey);
  state.typeIndex = idx >= 0 ? idx : 0;
  state.rootIndex = entry.rootIndex;
  state.boxIndex = 0;
  _renderRootStrip();
  _renderTypeList();
  await _refreshDiagrams();
}

// ── State transitions ────────────────────────────────────────────────────

function _syncModeButtons() {
  page.querySelectorAll('.training-mode-seg .view-seg-btn').forEach((btn) => {
    btn.classList.toggle('view-seg-active', btn.dataset.mode === state.mode);
  });
}

function _setMode(mode) {
  if (mode === state.mode) return;
  state.mode = mode;
  state.typeIndex = 0;
  state.boxIndex = 0;
  _syncModeButtons();
  _renderTypeList();
  _refreshDiagrams();
}

function _setRoot(i) {
  state.rootIndex = ((i % 12) + 12) % 12;
  state.boxIndex = 0;
  _renderRootStrip();
  _refreshDiagrams();
}

function _setType(i) {
  const items = _currentTypeList();
  if (!items.length) return;
  state.typeIndex = ((i % items.length) + items.length) % items.length;
  state.boxIndex = 0;
  _renderTypeList();
  _refreshDiagrams();
}

function _stepBox(delta) {
  if (state.diagrams.length < 2) return;
  stopAudioPreview();
  const n = state.diagrams.length;
  state.boxIndex = ((state.boxIndex + delta) % n + n) % n;
  _renderDiagram();
}

/** Play the shape currently on screen: an ascending run for a scale box, a
 *  strummed voicing for a chord. Uses the app's active MIDI soundfont bank. */
async function _playCurrent() {
  const box = state.diagrams[state.boxIndex];
  const btn = document.getElementById('tr-play');
  if (!box || !btn) return;
  btn.disabled = true;
  btn.classList.add('is-loading');
  try {
    if (state.mode === 'scale') {
      const pitches = scaleRun(box.notes).map((n) => n.midi);
      await playScaleRun(pitches);
    } else {
      // ChordDiagram.frets is [str1(high e) … str6(low E)]; strummed low → high.
      const pitches = [];
      for (let s = 6; s >= 1; s -= 1) {
        const fret = box.frets[s - 1];
        if (fret >= 0) pitches.push(midiAt(s, fret));
      }
      await playChordStrum(pitches);
    }
  } catch (e) {
    console.warn('[FretWise] training preview failed:', e);
  } finally {
    btn.disabled = false;
    btn.classList.remove('is-loading');
  }
}

function _setLabels(mode) {
  if (mode === state.labels) return;
  state.labels = mode;
  page.querySelectorAll('.training-label-seg .view-seg-btn').forEach((btn) => {
    btn.classList.toggle('view-seg-active', btn.dataset.labels === state.labels);
  });
  _renderDiagram();
}

// ── Diagram fetch + render ───────────────────────────────────────────────

async function _refreshDiagrams() {
  stopAudioPreview();
  const diagramEl = document.getElementById('tr-diagram');
  const items = _currentTypeList();
  const item = items[state.typeIndex];
  if (!item) {
    if (diagramEl) diagramEl.innerHTML = '';
    return;
  }
  const rootName = ROOTS[state.rootIndex];
  if (diagramEl) diagramEl.innerHTML = '<p class="training-loading">Chargement…</p>';
  try {
    if (state.mode === 'scale') {
      const data = await fetchTrainingScaleBoxes(item.name, rootName);
      state.diagrams = data.boxes || [];
    } else {
      state.diagrams = await fetchTrainingChord(`${rootName}${item.suffix}`);
    }
    state.boxIndex = 0;
    _renderDiagram();
    _scheduleRecent();
  } catch (e) {
    state.diagrams = [];
    if (diagramEl) diagramEl.innerHTML = `<p class="training-empty">Indisponible : ${esc(e.message || e)}</p>`;
    const counter = document.getElementById('tr-box-counter');
    if (counter) counter.textContent = '';
  }
}

/** Pretty box label: "box_1"/"position_1" → "Position 1". */
function _boxLabel(name) {
  const m = /(\d+)\s*$/.exec(String(name || ''));
  return m ? `Position ${m[1]}` : String(name || '');
}

function _renderDiagram() {
  const diagramEl = document.getElementById('tr-diagram');
  const counter = document.getElementById('tr-box-counter');
  const prevBtn = document.getElementById('tr-box-prev');
  const nextBtn = document.getElementById('tr-box-next');
  const titleEl = document.getElementById('tr-title');
  const legendEl = document.getElementById('tr-legend');
  const staffEl = document.getElementById('tr-staff');
  const howtoEl = document.getElementById('tr-howto');
  const labelSeg = page.querySelector('.training-label-seg');
  if (!diagramEl) return;

  const box = state.diagrams[state.boxIndex];
  const isScale = state.mode === 'scale';
  // The Doigts/Notes switch only drives the scale renderer; chord diagrams
  // always print the fingering they carry.
  if (labelSeg) labelSeg.style.visibility = isScale ? '' : 'hidden';

  if (!box) {
    diagramEl.innerHTML = '<p class="training-empty">Aucune position disponible.</p>';
    if (counter) counter.textContent = '';
    if (titleEl) titleEl.textContent = '';
    if (legendEl) legendEl.innerHTML = '';
    if (staffEl) staffEl.innerHTML = '';
    if (howtoEl) howtoEl.textContent = '';
    if (prevBtn) prevBtn.disabled = true;
    if (nextBtn) nextBtn.disabled = true;
    return;
  }

  const rootName = ROOTS[state.rootIndex];
  const typeLabel = _currentTypeList()[state.typeIndex]?.label || '';

  diagramEl.innerHTML = isScale
    ? scaleDiagramSVG(box, 2.0, { labels: state.labels })
    : chordDiagramSVG(box, 2.1);
  // chordDiagramSVG was built for the chord-bar popup, which always sits on
  // the cream score paper (--bg-score) — its name/fret-number text is a dark
  // color meant for a light backing. The training panel is dark, so give
  // chord diagrams their own paper card instead of reworking a renderer
  // that's correct everywhere else it's used.
  diagramEl.classList.toggle('training-diagram--paper', !isScale);

  const chordPosLabel = !isScale && box.base_fret > 1
    ? `position barrée, frette ${box.base_fret}`
    : !isScale ? 'position ouverte' : '';

  if (titleEl) {
    titleEl.textContent = isScale
      ? `${rootName} ${typeLabel} — ${_boxLabel(box.name)} · frettes ${box.min_fret}–${box.max_fret}`
      : `${rootName} ${typeLabel} — ${chordPosLabel}`;
  }
  if (legendEl) legendEl.innerHTML = isScale ? _scaleLegendHTML(rootName) : '';
  if (staffEl) {
    staffEl.innerHTML = isScale
      ? `<div class="training-staff-label">La même position, montée note à note</div>`
        + staffScaleSVG(box, 1.5, { labels: state.labels })
      : '';
  }
  if (howtoEl) {
    if (isScale) {
      howtoEl.textContent =
        `Corde du bas = mi grave (6e). Monte corde par corde de gauche à droite, puis redescends. `
        + `Les chiffres sous la grille sont les frettes réelles : place l'index à la frette ${Math.max(box.min_fret, 1)}, `
        + `la main ne bouge pas. Résous toujours sur un ${rootName} (pastille cerclée). `
        + `« aigu → » rejoue la même gamme plus haut sur le manche.`;
    } else {
      const posHint = box.base_fret > 1
        ? `Barre l'index à plat sur la frette ${box.base_fret} — c'est la frette la plus basse du diagramme, indiquée à droite de la grille.`
        : `Position ouverte, tout près du sillet (pas de barré).`;
      const altHint = state.diagrams.length > 1
        ? ` « aigu → » montre ${state.diagrams.length - 1} autre${state.diagrams.length > 2 ? 's' : ''} `
          + `position${state.diagrams.length > 2 ? 's' : ''} pour le même accord, plus haut sur le manche.`
        : '';
      howtoEl.textContent = posHint + altHint;
    }
  }

  const multi = state.diagrams.length > 1;
  if (counter) counter.textContent = multi ? `${state.boxIndex + 1} / ${state.diagrams.length}` : '';
  if (prevBtn) prevBtn.disabled = !multi;
  if (nextBtn) nextBtn.disabled = !multi;
}

function _scaleLegendHTML(rootName) {
  const fingers = [1, 2, 3, 4].map((f) => `
    <span class="training-legend-item">
      <span class="training-legend-dot" style="background:var(--f${f})">${f}</span>
      ${esc(FINGER_LABELS[f])}
    </span>`).join('');
  return `
    ${fingers}
    <span class="training-legend-item">
      <span class="training-legend-dot training-legend-root"></span>
      tonique (${esc(rootName)})
    </span>
    <span class="training-legend-item">
      <span class="training-legend-dot training-legend-open">0</span>
      corde à vide
    </span>`;
}

// ── Keyboard navigation ──────────────────────────────────────────────────

function _onKeydown(e) {
  if (!_isActive()) return;
  const tag = (e.target && e.target.tagName) || '';
  if (tag === 'INPUT' || tag === 'TEXTAREA' || (e.target && e.target.isContentEditable)) return;
  switch (e.key) {
    case 'ArrowLeft':
      e.preventDefault();
      if (e.shiftKey) _setRoot(state.rootIndex - 1); else _stepBox(-1);
      break;
    case 'ArrowRight':
      e.preventDefault();
      if (e.shiftKey) _setRoot(state.rootIndex + 1); else _stepBox(1);
      break;
    case 'ArrowUp':
      e.preventDefault();
      _setType(state.typeIndex - 1);
      break;
    case 'ArrowDown':
      e.preventDefault();
      _setType(state.typeIndex + 1);
      break;
    case 'Escape':
      stopAudioPreview();
      ctx.goBackToFiles();
      break;
    default:
      break;
  }
}
