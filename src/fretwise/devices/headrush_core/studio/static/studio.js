/**
 * HeadRush Studio front end: songs, AI design, rig view and push, device rigs.
 *
 * The rig view itself (slot cards, push preview and confirmation) is the module
 * FretWise's Rig panel uses, served at /shared/headrush.js.
 */
import { fetchRigView, renderRigView, setSettingsLabel } from '/shared/headrush.js';

setSettingsLabel('Réglages');

const $ = (id) => document.getElementById(id);

function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

async function getJson(url) {
  const res = await fetch(url, { credentials: 'same-origin' });
  const data = await res.json().catch(() => ({}));
  return { res, data };
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

function setStatus(el, text, kind = '') {
  el.textContent = text;
  el.className = `st-status${kind ? ` ${kind}` : ''}`;
}

const state = { songs: [], current: null, device: null, settings: null };

// ── Device status pill ────────────────────────────────────────────────────

async function refreshStatus() {
  const pill = $('st-device-pill');
  try {
    const { res, data } = await getJson('/api/devices/headrush/status');
    pill.className = 'st-pill';
    if (!res.ok) {
      pill.textContent = detailOf(data, res);
      pill.classList.add('bad');
      return;
    }
    if (data.reachable) {
      pill.textContent = `● ${data.deviceName} · ${data.loadedRig}`;
      pill.classList.add(data.firmwareMatches ? 'ok' : 'warn');
      pill.title = `${data.host} · firmware ${data.appVersion}` +
        (data.firmwareMatches ? '' : ' (différent du catalogue)') +
        ` · écriture ${data.writeEnabled ? 'autorisée' : 'désactivée'}`;
    } else {
      pill.textContent = `○ Core injoignable (${data.host})`;
      pill.classList.add('bad');
      pill.title = data.detail || '';
    }
  } catch (err) {
    pill.textContent = 'Studio injoignable';
    pill.className = 'st-pill bad';
  }
}

// ── Songs ─────────────────────────────────────────────────────────────────

async function loadSongs() {
  const { res, data } = await getJson('/api/devices/headrush/rigs');
  state.songs = res.ok ? data.rigs : [];
  $('st-song-count').textContent = state.songs.length ? `(${state.songs.length})` : '';
  renderSongs();
}

function isCurrent(song) {
  return state.current && state.current.artist === song.artist && state.current.title === song.title;
}

function renderSongs() {
  const query = $('st-filter').value.trim().toLowerCase();
  const shown = state.songs.filter((s) => (
    !query || `${s.artist} ${s.title} ${s.rig}`.toLowerCase().includes(query)
  ));
  $('st-song-list').innerHTML = shown.map((s) => {
    const pc = s.provisioned?.programChange;
    const tag = s.provisioned
      ? `<span class="st-tag ok">${pc !== null && pc !== undefined ? `PC ${esc(pc)}` : 'sur le Core'}</span>`
      : '<span class="st-tag">à envoyer</span>';
    return `<li><button type="button" class="st-song${isCurrent(s) ? ' is-active' : ''}" ` +
      `data-artist="${esc(s.artist)}" data-title="${esc(s.title)}">` +
      `<span class="st-song-t">${esc(s.title)}</span>${tag}` +
      `<span class="st-song-a">${esc(s.artist)}</span></button></li>`;
  }).join('') || `<li class="st-muted st-none">${state.songs.length ? 'Aucun résultat.' : 'Aucun rig enregistré.'}</li>`;
}

function selectTab(name) {
  document.querySelectorAll('.st-tab').forEach((t) => {
    t.classList.toggle('is-active', t.dataset.tab === name);
  });
  $('tab-rig').hidden = name !== 'rig';
  $('tab-design').hidden = name !== 'design';
}

async function selectSong(artist, title) {
  state.current = { artist, title };
  $('st-empty').hidden = true;
  $('st-song').hidden = false;
  $('st-song-title').textContent = title || '(sans titre)';
  $('st-song-artist').textContent = artist;
  $('st-prompt').value = '';
  $('st-paste').value = '';
  $('st-copy').disabled = true;
  $('st-validate-result').innerHTML = '';
  setStatus($('st-gen-status'), '');
  setStatus($('st-validate-status'), '');
  renderSongs();
  const hasRig = await showRig();
  selectTab(hasRig ? 'rig' : 'design');
}

async function showRig() {
  const { artist, title } = state.current;
  const view = $('tab-rig');
  view.innerHTML = '<p class="st-muted">Chargement…</p>';
  const payload = await fetchRigView(artist, title);
  renderRigView(view, payload, {
    emptyHint: 'Ouvrez l’onglet « Concevoir avec l’IA » : le prompt part dans votre LLM, ' +
      'vous collez sa réponse, et le rig validé s’affiche ici.',
    onChanged: async () => {
      await Promise.all([showRig(), loadSongs(), refreshStatus()]);
    },
  });
  return !!payload?.binding;
}

$('st-song-list').addEventListener('click', (event) => {
  const button = event.target.closest('.st-song');
  if (button) selectSong(button.dataset.artist, button.dataset.title);
});
$('st-filter').addEventListener('input', renderSongs);
$('st-open').addEventListener('submit', (event) => {
  event.preventDefault();
  const artist = $('st-open-artist').value.trim();
  const title = $('st-open-title').value.trim();
  if (!artist && !title) return;
  selectSong(artist, title);
});
document.querySelectorAll('.st-tab').forEach((tab) => {
  tab.addEventListener('click', () => selectTab(tab.dataset.tab));
});

// ── Design with the user's LLM ───────────────────────────────────────────

$('st-gen').addEventListener('click', async () => {
  const { artist, title } = state.current;
  const status = $('st-gen-status');
  setStatus(status, 'Génération…');
  const params = new URLSearchParams({ artist, title });
  const guidance = $('st-guidance').value.trim();
  if (guidance) params.set('guidance', guidance);
  try {
    const res = await fetch(`/api/devices/headrush/prompt?${params}`, { credentials: 'same-origin' });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      setStatus(status, detailOf(data, res), 'error');
      return;
    }
    $('st-prompt').value = await res.text();
    $('st-copy').disabled = false;
    const correcting = res.headers.get('X-FretWise-Prompt-Mode') === 'verify';
    setStatus(status, `Prompt prêt — firmware ${res.headers.get('X-FretWise-App-Version') || '?'}` +
      (correcting ? ' — demande de corriger le rig existant' : ''), 'ok');
  } catch (err) {
    setStatus(status, `Erreur réseau : ${err}`, 'error');
  }
});

$('st-copy').addEventListener('click', async () => {
  const status = $('st-gen-status');
  try {
    await navigator.clipboard.writeText($('st-prompt').value);
    setStatus(status, 'Copié — collez-le dans votre LLM.', 'ok');
  } catch {
    $('st-prompt').select();
    setStatus(status, 'Copiez avec Ctrl+C.');
  }
});

$('st-validate').addEventListener('click', async () => {
  const status = $('st-validate-status');
  const result = $('st-validate-result');
  const raw = $('st-paste').value.trim();
  if (!raw) {
    setStatus(status, 'Collez d’abord la réponse du LLM.', 'error');
    return;
  }
  const { artist, title } = state.current;
  setStatus(status, 'Validation contre le catalogue…');
  result.innerHTML = '';
  try {
    const { res, data } = await postJson('/api/devices/headrush/ingest', {
      artist, title, response: raw, save: true,
    });
    if (res.status === 422) {
      setStatus(status, 'Refusé : rien n’a été enregistré.', 'error');
      result.innerHTML = `<pre class="st-errors">${esc(data.detail)}</pre>` +
        '<p class="st-muted">Recollez ces lignes à votre LLM : elles nomment le paramètre ' +
        'attendu quand il s’est trompé.</p>';
      return;
    }
    if (!res.ok) {
      setStatus(status, detailOf(data, res), 'error');
      return;
    }
    setStatus(status, `Validé et enregistré — ${data.blocks} blocs.`, 'ok');
    if ((data.warnings || []).length) {
      result.innerHTML = `<ul class="st-warn">${data.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`;
    }
    await Promise.all([loadSongs(), showRig()]);
    selectTab('rig');
  } catch (err) {
    setStatus(status, `Erreur réseau : ${err}`, 'error');
  }
});

// ── Device view ──────────────────────────────────────────────────────────

async function loadDevice() {
  const summary = $('st-device-summary');
  summary.textContent = 'Lecture de l’appareil…';
  $('st-device-rigs').innerHTML = '';
  const { res, data } = await getJson('/api/devices/headrush/device');
  if (!res.ok) {
    summary.textContent = detailOf(data, res);
    return;
  }
  state.device = data;
  if (!data.reachable) {
    summary.textContent = `Core injoignable à ${data.host} — ${data.detail || ''}`;
    return;
  }
  const mine = data.rigs.filter((r) => r.generated).length;
  const loaded = data.rigs.find((r) => r.loaded);
  summary.textContent = `${data.deviceName} · firmware ${data.appVersion} · ${data.rigs.length} rigs, ` +
    `dont ${mine} créés par FretWise · chargé : ${loaded ? loaded.name : '?'}` +
    (data.writeEnabled ? '' : ' · écriture désactivée (Réglages) : « Charger » indisponible');
  renderDevice();
}

function renderDevice() {
  const data = state.device;
  if (!data?.reachable) return;
  const query = $('st-device-filter').value.trim().toLowerCase();
  const rows = data.rigs.filter((r) => (
    !query || `${r.name} ${r.song?.artist || ''} ${r.song?.title || ''}`.toLowerCase().includes(query)
  ));
  $('st-device-rigs').innerHTML = rows.map((r) => {
    const song = r.song
      ? `<button type="button" class="st-link" data-artist="${esc(r.song.artist)}" ` +
        `data-title="${esc(r.song.title)}">${esc(r.song.artist)} — ${esc(r.song.title)}</button>`
      : '';
    const pc = r.song?.programChange ?? '';
    const tags = (r.loaded ? '<span class="st-tag ok">chargé</span>' : '') +
      (r.generated ? '<span class="st-tag">FretWise</span>' : '');
    const disabled = r.loaded || !data.writeEnabled ? ' disabled' : '';
    return `<tr class="${r.loaded ? 'is-loaded' : ''}"><td>${esc(r.name)} ${tags}</td>` +
      `<td>${song}</td><td>${esc(pc)}</td>` +
      `<td><button type="button" class="st-btn st-small st-load" data-id="${esc(r.id)}"${disabled}>Charger</button></td></tr>`;
  }).join('') || '<tr><td colspan="4" class="st-muted">Aucun rig.</td></tr>';
}

$('st-device-filter').addEventListener('input', renderDevice);
$('st-device-refresh').addEventListener('click', loadDevice);
$('st-device-rigs').addEventListener('click', async (event) => {
  const link = event.target.closest('.st-link');
  if (link) {
    switchView('songs');
    selectSong(link.dataset.artist, link.dataset.title);
    return;
  }
  const load = event.target.closest('.st-load');
  if (!load) return;
  load.disabled = true;
  $('st-device-summary').textContent = 'Chargement du rig sur l’appareil…';
  const { res, data } = await postJson('/api/devices/headrush/load', { rigId: load.dataset.id });
  if (!res.ok) {
    $('st-device-summary').textContent = `Refusé : ${detailOf(data, res)}`;
    load.disabled = false;
    return;
  }
  await Promise.all([loadDevice(), refreshStatus()]);
});

// ── Views ────────────────────────────────────────────────────────────────

function switchView(name) {
  document.querySelectorAll('.st-nav-btn').forEach((b) => {
    b.classList.toggle('is-active', b.dataset.view === name);
  });
  $('view-songs').hidden = name !== 'songs';
  $('view-device').hidden = name !== 'device';
  if (name === 'device') loadDevice();
}

document.querySelectorAll('.st-nav-btn').forEach((b) => {
  b.addEventListener('click', () => switchView(b.dataset.view));
});

// ── Settings ─────────────────────────────────────────────────────────────

async function openSettings() {
  const { res, data } = await getJson('/api/studio/settings');
  const status = $('st-settings-status');
  setStatus(status, '');
  if (res.ok) {
    state.settings = data;
    $('st-host').value = data.host || '';
    $('st-write').checked = !!data.allowWriteSetting;
    const locked = data.locked || [];
    $('st-host').disabled = locked.includes('headrush_host');
    $('st-locked').hidden = !locked.length;
    $('st-locked').textContent = locked.length
      ? `Imposé par l’environnement du serveur : ${locked.join(', ')}.` : '';
  } else {
    setStatus(status, detailOf(data, res), 'error');
  }
  $('st-settings').showModal();
}

async function saveSettings() {
  const status = $('st-settings-status');
  const body = { headrush_allow_write: $('st-write').checked };
  if (!$('st-host').disabled) body.headrush_host = $('st-host').value.trim();
  const { res, data } = await postJson('/api/studio/settings', body);
  if (!res.ok) {
    setStatus(status, detailOf(data, res), 'error');
    return false;
  }
  state.settings = { ...state.settings, ...data };
  setStatus(status, 'Enregistré.', 'ok');
  refreshStatus();
  if (state.current) showRig();
  if (!$('view-device').hidden) loadDevice();
  return true;
}

$('st-settings-btn').addEventListener('click', openSettings);
$('st-device-pill').addEventListener('click', openSettings);
$('st-settings-save').addEventListener('click', saveSettings);
$('st-test').addEventListener('click', async () => {
  const status = $('st-settings-status');
  // Test the address typed, not the one saved before it.
  if (!(await saveSettings())) return;
  setStatus(status, 'Connexion…');
  const { res, data } = await getJson('/api/devices/headrush/status');
  if (!res.ok) {
    setStatus(status, detailOf(data, res), 'error');
    return;
  }
  if (data.reachable) {
    setStatus(status, `✓ ${data.deviceName} — firmware ${data.appVersion}` +
      `${data.firmwareMatches ? '' : ' (différent du catalogue !)'} — ${data.rigCount} rigs — ` +
      `« ${data.sandbox} » ${data.sandboxPresent ? 'présent' : 'ABSENT'}`, data.sandboxPresent ? 'ok' : 'error');
  } else {
    setStatus(status, `✗ Injoignable à ${data.host} : ${data.detail}`, 'error');
  }
});

// ── Start ────────────────────────────────────────────────────────────────

refreshStatus();
loadSongs();
setInterval(() => { if (!document.hidden) refreshStatus(); }, 30000);
