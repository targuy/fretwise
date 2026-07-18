/**
 * main.js — App initialization, page routing, event wiring
 *
 * Pages:  file-selector → track-selector → tab-viewer
 * Orchestra: renderer + playback + toolbar
 */

import { activateRigProfile, activateSoundfont, cleanupLibrary, connectStorage, deleteSoundfont, disconnectStorage, downloadFile, fetchExportGp, fetchExportMusicXml, fetchExportMusicXmlAll, fetchExportPdf, fetchFiles, fetchGearVerificationPrompt, fetchGmInstruments, fetchLlmPrompt, fetchMe, fetchNotes, fetchSettings, fetchSongInfo, fetchSolve, fetchSongListDownload, fetchSoundfonts, fetchStorage, fetchTracks, fetchSaveGp, fetchRig, fetchRigBank, fetchRigMidiOutputs, recommendRigProfile, saveGearSheet, saveRigBinding, saveRigProfile, importSongMetadata, saveSettings, uploadFile, uploadSoundfont } from './api.js';
import { getMaskedMeasures, renderAuditBanner, resetAuditBanner, statusBanner } from './audit.js';
import { TabRenderer, buildLegendHTML } from './renderer.js';
import { SlopeRenderer } from './slope-renderer.js';
import { PlaybackEngine } from './playback.js';
import { SvgCursorDriver } from './svg-playback.js';
import { task as notifyTask, toast as notifyToast } from './notify.js';
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
let _slopeRenderer = null;
// Slope legibility sub-mode (P1–P4), persisted across sessions/tracks.
const _SLOPE_MODE_KEY = 'fretwise.slopeMode';
const _SLOPE_MODES = ['base', 'p1', 'p2', 'p3', 'p4'];
let _slopeMode = (() => {
  try {
    const v = localStorage.getItem(_SLOPE_MODE_KEY);
    return _SLOPE_MODES.includes(v) ? v : 'p1';
  } catch (_) { return 'p1'; }
})();
const _slopeModeSeg = document.getElementById('slope-mode-seg');
// P2 — density: how many beats of upcoming notes the Slope view shows at once.
// Persisted like the mode; applies regardless of which sub-mode is active
// (a slower glide helps P1's moving discs too, not just P2's own readout).
const _SLOPE_DENSITY_KEY = 'fretwise.slopeDensity';
const _SLOPE_DENSITY_MIN = 24;
const _SLOPE_DENSITY_MAX = 48;
let _slopeDensity = (() => {
  try {
    const v = Number(localStorage.getItem(_SLOPE_DENSITY_KEY));
    return Number.isFinite(v) && v >= _SLOPE_DENSITY_MIN && v <= _SLOPE_DENSITY_MAX ? v : 24;
  } catch (_) { return 24; }
})();
const _slopeDensityCtrl = document.getElementById('slope-density-ctrl');
const _rngSlopeDensity = document.getElementById('rng-slope-density');
if (_rngSlopeDensity) _rngSlopeDensity.value = String(_slopeDensity);
let playback = null;
let _svgDriver = null;  // SvgCursorDriver instance for standard/standard+tab views
let loopASet = false;  // has A marker been set
let soundOn = false;   // tracks mute state across track changes
const _notesCache = new Map(); // key: `${file}#${trackId}` → /api/notes response
const _RIG_MIDI_OUTPUT_SESSION_KEY = 'fretwise.rigMidiOutput';
let _lastRigMidiOutput = _readSessionValue(_RIG_MIDI_OUTPUT_SESSION_KEY);
// Client-side solve cache: key `${file}#${trackId}#${mode}#${prefsKey}` →
// /api/solve response. Avoids re-hitting the network (and re-deserialising a
// large payload) when the user flips back to a track/mode already viewed.
const _solveCache = new Map();
// key: primaryTrackId → Set<secondaryTrackId> — tracks explicitly muted by the user
const _mutedSecondaryTracks = new Map();
// Files discovered (via solve) to have chord diagrams embedded — used for the
// library chord badge. Progressive: only populated after a solve has been seen.
const _chordFilesSet = new Set();

// Calibrated baseline zoom per view — these are the "zero" reference points baked
// in from user calibration. The slider always shows offset from this baseline.
const _ZOOM_BASE = {
  [MODES.STANDARD]:           20,   // Staff  : +20 %
  [MODES.STANDARD_TABLATURE]: 40,   // Mixed  : +40 %
  [MODES.TABLATURE]:          -5,   // Tab    :  -5 %
  [MODES.TABLATURE_RHYTHM]:   -5,   // Tab+Rhythm : same as Tab
  [MODES.SLOPE]:               0,   // Slope  : full-canvas perspective view
  [MODES.HAND_3D]:             0,   // 3D     : dedicated hand/guitar view
};
// User slider offset relative to each view's baseline (-50 to +50).
const _viewZoom = {};

/** Stable cache key for a solve request (file, track, mode, rule prefs, svgWidth). */
function _solveCacheKey(file, trackId, mode, prefs, svgWidth) {
  const p = prefs || {};
  const prefsKey = `${p.sameFingerPenalty !== false ? 1 : 0}`
    + `:${p.inferImplicitLegato !== false ? 1 : 0}`;
  const wKey = svgWidth ? `@${svgWidth}` : '';
  return `${file}#${trackId}#${mode}#${prefsKey}${wKey}`;
}

/**
 * Return the SVG render width to request for staff/mixed views: nearest-50px
 * bucket of (innerWidth minus #core-svg-view horizontal padding).  Returns
 * undefined for canvas-only modes (tablature, tablature_rhythm) where the
 * backend never generates a core SVG.
 */
function _svgRenderWidth(mode) {
  // Canvas-only modes: no SVG is generated, width is irrelevant.
  if (mode === MODES.TABLATURE || mode === MODES.TABLATURE_RHYTHM
      || mode === MODES.SLOPE || mode === MODES.HAND_3D) return undefined;
  const base = _ZOOM_BASE[mode] ?? 0;          // fallback 0 if unknown mode
  const factor = 1 + ((base + (_viewZoom[mode] ?? 0)) / 100);
  const w = Math.round((window.innerWidth - 48) / factor / 50) * 50;
  // Guard against NaN / non-finite values from unknown modes or extreme zoom.
  return Number.isFinite(w) && w >= 400 ? w : undefined;
}

/** Slope and 3D are frontend-only views; the backend payload is the tablature solve. */
function _backendRepresentationMode(mode) {
  return (mode === MODES.SLOPE || mode === MODES.HAND_3D) ? MODES.TABLATURE : mode;
}

/**
 * Solve with a client-side cache. The first call for a (file, track, mode,
 * prefs, svgWidth) tuple hits the network; subsequent calls return the cached
 * payload synchronously-fast. The server keeps its own LRU cache, but reusing
 * the parsed JS object also skips re-deserialising a large payload on every tab switch.
 */
async function _cachedSolve(file, trackId, mode, prefs, svgWidth) {
  const key = _solveCacheKey(file, trackId, mode, prefs, svgWidth);
  if (_solveCache.has(key)) return _solveCache.get(key);
  const data = await fetchSolve(file, trackId, mode, prefs, svgWidth);
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
const slopeCanvas   = $('#slope-canvas');
const hand3dViewFrame = $('#hand3d-view-frame');
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
const rngZoom       = $('#rng-zoom');
const zoomLabel     = $('#zoom-label');
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

function _speedMultiplier() {
  const raw = selSpeed ? parseInt(selSpeed.value, 10) : 100;
  return Math.max(0.1, Math.min(2.0, (Number.isFinite(raw) ? raw : 100) / 100));
}

function _effectiveTempo(baseTempo) {
  const tempo = Number(baseTempo ?? playback?.tempo ?? renderer?.tempo ?? 120) || 120;
  return Math.round(tempo * _speedMultiplier());
}

function _setTempoText(baseTempo) {
  const tempo = Math.round(Number(baseTempo ?? playback?.tempo ?? renderer?.tempo ?? 120) || 120);
  const effective = _effectiveTempo(tempo);
  const tempoStr = `♩ = ${tempo}`;
  if (metaTempo) metaTempo.textContent = tempoStr;
  if (headerMetaTempo) headerMetaTempo.textContent = tempoStr;
  if (bpmInput) {
    bpmInput.value = effective;
    bpmInput.title = effective === tempo
      ? `BPM: ${tempo}`
      : `BPM effectif: ${effective} (tempo ${tempo} x ${Math.round(_speedMultiplier() * 100)}%)`;
  }
}

// Header extras
const headerMeta       = $('#header-meta');
const headerMetaTitle  = $('#header-meta-title');
const headerMetaTrack  = $('#header-meta-track');
const headerMetaTempo  = $('#header-meta-tempo');
const btnHeaderBack    = $('#btn-header-back');
const btnHeaderPdf     = $('#btn-header-pdf');
const btnHeaderGp      = $('#btn-header-gp');
const btnHeaderSave    = $('#btn-header-save');
const btnHeaderMusicXml = $('#btn-header-musicxml');

// Header
const btnLegend     = $('#btn-legend');
const legendOverlay = $('#legend-overlay');
const legendClose   = $('#legend-close');
const btnInsertFingerings  = $('#btn-insert-fingerings');
const btnRig               = $('#btn-rig');
const rigPanel             = $('#rig-panel');
let _hand3dFrameLoaded = false;
const HAND_VIZ_SEEK_POST_MS = 1000 / 60;
let _lastHandVizSeekPostMs = 0;

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
// Multi-select state for batch fingering calculation
let _selectedFiles = new Set();
// Pagination: rows per page adapts to viewport height at load time.
// Header=44px, sticky strip≈90px, toolbar≈52px, row≈44px.
function _computeLibPageSize() {
  const strip = document.getElementById('lib-sticky-strip');
  const stripH = strip ? strip.offsetHeight : 90;
  const available = window.innerHeight - 44 - stripH - 52;
  return Math.max(5, Math.floor(available / 44));
}
let LIB_PAGE_SIZE = 15; // updated after DOMContentLoaded via _initLibPageSize()
function _initLibPageSize() { LIB_PAGE_SIZE = _computeLibPageSize(); }
let _libPage = 0;
let _libRows = [];   // the full filtered+sorted set (page is a slice of this)

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
    _libRows = [];
    _renderAzBar([]);
    _renderPager(0);
    return;
  }
  if (empty) empty.style.display = 'none';

  // Paginate: keep the whole filtered+sorted set in _libRows (so the A–Z bar and
  // letter-jump can address rows on other pages) and render only the current
  // page slice of LIB_PAGE_SIZE rows.
  _libRows = rows;
  const pageCount = Math.max(1, Math.ceil(rows.length / LIB_PAGE_SIZE));
  if (_libPage > pageCount - 1) _libPage = pageCount - 1;
  if (_libPage < 0) _libPage = 0;
  const pageRows = rows.slice(_libPage * LIB_PAGE_SIZE, _libPage * LIB_PAGE_SIZE + LIB_PAGE_SIZE);

  tbody.innerHTML = '';
  for (const f of pageRows) {
    const tr = document.createElement('tr');
    tr.className = 'lib-row';
    tr.dataset.file = f.name;
    tr.dataset.sortkey = _libNavKey(f);

    const title = f.meta?.title || f.stem || f.name;
    const artist = f.meta?.artist || '—';
    const genre = f.meta?.genre || '—';
    const year = f.meta?.year || '—';
    const format = f.format || '?';

    const isGpFile = f.name.endsWith('.gp');
    const hasFingering = isGpFile && f.has_fingering;
    const isCurrent = hasFingering && f.fingering_is_current;
    const isChecked = _selectedFiles.has(f.name);
    // Distinctive hand icon marks partitions that carry saved fingerings:
    // green = up to date, amber (with ⚠) = made by an older algorithm version.
    const handIcon = '<svg class="lib-finger-ic" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><path d="M18 11V6a2 2 0 00-4 0v5"/><path d="M14 10V4a2 2 0 00-4 0v6"/><path d="M10 10.5V6a2 2 0 00-4 0v8"/><path d="M6 14v1a6 6 0 0012 0v-2"/></svg>';
    const fingerBadge = !isGpFile || !hasFingering ? '' :
      isCurrent
        ? `<span class="lib-finger-mark is-ok" title="Doigtés enregistrés, à jour (algo v${FINGERING_ALGO_VERSION || '?'})" aria-label="Doigtés à jour">${handIcon}</span>`
        : `<span class="lib-finger-mark is-old" title="Doigtés enregistrés avec une version antérieure de l'algorithme — recalculer recommandé" aria-label="Doigtés obsolètes">${handIcon}<span class="lib-finger-warn">⚠</span></span>`;
    // Chord diagram badge — shown when a previous solve revealed embedded chords
    const chordIcon = '<svg class="lib-chord-ic" width="13" height="13" viewBox="0 0 13 13" fill="none" xmlns="http://www.w3.org/2000/svg"><line x1="3" y1="1" x2="3" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="6.5" y1="1" x2="6.5" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="10" y1="1" x2="10" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="3.5" x2="12" y2="3.5" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="7" x2="12" y2="7" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="10.5" x2="12" y2="10.5" stroke="currentColor" stroke-width="1.2"/><circle cx="3" cy="7" r="1.6" fill="currentColor"/><circle cx="6.5" cy="3.5" r="1.6" fill="currentColor"/><circle cx="10" cy="10.5" r="1.6" fill="currentColor"/></svg>';
    const chordBadge = _chordFilesSet.has(f.name)
      ? `<span class="lib-chord-mark" title="Contient des diagrammes d'accords" aria-label="Accords">${chordIcon}</span>`
      : '';

    tr.innerHTML = `
      <td class="lib-cell-check"><input type="checkbox" class="lib-row-check" data-file="${_esc(f.name)}" ${isChecked ? 'checked' : ''} aria-label="Sélectionner ${_esc(title)}"></td>
      <td class="lib-cell-title"><span class="lib-title-text">${_esc(title)}</span>${fingerBadge}${chordBadge}</td>
      <td class="lib-cell-artist">${_esc(artist)}</td>
      <td class="lib-cell-genre"><span class="lib-badge lib-badge-genre">${_esc(genre)}</span></td>
      <td class="lib-cell-year">${_esc(String(year))}</td>
      <td class="lib-cell-format"><span class="lib-badge lib-badge-fmt">${_esc(format)}</span></td>
      <td class="lib-cell-actions">
        <button class="lib-btn-info" title="Song info" data-file="${_esc(f.name)}">ℹ</button>
        <button class="lib-btn-rig" title="Profil GP-180" data-file="${_esc(f.name)}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"><rect x="2" y="8" width="20" height="10" rx="2"/><path d="M6 8V6a2 2 0 012-2h8a2 2 0 012 2v2"/><circle cx="8" cy="13" r="1.5" fill="currentColor"/><circle cx="13" cy="13" r="1.5" fill="currentColor"/><circle cx="18" cy="13" r="1.5" fill="currentColor"/></svg></button>
        <button class="lib-btn-dl" title="Download ${_esc(f.name)}" data-file="${_esc(f.name)}">⬇</button>
      </td>
    `;

    const _rigBtn = tr.querySelector('.lib-btn-rig');
    if (_rigBtn) {
      _rigBtn.addEventListener('click', async (e) => {
        e.stopPropagation();
        if (rigPanel) {
          rigPanel.style.display = 'flex';
          if (btnRig) btnRig.classList.add('tb-btn-active');
          await _loadRig(f.name);
        }
      });
    }

    tr.querySelector('.lib-row-check').addEventListener('change', (e) => {
      e.stopPropagation();
      if (e.target.checked) _selectedFiles.add(f.name);
      else _selectedFiles.delete(f.name);
      _updateSelectionBar();
    });

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
  _renderPager(pageCount);
  // After layout settles, push the sticky strip height down to CSS so the
  // table's sticky <thead> stacks under it without overlap.
  requestAnimationFrame(_updateStickyOffsets);
}

/**
 * Render the page navigation into the search bar. The filtered+sorted set lives
 * in `_libRows`; we only ever render a 15-row slice (LIB_PAGE_SIZE), so without
 * this control the user could never reach songs past the first page.
 */
function _renderPager(pageCount) {
  const pager = document.getElementById('lib-pager');
  if (!pager) return;
  if (!pageCount || pageCount <= 1) {
    pager.innerHTML = '';
    pager.style.display = 'none';
    return;
  }
  pager.style.display = '';
  const cur = _libPage + 1; // 1-based for display
  pager.innerHTML = `
    <button class="lib-pager-btn" id="lib-pager-first" ${_libPage <= 0 ? 'disabled' : ''} title="Première page" aria-label="Première page">«</button>
    <button class="lib-pager-btn" id="lib-pager-prev" ${_libPage <= 0 ? 'disabled' : ''} title="Page précédente" aria-label="Page précédente">‹</button>
    <span class="lib-pager-info">${cur} / ${pageCount}</span>
    <button class="lib-pager-btn" id="lib-pager-next" ${_libPage >= pageCount - 1 ? 'disabled' : ''} title="Page suivante" aria-label="Page suivante">›</button>
    <button class="lib-pager-btn" id="lib-pager-last" ${_libPage >= pageCount - 1 ? 'disabled' : ''} title="Dernière page" aria-label="Dernière page">»</button>
  `;
  const go = (p) => {
    const clamped = Math.max(0, Math.min(pageCount - 1, p));
    if (clamped === _libPage) return;
    _libPage = clamped;
    _renderLibTable();
    // Scroll the page back to the top of the file-selector (sticky elements
    // are already "in view" per the browser so scrollIntoView is a no-op on them).
    window.scrollTo({ top: 0, behavior: 'instant' });
  };
  pager.querySelector('#lib-pager-first')?.addEventListener('click', () => go(0));
  pager.querySelector('#lib-pager-prev')?.addEventListener('click', () => go(_libPage - 1));
  pager.querySelector('#lib-pager-next')?.addEventListener('click', () => go(_libPage + 1));
  pager.querySelector('#lib-pager-last')?.addEventListener('click', () => go(pageCount - 1));
}

// ── Library multi-select + batch fingering calculation ───────────────────────

// Algo version must match FINGERING_ALGO_VERSION in app.py (bumped on pipeline changes).
const FINGERING_ALGO_VERSION = '2.1';

function _updateSelectionBar() {
  const bar = $('#lib-selection-bar');
  const countEl = $('#lib-selection-count');
  const checkAll = $('#lib-check-all');
  const n = _selectedFiles.size;
  if (bar) bar.style.display = n > 0 ? '' : 'none';
  if (countEl) countEl.textContent = `${n} fichier${n > 1 ? 's' : ''} sélectionné${n > 1 ? 's' : ''}`;
  if (checkAll) {
    const visibleGpFiles = _allFiles.filter(f => f.name.endsWith('.gp'));
    checkAll.indeterminate = n > 0 && n < visibleGpFiles.length;
    checkAll.checked = n > 0 && n >= visibleGpFiles.length;
  }
}

function _clearSelection() {
  _selectedFiles.clear();
  document.querySelectorAll('.lib-row-check').forEach(cb => { cb.checked = false; });
  _updateSelectionBar();
}

async function _calcFingeringsForSelected() {
  const files = [..._selectedFiles];
  if (!files.length) return;
  const statusEl = $('#lib-calc-status');
  const btn = $('#lib-btn-calc-fingerings');
  if (btn) btn.disabled = true;
  const total = files.length;
  let ok = 0, err = 0, done = 0;
  const _t = notifyTask('Calcul des doigtés (lot)…', { progress: 0 });
  // Single PARALLEL batch over the selection: the server fans the work across a
  // process pool and streams one JSON line per file, so the whole selection is
  // computed concurrently instead of one-blocking-await-per-file on the client
  // (which froze the UI for minutes). No library cleanup runs here — that pass
  // de-duplicated by (title, artist) and could trash freshly-computed files.
  try {
    const res = await fetch('/api/library/refresh-fingerings?force=true', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ files }),
    });
    if (!res.ok || !res.body) {
      const e = await res.json().catch(() => ({ detail: 'Échec du calcul' }));
      throw new Error(e.detail || 'Échec du calcul');
    }
    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = '';
    for (;;) {
      const { value, done: streamDone } = await reader.read();
      if (streamDone) break;
      buf += decoder.decode(value, { stream: true });
      let nl;
      while ((nl = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, nl).trim();
        buf = buf.slice(nl + 1);
        if (!line) continue;
        let msg;
        try { msg = JSON.parse(line); } catch { continue; }
        if (msg.event === 'start') {
          if (statusEl) statusEl.textContent = `0/${msg.to_process ?? total} — calcul en cours…`;
        } else if (msg.event === 'done') {
          ok = msg.ok ?? ok;
          err = msg.errors ?? err;
        } else if (msg.event === 'cancelled') {
          ok = msg.ok ?? ok;
          err = msg.errors ?? err;
        } else if (msg.status) {
          done++;
          if (msg.status === 'error') err++;
          else if (msg.status === 'ok') ok = Math.max(ok, done - err);
          if (statusEl) statusEl.textContent = `${done}/${total} — ${msg.file || ''}`;
          _t.progress(done / total);
          _t.message(`Calcul des doigtés… ${done}/${total} — ${msg.file || ''}`);
        }
      }
    }
  } catch (e) {
    console.error('Batch fingering failed:', e);
    _t.error(`Échec du calcul : ${e.message}`);
    if (statusEl) statusEl.textContent = `Échec : ${e.message}`;
    if (btn) btn.disabled = false;
    return;
  }
  _t.done(err
    ? `${ok} calculé(s), ${err} erreur(s)`
    : `${ok} fichier${ok > 1 ? 's' : ''} calculé${ok > 1 ? 's' : ''}`);
  if (statusEl) {
    statusEl.textContent = err
      ? `✓ ${ok} calculé(s) — ${err} erreur(s)`
      : `✓ ${ok} fichier${ok > 1 ? 's' : ''} calculé${ok > 1 ? 's' : ''}`;
    setTimeout(() => { if (statusEl) statusEl.textContent = ''; }, 6000);
  }
  if (btn) btn.disabled = false;
  _clearSelection();
  // Reload the file list so fingering badges update.
  await loadFiles();
}

const _libCheckAll = $('#lib-check-all');
if (_libCheckAll) {
  _libCheckAll.addEventListener('change', () => {
    const gpFiles = _allFiles.filter(f => f.name.endsWith('.gp'));
    if (_libCheckAll.checked) gpFiles.forEach(f => _selectedFiles.add(f.name));
    else _selectedFiles.clear();
    document.querySelectorAll('.lib-row-check').forEach(cb => {
      cb.checked = _libCheckAll.checked;
    });
    _updateSelectionBar();
  });
}

const _libBtnCalc = $('#lib-btn-calc-fingerings');
if (_libBtnCalc) _libBtnCalc.addEventListener('click', _calcFingeringsForSelected);

const _libBtnCancel = $('#lib-btn-cancel-selection');
if (_libBtnCancel) _libBtnCancel.addEventListener('click', _clearSelection);

// ── Sticky strip height ───────────────────────────────────────────────────────

// Measure the sticky control strip (.lib-sticky-strip = search/filters +
// A–Z bar) and expose its height as a CSS variable on #file-selector. The
// sticky table header reads it via calc() to pin under the strip.
function _updateStickyOffsets() {
  const fs = document.getElementById('file-selector');
  if (!fs || fs.style.display === 'none') return;
  const strip = document.getElementById('lib-sticky-strip');
  if (!strip) return;
  const h = Math.round(strip.getBoundingClientRect().height);
  if (h > 0) fs.style.setProperty('--lib-sticky-h', `${h}px`);
}
window.addEventListener('resize', _updateStickyOffsets);

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
// Pagination-aware: the target row may live on another page, so jump there
// first (the A–Z bar addresses the whole filtered set, not just the page).
function _scrollToLetter(letter) {
  const idx = _libRows.findIndex((f) => _libNavBucket(_libNavKey(f)) === letter);
  if (idx < 0) return;
  const targetPage = Math.floor(idx / LIB_PAGE_SIZE);
  if (targetPage !== _libPage) {
    _libPage = targetPage;
    _renderLibTable();
  }
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
  const ORDER = [
    'artist', 'album', 'genre', 'year',
    'guitarists', 'original_guitar', 'guitar_type',
    'target_tone', 'gear_confidence', 'rig_grade',
    'notes',
  ];
  const LABELS = {
    artist: 'Artist', album: 'Album', genre: 'Genre',
    year: 'Year', notes: 'Notes',
    guitarists: 'Guitariste(s)',
    original_guitar: 'Guitare originale',
    guitar_type: 'Type guitare',
    target_tone: 'Son cible',
    gear_confidence: 'Confiance gear',
    rig_grade: 'Fiabilité rig',
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
  // GP-180 profiles can be recommended even when no hand-written rig sheet exists.
  const _fInfo = _allFiles.find((f) => f.name === filename);
  if (btnRig) btnRig.style.display = _fInfo ? '' : 'none';
  if (rigPanel && rigPanel.style.display !== 'none') _loadRig(filename);

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
      const svgW = _svgRenderWidth(mode);
      const key = _solveCacheKey(filename, t.id, mode, prefs, svgW);
      if (_solveCache.has(key)) continue;  // already warm — skip the round-trip
      // Warm BOTH the server LRU and our client-side object cache so the next
      // interactive switch to this (track, mode) renders without any network.
      fetchSolve(filename, t.id, mode, prefs, svgW)
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
let _solveInFlight = false;        // a selectTrack() solve is currently running
let _autoPlayAfterSolve = false;   // play was requested before fingerings existed

async function selectTrack(trackId, trackName) {
  const myToken = ++_selectTrackToken;
  _solveInFlight = true;
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
    // Save the GLOBAL 1-based measure number, not the renderer slot index:
    // tracks that render different measure ranges (a voice entering at bar 16
    // renders slots starting there) would otherwise land on a different bar.
    const slot = playback.renderer?.cursorMeasure ?? 0;
    restorePos = {
      globalMeasure: playback.renderer?.measureNumbers?.[slot] ?? (slot + 1),
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
    const backendMode = _backendRepresentationMode(representationMode);
    const data = await _cachedSolve(
      currentFile,
      trackId,
      backendMode,
      getRulePreferences(),
      _svgRenderWidth(backendMode),
    );
    const viewData = { ...data, __client_view_mode: representationMode };
    // A newer selectTrack started while we were awaiting — drop this stale
    // result so it cannot clobber the view the user is now looking at.
    if (myToken !== _selectTrackToken) return;
    // Reconcile kind with the authoritative solve response: if /api/tracks
    // lacked a kind but the solve payload carries one, trust the latter and
    // re-apply the lock (covers a backend that only tags kind on /api/solve).
    if (viewData && viewData.kind != null && viewData.kind !== _currentTrackKind) {
      _currentTrackKind = viewData.kind;
      if (!_isCurrentTrackGuitar() && selRepresentationMode
          && selRepresentationMode.value !== MODES.STANDARD) {
        selRepresentationMode.value = MODES.STANDARD;
        _syncViewSegPills();
      }
      _applyTrackKindLock();
    }
    initRenderer(viewData);
    // Record chord-diagram availability for this file and update the library badge.
    if (viewData?.chord_diagrams?.length && currentFile && !_chordFilesSet.has(currentFile)) {
      _chordFilesSet.add(currentFile);
      const row = document.querySelector(`.lib-row[data-file="${CSS.escape(currentFile)}"]`);
      if (row) {
        const cell = row.querySelector('.lib-cell-title');
        if (cell && !cell.querySelector('.lib-chord-mark')) {
          const chordIcon = '<svg class="lib-chord-ic" width="13" height="13" viewBox="0 0 13 13" fill="none" xmlns="http://www.w3.org/2000/svg"><line x1="3" y1="1" x2="3" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="6.5" y1="1" x2="6.5" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="10" y1="1" x2="10" y2="12" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="3.5" x2="12" y2="3.5" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="7" x2="12" y2="7" stroke="currentColor" stroke-width="1.2"/><line x1="1" y1="10.5" x2="12" y2="10.5" stroke="currentColor" stroke-width="1.2"/><circle cx="3" cy="7" r="1.6" fill="currentColor"/><circle cx="6.5" cy="3.5" r="1.6" fill="currentColor"/><circle cx="10" cy="10.5" r="1.6" fill="currentColor"/></svg>';
          const badge = document.createElement('span');
          badge.className = 'lib-chord-mark';
          badge.title = 'Contient des diagrammes d\'accords';
          badge.innerHTML = chordIcon;
          cell.appendChild(badge);
        }
      }
    }
    renderAuditBanner(viewData?.audit, {
      onMaskedMeasuresChange: () => _syncCoreSvgFingering(),
    });
    _gateReviewButton(viewData?.audit);
    // Restore playback position from the previous track on the new one.
    // Clamp to the new track's measure count to handle tracks of different
    // lengths. Resume playback if it was playing before the switch.
    if (restorePos && playback) {
      // Map the saved global measure number back to a slot on the NEW track's
      // renderer. With the shared 1..N grid this is the identity; the nearest-
      // slot fallback covers renderers without measureNumbers (slope/3D) and
      // tracks whose range differs (MusicXML/MIDI fallback grouping).
      const nums = playback.renderer?.measureNumbers || null;
      let slot;
      if (nums && nums.length) {
        slot = nums.indexOf(restorePos.globalMeasure);
        if (slot < 0) {
          slot = nums.findIndex((n) => n >= restorePos.globalMeasure);
          if (slot < 0) slot = nums.length - 1;
        }
      } else {
        slot = restorePos.globalMeasure - 1;
      }
      const clamped = Math.max(
        0,
        Math.min(slot, (playback.totalMeasures || 1) - 1),
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
      // Focus the restored measure so opening a tab lands on where you were
      // (or the start), not at the top — and tracks the playhead if it's moving.
      _focusCurrentMeasure(clamped);
    }
    // The user pressed play before fingerings existed: the solve was launched on
    // their behalf, so start playback now that the track has playable measures.
    if (_autoPlayAfterSolve && playback) {
      _autoPlayAfterSolve = false;
      if (playback.totalMeasures > 0 && !playback.isPlaying) {
        _setFollowPlayhead(true);
        playback.play();
        updatePlayButton(true);
        startCursorLoop();
      }
    }
  } catch (err) {
    if (myToken !== _selectTrackToken) return;
    _autoPlayAfterSolve = false;
    ctx.clearRect(0, 0, tabCanvas.width, tabCanvas.height);
    ctx.fillStyle = '#ff5555';
    ctx.fillText(`Error: ${err.message}`, 200, 50);
  } finally {
    // Only the most recent selectTrack clears the busy state — a superseded
    // (stale) solve must not re-enable the tabs while a newer one is still
    // in flight.
    if (myToken === _selectTrackToken) {
      _solveInFlight = false;
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

let _songTask = null;
function _setSongLoading(on, message) {
  if (on) {
    if (!_songTask) _songTask = notifyTask(message || 'Calcul des doigtés…');
    else if (message) _songTask.message(message);
  } else if (_songTask) {
    _songTask.done();
    _songTask = null;
  }
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
  const _t = notifyTask('Export Guitar Pro…');
  try {
    const { blob, filename, annotatedNotes } = await fetchExportGp(
      currentFile, currentTrackId,
    );
    _downloadBlob(blob, filename);
    _t.done(`Export GP terminé (${annotatedNotes} doigtés)`);
    _setPdfExportStatus(
      `Export GP OK (${annotatedNotes} doigtés écrits)`, 'ok',
    );
  } catch (err) {
    // The backend returns a self-contained, user-facing message (incl. the
    // biomechanical-guard block), so show it verbatim without a prefix.
    _t.error(err.message || 'Export GP échoué');
    _setPdfExportStatus(err.message || 'Export GP échoué', 'error');
  } finally {
    if (btnHeaderGp) {
      btnHeaderGp.disabled = false;
      btnHeaderGp.setAttribute('aria-label', originalLabel);
    }
  }
}

async function saveGP() {
  if (!currentFile) return;
  if (!currentFile.toLowerCase().endsWith('.gp')) {
    _setPdfExportStatus(
      'Sauvegarde GP réservée aux fichiers GP 7/8 (.gp)', 'warn',
    );
    return;
  }
  if (btnHeaderSave) {
    btnHeaderSave.disabled = true;
    btnHeaderSave.setAttribute('aria-label', 'Sauvegarde…');
  }
  _setPdfExportStatus('Sauvegarde des doigtés…', 'neutral');
  const _t = notifyTask('Sauvegarde des doigtés…');
  try {
    const { saved, annotated_notes } = await fetchSaveGp(currentFile, currentTrackId);
    _t.done(`Doigtés sauvegardés (${annotated_notes} notes)`);
    _setPdfExportStatus(
      `Doigtés sauvegardés → ${saved} (${annotated_notes} notes)`, 'ok',
    );
  } catch (err) {
    _t.error(err.message || 'Sauvegarde GP échouée');
    _setPdfExportStatus(err.message || 'Sauvegarde GP échouée', 'error');
  } finally {
    if (btnHeaderSave) {
      btnHeaderSave.disabled = false;
      btnHeaderSave.setAttribute('aria-label', 'Sauver les doigtés');
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
  const _t = notifyTask(`Export MusicXML (${scopeLabel})…`);
  try {
    const { blob, filename, noteCount } = isAll
      ? await fetchExportMusicXmlAll(currentFile, currentTrackId)
      : await fetchExportMusicXml(currentFile, currentTrackId);
    _downloadBlob(blob, filename);
    _t.done(`Export MusicXML terminé (${noteCount} notes)`);
    _setPdfExportStatus(`Export MusicXML OK — ${scopeLabel} (${noteCount} notes)`, 'ok');
  } catch (err) {
    // Be defensive: a backend without scope support may 404 the "all" request.
    if (isAll && /\b404\b|not found|unsupported|scope/i.test(err.message || '')) {
      _t.error('Export multi-pistes indisponible sur ce serveur');
      _setPdfExportStatus('All-tracks export not available on this server', 'warn');
    } else {
      _t.error(`Export MusicXML échoué : ${err.message}`);
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
  const _t = notifyTask('Export PDF…');

  try {
    const representationMode = getSelectedRepresentationMode();
    const { blob, filename, conformanceIssues } = await fetchExportPdf(
      currentFile,
      currentTrackId,
      _backendRepresentationMode(representationMode),
    );
    _downloadBlob(blob, filename);
    if (conformanceIssues > 0) {
      _t.done(`Export PDF terminé (${conformanceIssues} avertissement(s))`);
      _setPdfExportStatus(`${conformanceIssues} conformance issue(s)`, 'warn');
    } else {
      _t.done('Export PDF terminé');
      _setPdfExportStatus('Export OK', 'ok');
    }
  } catch (err) {
    console.warn('API PDF export failed, falling back to local canvas export:', err);
    _t.message('Export PDF (rendu local)…');
    _setPdfExportStatus('API failed, using local fallback', 'warn');
    exportPDFLegacyCanvas();
    _t.done('Export PDF terminé (local)');
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
  // The prefs panel was removed from the toolbar; these keep the former
  // defaults (penalty + legato inference on, hand-overlay lane off).
  return {
    sameFingerPenalty: true,
    inferImplicitLegato: true,
    showHandOverlay: false,
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
  document.querySelectorAll('#view-seg .view-seg-btn').forEach((btn) => {
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
      else if (btn.dataset.mode === MODES.SLOPE) btn.title = 'Perspective playback lane';
      else if (btn.dataset.mode === MODES.HAND_3D) btn.title = '3D fretting hand';
    }
  });

  // Fingering button + insert-fingerings make no sense without fingering
  // data. Hide them entirely for non-guitar tracks.
  const fingeringControls = [btnFingering, btnInsertFingerings];
  for (const el of fingeringControls) {
    if (el) el.style.display = guitar ? '' : 'none';
  }
}

function applyRepresentationModeView(data) {
  // Non-guitar tracks are always shown as staff, regardless of what mode the
  // backend echoed back (covers a tab-mode solve issued before the kind was
  // known). Guitar tracks keep the requested / echoed mode unchanged.
  const representationMode = _isCurrentTrackGuitar()
    ? (data?.__client_view_mode || data?.representation_mode || getSelectedRepresentationMode())
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

  const showSlope = representationMode === MODES.SLOPE;
  const showHand3d = representationMode === MODES.HAND_3D;
  const showCore = representationMode !== MODES.TABLATURE
    && representationMode !== MODES.SLOPE
    && representationMode !== MODES.HAND_3D;
  if (tabCanvas) {
    // display:none (not just visibility:hidden) in every non-Tablature mode —
    // the canvas can be 40000+ px tall (one row per measure). Left display:block
    // while merely invisible, it still occupies #tab-container's layout box and
    // gives it its OWN scrollbar alongside #core-svg-view's, producing two
    // vertical scrollbars for one view (Staff/Mixed double-scrollbar bug).
    tabCanvas.style.display = (showCore || showSlope || showHand3d) ? 'none' : 'block';
  }
  if (cursorCanvas) cursorCanvas.style.display = (showCore || showSlope || showHand3d) ? 'none' : 'block';
  if (slopeCanvas) slopeCanvas.style.display = showSlope ? 'block' : 'none';
  if (hand3dViewFrame) hand3dViewFrame.style.display = showHand3d ? 'block' : 'none';
  if (!showHand3d) _releaseHand3dViewFrame();
  // The Slope legibility sub-mode selector (P1–P4) and density control only
  // make sense in Slope view.
  if (_slopeModeSeg) _slopeModeSeg.style.display = showSlope ? '' : 'none';
  if (_slopeDensityCtrl) _slopeDensityCtrl.style.display = showSlope ? '' : 'none';
  _slopeRenderer?.setVisible(showSlope);
  if (showHand3d) {
    const frameReady = _ensureHand3dViewFrame();
    if (frameReady) {
      window.requestAnimationFrame(() => {
        _postHandVizData();
        _postHandVizTime(true);
      });
    }
  }
  if (coreSvgView) {
    coreSvgView.style.display = showCore ? 'block' : 'none';
    coreSvgView.innerHTML = showCore && data?.core_svg ? data.core_svg : '';
    if (showCore) {
      _lastSvgWidth[representationMode] = _svgRenderWidth(representationMode);
      _applyResponsiveCoreSvg();
      _syncCoreSvgFingering();
      _syncCoreSvgAnnotations();
      _syncCoreSvgHandOverlay();
    }
  }
}

function _isHand3dViewVisible() {
  return getSelectedRepresentationMode() === MODES.HAND_3D
    && hand3dViewFrame
    && hand3dViewFrame.style.display !== 'none';
}

function _ensureHand3dViewFrame() {
  if (!hand3dViewFrame || !_isHand3dViewVisible()) return false;
  if (_hand3dFrameLoaded && hand3dViewFrame.contentWindow) return true;
  const src = hand3dViewFrame.getAttribute('src');
  if (!src) {
    const next = hand3dViewFrame.dataset.src || '/static/hand_viz.html?view=3d';
    hand3dViewFrame.setAttribute('src', next);
    _hand3dFrameLoaded = true;
    return false;
  }
  _hand3dFrameLoaded = true;
  return !!hand3dViewFrame.contentWindow;
}

function _releaseHand3dViewFrame() {
  if (!hand3dViewFrame || !_hand3dFrameLoaded) return;
  if (hand3dViewFrame.getAttribute('src')) hand3dViewFrame.removeAttribute('src');
  _hand3dFrameLoaded = false;
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
  const FINGER_CLASSES = [
    'fw-finger-1', 'fw-finger-2', 'fw-finger-3', 'fw-finger-4',
    'fw-finger-impossible', 'fw-finger-suspect',
  ];
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

    const reviewSeverity = String(resultNote.review_severity || 'ok');
    const reviewClass = reviewSeverity === 'impossible'
      ? 'fw-finger-impossible'
      : (reviewSeverity === 'suspect' ? 'fw-finger-suspect' : '');
    const fc = fingerClassMap[resultNote.finger];
    if (!reviewClass && !fc) continue;

    // The mask rect is the element immediately before the note text in the SVG
    const maskRect = noteText.previousElementSibling;
    if (maskRect && maskRect.classList.contains('fw-tab-note-mask')) {
      maskRect.classList.add(reviewClass || fc);
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
  const pushText = (content, x, y, {
    size = '6.5',
    weight = '700',
    fill = '#555555',
    anchor = 'middle',
    family = 'Inter, sans-serif',
  } = {}) => {
    const t = mk('text');
    t.setAttribute('x', x.toFixed(2));
    t.setAttribute('y', y.toFixed(2));
    t.setAttribute('font-family', family);
    t.setAttribute('font-size', size);
    t.setAttribute('font-weight', weight);
    t.setAttribute('fill', fill);
    t.setAttribute('text-anchor', anchor);
    t.textContent = content;
    return push(t);
  };

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

    // ── Always-visible note-state effects. These mirror the Tab canvas
    // renderer so every audible playback effect also leaves a visible mark
    // in Staff/Mixed SVG mode.
    if (r.muted) {
      pushText('X', x, y + 2, { size: '9', fill: '#555555' });
    } else if (r.ghost) {
      pushText('(', x - 5, y + 2, { size: '9', fill: '#888888', weight: '600' });
      pushText(')', x + 5, y + 2, { size: '9', fill: '#888888', weight: '600' });
    }

    let lowerLabelY = y + 12;
    const pushLowerLabel = (content, fill) => {
      pushText(content, x, lowerLabelY, { size: '5.5', fill });
      lowerLabelY += 8;
    };
    if (r.palm_muted) pushLowerLabel('P.M.', '#6b6b55');
    if (r.let_ring) pushLowerLabel('L.R.', '#2c7a45');
    if (r.harmonic_type) {
      const hLabel = {
        natural: 'N.H.',
        pinch: 'P.H.',
        artificial: 'A.H.',
        harp: 'H.H.',
      }[r.harmonic_type] || 'Harm.';
      pushLowerLabel(hLabel, '#6a4c93');
    }

    if (r.tremolo_picking) {
      pushText('///', x + 6, y - 1, { size: '7', fill: '#37474f' });
    }

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

    // ── Staccato dot
    if (r.staccato || r.articulation === 'staccato') {
      const c = mk('circle');
      c.setAttribute('cx', x.toFixed(2));
      c.setAttribute('cy', (y - 6).toFixed(2));
      c.setAttribute('r', '1.2');
      c.setAttribute('fill', '#333333');
      push(c);
    }

    // ── Strum direction / right-hand techniques
    if (r.strum_direction === 'up' || r.strum_direction === 'down') {
      const t = mk('text');
      t.setAttribute('x', (x - 6).toFixed(2));
      t.setAttribute('y', (y - 10).toFixed(2));
      t.setAttribute('font-family', 'Inter, sans-serif');
      t.setAttribute('font-size', '7');
      t.setAttribute('font-weight', '700');
      t.setAttribute('fill', '#37474f');
      t.setAttribute('text-anchor', 'middle');
      t.textContent = r.strum_direction === 'up' ? 'V' : '\u22a4';
      push(t);
    }

    const rhLabel = r.slap ? 'S'
      : (r.pop ? 'P' : (r.golpe ? '*' : (r.rasgueado ? 'Rasp.' : '')));
    if (rhLabel) {
      const t = mk('text');
      t.setAttribute('x', (x + 8).toFixed(2));
      t.setAttribute('y', (y - 10).toFixed(2));
      t.setAttribute('font-family', 'Inter, sans-serif');
      t.setAttribute('font-size', rhLabel === 'Rasp.' ? '5.5' : '7');
      t.setAttribute('font-weight', '700');
      t.setAttribute('fill', r.golpe || r.rasgueado ? '#795548' : '#1565c0');
      t.setAttribute('text-anchor', 'middle');
      t.textContent = rhLabel;
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
  _setTempoText(data.tempo || 120);
  if (metaMode) metaMode.textContent = 'PERFORMANCE';

  renderer = new TabRenderer(tabCanvas, data);
  _slopeRenderer?.destroy();
  _slopeRenderer = slopeCanvas ? new SlopeRenderer(slopeCanvas, data) : null;
  // Re-apply the user's persisted Slope legibility mode + density to the new renderer.
  _slopeRenderer?.setLegibilityMode(_slopeMode);
  _slopeRenderer?.setDensity(_slopeDensity);
  // Non-guitar tracks carry no fingering: never draw finger annotations and
  // keep the (hidden) fingering toggle inactive. Defensive — the solve
  // response also exposes `fingered:false` for these tracks.
  if (!_isCurrentTrackGuitar() || data.fingered === false) {
    renderer.showFingering = false;
  }
  // Update "Insérer les doigtés" button appearance based on sidecar status.
  _updateInsertFingeringsBtn(data);
  renderer.render();
  _slopeRenderer?.setVisible((data.__client_view_mode || getSelectedRepresentationMode()) === MODES.SLOPE);
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
  const chordToggle = $('#chord-bar-toggle');
  const strip = $('#chord-strip');
  if (strip) {
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
      if (chordToggle) chordToggle.style.display = '';   // chords available → show the toggle
    } else {
      strip.innerHTML = '';
      if (chordToggle) chordToggle.style.display = 'none';
      _setChordsOpen(false);                              // no chords → keep the score full-height
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
    // Real per-measure beat counts → meter-aware playback timeline (keeps the
    // cursor, audio and all tracks aligned across meter changes / pickup bars).
    measureBeats: Array.isArray(data.measure_beats) ? data.measure_beats : null,
    // Real per-measure tempo → tempo-aware timeline (a mid-song tempo change no
    // longer desyncs the cursor and audio from the music).
    measureTempos: Array.isArray(data.measure_tempos) ? data.measure_tempos : null,
  };
  if (playback) {
    playback.rebind(renderer, engineOpts);
  } else {
    playback = new PlaybackEngine(renderer, engineOpts);
  }
  _slopeRenderer?.bindPlayback(playback);
  // Set GM MIDI program (SpessaSynth) and infer MusyngKite instrument (fallback)
  playback.setMidiProgram(data.midi_program ?? -1);
  playback.setInstrument(data.track_name || '');
  playback.onMeasureChange = (_m) => {};
  playback.onStop = () => {
    updatePlayButton(false);
    stopCursorLoop();
    _postHandVizTime(true);
  };
  // Feed the dedicated 3D-hand iframe with the current playhead time on every
  // tick (sub-measure precision). Cheap: it is just one postMessage / frame.
  playback.onTimeChange = (sec) => {
    if (tcCurrent) tcCurrent.textContent = _fmtTime(sec);
    _slopeRenderer?.setPlaybackTime(sec, playback);
    if (getSelectedRepresentationMode() === MODES.HAND_3D) _postHandVizTime();
  };
  // Surface soundfont loading so a big bank (StrixGuitarPack 186 MB, East_West
  // 426 MB) doesn't look like a freeze. Must be wired BEFORE enableAudio() so the
  // synchronous 'loading' event from _initSynth() is caught. On 'ready'/'error',
  // start any playback the user requested while the instrument was still loading.
  playback.onSynthStatusChange = (status) => {
    if (status === 'loading') {
      if (_synthTask) _synthTask.close();
      _synthTask = notifyTask("Chargement de l'instrument…");
    } else if (_synthTask) {
      if (status === 'error') _synthTask.error('Instrument indisponible — son de repli');
      else _synthTask.done();
      _synthTask = null;
    }
  };
  playback.onSynthProgress = (frac, loadedMB, totalMB) => {
    if (!_synthTask) return;
    _synthTask.progress(frac);
    if (frac != null && totalMB) {
      _synthTask.message(`Chargement de l'instrument… ${loadedMB} / ${totalMB} Mo`);
    }
  };
  // Advisory when the active soundfont is not a full General MIDI bank: non-guitar
  // tracks can't map and everything collapses onto one timbre. Surface it once so
  // the user knows to switch banks (Réglages) rather than blaming the tab.
  playback.onSoundfontWarning = (message) => {
    try { notifyTask('Soundfont').error(message); } catch (_) { /* notices optional */ }
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
  const _svgMode = data.__client_view_mode || data.representation_mode || getSelectedRepresentationMode();
  if (_svgMode !== MODES.TABLATURE && _svgMode !== MODES.SLOPE
      && _svgMode !== MODES.HAND_3D && data.measure_regions?.length && coreSvgView) {
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
        // Click-to-seek: bring the chosen measure into view and flash it as the
        // selection. goToMeasure()'s highlight() only auto-scrolls while
        // follow-playhead is on, so without this an explicit click would leave
        // the selected measure off-screen (and a re-render can park the scroll
        // at the top — the "jumps to the beginning, no selection" bug).
        _svgDriver.scrollToMeasure(m);
      }
    };
  } else {
    if (coreSvgView) coreSvgView.onclick = null;
    // Canvas (Tab) view scrolls #tab-container. Slope owns its own full-canvas
    // animation and should not run the legacy tab cursor overlay.
    playback.usesSvgCursor = _svgMode === MODES.SLOPE || _svgMode === MODES.HAND_3D;
  }

  // Speed
  if (selSpeed) {
    selSpeed.value = '100';
    _slopeRenderer?.setSpeed(1.0);
    _setTempoText(playback?.tempo || data.tempo || 120);
    selSpeed.onchange = () => {
      const s = parseInt(selSpeed.value, 10) / 100;
      playback.setSpeed(s);
      _slopeRenderer?.setSpeed(s);
      _slopeRenderer?.render();
      _setTempoText(playback.tempo);
    };
  }

  if (bpmInput) {
    bpmInput.onchange = () => {
      const effectiveBpm = Math.max(20, Math.min(300, parseInt(bpmInput.value, 10) || 120));
      const bpm = Math.max(20, Math.min(300, Math.round(effectiveBpm / _speedMultiplier())));
      if (playback) playback.tempo = bpm;
      if (renderer) { renderer.tempo = bpm; renderer.render(); }
      if (_slopeRenderer) { _slopeRenderer.tempo = bpm; _slopeRenderer.render(); }
      _setTempoText(bpm);
    };
    bpmInput.onkeydown = (e) => { if (e.key === 'Enter') bpmInput.onchange(); };
  }

  _rebuildMultiTrackBar(currentTrackId);
  _rebuildTrackTabs(currentTrackId);
  // Tabs are built before the backing channels exist, so their faders start
  // disabled with no level to show; refresh them once the channels are in and
  // the engine has balanced them.
  _restoreSecondaryTracks(currentTrackId) // re-enable previously active secondary tracks
    .then(() => _refreshTrackFaders())
    .catch(() => { /* a track that fails to load just keeps its fader disabled */ });
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

/**
 * Per-track level fader for the track tabs — the visible mixer.
 *
 * The engine auto-balances backing tracks by instrument kind, but that was
 * invisible and unadjustable. Each tab now carries its own fader:
 *  - the open track drives MIDI channel 0 (kept in sync with the toolbar slider);
 *  - a backing track drives its own channel, and doing so pins the level against
 *    the auto-balance — double-click hands it back (title says so).
 * A muted track has no channel, so its fader is disabled rather than lying.
 *
 * @param {Object} t track descriptor from /api/tracks
 * @param {boolean} isPrimary
 * @param {boolean} isMuted
 * @param {string} color tab tint, reused for the manual-override cue
 * @returns {HTMLElement}
 */
function _buildTrackFader(t, isPrimary, isMuted, color) {
  const wrap = document.createElement('div');
  wrap.className = 'track-fader';

  const slider = document.createElement('input');
  slider.type = 'range';
  slider.className = 'track-fader-range';
  slider.min = '0';
  slider.max = '100';
  slider.step = '1';
  slider.dataset.trackId = String(t.id);

  const readout = document.createElement('span');
  readout.className = 'track-fader-val';

  const level = isPrimary
    ? (playback ? playback.primaryVolume : 0.8)
    : (playback ? playback.trackVolume(t.id) : null);
  const manual = !isPrimary && !!playback?.trackVolumeIsManual(t.id);
  const disabled = isMuted || level == null;

  slider.value = String(Math.round((level ?? 0) * 100));
  slider.disabled = disabled;
  readout.textContent = disabled ? '—' : String(Math.round((level ?? 0) * 100));
  wrap.dataset.manual = manual ? '1' : '0';
  if (manual) readout.style.color = color;

  const label = sanitize(t.name || `Track ${t.id}`);
  const describe = () => {
    if (disabled) return `${label} — muted`;
    return wrap.dataset.manual === '1'
      ? `${label} — level set by hand; double-click to auto-balance again`
      : `${label} — auto-balanced level; drag to set it by hand`;
  };
  slider.title = describe();

  const apply = (pct) => {
    const v = Math.max(0, Math.min(100, pct)) / 100;
    if (!playback) return;
    if (isPrimary) {
      playback.setChannelVolume(0, v);
      // The toolbar slider drives the same channel — keep them from diverging.
      if (rngTrackVolume) rngTrackVolume.value = String(Math.round(v * 100));
    } else {
      playback.setTrackVolume(t.id, v);
      wrap.dataset.manual = '1';
      readout.style.color = color;
    }
    readout.textContent = String(Math.round(v * 100));
    slider.title = describe();
  };

  // The tab itself switches the primary track on click — the fader must not.
  for (const ev of ['click', 'pointerdown', 'mousedown']) {
    slider.addEventListener(ev, (e) => e.stopPropagation());
  }
  slider.addEventListener('input', () => apply(parseInt(slider.value, 10)));

  if (!isPrimary) {
    slider.addEventListener('dblclick', (e) => {
      e.stopPropagation();
      if (!playback) return;
      const restored = playback.clearTrackVolumeOverride(t.id);
      if (restored == null) return;
      slider.value = String(Math.round(restored * 100));
      readout.textContent = String(Math.round(restored * 100));
      wrap.dataset.manual = '0';
      readout.style.color = '';
      slider.title = describe();
    });
  }

  wrap.appendChild(slider);
  wrap.appendChild(readout);
  return wrap;
}

/**
 * Sync every tab fader with the engine's current levels, in place.
 *
 * Needed because the tabs are built before the backing channels are registered
 * (and because adding/removing a track re-balances the survivors): without this
 * the strips would show a stale — or disabled — level for a track that is in
 * fact playing at an auto-balanced one.
 */
function _refreshTrackFaders() {
  if (!playback) return;
  for (const wrap of document.querySelectorAll('#track-tabs-bar .track-fader')) {
    const slider = wrap.querySelector('.track-fader-range');
    const readout = wrap.querySelector('.track-fader-val');
    if (!slider || !readout) continue;
    const trackId = Number(slider.dataset.trackId);
    const isPrimary = trackId === currentTrackId;
    const level = isPrimary ? playback.primaryVolume : playback.trackVolume(trackId);
    if (level == null) {                    // muted / not loaded → nothing to show
      slider.disabled = true;
      readout.textContent = '—';
      continue;
    }
    // Never fight the user mid-drag.
    if (document.activeElement === slider) continue;
    slider.disabled = false;
    slider.value = String(Math.round(level * 100));
    readout.textContent = String(Math.round(level * 100));
    wrap.dataset.manual = (!isPrimary && playback.trackVolumeIsManual(trackId)) ? '1' : '0';
  }
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
    body.appendChild(_buildTrackFader(t, isPrimary, isMuted, color));

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
          // Muting one of N same-kind tracks re-balances the survivors upward —
          // the strips must show the levels the engine actually applied.
          _refreshTrackFaders();
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
    playback.addSecondaryChannel(trackId, trackName, notesData.results, notesData.beats_per_measure, notesData.midi_program, notesData.kind);
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

/**
 * Playback needs solved notes (the fingering pass produces the playable score).
 * If the user hits play on a track that has nothing to play yet, compute the
 * fingerings first (showing the calc feedback) and auto-start when ready, rather
 * than silently doing nothing. Returns true when it took over the play request.
 */
function _ensureSolvedThenPlay() {
  if (!playback || playback.isPlaying || playback.totalMeasures > 0) return false;
  if (currentTrackId == null) return false;
  _autoPlayAfterSolve = true;
  notifyToast('Calcul des doigtés avant la lecture…', { spinner: true, duration: 2600 });
  // If a solve is already running it will honour _autoPlayAfterSolve on finish;
  // otherwise kick one off for the current track.
  if (!_solveInFlight) selectTrack(currentTrackId, _reviewTrackName || '');
  return true;
}

/**
 * Bring a measure into view and highlight it — used when opening a tab so the
 * user lands on the measure they were at (or the playhead if it's moving),
 * instead of at the top of the score. Works in both the SVG and canvas views.
 */
function _focusCurrentMeasure(measure) {
  if (!playback || !playback.renderer) return;
  const m = measure ?? playback.renderer.cursorMeasure ?? 0;
  if (playback.usesSvgCursor && _svgDriver) {
    _svgDriver.highlight(m, playback.loopStart, playback.loopEnd);
    _svgDriver.scrollToMeasure(m);
  } else {
    _setFollowPlayhead(true);
    try { playback._scrollCursorIntoView(); } catch (_) { /* geometry not ready */ }
  }
}

/**
 * Open/close the in-score chord strip. Adds .chords-open to #tab-container, which
 * grows the chord host at the top of the score and offsets the staves (SVG +
 * cursor overlay) down by the same height — so the chords sit inside the score.
 */
function _setChordsOpen(open) {
  const cont = $('#tab-container');
  const toggle = $('#chord-bar-toggle');
  if (cont) cont.classList.toggle('chords-open', !!open);
  if (toggle) toggle.setAttribute('aria-expanded', open ? 'true' : 'false');
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
    if (_ensureSolvedThenPlay()) return;  // nothing solved yet → compute first
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
    if (representationMode === MODES.HAND_3D) return;
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

const rngTrackVolume = $('#rng-track-volume');
if (rngTrackVolume) {
  rngTrackVolume.value = '80';
  // Volume of the currently-open track (MIDI channel 0) so it can be balanced
  // against the backing tracks instead of always playing loudest.
  rngTrackVolume.addEventListener('input', () => {
    const pct = parseInt(rngTrackVolume.value, 10);
    if (playback) playback.setChannelVolume(0, pct / 100);
    // Mirror onto the open track's tab fader — both drive MIDI channel 0, so
    // leaving one stale would show two different levels for one channel.
    const tab = document.querySelector('#track-tabs-bar .track-tab[data-active="1"]');
    const slider = tab?.querySelector('.track-fader-range');
    if (slider && !slider.disabled) {
      slider.value = String(pct);
      const readout = tab.querySelector('.track-fader-val');
      if (readout) readout.textContent = String(pct);
    }
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

if (btnHeaderSave) {
  btnHeaderSave.addEventListener('click', saveGP);
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

// ── "Insérer les doigtés" — viewer toolbar button ─────────────────────────────

/**
 * Update the insert-fingerings button appearance based on the solve response.
 * - No sidecar: button is highlighted (needs action)
 * - Sidecar current: button is normal (already done)
 * - Sidecar outdated: button shows warning
 */
function _updateInsertFingeringsBtn(data) {
  if (!btnInsertFingerings) return;
  const hasSaved = data?.has_saved_fingering;
  const isCurrent = data?.fingering_is_current;
  btnInsertFingerings.classList.toggle('is-needed', !hasSaved);
  btnInsertFingerings.classList.toggle('is-outdated', hasSaved && !isCurrent);
  if (!hasSaved) {
    btnInsertFingerings.title = 'Aucun doigté enregistré — cliquer pour calculer et sauvegarder';
  } else if (!isCurrent) {
    btnInsertFingerings.title = `Doigtés créés avec une version antérieure de l'algorithme (${data.fingering_algo_version || '?'}) — cliquer pour recalculer`;
  } else {
    btnInsertFingerings.title = 'Doigtés à jour — cliquer pour recalculer';
  }
}

/**
 * Show the "Doigtés à revoir" entry point only when there is actually something
 * to review. A clean audit with no biomechanical violations means "rien à
 * revoir" — surfacing the review panel in that case is just noise (bug #4).
 */
function _gateReviewButton(audit) {
  const btn = document.getElementById('btn-review');
  if (!btn) return;
  const hasAudit = !!(audit && audit.available !== false && audit.overall);
  const biomechViolations = (audit && audit.biomechanical_report
    && Array.isArray(audit.biomechanical_report.violations))
    ? audit.biomechanical_report.violations.length : 0;
  const worthReviewing = hasAudit && (audit.overall !== 'clean' || biomechViolations > 0);
  btn.style.display = worthReviewing ? '' : 'none';
  // If we are hiding the entry point, make sure a stale panel isn't left open.
  if (!worthReviewing) {
    const panel = document.getElementById('review-panel');
    if (panel) panel.style.display = 'none';
  }
}

let _insertRunning = false;

async function _insertFingerings() {
  if (_insertRunning) return;
  if (currentTrackId == null || currentFile == null) return;
  if (!currentFile.endsWith('.gp')) {
    _setPdfExportStatus('Insertion de doigtés uniquement disponible pour les fichiers .gp', 'warn');
    return;
  }
  _insertRunning = true;
  if (btnInsertFingerings) {
    btnInsertFingerings.disabled = true;
    btnInsertFingerings.classList.add('is-busy');
    btnInsertFingerings.setAttribute('aria-busy', 'true');
  }
  const file = currentFile;
  const primaryTrack = currentTrackId;
  try {
    await fetchSaveGp(file, primaryTrack);
    // Invalidate client-side solve cache so the reload reads the fresh sidecar.
    const prefix = `${file}#${primaryTrack}#`;
    for (const key of Array.from(_solveCache.keys())) {
      if (key.startsWith(prefix)) _solveCache.delete(key);
    }
    // Reflect the new fingering in the in-memory library immediately so the
    // list badge is up to date no matter how the user navigates back (bug #1).
    const fEntry = _allFiles.find((f) => f.name === file);
    if (fEntry) { fEntry.has_fingering = true; fEntry.fingering_is_current = true; }
    await selectTrack(primaryTrack, _reviewTrackName);   // current tab shown ASAP
    // Bug #3: now compute the OTHER guitar tracks asynchronously in the
    // background, so the user reads the current tab while the rest fill in and
    // become instant to switch to. Sequential (one save at a time) to avoid
    // racing the per-track sidecar; non-blocking (no await here).
    _computeOtherGuitarTracks(file, primaryTrack);
  } catch (err) {
    console.error('Insert fingerings failed:', err);
    _setPdfExportStatus(`Erreur : ${err.message}`, 'warn');
  } finally {
    _insertRunning = false;
    if (btnInsertFingerings) {
      btnInsertFingerings.disabled = false;
      btnInsertFingerings.classList.remove('is-busy');
      btnInsertFingerings.removeAttribute('aria-busy');
    }
  }
}

let _bgComputeRunning = false;

/**
 * Bug #3 — after the current guitar track is computed and shown, fingere the
 * OTHER guitar tracks of the same song in the background (sequentially, to avoid
 * racing the per-track sidecar). Each completed track becomes instant to switch
 * to. Aborts if the user navigates to a different file.
 */
async function _computeOtherGuitarTracks(file, primaryTrack) {
  if (_bgComputeRunning) return;
  const others = (currentTracks || [])
    .filter((t) => isGuitarKind(t.kind) && t.id !== primaryTrack)
    .map((t) => t.id);
  if (!others.length) return;
  _bgComputeRunning = true;
  let done = 0;
  try {
    for (const tid of others) {
      if (currentFile !== file) break;   // user moved on — stop
      _setPdfExportStatus(`Doigtés des autres pistes guitare… ${done}/${others.length}`, 'neutral');
      try {
        await fetchSaveGp(file, tid);
        const prefix = `${file}#${tid}#`;
        for (const key of Array.from(_solveCache.keys())) {
          if (key.startsWith(prefix)) _solveCache.delete(key);
        }
        done++;
      } catch (e) {
        console.error(`Background fingering failed for track ${tid}:`, e);
      }
    }
    if (done) {
      _setPdfExportStatus(`Doigtés calculés pour ${done + 1} pistes guitare`, 'ok');
    }
  } finally {
    _bgComputeRunning = false;
  }
}

if (btnInsertFingerings) btnInsertFingerings.addEventListener('click', _insertFingerings);

// ── Rig GP-180 floating panel ──────────────────────────────────────────

function _toggleRig() {
  if (!rigPanel) return;
  const visible = rigPanel.style.display !== 'none';
  if (visible) {
    rigPanel.style.display = 'none';
    if (btnRig) btnRig.classList.remove('tb-btn-active');
  } else {
    rigPanel.style.display = 'flex';
    if (btnRig) btnRig.classList.add('tb-btn-active');
    if (currentFile) _loadRig(currentFile);
  }
}

// Last rig shown in the panel.
let _lastRig = null;
// Score filename the panel was opened for.
let _lastRigFile = null;
let _rigBank = null;
let _lastRigResolution = null;

async function _loadRig(filename) {
  // The server returns the new-format gears sheet when one exists for this song,
  // otherwise the legacy .md; a stub covers songs with neither.
  const data = await fetchRig(filename) || _fallbackRigView(filename);
  _lastRig = data;
  _lastRigFile = filename;
  _renderRig(data);
  await _loadRigBankControl(filename, data);
}

function _fallbackRigView(filename) {
  const entry = _allFiles.find((f) => f.name === filename) || {};
  const meta = entry.meta || {};
  const parsed = _parseArtistTitleFromFilename(filename);
  return {
    artist: meta.artist || parsed.artist || '',
    song: meta.title || parsed.title || filename,
    genre: meta.genre || '',
    album: meta.album || '',
    accordage: '—',
    capo: '—',
    guitare_originale: '—',
    fiabilite: '—',
    chain: [],
    reglages: {},
    notes: '',
    limites: '',
    comments: 'Aucune fiche rig écrite pour ce morceau : FretWise conseille un profil GP-180 approchant.',
  };
}

function _parseArtistTitleFromFilename(filename) {
  const stem = (filename || '').replace(/\.[^.]+$/, '').replace(/\s*-\s*\d{1,2}-\d{1,2}-\d{4}\s*$/, '');
  if (stem.includes(' - ')) {
    const parts = stem.split(' - ');
    return { artist: parts[0]?.trim() || '', title: parts.slice(1).join(' - ').trim() || stem };
  }
  const idx = stem.indexOf('-');
  if (idx > 0) {
    return { artist: stem.slice(0, idx).trim(), title: stem.slice(idx + 1).trim() || stem };
  }
  return { artist: '', title: stem };
}

async function _loadRigBankControl(filename, rigData) {
  const wrap = document.getElementById('rig-bank-control');
  const select = document.getElementById('rig-profile-select');
  const outputSelect = document.getElementById('rig-midi-output-select');
  const status = document.getElementById('rig-bank-status');
  if (!wrap || !select || !status) return;
  wrap.style.display = 'none';
  select.innerHTML = '';
  if (outputSelect) outputSelect.innerHTML = '';
  _lastRigResolution = null;
  try {
    _rigBank = await fetchRigBank();
    const profiles = Array.isArray(_rigBank.profiles) ? _rigBank.profiles : [];
    if (!profiles.length) {
      status.className = 'rig-bank-status';
      status.textContent = 'Aucun profil MIDI dans rig_bank.json.';
      wrap.style.display = '';
      return;
    }
    const body = {
      filename,
      song: rigData?.song || null,
      artist: rigData?.artist || null,
      genre: rigData?.genre || null,
      rig_modules: _activeRigModules(rigData),
    };
    const recommendation = await recommendRigProfile(body);
    const orderedProfiles = _sortRigProfilesForRecommendation(profiles, recommendation, rigData);
    _renderRigProfileOptions(select, orderedProfiles);
    if (recommendation?.profile?.id) {
      select.value = recommendation.profile.id;
      _lastRigResolution = recommendation;
      _renderRigBankStatus(recommendation, false);
    } else {
      _lastRigResolution = null;
      status.className = 'rig-bank-status';
      status.textContent = 'Aucune recommandation disponible. Choisis un profil GP-180 à activer.';
    }
    wrap.style.display = '';
    await _loadRigMidiOutputs();
  } catch (err) {
    status.className = 'rig-bank-status error';
    status.textContent = `Banque GP-180 indisponible : ${err.message || err}`;
    wrap.style.display = '';
  }
}

function _activeRigModules(rigData) {
  const settings = rigData?.reglages;
  if (!settings || typeof settings !== 'object') return [];
  return Object.entries(settings)
    .filter(([, value]) => value?.active === true && String(value?.preset || '').trim())
    .map(([module, value]) => ({
      module,
      model: String(value.preset).trim(),
      active: true,
    }));
}

function _renderRigProfileOptions(select, profiles) {
  select.innerHTML = '';
  profiles.forEach((profile) => {
    const opt = document.createElement('option');
    opt.value = profile.id;
    const pgm = Number.isFinite(profile.program) ? `PC ${profile.program}` : 'PC ?';
    const genre = profile.genre ? ` · ${profile.genre}` : '';
    opt.textContent = `${profile.name || profile.id} · ${pgm}${genre}`;
    select.appendChild(opt);
  });
}

function _sortRigProfilesForRecommendation(profiles, recommendation, rigData) {
  const source = recommendation?.source || '';
  if (!['genre_binding', 'profile_genre', 'genre_match'].includes(source)) {
    return profiles;
  }
  const selectedId = recommendation?.profile?.id || '';
  const targetGenre = recommendation?.profile?.genre
    || recommendation?.matched_key
    || recommendation?.context?.genre
    || rigData?.genre
    || '';
  const targetKey = _textKey(targetGenre);
  const targetTokens = _textTokens(targetGenre);
  return [...profiles].sort((a, b) => {
    const rankA = _rigProfileGenreRank(a, targetKey, targetTokens, selectedId);
    const rankB = _rigProfileGenreRank(b, targetKey, targetTokens, selectedId);
    if (rankA !== rankB) return rankA - rankB;
    const programA = Number.isFinite(a.program) ? a.program : Number.MAX_SAFE_INTEGER;
    const programB = Number.isFinite(b.program) ? b.program : Number.MAX_SAFE_INTEGER;
    return programA - programB;
  });
}

function _rigProfileGenreRank(profile, targetKey, targetTokens, selectedId) {
  if (profile?.id === selectedId) return 0;
  const genreKey = _textKey(profile?.genre || '');
  if (targetKey && genreKey === targetKey) return 1;
  const genreTokens = _textTokens(profile?.genre || '');
  if (targetTokens.size && [...targetTokens].some((token) => genreTokens.has(token))) return 2;
  if (targetKey && genreKey && (targetKey.includes(genreKey) || genreKey.includes(targetKey))) {
    return 2;
  }
  return 3;
}

function _textKey(value) {
  return String(value || '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, ' ')
    .trim();
}

function _textTokens(value) {
  return new Set(_textKey(value).split(/\s+/).filter((token) => token.length >= 2));
}

async function _loadRigMidiOutputs() {
  const outputSelect = document.getElementById('rig-midi-output-select');
  const status = document.getElementById('rig-bank-status');
  if (!outputSelect) return;
  outputSelect.innerHTML = '';
  const defaultOpt = document.createElement('option');
  defaultOpt.value = '';
  defaultOpt.textContent = 'Port par défaut';
  outputSelect.appendChild(defaultOpt);
  try {
    const payload = await fetchRigMidiOutputs();
    const outputs = Array.isArray(payload.outputs) ? payload.outputs : [];
    outputs.forEach((name) => {
      const opt = document.createElement('option');
      opt.value = name;
      opt.textContent = name;
      outputSelect.appendChild(opt);
    });
    if (_lastRigMidiOutput && outputs.includes(_lastRigMidiOutput)) {
      outputSelect.value = _lastRigMidiOutput;
    } else if (outputs.length === 1) {
      outputSelect.value = outputs[0];
      _rememberRigMidiOutput(outputs[0]);
    }
    if (!outputs.length && status) {
      status.className = 'rig-bank-status';
      status.textContent = 'Aucun port MIDI détecté. Branche la GP-180 et vérifie Global > MIDI > USB/Mixed.';
    }
  } catch (err) {
    const opt = document.createElement('option');
    opt.value = '';
    opt.textContent = 'Backend MIDI indisponible';
    outputSelect.appendChild(opt);
    if (status) {
      status.className = 'rig-bank-status error';
      status.textContent = `Ports MIDI indisponibles : ${err.message || err}`;
    }
  }
}

function _readSessionValue(key) {
  try {
    return window.sessionStorage?.getItem(key) || '';
  } catch (_err) {
    return '';
  }
}

function _writeSessionValue(key, value) {
  try {
    if (value) window.sessionStorage?.setItem(key, value);
    else window.sessionStorage?.removeItem(key);
  } catch (_err) {
    // In private/restricted contexts, the in-memory variable still covers this tab.
  }
}

function _rememberRigMidiOutput(value) {
  _lastRigMidiOutput = value || '';
  _writeSessionValue(_RIG_MIDI_OUTPUT_SESSION_KEY, _lastRigMidiOutput);
}

function _renderRigBankStatus(payload, sent) {
  const status = document.getElementById('rig-bank-status');
  if (!status) return;
  const profile = payload?.profile || {};
  const midi = Array.isArray(payload?.midi)
    ? payload.midi.map((message) => `[${message.join(', ')}]`).join(' ')
    : '';
  const source = payload?.source ? ` · ${payload.source}` : '';
  const score = Number.isFinite(payload?.score) ? ` · score ${payload.score}` : '';
  const reasons = Array.isArray(payload?.reasons) && payload.reasons.length
    ? `\n${payload.reasons.join(' ')}`
    : '';
  status.className = 'rig-bank-status';
  status.textContent = `${sent ? 'Activé' : 'Conseillé'} : ${profile.name || profile.id || 'profil'}${source}${score}${midi ? ` · MIDI ${midi}` : ''}${reasons}`;
}

async function _previewSelectedRigProfile() {
  const select = document.getElementById('rig-profile-select');
  const status = document.getElementById('rig-bank-status');
  if (!select || !select.value) return;
  try {
    const payload = await activateRigProfile({ profile_id: select.value, dry_run: true });
    _lastRigResolution = payload;
    _renderRigBankStatus(payload, false);
  } catch (err) {
    if (status) {
      status.className = 'rig-bank-status error';
      status.textContent = `Prévisualisation MIDI impossible : ${err.message || err}`;
    }
  }
}

async function _activateSelectedRigProfile() {
  const select = document.getElementById('rig-profile-select');
  const outputSelect = document.getElementById('rig-midi-output-select');
  const status = document.getElementById('rig-bank-status');
  if (!select || !select.value) return;
  _rememberRigMidiOutput(outputSelect?.value || '');
  try {
    const payload = await activateRigProfile({
      profile_id: select.value,
      port_name: outputSelect?.value || null,
      dry_run: false,
    });
    _lastRigResolution = payload;
    _renderRigBankStatus(payload, true);
  } catch (err) {
    if (status) {
      status.className = 'rig-bank-status error';
      status.textContent = `Activation MIDI impossible : ${err.message || err}`;
    }
  }
}

function _renderRig(data) {
  const gearVerifyBtn = document.getElementById('rig-verify-ai-btn');
  if (gearVerifyBtn) {
    const hasGearSheet = data?.is_gears === true;
    gearVerifyBtn.dataset.mode = hasGearSheet ? 'verify' : 'create';
    gearVerifyBtn.textContent = hasGearSheet ? '✨ Vérifier avec IA' : "✨ Créer avec l'IA";
    gearVerifyBtn.title = hasGearSheet
      ? 'Vérifier et corriger cette fiche avec une IA…'
      : 'Créer une fiche avec une IA…';
  }
  const generated = data.is_generated === true;
  const title = document.getElementById('rig-panel-title');
  if (title) title.textContent = `Rig GP-180${generated ? ' (IA)' : ''} — ${data.artist || '?'} · ${data.song || '?'}`;

  const meta = document.getElementById('rig-meta');
  if (meta) {
    const grade = (data.fiabilite || 'D').toUpperCase();
    const gradeClass = grade === 'A' ? 'grade-a' : grade === 'B' ? 'grade-b' : grade === 'C' ? 'grade-c' : '';
    const research = data.original_gear_research || {};
    const isGenericGuitar = (value) => {
      const text = String(value || '').trim().toLowerCase();
      return !text || text === 'default electric guitar' || text === 'electric guitar' || text === 'guitare electrique generique' || text === 'guitare électrique générique';
    };
    const originalGuitar = research.guitar_model || research.guitar_type || data.guitare_originale;
    const originalGuitarImg = data.guitare_originale_image
      ? `<img class="rig-guitar-img" src="/api/rig-image/${encodeURIComponent(data.guitare_originale_image)}" alt="${_esc(originalGuitar || '')}" loading="lazy">`
      : '';
    const recommendedGuitar = !isGenericGuitar(data.recommended_guitar) ? data.recommended_guitar : null;
    const recommendedGuitarImg = recommendedGuitar && data.recommended_guitar_image
      ? `<img class="rig-guitar-img" src="/api/rig-image/${encodeURIComponent(data.recommended_guitar_image)}" alt="${_esc(recommendedGuitar)}" loading="lazy">`
      : '';
    const metaRows = [
      ['Accordage', _esc(data.accordage != null ? String(data.accordage) : '—')],
      ['Capo', _esc(data.capo != null ? String(data.capo) : '—')],
      ['Genre', _esc(data.genre != null && data.genre !== '' ? String(data.genre) : '—')],
    ];
    if (research.guitarist) metaRows.push(['Guitariste(s)', _esc(String(research.guitarist))]);
    metaRows.push([
      'Guitare originale',
      `${_esc(originalGuitar != null && originalGuitar !== '' ? String(originalGuitar) : '—')}${originalGuitarImg}`,
    ]);
    if (research.guitar_type && research.guitar_model) {
      metaRows.push(['Type guitare', _esc(String(research.guitar_type))]);
    }
    if (recommendedGuitar && recommendedGuitar !== originalGuitar) {
      metaRows.push(['Guitare recommandée', `${_esc(String(recommendedGuitar))}${recommendedGuitarImg}`]);
    }
    metaRows.push(['Fiabilité', `<span class="rig-fiabilite-badge ${gradeClass}">${_esc(grade)}</span>`]);
    // Each value is individually escaped or built from safe HTML before being
    // injected raw by the map below (XSS-safe).
    meta.innerHTML = metaRows.map(([lbl, val]) => `
      <div class="rig-meta-item">
        <span class="rig-meta-label">${_esc(lbl)}</span>
        <span class="rig-meta-value">${val}</span>
      </div>`).join('');
  }

  const chain = document.getElementById('rig-chain');
  if (chain && data.chain && data.reglages && data.chain.length) {
    chain.innerHTML = '';
    data.chain.forEach((effect, i) => {
      if (i > 0) {
        const arrow = document.createElement('span');
        arrow.className = 'rig-chain-arrow';
        arrow.textContent = '›';
        chain.appendChild(arrow);
      }
      const reg = data.reglages[effect] || {};
      const active = reg.active !== false && reg.preset != null;
      const block = document.createElement('div');
      block.className = `rig-block ${active ? 'active' : 'inactive'}`;
      const imgHtml = (active && reg.image)
        ? `<img class="rig-block-img" src="/api/rig-image/${encodeURIComponent(reg.image)}" alt="${_esc(reg.preset || '')}" loading="lazy">` : '';
      const presetHtml = (active && reg.preset)
        ? `<span class="rig-block-preset">${_esc(reg.preset)}</span>` : '';
      const paramsHtml = (active && reg.params)
        ? `<span class="rig-block-params">${_esc(reg.params)}</span>` : '';
      block.innerHTML = `
        <span class="rig-block-name">${_esc(effect)}</span>
        ${imgHtml}${presetHtml}${paramsHtml}
      `;
      chain.appendChild(block);
    });
  } else if (chain) {
    chain.innerHTML = '';
  }

  const notesWrap = document.getElementById('rig-notes-wrap');
  const notesEl = document.getElementById('rig-notes');
  const limitesEl = document.getElementById('rig-limites');
  const commentsEl = document.getElementById('rig-comments');
  const commentsDetails = document.getElementById('rig-comments-details');
  if (notesEl) {
    notesEl.textContent = data.notes || '';
    if (notesEl.closest('details')) notesEl.closest('details').style.display = data.notes ? '' : 'none';
  }
  if (limitesEl) {
    limitesEl.textContent = data.limites || '';
    if (limitesEl.closest('details')) limitesEl.closest('details').style.display = data.limites ? '' : 'none';
  }
  if (commentsEl) commentsEl.textContent = data.comments || '';
  if (commentsDetails) commentsDetails.style.display = data.comments ? '' : 'none';
  const hasAny = !!(data.notes || data.limites || data.comments);
  if (notesWrap) notesWrap.style.display = hasAny ? '' : 'none';

  _renderRigImprovements(data.improvements);
}

function _renderRigImprovements(improvements) {
  const wrap = document.getElementById('rig-improvements-wrap');
  const el = document.getElementById('rig-improvements');
  if (!wrap || !el) return;
  const proposals = Array.isArray(improvements?.proposals) ? improvements.proposals : [];
  if (!improvements || (!proposals.length && !improvements.summary)) {
    wrap.style.display = 'none';
    el.innerHTML = '';
    return;
  }
  const summaryHtml = improvements.summary
    ? `<p class="rig-improve-summary">${_esc(improvements.summary)}</p>` : '';
  const rows = proposals.map((p) => {
    const prio = String(p.priority || '').toUpperCase();
    const prioClass = prio === 'P1' ? 'prio-p1' : prio === 'P2' ? 'prio-p2' : prio === 'P3' ? 'prio-p3' : '';
    const bits = [
      p.type ? _esc(String(p.type)) : '',
      p.target ? `→ ${_esc(String(p.target))}` : '',
    ].filter(Boolean).join(' ');
    const asset = p.recommendedAsset ? `<div class="rig-improve-asset">${_esc(String(p.recommendedAsset))}</div>` : '';
    const reason = p.reason ? `<div class="rig-improve-reason">${_esc(String(p.reason))}</div>` : '';
    return `<div class="rig-improve-item">
      <span class="rig-improve-prio ${prioClass}">${_esc(prio || '—')}</span>
      <div class="rig-improve-body"><div class="rig-improve-head">${bits}</div>${asset}${reason}</div>
    </div>`;
  }).join('');
  el.innerHTML = summaryHtml + rows;
  wrap.style.display = '';
}

if (btnRig) btnRig.addEventListener('click', _toggleRig);
{
  const rigClose = document.getElementById('rig-close');
  if (rigClose) rigClose.addEventListener('click', () => {
    if (rigPanel) rigPanel.style.display = 'none';
    if (btnRig) btnRig.classList.remove('tb-btn-active');
  });
  const rigProfileSelect = document.getElementById('rig-profile-select');
  if (rigProfileSelect) rigProfileSelect.addEventListener('change', _previewSelectedRigProfile);
  const rigMidiOutputSelect = document.getElementById('rig-midi-output-select');
  if (rigMidiOutputSelect) {
    rigMidiOutputSelect.addEventListener('change', () => {
      _rememberRigMidiOutput(rigMidiOutputSelect.value || '');
    });
  }
  const rigMidiSendBtn = document.getElementById('rig-midi-send-btn');
  if (rigMidiSendBtn) rigMidiSendBtn.addEventListener('click', _activateSelectedRigProfile);
  // Drag support for the rig panel (same pattern as the hand-viz panel).
  const rigDrag = document.getElementById('rig-drag');
  if (rigDrag && rigPanel) {
    let _rigDrag = null;
    rigDrag.addEventListener('mousedown', (e) => {
      if (e.target.closest('.floating-panel-btn')) return;
      const rect = rigPanel.getBoundingClientRect();
      _rigDrag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!_rigDrag) return;
      const rect = rigPanel.getBoundingClientRect();
      const x = Math.max(12 - rect.width, Math.min(window.innerWidth - 48, e.clientX - _rigDrag.dx));
      const y = Math.max(4, Math.min(window.innerHeight - 48, e.clientY - _rigDrag.dy));
      rigPanel.style.left = x + 'px';
      rigPanel.style.top = y + 'px';
      rigPanel.style.right = 'auto';
      rigPanel.style.bottom = 'auto';
    });
    window.addEventListener('mouseup', () => { _rigDrag = null; });
  }
}

// ── Gear AI-verification floating panel ─────────────────────────────────
{
  const gearVerifyBtn = document.getElementById('rig-verify-ai-btn');
  const gearVerifyPanel = document.getElementById('gear-verify-panel');
  const gearVerifyClose = document.getElementById('gear-verify-close');
  const gearVerifyPromptEl = document.getElementById('gear-verify-prompt');
  const gearVerifyTitleEl = document.getElementById('gear-verify-title');
  const gearVerifyHintEl = document.getElementById('gear-verify-hint');
  const gearVerifyModelEl = document.getElementById('gear-verify-model');
  const gearVerifyPasteEl = document.getElementById('gear-verify-paste');
  const gearVerifyStatusEl = document.getElementById('gear-verify-status');
  const gearVerifyCopyBtn = document.getElementById('gear-verify-copy-btn');
  const gearVerifySaveBtn = document.getElementById('gear-verify-save-btn');
  let gearVerifyCreateMode = false;

  function _setGearVerifyStatus(msg, isError = false) {
    if (!gearVerifyStatusEl) return;
    gearVerifyStatusEl.textContent = msg || '';
    gearVerifyStatusEl.classList.toggle('gear-verify-status-error', !!isError);
  }

  if (gearVerifyBtn) gearVerifyBtn.addEventListener('click', async () => {
    if (!gearVerifyPanel || !_lastRigFile) return;
    gearVerifyCreateMode = gearVerifyBtn.dataset.mode === 'create';
    gearVerifyPanel.dataset.mode = gearVerifyCreateMode ? 'create' : 'verify';
    if (gearVerifyTitleEl) {
      gearVerifyTitleEl.textContent = gearVerifyCreateMode ? 'Créer avec une IA' : 'Vérifier avec une IA';
    }
    if (gearVerifyHintEl) {
      gearVerifyHintEl.textContent = gearVerifyCreateMode
        ? "Copiez le prompt dans un LLM connecté, collez sa réponse JSON, puis créez la fiche."
        : "Copiez le prompt dans un LLM connecté, collez sa réponse JSON, puis mettez la fiche à jour.";
    }
    if (gearVerifyModelEl) {
      gearVerifyModelEl.textContent = 'Modèle conseillé : GPT-5.6 Sol · raisonnement élevé · recherche Web activée.';
    }
    if (gearVerifySaveBtn) {
      gearVerifySaveBtn.textContent = gearVerifyCreateMode ? 'Créer et enregistrer' : 'Valider et enregistrer';
    }
    gearVerifyPanel.style.display = 'flex';
    if (gearVerifyPasteEl) gearVerifyPasteEl.value = '';
    _setGearVerifyStatus('');
    if (gearVerifyPromptEl) gearVerifyPromptEl.value = 'Chargement du prompt…';
    try {
      const prompt = await fetchGearVerificationPrompt(_lastRigFile);
      if (gearVerifyPromptEl) gearVerifyPromptEl.value = prompt;
    } catch (e) {
      if (gearVerifyPromptEl) gearVerifyPromptEl.value = '';
      _setGearVerifyStatus(e.message || 'Échec du chargement du prompt', true);
    }
  });

  if (gearVerifyClose) gearVerifyClose.addEventListener('click', () => {
    if (gearVerifyPanel) gearVerifyPanel.style.display = 'none';
  });

  if (gearVerifyCopyBtn) gearVerifyCopyBtn.addEventListener('click', async () => {
    if (!gearVerifyPromptEl) return;
    try {
      await navigator.clipboard.writeText(gearVerifyPromptEl.value);
      _setGearVerifyStatus('Prompt copié dans le presse-papiers.');
    } catch (_e) {
      gearVerifyPromptEl.select();
      document.execCommand('copy');
      _setGearVerifyStatus('Prompt copié dans le presse-papiers.');
    }
  });

  if (gearVerifySaveBtn) gearVerifySaveBtn.addEventListener('click', async () => {
    if (!_lastRigFile || !gearVerifyPasteEl) return;
    let gear;
    try {
      gear = JSON.parse(gearVerifyPasteEl.value);
    } catch (_e) {
      _setGearVerifyStatus('JSON invalide — vérifiez le collage.', true);
      return;
    }
    _setGearVerifyStatus('Enregistrement…');
    try {
      const result = await saveGearSheet(_lastRigFile, gear);
      _lastRig = result.view;
      _renderRig(result.view);
      const warn = (result.warnings || []).length ? ` (${result.warnings.length} avertissement(s))` : '';
      _setGearVerifyStatus(`${gearVerifyCreateMode ? 'Fiche créée' : 'Fiche mise à jour'}${warn}.`);
      if (gearVerifyPanel) setTimeout(() => { gearVerifyPanel.style.display = 'none'; }, 1200);
    } catch (e) {
      _setGearVerifyStatus(e.message || "Échec de l'enregistrement", true);
    }
  });

  // Drag support (same pattern as the rig panel).
  const gearVerifyDrag = document.getElementById('gear-verify-drag');
  if (gearVerifyDrag && gearVerifyPanel) {
    let _gearVerifyDrag = null;
    gearVerifyDrag.addEventListener('mousedown', (e) => {
      if (e.target.closest('.floating-panel-btn')) return;
      const rect = gearVerifyPanel.getBoundingClientRect();
      _gearVerifyDrag = { dx: e.clientX - rect.left, dy: e.clientY - rect.top };
      e.preventDefault();
    });
    window.addEventListener('mousemove', (e) => {
      if (!_gearVerifyDrag) return;
      const rect = gearVerifyPanel.getBoundingClientRect();
      const x = Math.max(12 - rect.width, Math.min(window.innerWidth - 48, e.clientX - _gearVerifyDrag.dx));
      const y = Math.max(4, Math.min(window.innerHeight - 48, e.clientY - _gearVerifyDrag.dy));
      gearVerifyPanel.style.left = x + 'px';
      gearVerifyPanel.style.top = y + 'px';
      gearVerifyPanel.style.right = 'auto';
      gearVerifyPanel.style.bottom = 'auto';
    });
    window.addEventListener('mouseup', () => { _gearVerifyDrag = null; });
  }
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
  document.querySelectorAll('#view-seg .view-seg-btn').forEach(btn => {
    btn.classList.toggle('view-seg-active', btn.dataset.mode === active);
  });
  _syncZoomControl(active);
  _applyZoomForMode(active);
}

document.querySelectorAll('#view-seg .view-seg-btn').forEach(btn => {
  btn.addEventListener('click', () => {
    if (!selRepresentationMode) return;
    // Ignore clicks on a pill locked for the current (non-guitar) track.
    if (btn.disabled || btn.classList.contains('view-seg-disabled')) return;
    // Slope legibility pills (P1–P4) carry data-slope-mode, not data-mode —
    // they switch the Slope aid, not the notation view. Skip the view logic.
    if (btn.dataset.mode == null) return;
    selRepresentationMode.value = btn.dataset.mode;
    selRepresentationMode.dispatchEvent(new Event('change'));
  });
});

// Slope legibility sub-mode pills (P1–P4): switch the in-motion readability aid
// on the live Slope renderer and persist the choice.
function _syncSlopeModePills() {
  if (!_slopeModeSeg) return;
  _slopeModeSeg.querySelectorAll('.view-seg-btn').forEach((btn) => {
    btn.classList.toggle('view-seg-active', btn.dataset.slopeMode === _slopeMode);
  });
}
if (_slopeModeSeg) {
  _slopeModeSeg.querySelectorAll('.view-seg-btn').forEach((btn) => {
    btn.addEventListener('click', () => {
      const mode = btn.dataset.slopeMode;
      if (!_SLOPE_MODES.includes(mode)) return;
      _slopeMode = mode;
      try { localStorage.setItem(_SLOPE_MODE_KEY, mode); } catch (_) { /* private mode */ }
      _syncSlopeModePills();
      _slopeRenderer?.setLegibilityMode(mode);
      _slopeRenderer?.render();
    });
  });
  _syncSlopeModePills();
}

// P2 density slider: how many beats of upcoming notes the Slope view shows.
// Applies live regardless of which legibility sub-mode is active.
if (_rngSlopeDensity) {
  _rngSlopeDensity.addEventListener('input', () => {
    const beats = Math.max(
      _SLOPE_DENSITY_MIN,
      Math.min(_SLOPE_DENSITY_MAX, parseFloat(_rngSlopeDensity.value) || 24),
    );
    _slopeDensity = beats;
    try { localStorage.setItem(_SLOPE_DENSITY_KEY, String(beats)); } catch (_) { /* private mode */ }
    _slopeRenderer?.setDensity(beats);
    _slopeRenderer?.render();
  });
}

_syncViewSegPills();

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
/**
 * Build an explicit "no fingering for this track" payload. Posting this (rather
 * than nothing) lets the hand-viz iframe degrade gracefully — it shows a clear
 * empty state instead of leaving a stale hand from a previous track or falling
 * back to its built-in demo lick. Carries `fingered:false` + empty `frames`.
 */
function _emptyHandVizPayload(reason) {
  return {
    meta: {
      title: (renderer?.data?.title) || 'FretWise',
      artist: (renderer?.data?.artist) || '',
      track: (renderer?.data?.track_name) || '',
      tempo: (renderer?.data?.tempo) || 120,
      synced: true,
      max_seconds: 10,
      fingered: false,
      empty_reason: reason || 'no-fingering',
    },
    fretboard: {
      num_frets: 12,
      scale_length_mm: 648,
      tuning: ['E2', 'A2', 'D3', 'G3', 'B3', 'E4'],
      capo: 0,
      num_strings: 6,
    },
    frames: [],
  };
}

function _buildHandVizPayload() {
  if (!renderer || !renderer.data || !Array.isArray(renderer.data.results)) {
    return _emptyHandVizPayload('no-track');
  }
  const results = renderer.data.results;
  if (results.length === 0) return _emptyHandVizPayload('empty-track');
  // Staff-only / vocal tracks carry note results but no fretted fingering
  // (every result is an open string or has no finger / non-positive fret).
  // Treat that as "no fingering" so the hand panel degrades gracefully.
  const hasFretted = results.some((r) => {
    const finger = String(r.finger || 'open');
    const fret = Number.parseInt(r.fret, 10);
    return finger !== 'open' && !finger.endsWith('OPEN')
      && Number.isFinite(fret) && fret > 0;
  });
  if (!hasFretted || renderer.data.fingered === false) {
    return _emptyHandVizPayload('staff-only');
  }
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
  // ── Real fretboard geometry threaded from the source ──────────────────
  // num_frets follows the music: enough room for the highest fret used,
  // never fewer than 12 so the neck still looks like a neck on low pieces.
  let highestFret = 0;
  for (const r of results) {
    if (typeof r.fret === 'number' && r.fret > highestFret) highestFret = r.fret;
  }
  const numFrets = Math.max(12, highestFret + 2);
  // tuning: the active track's real open-string MIDI pitches (low→high),
  // converted to note-name+octave strings the renderer expects. Falls back
  // to standard 6-string tuning when the track carries none.
  const activeTrack = (currentTracks || []).find((t) => t.id === currentTrackId);
  const trackTuning = activeTrack && Array.isArray(activeTrack.tuning) ? activeTrack.tuning : null;
  const tuning = (trackTuning && trackTuning.length)
    ? trackTuning.map(_midiToNoteName)
    : ['E2', 'A2', 'D3', 'G3', 'B3', 'E4'];
  // scale_length_mm / capo are optional and only present once the backend
  // exposes them; thread them through when available (forward-compatible).
  const scaleLengthMm = (renderer.data && typeof renderer.data.scale_length_mm === 'number')
    ? renderer.data.scale_length_mm
    : 648;
  const capo = (renderer.data && typeof renderer.data.capo === 'number' && renderer.data.capo > 0)
    ? renderer.data.capo
    : 0;
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
      num_frets: numFrets,
      scale_length_mm: scaleLengthMm,
      tuning,
      capo,
      num_strings: tuning.length,
    },
    frames,
  };
}

/** Convert a MIDI pitch (e.g. 40) to a note name with octave (e.g. "E2"). */
function _midiToNoteName(midi) {
  const NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
  const octave = Math.floor(midi / 12) - 1;   // MIDI 60 = C4 (scientific pitch)
  return NAMES[((midi % 12) + 12) % 12] + octave;
}

function _postHandVizData() {
  const payload = _buildHandVizPayload();
  if (!payload) return;
  const message = { type: 'fretwise-hand-data', payload };
  if (_isHand3dViewVisible() && _ensureHand3dViewFrame() && hand3dViewFrame.contentWindow) {
    hand3dViewFrame.contentWindow.postMessage(message, '*');
  }
  // After reinstalling data, also push current time so the iframe starts
  // at the right place instead of t=0.
  _postHandVizTime(true);
}

function _postHandVizTime(force = false) {
  const hand3dVisible = _isHand3dViewVisible() && _ensureHand3dViewFrame();
  if (!hand3dVisible) return;
  if (!playback || typeof playback.getCurrentTimeSec !== 'function') return;
  const now = performance.now();
  if (!force && playback.isPlaying && now - _lastHandVizSeekPostMs < HAND_VIZ_SEEK_POST_MS) {
    return;
  }
  _lastHandVizSeekPostMs = now;
  const message = {
    type: 'fretwise-hand-seek',
    t: playback.getCurrentTimeSec(),
    playing: !!playback.isPlaying,
  };
  if (hand3dViewFrame.contentWindow) {
    hand3dViewFrame.contentWindow.postMessage(message, '*');
  }
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
    const _t = notifyTask(`Import de ${file.name}…`, { progress: 0 });
    try {
      await uploadFile(file, (frac, loaded, total) => {
        _t.progress(frac);
        _t.message(`Import de ${file.name}… ${_fmtMB(loaded)} / ${_fmtMB(total)} Mo`);
      });
      _t.message('Analyse du morceau…'); _t.progress(null);
      if (uploadStatus) { uploadStatus.textContent = `✓ ${file.name} added`; uploadStatus.style.color = '#4caf50'; }
      uploadInput.value = '';
      await loadFiles();
      _t.done(`${file.name} ajouté`);
    } catch (err) {
      _t.error(err.message || 'Import échoué');
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
      if (_ensureSolvedThenPlay()) break;  // nothing solved yet → compute first
      playback.toggle();
      updatePlayButton(playback.isPlaying);
      if (playback.isPlaying) startCursorLoop();
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

// ── Per-view zoom (magnify slider) ───────────────────────────────────

function _zoomLabelText(pct) {
  return pct === 0 ? '0%' : (pct > 0 ? `+${pct}%` : `${pct}%`);
}

/** Apply canvas CSS zoom for tab mode; clear it for SVG modes. */
function _applyZoomForMode(mode) {
  const factor = 1 + ((_ZOOM_BASE[mode] + (_viewZoom[mode] ?? 0)) / 100);
  const cssVal = factor === 1 ? '' : String(factor);
  if (mode === MODES.TABLATURE) {
    if (tabCanvas) tabCanvas.style.zoom = cssVal;
    if (cursorCanvas) cursorCanvas.style.zoom = cssVal;
  } else {
    // SVG zoom is handled by _svgRenderWidth + CSS width:100% on the <svg> tag
    if (tabCanvas) tabCanvas.style.zoom = '';
    if (cursorCanvas) cursorCanvas.style.zoom = '';
  }
}

/** Update the zoom slider and label to reflect the current mode's stored zoom. */
function _syncZoomControl(mode) {
  const pct = _viewZoom[mode] ?? 0;
  if (rngZoom) rngZoom.value = String(pct);
  if (zoomLabel) zoomLabel.textContent = _zoomLabelText(pct);
}

/** Called when the zoom slider moves. */
function _onZoomInput() {
  const pct = parseInt(rngZoom.value, 10);
  const mode = getSelectedRepresentationMode();
  _viewZoom[mode] = pct;
  if (zoomLabel) zoomLabel.textContent = _zoomLabelText(pct);
  _applyZoomForMode(mode);
  if (mode !== MODES.TABLATURE && mode !== MODES.TABLATURE_RHYTHM
      && mode !== MODES.SLOPE && mode !== MODES.HAND_3D) {
    // Force SVG re-fetch with the new (zoom-adjusted) page width.
    _lastSvgWidth[mode] = null;
    _refreshSvgView();
  }
}

rngZoom?.addEventListener('input', _onZoomInput);

// ── resize handling ─────────────────────────────────────────────────

let resizeTimer;
// Per-mode width-bucket used for the current SVG render.  Keyed by mode string
// (e.g. 'standard', 'standard_tablature') so switching modes never contaminates
// the guard for another mode.  A null/missing entry means "force-refresh".
const _lastSvgWidth = {};

/**
 * Re-fetch and repaint the SVG when the viewport width bucket or zoom changed.
 *
 * Robustness invariants (why Staff/Mixed used to break on every zoom/resize):
 *  - `_lastSvgWidth` is now per-mode so switching Staff↔Mixed never pollutes
 *    the guard for the other mode.
 *  - `_svgDriver` is recreated after every innerHTML swap: the old instance
 *    held orphaned DOM refs (the rects it injected were destroyed by innerHTML
 *    replacement), making measure highlights invisible after the first refresh.
 *  - `newWidth === undefined` (canvas-only / unknown mode) → early-exit, no fetch.
 *  - Errors are surfaced to the console instead of being swallowed silently.
 */
async function _refreshSvgView() {
  if (!currentFile || !currentTrackId) return;
  const mode = getSelectedRepresentationMode();
  const newWidth = _svgRenderWidth(mode);
  // Canvas-only modes (tablature, tablature_rhythm) return undefined — skip.
  if (newWidth === undefined) return;
  // Per-mode guard: avoid redundant fetches when the width bucket didn't change.
  if (newWidth === _lastSvgWidth[mode]) return;
  _lastSvgWidth[mode] = newWidth;
  try {
    const data = await _cachedSolve(currentFile, currentTrackId, mode, getRulePreferences(), newWidth);
    // Guard: user may have switched to Tab (hidden) while the fetch was in flight.
    if (!coreSvgView || coreSvgView.style.display === 'none') return;
    coreSvgView.innerHTML = data?.core_svg || '';
    _applyResponsiveCoreSvg();
    _syncCoreSvgFingering();
    _syncCoreSvgAnnotations();
    _syncCoreSvgHandOverlay();
    // Recreate the cursor driver: the previous instance's rects were destroyed
    // when innerHTML was replaced above.  Without this, measure highlights and
    // click-to-seek are silently broken after every zoom or resize.
    if (data?.measure_regions?.length && coreSvgView) {
      _svgDriver = new SvgCursorDriver(coreSvgView, data);
      _svgDriver.init();
      _svgDriver.followPlayhead = _followPlayhead;
      // Restore the current-measure highlight immediately (no wait for next tick).
      if (playback && renderer) {
        _svgDriver.highlight(
          renderer.cursorMeasure ?? 0, playback.loopStart, playback.loopEnd,
        );
      }
    }
  } catch (err) {
    // Log the error so it is visible in DevTools, but keep the existing SVG.
    console.warn('[fretwise] SVG refresh failed:', err);
  }
}

window.addEventListener('resize', () => {
  clearTimeout(resizeTimer);
  resizeTimer = setTimeout(() => {
    if (renderer) {
      renderer._buildSystems();
      renderer.render();
    }
    _updateTrackTabsChevrons();
    // _refreshSvgView uses a per-mode bucket guard — it only fetches when the
    // 50 px-quantised render width actually changed, so rapid minor resizes
    // don't hammer the server.  _svgDriver is recreated inside _refreshSvgView
    // whenever the SVG content changes (new bucket → new measure regions).
    _refreshSvgView();
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
  _initLibPageSize();

  $('#chord-bar-toggle')?.addEventListener('click', () => {
    const cont = $('#tab-container');
    _setChordsOpen(!cont?.classList.contains('chords-open'));
  });
});

// ── Red cursor overlay ──────────────────────────────────────────────

let _cursorRaf = null;
let _autoScrollTarget = null;

// ── Instrument (soundfont) loading feedback (via notify.js) ────────
let _synthTask = null;  // active notify task while a soundfont downloads/parses
const _fmtMB = (bytes) => (bytes / 1048576).toFixed(1);  // bytes → "12.3" (MB)

function startCursorLoop() {
  if (_cursorRaf) cancelAnimationFrame(_cursorRaf);
  function loop() {
    // A draw error (overlay geometry, auto-scroll, SVG driver) must never kill
    // this loop and freeze the red playhead. Guard + log, then keep ticking.
    try {
      _drawCursorOverlay();
      _tickSvgCursor();
    } catch (err) {
      console.warn('[FretWise] cursor overlay error (continuing):', err);
    }
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
  // The SVG cursor line was removed; the current-measure highlight is driven by
  // playback.onMeasureChange (meter-aware timeline). Nothing to update per frame.
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

  // The cursor LINE was removed; we only need the current measure's screen column
  // to keep it in the reading zone (auto-scroll). Use the meter-aware measure-start
  // onset so scrolling stays correct across meter changes.
  const cursorOnset = playback._measureOnsetBeats(renderer.cursorMeasure || 0);
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
  // No cursor line is drawn — the highlighted current measure is the only
  // playback indicator. The cleared canvas above removes any stale line.
}

// ── Library table: sort and filter events ──────────────────────────

document.querySelectorAll('#lib-table th.sortable').forEach(th => {
  th.addEventListener('click', () => {
    const col = th.dataset.col;
    if (_libSort.col === col) _libSort.dir *= -1;
    else { _libSort.col = col; _libSort.dir = 1; }
    _libPage = 0;   // a new sort order invalidates the current page
    _renderLibTable();
  });
});

const libSearch = $('#lib-search');
if (libSearch) libSearch.addEventListener('input', () => { _libSearch = libSearch.value; _libPage = 0; _renderLibTable(); });

const libGenreFilter = $('#lib-genre-filter');
if (libGenreFilter) libGenreFilter.addEventListener('change', () => { _libGenreFilter = libGenreFilter.value; _libPage = 0; _renderLibTable(); });

const libFormatFilter = $('#lib-format-filter');
if (libFormatFilter) libFormatFilter.addEventListener('change', () => { _libFormatFilter = libFormatFilter.value; _libPage = 0; _renderLibTable(); });

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

  await _loadRigProfileEditor();

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
        const _t = notifyTask(`Envoi du soundfont ${file.name}…`, { progress: 0 });
        try {
          await uploadSoundfont(file, (frac, loaded, total) => {
            _t.progress(frac);
            _t.message(`Envoi du soundfont… ${_fmtMB(loaded)} / ${_fmtMB(total)} Mo`);
          });
          _t.done('Soundfont ajouté');
          if (sfUploadStatus) sfUploadStatus.textContent = '✓ Uploaded!';
          setTimeout(() => { if (sfUploadStatus) sfUploadStatus.textContent = ''; }, 3000);
          await _loadSoundfontsPanel();
        } catch (err) {
          _t.error(err.message || 'Envoi échoué');
          if (sfUploadStatus) sfUploadStatus.textContent = '✗ ' + err.message;
        }
        e.target.value = '';
      });
    }
  }
}

const _GP180_PROFILE_MODULES = ['NR', 'PRE', 'WAH', 'DST', 'N→S', 'AMP', 'CAB/IR', 'EQ', 'MOD', 'DLY', 'RVB', 'VOL'];

function _fillRigModuleEditor(modules = []) {
  const container = $('#set-rig-profile-modules');
  if (!container) return;
  const bySlot = new Map(
    (Array.isArray(modules) ? modules : []).map((item) => [String(item?.module || '').toUpperCase(), item]),
  );
  container.innerHTML = '';
  for (const slot of _GP180_PROFILE_MODULES) {
    const item = bySlot.get(slot.toUpperCase()) || null;
    const row = document.createElement('div');
    row.className = 'rig-module-row';
    row.dataset.module = slot;
    const active = document.createElement('input');
    active.type = 'checkbox';
    active.className = 'rig-module-active';
    active.checked = item?.active === true;
    active.setAttribute('aria-label', `Activer ${slot}`);
    const label = document.createElement('label');
    label.textContent = slot;
    const model = document.createElement('input');
    model.type = 'text';
    model.className = 'settings-text-input rig-module-model';
    model.value = String(item?.model || '');
    model.placeholder = 'Modèle exact';
    model.disabled = !active.checked;
    const warning = document.createElement('span');
    warning.className = 'rig-module-warning';
    warning.hidden = true;
    const refreshWarning = () => {
      const tapeInReverb = slot === 'RVB' && /\btape(?: delay)?\b/i.test(model.value);
      warning.hidden = !tapeInReverb;
      warning.textContent = tapeInReverb
        ? 'Manuel firmware 1.0.0: Tape Delay appartient à DLY, pas RVB. Valeur conservée.'
        : '';
    };
    active.addEventListener('change', () => {
      model.disabled = !active.checked;
      if (active.checked) model.focus();
      refreshWarning();
    });
    model.addEventListener('input', refreshWarning);
    row.append(active, label, model, warning);
    container.appendChild(row);
    refreshWarning();
  }
}

function _rigModulesFromSettingsForm() {
  const rows = [...document.querySelectorAll('#set-rig-profile-modules .rig-module-row')];
  return rows.flatMap((row) => {
    const active = row.querySelector('.rig-module-active')?.checked === true;
    if (!active) return [];
    const model = row.querySelector('.rig-module-model')?.value?.trim() || '';
    if (!model) throw new Error(`Active module ${row.dataset.module} requires a model.`);
    return [{ module: row.dataset.module, model, active: true }];
  });
}

async function _loadRigProfileEditor(selectedId = null) {
  const select = $('#set-rig-profile-select');
  const bindingProfile = $('#set-rig-binding-profile');
  const status = $('#set-rig-profile-status');
  if (!select || !bindingProfile) return;
  try {
    const bank = await fetchRigBank();
    _rigBank = bank;
    const profiles = Array.isArray(bank.profiles) ? bank.profiles : [];
    select.innerHTML = '';
    bindingProfile.innerHTML = '';
    for (const profile of profiles) {
      const genre = profile.genre ? ` · ${profile.genre}` : '';
      const label = `${profile.name || profile.id} · PC ${profile.program}${genre}`;
      const opt = document.createElement('option');
      opt.value = profile.id;
      opt.textContent = label;
      select.appendChild(opt);
      const bindOpt = document.createElement('option');
      bindOpt.value = profile.id;
      bindOpt.textContent = label;
      bindingProfile.appendChild(bindOpt);
    }
    const nextId = selectedId || select.value || profiles[0]?.id || '';
    if (nextId) {
      select.value = nextId;
      bindingProfile.value = nextId;
      _fillRigProfileForm(profiles.find((profile) => profile.id === nextId) || profiles[0]);
    } else {
      _fillRigProfileForm(null);
    }
    if (status && !profiles.length) status.textContent = 'No GP-180 profiles yet.';
  } catch (err) {
    if (status) status.textContent = `Failed to load GP-180 profiles: ${err.message || err}`;
  }
}

function _fillRigProfileForm(profile) {
  const set = (id, value) => { const el = $(id); if (el) el.value = value ?? ''; };
  set('#set-rig-profile-id', profile?.id || '');
  set('#set-rig-profile-name', profile?.name || '');
  set('#set-rig-profile-program', profile?.program ?? 0);
  set('#set-rig-profile-channel', profile?.midi_channel ?? 1);
  set('#set-rig-profile-artist', profile?.artist || '');
  set('#set-rig-profile-genre', profile?.genre || '');
  set('#set-rig-profile-tags', Array.isArray(profile?.tags) ? profile.tags.join(', ') : '');
  set('#set-rig-profile-notes', profile?.notes || '');
  _fillRigModuleEditor(profile?.modules || []);
}

function _rigProfileFromSettingsForm() {
  const id = $('#set-rig-profile-id')?.value?.trim();
  const name = $('#set-rig-profile-name')?.value?.trim();
  const program = parseInt($('#set-rig-profile-program')?.value || '', 10);
  const midiChannel = parseInt($('#set-rig-profile-channel')?.value || '', 10);
  const artist = $('#set-rig-profile-artist')?.value?.trim();
  const genre = $('#set-rig-profile-genre')?.value?.trim();
  const tags = ($('#set-rig-profile-tags')?.value || '')
    .split(',')
    .map((tag) => tag.trim())
    .filter(Boolean);
  const notes = $('#set-rig-profile-notes')?.value?.trim() || '';
  const modules = _rigModulesFromSettingsForm();
  if (!id || !name || !Number.isInteger(program) || !Number.isInteger(midiChannel)) {
    throw new Error('Profile id, name, program and MIDI channel are required.');
  }
  return {
    id,
    name,
    program,
    midi_channel: midiChannel,
    artist: artist || undefined,
    genre: genre || undefined,
    tags,
    source: 'settings',
    notes,
    modules,
  };
}

async function _saveRigProfileFromSettings() {
  const btn = $('#set-rig-profile-save');
  const status = $('#set-rig-profile-status');
  try {
    if (btn) btn.disabled = true;
    const profile = _rigProfileFromSettingsForm();
    await saveRigProfile(profile);
    if (status) status.textContent = 'Profile saved.';
    await _loadRigProfileEditor(profile.id);
  } catch (err) {
    if (status) status.textContent = `Save failed: ${err.message || err}`;
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function _saveRigBindingFromSettings() {
  const scope = $('#set-rig-binding-scope')?.value || 'song';
  const key = $('#set-rig-binding-key')?.value?.trim();
  const profileId = $('#set-rig-binding-profile')?.value;
  const status = $('#set-rig-profile-status');
  if (!key || !profileId) {
    if (status) status.textContent = 'Binding key and profile are required.';
    return;
  }
  try {
    await saveRigBinding({ scope, key, profile_id: profileId });
    if (status) status.textContent = `Binding saved: ${scope} "${key}".`;
    const keyInput = $('#set-rig-binding-key');
    if (keyInput) keyInput.value = '';
    await _loadRigProfileEditor(profileId);
  } catch (err) {
    if (status) status.textContent = `Binding failed: ${err.message || err}`;
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

const setRigProfileSelect = $('#set-rig-profile-select');
if (setRigProfileSelect) {
  setRigProfileSelect.addEventListener('change', () => {
    const profiles = Array.isArray(_rigBank?.profiles) ? _rigBank.profiles : [];
    _fillRigProfileForm(profiles.find((profile) => profile.id === setRigProfileSelect.value) || null);
  });
}

const setRigProfileNew = $('#set-rig-profile-new');
if (setRigProfileNew) {
  setRigProfileNew.addEventListener('click', () => {
    _fillRigProfileForm({
      id: 'new-gp180-profile',
      name: 'New GP-180 Profile',
      program: 0,
      midi_channel: 1,
      tags: [],
      notes: '',
    });
    const status = $('#set-rig-profile-status');
    if (status) status.textContent = 'Edit the new id/name, then save.';
  });
}

const setRigProfileSave = $('#set-rig-profile-save');
if (setRigProfileSave) setRigProfileSave.addEventListener('click', _saveRigProfileFromSettings);

const setRigBindingSave = $('#set-rig-binding-save');
if (setRigBindingSave) setRigBindingSave.addEventListener('click', _saveRigBindingFromSettings);

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
  // Scroll the score to a 1-based measure so the user can see the flagged spot.
  focusMeasure: (measureIndex) => {
    const zeroBased = Math.max(0, (measureIndex || 1) - 1);
    _setFollowPlayhead(false);  // stop auto-scroll fighting the manual jump
    if (_svgDriver && _svgDriver.scrollToMeasure) {
      if (_svgDriver.scrollToMeasure(zeroBased)) return;
    }
    if (renderer && typeof renderer.scrollToMeasure === 'function') {
      renderer.scrollToMeasure(zeroBased);
    }
  },
});
