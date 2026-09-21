/**
 * HeadRush Core UI: author a rig manually or through the configured AI API.
 * Prompts and JSON validation share the instrument catalog. API keys remain
 * on the server and are never returned to the browser.
 *
 * Pushing a stored rig to the device goes through a preview and a confirmed
 * apply on the server, which only writes when the installation opted in.
 *
 * `fetchRigView`, `renderRigView` and `setSettingsLabel` are also used by the
 * standalone HeadRush Studio, which serves this file as a shared module.
 */

const $ = (id) => document.getElementById(id);

// Where the device settings live in the host UI, named in error messages.
let settingsLabel = 'Préférences › Pédalier';

/** Name the place the device settings live in the host UI. */
export function setSettingsLabel(label) {
  settingsLabel = label;
}

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

async function postJson(url, body) {
  const res = await fetch(url, {
    method: 'POST',
    credentials: 'same-origin',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  const data = await res.json().catch(() => ({}));
  return { res, data };
}

function detailOf(data, res) {
  const d = data?.detail;
  if (d && typeof d === 'object') return d.detail || d.code || `Erreur ${res.status}`;
  return d || `Erreur ${res.status}`;
}

/** Display name for a configured rig generation mode. */
export function rigAiProviderName(mode) {
  return { anthropic: 'Claude', openai: 'OpenAI', manual: 'Texte manuel' }[mode] || 'Texte manuel';
}

/** Shared preferences for FretWise and standalone Studio; no key is read back. */
export function initRigAiSettings({ container, onChange = () => {} }) {
  let settings = null;
  let saving = false;
  let revision = 0;
  if (container) {
    container.innerHTML = '<h3>Génération IA des rigs HeadRush</h3>' +
      '<label>Mode <select data-ai="mode"><option value="manual">Texte manuel</option>' +
      '<option value="anthropic">Claude API</option><option value="openai">OpenAI API</option>' +
      '</select></label>' +
      '<p class="settings-hint st-muted">Les réglages sont partagés sur ce serveur. ' +
      'Chaque génération API utilise la clé du fournisseur choisi.</p>' +
      ['anthropic', 'openai'].map((provider) => (
        `<fieldset data-provider="${provider}" hidden><legend>${rigAiProviderName(provider)}</legend>` +
        `<label>Modèle <input data-ai="${provider}-model" type="text" autocomplete="off" spellcheck="false"></label>` +
        `<p data-ai="${provider}-status" class="settings-hint st-muted"></p>` +
        `<label data-ai="${provider}-key-field">Nouvelle clé API ` +
        `<input data-ai="${provider}-key" type="password" autocomplete="new-password" spellcheck="false" ` +
        'placeholder="Laisser vide pour conserver la clé"></label>' +
        `<label data-ai="${provider}-clear-field" class="rig-ai-check">` +
        `<input data-ai="${provider}-clear" type="checkbox"> Supprimer la clé enregistrée</label>` +
        '</fieldset>'
      )).join('') +
      '<label data-ai="search-field" class="rig-ai-check" hidden><input data-ai="search" type="checkbox"> ' +
      'Recherche web pour documenter le son (coût fournisseur possible)</label>' +
      '<button data-ai="save" class="tx-btn st-btn st-primary" type="button">Enregistrer le mode IA</button>' +
      '<p data-ai="status" class="settings-hint st-status" role="status" aria-live="polite"></p>';
  }
  const el = (name) => container?.querySelector(`[data-ai="${name}"]`);
  function showFields() {
    if (!container) return;
    const mode = el('mode').value;
    const canEdit = !!settings?.canEdit && !saving;
    el('mode').disabled = !canEdit;
    el('save').hidden = !settings?.canEdit;
    el('save').disabled = !canEdit;
    for (const provider of ['anthropic', 'openai']) {
      const field = container.querySelector(`[data-provider="${provider}"]`);
      field.hidden = mode !== provider;
      field.disabled = mode !== provider || !canEdit;
      const editable = canEdit && settings?.[provider]?.editable !== false;
      el(`${provider}-key-field`).hidden = !editable;
      el(`${provider}-clear-field`).hidden = !editable;
      el(`${provider}-key`).disabled = !editable || mode !== provider;
      el(`${provider}-clear`).disabled = !editable || mode !== provider;
    }
    el('search-field').hidden = mode === 'manual';
    el('search').disabled = mode === 'manual' || !canEdit;
  }
  function render() {
    if (!container || !settings) return;
    el('mode').value = settings.mode || 'manual';
    el('search').checked = !!settings.webSearch;
    for (const provider of ['anthropic', 'openai']) {
      const conf = settings[provider] || {};
      el(`${provider}-model`).value = conf.model || '';
      el(`${provider}-key`).value = '';
      el(`${provider}-clear`).checked = false;
      el(`${provider}-status`).textContent = (conf.configured ? 'Clé configurée.' : 'Clé absente.') +
        (conf.editable === false ? ' Gérée par l’environnement du serveur.' : '');
    }
    showFields();
  }
  async function refresh() {
    const request = ++revision;
    try {
      const res = await fetch('/api/rig-ai/settings', { credentials: 'same-origin' });
      const data = await res.json().catch(() => ({}));
      if (request !== revision) return settings;
      if (!res.ok) throw new Error(detailOf(data, res));
      settings = data;
      render();
      if (el('status')) el('status').textContent = data.canEdit ? '' : 'Réglages réservés aux administrateurs.';
      onChange(settings);
      return settings;
    } catch (err) {
      if (el('status')) el('status').textContent = `Réglages IA indisponibles : ${err.message}`;
      return null;
    }
  }
  el('mode')?.addEventListener('change', () => {
    // Discard an unsaved secret when leaving its provider. Never retain it in memory.
    for (const provider of ['anthropic', 'openai']) {
      el(`${provider}-key`).value = '';
      el(`${provider}-clear`).checked = false;
    }
    showFields();
  });
  el('save')?.addEventListener('click', async () => {
    if (saving || !settings?.canEdit) return;
    const mode = el('mode').value;
    const body = { mode, web_search: el('search').checked };
    if (mode !== 'manual') {
      body[`${mode}_model`] = el(`${mode}-model`).value.trim();
      if (settings[mode]?.editable !== false) {
        const key = el(`${mode}-key`).value.trim();
        const clear = el(`${mode}-clear`).checked;
        if (key && clear) {
          el('status').textContent = 'Choisissez remplacer ou supprimer la clé.';
          return;
        }
        if (key) body[`${mode}_api_key`] = key;
        if (clear) body[`clear_${mode}_key`] = true;
      }
    }
    saving = true;
    ++revision;
    showFields();
    el('status').textContent = 'Enregistrement…';
    try {
      const { res, data } = await postJson('/api/rig-ai/settings', body);
      if (!res.ok) throw new Error(detailOf(data, res));
      const refreshed = await refresh();
      el('status').textContent = refreshed
        ? 'Mode IA enregistré.' : 'Enregistré. Actualisez les préférences pour relire le mode IA.';
    } catch (err) {
      el('status').textContent = `Impossible d’enregistrer : ${err.message}`;
    } finally {
      for (const provider of ['anthropic', 'openai']) el(`${provider}-key`).value = '';
      saving = false;
      showFields();
    }
  });
  showFields();
  return { refresh, get: () => settings };
}

/**
 * Fill the push box with the server's preview, and wire the confirm button.
 *
 * Nothing is written until "Confirmer" — and the apply call carries the plan
 * token of this preview, so a rig re-validated meanwhile is refused, not pushed.
 */
function renderPushBox(box, payload, p, onChanged) {
  const dev = p.device || {};
  const blockers = [];
  if (!dev.reachable) {
    blockers.push(`Appareil injoignable à ${p.host} — ${dev.detail || ''} ` +
      `Vérifiez qu’il est allumé et son adresse dans ${settingsLabel}.`);
  } else {
    if (!dev.firmwareMatches) {
      blockers.push(`Firmware ${dev.appVersion} différent du catalogue : régénérer le catalogue.`);
    }
    if (dev.saveDialogOpen) {
      blockers.push('Un dialogue de sauvegarde est ouvert sur l’appareil : Save ou Discard d’abord.');
    }
    if (p.mode === 'create' && !dev.sandboxPresent) {
      blockers.push(`Aucun rig « ${p.sandbox} » sur l’appareil : créez-en un vide à la main ` +
        '(il sert de modèle et n’est jamais modifié).');
    }
  }
  if (!p.applicable) blockers.push(...(p.errors || []));
  if (!p.writeEnabled) {
    blockers.push(`Écriture désactivée : cochez « Autoriser l’écriture » dans ${settingsLabel}.`);
  }
  const notes = [];
  if (dev.reachable && dev.loadedDirty) {
    notes.push(`Le rig chargé (« ${dev.loadedRig} ») a des modifications non sauvegardées : ` +
      'le chargement risque d’être bloqué par le dialogue de sauvegarde.');
  }
  const steps = p.steps || [];
  const what = {
    create: `Création : charge « ${p.sandbox} », écrit ${steps.length} étapes, relit tout, ` +
      `puis « Save As » sous « ${p.rig} ».` +
      (dev.reachable ? ` Le rig en cours (« ${dev.loadedRig} ») est quitté sans être modifié.` : ''),
    update: `Mise à jour du rig existant « ${p.known?.rigName || p.rig} » : chargement, ` +
      `${steps.length} étapes, relecture, Save.`,
    unchanged: 'Ce rig est déjà à jour sur l’appareil : seul un Program Change différent sera écrit.',
    program_change: 'Rig inchangé : seul le Program Change sera écrit.',
  }[p.mode] || p.mode;
  const deviceLine = dev.reachable
    ? `${esc(dev.deviceName)} à ${esc(p.host)} · firmware ${esc(dev.appVersion)} · ` +
      `rig chargé : ${esc(dev.loadedRig)}`
    : '';
  box.innerHTML =
    `<div class="hr-push-title">Envoyer « ${esc(p.rig)} » sur le HeadRush</div>` +
    (deviceLine ? `<div class="hr-push-dev">${deviceLine}</div>` : '') +
    `<p class="hr-push-what">${esc(what)}</p>` +
    (blockers.length ? `<ul class="hr-push-block">${blockers.map((b) => `<li>${esc(b)}</li>`).join('')}</ul>` : '') +
    (notes.length ? `<ul class="hr-warn">${notes.map((n) => `<li>${esc(n)}</li>`).join('')}</ul>` : '') +
    '<label class="hr-push-pc">Program Change ' +
    `<input type="number" min="0" max="127" step="1" value="${esc(p.suggestedProgramChange ?? '')}">` +
    '<span class="settings-hint">affiché +1 sur l’écran · vide = ne pas l’attribuer</span></label>' +
    `<details><summary>${steps.length} étapes</summary><pre class="hr-cmd">${esc(steps.join('\n'))}</pre></details>` +
    '<div class="hr-push-actions">' +
    '<button type="button" class="tx-btn hr-push-confirm">Confirmer l’envoi</button>' +
    '<button type="button" class="tx-btn hr-push-cancel">Annuler</button></div>' +
    '<p class="hr-push-status"></p>';
  const confirmBtn = box.querySelector('.hr-push-confirm');
  const status = box.querySelector('.hr-push-status');
  const pcInput = box.querySelector('.hr-push-pc input');
  if (blockers.length) confirmBtn.disabled = true;
  box.querySelector('.hr-push-cancel').addEventListener('click', () => {
    box.hidden = true;
    box.innerHTML = '';
  });
  confirmBtn.addEventListener('click', async () => {
    const raw = pcInput.value.trim();
    if (raw !== '' && !(Number.isInteger(Number(raw)) && Number(raw) >= 0 && Number(raw) <= 127)) {
      status.textContent = 'Program Change : entier de 0 à 127.';
      return;
    }
    confirmBtn.disabled = true;
    status.className = 'hr-push-status';
    status.textContent = 'Écriture sur l’appareil… (10 à 30 s, ne pas toucher au Core)';
    try {
      const { res, data } = await postJson('/api/devices/headrush/push', {
        artist: payload.artist,
        title: payload.title,
        apply: true,
        confirm: true,
        token: p.token,
        programChange: raw === '' ? null : Number(raw),
      });
      if (!res.ok) {
        status.className = 'hr-push-status error';
        status.textContent = `Refusé : ${detailOf(data, res)}`;
        confirmBtn.disabled = false;
        return;
      }
      if (!data.ok) {
        status.className = 'hr-push-status error';
        status.textContent = 'Écarts à la relecture, rien n’a été sauvegardé : ' +
          (data.mismatches || []).join(' · ');
        return;
      }
      const pc = data.programChange !== null && data.programChange !== undefined
        ? ` · PC ${data.programChange}` : '';
      const verb = { create: 'Créé', update: 'Mis à jour', program_change: 'Program Change écrit' }[data.mode]
        || 'Déjà à jour';
      status.className = 'hr-push-status ok';
      status.textContent = `${verb} sur l’appareil : « ${data.rigName} »${pc}`;
      setTimeout(() => onChanged?.(), 1500);
    } catch (err) {
      status.className = 'hr-push-status error';
      status.textContent = `Erreur réseau : ${err}`;
      confirmBtn.disabled = false;
    }
  });
}

async function openPush(box, payload, onChanged) {
  box.hidden = false;
  box.innerHTML = '<p class="settings-hint">Lecture de l’appareil…</p>';
  try {
    const { res, data } = await postJson('/api/devices/headrush/push', {
      artist: payload.artist, title: payload.title,
    });
    if (!res.ok) {
      box.innerHTML = `<p class="hr-push-status error">${esc(detailOf(data, res))}</p>`;
      return;
    }
    renderPushBox(box, payload, data, onChanged);
  } catch (err) {
    box.innerHTML = `<p class="hr-push-status error">Erreur réseau : ${esc(err)}</p>`;
  }
}

/**
 * Render a stored rig inside the Rig panel: one card per slot, in chain order,
 * with the CC that bypasses it, whether it is already on the device, and the
 * button that creates or updates it there.
 *
 * @param {object} [options]
 * @param {() => void} [options.onChanged] the rig was written to the device.
 * @param {string} [options.emptyHint] how to create a rig, shown when there is none.
 */
export function renderRigView(container, payload, { onChanged, emptyHint } = {}) {
  if (!container) return;
  if (!payload || payload.error) {
    container.innerHTML = `<p class="hr-empty">${esc(payload?.error || 'Indisponible.')}</p>`;
    return;
  }
  const view = payload.view;
  if (!payload.binding || !view) {
    container.innerHTML =
      '<p class="hr-empty">Aucun rig HeadRush pour ce morceau.</p>' +
      `<p class="settings-hint">${esc(emptyHint || (
        'Cliquez « ✨ Créer avec l’IA ». Le mode choisi dans les préférences ' +
        'permet la génération par API ou le copier-coller du JSON.'))}</p>`;
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
      (b.image ? `<img class="hr-slot-img" src="${esc(b.image)}" alt="" loading="lazy">` : '') +
      `<div class="hr-slot-mod">${esc(b.module)}</div>` +
      `<div class="hr-slot-params">${paramsText(b.params)}</div>` +
    '</div>'
  )).join('');
  const problems = (view.errors || []).length
    ? `<pre class="hr-errors">${esc(view.errors.join('\n'))}</pre>` : '';
  const canWrite = !!payload.push?.writeEnabled;
  const pushLabel = prov ? '⇪ Mettre à jour sur le HeadRush' : '⇪ Créer sur le HeadRush';
  const pushHint = canWrite ? '' : (
    '<p class="settings-hint">Écriture désactivée : cochez « Autoriser l’écriture » dans ' +
    `${esc(settingsLabel)}. Ou, sur le PC relié à l’appareil :</p>` +
    `<pre class="hr-cmd">${esc(payload.provisionCommand || '')}</pre>`
  );
  container.innerHTML =
    `<div class="hr-head"><span class="hr-rig">${esc(view.rig || '')}</span>${badge}${conf}` +
    '<span class="hr-head-actions">' +
    `<button type="button" class="tx-btn hr-push-btn"${canWrite ? '' : ' disabled'}>${pushLabel}</button>` +
    '<button type="button" class="tx-btn hr-download-stored">Télécharger le rig</button></span></div>' +
    `${tone}<div class="hr-slots">${slots}</div>${problems}` +
    '<div class="hr-push" hidden></div>' + pushHint;
  // A picture the Core cannot provide (switched off, unknown model) leaves the text alone.
  container.querySelectorAll('.hr-slot-img').forEach((img) => {
    if (img.complete && img.naturalWidth === 0 && img.src) img.remove();
    else img.addEventListener('error', () => img.remove(), { once: true });
  });
  container.querySelector('.hr-download-stored')?.addEventListener('click', () => {
    downloadJson(payload.binding, `${payload.key || 'rig'}.json`);
  });
  container.querySelector('.hr-push-btn')?.addEventListener('click', () => {
    openPush(container.querySelector('.hr-push'), payload, onChanged);
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
    refreshAiSettings: async () => {},
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

  const hostInput = $('set-headrush-host');
  const writeBox = $('set-headrush-write');
  const connEl = $('set-headrush-conn');
  const HOST_RE = /^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$/;

  let activeDevice = 'valeton_gp180';
  let lastBinding = null;
  let lastFilename = 'rig.json';
  let panelEpoch = 0;
  let busy = false;
  let panelSong = null;
  let panelMode = null;
  const resizedHeights = {};
  const songKey = (song) => JSON.stringify([song?.artist || '', song?.title || '']);
  const sameSong = () => panelSong && songKey(panelSong) === songKey(getSong());

  function applyAiMode() {
    const settings = aiSettings.get();
    const manual = (settings?.mode || 'manual') === 'manual';
    const mode = manual ? 'manual' : 'api';
    if (panelMode !== mode) {
      // Native resizing writes inline height. Keep that choice per mode so a
      // resized manual editor does not leave empty space in the API panel.
      if (panelMode) resizedHeights[panelMode] = panel.style.height;
      panel.style.height = resizedHeights[mode] || '';
      panelMode = mode;
    }
    panel.setAttribute('data-hr-mode', mode);
    panel.querySelectorAll('[data-hr-manual]').forEach((el) => {
      el.hidden = !manual;
      if ('disabled' in el) el.disabled = !manual || busy || !settings;
      el.querySelectorAll('button, input, textarea').forEach((input) => {
        input.disabled = !manual || busy || !settings;
      });
    });
    const generate = $('headrush-generate-btn');
    if (generate) {
      generate.hidden = manual;
      generate.disabled = busy || !settings?.canGenerate || !settings?.[settings.mode]?.configured;
      generate.textContent = `Générer / corriger avec ${rigAiProviderName(settings?.mode)}`;
    }
    if (guidanceEl) guidanceEl.disabled = busy;
    panel.setAttribute('aria-busy', String(busy));
    const hint = $('headrush-mode-hint');
    if (hint) hint.textContent = manual
      ? 'Copiez le prompt dans votre LLM, collez sa réponse JSON, puis validez.'
      : `${rigAiProviderName(settings.mode)} produit le rig et FretWise le valide avant de l’enregistrer. ` +
        (!settings.canGenerate ? 'Génération réservée aux administrateurs.' :
          !settings[settings.mode]?.configured ? 'Configurez une clé dans les préférences.' :
            '2 appels API maximum : génération et correction technique si nécessaire, sur votre crédit API. ' +
            'L’envoi au HeadRush reste une action séparée.');
  }
  const aiSettings = initRigAiSettings({
    container: $('settings-rig-ai'),
    onChange: applyAiMode,
  });

  function setBusy(value) {
    busy = value;
    applyAiMode();
  }

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
      const core = data.headrush || {};
      if (hostInput && document.activeElement !== hostInput) hostInput.value = core.host || '';
      if (writeBox) writeBox.checked = !!core.writeEnabled;
    } catch { /* offline: keep the last known state */ }
  }

  async function open() {
    const { artist, title } = getSong() || {};
    if (!artist && !title) {
      setStatus('Ouvrez un morceau d’abord.', 'error');
      return;
    }
    const epoch = ++panelEpoch;
    const changed = songKey(panelSong) !== songKey({ artist, title });
    panelSong = { artist, title };
    titleEl.textContent = `HeadRush Core — ${[artist, title].filter(Boolean).join(' — ')}`;
    panel.style.display = '';
    resultEl.innerHTML = '';
    // A rig validated for the previous song must not stay downloadable here.
    lastBinding = null;
    promptEl.value = '';
    if (changed) {
      pasteEl.value = '';
      if (guidanceEl) guidanceEl.value = '';
    }
    if (downloadBtn) downloadBtn.style.display = 'none';
    setStatus('Lecture du mode IA…');
    const settings = await aiSettings.refresh();
    if (epoch !== panelEpoch || !sameSong()) return;
    if (!settings) {
      setStatus('Réglages IA indisponibles. Rouvrez ce panneau pour réessayer.', 'error');
      return;
    }
    if (busy) {
      setStatus('Une génération est encore en cours. Attendez sa fin avant de relancer.');
      return;
    }
    applyAiMode();
    if (settings.mode !== 'manual') {
      setStatus('Prêt : précisez le son recherché, puis lancez la génération.');
      return;
    }
    setStatus('Génération du prompt…');
    const params = new URLSearchParams({ artist: artist || '', title: title || '' });
    if (guidanceEl?.value.trim()) params.set('guidance', guidanceEl.value.trim());
    try {
      const res = await fetch(`/api/devices/headrush/prompt?${params}`, {
        credentials: 'same-origin',
      });
      const prompt = await res.text();
      if (epoch !== panelEpoch || !sameSong()) return;
      if (!res.ok) {
        let body = {};
        try { body = JSON.parse(prompt); } catch { /* non-JSON server response */ }
        setStatus(detailOf(body, res), 'error');
        promptEl.value = '';
        return;
      }
      promptEl.value = prompt;
      const version = res.headers.get('X-FretWise-App-Version') || '';
      const mode = res.headers.get('X-FretWise-Prompt-Mode') === 'verify'
        ? ' — corrige le rig existant' : '';
      setStatus(`Prompt prêt${version ? ` — firmware ${version}` : ''}${mode}`);
    } catch (err) {
      if (epoch === panelEpoch && sameSong()) setStatus(`Erreur réseau : ${err}`, 'error');
    }
  }

  function showSaved(data) {
    lastBinding = data.binding;
    lastFilename = data.suggestedFilename || 'rig.json';
    const source = data.generation ? ` · ${rigAiProviderName(data.generation.provider)} · ${data.generation.model}` : '';
    setStatus(`Validé et enregistré — ${data.blocks} blocs${source}`, 'ok');
    const warn = (data.warnings || []).length
      ? `<ul class="hr-warn">${data.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`
      : '';
    resultEl.innerHTML =
      `<p class="hr-rig">${esc(data.rig)}</p>${chainRows(data.view)}${warn}` +
      '<p class="settings-hint">Le rig est enregistré dans le panneau Rig de ce morceau. ' +
      'Ouvrez ce panneau pour prévisualiser puis confirmer son envoi au HeadRush.</p>';
    if (downloadBtn) downloadBtn.style.display = '';
    onSaved?.();
  }

  async function generate() {
    const settings = aiSettings.get();
    if (busy || !settings?.canGenerate || settings.mode === 'manual') return;
    if (!sameSong()) {
      await open();
      return;
    }
    const song = { ...panelSong };
    const epoch = panelEpoch;
    setBusy(true);
    setStatus(`${rigAiProviderName(settings.mode)} : génération et validation en cours… ` +
      'Correction technique automatique si nécessaire (2 appels API maximum). Cela peut prendre quelques minutes.');
    resultEl.innerHTML = '';
    lastBinding = null;
    if (downloadBtn) downloadBtn.style.display = 'none';
    try {
      const { res, data } = await postJson('/api/devices/headrush/generate', {
        ...song, guidance: guidanceEl?.value.trim() || '',
      });
      if (epoch !== panelEpoch || !sameSong()) return;
      if (!res.ok) {
        setStatus(`Génération interrompue : ${detailOf(data, res)} Vous pouvez réessayer.`, 'error');
        return;
      }
      showSaved(data);
    } catch (err) {
      if (epoch === panelEpoch && sameSong()) setStatus(`Erreur réseau : ${err}. Vous pouvez réessayer.`, 'error');
    } finally {
      setBusy(false);
    }
  }

  async function validate() {
    if (busy || aiSettings.get()?.mode !== 'manual') return;
    if (!sameSong()) {
      setStatus('Le morceau a changé. Rouvrez la création du rig avant de valider.', 'error');
      return;
    }
    const raw = pasteEl.value.trim();
    if (!raw) {
      setStatus('Collez d’abord la réponse du LLM.', 'error');
      return;
    }
    const { artist, title } = panelSong;
    const epoch = panelEpoch;
    setBusy(true);
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
      if (epoch !== panelEpoch || !sameSong()) return;
      if (res.status === 422) {
        setStatus('Refusé : non enregistré', 'error');
        resultEl.innerHTML =
          `<pre class="hr-errors">${esc(data.detail)}</pre>` +
          '<p class="settings-hint">Recollez ces lignes à votre LLM : elles nomment le ' +
          'paramètre attendu quand il s’est trompé.</p>';
        return;
      }
      if (!res.ok) {
        setStatus(detailOf(data, res), 'error');
        return;
      }
      showSaved(data);
    } catch (err) {
      if (epoch === panelEpoch && sameSong()) setStatus(`Erreur réseau : ${err}`, 'error');
    } finally {
      setBusy(false);
    }
  }

  $('headrush-close')?.addEventListener('click', () => { ++panelEpoch; panel.style.display = 'none'; });
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
  $('headrush-generate-btn')?.addEventListener('click', generate);
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

  async function saveSetting(body) {
    const { res, data } = await postJson('/api/settings', body);
    if (res.ok) return true;
    if (connEl) {
      connEl.textContent = data?.detail?.code === 'setting_managed_by_environment'
        ? 'Réglage imposé par une variable d’environnement du serveur.'
        : `Impossible d’enregistrer (${res.status}).`;
    }
    return false;
  }

  $('set-headrush-host-save')?.addEventListener('click', async () => {
    const value = hostInput.value.trim();
    if (!HOST_RE.test(value)) {
      connEl.textContent = 'Adresse invalide : une IP ou un nom, port optionnel (ex. 192.168.1.34).';
      return;
    }
    if (await saveSetting({ headrush_host: value })) {
      connEl.textContent = `Adresse enregistrée : ${value}`;
      await refreshDevices();
      onDeviceChange?.(activeDevice);
    }
  });

  writeBox?.addEventListener('change', async () => {
    if (!(await saveSetting({ headrush_allow_write: writeBox.checked }))) {
      writeBox.checked = !writeBox.checked;
      return;
    }
    connEl.textContent = writeBox.checked
      ? 'Écriture autorisée : le panneau Rig propose « Créer sur le HeadRush ».'
      : 'Écriture désactivée.';
    await refreshDevices();
    onDeviceChange?.(activeDevice);
  });

  $('set-headrush-test')?.addEventListener('click', async () => {
    connEl.textContent = 'Connexion…';
    try {
      const res = await fetch('/api/devices/headrush/status', { credentials: 'same-origin' });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) {
        connEl.textContent = detailOf(d, res);
        return;
      }
      connEl.textContent = d.reachable
        ? `✓ ${d.deviceName} à ${d.host} — firmware ${d.appVersion}` +
          `${d.firmwareMatches ? '' : ' (différent du catalogue !)'} — rig chargé : ${d.loadedRig}` +
          ` — ${d.rigCount} rigs — « ${d.sandbox} » ${d.sandboxPresent ? 'présent' : 'ABSENT'}`
        : `✗ Injoignable à ${d.host} : ${d.detail}`;
    } catch (err) {
      connEl.textContent = `Erreur réseau : ${err}`;
    }
  });

  // The Rig panel waits on this before choosing which view to draw, so a panel
  // opened right after page load does not flash the GP-180 sheet.
  api.ready = Promise.all([refreshDevices(), aiSettings.refresh()]);
  api.open = open;
  api.isActive = () => activeDevice === 'headrush_core';
  api.refreshDevices = refreshDevices;
  api.refreshAiSettings = aiSettings.refresh;
  return api;
}
