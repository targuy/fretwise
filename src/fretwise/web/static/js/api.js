/** api.js — FretWise API client */

export async function fetchFiles() {
  const res = await fetch('/api/files');
  if (!res.ok) throw new Error('Failed to load files');
  return res.json();
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

export async function activateSoundfont(name) {
  const res = await fetch(`/api/soundfonts/${encodeURIComponent(name)}/activate`, { method: 'POST' });
  if (!res.ok) throw new Error('Activate failed');
  return res.json();
}
