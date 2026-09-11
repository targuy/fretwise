/**
 * HeadRush Core UI: author a rig for a song through the user's own LLM, store
 * it, and show it in the Rig panel.
 *
 * FretWise calls no provider. The prompt is generated server-side from the
 * catalog read off the instrument — so every block name and enumeration label in
 * it is real — and the JSON pasted back is validated against that same catalog
 * before it is stored.
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
        'Cliquez « ✨ Créer avec l’IA » : FretWise génère le prompt, ' +
        'vous collez la réponse de votre LLM, et le rig validé s’affiche ici.'))}</p>`;
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
  api.ready = refreshDevices();
  api.open = open;
  api.isActive = () => activeDevice === 'headrush_core';
  api.refreshDevices = refreshDevices;
  return api;
}
