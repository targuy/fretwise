/**
 * HeadRush Core panel: author a rig for a song through the user's own LLM.
 *
 * FretWise calls no provider. The prompt is generated server-side from the
 * catalog read off the instrument — so every block name and enumeration label in
 * it is real — and the JSON pasted back is validated against that same catalog
 * before it can go anywhere near the amplifier.
 *
 * The panel deliberately stops at a validated document. Pushing to the device is
 * a command-line operation on the machine that owns the instrument, because the
 * Core's local API has no authentication and proxying writes through a web app
 * would open a door onto someone's amplifier.
 */

const $ = (id) => document.getElementById(id);

/** Escape text destined for innerHTML. */
function esc(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}

/** Render the validated chain, showing each slot and the CC that bypasses it. */
function chainRows(binding) {
  const blocks = Array.isArray(binding?.blocks) ? binding.blocks : [];
  if (!blocks.length) return '<p class="settings-hint">Aucun bloc.</p>';
  const rows = blocks.map((b) => {
    const params = Object.entries(b.params || {})
      .map(([k, v]) => `${esc(k)} <b>${esc(v)}</b>`)
      .join(' · ');
    return `<tr><td class="hr-mod">${esc(b.module)}</td><td class="hr-params">${params}</td></tr>`;
  }).join('');
  return `<table class="hr-chain"><tbody>${rows}</tbody></table>`;
}

/**
 * Wire the HeadRush panel.
 *
 * @param {object} options
 * @param {() => {artist: string, title: string}} options.getSong current song.
 */
export function initHeadrush({ getSong }) {
  const panel = $('headrush-panel');
  if (!panel) return { open: () => {}, isActive: () => false };

  const promptEl = $('headrush-prompt');
  const pasteEl = $('headrush-paste');
  const statusEl = $('headrush-status');
  const resultEl = $('headrush-result');
  const titleEl = $('headrush-title');
  const guidanceEl = $('headrush-guidance');

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
          : "Aucun catalogue. Lancez scripts/device_catalog_dump.py, appareil allumé.";
      }
    } catch { /* offline: leave the last known state */ }
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
    lastBinding = null;
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
      setStatus(version ? `Prompt prêt — firmware ${version}` : 'Prompt prêt');
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
        body: JSON.stringify({ artist, title, response: raw }),
      });
      const data = await res.json();
      if (res.status === 422) {
        setStatus('Refusé par l’appareil', 'error');
        resultEl.innerHTML =
          `<pre class="hr-errors">${esc(data.detail)}</pre>` +
          `<p class="settings-hint">Recollez ces lignes à votre LLM : elles nomment le
           paramètre attendu quand il s’est trompé.</p>`;
        return;
      }
      if (!res.ok) {
        setStatus(data?.detail || `Erreur ${res.status}`, 'error');
        return;
      }
      lastBinding = data.binding;
      lastFilename = data.suggestedFilename || 'rig.json';
      setStatus(`Validé — ${data.blocks} blocs`, 'ok');
      const warn = (data.warnings || []).length
        ? `<ul class="hr-warn">${data.warnings.map((w) => `<li>${esc(w)}</li>`).join('')}</ul>`
        : '';
      resultEl.innerHTML =
        `<p class="hr-rig">${esc(data.rig)}</p>${chainRows(data.binding)}${warn}` +
        `<p class="settings-hint">Téléchargez le fichier dans
         <code>data/devices/headrush-core/rigs/</code>, puis, sur la machine reliée
         au Core :</p>
         <pre class="hr-cmd">pixi run python scripts/device_provision.py \\
  data/devices/headrush-core/rigs/${esc(lastFilename)} --apply --confirm --pc &lt;num&gt;</pre>`;
      $('headrush-download-btn').style.display = '';
    } catch (err) {
      setStatus(`Erreur réseau : ${err}`, 'error');
    }
  }

  function download() {
    if (!lastBinding) return;
    const blob = new Blob([JSON.stringify(lastBinding, null, 1)], { type: 'application/json' });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = lastFilename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    URL.revokeObjectURL(a.href);
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
  $('headrush-download-btn')?.addEventListener('click', download);

  const deviceSelect = $('set-gear-device');
  deviceSelect?.addEventListener('change', async () => {
    const value = deviceSelect.value;
    try {
      const res = await fetch('/api/settings', {
        method: 'POST',
        credentials: 'same-origin',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ gear_device: value }),
      });
      const state = $('set-headrush-state');
      if (!res.ok && state) {
        state.textContent = `Impossible d’enregistrer le choix (${res.status}).`;
        return;
      }
      activeDevice = value;
      await refreshDevices();
    } catch (err) {
      const state = $('set-headrush-state');
      if (state) state.textContent = `Erreur réseau : ${err}`;
    }
  });

  refreshDevices();
  return { open, isActive: () => activeDevice === 'headrush_core', refreshDevices };
}
