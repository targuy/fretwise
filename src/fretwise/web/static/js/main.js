/**
 * main.js — App initialization, page routing, event wiring
 *
 * Pages:  file-selector → track-selector → tab-viewer
 * Orchestra: renderer + playback + toolbar
 */

import { activateSoundfont, connectStorage, deleteSoundfont, disconnectStorage, downloadFile, fetchExportGp, fetchExportMusicXml, fetchExportMusicXmlAll, fetchExportPdf, fetchFiles, fetchGmInstruments, fetchLlmPrompt, fetchMe, fetchNotes, fetchSettings, fetchSongInfo, fetchSolve, fetchSongListDownload, fetchSoundfonts, fetchStorage, fetchTracks, importSongMetadata, saveSettings, uploadFile, uploadSoundfont } from './api.js';
import { getMaskedMeasures, renderAuditBanner, resetAuditBanner } from './audit.js';
import { TabRenderer, buildLegendHTML } from './renderer.js';
import { PlaybackEngine } from './playback.js';
import { SvgCursorDriver } from './svg-playback.js';
import { MODES, MODE_LABELS, DEFAULT_MODE, isGuitarKind, trackKindLabel } from './modeConfig.js';
import { applyLeatherIcons } from './icons.js';
import { initReview, resetReview } from './review.js';

// ── State ───────────────────────────────────────────────────────────

let currentFile = null;
let currentTrackId = null;
let _reviewTrackName = null;
let currentTracks = [];   // all tracks for the current file
// Kind of the currently-displayed primary track (guitar|bass|drums|vocal|
// other). Defaults to guitar so the UI behaves exactly as before until the
// backend supplies a kind. Drives the staff-only lock for non-guitar tracks.
let _currentTrackKind = 'guitar';
// Remembers the last view mode chosen while a guitar track was active so that
// switching to a non-guitar track (forced to Staff) and back does not leave
// the guitar track stuck in Staff view. Defaults to the standard default.
let _lastGuitarMode = DEFAULT_MODE;
let renderer = null;
let playback = null;
let _svgDriver = null;  // SvgCursorDriver instance for standard/standard+tab views
let loopASet = false;  // has A marker been set
let soundOn = false;   // tracks mute state across track changes
const _notesCache = new Map(); // key: `${file}#${trackId}` → /api/notes response
// Client-side solve cache: key `${file}#${trackId}#${mode}#${prefsKey}` →
// /api/solve response. Avoids re-hitting the network (and re-deserialising a
// large payload) when the user flips back to a track/mode already viewed.
const _solveCache = new Map();
// key: primaryTrackId → Set<secondaryTrackId> — tracks explicitly muted by the user
const _mutedSecondaryTracks = new Map();

/** Stable cache key for a solve request (file, track, mode, rule prefs). */
function _solveCacheKey(file, trackId, mode, prefs) {
  const p = prefs || {};
  const prefsKey = `${p.sameFingerPenalty !== false ? 1 : 0}`
    + `:${p.inferImplicitLegato !== false ? 1 : 0}`;
  return `${file}#${trackId}#${mode}#${prefsKey}`;
}

/**
 * Solve with a client-side cache. The first call for a (file, track, mode,
 * prefs) tuple hits the network; subsequent calls return the cached payload
 * synchronously-fast (still a Promise for a uniform API). The server keeps its
 * own LRU cache, but reusing the parsed JS object also skips re-deserialising
 * a multi-thousand-note payload on every tab switch.
 */
async function _cachedSolve(file, trackId, mode, prefs) {
  const key = _solveCacheKey(file, trackId, mode, prefs);
  if (_solveCache.has(key)) return _solveCache.get(key);
  const data = await fetchSolve(file, trackId, mode, prefs);
  _solveCache.set(key, data);
  return data;
}

let _followPlayhead = true;  // when false, user is exploring — no auto-scroll

// ── Debug overlay (toggle Shift+D) ──────────────────────────────────
// Read-only live snapshot of all coordinates / scroll states involved in
// the U2 centering bug. No production effect; activated manually.
let _debugOverlayOn = false;
let _debugOverlayRaf = null;

function _formatDebugLine(label, parts) {
  return `${label.padEnd(9)}` + parts.map(p => `${p.k}=${p.v}`).join('  ');
}

function _renderDebugOverlay() {
  const el = document.getElementById('debug-overlay');
  if (!el || !_debugOverlayOn) return;

  const mode = (typeof getSelectedRepresentationMode === 'function')
    ? getSelectedRepresentationMode() : 'unknown';
  const cont  = document.getElementById('tab-container');
  const svgC  = document.getElementById('core-svg-view');
  const body  = document.body;

  const measure = (typeof renderer !== 'undefined' && renderer)
    ? (renderer.cursorMeasure ?? 0) : '—';

  // System geometry as seen by playback._scrollCursorIntoView
  let sysInfo = 'no renderer';
  if (typeof renderer !== 'undefined' && renderer && renderer.systems) {
    const m = renderer.cursorMeasure || 0;
    const sysIdx = renderer.systems.findIndex(
      s => m >= s.startMeasure && m < s.startMeasure + s.measures.length,
    );
    const SYSTEM_H = 200, INTER_SYSTEM = 16, MARGIN_T = 12;
    const sysY = MARGIN_T + sysIdx * (SYSTEM_H + INTER_SYSTEM);
    const sysMid = sysY + SYSTEM_H / 2;
    const clientH = cont ? cont.clientHeight : 0;
    const centerTarget = Math.max(0, sysMid - clientH / 2);
    const drift = cont ? Math.round(cont.scrollTop - centerTarget) : 0;
    let driftCls = 'dbg-drift-ok';
    if (Math.abs(drift) > 80) driftCls = 'dbg-drift-high';
    else if (Math.abs(drift) > 20) driftCls = 'dbg-drift-mid';
    sysInfo =
      `sysIdx=${sysIdx}  sysY=${sysY}  sysMid=${sysMid}` +
      `  target=${Math.round(centerTarget)}` +
      `  <span class="${driftCls}">drift=${drift > 0 ? '+' : ''}${drift}</span>`;
  }

  const followStates = [
    `main=${_followPlayhead}`,
    `playback=${typeof playback !== 'undefined' && playback ? playback._followPlayhead : '—'}`,
    `svg=${typeof _svgDriver !== 'undefined' && _svgDriver ? _svgDriver.followPlayhead : '—'}`,
  ].join('  ');

  // Count visible scrollbars on the right edge (heuristic): elements whose
  // computed overflow-y is 'scroll' or 'auto' AND scrollHeight > clientHeight.
  const scrollables = [
    ['body', body],
    ['tabCont', cont],
    ['svgView', svgC],
    ['svgView.parent', svgC?.parentElement],
  ].filter(([_, e]) => e)
    .map(([name, e]) => {
      const cs = getComputedStyle(e);
      const oy = cs.overflowY;
      const isScrollable = (oy === 'scroll' || oy === 'auto') && e.scrollHeight > e.clientHeight;
      return { name, oy, isScrollable, scroll: e.scrollTop, client: e.clientHeight, full: e.scrollHeight };
    });
  const visibleScrollbars = scrollables.filter(s => s.isScrollable).length;

  const lines = [
    `<span class="dbg-title">─── DEBUG (Shift+D = close) ───</span>`,
    `mode      ${mode}`,
    `follow    ${followStates}`,
    `cursor    measure=${measure}`,
    `system    ${sysInfo}`,
    `viewport  innerW=${window.innerWidth}  innerH=${window.innerHeight}`,
    `bars      visible-scrollbars=${visibleScrollbars}`,
    ...scrollables.map(s =>
      `${s.name.padEnd(10)}oy=${s.oy.padEnd(7)} scroll=${s.scroll.toString().padStart(4)}  client=${s.client.toString().padStart(4)}  full=${s.full.toString().padStart(5)}  ${s.isScrollable ? '*' : ' '}`,
    ),
  ];
  el.innerHTML = lines.join('\n');

  _debugOverlayRaf = requestAnimationFrame(_renderDebugOverlay);
}

function _toggleDebugOverlay() {
  const el = document.getElementById('debug-overlay');
  if (!el) return;
  _debugOverlayOn = !_debugOverlayOn;
  el.style.display = _debugOverlayOn ? '' : 'none';
  if (_debugOverlayOn) {
    _renderDebugOverlay();
  } else if (_debugOverlayRaf) {
    cancelAnimationFrame(_debugOverlayRaf);
    _debugOverlayRaf = null;
  }
}

document.addEventListener('keydown', (e) => {
  // Shift+D toggles the overlay. Ignore when typing in inputs.
  if (e.shiftKey && (e.key === 'D' || e.key === 'd')) {
    const tag = (document.activeElement?.tagName || '').toLowerCase();
    if (tag === 'input' || tag === 'textarea' || document.activeElement?.isContentEditable) return;
    e.preventDefault();
    _toggleDebugOverlay();
  }
});

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
const btnHeaderMusicXml = $('#btn-header-musicxml');

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
const handVizPopout = $('#hand-viz-popout');
const handVizDrag   = $('#hand-viz-drag');
let handVizPopupWindow = null;

// ── Page routing ────────────────────────────────────────────────────

function showPage(page) {
  const isViewer = page === 'viewer';
  const isSettings = page === 'settings';
  fileSelector.style.display  = page === 'files'    ? '' : 'none';
  trackSelector.style.display = page === 'tracks'   ? '' : 'none';
  tabViewer.style.display     = isViewer ? '' : 'none';
  toolbar.style.display       = isViewer ? '' : 'none';
  if (settingsPage)     settingsPage.style.display     = isSettings ? '' : 'none';
  if (headerMeta)       headerMeta.style.display       = isViewer ? '' : 'none';
  if (btnHeaderBack)    btnHeaderBack.style.display    = isViewer ? '' : 'none';
  if (btnDownloadGp)    btnDownloadGp.style.display    = isViewer ? '' : 'none';
  const tabsBar = $('#track-tabs-bar');
  if (tabsBar) tabsBar.style.display = isViewer ? '' : 'none';
  // Chevrons follow the bar; recompute after the display change applies.
  if (typeof _updateTrackTabsChevrons === 'function') {
    requestAnimationFrame(_updateTrackTabsChevrons);
  }
  // Update settings nav: "Back to song" only active when a track is loaded
  const setBackViewer = $('#set-back-viewer');
  if (setBackViewer) setBackViewer.disabled = !(currentTrackId != null && currentFile != null);
  // Ensure the old bottom bar class doesn't shift bottom elements
  document.body.classList.remove('has-multitrack-bar');
}

// ── File selector (library table) ──────────────────────────────────

let _allFiles = [];
let _storageStatus = null;  // /api/storage result, fetched when the library is empty
let _libSort = { col: 'title', dir: 1 };
let _libSearch = '';
let _libGenreFilter = '';
let _libFormatFilter = '';

async function loadFiles() {
  showPage('files');
  try {
    _allFiles = await fetchFiles();
    // When the library is empty, the storage status tells us WHY (no backend
    // connected vs an empty cloud folder) so the empty-state can guide the user.
    _storageStatus = _allFiles.length === 0 ? await fetchStorage() : null;
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

// Choose the empty-state message. Distinguishes "no search match" (the library
// has files, the filters hid them) from a genuinely empty library, and within
// the latter distinguishes a not-yet-connected cloud backend from an empty
// cloud folder vs the single-user local-directory case.
function _emptyLibraryMessage() {
  const filtersActive = _libSearch || _libGenreFilter || _libFormatFilter;
  if (_allFiles.length > 0 && filtersActive) {
    return 'No scores match your search or filters.';
  }
  const s = _storageStatus;
  if (s && s.configured === false) {
    return 'No storage connected. Connect your cloud storage (e.g. Google Drive) '
      + 'in Settings ⚙, or upload a file below.';
  }
  if (s && s.configured && s.backend && s.backend !== 'local') {
    return `Your ${s.backend} storage has no scores yet — upload a file below to get started.`;
  }
  return 'No files found. Check your partition directory in Settings, or upload a file below.';
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
    if (empty) {
      empty.style.display = '';
      empty.textContent = _emptyLibraryMessage();
    }
    tbody.innerHTML = '';
    _renderAzBar([]);
    return;
  }
  if (empty) empty.style.display = 'none';

  tbody.innerHTML = '';
  for (const f of rows) {
    const tr = document.createElement('tr');
    tr.className = 'lib-row';
    tr.dataset.file = f.name;
    tr.dataset.sortkey = _libNavKey(f);

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

  _renderAzBar(rows);
}

// The value used by the A–Z bar to bucket a row. Follows the active table sort
// when it is by 'artist' or 'title'; otherwise falls back to title so the bar
// still makes sense when sorting by year/genre/format.
function _libNavKey(f) {
  const col = (_libSort.col === 'artist') ? 'artist' : 'title';
  const val = col === 'artist'
    ? (f.meta?.artist || '')
    : (f.meta?.title || f.stem || f.name || '');
  return String(val).trim().toUpperCase();
}

// Map a sort key to its index bucket: A–Z, or '#' for anything else (digits,
// symbols, empty).
function _libNavBucket(key) {
  const c = (key || '').charAt(0);
  return (c >= 'A' && c <= 'Z') ? c : '#';
}

// Build the A–Z index bar. Letters with no matching entry are disabled/dimmed;
// clicking a letter scrolls the table to its first matching row.
function _renderAzBar(rows) {
  const bar = $('#lib-az-bar');
  if (!bar) return;
  bar.innerHTML = '';

  const present = new Set();
  for (const f of rows) present.add(_libNavBucket(_libNavKey(f)));

  const letters = ['#', ...'ABCDEFGHIJKLMNOPQRSTUVWXYZ'];
  for (const letter of letters) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'lib-az-letter';
    btn.textContent = letter;
    if (!present.has(letter)) {
      btn.disabled = true;
    } else {
      btn.addEventListener('click', () => _scrollToLetter(letter));
    }
    bar.appendChild(btn);
  }
}

// Scroll the table to the first row whose nav key falls in the given bucket.
function _scrollToLetter(letter) {
  const tbody = $('#lib-table-body');
  if (!tbody) return;
  for (const tr of tbody.querySelectorAll('tr.lib-row')) {
    if (_libNavBucket(tr.dataset.sortkey || '') === letter) {
      tr.scrollIntoView({ behavior: 'smooth', block: 'start' });
      tr.classList.add('lib-row-flash');
      setTimeout(() => tr.classList.remove('lib-row-flash'), 800);
      return;
    }
  }
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

  // Base = the already-enriched meta from the file list (filename + catalog
  // merged). Overlay any non-empty fields from the catalog row endpoint on top.
  const meta = { ...(f.meta || {}) };
  try {
    const fetched = await fetchSongInfo(f.name);
    if (fetched) {
      for (const [k, v] of Object.entries(fetched)) {
        if (v != null && String(v).trim() !== '') meta[k] = v;
      }
    }
  } catch (_) {}

  const title = meta.title || f.stem || f.name;

  // Bookkeeping/key columns that should never show as displayable metadata.
  const HIDE = new Set(['filename', 'file', 'name', 'stem', 'title']);
  // Preferred display order for the known catalog fields.
  const ORDER = ['artist', 'album', 'genre', 'year', 'notes'];
  const LABELS = {
    artist: 'Artist', album: 'Album', genre: 'Genre',
    year: 'Year', notes: 'Notes',
  };

  const seen = new Set();
  const ordered = [];
  for (const k of ORDER) {
    if (k in meta) { ordered.push(k); seen.add(k); }
  }
  // Append any extra catalog columns the user added, in their own order.
  for (const k of Object.keys(meta)) {
    if (!HIDE.has(k) && !seen.has(k)) ordered.push(k);
  }
  // Always show the core fields even if blank, so the panel reads consistently.
  for (const k of ['artist', 'album', 'genre', 'year', 'notes']) {
    if (!ordered.includes(k)) ordered.push(k);
  }

  const _label = (k) => LABELS[k] || (k.charAt(0).toUpperCase() + k.slice(1));
  const rows = ordered.map((k) => {
    const v = meta[k];
    const disp = (v == null || String(v).trim() === '') ? '—' : String(v);
    return `<tr><th>${_esc(_label(k))}</th><td>${_esc(disp)}</td></tr>`;
  }).join('');

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
  _solveCache.clear();
  _mutedSecondaryTracks.clear();
  resetReview();

  try {
    const tracks = await fetchTracks(filename);
    currentTracks = tracks;
    if (!tracks.length) {
      // Stay on file selector and surface the error
      const libEmpty = $('#lib-empty');
      if (libEmpty) { libEmpty.style.display = ''; libEmpty.textContent = `No tracks found in "${sanitize(filename)}".`; }
      return;
    }
    // Auto-select the first guitar track to preserve the prior UX (the
    // backend now returns every track, not just guitars). Fall back to the
    // first track when the song has no guitar at all.
    const firstGuitar = tracks.find((t) => isGuitarKind(t.kind)) || tracks[0];
    await selectTrack(firstGuitar.id, firstGuitar.name);
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
    // Non-guitar tracks only ever render in staff view, so warm just that
    // mode. Missing/unknown kind is treated as guitar (warm every mode).
    const modes = isGuitarKind(t.kind) ? _PREFETCH_MODES : [MODES.STANDARD];
    for (const mode of modes) {
      if (myToken !== _prefetchAbortToken) return;
      const key = _solveCacheKey(filename, t.id, mode, prefs);
      if (_solveCache.has(key)) continue;  // already warm — skip the round-trip
      // Warm BOTH the server LRU and our client-side object cache so the next
      // interactive switch to this (track, mode) renders without any network.
      fetchSolve(filename, t.id, mode, prefs)
        .then((data) => { _solveCache.set(key, data); })
        .catch(() => { /* silent — interactive solve will retry */ });
    }
  }
}

// ── Tab viewer ──────────────────────────────────────────────────────

function populateTrackSwitcher(_trackId) {
  // Track switching is now handled by the multi-track bar name clicks — no-op
}

// Monotonic token: every selectTrack bumps it, so a slow solve that resolves
// after the user has clicked another tab is discarded instead of overwriting
// the newer view. Also doubles as a re-entrancy / rapid-click guard.
let _selectTrackToken = 0;

async function selectTrack(trackId, trackName) {
  const myToken = ++_selectTrackToken;
  currentTrackId = trackId;
  _reviewTrackName = trackName;  // remembered so the review panel can re-solve
  // Resolve the track kind from the loaded list and lock the UI before any
  // solve is requested. Non-guitar tracks are forced to staff-only view so
  // we never ask the backend for tablature / fingering they cannot provide;
  // guitar tracks restore the user's last guitar view mode (so a detour
  // through a non-guitar track does not strand them in Staff view).
  _currentTrackKind = _trackKindById(trackId);
  if (selRepresentationMode) {
    const target = _isCurrentTrackGuitar() ? _lastGuitarMode : MODES.STANDARD;
    if (selRepresentationMode.value !== target) {
      selRepresentationMode.value = target;
      _syncViewSegPills();
    }
  }
  _applyTrackKindLock();
  // Capture playback position BEFORE pausing/recreating so we can restore
  // it on the new track. Without this, switching tracks always restarts
  // from measure 0 — confirmed annoying by the PO.
  let restorePos = null;
  if (playback) {
    const wasPlaying = playback.isPlaying;
    if (wasPlaying) {
      playback.pause();
      updatePlayButton(false);
      stopCursorLoop();
    }
    restorePos = {
      measure: playback.renderer?.cursorMeasure ?? 0,
      subMeasureSec: playback._resumeSubMeasureSec || 0,
      wasPlaying,
    };
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

  // Loading feedback + tab lock: show the banner and disable the track tabs
  // so the user cannot stack up multiple solves with rapid clicks. Cleared in
  // the finally block once this solve has rendered (or been superseded).
  _setSongLoading(true);
  _setTabsBusy(true);

  try {
    const representationMode = getSelectedRepresentationMode();
    const data = await _cachedSolve(
      currentFile,
      trackId,
      representationMode,
      getRulePreferences(),
    );
    // A newer selectTrack started while we were awaiting — drop this stale
    // result so it cannot clobber the view the user is now looking at.
    if (myToken !== _selectTrackToken) return;
    // Reconcile kind with the authoritative solve response: if /api/tracks
    // lacked a kind but the solve payload carries one, trust the latter and
    // re-apply the lock (covers a backend that only tags kind on /api/solve).
    if (data && data.kind != null && data.kind !== _currentTrackKind) {
      _currentTrackKind = data.kind;
      if (!_isCurrentTrackGuitar() && selRepresentationMode
          && selRepresentationMode.value !== MODES.STANDARD) {
        selRepresentationMode.value = MODES.STANDARD;
        _syncViewSegPills();
      }
      _applyTrackKindLock();
    }
    initRenderer(data);
    renderAuditBanner(data?.audit, {
      onMaskedMeasuresChange: () => _syncCoreSvgFingering(),
    });
    // Restore playback position from the previous track on the new one.
    // Clamp to the new track's measure count to handle tracks of different
    // lengths. Resume playback if it was playing before the switch.
    if (restorePos && playback) {
      const clamped = Math.max(
        0,
        Math.min(restorePos.measure, (playback.totalMeasures || 1) - 1),
      );
      if (playback.renderer) playback.renderer.cursorMeasure = clamped;
      playback._resumeSubMeasureSec = restorePos.subMeasureSec;
      if (playback.onMeasureChange) playback.onMeasureChange(clamped);
      if (playback.onTimeChange) {
        playback.onTimeChange(playback.getCurrentTimeSec());
      }
      if (restorePos.wasPlaying) {
        playback.play();
        updatePlayButton(true);
        startCursorLoop();
      }
    }
  } catch (err) {
    if (myToken !== _selectTrackToken) return;
    ctx.clearRect(0, 0, tabCanvas.width, tabCanvas.height);
    ctx.fillStyle = '#ff5555';
    ctx.fillText(`Error: ${err.message}`, 200, 50);
  } finally {
    // Only the most recent selectTrack clears the busy state — a superseded
    // (stale) solve must not re-enable the tabs while a newer one is still
    // in flight.
    if (myToken === _selectTrackToken) {
      _setSongLoading(false);
      _setTabsBusy(false);
    }
  }
}

// ── Loading feedback (B3.2 / B2.1) ───────────────────────────────────
//
// A non-blocking banner shown while a track is being solved + rendered, plus
// a guard that disables the track tabs so a second click cannot queue another
// solve before the first finishes. Both are owned by the frontend team; the
// banner element is created lazily so no index.html change is required beyond
// the (separately added) markup.

function _setSongLoading(on) {
  const banner = document.getElementById('song-loading-banner');
  if (!banner) return;
  banner.style.display = on ? 'flex' : 'none';
}

function _setTabsBusy(busy) {
  const bar = document.getElementById('track-tabs-bar');
  if (bar) {
    bar.classList.toggle('tabs-busy', busy);
    bar.querySelectorAll('.track-tab').forEach((tab) => {
      tab.style.pointerEvents = busy ? 'none' : '';
      tab.style.opacity = busy ? '0.55' : '';
    });
  }
  // The multi-track mixer names also switch the primary track — lock them too.
  if (_multiTrackBar) {
    _multiTrackBar.querySelectorAll('.mt-name').forEach((el) => {
      el.style.pointerEvents = busy ? 'none' : '';
    });
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
    // The backend returns a self-contained, user-facing message (incl. the
    // biomechanical-guard block), so show it verbatim without a prefix.
    _setPdfExportStatus(err.message || 'Export GP échoué', 'error');
  } finally {
    if (btnHeaderGp) {
      btnHeaderGp.disabled = false;
      btnHeaderGp.setAttribute('aria-label', originalLabel);
    }
  }
}

async function exportMusicXML(scope = 'current') {
  if (!currentFile) return;
  const isAll = scope === 'all';
  const originalLabel = btnHeaderMusicXml?.getAttribute('aria-label') || 'Export MusicXML';
  if (btnHeaderMusicXml) {
    btnHeaderMusicXml.disabled = true;
    btnHeaderMusicXml.setAttribute('aria-label', 'Export…');
  }
  const scopeLabel = isAll ? 'all tracks' : 'current track';
  _setPdfExportStatus(`Export MusicXML (${scopeLabel})…`, 'neutral');
  try {
    const { blob, filename, noteCount } = isAll
      ? await fetchExportMusicXmlAll(currentFile, currentTrackId)
      : await fetchExportMusicXml(currentFile, currentTrackId);
    _downloadBlob(blob, filename);
    _setPdfExportStatus(`Export MusicXML OK — ${scopeLabel} (${noteCount} notes)`, 'ok');
  } catch (err) {
    // Be defensive: a backend without scope support may 404 the "all" request.
    if (isAll && /\b404\b|not found|unsupported|scope/i.test(err.message || '')) {
      _setPdfExportStatus('All-tracks export not available on this server', 'warn');
    } else {
      _setPdfExportStatus(`Export MusicXML failed: ${err.message}`, 'error');
    }
  } finally {
    if (btnHeaderMusicXml) {
      btnHeaderMusicXml.disabled = false;
      btnHeaderMusicXml.setAttribute('aria-label', originalLabel);
    }
  }
}

// Small scope-choice menu anchored under the MusicXML header button.
let _musicXmlScopeMenu = null;
function _closeMusicXmlScopeMenu() {
  if (_musicXmlScopeMenu) {
    _musicXmlScopeMenu.remove();
    _musicXmlScopeMenu = null;
  }
}
function _openMusicXmlScopeMenu(anchorBtn) {
  _closeMusicXmlScopeMenu();
  const menu = document.createElement('div');
  menu.className = 'instr-dropdown musicxml-scope-menu';
  menu.setAttribute('role', 'menu');
  menu.setAttribute('aria-label', 'MusicXML export scope');

  const choices = [
    { scope: 'current', label: 'Current track', hint: 'This track only (default)' },
    { scope: 'all', label: 'All tracks', hint: 'Every track in one file' },
  ];
  for (const c of choices) {
    const btn = document.createElement('button');
    btn.className = 'instr-item';
    btn.setAttribute('role', 'menuitem');
    btn.innerHTML = `<strong>${sanitize(c.label)}</strong><br>`
      + `<span style="opacity:0.65;font-size:11px">${sanitize(c.hint)}</span>`;
    btn.addEventListener('click', () => {
      _closeMusicXmlScopeMenu();
      exportMusicXML(c.scope);
    });
    menu.appendChild(btn);
  }

  document.body.appendChild(menu);
  _musicXmlScopeMenu = menu;

  const rect = anchorBtn.getBoundingClientRect();
  const menuWidth = menu.offsetWidth || 260;
  let left = rect.right - menuWidth;
  if (left < 8) left = 8;
  if (left + menuWidth > window.innerWidth - 8) left = window.innerWidth - menuWidth - 8;
  menu.style.left = `${left}px`;
  menu.style.top = `${rect.bottom + 4}px`;

  setTimeout(() => {
    document.addEventListener('click', _closeMusicXmlScopeMenu, { once: true });
  }, 0);
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

// ── Track-kind UI lock ──────────────────────────────────────────────
//
// Guitar tracks expose tablature, the Tab/Mixed view toggles and the
// left-hand fingering UI exactly as before. Non-guitar tracks (bass tabbed
// as `other`, drums, vocal, …) have no fingering and no tablature: we force
// the staff-only view and disable the Tab + Mixed pills and the fingering
// controls so the user cannot request data that does not exist.

/**
 * Resolve the ``kind`` of a track from the loaded track list.
 *
 * @param {number} trackId
 * @returns {string} kind string, defaulting to ``'guitar'`` when unknown.
 */
function _trackKindById(trackId) {
  const t = (currentTracks || []).find((x) => x.id === trackId);
  return t?.kind || 'guitar';
}

/** True when the currently-displayed primary track is a fretted guitar. */
function _isCurrentTrackGuitar() {
  return isGuitarKind(_currentTrackKind);
}

/**
 * Enable / disable the Tab + Mixed view pills and the fingering toolbar
 * buttons according to the current track kind. For non-guitar tracks the
 * tablature-bearing pills (Mixed, Tab) and the fingering / hand-overlay
 * controls are visually disabled and non-interactive; only the Staff pill
 * stays active. Guitar tracks restore every control. Idempotent and safe to
 * call repeatedly (e.g. after each ``selectTrack``).
 */
function _applyTrackKindLock() {
  const guitar = _isCurrentTrackGuitar();

  // View pills: Staff is always available; Mixed / Tab require tablature.
  // style.css is owned by another team, so the disabled look is applied via
  // inline styles (opacity / cursor / pointer-events) rather than a class.
  document.querySelectorAll('.view-seg-btn').forEach((btn) => {
    const needsTab = btn.dataset.mode !== MODES.STANDARD;
    const lock = !guitar && needsTab;
    btn.disabled = lock;
    btn.classList.toggle('view-seg-disabled', lock);
    if (lock) {
      btn.setAttribute('aria-disabled', 'true');
      btn.setAttribute('tabindex', '-1');
      btn.style.opacity = '0.35';
      btn.style.cursor = 'not-allowed';
      btn.style.pointerEvents = 'none';
      btn.title = 'Tablature unavailable for non-guitar tracks';
    } else {
      btn.removeAttribute('aria-disabled');
      btn.removeAttribute('tabindex');
      btn.style.opacity = '';
      btn.style.cursor = '';
      btn.style.pointerEvents = '';
      // Restore the original tooltip (set in index.html).
      if (btn.dataset.mode === MODES.STANDARD) btn.title = 'Standard notation';
      else if (btn.dataset.mode === MODES.STANDARD_TABLATURE) {
        btn.title = 'Standard + Tab (default)';
      } else if (btn.dataset.mode === MODES.TABLATURE) btn.title = 'Tablature only';
    }
  });

  // Fingering button + fretboard / hand-overlay panel make no sense without
  // fingering data. Hide them entirely for non-guitar tracks.
  const fingeringControls = [btnFingering, btnHandViz];
  for (const el of fingeringControls) {
    if (el) el.style.display = guitar ? '' : 'none';
  }
  // The hand-movement-lane preference lives inside the prefs panel.
  const handPrefItem = document.querySelector('.tb-pref-hand-overlay');
  if (handPrefItem && !guitar) handPrefItem.style.display = 'none';

  // Close the floating fretboard panel if it was left open from a guitar
  // track — it has nothing to show for a non-guitar one.
  if (!guitar && handVizPanel && handVizPanel.style.display !== 'none') {
    handVizPanel.style.display = 'none';
    if (btnHandViz) btnHandViz.classList.remove('tb-btn-active');
  }
}

function applyRepresentationModeView(data) {
  // Non-guitar tracks are always shown as staff, regardless of what mode the
  // backend echoed back (covers a tab-mode solve issued before the kind was
  // known). Guitar tracks keep the requested / echoed mode unchanged.
  const representationMode = _isCurrentTrackGuitar()
    ? (data?.representation_mode || getSelectedRepresentationMode())
    : MODES.STANDARD;
  if (selRepresentationMode && selRepresentationMode.value !== representationMode) {
    selRepresentationMode.value = representationMode;
  }
  // Keep the segmented-control highlight in step with the (possibly coerced)
  // select value without dispatching a re-solve.
  _syncViewSegPills();
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
  // Non-guitar tracks carry no fingering: never draw finger annotations and
  // keep the (hidden) fingering toggle inactive. Defensive — the solve
  // response also exposes `fingered:false` for these tracks.
  if (!_isCurrentTrackGuitar() || data.fingered === false) {
    renderer.showFingering = false;
  }
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
  // Reuse the existing engine across track / mode switches so we do NOT tear
  // down the AudioContext and re-fetch + re-parse the (multi-MB) SF2 soundfont
  // every time — that reload was the dominant tab-switch cost (B1.2). rebind()
  // swaps in the new renderer + tempo, stops in-flight audio and clears the
  // secondary channels (re-added below), but keeps the loaded synth alive.
  updatePlayButton(false);
  stopCursorLoop();
  const engineOpts = {
    tempo: data.tempo || 120,
    beatsPerMeasure: data.beats_per_measure || 4,
  };
  if (playback) {
    playback.rebind(renderer, engineOpts);
  } else {
    playback = new PlaybackEngine(renderer, engineOpts);
  }
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
    const panelVisible = handVizPanel && handVizPanel.style.display !== 'none';
    const popupVisible = handVizPopupWindow && !handVizPopupWindow.closed;
    if (panelVisible || popupVisible) _postHandVizTime();
  };
  // Enable audio immediately (muting is handled per-track in the multi-track bar)
  playback.enableAudio();

  // Safari/iOS: enableAudio() above creates the AudioContext in a 'suspended'
  // state because page load is not a user gesture, and the browser only resumes
  // it from within one. The splash screen now consumes the very first click, so
  // resume the context on the first user gesture anywhere — the splash dismiss
  // click bubbles to this capture-phase listener, unlocking sound before any
  // playback. Self-removing: later play handlers already re-resume as a backup.
  {
    const _unlockAudio = () => {
      playback.resumeAudioContext();
      if (!playback.audioEnabled) playback.enableAudio();
      ['pointerdown', 'touchend', 'keydown'].forEach((evt) =>
        window.removeEventListener(evt, _unlockAudio, { capture: true }));
    };
    ['pointerdown', 'touchend', 'keydown'].forEach((evt) =>
      window.addEventListener(evt, _unlockAudio, { capture: true }));
  }

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
        _setFollowPlayhead(false);
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
    _svgDriver.followPlayhead = _followPlayhead;
    // SVG view: the driver scrolls #core-svg-view. Tell the engine to suppress
    // its own canvas-geometry scroll of #tab-container (which would otherwise
    // drag the absolutely-positioned SVG box out of frame — the "narrowing"
    // playback bug).
    playback.usesSvgCursor = true;
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
          _setFollowPlayhead(false);
        }
        playback.goToMeasure(m);
      }
    };
  } else {
    if (coreSvgView) coreSvgView.onclick = null;
    // Canvas (Tab) view: this engine scrolls #tab-container normally.
    playback.usesSvgCursor = false;
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
  _setFollowPlayhead(true);
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

// Distinct colour-bar tint for every non-guitar track kind (guitar keeps the
// rotating palette so its tabs look exactly as before). Emoji glyph gives an
// at-a-glance icon next to the kind badge.
const _NON_GUITAR_KIND_STYLE = {
  bass:  { color: 'oklch(0.62 0.10 40)',  glyph: '🎸' },
  drums: { color: 'oklch(0.55 0.02 0)',   glyph: '🥁' },
  vocal: { color: 'oklch(0.68 0.12 350)', glyph: '🎤' },
  other: { color: 'oklch(0.60 0.02 250)', glyph: '🎹' },
};

// ── Track-tab horizontal navigation (mouse-friendly) ────────────────
// The tabs bar scrolls horizontally but hides its scrollbar, so on a plain
// mouse (no horizontal wheel/trackpad) off-screen tabs are unreachable. We
// (1) translate vertical wheel into horizontal scroll, and (2) show left/right
// chevrons only when the bar overflows, hiding the arrow once that end is hit.
let _trackTabsNavWired = false;

function _updateTrackTabsChevrons() {
  const bar = $('#track-tabs-bar');
  const left = $('#track-tabs-chevron-left');
  const right = $('#track-tabs-chevron-right');
  if (!bar || !left || !right) return;
  // Hide both chevrons entirely when the bar itself is hidden or fits.
  const barHidden = bar.style.display === 'none' || bar.offsetParent === null;
  const overflowing = bar.scrollWidth > bar.clientWidth + 1;
  if (barHidden || !overflowing) {
    left.hidden = true;
    right.hidden = true;
    return;
  }
  const maxScroll = bar.scrollWidth - bar.clientWidth;
  const atStart = bar.scrollLeft <= 1;
  const atEnd = bar.scrollLeft >= maxScroll - 1;
  left.hidden = atStart;
  right.hidden = atEnd;
}

function _scrollTrackTabs(direction) {
  const bar = $('#track-tabs-bar');
  if (!bar) return;
  // One "tab width" ≈ first tab's outer width, fallback to a sensible default.
  const firstTab = bar.querySelector('.track-tab');
  const step = firstTab ? firstTab.offsetWidth + 4 : 180;
  bar.scrollBy({ left: direction * step, behavior: 'smooth' });
}

function _wireTrackTabsNav() {
  if (_trackTabsNavWired) return;
  const bar = $('#track-tabs-bar');
  const left = $('#track-tabs-chevron-left');
  const right = $('#track-tabs-chevron-right');
  if (!bar) return;
  _trackTabsNavWired = true;

  // Vertical wheel → horizontal scroll. Only intercept when there is overflow
  // and the gesture is predominantly vertical (leave native horizontal alone).
  bar.addEventListener('wheel', (e) => {
    if (bar.scrollWidth <= bar.clientWidth + 1) return;
    if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
    bar.scrollLeft += e.deltaY;
    e.preventDefault();
    _updateTrackTabsChevrons();
  }, { passive: false });

  bar.addEventListener('scroll', _updateTrackTabsChevrons, { passive: true });

  if (left) left.addEventListener('click', () => _scrollTrackTabs(-1));
  if (right) right.addEventListener('click', () => _scrollTrackTabs(1));
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
    // Treat a missing kind as guitar so existing files render unchanged.
    const isGuitar = isGuitarKind(t.kind);
    // Guitar keeps the rotating palette colour (so several guitars stay
    // distinct) but now shares the SAME badge + colour-bar + left-border layout
    // as every other kind. Non-guitar kinds use their fixed tint + glyph.
    const kindStyle = isGuitar
      ? { color: _TRACK_COLORS[i % _TRACK_COLORS.length], glyph: '🎸' }
      : (_NON_GUITAR_KIND_STYLE[String(t.kind).toLowerCase()]
         || _NON_GUITAR_KIND_STYLE.other);
    const color = kindStyle.color;
    const label = sanitize(t.name || `Track ${t.id}`);
    const tuning = _tuningLabel(t.tuning);
    const metaText = tuning ? `${tuning} · ${t.id}` : `Track ${t.id}`;
    const kindBadge = isGuitar ? 'GUITAR' : trackKindLabel(t.kind);

    const tab = document.createElement('div');
    tab.className = 'track-tab';
    tab.dataset.active = isPrimary ? '1' : '0';
    tab.dataset.trackId = t.id;
    tab.dataset.kind = isGuitar ? 'guitar' : String(t.kind).toLowerCase();
    // Tinted left border so every tab (guitars included) reads as part of the
    // same coloured family. Non-guitar tabs are dimmed a touch so the active
    // guitar still stands out.
    tab.style.borderLeft = `3px solid ${color}`;
    if (!isGuitar) tab.style.opacity = '0.92';

    const colorBar = document.createElement('div');
    colorBar.className = 'track-tab-color';
    colorBar.style.background = color;

    const body = document.createElement('div');
    body.className = 'track-tab-body';
    const badgeHTML = kindBadge
      ? `<span class="track-kind-badge" style="display:inline-block;`
        + `font-family:var(--mono);font-size:8.5px;font-weight:700;`
        + `letter-spacing:0.04em;padding:0 4px;margin-right:4px;border-radius:3px;`
        + `background:${color};color:#fff;vertical-align:1px;">`
        + `${kindStyle.glyph} ${sanitize(kindBadge)}</span>`
      : '';
    body.innerHTML =
      `<div class="track-tab-name">${badgeHTML}${label}</div>`
      + `<div class="track-tab-meta">${metaText}</div>`;

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

  // Wire the mouse-navigation handlers once, then refresh chevron visibility
  // after the new tabs have laid out.
  _wireTrackTabsNav();
  requestAnimationFrame(_updateTrackTabsChevrons);
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
    btnPlay.title = playing ? 'Pause' : 'Play';
    btnPlay.classList.toggle('is-playing', playing);
    // When the leather knob icon has been applied (icons.js inserts a child
    // span), setting textContent would wipe it — so only write the ▶/⏸ glyph
    // in the un-iconified fallback.
    if (!btnPlay.classList.contains('fw-iconified')) {
      btnPlay.textContent = playing ? '⏸' : '▶';
    }
  }
}

function _updateFollowButton() {
  if (!btnFollow) return;
  btnFollow.classList.toggle('active', _followPlayhead);
  btnFollow.title = _followPlayhead
    ? 'Following playhead (click to explore freely)'
    : 'Click to follow playhead again';
}

/**
 * Single source of truth for the "follow playhead" state. Propagates the flag
 * to BOTH scroll owners — the canvas engine (`playback._followPlayhead`, which
 * was previously never updated, so its click-to-explore comment never worked)
 * and the SVG driver (`_svgDriver.followPlayhead`) — then refreshes the button.
 * @param {boolean} on
 */
function _setFollowPlayhead(on) {
  _followPlayhead = on;
  if (playback) playback._followPlayhead = on;
  if (_svgDriver) _svgDriver.followPlayhead = on;
  _updateFollowButton();
}

if (btnFollow) {
  btnFollow.addEventListener('click', () => {
    _setFollowPlayhead(true);
    // Immediately recenter on the current playhead position.
    if (!playback || !renderer) return;
    // SVG (Staff / Mixed): the driver scrolls #core-svg-view. The canvas
    // geometry below does not apply (and #tab-container is no longer scrolled).
    if (playback.usesSvgCursor && _svgDriver) {
      _svgDriver.highlight(
        renderer.cursorMeasure || 0, playback.loopStart, playback.loopEnd,
      );
      return;
    }
    // Canvas (Tab): scroll #tab-container by system geometry.
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
    // Autoplay policy: the AudioContext was created (and possibly resumed)
    // outside a gesture during render, so it may still be suspended. This
    // click IS a user gesture, so resume here to guarantee sound on first
    // play (B1.3). enableAudio() also (re)kicks the synth load if needed.
    playback.resumeAudioContext();
    if (!playback.audioEnabled) playback.enableAudio();
    if (!playback.isPlaying) {
      _setFollowPlayhead(true);  // resume following when starting play
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

if (btnHeaderMusicXml) {
  // Default click = current track (unchanged). Shift/Alt-click or right-click
  // opens a small menu to choose current vs all tracks.
  btnHeaderMusicXml.addEventListener('click', (e) => {
    if (e.shiftKey || e.altKey) {
      e.preventDefault();
      _openMusicXmlScopeMenu(btnHeaderMusicXml);
    } else {
      exportMusicXML('current');
    }
  });
  btnHeaderMusicXml.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    _openMusicXmlScopeMenu(btnHeaderMusicXml);
  });
}

const btnRefreshFingerings = $('#set-refresh-fingerings');
const btnRefreshResume = $('#set-refresh-resume');
const btnRefreshForceSave = $('#set-refresh-force-save');
const btnRefreshStop = $('#set-refresh-stop');
const refreshWorkers = $('#set-refresh-workers');
const refreshWorkersValue = $('#set-refresh-workers-value');
const refreshFingeringsStatus = $('#set-refresh-fingerings-status');
const refreshProgressWrap = $('#set-refresh-progress-wrap');
const refreshProgress = $('#set-refresh-progress');
const refreshEta = $('#set-refresh-eta');

function _setRefreshRunning(running) {
  if (btnRefreshFingerings) btnRefreshFingerings.disabled = running;
  if (btnRefreshResume) btnRefreshResume.disabled = running;
  if (btnRefreshForceSave) btnRefreshForceSave.disabled = running;
  if (btnRefreshStop) { btnRefreshStop.style.display = running ? '' : 'none'; btnRefreshStop.disabled = false; }
  if (refreshWorkers) refreshWorkers.disabled = running;
  if (refreshProgressWrap) refreshProgressWrap.style.display = running ? '' : 'none';
}

function _refreshWorkerCount() {
  const raw = Number.parseInt(refreshWorkers?.value || '4', 10);
  return Math.max(1, Math.min(8, Number.isFinite(raw) ? raw : 4));
}

function _syncRefreshWorkersLabel() {
  const count = _refreshWorkerCount();
  if (refreshWorkers) refreshWorkers.value = String(count);
  if (refreshWorkersValue) refreshWorkersValue.textContent = String(count);
}

if (refreshWorkers) {
  _syncRefreshWorkersLabel();
  refreshWorkers.addEventListener('input', _syncRefreshWorkersLabel);
}

if (btnRefreshStop) {
  btnRefreshStop.addEventListener('click', async () => {
    btnRefreshStop.disabled = true;
    if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = 'Annulation en cours…';
    try { await fetch('/api/library/refresh-fingerings', { method: 'DELETE' }); } catch (_) {}
  });
}

async function _runRefreshFingerings({ confirmRun = true, forceOverride = null, confirmMessage = null } = {}) {
  if (confirmRun) {
    const ok = window.confirm(
      confirmMessage || (
        'Cette opération complète les fichiers <nom>_fingered.gp manquants ou périmés '
        + 'dans le dossier de partitions. Les originaux restent intacts. '
        + 'Sur de gros corpus ça peut prendre plusieurs minutes. Continuer ?'
      )
    );
    if (!ok) return;
  }
  _setRefreshRunning(true);
  if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = 'Démarrage…';
  if (refreshProgress) { refreshProgress.value = 0; refreshProgress.max = 100; }
  if (refreshEta) refreshEta.textContent = '';
  try {
    const forceChecked = forceOverride ?? ($('#set-refresh-force')?.checked ?? false);
    const params = new URLSearchParams({ workers: String(_refreshWorkerCount()) });
    if (forceChecked) params.set('force', 'true');
    const refreshUrl = `/api/library/refresh-fingerings?${params.toString()}`;
    const res = await fetch(refreshUrl, { method: 'POST' });
    if (!res.ok || !res.body) {
      throw new Error(`HTTP ${res.status}`);
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    let okCount = 0;
    let errCount = 0;
    let totalFiles = 0;
    let toProcess = 0;
    let preSkipped = 0;
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
          totalFiles = msg.total_files || 0;
          toProcess = msg.to_process || 0;
          preSkipped = msg.pre_skipped || 0;
          const progressMax = totalFiles || toProcess || 1;
          if (refreshProgress) { refreshProgress.max = progressMax; refreshProgress.value = preSkipped; }
          const preSkipTxt = preSkipped > 0 ? `, ${preSkipped} déjà à jour` : '';
          if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
            `${preSkipped} / ${progressMax} traités${preSkipTxt} — ${toProcess} à faire (${msg.workers} workers)`;
        } else if (msg.event === 'done') {
          const preSkip = msg.pre_skipped ?? preSkipped;
          const doneTotal = preSkip + (msg.ok || 0) + (msg.errors || 0) + (msg.skipped || 0);
          const progressMax = totalFiles || doneTotal || 1;
          const preSkipTxt = preSkip > 0 ? `, ${preSkip} déjà à jour` : '';
          const avgTxt = msg.avg_s ? ` — ${msg.avg_s}s/fichier` : '';
          if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
            `Terminé : ${doneTotal} / ${progressMax} — ${msg.ok} OK, ${msg.errors} erreurs, ${msg.skipped} ignorés${preSkipTxt}${avgTxt}.`;
          if (refreshProgress) { refreshProgress.max = progressMax; refreshProgress.value = progressMax; }
          if (refreshEta) refreshEta.textContent = '';
        } else if (msg.event === 'cancelled') {
          const doneTotal = preSkipped + (msg.ok || 0) + (msg.errors || 0) + (msg.skipped || 0);
          const progressMax = totalFiles || doneTotal || 1;
          if (refreshProgress) { refreshProgress.max = progressMax; refreshProgress.value = doneTotal; }
          if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
            `Annulé — ${doneTotal} / ${progressMax} traités (${msg.ok} OK, ${msg.errors} erreurs, ${preSkipped} déjà à jour). Cliquez sur Reprise pour continuer.`;
          if (refreshEta) refreshEta.textContent = '';
          if (btnRefreshResume) btnRefreshResume.style.display = '';
        } else if (msg.status) {
          if (msg.status === 'ok') okCount++;
          if (msg.status === 'error') errCount++;
          // Pool results have "done"; pre-skipped lines don't.
          if (msg.done != null) {
            const doneTotal = preSkipped + msg.done;
            const progressMax = totalFiles || toProcess || 1;
            if (refreshProgress) { refreshProgress.max = progressMax; refreshProgress.value = doneTotal; }
            const pct = progressMax > 0 ? ` (${Math.round((doneTotal / progressMax) * 100)}%)` : '';
            if (refreshFingeringsStatus) refreshFingeringsStatus.textContent =
              `${doneTotal} / ${progressMax}${pct}  (${okCount} OK, ${errCount} err, ${preSkipped} déjà à jour) — ${msg.file}`;
            if (refreshEta) {
              if (msg.eta_s != null) {
                const m = Math.floor(msg.eta_s / 60);
                const s = msg.eta_s % 60;
                const etaTxt = m > 0 ? `${m}m ${s}s` : `${s}s`;
                const avgTxt = msg.avg_s ? `${msg.avg_s}s/fichier · ` : '';
                refreshEta.textContent = `${avgTxt}ETA : ${etaTxt}`;
              } else if (msg.avg_s) {
                refreshEta.textContent = `${msg.avg_s}s/fichier`;
              }
            }
          }
        }
      }
    }
  } catch (err) {
    if (refreshFingeringsStatus) refreshFingeringsStatus.textContent = `Erreur : ${err.message}`;
  } finally {
    _setRefreshRunning(false);
  }
}

if (btnRefreshFingerings) {
  btnRefreshFingerings.addEventListener('click', () => {
    if (btnRefreshResume) btnRefreshResume.style.display = 'none';
    _runRefreshFingerings({ confirmRun: true });
  });
}

if (btnRefreshForceSave) {
  btnRefreshForceSave.addEventListener('click', () => {
    if (btnRefreshResume) btnRefreshResume.style.display = 'none';
    _runRefreshFingerings({
      confirmRun: true,
      forceOverride: true,
      confirmMessage:
        'Cette opération recalculera TOUS les fichiers .gp du dossier de partitions '
        + 'et remplacera leurs fichiers <nom>_fingered.gp. Les originaux .gp restent intacts. Continuer ?',
    });
  });
}

if (btnRefreshResume) {
  btnRefreshResume.addEventListener('click', () => {
    btnRefreshResume.style.display = 'none';
    _runRefreshFingerings({ confirmRun: false, forceOverride: false });
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
    // Remember the user's explicit choice while on a guitar track so it can
    // be restored after a detour through a non-guitar track. Recorded before
    // re-solving, since selectTrack reads _lastGuitarMode at its top.
    if (_isCurrentTrackGuitar()) {
      _lastGuitarMode = selRepresentationMode.value || DEFAULT_MODE;
    }
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
    // Ignore clicks on a pill locked for the current (non-guitar) track.
    if (btn.disabled || btn.classList.contains('view-seg-disabled')) return;
    selRepresentationMode.value = btn.dataset.mode;
    selRepresentationMode.dispatchEvent(new Event('change'));
  });
});

_syncViewSegPills();

if (prefSameFingerPenalty) {
  prefSameFingerPenalty.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      _notesCache.clear();
      _solveCache.clear();
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

if (prefInferLegato) {
  prefInferLegato.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      _notesCache.clear();
      _solveCache.clear();
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
  const payload = _buildHandVizPayload();
  if (!payload) return;
  const message = { type: 'fretwise-hand-data', payload };
  if (handVizFrame && handVizFrame.contentWindow) {
    handVizFrame.contentWindow.postMessage(message, '*');
  }
  if (handVizPopupWindow && !handVizPopupWindow.closed) {
    handVizPopupWindow.postMessage(message, '*');
  }
  // After reinstalling data, also push current time so the iframe starts
  // at the right place instead of t=0.
  _postHandVizTime();
}

function _reloadHandVizFrame() {
  if (!handVizFrame) return;
  handVizFrame.src = `/static/hand_viz.html?v=${Date.now()}`;
}

function _postHandVizTime() {
  const panelVisible = handVizPanel && handVizPanel.style.display !== 'none';
  const popupVisible = handVizPopupWindow && !handVizPopupWindow.closed;
  if (!panelVisible && !popupVisible) return;
  if (!playback || typeof playback.getCurrentTimeSec !== 'function') return;
  const message = {
    type: 'fretwise-hand-seek',
    t: playback.getCurrentTimeSec(),
    playing: !!playback.isPlaying,
  };
  if (panelVisible && handVizFrame && handVizFrame.contentWindow) {
    handVizFrame.contentWindow.postMessage(message, '*');
  }
  if (popupVisible) handVizPopupWindow.postMessage(message, '*');
}

function _openHandVizPopup() {
  const features = 'popup=yes,width=760,height=680,left=80,top=40,resizable=yes,scrollbars=yes';
  if (!handVizPopupWindow || handVizPopupWindow.closed) {
    handVizPopupWindow = window.open(`/static/hand_viz.html?v=${Date.now()}`, 'fretwise-hand-viz', features);
  } else {
    handVizPopupWindow.focus();
  }
  setTimeout(_postHandVizData, 350);
  setTimeout(_postHandVizTime, 450);
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
if (handVizPopout) handVizPopout.addEventListener('click', _openHandVizPopup);

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
    const rect = handVizPanel.getBoundingClientRect();
    const x = Math.max(12 - rect.width, Math.min(window.innerWidth - 48, e.clientX - drag.dx));
    const y = Math.max(4, Math.min(window.innerHeight - 48, e.clientY - drag.dy));
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

// ── Song metadata workflow (enrich catalog via the user's own LLM) ──────────
//
// Three-step flow: export the song list (JSON) → run the LLM prompt in your own
// LLM → import the LLM's JSON output to merge titles/artists/etc. into the
// catalog. Endpoints are owned by the backend; we degrade gracefully on errors.

let _metaDropdown = null;

function _closeMetaDropdown() {
  if (_metaDropdown) { _metaDropdown.remove(); _metaDropdown = null; }
  const btn = $('#lib-meta-btn');
  if (btn) btn.setAttribute('aria-expanded', 'false');
}

function _setMetaStatus(msg, kind) {
  const el = $('#lib-meta-status');
  if (!el) return;
  el.textContent = msg || '';
  el.style.color = kind === 'error' ? '#ff5555' : kind === 'ok' ? '#4caf50' : '#888';
}

async function _metaDownloadSongList() {
  _setMetaStatus('Preparing song list…');
  try {
    const { blob, filename } = await fetchSongListDownload();
    _downloadBlob(blob, filename);
    _setMetaStatus(`✓ Downloaded ${filename}`, 'ok');
  } catch (err) {
    _setMetaStatus(`✗ ${err.message || err}`, 'error');
  }
}

async function _metaDownloadPrompt() {
  _setMetaStatus('Preparing prompt…');
  try {
    const { blob, filename } = await fetchLlmPrompt();
    _downloadBlob(blob, filename);
    _setMetaStatus(`✓ Downloaded ${filename}`, 'ok');
  } catch (err) {
    _setMetaStatus(`✗ ${err.message || err}`, 'error');
  }
}

async function _metaImportMetadata(file) {
  if (!file) return;
  _setMetaStatus(`Importing ${file.name}…`);
  let parsed;
  try {
    const text = await file.text();
    parsed = JSON.parse(text);
  } catch (_err) {
    _setMetaStatus('✗ Could not read file: invalid JSON', 'error');
    return;
  }
  try {
    const res = await importSongMetadata(parsed);
    const updated = res.updated ?? 0;
    const added = res.added ?? 0;
    const total = res.total ?? 0;
    _setMetaStatus(
      `✓ Catalog updated: ${updated} updated, ${added} added (${total} total)`,
      'ok',
    );
    await loadFiles();
  } catch (err) {
    _setMetaStatus(`✗ ${err.message || err}`, 'error');
  }
}

function _openMetaDropdown(anchorBtn) {
  _closeMetaDropdown();
  const dd = document.createElement('div');
  dd.className = 'instr-dropdown lib-meta-menu';
  dd.setAttribute('role', 'menu');

  const items = [
    { label: '1. Download song list (JSON)', action: _metaDownloadSongList },
    { label: '2. Download LLM prompt', action: _metaDownloadPrompt },
    {
      label: '3. Import metadata (JSON)…',
      action: () => {
        const input = $('#lib-meta-import-input');
        if (input) input.click();
      },
    },
  ];

  for (const item of items) {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'instr-item';
    btn.setAttribute('role', 'menuitem');
    btn.textContent = item.label;
    btn.addEventListener('click', () => {
      _closeMetaDropdown();
      item.action();
    });
    dd.appendChild(btn);
  }

  document.body.appendChild(dd);
  _metaDropdown = dd;
  anchorBtn.setAttribute('aria-expanded', 'true');

  const rect = anchorBtn.getBoundingClientRect();
  let left = rect.left;
  let top = rect.bottom + 4;
  if (left + 240 > window.innerWidth) left = window.innerWidth - 248;
  if (top + 160 > window.innerHeight) top = rect.top - 164;
  dd.style.left = `${left}px`;
  dd.style.top = `${top}px`;

  setTimeout(() => {
    document.addEventListener('click', _closeMetaDropdown, { once: true });
  }, 0);
}

const metaBtn = $('#lib-meta-btn');
if (metaBtn) {
  metaBtn.addEventListener('click', (e) => {
    e.stopPropagation();
    if (_metaDropdown) { _closeMetaDropdown(); return; }
    _openMetaDropdown(metaBtn);
  });
}

const metaImportInput = $('#lib-meta-import-input');
if (metaImportInput) {
  metaImportInput.addEventListener('change', async () => {
    const file = metaImportInput.files[0];
    await _metaImportMetadata(file);
    metaImportInput.value = '';
  });
}

// ── Audio autoplay-policy unlock ────────────────────────────────────
//
// Browsers create the AudioContext in a "suspended" state and refuse to
// resume() it outside a user gesture. We enable audio during render (no
// gesture), so without this the very first playback is silent (B1.3). A
// one-shot capture-phase listener on the first real user interaction resumes
// the context (and re-kicks the synth load if it failed before any gesture).
function _unlockAudioOnFirstGesture() {
  if (playback) {
    playback.resumeAudioContext();
    if (!playback.audioEnabled) playback.enableAudio();
  }
}
['pointerdown', 'keydown', 'touchstart'].forEach((evt) => {
  document.addEventListener(evt, _unlockAudioOnFirstGesture, {
    capture: true, passive: true,
  });
});

// ── Keyboard shortcuts ──────────────────────────────────────────────

document.addEventListener('keydown', (e) => {
  if (!playback) return;
  if (e.target.tagName === 'INPUT' || e.target.tagName === 'SELECT') return;

  switch (e.key) {
    case ' ':
      e.preventDefault();
      playback.resumeAudioContext();
      if (!playback.audioEnabled) playback.enableAudio();
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
    _updateTrackTabsChevrons();
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
  // SVG views (Staff / Mixed): the canvas + its red line are hidden and the
  // SvgCursorDriver draws the real cursor (_tickSvgCursor) and owns scrolling.
  // Skip entirely — otherwise this would run a canvas-geometry window scroll
  // off the hidden canvas, fighting the SVG scroll and shoving it out of frame.
  if (playback.usesSvgCursor) return;

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

// ── Settings page navigation ────────────────────────────────────────
const setBackViewerBtn = $('#set-back-viewer');
if (setBackViewerBtn) {
  setBackViewerBtn.addEventListener('click', () => {
    if (currentTrackId != null && currentFile != null) {
      showPage('viewer');
    }
  });
}

const setBackFilesBtn = $('#set-back-files');
if (setBackFilesBtn) {
  setBackFilesBtn.addEventListener('click', () => {
    loadFiles();
  });
}

async function _renderCloudStatus(me) {
  const section = $('#settings-cloud-section');
  const statusEl = $('#cloud-status');
  const connectBtn = $('#cloud-connect-gdrive');
  const disconnectBtn = $('#cloud-disconnect');
  const signinLink = $('#cloud-signin');
  if (!section) return;
  // Single-user mode (no auth): /api/me unavailable → keep section hidden.
  if (!me || !me.authenticated) { section.style.display = 'none'; return; }
  section.style.display = '';
  const connected = !!me.has_storage && !!me.storage_backend;
  if (connected) {
    statusEl.textContent = `✓ Connected: ${me.storage_backend}` +
      (me.email ? ` (${me.email})` : '');
    connectBtn.style.display = 'none';
    signinLink.style.display = 'none';
    disconnectBtn.style.display = '';
  } else {
    statusEl.textContent = 'No storage connected yet — connect your Google Drive to load and save scores.';
    disconnectBtn.style.display = 'none';
    const canGdrive = (me.available_backends || []).includes('gdrive');
    connectBtn.style.display = canGdrive ? '' : 'none';
    signinLink.style.display = 'none';
  }
}

async function _initCloudStorage() {
  let me = null;
  try { me = await fetchMe(); } catch (_e) { me = null; }
  await _renderCloudStatus(me);

  // Sign-out button: shown only when authenticated (multi-user mode). Lets the
  // user log out of Google so they can sign in as the local admin instead.
  const logoutBtn = $('#btn-logout');
  if (logoutBtn) {
    if (me && me.authenticated) {
      logoutBtn.style.display = '';
      logoutBtn.title = me.email ? `Se déconnecter (${me.email})` : 'Se déconnecter';
      if (!logoutBtn.dataset.wired) {
        logoutBtn.dataset.wired = '1';
        logoutBtn.addEventListener('click', () => { window.location.href = '/auth/logout'; });
      }
    } else {
      logoutBtn.style.display = 'none';
    }
  }

  const connectBtn = $('#cloud-connect-gdrive');
  const disconnectBtn = $('#cloud-disconnect');
  const signinLink = $('#cloud-signin');
  const msg = $('#cloud-status-msg');

  if (connectBtn && !connectBtn.dataset.wired) {
    connectBtn.dataset.wired = '1';
    connectBtn.addEventListener('click', async () => {
      if (msg) msg.textContent = 'Connecting to Google Drive…';
      connectBtn.disabled = true;
      try {
        await connectStorage('gdrive');
        if (msg) msg.textContent = '✓ Connected.';
        await _renderCloudStatus(await fetchMe());
        await loadFiles();
      } catch (err) {
        if (msg) msg.textContent = '✗ ' + err.message;
        // Needs a Google sign-in (Drive permission) first.
        if (signinLink && /sign in with google/i.test(err.message || '')) {
          signinLink.style.display = '';
        }
      } finally {
        connectBtn.disabled = false;
      }
    });
  }

  if (disconnectBtn && !disconnectBtn.dataset.wired) {
    disconnectBtn.dataset.wired = '1';
    disconnectBtn.addEventListener('click', async () => {
      if (msg) msg.textContent = 'Disconnecting…';
      disconnectBtn.disabled = true;
      try {
        await disconnectStorage();
        if (msg) msg.textContent = 'Disconnected.';
        await _renderCloudStatus(await fetchMe());
      } catch (err) {
        if (msg) msg.textContent = '✗ ' + err.message;
      } finally {
        disconnectBtn.disabled = false;
      }
    });
  }
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

  await _initCloudStorage();

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
// Swap built-in button glyphs for the metallic knob icon set. Async + best
// effort; the static header/toolbar buttons already exist (this module is
// deferred), so a single pass covers them.
applyLeatherIcons();

// Fingering-review panel (continuous improvement). Reads live app state via
// getters; `reload` clears the client solve cache and re-runs the current
// track so a saved choice is reflected immediately.
initReview({
  getFile: () => currentFile,
  getTrackId: () => currentTrackId,
  isGuitar: () => _isCurrentTrackGuitar(),
  reload: async () => {
    _solveCache.clear();
    if (currentTrackId != null) await selectTrack(currentTrackId, _reviewTrackName);
  },
});
