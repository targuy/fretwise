/**
 * Audit banner — renders per-movement quality verdicts surfaced by
 * /api/solve under the `audit` field. Allows the user to selectively
 * show/hide fingerings on `bad` movements (default: hidden).
 *
 * Public API:
 *   - renderAuditBanner(auditPayload, { onMaskedMeasuresChange })
 *   - resetAuditBanner()
 *   - getMaskedMeasures()  → Set<number>  (1-based measure indices to mask)
 */

const REASON_LABELS = {
  source_bad: 'Erreurs source',
  source_suspect: 'Source suspecte',
  high_cost_density: 'Coût très élevé',
  elevated_cost: 'Coût élevé',
  ml_uncertain: 'Modèle ML incertain',
  ml_borderline: 'ML hésitant',
};

const VERDICT_LABEL_FR = {
  clean: 'OK',
  suspect: 'suspect',
  bad: 'à la limite',
};

// Module-level state — kept simple, reset on each render.
let _maskedMeasures = new Set();   // 1-based measure indices currently masked
let _onMaskChange = null;          // callback invoked after toggle

/**
 * Render the audit banner from the /api/solve `audit` payload.
 *
 * @param {Object|null|undefined} audit  The audit field from the API response.
 * @param {Object} [opts]
 * @param {Function} [opts.onMaskedMeasuresChange] Called after user toggles
 *   any per-movement mask, receives the new Set of masked measure indices.
 */
export function renderAuditBanner(audit, opts = {}) {
  const banner = document.getElementById('audit-banner');
  if (!banner) return;
  _onMaskChange = opts.onMaskedMeasuresChange || null;
  _maskedMeasures = new Set();

  if (!audit || audit.available === false) {
    banner.style.display = 'none';
    return;
  }

  banner.style.display = 'block';
  banner.classList.remove('audit-overall-clean', 'audit-overall-suspect', 'audit-overall-bad');
  banner.classList.add(`audit-overall-${audit.overall}`);

  const dot = document.getElementById('audit-dot');
  if (dot) {
    dot.classList.remove('audit-clean', 'audit-suspect', 'audit-bad');
    dot.classList.add(`audit-${audit.overall}`);
  }

  const summary = document.getElementById('audit-text');
  const movements = Array.isArray(audit.movements) ? audit.movements : [];
  const badCount = movements.filter((m) => m.verdict === 'bad').length;
  const suspectCount = movements.filter((m) => m.verdict === 'suspect').length;
  const mlNote = audit.ml_signal_available ? '' : ' (signal ML indisponible)';

  if (summary) {
    if (audit.overall === 'clean') {
      summary.textContent = `Audit : tous les mouvements OK (${movements.length})${mlNote}`;
    } else {
      summary.textContent =
        `Audit : ${VERDICT_LABEL_FR[audit.overall] || audit.overall} — ` +
        `${badCount} à la limite, ${suspectCount} suspect${suspectCount > 1 ? 's' : ''}, ` +
        `${movements.length - badCount - suspectCount} OK${mlNote}`;
    }
  }

  // Default: mask all bad movements.
  for (const m of movements) {
    if (m.verdict === 'bad') {
      _addRangeToMask(m.span.measure_start, m.span.measure_end);
    }
  }

  const details = document.getElementById('audit-details');
  if (details) {
    details.style.display = 'none';
    details.innerHTML = '';
    const nonClean = movements.filter((m) => m.verdict !== 'clean');
    for (const m of nonClean) {
      details.appendChild(_buildMovementRow(m));
    }
    if (!nonClean.length) {
      const empty = document.createElement('div');
      empty.style.opacity = '0.7';
      empty.textContent = 'Aucun mouvement à signaler.';
      details.appendChild(empty);
    }
  }

  const toggleBtn = document.getElementById('audit-toggle');
  if (toggleBtn && details) {
    toggleBtn.onclick = () => {
      const open = details.style.display !== 'none';
      details.style.display = open ? 'none' : 'grid';
      toggleBtn.setAttribute('aria-expanded', String(!open));
      toggleBtn.textContent = open ? 'Détails' : 'Replier';
    };
  }
}

/** Return the current Set of measure indices that should have fingerings hidden. */
export function getMaskedMeasures() {
  return new Set(_maskedMeasures);
}

/** Clear the banner (e.g. when leaving the tab viewer). */
export function resetAuditBanner() {
  _maskedMeasures = new Set();
  _onMaskChange = null;
  const banner = document.getElementById('audit-banner');
  if (banner) banner.style.display = 'none';
}

// ── internals ──────────────────────────────────────────────────────────

function _buildMovementRow(movement) {
  const row = document.createElement('div');
  row.className = 'audit-mvt-row';

  const dot = document.createElement('span');
  dot.className = `audit-dot audit-${movement.verdict}`;
  row.appendChild(dot);

  const info = document.createElement('div');
  const name = document.createElement('span');
  name.className = 'audit-mvt-name';
  name.textContent = movement.span?.name || `Mouvement ${movement.span?.measure_start ?? '?'}`;
  info.appendChild(name);

  const meta = document.createElement('span');
  meta.className = 'audit-mvt-meta';
  meta.textContent = `mes. ${movement.span?.measure_start}–${movement.span?.measure_end} · ${movement.note_count} notes`;
  info.appendChild(meta);

  if (Array.isArray(movement.reasons) && movement.reasons.length) {
    const reasonsLine = document.createElement('div');
    reasonsLine.className = 'audit-mvt-reasons';
    reasonsLine.textContent = movement.reasons.map((r) => REASON_LABELS[r] || r).join(' · ');
    info.appendChild(reasonsLine);
  }
  row.appendChild(info);

  if (movement.verdict === 'bad' && movement.span) {
    row.appendChild(_buildBadToggle(movement.span));
  } else {
    // Spacer keeps the grid columns aligned visually.
    const spacer = document.createElement('span');
    row.appendChild(spacer);
  }
  return row;
}

function _buildBadToggle(span) {
  const label = document.createElement('label');
  label.className = 'audit-mvt-toggle';
  const cb = document.createElement('input');
  cb.type = 'checkbox';
  cb.checked = false;            // default: fingerings hidden on bad movements
  const txt = document.createElement('span');
  txt.textContent = 'Afficher les doigtés';
  label.appendChild(cb);
  label.appendChild(txt);

  cb.addEventListener('change', () => {
    if (cb.checked) {
      _removeRangeFromMask(span.measure_start, span.measure_end);
    } else {
      _addRangeToMask(span.measure_start, span.measure_end);
    }
    if (typeof _onMaskChange === 'function') _onMaskChange(getMaskedMeasures());
  });
  return label;
}

function _addRangeToMask(start, end) {
  for (let m = start; m <= end; m++) _maskedMeasures.add(m);
}

function _removeRangeFromMask(start, end) {
  for (let m = start; m <= end; m++) _maskedMeasures.delete(m);
}
