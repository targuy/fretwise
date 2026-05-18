/**
 * main.js — App initialization, page routing, event wiring
 *
 * Pages:  file-selector → track-selector → tab-viewer
 * Orchestra: renderer + playback + toolbar
 */

import { activateSoundfont, deleteSoundfont, downloadFile, fetchExportGp, fetchExportPdf, fetchFiles, fetchGmInstruments, fetchNotes, fetchSettings, fetchSongInfo, fetchSolve, fetchSoundfonts, fetchTracks, saveSettings, uploadFile, uploadSoundfont } from './api.js';
import { getMaskedMeasures, renderAuditBanner, resetAuditBanner } from './audit.js';
import { TabRenderer, buildLegendHTML } from './renderer.js';
import { PlaybackEngine } from './playback.js';
import { SvgCursorDriver } from './svg-playback.js';
import { MODES, MODE_LABELS, DEFAULT_MODE } from './modeConfig.js';

// ── State ───────────────────────────────────────────────────────────

let currentFile = null;
let currentTrackId = null;
let currentTracks = [];   // all tracks for the current file
let renderer = null;
let playback = null;
let _svgDriver = null;  // SvgCursorDriver instance for standard/standard+tab views
let loopASet = false;  // has A marker been set
let soundOn = false;   // tracks mute state across track changes
const _notesCache = new Map(); // key: `${file}#${trackId}` → /api/notes response
// key: primaryTrackId → Set<secondaryTrackId> — tracks explicitly muted by the user
const _mutedSecondaryTracks = new Map();

let _followPlayhead = true;  // when false, user is exploring — no auto-scroll

// ── DOM references ──────────────────────────────────────────────────

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const fileSelector  = $('#file-selector');
const trackSelector = $('#track-selector');
const tabViewer     = $('#tab-viewer');
const settingsPage  = $('#settings-page');
const trackGrid     = $('#track-list');
const tabCanvas     = $('#tab-canvas');
const cursorCanvas  = $('#cursor-canvas');
const coreSvgView   = $('#core-svg-view');
const legendContent = $('#legend-content');
const toolbar       = $('#toolbar');

// Toolbar controls
const btnPlay       = $('#btn-play');
const btnPrev       = $('#btn-prev');
const btnNext       = $('#btn-next');
const btnLoopA      = $('#btn-loop-a');
const btnLoopB      = $('#btn-loop-b');
const btnLoopClear  = $('#btn-loop-clear');
const btnMetronome  = $('#btn-metronome');
const btnFollow     = $('#btn-follow');
const btnFingering  = $('#btn-fingering');
const btnExportPdf  = $('#btn-export-pdf');
const btnExportGp   = $('#btn-export-gp');
const btnDownloadGp = $('#btn-download-gp');
const pdfExportStatus = $('#pdf-export-status');
const btnBackFiles  = $('#btn-back-files');
const btnBackViewer  = $('#btn-back-viewer');
const trackSwitcher  = $('#track-switcher');
const selSpeed       = $('#speed-select');
const bpmInput       = $('#bpm-input');
const selRepresentationMode = $('#representation-mode-select');
const uploadInput    = $('#upload-input');
const uploadStatus   = $('#upload-status');
const rngVolume     = $('#rng-volume');
const songTitle     = $('#song-title');
const songArtist    = $('#song-artist');
const trackBadge    = $('#meta-instrument');
const metaMode      = $('#meta-mode');
const metaViewMode  = $('#meta-view-mode');
const metaTempo     = $('#meta-tempo');
const positionBar   = $('#position-bar');

// Timecode
const tcCurrent = $('#tc-current');

function _fmtTime(sec) {
  const s = Math.floor(sec);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

// Header extras
const headerMeta       = $('#header-meta');
const headerMetaTitle  = $('#header-meta-title');
const headerMetaTrack  = $('#header-meta-track');
const headerMetaTempo  = $('#header-meta-tempo');
const btnHeaderBack    = $('#btn-header-back');
const btnHeaderPdf     = $('#btn-header-pdf');
const btnHeaderGp      = $('#btn-header-gp');

// Header
const btnLegend     = $('#btn-legend');
const legendOverlay = $('#legend-overlay');
const legendClose   = $('#legend-close');
const prefSameFingerPenalty = $('#pref-same-finger-penalty');
const prefInferLegato = $('#pref-infer-legato');
const prefHandOverlay = $('#pref-hand-overlay');
const btnHandViz    = $('#btn-hand-viz');
const handVizPanel  = $('#hand-viz-panel');
const handVizFrame  = $('#hand-viz-frame');
const handVizClose  = $('#hand-viz-close');
const handVizResync = $('#hand-viz-resync');
const handVizDrag   = $('#hand-viz-drag');

// ── Page routing ────────────────────────────────────────────────────

function showPage(page) {
  const isViewer = page === 'viewer';
  fileSelector.style.display  = page === 'files'    ? '' : 'none';
  trackSelector.style.display = page === 'tracks'   ? '' : 'none';
  tabViewer.style.display     = isViewer ? '' : 'none';
  toolbar.style.display       = isViewer ? '' : 'none';
  if (settingsPage)     settingsPage.style.display     = page === 'settings' ? '' : 'none';
  if (headerMeta)       headerMeta.style.display       = isViewer ? '' : 'none';
  if (btnHeaderBack)    btnHeaderBack.style.display    = isViewer ? '' : 'none';
  if (btnDownloadGp)    btnDownloadGp.style.display    = isViewer ? '' : 'none';
  const tabsBar = $('#track-tabs-bar');
  if (tabsBar) tabsBar.style.display = isViewer ? '' : 'none';
  // Ensure the old bottom bar class doesn't shift bottom elements
  document.body.classList.remove('has-multitrack-bar');
}

// ── File selector (library table) ──────────────────────────────────

let _allFiles = [];
let _libSort = { col: 'title', dir: 1 };
let _libSearch = '';
let _libGenreFilter = '';
let _libFormatFilter = '';

async function loadFiles() {
  showPage('files');
  try {
    _allFiles = await fetchFiles();
    _populateLibFilters();
    _renderLibTable();
  } catch (err) {
    console.error('loadFiles error:', err);
    const empty = $('#lib-empty');
    if (empty) {
      empty.style.display = '';
      empty.textContent = 'Error loading files: ' + (err.message || err);
    }
  }
}

function _populateLibFilters() {
  const genres = new Set();
  const formats = new Set();
  for (const f of _allFiles) {
    if (f.meta?.genre) genres.add(f.meta.genre);
    if (f.format) formats.add(f.format);
  }
  const genreSel = $('#lib-genre-filter');
  if (genreSel) {
    genreSel.innerHTML = '<option value="">All genres</option>';
    [...genres].sort().forEach(g => {
      const o = document.createElement('option');
      o.value = g; o.textContent = g;
      genreSel.appendChild(o);
    });
  }
  const fmtSel = $('#lib-format-filter');
  if (fmtSel) {
    fmtSel.innerHTML = '<option value="">All formats</option>';
    [...formats].sort().forEach(f => {
      const o = document.createElement('option');
      o.value = f; o.textContent = f;
      fmtSel.appendChild(o);
    });
  }
}

function _renderLibTable() {
  const tbody = $('#lib-table-body');
  const empty = $('#lib-empty');
  if (!tbody) return;

  let rows = _allFiles.filter(f => {
    const title = (f.meta?.title || f.stem || '').toLowerCase();
    const artist = (f.meta?.artist || '').toLowerCase();
    const genre = (f.meta?.genre || '').toLowerCase();
    const q = _libSearch.toLowerCase();
    if (q && !title.includes(q) && !artist.includes(q) && !genre.includes(q) && !(f.name || '').toLowerCase().includes(q)) return false;
    if (_libGenreFilter && (f.meta?.genre || '') !== _libGenreFilter) return false;
    if (_libFormatFilter && (f.format || '') !== _libFormatFilter) return false;
    return true;
  });

  rows.sort((a, b) => {
    let av, bv;
    switch (_libSort.col) {
      case 'title':  av = a.meta?.title || a.stem || ''; bv = b.meta?.title || b.stem || ''; break;
      case 'artist': av = a.meta?.artist || ''; bv = b.meta?.artist || ''; break;
      case 'genre':  av = a.meta?.genre || ''; bv = b.meta?.genre || ''; break;
      case 'year':   av = parseInt(a.meta?.year) || 0; bv = parseInt(b.meta?.year) || 0; break;
      case 'format': av = a.format || ''; bv = b.format || ''; break;
      default:       av = ''; bv = '';
    }
    if (av < bv) return -_libSort.dir;
    if (av > bv) return _libSort.dir;
    return 0;
  });

  if (rows.length === 0) {
    if (empty) empty.style.display = '';
    tbody.innerHTML = '';
    return;
  }
  if (empty) empty.style.display = 'none';

  tbody.innerHTML = '';
  for (const f of rows) {
    const tr = document.createElement('tr');
    tr.className = 'lib-row';
    tr.dataset.file = f.name;

    const title = f.meta?.title || f.stem || f.name;
    const artist = f.meta?.artist || '—';
    const genre = f.meta?.genre || '—';
    const year = f.meta?.year || '—';
    const format = f.format || '?';

    tr.innerHTML = `
      <td class="lib-cell-title"><span class="lib-title-text">${_esc(title)}</span></td>
      <td class="lib-cell-artist">${_esc(artist)}</td>
      <td class="lib-cell-genre"><span class="lib-badge lib-badge-genre">${_esc(genre)}</span></td>
      <td class="lib-cell-year">${_esc(String(year))}</td>
      <td class="lib-cell-format"><span class="lib-badge lib-badge-fmt">${_esc(format)}</span></td>
      <td class="lib-cell-actions">
        <button class="lib-btn-info" title="Song info" data-file="${_esc(f.name)}">ℹ</button>
        <button class="lib-btn-dl" title="Download ${_esc(f.name)}" data-file="${_esc(f.name)}">⬇</button>
      </td>
    `;

    tr.querySelector('.lib-cell-title').addEventListener('click', () => selectFile(f.name));

    tr.querySelector('.lib-btn-info').addEventListener('click', (e) => {
      e.stopPropagation();
      _showSongInfo(f);
    });

    tr.querySelector('.lib-btn-dl').addEventListener('click', async (e) => {
      e.stopPropagation();
      try {
        const { blob, filename } = await downloadFile(f.name);
        _downloadBlob(blob, filename);
      } catch (err) {
        console.error('Download error:', err);
      }
    });

    tbody.appendChild(tr);
  }

  document.querySelectorAll('#lib-table th.sortable').forEach(th => {
    const col = th.dataset.col;
    const arrow = th.querySelector('.sort-arrow');
    if (!arrow) return;
    if (col === _libSort.col) {
      arrow.textContent = _libSort.dir === 1 ? ' ▲' : ' ▼';
    } else {
      arrow.textContent = '';
    }
  });
}

function _esc(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
}

async function _showSongInfo(f) {
  const panel = $('#song-info-panel');
  const content = $('#song-info-content');
  if (!panel || !content) return;

  content.innerHTML = '<div class="song-info-loading">Loading…</div>';
  panel.classList.add('open');

  let meta = f.meta || {};
  try {
    const fetched = await fetchSongInfo(f.name);
    if (fetched) meta = fetched;
  } catch (_) {}

  const title = meta.title || f.stem || f.name;
  const rows = Object.entries(meta)
    .filter(([k]) => k !== 'filename' && k !== 'file' && k !== 'name')
    .map(([k, v]) => `<tr><th>${_esc(k)}</th><td>${_esc(String(v || '—'))}</td></tr>`)
    .join('');

  content.innerHTML = `
    <div class="song-info-title">${_esc(title)}</div>
    <table class="song-info-table">
      <tbody>${rows || '<tr><td colspan="2">No metadata available</td></tr>'}</tbody>
    </table>
    <div class="song-info-actions">
      <button class="tx-btn song-info-open-btn" data-file="${_esc(f.name)}">Open →</button>
      <button class="tx-btn song-info-dl-btn" data-file="${_esc(f.name)}">Download</button>
    </div>
  `;

  content.querySelector('.song-info-open-btn')?.addEventListener('click', () => {
    panel.classList.remove('open');
    selectFile(f.name);
  });
  content.querySelector('.song-info-dl-btn')?.addEventListener('click', async () => {
    try {
      const { blob, filename } = await downloadFile(f.name);
      _downloadBlob(blob, filename);
    } catch (err) { console.error(err); }
  });
}

// ── Track selector ──────────────────────────────────────────────────

async function selectFile(filename) {
  currentFile = filename;
  _notesCache.clear();
  _mutedSecondaryTracks.clear();

  try {
    const tracks = await fetchTracks(filename);
    currentTracks = tracks;
    if (!tracks.length) {
      // Stay on file selector and surface the error
      const libEmpty = $('#lib-empty');
      if (libEmpty) { libEmpty.style.display = ''; libEmpty.textContent = `No guitar tracks found in "${sanitize(filename)}".`; }
      return;
    }
    // Auto-select first track — skip the intermediate track-selector page
    await selectTrack(tracks[0].id, tracks[0].name);
    // Warm the server-side solve cache for every track × representation
    // mode while the user is reading the first one. Runs entirely in the
    // background; failures are silent (next interactive solve will retry).
    _prefetchAllTrackModes(filename, tracks);
  } catch (err) {
    const libEmpty = $('#lib-empty');
    if (libEmpty) { libEmpty.style.display = ''; libEmpty.textContent = `Error loading "${sanitize(filename)}": ${sanitize(err.message)}`; }
  }
}

const _PREFETCH_MODES = [
  MODES.STANDARD_TABLATURE,
  MODES.TABLATURE,
  MODES.STANDARD,
  MODES.TABLATURE_RHYTHM,
];
let _prefetchAbortToken = 0;

/**
 * Fire-and-forget solve requests for every (track × mode) combination so the
 * server-side LRU cache is warm by the time the user clicks anything. The
 * primary (foreground) solve has already been issued by selectTrack; we
 * deliberately re-issue the same call here so it short-circuits on the
 * server-side cache without doing any work.
 *
 * A token guards against stale prefetches when the user opens a new file
 * before the previous prefetch fan-out has finished.
 */
function _prefetchAllTrackModes(filename, tracks) {
  const myToken = ++_prefetchAbortToken;
  const prefs = getRulePreferences();
  // Order: every mode for the CURRENT track first, then every mode for the
  // other tracks. The first batch covers the most likely next click (mode
  // change on the visible track); subsequent batches warm the rest in the
  // background. No artificial throttle — browsers cap concurrent HTTP/1.1
  // requests per origin (~6), which acts as natural backpressure and lets
  // the foreground response come back first.
  const orderedTracks = [...tracks].sort((a, b) => {
    if (a.id === currentTrackId) return -1;
    if (b.id === currentTrackId) return 1;
    return 0;
  });
  for (const t of orderedTracks) {
    for (const mode of _PREFETCH_MODES) {
      if (myToken !== _prefetchAbortToken) return;
      fetchSolve(filename, t.id, mode, prefs).catch(() => { /* silent */ });
    }
  }
}

// ── Tab viewer ──────────────────────────────────────────────────────

function populateTrackSwitcher(_trackId) {
  // Track switching is now handled by the multi-track bar name clicks — no-op
}

async function selectTrack(trackId, trackName) {
  currentTrackId = trackId;
  // Stop playback when switching tracks
  if (playback && playback.isPlaying) {
    playback.pause();
    updatePlayButton(false);
    stopCursorLoop();
  }
  showPage('viewer');
  populateTrackSwitcher(trackId);

  const cleanTitle = currentFile.replace(/\.[^.]+$/, '');
  songTitle.textContent = cleanTitle;
  songArtist.textContent = trackName || `Track ${trackId}`;
  if (trackBadge) trackBadge.textContent = trackName || `Track ${trackId}`;
  if (metaMode) metaMode.textContent = 'PERFORMANCE';
  if (headerMetaTitle) headerMetaTitle.textContent = cleanTitle;
  if (headerMetaTrack) headerMetaTrack.textContent = trackName || `Track ${trackId}`;

  tabCanvas.width = 100;
  tabCanvas.height = 100;
  const ctx = tabCanvas.getContext('2d');
  ctx.fillStyle = '#aaa';
  ctx.font = '14px Arial';
  ctx.textAlign = 'center';
  ctx.fillText('Computing fingerings…', 50, 50);

  try {
    const representationMode = getSelectedRepresentationMode();
    const data = await fetchSolve(
      currentFile,
      trackId,
      representationMode,
      getRulePreferences(),
    );
    initRenderer(data);
    renderAuditBanner(data?.audit, {
      onMaskedMeasuresChange: () => _syncCoreSvgFingering(),
    });
  } catch (err) {
    ctx.clearRect(0, 0, tabCanvas.width, tabCanvas.height);
    ctx.fillStyle = '#ff5555';
    ctx.fillText(`Error: ${err.message}`, 200, 50);
  }
}

async function exportGP() {
  if (!currentFile) return;
  if (!currentFile.toLowerCase().endsWith('.gp')) {
    _setPdfExportStatus(
      'Export GP réservé aux fichiers GP 7/8 (.gp)', 'warn',
    );
    return;
  }
  const originalLabel = btnHeaderGp?.getAttribute('aria-label') || 'Export GP';
  if (btnHeaderGp) {
    btnHeaderGp.disabled = true;
    btnHeaderGp.setAttribute('aria-label', 'Export…');
  }
  _setPdfExportStatus('Export GP…', 'neutral');
  try {
    const { blob, filename, annotatedNotes } = await fetchExportGp(
      currentFile, currentTrackId,
    );
    _downloadBlob(blob, filename);
    _setPdfExportStatus(
      `Export GP OK (${annotatedNotes} doigtés écrits)`, 'ok',
    );
  } catch (err) {
    _setPdfExportStatus(`Export GP failed: ${err.message}`, 'error');
  } finally {
    if (btnHeaderGp) {
      btnHeaderGp.disabled = false;
      btnHeaderGp.setAttribute('aria-label', originalLabel);
    }
  }
}

async function exportPDF() {
  if (!renderer || !currentFile) return;

  const originalLabel = btnExportPdf?.textContent || '📄 PDF';
  if (btnExportPdf) {
    btnExportPdf.disabled = true;
    btnExportPdf.textContent = 'Export…';
  }
  _setPdfExportStatus('Exporting…', 'neutral');

  try {
    const representationMode = getSelectedRepresentationMode();
    const { blob, filename, conformanceIssues } = await fetchExportPdf(
      currentFile,
      currentTrackId,
      representationMode,
    );
    _downloadBlob(blob, filename);
    if (conformanceIssues > 0) {
      _setPdfExportStatus(`${conformanceIssues} conformance issue(s)`, 'warn');
    } else {
      _setPdfExportStatus('Export OK', 'ok');
    }
  } catch (err) {
    console.warn('API PDF export failed, falling back to local canvas export:', err);
    _setPdfExportStatus('API failed, using local fallback', 'warn');
    exportPDFLegacyCanvas();
  } finally {
    if (btnExportPdf) {
      btnExportPdf.disabled = false;
      btnExportPdf.textContent = originalLabel;
    }
  }
}

function _downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename || 'fretwise-export.pdf';
  document.body.appendChild(link);
  link.click();
  link.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30000);
}

function _setPdfExportStatus(message, level = 'neutral') {
  if (!pdfExportStatus) return;
  pdfExportStatus.textContent = message;
  if (level === 'ok') {
    pdfExportStatus.style.color = '#9be7a0';
    return;
  }
  if (level === 'warn') {
    pdfExportStatus.style.color = '#ffd180';
    return;
  }
  if (level === 'error') {
    pdfExportStatus.style.color = '#ef9a9a';
    return;
  }
  pdfExportStatus.style.color = 'rgba(255,255,255,0.75)';
}

function getSelectedRepresentationMode() {
  return selRepresentationMode?.value || DEFAULT_MODE;
}

function getRulePreferences() {
  return {
    sameFingerPenalty: prefSameFingerPenalty?.checked !== false,
    inferImplicitLegato: prefInferLegato?.checked !== false,
    showHandOverlay: prefHandOverlay?.checked !== false,
  };
}

function _representationModeLabel(mode) {
  return (MODE_LABELS[mode] || MODE_LABELS[DEFAULT_MODE]).toUpperCase();
}

function applyRepresentationModeView(data) {
  const representationMode = data?.representation_mode || getSelectedRepresentationMode();
  if (selRepresentationMode && selRepresentationMode.value !== representationMode) {
    selRepresentationMode.value = representationMode;
  }
  if (metaViewMode) {
    metaViewMode.textContent = _representationModeLabel(representationMode);
  }

  const showCore = representationMode !== MODES.TABLATURE;
  if (tabCanvas) tabCanvas.style.visibility = showCore ? 'hidden' : 'visible';
  if (cursorCanvas) cursorCanvas.style.visibility = showCore ? 'hidden' : 'visible';
  if (coreSvgView) {
    coreSvgView.style.display = showCore ? 'block' : 'none';
    coreSvgView.innerHTML = showCore && data?.core_svg ? data.core_svg : '';
    if (showCore) {
      _applyResponsiveCoreSvg();
      _syncCoreSvgFingering();
      _syncCoreSvgAnnotations();
      _syncCoreSvgHandOverlay();
    }
  }
}

function _fingerGlyph(finger) {
  return {
    index: 'i',
    middle: 'm',
    ring: 'r',
    pinky: 'p',
  }[String(finger || '').toLowerCase()] || '';
}

function _buildResultByOnsetString(results) {
  const map = new Map();
  for (const note of (results || [])) {
    const onset = Number.parseFloat(note?.onset);
    const tabString = Number.parseInt(note?.string, 10);
    if (!Number.isFinite(onset) || !Number.isInteger(tabString)) continue;
    const key = `${onset.toFixed(6)}:${tabString}`;
    if (!map.has(key)) map.set(key, note);
  }
  return map;
}

function _syncCoreSvgFingering() {
  if (!coreSvgView || !renderer) return;
  const svg = coreSvgView.querySelector('svg');
  if (!svg) return;

  // Clear previous finger classes from all masks
  const FINGER_CLASSES = ['fw-finger-1', 'fw-finger-2', 'fw-finger-3', 'fw-finger-4'];
  svg.querySelectorAll('.fw-tab-note-mask').forEach((rect) => {
    rect.classList.remove(...FINGER_CLASSES);
  });

  if (!renderer.showFingering) return;

  const fingerClassMap = {
    index:  'fw-finger-1',
    middle: 'fw-finger-2',
    ring:   'fw-finger-3',
    pinky:  'fw-finger-4',
  };

  const byOnsetString = _buildResultByOnsetString(renderer.data?.results || []);
  const masked = getMaskedMeasures();  // 1-based measure indices to hide
  const tabNotes = svg.querySelectorAll('text.fw-tab-note');
  for (const noteText of tabNotes) {
    const onset = Number.parseFloat(noteText.getAttribute('data-onset') || '');
    const tabString = Number.parseInt(noteText.getAttribute('data-tab-string') || '', 10);
    if (!Number.isFinite(onset) || !Number.isInteger(tabString)) continue;

    const resultNote = byOnsetString.get(`${onset.toFixed(6)}:${tabString}`);
    if (!resultNote || Number.parseInt(resultNote.fret, 10) <= 0) continue;

    // Audit masking: skip the finger class for notes in flagged movements
    // (user can override via the per-movement checkbox in the audit banner).
    if (masked.size > 0 && resultNote.measure_index != null
        && masked.has(resultNote.measure_index)) {
      continue;
    }

    const fc = fingerClassMap[resultNote.finger];
    if (!fc) continue;

    // The mask rect is the element immediately before the note text in the SVG
    const maskRect = noteText.previousElementSibling;
    if (maskRect && maskRect.classList.contains('fw-tab-note-mask')) {
      maskRect.classList.add(fc);
    }
  }
}

function _clusterSorted(values, epsilon = 1.0) {
  const sorted = Array.from(values).sort((a, b) => a - b);
  const out = [];
  for (const v of sorted) {
    const prev = out[out.length - 1];
    if (!prev || Math.abs(v - prev) > epsilon) out.push(v);
  }
  return out;
}

/** Inject technique & expression annotations into the SVG TAB view. */
function _syncCoreSvgAnnotations() {
  if (!coreSvgView || !renderer) return;
  const svg = coreSvgView.querySelector('svg');
  if (!svg) return;

  svg.querySelectorAll('.fw-svg-annotation').forEach((el) => el.remove());

  const NS = 'http://www.w3.org/2000/svg';
  const mk = (tag) => document.createElementNS(NS, tag);
  const push = (el) => { el.classList.add('fw-svg-annotation'); svg.appendChild(el); return el; };

  const byOnsetString = _buildResultByOnsetString(renderer.data?.results || []);
  const tabNotes = Array.from(svg.querySelectorAll('text.fw-tab-note'));
  if (!tabNotes.length) return;

  // Build onset→y map for string 6 (lowest) — used to place dynamics below the staff
  const str6YByOnset = new Map();
  for (const el of tabNotes) {
    if (parseInt(el.getAttribute('data-tab-string') || '', 10) !== 6) continue;
    const onset = Number.parseFloat(el.getAttribute('data-onset') || '');
    const y     = Number.parseFloat(el.getAttribute('y') || '');
    if (Number.isFinite(onset) && Number.isFinite(y))
      str6YByOnset.set(onset.toFixed(6), y);
  }

  // Process in onset order so dynamic tracking works correctly
  const sorted = tabNotes.slice().sort((a, b) =>
    Number.parseFloat(a.getAttribute('data-onset') || '0') -
    Number.parseFloat(b.getAttribute('data-onset') || '0')
  );

  let lastDynamic = '';
  const dynShown = new Set(); // one dynamic per onset column

  for (const noteText of sorted) {
    const onset     = Number.parseFloat(noteText.getAttribute('data-onset') || '');
    const tabString = Number.parseInt(noteText.getAttribute('data-tab-string') || '', 10);
    if (!Number.isFinite(onset) || !Number.isInteger(tabString)) continue;

    const r = byOnsetString.get(`${onset.toFixed(6)}:${tabString}`);
    if (!r) continue;

    const x  = Number.parseFloat(noteText.getAttribute('x') || '0');
    const y  = Number.parseFloat(noteText.getAttribute('y') || '0');
    if (!Number.isFinite(x) || !Number.isFinite(y)) continue;

    const ok = Number.parseInt(r.fret, 10);

    // ── Dynamic (once per onset, on string-6 column, only on change)
    const dynKey = onset.toFixed(6);
    if (r.dynamic && !dynShown.has(dynKey) && r.dynamic !== lastDynamic) {
      const baseY = str6YByOnset.get(dynKey);
      if (Number.isFinite(baseY)) {
        lastDynamic = r.dynamic;
        dynShown.add(dynKey);
        const t = mk('text');
        t.setAttribute('x', x.toFixed(2));
        t.setAttribute('y', (baseY + 14).toFixed(2));
        t.setAttribute('font-family', '"Fraunces", Georgia, serif');
        t.setAttribute('font-size', '8');
        t.setAttribute('font-style', 'italic');
        t.setAttribute('font-weight', '700');
        t.setAttribute('fill', '#666655');
        t.setAttribute('text-anchor', 'middle');
        t.textContent = r.dynamic;
        push(t);
      }
    }

    if (ok <= 0) continue; // open strings skip technique labels

    // ── Hammer-on / Pull-off label
    if (r.articulation === 'hammer_on' || r.articulation === 'pull_off') {
      const t = mk('text');
      t.setAttribute('x', x.toFixed(2));
      t.setAttribute('y', (y - 7).toFixed(2));
      t.setAttribute('font-family', 'Inter, sans-serif');
      t.setAttribute('font-size', '6');
      t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#666655');
      t.setAttribute('text-anchor', 'middle');
      t.textContent = r.articulation === 'hammer_on' ? 'H' : 'P';
      push(t);
    }

    // ── Bend arrow + amount
    if (r.bend_value) {
      const semis = Number(r.bend_value);
      const label = semis === 0.5 ? '½' : semis === 1.5 ? '1½' : semis === 2.5 ? '2½' : String(semis);
      const arr = mk('text');
      arr.setAttribute('x', (x + 2).toFixed(2));
      arr.setAttribute('y', (y - 5).toFixed(2));
      arr.setAttribute('font-size', '8');
      arr.setAttribute('fill', '#c0392b');
      arr.setAttribute('text-anchor', 'middle');
      arr.textContent = '↑';
      push(arr);
      if (label) {
        const t = mk('text');
        t.setAttribute('x', (x + 6).toFixed(2));
        t.setAttribute('y', (y - 11).toFixed(2));
        t.setAttribute('font-family', 'Inter, sans-serif');
        t.setAttribute('font-size', '5.5');
        t.setAttribute('font-weight', '700');
        t.setAttribute('fill', '#c0392b');
        t.setAttribute('text-anchor', 'middle');
        t.textContent = label;
        push(t);
      }
    }

    // ── Vibrato ~
    if (r.articulation === 'vibrato' || r.articulation === 'wide_vibrato' || r.vibrato_wide) {
      const t = mk('text');
      t.setAttribute('x', (x + 7).toFixed(2));
      t.setAttribute('y', (y - 5).toFixed(2));
      t.setAttribute('font-size', '9');
      t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#2a8a2a');
      t.setAttribute('text-anchor', 'start');
      t.textContent = r.articulation === 'wide_vibrato' || r.vibrato_wide ? '≈' : '~';
      push(t);
    }

    // ── Tapping T
    if (r.tapping) {
      const t = mk('text');
      t.setAttribute('x', x.toFixed(2));
      t.setAttribute('y', (y - 8).toFixed(2));
      t.setAttribute('font-family', 'Inter, sans-serif');
      t.setAttribute('font-size', '6.5');
      t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#1a45aa');
      t.setAttribute('text-anchor', 'middle');
      t.textContent = 'T';
      push(t);
    }

    // ── Accent > / ∧
    if (r.accent_strong) {
      const t = mk('text');
      t.setAttribute('x', x.toFixed(2));
      t.setAttribute('y', (y - 8).toFixed(2));
      t.setAttribute('font-size', '8'); t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#c0392b'); t.setAttribute('text-anchor', 'middle');
      t.textContent = '∧';
      push(t);
    } else if (r.accent) {
      const t = mk('text');
      t.setAttribute('x', x.toFixed(2));
      t.setAttribute('y', (y - 8).toFixed(2));
      t.setAttribute('font-size', '8'); t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#c0392b'); t.setAttribute('text-anchor', 'middle');
      t.textContent = '>';
      push(t);
    }
  }
}

function _syncCoreSvgHandOverlay() {
  if (!coreSvgView || !renderer) return;
  const svg = coreSvgView.querySelector('svg');
  if (!svg) return;

  svg.querySelectorAll('.fw-hand-annotation').forEach((el) => el.remove());
  const prefs = getRulePreferences();
  if (!prefs.showHandOverlay) return;

  const byOnsetString = _buildResultByOnsetString(renderer.data?.results || []);
  const tabNotes = Array.from(svg.querySelectorAll('text.fw-tab-note'));
  if (!tabNotes.length) return;

  const laneSeeds = _clusterSorted(
    tabNotes
      .filter((el) => parseInt(el.getAttribute('data-tab-string') || '', 10) === 6)
      .map((el) => Number.parseFloat(el.getAttribute('y') || '0'))
      .filter((v) => Number.isFinite(v)),
    1.4,
  );
  if (!laneSeeds.length) {
    const yMax = Math.max(...tabNotes.map((el) => Number.parseFloat(el.getAttribute('y') || '0')));
    if (Number.isFinite(yMax)) laneSeeds.push(yMax);
  }
  if (!laneSeeds.length) return;

  const onsetEntries = new Map();
  
  for (const noteText of tabNotes) {
    const onset = Number.parseFloat(noteText.getAttribute('data-onset') || '');
    const tabString = Number.parseInt(noteText.getAttribute('data-tab-string') || '', 10);
    const x = Number.parseFloat(noteText.getAttribute('x') || '0');
    const y = Number.parseFloat(noteText.getAttribute('y') || '0');
    if (!Number.isFinite(onset) || !Number.isFinite(x) || !Number.isFinite(y) || !Number.isInteger(tabString)) {
      continue;
    }
    const resultNote = byOnsetString.get(`${onset.toFixed(6)}:${tabString}`);
    if (!resultNote || !Number.isFinite(Number(resultNote.hand_position))) continue;

    let laneIdx = 0;
    let laneDist = Infinity;
    for (let i = 0; i < laneSeeds.length; i += 1) {
      const d = Math.abs(y - laneSeeds[i]);
      if (d < laneDist) {
        laneDist = d;
        laneIdx = i;
      }
    }

    const onsetKey = onset.toFixed(6);
    const existing = onsetEntries.get(onsetKey);
    if (!existing || x < existing.x) {
      onsetEntries.set(onsetKey, {
        onset,
        x,
        laneIdx,
        handPosition: Number(resultNote.hand_position),
        measureIndex: resultNote.measure_index,
      });
    }
  }

  const onsets = Array.from(onsetEntries.values()).sort((a, b) => a.onset - b.onset || a.x - b.x);

  const MIN_SPACING = 38.0;
  let globalPrevHand = null;
  const lastAnnotXByLane = new Map();
  const lastMeasureByLane = new Map();
  const seenLanes = new Set();

  for (const entry of onsets) {
    const laneIdx = entry.laneIdx;
    const laneBaseY = laneSeeds[Math.min(laneIdx, laneSeeds.length - 1)] + 12.0;
    const isNewLane = !seenLanes.has(laneIdx);
    const handChanged = globalPrevHand !== null && globalPrevHand !== entry.handPosition;

    let displayLabel = null;
    let isChange = false;

    if (isNewLane) {
      // First note on this visual row — always show, with arrow if position changed
      if (handChanged) {
        const arrow = globalPrevHand < entry.handPosition ? '→' : '←';
        displayLabel = arrow + 'P' + entry.handPosition;
        isChange = true;
      } else {
        displayLabel = 'P' + entry.handPosition;
      }
    } else if (handChanged) {
      // Position changed mid-lane
      const arrow = globalPrevHand < entry.handPosition ? '→' : '←';
      displayLabel = arrow + 'P' + entry.handPosition;
      isChange = true;
    } else if (Number.isFinite(entry.measureIndex)) {
      // Measure-boundary reminder when position is unchanged
      const prevMeasure = lastMeasureByLane.get(laneIdx);
      const isFirstOfMeasure = prevMeasure == null || entry.measureIndex !== prevMeasure;
      if (isFirstOfMeasure) {
        const lastAnnotX = lastAnnotXByLane.get(laneIdx);
        if (lastAnnotX == null || entry.x - lastAnnotX >= MIN_SPACING) {
          displayLabel = 'P' + entry.handPosition;
        }
      }
    }

    // Always update tracking state, even when not rendering
    seenLanes.add(laneIdx);
    globalPrevHand = entry.handPosition;
    if (Number.isFinite(entry.measureIndex)) {
      lastMeasureByLane.set(laneIdx, entry.measureIndex);
    }

    if (displayLabel === null) continue;

    const textEl = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    textEl.setAttribute('class', 'fw-hand-annotation');
    textEl.setAttribute('x', entry.x.toFixed(2));
    textEl.setAttribute('y', laneBaseY.toFixed(2));
    textEl.setAttribute('font-family', 'Arial,sans-serif');
    textEl.setAttribute('font-size', isChange ? '6.2' : '5.8');
    textEl.setAttribute('font-weight', isChange ? '700' : '600');
    textEl.setAttribute('fill', isChange ? '#c0392b' : '#546e7a');
    textEl.setAttribute('text-anchor', 'middle');
    textEl.setAttribute('dominant-baseline', 'hanging');
    textEl.textContent = displayLabel;
    svg.appendChild(textEl);

    lastAnnotXByLane.set(laneIdx, entry.x);
  }
}

function _applyResponsiveCoreSvg() {
  if (!coreSvgView) return;
  const svg = coreSvgView.querySelector('svg');
  if (!svg) return;
  svg.setAttribute('preserveAspectRatio', 'xMinYMin meet');
  svg.removeAttribute('width');
  svg.removeAttribute('height');
  svg.style.display = 'block';
  svg.style.width = '100%';
  svg.style.maxWidth = '100%';
  svg.style.height = 'auto';
}

function exportPDFLegacyCanvas() {
  if (!tabCanvas || !renderer) return;

  const savedCursor = renderer.cursorMeasure;
  renderer.cursorMeasure = -1;
  renderer.render();

  const w = renderer.systemWidth;
  const h = renderer.totalHeight;
  const artist = songArtist.textContent.trim();
  const title = songTitle.textContent.trim();
  const titleHeight = artist ? 56 : 38;

  const printCanvas = document.createElement('canvas');
  printCanvas.width = Math.round(w);
  printCanvas.height = Math.round(h) + titleHeight;
  const ctx = printCanvas.getContext('2d');

  ctx.fillStyle = '#ffffff';
  ctx.fillRect(0, 0, printCanvas.width, titleHeight);

  ctx.fillStyle = '#000000';
  ctx.textAlign = 'center';
  ctx.font = 'bold 22px sans-serif';
  ctx.fillText(title, printCanvas.width / 2, 26);

  if (artist) {
    ctx.font = '14px sans-serif';
    ctx.fillStyle = '#555555';
    ctx.fillText(artist, printCanvas.width / 2, 46);
  }

  ctx.drawImage(
    tabCanvas,
    0,
    0,
    tabCanvas.width,
    tabCanvas.height,
    0,
    titleHeight,
    Math.round(w),
    Math.round(h),
  );

  renderer.cursorMeasure = savedCursor;
  renderer.render();

  const imgDataUrl = printCanvas.toDataURL('image/png');
  const safeTitle = artist ? `${title} — ${artist}` : title;

  const html = `<!DOCTYPE html><html><head>
<meta charset="utf-8"><title>${sanitize(safeTitle)}</title>
<style>
  * { margin:0; padding:0; }
  body { background:#fff; }
  img  { width:100%; display:block; }
  @page { margin:0; size:auto; }
</style>
</head><body>
<img src="${imgDataUrl}">
</body></html>`;

  const blobUrl = URL.createObjectURL(new Blob([html], { type: 'text/html' }));
  const iframe = document.createElement('iframe');
  iframe.style.cssText =
    'position:fixed;top:-9999px;left:-9999px;width:1px;height:1px;border:0;';
  document.body.appendChild(iframe);

  iframe.onload = () => {
    try {
      iframe.contentWindow.focus();
      iframe.contentWindow.print();
    } catch (_e) {
      window.open(blobUrl, '_blank');
    }
    setTimeout(() => {
      if (iframe.parentNode) iframe.parentNode.removeChild(iframe);
      URL.revokeObjectURL(blobUrl);
    }, 30000);
  };

  iframe.src = blobUrl;
}

function initRenderer(data) {
  // Reset loop state
  loopASet = false;
  if (btnLoopA)     btnLoopA.classList.remove('active');
  if (btnLoopB)     btnLoopB.classList.remove('active');
  if (btnLoopClear) btnLoopClear.classList.remove('loop-active');

  // Update title/artist from API response
  if (data.title) { songTitle.textContent = data.title; if (headerMetaTitle) headerMetaTitle.textContent = data.title; }
  if (data.artist) { songArtist.textContent = data.artist; if (headerMetaTrack) headerMetaTrack.textContent = data.artist; }
  const tempoStr = `♩ = ${Math.round(data.tempo || 120)}`;
  if (metaTempo) metaTempo.textContent = tempoStr;
  if (headerMetaTempo) headerMetaTempo.textContent = tempoStr;
  if (bpmInput) bpmInput.value = Math.round(data.tempo || 120);
  if (metaMode) metaMode.textContent = 'PERFORMANCE';

  renderer = new TabRenderer(tabCanvas, data);
  renderer.render();
  // Notify the floating hand-viz panel that fresh fingering data is ready.
  window.dispatchEvent(new CustomEvent('fretwise:renderer-ready'));
  // Audio is always enabled; the multi-track bar handles per-track muting
  soundOn = true;
  if (btnFingering) {
    btnFingering.classList.toggle('active', renderer.showFingering);
  }
  applyRepresentationModeView(data);

  // Populate chord strip from chord diagrams
  _chordDataMap = {};
  const bar   = $('#chord-bar');
  const strip = $('#chord-strip');
  if (bar && strip) {
    if (data.chord_diagrams?.length) {
      strip.innerHTML = '';
      for (const cd of data.chord_diagrams) {
        _chordDataMap[cd.name] = cd;
        const el = document.createElement('div');
        el.className = 'chord-diagram-item';
        el.setAttribute('data-chord', cd.name);
        el.innerHTML = chordDiagramSVG(cd);
        el.addEventListener('click', (ev) => {
          ev.stopPropagation();
          showChordPopup(cd.name, ev.clientX, ev.clientY);
        });
        strip.appendChild(el);
      }
      bar.style.display = '';
    } else {
      bar.style.display = 'none';
    }
  }

  // Playback engine
  // Stop and release any existing playback engine
  if (playback) {
    try { playback.pause(); } catch (_) {}
    try { playback.disableAudio(); } catch (_) {}
    playback = null;
  }
  updatePlayButton(false);
  stopCursorLoop();
  playback = new PlaybackEngine(renderer, {
    tempo: data.tempo || 120,
    beatsPerMeasure: data.beats_per_measure || 4,
  });
  // Set GM MIDI program (SpessaSynth) and infer MusyngKite instrument (fallback)
  playback.setMidiProgram(data.midi_program ?? -1);
  playback.setInstrument(data.track_name || '');
  playback.onMeasureChange = (_m) => {};
  playback.onStop = () => {
    updatePlayButton(false);
    stopCursorLoop();
    _postHandVizTime();
  };
  // Feed the floating hand-viz panel with the current playhead time on every
  // tick (sub-measure precision). Cheap: it is just one postMessage / frame.
  playback.onTimeChange = (sec) => {
    if (tcCurrent) tcCurrent.textContent = _fmtTime(sec);
    if (handVizPanel && handVizPanel.style.display !== 'none') _postHandVizTime();
  };
  // Enable audio immediately (muting is handled per-track in the multi-track bar)
  playback.enableAudio();

  // Wire position scrubber
  playback.onPositionChange = (frac) => {
    const pb = $('#position-bar input');
    if (pb) pb.value = Math.round(frac * 1000);
  };

  // Canvas click: chord label → inline popup, else measure jump
  tabCanvas.onclick = (e) => {
    const rect = tabCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    const chordName = renderer.getChordNameAtPoint(x, y);
    if (chordName) {
      e.stopPropagation();
      showChordPopup(chordName, e.clientX, e.clientY);
      return;
    }
    hideChordPopup();
    const m = renderer.getMeasureAtPoint(x, y);
    if (m >= 0 && playback) {
      // If playing and user clicks elsewhere: stop following, jump there
      if (playback.isPlaying) {
        _followPlayhead = false;
        _updateFollowButton();
      }
      playback.goToMeasure(m);
    }
  };

  // Canvas mousemove: show pointer cursor over chord label zones
  tabCanvas.addEventListener('mousemove', (e) => {
    if (!renderer) return;
    const rect = tabCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    tabCanvas.style.cursor = renderer.getChordNameAtPoint(x, y) ? 'pointer' : 'default';
  });

  // SVG cursor driver for standard / standard+tab modes
  _svgDriver = null;
  const _svgMode = data.representation_mode || getSelectedRepresentationMode();
  if (_svgMode !== MODES.TABLATURE && data.measure_regions?.length && coreSvgView) {
    _svgDriver = new SvgCursorDriver(coreSvgView, data);
    _svgDriver.init();
    playback.onMeasureChange = (m) => {
      _svgDriver.highlight(m, playback.loopStart, playback.loopEnd);
    };
    coreSvgView.onclick = (e) => {
      const chordEl = e.target.closest('[data-chord]');
      if (chordEl) {
        const chordName = chordEl.getAttribute('data-chord');
        if (chordName) {
          e.stopPropagation();
          showChordPopup(chordName, e.clientX, e.clientY);
          return;
        }
      }
      hideChordPopup();
      const m = _svgDriver.measureAtClick(e);
      if (m >= 0) {
        if (playback?.isPlaying) {
          _followPlayhead = false;
          _updateFollowButton();
        }
        playback.goToMeasure(m);
      }
    };
  } else {
    if (coreSvgView) coreSvgView.onclick = null;
  }

  // Speed
  if (selSpeed) {
    selSpeed.value = '100';
    selSpeed.onchange = () => {
      const s = parseInt(selSpeed.value, 10) / 100;
      playback.setSpeed(s);
    };
  }

  if (bpmInput) {
    bpmInput.onchange = () => {
      const bpm = Math.max(20, Math.min(300, parseInt(bpmInput.value, 10) || 120));
      bpmInput.value = bpm;
      if (playback) playback.tempo = bpm;
      if (renderer) { renderer.tempo = bpm; renderer.render(); }
      if (metaTempo) metaTempo.textContent = `♩ = ${bpm}`;
    };
    bpmInput.onkeydown = (e) => { if (e.key === 'Enter') bpmInput.onchange(); };
  }

  _rebuildMultiTrackBar(currentTrackId);
  _rebuildTrackTabs(currentTrackId);
  _restoreSecondaryTracks(currentTrackId); // re-enable previously active secondary tracks
  updatePlayButton(false);
  _followPlayhead = true;
  _updateFollowButton();
}

// ── Track tabs bar ──────────────────────────────────────────────────

const _TRACK_COLORS = [
  'oklch(0.74 0.14 30)',   // coral
  'oklch(0.76 0.14 245)',  // blue
  'oklch(0.78 0.14 130)',  // green
  'oklch(0.78 0.14 320)',  // magenta
  'oklch(0.82 0.15 75)',   // amber
  'oklch(0.74 0.14 190)',  // teal
];

/** Convert MIDI note array to tuning string (e.g. [40,45,50,55,59,64] → "EADGBE"). */
function _tuningLabel(tuning) {
  if (!tuning || !tuning.length) return '';
  const NAMES = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B'];
  return tuning.map(n => NAMES[n % 12]).join('');
}

function _rebuildTrackTabs(primaryTrackId) {
  const bar = $('#track-tabs-bar');
  if (!bar) return;
  bar.innerHTML = '';
  if (!currentTracks || !currentTracks.length) return;

  for (let i = 0; i < currentTracks.length; i++) {
    const t = currentTracks[i];
    const isPrimary = t.id === primaryTrackId;
    const muted = _mutedSecondaryTracks.get(primaryTrackId) ?? new Set();
    const isMuted = !isPrimary && muted.has(t.id);
    const color = _TRACK_COLORS[i % _TRACK_COLORS.length];
    const label = sanitize(t.name || `Track ${t.id}`);
    const tuning = _tuningLabel(t.tuning);
    const metaText = tuning ? `${tuning} · ${t.id}` : `Track ${t.id}`;

    const tab = document.createElement('div');
    tab.className = 'track-tab';
    tab.dataset.active = isPrimary ? '1' : '0';
    tab.dataset.trackId = t.id;

    const colorBar = document.createElement('div');
    colorBar.className = 'track-tab-color';
    colorBar.style.background = color;

    const body = document.createElement('div');
    body.className = 'track-tab-body';
    body.innerHTML = `<div class="track-tab-name">${label}</div><div class="track-tab-meta">${metaText}</div>`;

    // Instrument picker button
    const instrBtn = document.createElement('button');
    instrBtn.className = 'instr-picker-btn';
    instrBtn.textContent = '🎵';
    const storedProgram = _getStoredInstrument(currentFile || '', t.id);
    instrBtn.title = storedProgram !== null
      ? `Instrument: GM ${storedProgram} (click to change)`
      : 'Select instrument (click to change)';
    instrBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      // Channel 0 = primary, secondary channels start at 1
      const chIdx = isPrimary ? 0 : Math.min(15,
        currentTracks.filter(x => x.id !== primaryTrackId).findIndex(x => x.id === t.id) + 1
      );
      _openInstrumentPicker(instrBtn, currentFile || '', t.id, chIdx);
    });

    tab.appendChild(colorBar);
    tab.appendChild(body);
    tab.appendChild(instrBtn);

    // Mute button (secondary tracks only)
    if (!isPrimary) {
      const muteBtn = document.createElement('button');
      muteBtn.className = 'track-mute-btn';
      muteBtn.textContent = 'M';
      muteBtn.dataset.muted = isMuted ? '1' : '0';
      muteBtn.title = isMuted ? `Unmute ${label}` : `Mute ${label}`;
      muteBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const oldBtn = _multiTrackBar ? _multiTrackBar.querySelector(`[data-track-id="${t.id}"]`) : null;
        _toggleSecondaryTrack(t.id, t.name || '', oldBtn || muteBtn).then(() => {
          _rebuildTrackTabs(primaryTrackId);
        });
      });
      tab.appendChild(muteBtn);

      // Click tab name to switch primary
      tab.addEventListener('click', () => selectTrack(t.id, t.name || ''));
    }

    bar.appendChild(tab);
  }
}

// ── Multi-track audio mixer ─────────────────────────────────────────

const _multiTrackBar = $('#multi-track-bar');
const _tabContainer  = $('#tab-container');

function _rebuildMultiTrackBar(primaryTrackId) {
  if (!_multiTrackBar) return;
  if (!currentTracks || currentTracks.length <= 1) {
    _multiTrackBar.style.display = 'none';
    document.body.classList.remove('has-multitrack-bar');
    return;
  }
  _multiTrackBar.style.display = '';
  document.body.classList.add('has-multitrack-bar');
  _multiTrackBar.innerHTML = '<span class="mt-label">🏛 Pistes :</span>';
  const muted = _mutedSecondaryTracks.get(primaryTrackId) ?? new Set();
  for (const t of currentTracks) {
    const isPrimary = t.id === primaryTrackId;
    const isMuted   = !isPrimary && muted.has(t.id);
    const icon = isPrimary ? '▶' : isMuted ? '🔇' : '🔈';
    const label = sanitize(t.name || `Piste ${t.id}`);

    const btn = document.createElement('button');
    btn.className = 'mt-track-btn' +
      (isPrimary ? ' mt-primary' : '') +
      (!isPrimary && !isMuted ? ' mt-active' : '');
    btn.dataset.trackId = t.id;
    btn.title = isPrimary
      ? `Piste principale : ${label}`
      : (isMuted ? `Activer ${label}` : `Muter ${label}`) + ` — cliquer le nom pour basculer la vue`;

    // Icon span: click = mute/unmute (secondary only)
    const iconSpan = document.createElement('span');
    iconSpan.className = 'mt-icon';
    iconSpan.textContent = icon;
    if (!isPrimary) {
      iconSpan.title = isMuted ? `Activer ${label}` : `Muter ${label}`;
      iconSpan.addEventListener('click', (e) => {
        e.stopPropagation();
        _toggleSecondaryTrack(t.id, t.name || '', btn);
      });
    }

    // Name span: click = switch primary track
    const nameSpan = document.createElement('span');
    nameSpan.className = 'mt-name';
    nameSpan.textContent = label;
    if (!isPrimary) {
      nameSpan.title = `Basculer la vue sur ${label}`;
      nameSpan.addEventListener('click', (e) => {
        e.stopPropagation();
        selectTrack(t.id, t.name || '');
      });
    }

    btn.appendChild(iconSpan);
    btn.appendChild(nameSpan);
    _multiTrackBar.appendChild(btn);
  }
}

async function _toggleSecondaryTrack(trackId, trackName, btn) {
  if (!playback) return;
  const isMuted = !playback._secondaryChannels.some(c => c.trackId === trackId);
  const iconSpan = btn.querySelector('.mt-icon');
  if (!isMuted) {
    // Currently playing → mute it
    playback.removeSecondaryChannel(trackId);
    if (!_mutedSecondaryTracks.has(currentTrackId)) _mutedSecondaryTracks.set(currentTrackId, new Set());
    _mutedSecondaryTracks.get(currentTrackId).add(trackId);
    btn.className = 'mt-track-btn';
    if (iconSpan) { iconSpan.textContent = '🔇'; iconSpan.title = `Activer ${sanitize(trackName)}`; }
    return;
  }
  // Currently muted → unmute
  if (iconSpan) iconSpan.textContent = '⏳';
  btn.disabled = true;
  try {
    const cacheKey = `${currentFile}#${trackId}`;
    let notesData = _notesCache.get(cacheKey);
    if (!notesData) {
      notesData = await fetchNotes(
        currentFile,
        trackId,
        getRulePreferences(),
      );
      _notesCache.set(cacheKey, notesData);
    }
    playback.addSecondaryChannel(trackId, trackName, notesData.results, notesData.beats_per_measure, notesData.midi_program);
    _mutedSecondaryTracks.get(currentTrackId)?.delete(trackId);
    btn.className = 'mt-track-btn mt-active';
    if (iconSpan) { iconSpan.textContent = '🔈'; iconSpan.title = `Muter ${sanitize(trackName)}`; }
  } catch (err) {
    console.error('[FretWise] secondary track load failed:', err);
    if (iconSpan) iconSpan.textContent = '❌';
    setTimeout(() => { if (iconSpan) { iconSpan.textContent = '🔇'; iconSpan.title = `Activer ${sanitize(trackName)}`; } }, 2000);
  } finally {
    btn.disabled = false;
  }
}

/** Activate all secondary tracks that are not explicitly muted for this primary track. */
async function _restoreSecondaryTracks(primaryTrackId) {
  const muted = _mutedSecondaryTracks.get(primaryTrackId) ?? new Set();
  for (const t of currentTracks) {
    if (t.id === primaryTrackId) continue;
    if (muted.has(t.id)) continue;
    const btn = _multiTrackBar?.querySelector(`[data-track-id="${t.id}"]`);
    if (btn) await _toggleSecondaryTrack(t.id, t.name || '', btn);
  }
}

// ── Toolbar wiring ──────────────────────────────────────────────────

function updatePlayButton(playing) {
  if (btnPlay) {
    btnPlay.textContent = playing ? '⏸' : '▶';
    btnPlay.title = playing ? 'Pause' : 'Play';
  }
}

function _updateFollowButton() {
  if (!btnFollow) return;
  btnFollow.classList.toggle('active', _followPlayhead);
  btnFollow.title = _followPlayhead
    ? 'Following playhead (click to explore freely)'
    : 'Click to follow playhead again';
}

if (btnFollow) {
  btnFollow.addEventListener('click', () => {
    _followPlayhead = true;
    _updateFollowButton();
    // Immediately scroll to current playhead position
    if (playback && renderer) {
      const m = renderer.cursorMeasure || 0;
      const sys = renderer.systems?.find(
        s => m >= s.startMeasure && m < s.startMeasure + s.measures.length
      );
      if (sys) {
        const container = tabCanvas.parentElement;
        if (container) {
          const sysIdx = renderer.systems.indexOf(sys);
          const SYSTEM_H = 200, INTER_SYSTEM = 16, MARGIN_T = 12;
          const sysY = MARGIN_T + sysIdx * (SYSTEM_H + INTER_SYSTEM);
          container.scrollTo({ top: Math.max(0, sysY - container.offsetHeight / 2 + SYSTEM_H / 2), behavior: 'smooth' });
        }
        _autoScrollTarget = null;
      }
    }
  });
}

if (btnDownloadGp) {
  btnDownloadGp.addEventListener('click', async () => {
    if (!currentFile) return;
    try {
      const { blob, filename } = await downloadFile(currentFile);
      _downloadBlob(blob, filename);
    } catch (err) {
      console.error('Download failed:', err);
    }
  });
}

if (btnPlay) {
  btnPlay.addEventListener('click', () => {
    if (!playback) return;
    if (!playback.isPlaying) {
      _followPlayhead = true;  // resume following when starting play
      _updateFollowButton();
    }
    playback.toggle();
    updatePlayButton(playback.isPlaying);
    if (playback.isPlaying) startCursorLoop();
    else stopCursorLoop();
  });
}

if (btnPrev) {
  btnPrev.addEventListener('click', () => {
    if (playback) playback.prev();
  });
}

if (btnNext) {
  btnNext.addEventListener('click', () => {
    if (playback) playback.next();
  });
}

if (btnLoopA) {
  btnLoopA.addEventListener('click', () => {
    if (!playback || !renderer) return;
    const m = renderer.cursorMeasure ?? 0;
    playback.setLoopStart(m);
    loopASet = true;
    btnLoopA.classList.add('active');
    btnLoopA.title = `Loop start: measure ${m + 1}`;
  });
}

if (btnLoopB) {
  btnLoopB.addEventListener('click', () => {
    if (!playback || !renderer) return;
    const m = renderer.cursorMeasure ?? (renderer.measures.length - 1);
    playback.setLoopEnd(m);
    btnLoopB.classList.add('active');
    btnLoopB.title = `Loop end: measure ${m + 1}`;
    // Highlight the loop button when A→B is fully set
    if (loopASet && btnLoopClear) btnLoopClear.classList.add('loop-active');
  });
}

if (btnLoopClear) {
  btnLoopClear.addEventListener('click', () => {
    if (!playback) return;
    playback.clearLoop();
    loopASet = false;
    if (btnLoopA) { btnLoopA.classList.remove('active'); btnLoopA.title = 'Set loop start (A)'; }
    if (btnLoopB) { btnLoopB.classList.remove('active'); btnLoopB.title = 'Set loop end (B)'; }
    btnLoopClear.classList.remove('loop-active');
  });
}

if (btnFingering) {
  btnFingering.addEventListener('click', () => {
    if (!renderer) return;
    renderer.showFingering = !renderer.showFingering;
    btnFingering.classList.toggle('active', renderer.showFingering);
    const representationMode = getSelectedRepresentationMode();
    if (representationMode === MODES.TABLATURE) {
      renderer.render();
      return;
    }
    _syncCoreSvgFingering();
    _syncCoreSvgAnnotations();
    _syncCoreSvgHandOverlay();
  });
}

if (rngVolume) {
  rngVolume.value = '70';
  rngVolume.addEventListener('input', () => {
    if (playback) playback.setVolume(parseInt(rngVolume.value, 10) / 100);
  });
}

if (btnExportPdf) {
  btnExportPdf.addEventListener('click', exportPDF);
}

if (btnExportGp) {
  btnExportGp.addEventListener('click', exportGP);
}

if (btnMetronome) {
  btnMetronome.addEventListener('click', () => {
    if (!playback) return;
    const on = playback.toggleMetronome();
    btnMetronome.classList.toggle('active', on);
  });
}

if (btnBackViewer) {
  btnBackViewer.addEventListener('click', () => {
    if (playback) playback.stop();
    renderer = null;
    playback = null;
    loadFiles();
  });
}

if (btnHeaderBack) {
  btnHeaderBack.addEventListener('click', () => {
    if (playback) playback.stop();
    renderer = null;
    playback = null;
    loadFiles();
  });
}

if (btnHeaderGp) {
  btnHeaderGp.addEventListener('click', exportGP);
}

const btnRefreshFingerings = $('#set-refresh-fingerings');
const refreshFingeringsStatus = $('#set-refresh-fingerings-status');
if (btnRefreshFingerings) {
  btnRefreshFingerings.addEventListener('click', async () => {
    const ok = window.confirm(
      'Cette opération va ré-écrire un fichier <nom>_fingered.gp à côté '
      + 'de chaque .gp de votre bibliothèque. L\'original reste intact. '
      + 'Sur de gros corpus ça peut prendre plusieurs minutes. Continuer ?'
    );
    if (!ok) return;
    btnRefreshFingerings.disabled = true;
    if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = 'Démarrage…';
    try {
      const res = await fetch('/api/library/refresh-fingerings', { method: 'POST' });
      if (!res.ok || !res.body) {
        throw new Error(`HTTP ${res.status}`);
      }
      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buf = '';
      let processed = 0;
      let total = 0;
      let okCount = 0;
      let errCount = 0;
      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buf += decoder.decode(value, { stream: true });
        let nl;
        while ((nl = buf.indexOf('\n')) !== -1) {
          const line = buf.slice(0, nl).trim();
          buf = buf.slice(nl + 1);
          if (!line) continue;
          let msg;
          try { msg = JSON.parse(line); } catch (_) { continue; }
          if (msg.event === 'start') {
            total = msg.total_files || 0;
            if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = `0 / ${total}`;
          } else if (msg.event === 'done') {
            if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
              `Terminé : ${msg.ok} OK, ${msg.errors} erreurs, ${msg.skipped} ignorés.`;
          } else if (msg.status) {
            processed++;
            if (msg.status === 'ok') okCount++;
            if (msg.status === 'error') errCount++;
            if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
              `${processed} / ${total}  (${okCount} OK, ${errCount} erreurs) — ${msg.file}`;
          }
        }
      }
    } catch (err) {
      if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = `Erreur : ${err.message}`;
    } finally {
      btnRefreshFingerings.disabled = false;
    }
  });
}

if (btnHeaderPdf) {
  btnHeaderPdf.addEventListener('click', exportPDF);
}

if (btnBackFiles) {
  btnBackFiles.addEventListener('click', () => {
    loadFiles();
  });
}

// ── Legend overlay ───────────────────────────────────────────────────
if (btnLegend) {
  btnLegend.addEventListener('click', () => {
    legendOverlay.style.display = '';
    // Always rebuild so finger colors reflect the current theme
    if (legendContent) buildLegendHTML(legendContent);
  });
}

if (legendClose) {
  legendClose.addEventListener('click', () => {
    legendOverlay.style.display = 'none';
  });
}

if (legendOverlay) {
  legendOverlay.addEventListener('click', (e) => {
    if (e.target === legendOverlay) {
      legendOverlay.style.display = 'none';
    }
  });
}

// ── Position scrubber ───────────────────────────────────────────────

document.addEventListener('input', (e) => {
  if (e.target && e.target.id === 'position-scrubber') {
    if (!playback || !renderer) return;
    const total = renderer.measures.length || 1;
    const m = Math.round((e.target.value / 1000) * (total - 1));
    playback.goToMeasure(m);
  }
});

// ── Representation mode change re-solve ────────────────────────────

if (selRepresentationMode) {
  selRepresentationMode.addEventListener('change', () => {
    _syncViewSegPills();
    if (currentFile && currentTrackId != null) {
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

// ── View segmented control (pills) ─────────────────────────────────
function _syncViewSegPills() {
  const active = selRepresentationMode?.value || DEFAULT_MODE;
  document.querySelectorAll('.view-seg-btn').forEach(btn => {
    btn.classList.toggle('view-seg-active', btn.dataset.mode === active);
  });
}

document.querySelectorAll('.view-seg-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!selRepresentationMode) return;
    selRepresentationMode.value = btn.dataset.mode;
    selRepresentationMode.dispatchEvent(new Event('change'));
  });
});

_syncViewSegPills();

if (prefSameFingerPenalty) {
  prefSameFingerPenalty.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      _notesCache.clear();
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

if (prefInferLegato) {
  prefInferLegato.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      _notesCache.clear();
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

if (prefHandOverlay) {
  prefHandOverlay.addEventListener('change', () => {
    if (!renderer) return;
    if (getSelectedRepresentationMode() === MODES.TABLATURE) {
      renderer.render();
      return;
    }
    _syncCoreSvgHandOverlay();
  });
}

// ── Floating hand-visualization panel ──────────────────────────────────
// Available in ALL representation modes. The panel hosts an iframe that
// renders the animated left hand with active / sedentary / idle states.
//
// Two-way integration with parent:
//   - Data push  (track selection → post full fingering payload to iframe)
//   - Playhead sync (every tick → post current time in seconds so the
//     iframe animates in lock-step with parent's playback cursor).
//
// See docs/finger_placement_strategy.md for the sedentary-finger logic.
function _buildHandVizPayload() {
  if (!renderer || !renderer.data || !Array.isArray(renderer.data.results)) {
    return null;
  }
  const results = renderer.data.results;
  if (results.length === 0) return null;
  const tempo = renderer.data.tempo || 120;
  const frames = [];
  // Time base = parent's playback clock (t=0 at measure 0 beat 0), so
  // onset_sec is onset_beats * 60 / tempo — no "first-note" offset.
  for (const r of results) {
    const onsetSec = (r.onset || 0) * 60 / tempo;
    const durSec = Math.max(0.08, (r.duration || 0.25) * 60 / tempo);
    // `r.finger` comes from Python as "Finger.INDEX" — normalise to bare word.
    let finger = String(r.finger || 'open');
    if (finger.startsWith('Finger.')) finger = finger.slice(7).toLowerCase();
    frames.push({
      note_id: r.note_id,
      onset_sec: onsetSec,
      duration_sec: durSec,
      string: r.string,
      fret: r.fret,
      finger,
      hand_position: r.hand_position,
      pitch: r.pitch,
      voice: r.voice_hint || 0,
      planted: r.planted_fingers || {},
    });
  }
  return {
    meta: {
      title: (renderer.data.title || 'FretWise'),
      artist: renderer.data.artist || '',
      track: renderer.data.track_name || '',
      tempo,
      synced: true,                     // iframe MUST use external clock
      max_seconds: frames.length
        ? frames[frames.length - 1].onset_sec + 4
        : 10,
    },
    fretboard: {
      num_frets: 15,
      scale_length_mm: 648,
      tuning: ['E2', 'A2', 'D3', 'G3', 'B3', 'E4'],
    },
    frames,
  };
}

function _postHandVizData() {
  if (!handVizFrame || !handVizFrame.contentWindow) return;
  const payload = _buildHandVizPayload();
  if (!payload) return;
  handVizFrame.contentWindow.postMessage(
    { type: 'fretwise-hand-data', payload },
    '*',
  );
  // After reinstalling data, also push current time so the iframe starts
  // at the right place instead of t=0.
  _postHandVizTime();
}

function _reloadHandVizFrame() {
  if (!handVizFrame) return;
  handVizFrame.src = `/static/hand_viz.html?v=${Date.now()}`;
}

function _postHandVizTime() {
  if (!handVizFrame || !handVizFrame.contentWindow) return;
  if (!handVizPanel || handVizPanel.style.display === 'none') return;
  if (!playback || typeof playback.getCurrentTimeSec !== 'function') return;
  handVizFrame.contentWindow.postMessage(
    { type: 'fretwise-hand-seek', t: playback.getCurrentTimeSec(),
      playing: !!playback.isPlaying },
    '*',
  );
}

function _toggleHandViz() {
  if (!handVizPanel) return;
  const visible = handVizPanel.style.display !== 'none';
  handVizPanel.style.display = visible ? 'none' : 'flex';
  if (btnHandViz) btnHandViz.classList.toggle('tb-btn-active', !visible);
  if (!visible) {
    _reloadHandVizFrame();
    setTimeout(_postHandVizData, 250);
  }
}

if (btnHandViz) btnHandViz.addEventListener('click', _toggleHandViz);

if (handVizClose) {
  handVizClose.addEventListener('click', () => {
    if (handVizPanel) handVizPanel.style.display = 'none';
    if (btnHandViz) btnHandViz.classList.remove('tb-btn-active');
  });
}
if (handVizResync) handVizResync.addEventListener('click', () => {
  _reloadHandVizFrame();
  setTimeout(_postHandVizData, 250);
});

// Make the panel draggable by its header.
if (handVizDrag && handVizPanel) {
  let drag = null;
  handVizDrag.addEventListener('mousedown', (e) => {
    // Skip clicks on the header buttons themselves.
    if (e.target.closest('.floating-panel-btn')) return;
    const rect = handVizPanel.getBoundingClientRect();
    drag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
    e.preventDefault();
  });
  window.addEventListener('mousemove', (e) => {
    if (!drag) return;
    const x = Math.max(4, Math.min(window.innerWidth  - 60,  e.clientX - drag.dx));
    const y = Math.max(4, Math.min(window.innerHeight - 60,  e.clientY - drag.dy));
    handVizPanel.style.left   = x + 'px';
    handVizPanel.style.top    = y + 'px';
    handVizPanel.style.right  = 'auto';
    handVizPanel.style.bottom = 'auto';
  });
  window.addEventListener('mouseup', () => { drag = null; });
}

// Repush whenever the iframe signals it is ready.
window.addEventListener('message', (ev) => {
  if (ev && ev.data && ev.data.type === 'fretwise-hand-ready') _postHandVizData();
});

// Repush whenever the track changes or the pipeline re-runs. We hook into
// the renderer initialization point below.
window.addEventListener('fretwise:renderer-ready', _postHandVizData);

// ── File upload ─────────────────────────────────────────────────────

if (uploadInput) {
  uploadInput.addEventListener('change', async () => {
    const file = uploadInput.files[0];
    if (!file) return;
    if (uploadStatus) { uploadStatus.textContent = `Uploading ${file.name}…`; uploadStatus.style.color = '#888'; }
    try {
      await uploadFile(file);
      if (uploadStatus) { uploadStatus.textContent = `✓ ${file.name} added`; uploadStatus.style.color = '#4caf50'; }
      uploadInput.value = '';
      await loadFiles();
    } catch (err) {
      if (uploadStatus) { uploadStatus.textContent = `✗ ${err.message}`; uploadStatus.style.color = '#ff5555'; }
    }
  });
}

// ── Keyboard shortcuts ──────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  if (!playback) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

  switch (e.key) {
    case ' ':
      e.preventDefault();
      playback.toggle();
      updatePlayButton(playback.isPlaying);
      break;
    case 'ArrowLeft':
      e.preventDefault();
      playback.prev();
      break;
    case 'ArrowRight':
      e.preventDefault();
      playback.next();
      break;
    case 'Home':
      e.preventDefault();
      playback.goToMeasure(0);
      break;
    case 'End':
      e.preventDefault();
      playback.goToMeasure(renderer.measures.length - 1);
      break;
    case 'm':
    case 'M':
      playback.toggleMetronome();
      break;
  }
});

// ── resize handling ─────────────────────────────────────────────────

let resizeTimer;
window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (renderer) {
      renderer._buildSystems();
      renderer.render();
    }
  }, 200);
});

// ── Sanitize helper (XSS protection) ────────────────────────────────

function sanitize(str) {
  const el = document.createElement('span');
  el.textContent = str;
  return el.innerHTML;
}

// ── Chord diagram SVG renderer ──────────────────────────────────────

function _toRoman(n) {
  const pairs = [[10,'X'],[9,'IX'],[8,'VIII'],[7,'VII'],[6,'VI'],
                 [5,'V'],[4,'IV'],[3,'III'],[2,'II'],[1,'I']];
  let r = '';
  for (const [v, s] of pairs) while (n >= v) { r += s; n -= v; }
  return r;
}

/**
 * Returns an inline SVG string for a chord diagram.
 * @param {object} cd  Chord diagram data (name, frets, fingers, base_fret, string_count)
 * @param {number} sc  Scale factor (1 = strip size, ~1.9 = popup size)
 */
function chordDiagramSVG(cd, sc = 1) {
  const nStr  = cd.string_count || 6;
  const nFret = 5;
  const S     = Math.round(13 * sc);
  const F     = Math.round(13 * sc);
  const ML    = Math.round(8  * sc);
  const dotR  = Math.round(5  * sc);
  const boxW  = (nStr - 1) * S;
  const boxH  = nFret * F;
  const gridY = Math.round(30 * sc);
  const hasPos = cd.base_fret > 1;
  const svgW  = ML + boxW + ML + (hasPos ? Math.round(22 * sc) : 0);
  const svgH  = gridY + boxH + Math.round(8 * sc);
  const fSz   = Math.max(6, Math.round(7  * sc));   // finger-number font
  const nameSz= Math.max(9, Math.round(13 * sc));   // chord-name font

  const strX = i => ML + (nStr - 1 - i) * S;

  // Finger color mapped to program CSS variables (--f1…--f4)
  const dotFill  = (f) => (f >= 1 && f <= 4) ? `var(--f${f})` : '#444';
  const dotText  = '#111'; // all finger colors are light → dark text readable

  let p = `<svg width="${svgW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg" style="display:block">`;

  // Chord name
  p += `<text x="${ML + boxW / 2}" y="${Math.round(14 * sc)}"
    font-family="Arial,sans-serif" font-weight="bold" font-size="${nameSz}"
    text-anchor="middle" fill="#222">${sanitize(cd.name)}</text>`;

  // Nut bar or fret label
  if (!hasPos) {
    p += `<rect x="${ML}" y="${gridY - Math.round(3 * sc)}" width="${boxW}" height="${Math.round(3.5 * sc)}"
      fill="#333" rx="0.5"/>`;
  } else {
    const posSz = Math.max(7, Math.round(9 * sc));
    p += `<text x="${ML + boxW + 5}" y="${gridY + F / 2 + Math.round(4 * sc)}"
      font-family="Arial,sans-serif" font-size="${posSz}" fill="#555">${_toRoman(cd.base_fret)}fr</text>`;
  }

  // Grid: string lines
  for (let i = 0; i < nStr; i++) {
    const x = strX(i);
    p += `<line x1="${x}" y1="${gridY}" x2="${x}" y2="${gridY + boxH}" stroke="#bbb" stroke-width="0.8"/>`;
  }

  // Grid: fret lines
  for (let f = 0; f <= nFret; f++) {
    const y = gridY + f * F;
    p += `<line x1="${ML}" y1="${y}" x2="${ML + boxW}" y2="${y}" stroke="#bbb" stroke-width="0.8"/>`;
  }

  // Muted (×) and open (○) markers above grid
  const markY = Math.round(26 * sc);
  const openCY = Math.round(21 * sc);
  const openR  = Math.round(3.5 * sc);
  const markSz = Math.max(7, Math.round(9 * sc));
  for (let i = 0; i < nStr; i++) {
    const x = strX(i);
    const fv = cd.frets[i];
    if (fv === -1) {
      p += `<text x="${x}" y="${markY}" font-family="Arial,sans-serif"
        font-size="${markSz}" font-weight="bold" text-anchor="middle" fill="#555">x</text>`;
    } else if (fv === 0) {
      p += `<circle cx="${x}" cy="${openCY}" r="${openR}" fill="none" stroke="#555" stroke-width="1.2"/>`;
    }
  }

  // Barre detection: ≥2 strings at the lowest fretted fret
  const frettedNotes = cd.frets.map((fv, i) => ({ i, fv })).filter(n => n.fv > 0);
  const barreSet = new Set();
  if (frettedNotes.length >= 2) {
    const minFret = Math.min(...frettedNotes.map(n => n.fv));
    const barreSt = frettedNotes.filter(n => n.fv === minFret);
    if (barreSt.length >= 2) {
      const row = minFret - Math.max(cd.base_fret, 1);
      if (row >= 0 && row < nFret) {
        const cy  = gridY + row * F + F / 2;
        const xs  = barreSt.map(n => strX(n.i));
        const bx0 = Math.min(...xs), bx1 = Math.max(...xs);
        const bf  = cd.fingers?.[barreSt[0].i] || 0;
        p += `<rect x="${bx0 - dotR}" y="${cy - dotR}"
          width="${bx1 - bx0 + 2 * dotR}" height="${2 * dotR}"
          rx="${dotR}" fill="${dotFill(bf)}"/>`;
        if (bf) p += `<text x="${(bx0 + bx1) / 2}" y="${cy + dotR * 0.42}"
          font-family="Arial,sans-serif" font-size="${fSz}" font-weight="bold"
          text-anchor="middle" fill="${dotText}">${bf}</text>`;
        for (const n of barreSt) barreSet.add(n.i);
      }
    }
  }

  // Individual finger dots
  for (let i = 0; i < nStr; i++) {
    const fv = cd.frets[i];
    if (fv <= 0 || barreSet.has(i)) continue;
    const row = fv - Math.max(cd.base_fret, 1);
    if (row < 0 || row >= nFret) continue;
    const cx     = strX(i);
    const cy     = gridY + row * F + F / 2;
    const finger = cd.fingers?.[i] || 0;
    p += `<circle cx="${cx}" cy="${cy}" r="${dotR}" fill="${dotFill(finger)}"/>`;
    if (finger) {
      p += `<text x="${cx}" y="${cy + dotR * 0.42}"
        font-family="Arial,sans-serif" font-size="${fSz}" font-weight="bold"
        text-anchor="middle" fill="${dotText}">${finger}</text>`;
    }
  }

  p += '</svg>';
  return p;
}

// ── Chord popup: show inline, close on outside click ──────────────

let _chordDataMap = {};

function showChordPopup(chordName, clientX, clientY) {
  const cd = _chordDataMap[chordName];
  const popup = $('#chord-popup');
  if (!cd || !popup) return;

  popup.innerHTML = chordDiagramSVG(cd, 1.85);
  popup.classList.add('visible');
  popup.style.display = 'block';

  // Position near click, clamped to viewport
  const VW = window.innerWidth, VH = window.innerHeight;
  popup.style.left = '0'; popup.style.top = '0'; // reset for measurement
  const pw = popup.offsetWidth, ph = popup.offsetHeight;
  const px = Math.max(8, Math.min((clientX ?? VW / 2) - pw / 2, VW - pw - 8));
  const py = Math.max(8, Math.min((clientY ?? VH / 2) + 12,     VH - ph - 8));
  popup.style.left = `${px}px`;
  popup.style.top  = `${py}px`;
}

function hideChordPopup() {
  const popup = $('#chord-popup');
  if (popup) { popup.style.display = 'none'; popup.classList.remove('visible'); }
}

// Dismiss popup on any outside click
document.addEventListener('click', (e) => {
  const popup = $('#chord-popup');
  if (popup?.style.display !== 'none' && !popup.contains(e.target)) hideChordPopup();
});

// Chord bar collapse/expand toggle
document.addEventListener('DOMContentLoaded', () => {
  $('#chord-bar-toggle')?.addEventListener('click', () => {
    $('#chord-bar')?.classList.toggle('collapsed');
  });
});

// ── Red cursor overlay ──────────────────────────────────────────────

let _cursorRaf = null;
let _autoScrollTarget = null;

function startCursorLoop() {
  if (_cursorRaf) cancelAnimationFrame(_cursorRaf);
  function loop() {
    _drawCursorOverlay();
    _tickSvgCursor();
    if (playback?.isPlaying) {
      _cursorRaf = requestAnimationFrame(loop);
    } else {
      _cursorRaf = null;
    }
  }
  _cursorRaf = requestAnimationFrame(loop);
}

function stopCursorLoop() {
  if (_cursorRaf) { cancelAnimationFrame(_cursorRaf); _cursorRaf = null; }
  _autoScrollTarget = null;
  if (cursorCanvas) {
    cursorCanvas.getContext('2d').clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);
  }
  _svgDriver?.hideLine();
}

function _tickSvgCursor() {
  if (!_svgDriver || !playback?.isPlaying) return;
  const elapsed = (performance.now() - playback._startTime) / 1000;
  const elapsedBeats = elapsed * playback.tempo / 60 * playback.speed;
  const onset = playback._startMeasure * playback.bpm + elapsedBeats;
  _svgDriver.tick(onset, playback.bpm);
}

function _drawCursorOverlay() {
  if (!cursorCanvas || !renderer || !playback) return;

  // Match cursor canvas size exactly to tab canvas
  const dpr = window.devicePixelRatio || 1;
  if (cursorCanvas.width !== tabCanvas.width || cursorCanvas.height !== tabCanvas.height) {
    cursorCanvas.width  = tabCanvas.width;
    cursorCanvas.height = tabCanvas.height;
    cursorCanvas.style.width  = tabCanvas.style.width;
    cursorCanvas.style.height = tabCanvas.style.height;
  }

  const ctx = cursorCanvas.getContext('2d');
  ctx.clearRect(0, 0, cursorCanvas.width, cursorCanvas.height);

  if (!playback.isPlaying) return;

  // Current onset in beats
  const elapsed = (performance.now() - playback._startTime) / 1000;
  const elapsedBeats = elapsed * playback.tempo / 60 * playback.speed;
  const cursorOnset  = playback._startMeasure * playback.bpm + elapsedBeats;

  const col = renderer.getCursorX(cursorOnset);
  if (!col) return;

  // ── Auto-scroll: keep cursor in comfortable reading zone ──────────
  // Fixed UI: header=50px top, toolbar=52px+scrubber=16px bottom
  if (_followPlayhead) {
    const TOP_GUTTER  = 70;   // header (50) + small buffer
    const BOT_GUTTER  = 88;   // toolbar (52) + scrubber (16) + buffer
    const canvasRect = tabCanvas.getBoundingClientRect();
    const cursorViewportY = canvasRect.top + col.yTop;
    const vh = window.innerHeight;
    const usable = vh - TOP_GUTTER - BOT_GUTTER;
    const triggerLow  = vh - BOT_GUTTER - 80;   // wider trigger zone near bottom
    const triggerHigh = TOP_GUTTER + 40;          // wider trigger zone near top
    const targetY     = TOP_GUTTER + usable * 0.45; // land at 45% of usable area (near center)
    if (cursorViewportY > triggerLow || cursorViewportY < triggerHigh) {
      _autoScrollTarget = window.scrollY + cursorViewportY - targetY;
    }
    if (_autoScrollTarget !== null) {
      const delta = _autoScrollTarget - window.scrollY;
      if (Math.abs(delta) < 0.5) {
        _autoScrollTarget = null;
      } else {
        window.scrollTo(0, window.scrollY + delta * 0.12);
      }
    }
  }
  // ─────────────────────────────────────────────────────────────────

  ctx.save();
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.strokeStyle = '#e53935';
  ctx.lineWidth = 1.5;
  ctx.globalAlpha = 0.85;
  ctx.shadowColor = '#e53935';
  ctx.shadowBlur = 3;
  ctx.beginPath();
  ctx.moveTo(col.x, col.yTop);
  ctx.lineTo(col.x, col.yBottom);
  ctx.stroke();
  ctx.restore();
}

// ── Library table: sort and filter events ──────────────────────────

document.querySelectorAll('#lib-table th.sortable').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (_libSort.col === col) _libSort.dir *= -1;
    else { _libSort.col = col; _libSort.dir = 1; }
    _renderLibTable();
  });
});

const libSearch = $('#lib-search');
if (libSearch) libSearch.addEventListener('input', () => { _libSearch = libSearch.value; _renderLibTable(); });

const libGenreFilter = $('#lib-genre-filter');
if (libGenreFilter) libGenreFilter.addEventListener('change', () => { _libGenreFilter = libGenreFilter.value; _renderLibTable(); });

const libFormatFilter = $('#lib-format-filter');
if (libFormatFilter) libFormatFilter.addEventListener('change', () => { _libFormatFilter = libFormatFilter.value; _renderLibTable(); });

const songInfoClose = $('#song-info-close');
if (songInfoClose) songInfoClose.addEventListener('click', () => $('#song-info-panel')?.classList.remove('open'));

// ─── Settings page ────────────────────────────────────────────────

// ── Instrument Picker ────────────────────────────────────────────────

let _gmInstruments = null;
let _instrDropdown = null;

async function _ensureGmInstruments() {
  if (_gmInstruments) return _gmInstruments;
  try {
    _gmInstruments = await fetchGmInstruments();
  } catch (_) {
    _gmInstruments = [];
  }
  return _gmInstruments;
}

function _getStoredInstrument(file, trackId) {
  try {
    const val = localStorage.getItem(`fretwise:instrument:${file}:${trackId}`);
    return val !== null ? parseInt(val, 10) : null;
  } catch (_) { return null; }
}

function _storeInstrument(file, trackId, program) {
  try {
    localStorage.setItem(`fretwise:instrument:${file}:${trackId}`, String(program));
  } catch (_) {}
}

function _closeInstrDropdown() {
  if (_instrDropdown) { _instrDropdown.remove(); _instrDropdown = null; }
}

async function _openInstrumentPicker(anchorBtn, file, trackId, channelIdx) {
  _closeInstrDropdown();

  const instruments = await _ensureGmInstruments();
  const currentProgram = _getStoredInstrument(file, trackId);

  const dd = document.createElement('div');
  dd.className = 'instr-dropdown';

  const categories = {};
  for (const instr of instruments) {
    if (!categories[instr.category]) categories[instr.category] = [];
    categories[instr.category].push(instr);
  }

  for (const [cat, instrs] of Object.entries(categories)) {
    const catEl = document.createElement('div');
    catEl.className = 'instr-category';
    catEl.textContent = cat;
    dd.appendChild(catEl);

    for (const instr of instrs) {
      const btn = document.createElement('button');
      btn.className = 'instr-item' + (instr.id === currentProgram ? ' active' : '');
      btn.textContent = `${instr.id}. ${instr.name}`;
      btn.addEventListener('click', () => {
        _storeInstrument(file, trackId, instr.id);
        if (playback && channelIdx !== undefined) {
          playback.setChannelInstrument(channelIdx, instr.id);
        }
        _closeInstrDropdown();
        anchorBtn.title = `Instrument: ${instr.name} (click to change)`;
      });
      dd.appendChild(btn);
    }
  }

  document.body.appendChild(dd);
  _instrDropdown = dd;

  const rect = anchorBtn.getBoundingClientRect();
  let left = rect.left;
  let top = rect.bottom + 4;
  if (left + 260 > window.innerWidth) left = window.innerWidth - 268;
  if (top + 380 > window.innerHeight) top = rect.top - 384;
  dd.style.left = `${left}px`;
  dd.style.top = `${top}px`;

  setTimeout(() => {
    document.addEventListener('click', _closeInstrDropdown, { once: true });
  }, 0);
}

const btnSettings = $('#btn-settings');
if (btnSettings) {
  btnSettings.addEventListener('click', () => {
    showPage('settings');
    initSettingsPage();
  });
}

async function initSettingsPage() {
  try {
    const cfg = await fetchSettings();
    const pdInput = $('#set-partitions-dir');
    const ipInput = $('#set-index-path');
    if (pdInput) pdInput.value = cfg.partitions_dir || '';
    if (ipInput) ipInput.value = cfg.index_path || '';
  } catch (err) {
    console.error('Failed to load settings:', err);
  }

  await _loadSoundfontsPanel();

  const sfUploadInput = $('#sf-upload-input');
  const sfUploadStatus = $('#sf-upload-status');
  if (sfUploadInput) {
    // Avoid double-wiring on re-entry
    if (!sfUploadInput.dataset.wired) {
      sfUploadInput.dataset.wired = '1';
      sfUploadInput.addEventListener('change', async (e) => {
        const file = e.target.files[0];
        if (!file) return;
        if (sfUploadStatus) sfUploadStatus.textContent = 'Uploading…';
        try {
          await uploadSoundfont(file);
          if (sfUploadStatus) sfUploadStatus.textContent = '✓ Uploaded!';
          setTimeout(() => { if (sfUploadStatus) sfUploadStatus.textContent = ''; }, 3000);
          await _loadSoundfontsPanel();
        } catch (err) {
          if (sfUploadStatus) sfUploadStatus.textContent = '✗ ' + err.message;
        }
        e.target.value = '';
      });
    }
  }
}

async function _loadSoundfontsPanel() {
  const sfList = $('#sf-list');
  if (!sfList) return;
  try {
    const sfs = await fetchSoundfonts();
    if (sfs.length === 0) {
      sfList.innerHTML = '<div class="sf-empty">No soundfonts found in your soundfonts directory.</div>';
      return;
    }
    sfList.innerHTML = '';
    for (const sf of sfs) {
      const row = document.createElement('div');
      row.className = 'sf-row' + (sf.active ? ' active' : '');
      row.innerHTML = `
        <div class="sf-info">
          <span class="sf-name">${_esc(sf.name)}</span>
          <span class="sf-size">${sf.size_mb} MB</span>
          ${sf.active ? '<span class="sf-active-badge">Active</span>' : ''}
        </div>
        <div class="sf-actions">
          ${!sf.active ? `<button class="tx-btn sf-btn-activate" data-sf="${_esc(sf.name)}">Set Active</button>` : ''}
          <button class="tx-btn sf-btn-delete" data-sf="${_esc(sf.name)}">Delete</button>
        </div>
      `;
      row.querySelector('.sf-btn-activate')?.addEventListener('click', async (e) => {
        const name = e.currentTarget.dataset.sf;
        try {
          await activateSoundfont(name);
          await _loadSoundfontsPanel();
        } catch (err) { console.error(err); }
      });
      row.querySelector('.sf-btn-delete')?.addEventListener('click', async (e) => {
        const name = e.currentTarget.dataset.sf;
        if (!confirm(`Delete soundfont "${name}"? This cannot be undone.`)) return;
        try {
          await deleteSoundfont(name);
          await _loadSoundfontsPanel();
        } catch (err) { console.error(err); alert('Delete failed: ' + err.message); }
      });
      sfList.appendChild(row);
    }
  } catch (err) {
    sfList.innerHTML = `<div class="sf-empty">Failed to load soundfonts: ${_esc(err.message)}</div>`;
  }
}

const setPartitionsApply = $('#set-partitions-apply');
if (setPartitionsApply) {
  setPartitionsApply.addEventListener('click', async () => {
    const val = $('#set-partitions-dir')?.value?.trim();
    if (!val) return;
    try {
      await saveSettings({ partitions_dir: val });
      setPartitionsApply.textContent = '✓ Saved';
      setTimeout(() => { setPartitionsApply.textContent = 'Apply'; }, 2000);
      await loadFiles();
    } catch (err) {
      setPartitionsApply.textContent = '✗ Error';
      console.error(err);
      setTimeout(() => { setPartitionsApply.textContent = 'Apply'; }, 3000);
    }
  });
}

const setIndexApply = $('#set-index-apply');
if (setIndexApply) {
  setIndexApply.addEventListener('click', async () => {
    const val = $('#set-index-path')?.value?.trim();
    if (!val) return;
    try {
      await saveSettings({ index_path: val });
      setIndexApply.textContent = '✓ Saved';
      setTimeout(() => { setIndexApply.textContent = 'Apply'; }, 2000);
      await loadFiles();
    } catch (err) {
      setIndexApply.textContent = '✗ Error';
      console.error(err);
      setTimeout(() => { setIndexApply.textContent = 'Apply'; }, 3000);
    }
  });
}

// ── Boot ────────────────────────────────────────────────────────────

loadFiles();
