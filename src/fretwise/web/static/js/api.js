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

export async function fetchSolve(filename, trackId, mode, representationMode) {
  let url =
    `/api/solve/${encodeURIComponent(filename)}?mode=${encodeURIComponent(mode)}` +
    `&representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Solve failed');
  }
  return res.json();
}

export async function fetchExportPdf(filename, trackId, mode, engine, representationMode) {
  let url =
    `/api/export/pdf/${encodeURIComponent(filename)}` +
    `?mode=${encodeURIComponent(mode)}` +
    `&engine=${encodeURIComponent(engine)}` +
    `&representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}`;
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
  const usedEngine = res.headers.get('x-fretwise-pdf-engine') || engine || 'legacy';
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
  const m = /filename=\"?([^\";]+)\"?/i.exec(contentDisposition);
  if (m && m[1]) filenameOut = m[1];

  return {
    blob,
    filename: filenameOut,
    engine: usedEngine,
    conformanceIssues,
    conformanceReport,
  };
}
