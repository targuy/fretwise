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
    listEl.innerHTML = `<p class="review-empty">Erreur : ${e.message}</p>`;
    return;
  }
  if (report && report.available === false) {
    listEl.innerHTML = `<p class="review-empty">${report.reason || 'Indisponible.'}</p>`;
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
        <span class="review-sev ${sev.cls}">${sev.label}</span>
        <span class="review-measure">Mesure ${it.measure_index}</span>
      </div>
      <div class="review-reason">${(it.reasons[0] || '').replace(/</g, '&lt;')}</div>
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

  // Legend so the compact notation reads clearly.
  box.appendChild(_legend());

  if (current) {
    const head = document.createElement('div');
    head.className = 'review-cur-head';
    head.textContent = 'Doigté actuel';
    box.appendChild(head);
    box.appendChild(_tabRow(current.fingerings));
  }

  if (!others.length) {
    const note = document.createElement('p');
    note.className = 'review-altnote';
    note.textContent =
      'Aucune alternative jouable distincte : sur ce morceau la corde et la ' +
      'case sont imposées par la source, seul le doigt pourrait changer et le ' +
      'choix actuel est déjà le meilleur ici.';
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

function _altCard(item, alt, current) {
  const card = document.createElement('div');
  card.className = 'review-alt';
  const warn = alt.playable ? '' : '<span class="review-alt-warn">⚠ injouable</span>';
  card.innerHTML = `
    <div class="review-alt-head">
      <span class="review-alt-label">${alt.label}</span>
      ${warn}
      <span class="review-alt-cost">coût ${alt.cost}</span>
    </div>
  `;
  card.appendChild(_tabRow(alt.fingerings));
  const diff = _diffLine(current, alt);
  if (diff) card.appendChild(diff);
  const pick = document.createElement('button');
  pick.className = 'review-alt-pick';
  pick.textContent = 'Choisir ce doigté';
  pick.addEventListener('click', (ev) => {
    ev.stopPropagation();
    _choose(item, alt, pick);
  });
  card.appendChild(pick);
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
