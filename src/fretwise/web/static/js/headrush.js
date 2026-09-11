/**
 * HeadRush Core UI: author a rig for a song through the user's own LLM, store
 * it, and show it in the Rig panel.
 *
 * FretWise calls no provider. The prompt is generated server-side from the
 * catalog read off the instrument — so every block name and enumeration label in
 * it is real — and the JSON pasted back is validated against that same catalog
 * before it is stored.
 *
 * Pushing a stored rig to the device stays a command-line operation on the
 * machine that owns the instrument: the Core's local API has no authentication,
 * and proxying writes through a web app would open a door onto someone's
 * amplifier. The Rig panel shows that command for rigs not yet on the device.
 */

const $ = (id) => document.getElementById(id);

/** Escape text destined for innerHTML. */
function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Render a block's parameters as "Name value · Name value". */
function paramsText(params) {
  return Object.entries(params || {})
    .map(([k, v]) => {
      const shown = typeof v === 'boolean' ? (v ? 'on' : 'off') : v;
      return `${esc(k)} <b>${esc(shown)}</b>`;
    })
    .join(' · ');
}

/** Save a JSON document through a temporary link. */
function downloadJson(document_, filename) {
  const blob = new Blob([JSON.stringify(document_, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(a.href);
}

/**
 * Fetch the rig stored for a song.
 *
 * @returns {Promise<object>} the /api/devices/headrush/rig payload, or `{error}`.
 */
export async function fetchRigView(artist, title) {
  const params = new URLSearchParams({ artist: artist || '', title: title || '' });
  try {
    const res = await fetch(`/api/devices/headrush/rig?${params}`, { credentials: 'same-origin' });
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      return { error: body?.detail?.detail || body?.detail || `Erreur ${res.status}` };
    }
    return await res.json();
  } catch (err) {
    return { error: `Erreur réseau : ${err}` };
  }
}

/**
 * Render a stored rig inside the Rig panel: one card per slot, in chain order,
 * with the CC that bypasses it, whether it is already on the device, and — when
 * it is not — the command that puts it there.
 */
export function renderRigView(container, payload) {
  if (!container) return;
  if (!payload || payload.error) {
    container.innerHTML = `<p class="hr-empty">${esc(payload?.error || 'Indisponible.')}</p>`;
    return;
  }
  const view = payload.view;
  if (!payload.binding || !view) {
    container.innerHTML =
      '<p class="hr-empty">Aucun rig HeadRush pour ce morceau.</p>' +
      '<p class="settings-hint">Cliquez « ✨ Créer avec l’IA » : FretWise génère le prompt, ' +
      'vous collez la réponse de votre LLM, et le rig validé s’affiche ici.</p>';
    return;
  }
  const prov = payload.provisioned;
  const badge = prov
    ? `<span class="hr-badge ok">Sur l’appareil${
      prov.programChange !== null && prov.programChange !== undefined
        ? ` · PC ${esc(prov.programChange)}` : ''}</span>`
    : '<span class="hr-badge todo">Pas encore sur l’appareil</span>';
  const conf = view.confidence
    ? `<span class="hr-badge">confiance ${esc(view.confidence)}</span>` : '';
  const tone = view.tone?.summary ? `<div class="hr-tone">${esc(view.tone.summary)}</div>` : '';
  const slots = (view.blocks || []).map((b) => (
    `<div class="hr-slot" title="${esc(b.why || '')}">` +
      `<div class="hr-slot-n">Slot ${esc(b.slot)} · CC${esc(b.cc)} · ${esc(b.category)}</div>` +
      `<div class="hr-slot-mod">${esc(b.module)}</div>` +
      `<div class="hr-slot-params">${paramsText(b.params)}</div>` +
    '</div>'
  )).join('');
  const problems = (view.errors || []).length
    ? `<pre class="hr-errors">${esc(view.errors.join('\n'))}</pre>` : '';
  const push = prov ? '' : (
    '<p class="settings-hint">Pour l’envoyer sur le Core : téléchargez le rig dans ' +
    '<code>data/devices/headrush-core/rigs/</code>, puis sur le PC relié à l’appareil :</p>' +
    `<pre class="hr-cmd">${esc(payload.provisionCommand || '')}</pre>`
  );
  container.innerHTML =
    `<div class="hr-head"><span class="hr-rig">${esc(view.rig || '')}</span>${badge}${conf}` +
    '<button type="button" class="tx-btn hr-download-stored">Télécharger le rig</button></div>' +
    `${tone}<div class="hr-slots">${slots}</div>${problems}${push}`;
  container.querySelector('.hr-download-stored')?.addEventListener('click', () => {
    downloadJson(payload.binding, `${payload.key || 'rig'}.json`);
  });
}

/** Render the validated chain inside the authoring panel. */
function chainRows(view) {
  const blocks = Array.isArray(view?.blocks) ? view.blocks : [];
  if (!blocks.length) return '<p class="settings-hint">Aucun bloc.</p>';
  const rows = blocks.map((b) => (
    `<tr><td class="hr-mod">${esc(b.slot)} · ${esc(b.module)}</td>` +
    `<td class="hr-params">${paramsText(b.params)}</td></tr>`
  )).join('');
  return `<table class="hr-chain"><tbody>${rows}</tbody></table>`;
}

/**
 * Wire the HeadRush authoring panel and the device selector.
 *
 * @param {object} options
 * @param {() => {artist: string, title: string}} options.getSong current song.
 * @param {() => void} [options.onSaved] a rig was validated and stored.
 * @param {(device: string) => void} [options.onDeviceChange] selected unit changed.
 */
export function initHeadrush({ getSong, onSaved, onDeviceChange }) {
  const panel = $('headrush-panel');
  const api = {
    open: () => {},
    isActive: () => false,
    refreshDevices: async () => {},
    ready: Promise.resolve(),
    fetchRigView,
    renderRigView,
  };
  if (!panel) return api;

  const promptEl = $('headrush-prompt');
  const pasteEl = $('headrush-paste');
  const statusEl = $('headrush-status');
  const resultEl = $('headrush-result');
  const titleEl = $('headrush-title');
  const guidanceEl = $('headrush-guidance');
  const downloadBtn = $('headrush-download-btn');

  let activeDevice = 'valeton_gp180';
  let lastBinding = null;
  let lastFilename = 'rig.json';

  const setStatus = (message, kind = '') => {
    statusEl.textContent = message;
    statusEl.className = `gear-verify-status${kind ? ' ' + kind : ''}`;
  };

  async function refreshDevices() {
    try {
      const res = await fetch('/api/devices', { credentials: 'same-origin' });
      if (!res.ok) return;
      const data = await res.json();
      activeDevice = data.active || 'valeton_gp180';
      const select = $('set-gear-device');
      if (select) select.value = activeDevice;
      const hr = (data.devices || []).find((d) => d.id === 'headrush_core');
      const state = $('set-headrush-state');
      if (state) {
        state.textContent = hr?.catalogAvailable
          ? 'Catalogue présent : le prompt est généré depuis votre appareil.'
          : 'Aucun catalogue. Lancez scripts/device_catalog_dump.py, appareil allumé.';
      }
    } catch { /* offline: keep the last known state */ }
  }

  async function open() {
    const { artist, title } = getSong() || {};
    if (!artist && !title) {
      setStatus('Ouvrez un morceau d’abord.', 'error');
      return;
    }
    titleEl.textContent = `HeadRush Core — ${[artist, title].filter(Boolean).join(' — ')}`;
    panel.style.display = '';
    resultEl.innerHTML = '';
    // A rig validated for the previous song must not stay downloadable here.
    lastBinding = null;
    if (downloadBtn) downloadBtn.style.display = 'none';
    setStatus('Génération du prompt…');
    const params = new URLSearchParams({ artist: artist || '', title: title || '' });
    if (guidanceEl?.value.trim()) params.set('guidance', guidanceEl.value.trim());
    try {
      const res = await fetch(`/api/devices/headrush/prompt?${params}`, {
        credentials: 'same-origin',
      });
      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        setStatus(body?.detail?.detail || body?.detail || `Erreur ${res.status}`, 'error');
        promptEl.value = '';
        return;
      }
      promptEl.value = await res.text();
      const version = res.headers.get('X-FretWise-App-Version') || '';
      const mode = res.headers.get('X-FretWise-Prompt-Mode') === 'verify'
        ? ' — corrige le rig existant' : '';
      setStatus(`Prompt prêt${version ? ` — firmware ${version}` : ''}${mode}`);
    } catch (err) {
      setStatus(`Erreur réseau : ${err}`, 'error');
    }
  }

  async function validate() {
    const raw = pasteEl.value.trim();
    if (!raw) {
      setStatus('Collez d’abord la réponse du LLM.', 'error');
      return;
    }
    const { artist, title } = getSong() || {};
    setStatus('Validation contre le catalogue de l’appareil…');
    resultEl.innerHTML = '';
    try {
      const res = await fetch('/api/devices/headrush/ingest', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ artist, title, response: raw, save: true }),
      });
      const data = await res.json().catch(() => ({}));
      if (res.status === 422) {
        setStatus('Refusé : non enregistré', 'error');
        resultEl.innerHTML =
          `<pre class="hr-errors">${esc(data.detail)}</pre>` +
          '<p class="settings-hint">Recollez ces lignes à votre LLM : elles nomment le ' +
          'paramètre attendu quand il s’est trompé.</p>';
        return;
      }
      if (!res.ok) {
        setStatus(data?.detail || `Erreur ${res.status}`, 'error');
        return;
      }
      lastBinding = data.binding;
      lastFilename = data.suggestedFilename || 'rig.json';
      setStatus(`Validé et enregistré — ${data.blocks} blocs`, 'ok');
      const warn = (data.warnings || []).length
        ? `<ul class="hr-warn">${data.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`
        : '';
      resultEl.innerHTML =
        `<p class="hr-rig">${esc(data.rig)}</p>${chainRows(data.view)}${warn}` +
        '<p class="settings-hint">Le rig est enregistré : il s’affiche maintenant dans le ' +
        'panneau Rig de ce morceau.</p>';
      if (downloadBtn) downloadBtn.style.display = '';
      onSaved?.();
    } catch (err) {
      setStatus(`Erreur réseau : ${err}`, 'error');
    }
  }

  $('headrush-close')?.addEventListener('click', () => { panel.style.display = 'none'; });
  $('headrush-copy-btn')?.addEventListener('click', async () => {
    if (!promptEl.value) return;
    try {
      await navigator.clipboard.writeText(promptEl.value);
      setStatus('Prompt copié — collez-le dans votre LLM.', 'ok');
    } catch {
      promptEl.select();
      setStatus('Copiez avec Ctrl+C.', '');
    }
  });
  $('headrush-regen-btn')?.addEventListener('click', open);
  $('headrush-validate-btn')?.addEventListener('click', validate);
  downloadBtn?.addEventListener('click', () => {
    if (lastBinding) downloadJson(lastBinding, lastFilename);
  });

  const deviceSelect = $('set-gear-device');
  deviceSelect?.addEventListener('change', async () => {
    const value = deviceSelect.value;
    const state = $('set-headrush-state');
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gear_device: value }),
      });
      if (!res.ok) {
        if (state) state.textContent = `Impossible d’enregistrer le choix (${res.status}).`;
        deviceSelect.value = activeDevice;
        return;
      }
      await refreshDevices();
      onDeviceChange?.(activeDevice);
    } catch (err) {
      if (state) state.textContent = `Erreur réseau : ${err}`;
    }
  });

  // The Rig panel waits on this before choosing which view to draw, so a panel
  // opened right after page load does not flash the GP-180 sheet.
  api.ready = refreshDevices();
  api.open = open;
  api.isActive = () => activeDevice === 'headrush_core';
  api.refreshDevices = refreshDevices;
  return api;
}
