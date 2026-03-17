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

export async function fetchSolve(filename, trackId, mode) {
  let url = `/api/solve/${encodeURIComponent(filename)}?mode=${mode}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Solve failed');
  }
  return res.json();
}

export async function fetchExportPdf(filename, trackId, mode, engine) {
  let url =
    `/api/export/pdf/${encodeURIComponent(filename)}` +
    `?mode=${encodeURIComponent(mode)}` +
    `&engine=${encodeURIComponent(engine)}`;
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
  let filenameOut = 'fretwise-export.pdf';
  const m = /filename=\"?([^\";]+)\"?/i.exec(contentDisposition);
  if (m && m[1]) filenameOut = m[1];

  return { blob, filename: filenameOut };
}
