/**
 * main.js — App initialization, page routing, event wiring
 *
 * Pages:  file-selector → track-selector → tab-viewer
 * Orchestra: renderer + playback + toolbar
 */

import { fetchExportPdf, fetchFiles, fetchNotes, fetchSolve, fetchTracks, uploadFile } from './api.js';
import { TabRenderer, buildLegendHTML } from './renderer.js';
import { PlaybackEngine } from './playback.js';
import { SvgCursorDriver } from './svg-playback.js';

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

// ── DOM references ──────────────────────────────────────────────────

const $  = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

const fileSelector  = $('#file-selector');
const trackSelector = $('#track-selector');
const tabViewer     = $('#tab-viewer');
const fileGrid      = $('#file-list');
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
const btnFingering  = $('#btn-fingering');
const btnExportPdf  = $('#btn-export-pdf');
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
  fileSelector.style.display  = page === 'files'  ? '' : 'none';
  trackSelector.style.display = page === 'tracks' ? '' : 'none';
  tabViewer.style.display     = isViewer ? '' : 'none';
  toolbar.style.display       = isViewer ? '' : 'none';
  if (headerMeta)       headerMeta.style.display       = isViewer ? '' : 'none';
  if (btnHeaderBack)    btnHeaderBack.style.display    = isViewer ? '' : 'none';
  const tabsBar = $('#track-tabs-bar');
  if (tabsBar) tabsBar.style.display = isViewer ? '' : 'none';
  // Ensure the old bottom bar class doesn't shift bottom elements
  document.body.classList.remove('has-multitrack-bar');
}

// ── File selector ───────────────────────────────────────────────────

async function loadFiles() {
  showPage('files');
  fileGrid.innerHTML = '<p style="color:#aaa;">Loading files…</p>';
  try {
    const files = await fetchFiles();
    if (!files.length) {
      fileGrid.innerHTML = '<p style="color:#aaa;">No score files found.</p>';
      return;
    }
    fileGrid.innerHTML = '';
    for (const f of files) {
      const card = document.createElement('div');
      card.className = 'file-card';
      card.innerHTML = `
        <div class="file-icon">🎸</div>
        <div class="file-name">${sanitize(f.stem)}</div>
        <div class="file-ext">${sanitize(f.format)}</div>
      `;
      card.addEventListener('click', () => selectFile(f.name));
      fileGrid.appendChild(card);
    }
  } catch (err) {
    fileGrid.innerHTML = `<p style="color:#ff5555;">Error: ${sanitize(err.message)}</p>`;
  }
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
      fileGrid.innerHTML = `<p style="color:#ff5555;">No guitar tracks found in "${sanitize(filename)}".</p>`;
      return;
    }
    // Auto-select first track — skip the intermediate track-selector page
    await selectTrack(tracks[0].id, tracks[0].name);
  } catch (err) {
    fileGrid.innerHTML = `<p style="color:#ff5555;">Error loading "${sanitize(filename)}": ${sanitize(err.message)}</p>`;
  }
}

// ── Tab viewer ──────────────────────────────────────────────────────

function populateTrackSwitcher(_trackId) {
  // Track switching is now handled by the multi-track bar name clicks — no-op
}

async function selectTrack(trackId, trackName) {
  currentTrackId = trackId;
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
  } catch (err) {
    ctx.clearRect(0, 0, tabCanvas.width, tabCanvas.height);
    ctx.fillStyle = '#ff5555';
    ctx.fillText(`Error: ${err.message}`, 200, 50);
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
  return selRepresentationMode?.value || 'standard_tablature';
}

function getRulePreferences() {
  return {
    sameFingerPenalty: prefSameFingerPenalty?.checked !== false,
    inferImplicitLegato: prefInferLegato?.checked !== false,
    showHandOverlay: prefHandOverlay?.checked !== false,
  };
}

function _representationModeLabel(mode) {
  switch (mode) {
    case 'standard':
      return 'STANDARD';
    case 'standard_tablature':
      return 'STANDARD + TAB';
    case 'tablature_rhythm':
      return 'TAB + RHYTHM';
    case 'tablature':
      return 'TAB';
    default:
      return 'TAB + RHYTHM';
  }
}

function applyRepresentationModeView(data) {
  const representationMode = data?.representation_mode || getSelectedRepresentationMode();
  if (selRepresentationMode && selRepresentationMode.value !== representationMode) {
    selRepresentationMode.value = representationMode;
  }
  if (metaViewMode) {
    metaViewMode.textContent = _representationModeLabel(representationMode);
  }

  const showCore = representationMode !== 'tablature';
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
  const tabNotes = svg.querySelectorAll('text.fw-tab-note');
  for (const noteText of tabNotes) {
    const onset = Number.parseFloat(noteText.getAttribute('data-onset') || '');
    const tabString = Number.parseInt(noteText.getAttribute('data-tab-string') || '', 10);
    if (!Number.isFinite(onset) || !Number.isInteger(tabString)) continue;

    const resultNote = byOnsetString.get(`${onset.toFixed(6)}:${tabString}`);
    if (!resultNote || Number.parseInt(resultNote.fret, 10) <= 0) continue;

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
    if (m >= 0 && playback) playback.goToMeasure(m);
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
  if (_svgMode !== 'tablature' && data.measure_regions?.length && coreSvgView) {
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
      if (m >= 0) playback.goToMeasure(m);
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

    tab.appendChild(colorBar);
    tab.appendChild(body);

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

if (btnPlay) {
  btnPlay.addEventListener('click', () => {
    if (!playback) return;
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
    if (representationMode === 'tablature') {
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
  const active = selRepresentationMode?.value || 'standard_tablature';
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
    if (getSelectedRepresentationMode() === 'tablature') {
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
  if (!visible) setTimeout(_postHandVizData, 100);
}

if (btnHandViz) btnHandViz.addEventListener('click', _toggleHandViz);

if (handVizClose) {
  handVizClose.addEventListener('click', () => {
    if (handVizPanel) handVizPanel.style.display = 'none';
    if (btnHandViz) btnHandViz.classList.remove('tb-btn-active');
  });
}
if (handVizResync) handVizResync.addEventListener('click', _postHandVizData);

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
  const TOP_GUTTER  = 70;   // header (50) + small buffer
  const BOT_GUTTER  = 88;   // toolbar (52) + scrubber (16) + buffer
  const canvasRect = tabCanvas.getBoundingClientRect();
  const cursorViewportY = canvasRect.top + col.yTop;
  const vh = window.innerHeight;
  const usable = vh - TOP_GUTTER - BOT_GUTTER;
  const triggerLow  = vh - BOT_GUTTER - 20;   // near bottom fixed UI
  const triggerHigh = TOP_GUTTER + 10;         // near top header
  const targetY     = TOP_GUTTER + usable * 0.30; // land at 30% of usable area
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

// ── Boot ────────────────────────────────────────────────────────────

loadFiles();
