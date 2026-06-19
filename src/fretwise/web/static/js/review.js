/**
 * review.js — "Doigtés à revoir" panel (continuous improvement loop).
 *
 * Lists impossible / suspect / high-cost fingerings (sorted by severity, with
 * filters), lets the user open one (scrolling the score to that measure), shows
 * up to N alternative fingerings for the measure as a clear diff vs. the current
 * choice, and persists their motor-preference pick — which the backend then uses
 * to re-bias future solves.
 */

import { fetchAlternatives, fetchReview, postReviewChoice } from './api.js';

/** Escape user/server-controlled text before injecting into innerHTML. */
function esc(str) {
  return String(str ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

const SEVERITIES = {
  impossible: { label: 'Impossible', cls: 'sev-impossible' },
  suspect: { label: 'Suspect', cls: 'sev-suspect' },
  high_cost: { label: 'Coût élevé', cls: 'sev-high' },
};
const FINGER_NAME = {
  open: 'à vide', index: 'index', middle: 'majeur', ring: 'annulaire', pinky: 'auriculaire',
};
const FINGER_COLOR = {
  open: 'var(--f0)', index: 'var(--f1)', middle: 'var(--f2)',
  ring: 'var(--f3)', pinky: 'var(--f4)',
};
const FINGER_SHORT = { open: '0', index: '1', middle: '2', ring: '3', pinky: '4' };

let ctx = null;
let panel = null;
let listEl = null;
let badgeEl = null;
let report = null;
const activeFilters = new Set(['impossible', 'suspect', 'high_cost']);

// Hand-visualisation embed for the current measure's alternatives. Tempo +
// tuning come from the /alternatives response; a single shared iframe (the same
// hand_viz.html used by the floating panel) is fed the fingerings of whichever
// option the user picks, in standalone (self-looping) mode.
let _vizTempo = 120;
let _vizTuning = [40, 45, 50, 55, 59, 64];
let _vizFrame = null;

/**
 * Initialize the review panel.
 * @param {{getFile:Function,getTrackId:Function,isGuitar:Function,reload:Function,focusMeasure:Function}} context
 */
export function initReview(context) {
  ctx = context;
  _buildPanel();
  badgeEl = document.getElementById('review-badge');
  const btn = document.getElementById('btn-review');
  if (btn) btn.addEventListener('click', _toggle);
  // Entry point from the audit banner ("Revoir les doigtés →").
  const auditOpen = document.getElementById('audit-review-open');
  if (auditOpen) auditOpen.addEventListener('click', openReview);
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape' && panel && panel.style.display !== 'none') _close();
  });
}

/** Reset the panel/badge when no song is loaded (called on file change). */
export function resetReview() {
  report = null;
  _setBadge(0);
  if (panel) panel.style.display = 'none';
}

/** Open the panel and (re)load the list — usable from the audit banner. */
export async function openReview() {
  if (!panel) return;
  panel.style.display = '';
  await refresh();
}

function _buildPanel() {
  panel = document.createElement('div');
  panel.id = 'review-panel';
  panel.className = 'floating-panel review-panel';
  panel.style.display = 'none';
  panel.innerHTML = `
    <div class="floating-panel-header" id="review-drag">
      <span class="floating-panel-title">Doigtés à revoir</span>
      <div class="floating-panel-actions">
        <button class="floating-panel-btn" id="review-refresh" title="Réanalyser">↻</button>
        <button class="floating-panel-btn" id="review-close" title="Fermer (Échap)">×</button>
      </div>
    </div>
    <div class="review-filters">
      <button class="review-chip sev-impossible is-on" data-sev="impossible">Impossible</button>
      <button class="review-chip sev-suspect is-on" data-sev="suspect">Suspect</button>
      <button class="review-chip sev-high is-on" data-sev="high_cost">Coût élevé</button>
    </div>
    <div class="review-list" id="review-list"></div>
  `;
  document.body.appendChild(panel);
  listEl = panel.querySelector('#review-list');
  panel.querySelector('#review-close').addEventListener('click', _close);
  panel.querySelector('#review-refresh').addEventListener('click', refresh);
  panel.querySelectorAll('.review-chip').forEach((chip) => {
    chip.addEventListener('click', () => {
      const sev = chip.dataset.sev;
      if (activeFilters.has(sev)) { activeFilters.delete(sev); chip.classList.remove('is-on'); }
      else { activeFilters.add(sev); chip.classList.add('is-on'); }
      _renderList();
    });
  });
  _makeDraggable(panel, panel.querySelector('#review-drag'));
}

function _toggle() {
  if (panel.style.display === 'none') openReview();
  else _close();
}

function _close() {
  panel.style.display = 'none';
}

/** Re-fetch the review list for the current track. */
export async function refresh() {
  if (!ctx || !ctx.getFile || !ctx.getFile()) {
    listEl.innerHTML = '<p class="review-empty">Aucun morceau chargé.</p>';
    return;
  }
  if (ctx.isGuitar && !ctx.isGuitar()) {
    listEl.innerHTML = '<p class="review-empty">Piste non-guitare — pas de doigtés.</p>';
    _setBadge(0);
    return;
  }
  listEl.innerHTML = '<p class="review-empty">Analyse en cours…</p>';
  try {
    report = await fetchReview(ctx.getFile(), ctx.getTrackId());
  } catch (e) {
    listEl.innerHTML = `<p class="review-empty">Erreur : ${esc(e.message)}</p>`;
    return;
  }
  if (report && report.available === false) {
    listEl.innerHTML = `<p class="review-empty">${esc(report.reason || 'Indisponible.')}</p>`;
    _setBadge(0);
    return;
  }
  _renderList();
}

function _visibleItems() {
  if (!report || !report.items) return [];
  return report.items.filter((it) => activeFilters.has(it.severity));
}

function _renderList() {
  const items = _visibleItems();
  _setBadge((report && report.items) ? report.items.length : 0);
  if (!items.length) {
    listEl.innerHTML = '<p class="review-empty">Aucun doigté à revoir 🎉</p>';
    return;
  }
  listEl.innerHTML = '';
  for (const it of items) {
    const row = document.createElement('div');
    row.className = 'review-item';
    const sev = SEVERITIES[it.severity] || { label: it.severity, cls: '' };
    row.innerHTML = `
      <div class="review-item-head">
        <span class="review-sev ${sev.cls}">${esc(sev.label)}</span>
        <span class="review-measure">Mesure ${it.measure_index}</span>
      </div>
      <div class="review-reason">${esc(it.reasons[0] || '')}</div>
    `;
    row.addEventListener('click', () => {
      if (ctx.focusMeasure) ctx.focusMeasure(it.measure_index);
      _openAlternatives(it, row);
    });
    listEl.appendChild(row);
  }
}

async function _openAlternatives(item, row) {
  panel.querySelectorAll('.review-alts').forEach((el) => el.remove());
  panel.querySelectorAll('.review-item.is-active').forEach((el) =>
    el.classList.remove('is-active'));
  row.classList.add('is-active');

  const box = document.createElement('div');
  box.className = 'review-alts';
  box.innerHTML = '<p class="review-loading">Calcul des alternatives…</p>';
  row.after(box);

  let data;
  try {
    data = await fetchAlternatives(ctx.getFile(), item.measure_index, ctx.getTrackId());
  } catch (e) {
    box.innerHTML = `<p class="review-loading">Erreur : ${e.message}</p>`;
    return;
  }
  box.innerHTML = '';

  const others = data.alternatives.filter((a) => !a.is_current);
  const current = data.alternatives.find((a) => a.is_current) || null;

  // Tempo + tuning for the hand-viz payloads.
  _vizTempo = typeof data.tempo === 'number' ? data.tempo : 120;
  _vizTuning = Array.isArray(data.tuning) && data.tuning.length
    ? data.tuning : [40, 45, 50, 55, 59, 64];
  _vizFrame = null;  // a fresh iframe is created for this box below

  // Legend so the compact notation reads clearly.
  box.appendChild(_legend());

  // Shared hand visualisation — the compact tab is hard to read, so each option
  // (current + alternatives) can be shown on a 3D fretting hand right here.
  const vizWrap = document.createElement('div');
  vizWrap.className = 'review-handviz';
  _ensureVizFrame(vizWrap);
  box.appendChild(vizWrap);

  if (current) {
    const head = document.createElement('div');
    head.className = 'review-cur-head';
    head.innerHTML = '<span>Doigté actuel</span>';
    const curBtn = _vizButton(current.fingerings);
    head.appendChild(curBtn);
    box.appendChild(head);
    box.appendChild(_tabRow(current.fingerings));
    // Default the hand viz to the current fingering so the panel is immediately
    // readable — even when there are no alternatives (early-returns below).
    curBtn.click();
  }

  if (!others.length) {
    row.classList.add('is-noalt');  // nothing actionable here
    const note = document.createElement('p');
    note.className = 'review-altnote';
    note.textContent =
      'Aucune alternative distincte trouvée : le doigté actuel est déjà le ' +
      'meilleur compromis jouable pour cette mesure.';
    box.appendChild(note);
    return;
  }

  const head = document.createElement('div');
  head.className = 'review-cur-head';
  head.textContent = `Alternatives (${others.length})`;
  box.appendChild(head);
  for (const alt of others) {
    box.appendChild(_altCard(item, alt, current));
  }

  // No current fingering (rare) → default the viz to the first alternative.
  if (!current) {
    const firstViz = box.querySelector('.review-viz-btn');
    if (firstViz) firstViz.click();
  }
}

function _legend() {
  const el = document.createElement('div');
  el.className = 'review-legend';
  el.innerHTML = '<span class="review-legend-lbl">Doigts :</span>' +
    Object.keys(FINGER_NAME).map((f) =>
      `<span class="review-legend-item"><span class="review-dot" style="background:${FINGER_COLOR[f]}">${FINGER_SHORT[f]}</span>${FINGER_NAME[f]}</span>`
    ).join('');
  return el;
}

function _tabRow(fingerings) {
  const wrap = document.createElement('div');
  wrap.className = 'review-alt-tab';
  wrap.innerHTML = fingerings
    .slice()
    .sort((a, b) => (a.onset - b.onset) || (a.string - b.string))
    .map((f) => {
      const color = FINGER_COLOR[f.finger] || 'var(--f0)';
      const fg = FINGER_SHORT[f.finger] || '·';
      return `<span class="review-note" title="corde ${f.string}, case ${f.fret}, ${FINGER_NAME[f.finger] || f.finger}">` +
        `<span class="review-dot" style="background:${color}">${fg}</span>` +
        `<span class="review-note-pos">${f.string}<small>c</small>${f.fret}</span></span>`;
    })
    .join('');
  return wrap;
}

/** Convert a MIDI pitch (e.g. 40) to a note name with octave (e.g. "E2"). */
function _midiToNoteName(midi) {
  const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const octave = Math.floor(midi / 12) - 1;
  return NAMES[((midi % 12) + 12) % 12] + octave;
}

/**
 * Build a standalone (self-looping) hand_viz payload from a fingering set.
 * Onsets are normalised so the measure starts ~0.3 s in, and each note is held
 * long enough to read the pose. Mirrors main.js's _buildHandVizPayload shape.
 */
function _buildAltHandPayload(fingerings) {
  const tempo = _vizTempo || 120;
  const tuning = (_vizTuning && _vizTuning.length) ? _vizTuning : [40, 45, 50, 55, 59, 64];
  const sorted = fingerings.slice()
    .sort((a, b) => (a.onset - b.onset) || (a.string - b.string));
  const minOnset = sorted.length ? Math.min(...sorted.map((f) => f.onset || 0)) : 0;
  const lead = 0.3;
  let maxFret = 0;
  const frames = sorted.map((f) => {
    let finger = String(f.finger || 'open');
    if (finger.startsWith('Finger.')) finger = finger.slice(7).toLowerCase();
    if (typeof f.fret === 'number' && f.fret > maxFret) maxFret = f.fret;
    return {
      note_id: f.note_id,
      onset_sec: ((f.onset || 0) - minOnset) * 60 / tempo + lead,
      duration_sec: 0.7,
      string: f.string,
      fret: f.fret,
      finger,
      hand_position: f.hand_position,
      pitch: f.pitch,
      voice: f.voice_hint || 0,
      planted: {},
    };
  });
  const lastSec = frames.length ? frames[frames.length - 1].onset_sec : 0;
  return {
    meta: {
      title: 'Doigté', artist: '', track: '', tempo,
      synced: false,                       // self-loop in standalone mode
      max_seconds: lastSec + 1.2,
    },
    fretboard: {
      num_frets: Math.max(12, maxFret + 2),
      scale_length_mm: 648,
      tuning: tuning.map(_midiToNoteName),
      capo: 0,
      num_strings: tuning.length,
    },
    frames,
  };
}

/** Create (once per alternatives box) the shared embedded hand-viz iframe. */
function _ensureVizFrame(container) {
  if (_vizFrame && _vizFrame.isConnected) return _vizFrame;
  const frame = document.createElement('iframe');
  frame.className = 'review-handviz-frame';
  frame.title = 'Visualisation de la main';
  frame._ready = false;
  frame._pending = null;
  frame.addEventListener('load', () => {
    frame._ready = true;
    if (frame._pending && frame.contentWindow) {
      frame.contentWindow.postMessage(
        { type: 'fretwise-hand-data', payload: frame._pending }, '*');
      frame._pending = null;
    }
  });
  // Cache-bust so a fresh standalone instance loads each open.
  frame.src = `/static/hand_viz.html?embed=1&v=${Date.now()}`;
  _vizFrame = frame;
  container.appendChild(frame);
  return frame;
}

/** Feed the given fingerings to the shared hand-viz iframe. */
function _showHand(fingerings) {
  if (!_vizFrame || !_vizFrame.isConnected) return;
  const payload = _buildAltHandPayload(fingerings);
  if (_vizFrame._ready && _vizFrame.contentWindow) {
    _vizFrame.contentWindow.postMessage(
      { type: 'fretwise-hand-data', payload }, '*');
  } else {
    _vizFrame._pending = payload;   // posted on iframe load
  }
}

/** A "Voir la main" button that loads *fingerings* into the shared viz. */
function _vizButton(fingerings) {
  const b = document.createElement('button');
  b.type = 'button';
  b.className = 'review-viz-btn';
  b.innerHTML =
    '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" ' +
    'stroke-width="1.7" stroke-linecap="round"><path d="M18 11V6a2 2 0 00-4 0v5"/>' +
    '<path d="M14 10V4a2 2 0 00-4 0v6"/><path d="M10 10.5V6a2 2 0 00-4 0v8"/>' +
    '<path d="M6 14v1a6 6 0 0012 0v-2"/></svg> Voir la main';
  b.addEventListener('click', (ev) => {
    ev.stopPropagation();
    panel.querySelectorAll('.review-viz-btn.is-viz-active')
      .forEach((x) => x.classList.remove('is-viz-active'));
    b.classList.add('is-viz-active');
    _showHand(fingerings);
  });
  return b;
}

function _altCard(item, alt, current) {
  const card = document.createElement('div');
  card.className = 'review-alt';
  const warn = alt.playable ? '' : '<span class="review-alt-warn">⚠ injouable</span>';
  card.innerHTML = `
    <div class="review-alt-head">
      <span class="review-alt-label">${esc(alt.label)}</span>
      ${warn}
      <span class="review-alt-cost">coût ${esc(String(alt.cost))}</span>
    </div>
  `;
  card.appendChild(_tabRow(alt.fingerings));
  const diff = _diffLine(current, alt);
  if (diff) card.appendChild(diff);
  const actions = document.createElement('div');
  actions.className = 'review-alt-actions';
  actions.appendChild(_vizButton(alt.fingerings));
  const pick = document.createElement('button');
  pick.className = 'review-alt-pick';
  pick.textContent = 'Choisir ce doigté';
  pick.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _choose(item, alt, pick);
  });
  actions.appendChild(pick);
  card.appendChild(actions);
  // Selecting (not committing) scrolls the score to the measure to locate it.
  card.addEventListener('click', () => {
    if (ctx.focusMeasure) ctx.focusMeasure(item.measure_index);
  });
  return card;
}

function _diffLine(current, alt) {
  if (!current) return null;
  const curByKey = new Map(
    current.fingerings.map((f) => [`${f.onset}:${f.string}:${f.fret}`, f.finger]),
  );
  const changes = [];
  for (const f of alt.fingerings) {
    const was = curByKey.get(`${f.onset}:${f.string}:${f.fret}`);
    if (was && was !== f.finger) {
      changes.push(`${FINGER_NAME[was] || was} → ${FINGER_NAME[f.finger] || f.finger}`);
    }
  }
  if (!changes.length) return null;
  const el = document.createElement('div');
  el.className = 'review-diff';
  el.textContent = 'Change : ' + changes.slice(0, 4).join(', ') +
    (changes.length > 4 ? '…' : '');
  return el;
}

async function _choose(item, alt, btn) {
  btn.disabled = true;
  btn.textContent = 'Enregistrement…';
  const body = {
    item_id: item.item_id,
    measure_index: item.measure_index,
    onset: item.onset,
    severity: item.severity,
    reasons: item.reasons,
    chosen: alt.fingerings,
    rejected: item.current,
    alternatives_offered: [],
  };
  try {
    await postReviewChoice(ctx.getFile(), ctx.getTrackId(), body);
  } catch (e) {
    btn.disabled = false;
    btn.textContent = 'Réessayer';
    console.error('review choice failed', e);
    return;
  }
  if (ctx.reload) await ctx.reload();
  await refresh();
}

function _setBadge(n) {
  if (!badgeEl) return;
  badgeEl.textContent = String(n);
  badgeEl.hidden = !n;
}

function _makeDraggable(el, handle) {
  let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
  handle.addEventListener('pointerdown', (e) => {
    // Never start a drag from the action buttons (close/refresh) — that
    // swallowed the click and left the panel unable to close.
    if (e.target.closest('.floating-panel-actions')) return;
    dragging = true;
    sx = e.clientX; sy = e.clientY;
    const r = el.getBoundingClientRect();
    ox = r.left; oy = r.top;
    el.style.right = 'auto';
    handle.setPointerCapture(e.pointerId);
  });
  handle.addEventListener('pointermove', (e) => {
    if (!dragging) return;
    el.style.left = `${ox + (e.clientX - sx)}px`;
    el.style.top = `${oy + (e.clientY - sy)}px`;
  });
  handle.addEventListener('pointerup', (e) => {
    dragging = false;
    if (handle.hasPointerCapture(e.pointerId)) handle.releasePointerCapture(e.pointerId);
  });
}
