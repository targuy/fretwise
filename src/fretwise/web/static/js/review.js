/**
 * review.js — "Doigtés à revoir" panel (continuous improvement loop).
 *
 * Lists impossible / suspect / high-cost fingerings (sorted by severity, with
 * filters), lets the user open one, shows up to N alternative fingerings for the
 * measure, and persists their motor-preference choice — which the backend then
 * uses to re-bias future solves.
 */

import { fetchAlternatives, fetchReview, postReviewChoice } from './api.js';

const SEVERITIES = {
  impossible: { label: 'Impossible', cls: 'sev-impossible' },
  suspect: { label: 'Suspect', cls: 'sev-suspect' },
  high_cost: { label: 'Coût élevé', cls: 'sev-high' },
};
const FINGER_COLOR = {
  open: 'var(--f0)', index: 'var(--f1)', middle: 'var(--f2)',
  ring: 'var(--f3)', pinky: 'var(--f4)',
};
const FINGER_SHORT = {
  open: '0', index: '1', middle: '2', ring: '3', pinky: '4',
};

let ctx = null;
let panel = null;
let listEl = null;
let badgeEl = null;
let report = null;
const activeFilters = new Set(['impossible', 'suspect', 'high_cost']);

/**
 * Initialize the review panel.
 * @param {{getFile:Function,getTrackId:Function,isGuitar:Function,reload:Function}} context
 */
export function initReview(context) {
  ctx = context;
  _buildPanel();
  badgeEl = document.getElementById('review-badge');
  const btn = document.getElementById('btn-review');
  if (btn) btn.addEventListener('click', _toggle);
}

/** Reset the panel/badge when no song is loaded (called on file change). */
export function resetReview() {
  report = null;
  _setBadge(0);
  if (panel) panel.style.display = 'none';
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
        <button class="floating-panel-btn" id="review-close" title="Fermer">×</button>
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
  if (panel.style.display === 'none') _open();
  else _close();
}

async function _open() {
  panel.style.display = '';
  await refresh();
}

function _close() {
  panel.style.display = 'none';
}

/** Re-fetch the review list for the current track. */
export async function refresh() {
  if (!ctx || !ctx.getFile || !ctx.getFile()) return;
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
    row.addEventListener('click', () => _openAlternatives(it, row));
    listEl.appendChild(row);
  }
}

async function _openAlternatives(item, row) {
  // Collapse any other open alternatives block.
  panel.querySelectorAll('.review-alts').forEach((el) => el.remove());
  panel.querySelectorAll('.review-item.is-active').forEach((el) =>
    el.classList.remove('is-active'));
  row.classList.add('is-active');

  const box = document.createElement('div');
  box.className = 'review-alts';
  box.innerHTML = '<p class="review-empty">Calcul des alternatives…</p>';
  row.after(box);

  let data;
  try {
    data = await fetchAlternatives(ctx.getFile(), item.measure_index, ctx.getTrackId());
  } catch (e) {
    box.innerHTML = `<p class="review-empty">Erreur : ${e.message}</p>`;
    return;
  }
  box.innerHTML = '';
  if (data.incomplete) {
    const note = document.createElement('p');
    note.className = 'review-altnote';
    note.textContent =
      `Seulement ${data.alternatives.length}/${data.requested} variantes distinctes ` +
      '(voicing contraint par la source).';
    box.appendChild(note);
  }
  for (const alt of data.alternatives) {
    box.appendChild(_altCard(item, alt));
  }
}

function _altCard(item, alt) {
  const card = document.createElement('div');
  card.className = 'review-alt' + (alt.is_current ? ' is-current' : '');
  const tag = alt.is_current ? '<span class="review-alt-cur">actuel</span>' : '';
  const warn = alt.playable ? '' : '<span class="review-alt-warn">⚠ injouable</span>';
  card.innerHTML = `
    <div class="review-alt-head">
      <span class="review-alt-label">${alt.label}</span>
      ${tag}${warn}
      <span class="review-alt-cost">coût ${alt.cost}</span>
    </div>
    <div class="review-alt-tab">${_miniTab(alt.fingerings)}</div>
    <button class="review-alt-pick"${alt.is_current ? ' disabled' : ''}>Choisir</button>
  `;
  const pick = card.querySelector('.review-alt-pick');
  if (pick && !alt.is_current) {
    pick.addEventListener('click', (ev) => {
      ev.stopPropagation();
      _choose(item, alt, pick);
    });
  }
  return card;
}

function _miniTab(fingerings) {
  // Compact chips: string·fret with a finger-coloured dot.
  return fingerings
    .slice()
    .sort((a, b) => (a.onset - b.onset) || (a.string - b.string))
    .map((f) => {
      const color = FINGER_COLOR[f.finger] || 'var(--f0)';
      const fg = FINGER_SHORT[f.finger] || '·';
      return `<span class="review-note" title="corde ${f.string}, frette ${f.fret}, doigt ${f.finger}">` +
        `<span class="review-dot" style="background:${color}">${fg}</span>` +
        `C${f.string}·${f.fret}</span>`;
    })
    .join('');
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
  if (ctx.reload) await ctx.reload();   // re-solve with the new lock/bias
  await refresh();                      // refresh the (now shorter) list
}

function _setBadge(n) {
  if (!badgeEl) return;
  badgeEl.textContent = String(n);
  badgeEl.hidden = !n;
}

function _makeDraggable(el, handle) {
  let sx = 0, sy = 0, ox = 0, oy = 0, dragging = false;
  handle.style.cursor = 'move';
  handle.addEventListener('pointerdown', (e) => {
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
    handle.releasePointerCapture(e.pointerId);
  });
}
