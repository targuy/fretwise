/** api.js — FretWise API client */

export async function fetchFiles() {
  // no-store: fingering badges change after a save, so a cached body would
  // show stale icons when returning to the library.
  const res = await fetch('/api/files', { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to load files');
  return res.json();
}

/**
 * Stream score files progressively from the server as NDJSON.
 * `onItem(fileObj)` is called once per file as it arrives.
 * Resolves when the stream is fully consumed.
 */
export async function streamFiles(onItem) {
  const res = await fetch('/api/files/stream', { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to stream files');
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = '';
  while (true) {
    const { value, done } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    let nl;
    while ((nl = buf.indexOf('\n')) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (!line) continue;
      const item = JSON.parse(line);
      if (item.error) throw new Error(item.error);
      onItem(item);
    }
  }
}

export async function fetchRig(filename) {
  // Valeton GP-180 rig for a song; null when the song has no rig. The server
  // prefers a new-format gears sheet over the legacy .md when both exist.
  try {
    const res = await fetch(`/api/rig/${encodeURIComponent(filename)}`);
    if (!res.ok) return null;
    return await res.json();
  } catch (_e) {
    return null;
  }
}

export async function fetchRigBank() {
  const res = await fetch('/api/rig-bank', { cache: 'no-store' });
  if (!res.ok) throw new Error('Failed to load GP-180 rig bank');
  return await res.json();
}

export async function resolveRigProfile(body) {
  const res = await fetch('/api/rig-bank/resolve', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function recommendRigProfile(body) {
  const res = await fetch('/api/rig-bank/recommend', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (res.status === 404) return null;
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function activateRigProfile(body) {
  const res = await fetch('/api/rig-bank/activate', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body || {}),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function fetchRigMidiOutputs() {
  const res = await fetch('/api/rig-bank/midi-outputs', { cache: 'no-store' });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function saveRigProfile(profile) {
  const res = await fetch('/api/rig-bank/profile', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(profile || {}),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function saveRigBinding(binding) {
  const res = await fetch('/api/rig-bank/binding', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(binding || {}),
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try { const b = await res.json(); if (b && b.detail) detail = b.detail; } catch (_e) { /* keep */ }
    throw new Error(detail);
  }
  return await res.json();
}

export async function fetchStorage() {
  // Active storage backend + health. In multi-user mode this is the logged-in
  // user's own backend; { configured: false } when they have not connected one.
  // Returns null on any error so callers can degrade gracefully.
  try {
    const res = await fetch('/api/storage');
    if (!res.ok) return null;
    return await res.json();
  } catch (_e) {
    return null;
  }
}

export async function fetchTracks(filename) {
  const res = await fetch(`/api/tracks/${encodeURIComponent(filename)}`);
  if (!res.ok) throw new Error('Failed to load tracks');
  return res.json();
}

export function uploadFile(file, onProgress) {
  return _xhrUpload('/api/upload', file, onProgress);
}

/**
 * POST a file as multipart/form-data via XHR so upload progress is observable.
 * @param {string} url
 * @param {File} file
 * @param {(frac:number, loaded:number, total:number)=>void} [onProgress]
 * @returns {Promise<object>} parsed JSON response
 */
function _xhrUpload(url, file, onProgress) {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    fd.append('file', file);
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    if (onProgress) {
      xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) onProgress(e.loaded / e.total, e.loaded, e.total);
      };
    }
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        try { resolve(JSON.parse(xhr.responseText)); } catch { resolve({}); }
      } else {
        let detail = 'Upload failed';
        try { detail = JSON.parse(xhr.responseText).detail || detail; } catch { /* keep default */ }
        reject(new Error(detail));
      }
    };
    xhr.onerror = () => reject(new Error('Upload failed (network error)'));
    xhr.send(fd);
  });
}

export async function fetchNotes(filename, trackId, preferences = {}) {
  const sameFingerPenalty = preferences.sameFingerPenalty !== false;
  const inferImplicitLegato = preferences.inferImplicitLegato !== false;
  let url = `/api/notes/${encodeURIComponent(filename)}?`;
  url += `same_finger_motion_penalty=${sameFingerPenalty ? 'true' : 'false'}`;
  url += `&infer_implicit_legato=${inferImplicitLegato ? 'true' : 'false'}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Notes fetch failed');
  }
  return res.json();
}

export async function fetchSolve(filename, trackId, representationMode, preferences = {}, svgWidth) {
  const sameFingerPenalty = preferences.sameFingerPenalty !== false;
  const inferImplicitLegato = preferences.inferImplicitLegato !== false;
  let url =
    `/api/solve/${encodeURIComponent(filename)}?` +
    `representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}` +
    `&same_finger_motion_penalty=${sameFingerPenalty ? 'true' : 'false'}` +
    `&infer_implicit_legato=${inferImplicitLegato ? 'true' : 'false'}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  if (svgWidth) url += `&svg_width=${svgWidth}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Solve failed');
  }
  return res.json();
}

export async function fetchExportGp(filename, trackId) {
  let url = `/api/export/gp/${encodeURIComponent(filename)}`;
  if (trackId !== null && trackId !== undefined) url += `?track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'GP export failed' }));
    throw new Error(err.detail || 'GP export failed');
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') || '';
  const m = disposition.match(/filename="([^"]+)"/);
  const annotatedNotes = parseInt(
    res.headers.get('x-fretwise-annotated-notes') || '0', 10,
  );
  return { blob, filename: m ? m[1] : 'fingered.gp', annotatedNotes };
}

export async function fetchSaveGp(filename, trackId) {
  let url = `/api/save/gp/${encodeURIComponent(filename)}`;
  if (trackId !== null && trackId !== undefined) url += `?track_id=${trackId}`;
  const res = await fetch(url, { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Sauvegarde GP échouée' }));
    throw new Error(err.detail || 'Sauvegarde GP échouée');
  }
  return res.json();
}

export async function cleanupLibrary() {
  const res = await fetch('/api/library/cleanup', { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Nettoyage échoué' }));
    throw new Error(err.detail || 'Nettoyage échoué');
  }
  return res.json();
}

export async function fetchExportMusicXml(filename, trackId, scope = 'current') {
  // scope: 'current' (single track, default — today's behaviour) or 'all'
  // (every track, backend returns a multi-part MusicXML suffixed _all).
  const params = new URLSearchParams();
  if (trackId !== null && trackId !== undefined) params.set('track_id', String(trackId));
  if (scope && scope !== 'current') params.set('scope', scope);
  const qs = params.toString();
  const url = `/api/export/musicxml/${encodeURIComponent(filename)}${qs ? `?${qs}` : ''}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'MusicXML export failed' }));
    throw new Error(err.detail || 'MusicXML export failed');
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') || '';
  const m = disposition.match(/filename="([^"]+)"/);
  const noteCount = parseInt(res.headers.get('x-fretwise-note-count') || '0', 10);
  return { blob, filename: m ? m[1] : 'fretwise.musicxml', noteCount };
}

// Convenience wrapper for the "export every track" choice. Falls back is
// handled by the caller (e.g. on 404 from a backend without scope support).
export async function fetchExportMusicXmlAll(filename, trackId) {
  return fetchExportMusicXml(filename, trackId, 'all');
}

export async function downloadFile(filename) {
  const url = `/api/download/${encodeURIComponent(filename)}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Download failed' }));
    throw new Error(err.detail || 'Download failed');
  }
  const blob = await res.blob();
  const contentDisposition = res.headers.get('content-disposition') || '';
  let filenameOut = filename;
  const m = /filename="?([^";]+)"?/i.exec(contentDisposition);
  if (m && m[1]) filenameOut = m[1];
  return { blob, filename: filenameOut };
}

export async function fetchExportPdf(filename, trackId, representationMode) {
  let url =
    `/api/export/pdf/${encodeURIComponent(filename)}` +
    `?representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}`;
  if (trackId !== null && trackId !== undefined) {
    url += `&track_id=${trackId}`;
  }

  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'PDF export failed' }));
    throw new Error(err.detail || 'PDF export failed');
  }

  const blob = await res.blob();
  const contentDisposition = res.headers.get('content-disposition') || '';
  const conformanceIssuesRaw = res.headers.get('x-fretwise-conformance-issues') || '0';
  const conformanceIssues = Number.parseInt(conformanceIssuesRaw, 10) || 0;
  const conformanceReportRaw = res.headers.get('x-fretwise-conformance-report') || '';
  let conformanceReport = null;
  if (conformanceReportRaw) {
    try {
      conformanceReport = JSON.parse(conformanceReportRaw);
    } catch (_err) {
      conformanceReport = null;
    }
  }
  let filenameOut = 'fretwise-export.pdf';
  const m = /filename="?([^";]+)"?/i.exec(contentDisposition);
  if (m && m[1]) filenameOut = m[1];

  return { blob, filename: filenameOut, engine: 'core', conformanceIssues, conformanceReport };
}

export async function fetchSettings() {
  const res = await fetch('/api/settings');
  if (!res.ok) throw new Error('Failed to fetch settings');
  return res.json();
}

export async function saveSettings(updates) {
  const res = await fetch('/api/settings', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(updates),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to save settings' }));
    throw new Error(err.detail || 'Failed to save settings');
  }
  return res.json();
}

export async function fetchSongInfo(filename) {
  const res = await fetch(`/api/song-info/${encodeURIComponent(filename)}`);
  if (!res.ok) return null;
  return res.json();
}

export async function fetchGmInstruments() {
  const res = await fetch('/api/soundfont/instruments');
  if (!res.ok) throw new Error('Failed to fetch GM instruments');
  return res.json();
}

export async function fetchSoundfonts() {
  const res = await fetch('/api/soundfonts');
  if (!res.ok) throw new Error('Failed to fetch soundfonts');
  return res.json();
}

export async function deleteSoundfont(name) {
  const res = await fetch(`/api/soundfonts/${encodeURIComponent(name)}`, { method: 'DELETE' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Delete failed' }));
    throw new Error(err.detail || 'Delete failed');
  }
  return res.json();
}

export function uploadSoundfont(file, onProgress) {
  return _xhrUpload('/api/soundfonts/upload', file, onProgress);
}

/** Current authenticated user + storage status. Returns null in single-user mode. */
export async function fetchMe() {
  const res = await fetch('/api/me');
  if (!res.ok) return null;
  return res.json();
}

export async function connectStorage(backend, config = {}) {
  const res = await fetch('/api/storage/connect', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ backend, config }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Connect failed' }));
    throw new Error(err.detail || 'Connect failed');
  }
  return res.json();
}

export async function disconnectStorage() {
  const res = await fetch('/api/storage/disconnect', { method: 'POST' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Disconnect failed' }));
    throw new Error(err.detail || 'Disconnect failed');
  }
  return res.json();
}

// ── Song metadata workflow (enrich catalog via the user's own LLM) ──────────

/**
 * Download the song list as a JSON file (Content-Disposition attachment).
 * Returns { blob, filename } for use with _downloadBlob.
 */
export async function fetchSongListDownload() {
  const res = await fetch('/api/songs/export-list?download=1');
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to export song list' }));
    throw new Error(err.detail || 'Failed to export song list');
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') || '';
  const m = /filename="?([^";]+)"?/i.exec(disposition);
  return { blob, filename: m && m[1] ? m[1] : 'fretwise-songs.json' };
}

/**
 * Download the LLM prompt as a markdown file. Returns { blob, filename }.
 */
export async function fetchLlmPrompt() {
  const res = await fetch('/api/songs/prompt');
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch prompt' }));
    throw new Error(err.detail || 'Failed to fetch prompt');
  }
  const blob = await res.blob();
  const disposition = res.headers.get('content-disposition') || '';
  const m = /filename="?([^";]+)"?/i.exec(disposition);
  return { blob, filename: m && m[1] ? m[1] : 'fretwise-metadata-prompt.md' };
}

/**
 * POST the LLM's output (an array of metadata objects) to merge into the
 * catalog. Returns { updated, added, total }.
 */
export async function importSongMetadata(jsonBody) {
  const res = await fetch('/api/songs/import', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(jsonBody),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Import failed' }));
    throw new Error(err.detail || 'Import failed');
  }
  return res.json();
}

/**
 * Fetch the copy-paste prompt asking an external LLM to (re-)verify a song's
 * gear/rig sheet. Grounded in the existing sheet when one exists. Returns the
 * prompt text (Markdown).
 */
export async function fetchGearVerificationPrompt(filename) {
  const res = await fetch(`/api/gears/${encodeURIComponent(filename)}/prompt`, { cache: 'no-store' });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Failed to fetch prompt' }));
    throw new Error(err.detail || 'Failed to fetch prompt');
  }
  return res.text();
}

/**
 * Save a gear.v2 JSON document pasted back from an LLM. Overwrites the song's
 * existing sheet in place, or creates a new one. Returns
 * `{ saved, warnings, view }` where `view` is the refreshed rig view dict.
 */
export async function saveGearSheet(filename, gear) {
  const res = await fetch(`/api/gears/${encodeURIComponent(filename)}/save`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ gear }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Save failed' }));
    throw new Error(err.detail || 'Save failed');
  }
  return res.json();
}

// ── Fingering review & continuous improvement ───────────────────────────────

/** Fetch the ranked list of fingerings to review for a track. */
export async function fetchReview(filename, trackId) {
  let url = `/api/review/${encodeURIComponent(filename)}`;
  if (trackId !== null && trackId !== undefined) url += `?track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Review failed' }));
    throw new Error(err.detail || 'Review failed');
  }
  return res.json();
}

/** Fetch up to N distinct, playable fingerings for one measure. */
export async function fetchAlternatives(filename, measureIndex, trackId) {
  const params = new URLSearchParams({ measure_index: String(measureIndex) });
  if (trackId !== null && trackId !== undefined) params.set('track_id', String(trackId));
  const url = `/api/review/${encodeURIComponent(filename)}/alternatives?${params}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Alternatives failed' }));
    throw new Error(err.detail || 'Alternatives failed');
  }
  return res.json();
}

/** Persist a user's chosen fingering for a measure. */
export async function postReviewChoice(filename, trackId, body) {
  let url = `/api/review/${encodeURIComponent(filename)}/choice`;
  if (trackId !== null && trackId !== undefined) url += `?track_id=${trackId}`;
  const res = await fetch(url, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Save failed' }));
    throw new Error(err.detail || 'Save failed');
  }
  return res.json();
}

export async function activateSoundfont(name) {
  const res = await fetch(`/api/soundfonts/${encodeURIComponent(name)}/activate`, { method: 'POST' });
  if (!res.ok) throw new Error('Activate failed');
  return res.json();
}
