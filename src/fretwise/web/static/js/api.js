/** api.js — FretWise API client */

export async function fetchFiles() {
  const res = await fetch('/api/files');
  if (!res.ok) throw new Error('Failed to load files');
  return res.json();
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

export async function uploadFile(file) {
  const form = new FormData();
  form.append('file', file);
  const res = await fetch('/api/upload', { method: 'POST', body: form });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
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

export async function fetchSolve(filename, trackId, representationMode, preferences = {}) {
  const sameFingerPenalty = preferences.sameFingerPenalty !== false;
  const inferImplicitLegato = preferences.inferImplicitLegato !== false;
  let url =
    `/api/solve/${encodeURIComponent(filename)}?` +
    `representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}` +
    `&same_finger_motion_penalty=${sameFingerPenalty ? 'true' : 'false'}` +
    `&infer_implicit_legato=${inferImplicitLegato ? 'true' : 'false'}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
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

export async function uploadSoundfont(file) {
  const fd = new FormData();
  fd.append('file', file);
  const res = await fetch('/api/soundfonts/upload', { method: 'POST', body: fd });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Upload failed' }));
    throw new Error(err.detail || 'Upload failed');
  }
  return res.json();
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

export async function activateSoundfont(name) {
  const res = await fetch(`/api/soundfonts/${encodeURIComponent(name)}/activate`, { method: 'POST' });
  if (!res.ok) throw new Error('Activate failed');
  return res.json();
}
