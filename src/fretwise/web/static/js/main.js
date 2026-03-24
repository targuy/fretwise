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
let loopASet = false;  // has A marker been set
let soundOn = false;   // tracks mute state across track changes
const _notesCache = new Map(); // key: `${file}#${trackId}` → /api/notes response
// key: primaryTrackId → Set<secondaryTrackId> — persists across primary-track switches
const _activeSecondaryTracks = new Map();

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
const btnSound      = $('#btn-sound');
const btnFingering  = $('#btn-fingering');
const btnExportPdf  = $('#btn-export-pdf');
const pdfEngineSelect = $('#pdf-engine-select');
const pdfExportStatus = $('#pdf-export-status');
const btnBackFiles  = $('#btn-back-files');
const btnBackViewer  = $('#btn-back-viewer');
const trackSwitcher  = $('#track-switcher');
const selSpeed       = $('#speed-select');
const bpmInput       = $('#bpm-input');
const selMode        = $('#mode-select');
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

// Header
const btnLegend     = $('#btn-legend');
const legendOverlay = $('#legend-overlay');
const legendClose   = $('#legend-close');

// ── Page routing ────────────────────────────────────────────────────

function showPage(page) {
  fileSelector.style.display  = page === 'files'  ? '' : 'none';
  trackSelector.style.display = page === 'tracks' ? '' : 'none';
  tabViewer.style.display     = page === 'viewer' ? '' : 'none';
  toolbar.style.display       = page === 'viewer' ? '' : 'none';
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
  _notesCache.clear(); // bust cache on new file
  _activeSecondaryTracks.clear(); // reset preferences on new file
  showPage('tracks');
  trackGrid.innerHTML = '<p style="color:#aaa;">Loading tracks…</p>';

  try {
    const tracks = await fetchTracks(filename);
    currentTracks = tracks;
    if (!tracks.length) {
      trackGrid.innerHTML = '<p style="color:#aaa;">No guitar tracks found.</p>';
      return;
    }
    trackGrid.innerHTML = '';
    for (const t of tracks) {
      const card = document.createElement('div');
      card.className = 'track-card';
      card.innerHTML = `
        <div class="track-icon">🎵</div>
        <div class="track-name">${sanitize(t.name)}</div>
        <div class="track-id">Track ${t.id}</div>
      `;
      card.addEventListener('click', () => selectTrack(t.id, t.name));
      trackGrid.appendChild(card);
    }
  } catch (err) {
    trackGrid.innerHTML = `<p style="color:#ff5555;">Error: ${sanitize(err.message)}</p>`;
  }
}

// ── Tab viewer ──────────────────────────────────────────────────────

function populateTrackSwitcher(trackId) {
  if (!trackSwitcher) return;
  trackSwitcher.innerHTML = '';
  if (currentTracks.length <= 1) {
    trackSwitcher.style.display = 'none';
    return;
  }
  trackSwitcher.style.display = '';
  for (const t of currentTracks) {
    const opt = document.createElement('option');
    opt.value = t.id;
    opt.textContent = t.name || `Track ${t.id}`;
    if (t.id === trackId) opt.selected = true;
    trackSwitcher.appendChild(opt);
  }
}

async function selectTrack(trackId, trackName) {
  currentTrackId = trackId;
  showPage('viewer');
  populateTrackSwitcher(trackId);

  songTitle.textContent = currentFile.replace(/\.[^.]+$/, '');
  songArtist.textContent = trackName || `Track ${trackId}`;
  if (trackBadge) trackBadge.textContent = trackName || `Track ${trackId}`;
  if (metaMode) metaMode.textContent = (selMode?.value || 'reference').toUpperCase();

  tabCanvas.width = 100;
  tabCanvas.height = 100;
  const ctx = tabCanvas.getContext('2d');
  ctx.fillStyle = '#aaa';
  ctx.font = '14px Arial';
  ctx.textAlign = 'center';
  ctx.fillText('Computing fingerings…', 50, 50);

  try {
    const mode = selMode?.value || 'reference';
    const representationMode = getSelectedRepresentationMode();
    const data = await fetchSolve(currentFile, trackId, mode, representationMode);
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
    const mode = selMode?.value || 'reference';
    const engine = pdfEngineSelect?.value || 'core';
    const representationMode = getSelectedRepresentationMode();
    const {
      blob,
      filename,
      engine: usedEngine,
      conformanceIssues,
      conformanceReport,
    } = await fetchExportPdf(
      currentFile,
      currentTrackId,
      mode,
      engine,
      representationMode,
    );
    _downloadBlob(blob, filename);
    if (usedEngine === 'core') {
      if (conformanceIssues > 0) {
        _setPdfExportStatus(`Core: ${conformanceIssues} issue(s)`, 'warn');
      } else {
        _setPdfExportStatus('Core: conformance OK', 'ok');
      }
    } else {
      if (conformanceReport?.shadow_failed) {
        _setPdfExportStatus('Legacy: shadow core unavailable', 'warn');
      } else if (conformanceIssues > 0) {
        _setPdfExportStatus(`Legacy: shadow core ${conformanceIssues} issue(s)`, 'warn');
      } else {
        _setPdfExportStatus('Legacy export complete', 'ok');
      }
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

function _representationModeLabel(mode) {
  switch (mode) {
    case 'standard':
      return 'STANDARD';
    case 'standard_tablature':
      return 'STANDARD + TAB';
    case 'tablature':
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
    if (showCore) _applyResponsiveCoreSvg();
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
  if (btnLoopA)    btnLoopA.classList.remove('active');
  if (btnLoopB)    btnLoopB.classList.remove('active');

  // Update title/artist from API response
  if (data.title) songTitle.textContent = data.title;
  if (data.artist) songArtist.textContent = data.artist;
  if (metaTempo) metaTempo.textContent = `♩ = ${Math.round(data.tempo || 120)}`;
  if (bpmInput) bpmInput.value = Math.round(data.tempo || 120);
  if (metaMode) metaMode.textContent = (selMode?.value || 'reference').toUpperCase();

  renderer = new TabRenderer(tabCanvas, data);
  renderer.render();
  // Reset sound button state when loading a new track
  soundOn = false;
  if (btnSound) {
    btnSound.classList.remove('active');
    btnSound.textContent = '\uD83D\uDD07';
    btnSound.title = 'Sound OFF — click to enable';
  }
  if (btnFingering) {
    btnFingering.classList.toggle('active', renderer.showFingering);
  }
  applyRepresentationModeView(data);

  // Populate chord strip from chord diagrams
  const strip = $('#chord-strip');
  if (strip) {
    if (data.chord_diagrams?.length) {
      strip.innerHTML = '';
      for (const cd of data.chord_diagrams) {
        const el = document.createElement('div');
        el.className = 'chord-diagram-item';
        el.setAttribute('data-chord', cd.name);
        el.innerHTML = chordDiagramSVG(cd);
        strip.appendChild(el);
      }
      strip.style.display = '';
    } else {
      strip.style.display = 'none';
    }
  }

  // Playback engine
  playback = new PlaybackEngine(renderer, {
    tempo: data.tempo || 120,
    beatsPerMeasure: data.beats_per_measure || 4,
  });
  // Select the right soundfont instrument from the track name
  playback.setInstrument(data.track_name || '');
  playback.onMeasureChange = (_m) => {};
  playback.onStop = () => { updatePlayButton(false); stopCursorLoop(); };

  // Wire position scrubber
  playback.onPositionChange = (frac) => {
    const pb = $('#position-bar input');
    if (pb) pb.value = Math.round(frac * 1000);
  };

  // Canvas click: chord label → scroll+highlight, else measure jump
  tabCanvas.onclick = (e) => {
    const rect = tabCanvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    const y = e.clientY - rect.top;
    // Check chord name click first
    const chordName = renderer.getChordNameAtPoint(x, y);
    if (chordName) {
      const strip = $('#chord-strip');
      if (strip) {
        const el = strip.querySelector(`[data-chord="${CSS.escape(chordName)}"]`);
        if (el) {
          el.scrollIntoView({ behavior: 'smooth', block: 'center' });
          el.classList.add('chord-highlight');
          setTimeout(() => el.classList.remove('chord-highlight'), 1500);
        }
      }
      return;
    }
    // Measure jump
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
  const _svgMode = data.representation_mode || getSelectedRepresentationMode();
  if (_svgMode !== 'tablature' && data.measure_regions?.length && coreSvgView) {
    const _svgDriver = new SvgCursorDriver(coreSvgView, data);
    _svgDriver.init();
    playback.onMeasureChange = (m) => {
      _svgDriver.highlight(m, playback.loopStart, playback.loopEnd);
    };
    coreSvgView.onclick = (e) => {
      const m = _svgDriver.measureAtClick(e);
      if (m >= 0) playback.goToMeasure(m);
    };
  } else {
    if (coreSvgView) coreSvgView.onclick = null;
  }

  // SF2 loading indicator — update sound button while SpessaSynth is fetching
  playback.onSynthStatusChange = (status) => {
    if (!btnSound) return;
    const instName = PlaybackEngine._inferInstrument(data.track_name || '');
    if (status === 'loading') {
      btnSound.textContent = '⏳';
      btnSound.title = `Chargement de l'instrument (${instName})…`;
    } else if (status === 'ready') {
      btnSound.textContent = soundOn ? '🔊' : '🔇';
      btnSound.title = soundOn ? `Son ON (${instName}) — cliquer pour couper` : 'Son OFF — cliquer pour activer';
    } else { // 'error' — oscillator fallback
      btnSound.textContent = soundOn ? '🔊' : '🔇';
      btnSound.title = soundOn ? 'Son ON (oscillateur) — soundfont indisponible' : 'Son OFF — cliquer pour activer';
    }
  };

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
  _restoreSecondaryTracks(currentTrackId); // re-enable previously active secondary tracks
  updatePlayButton(false);
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
  _multiTrackBar.innerHTML = '<span class="mt-label">🏛 Pistes audio :</span>';
  for (const t of currentTracks) {
    const isPrimary = t.id === primaryTrackId;
    const isActive  = !isPrimary && playback &&
      playback._secondaryChannels.some(c => c.trackId === t.id);
    const btn = document.createElement('button');
    btn.className = 'mt-track-btn' +
      (isPrimary ? ' mt-primary' : '') +
      (isActive  ? ' mt-active'  : '');
    btn.textContent = (isPrimary ? '▶ ' : isActive ? '🔈 ' : '🔇 ') +
      sanitize(t.name || `Piste ${t.id}`);
    btn.dataset.trackId = t.id;
    if (!isPrimary) {
      btn.addEventListener('click', () => _toggleSecondaryTrack(t.id, t.name || '', btn));
    }
    _multiTrackBar.appendChild(btn);
  }
}

async function _toggleSecondaryTrack(trackId, trackName, btn) {
  if (!playback) return;
  // Already active → remove
  const existing = playback._secondaryChannels.findIndex(c => c.trackId === trackId);
  if (existing >= 0) {
    playback.removeSecondaryChannel(trackId);
    // Forget preference
    _activeSecondaryTracks.get(currentTrackId)?.delete(trackId);
    btn.className = 'mt-track-btn';
    btn.textContent = '🔇 ' + sanitize(trackName);
    return;
  }
  // Not active → fetch notes (cached) and add
  btn.textContent = '⏳ ' + sanitize(trackName);
  btn.disabled = true;
  try {
    const cacheKey = `${currentFile}#${trackId}`;
    let notesData = _notesCache.get(cacheKey);
    if (!notesData) {
      notesData = await fetchNotes(currentFile, trackId, selMode?.value || 'reference');
      _notesCache.set(cacheKey, notesData);
    }
    playback.addSecondaryChannel(
      trackId, trackName, notesData.results, notesData.beats_per_measure
    );
    // Save preference
    if (!_activeSecondaryTracks.has(currentTrackId)) _activeSecondaryTracks.set(currentTrackId, new Set());
    _activeSecondaryTracks.get(currentTrackId).add(trackId);
    btn.className = 'mt-track-btn mt-active';
    btn.textContent = '🔈 ' + sanitize(trackName);
  } catch (err) {
    console.error('[FretWise] secondary track load failed:', err);
    btn.textContent = '❌ ' + sanitize(trackName);
    setTimeout(() => {
      btn.textContent = '🔇 ' + sanitize(trackName);
    }, 2000);
  } finally {
    btn.disabled = false;
  }
}

/** Re-activate secondary tracks that were remembered for this primary track. */
async function _restoreSecondaryTracks(primaryTrackId) {
  const active = _activeSecondaryTracks.get(primaryTrackId);
  if (!active || active.size === 0) return;
  for (const trackId of active) {
    const t = currentTracks.find(x => x.id === trackId);
    if (!t) continue;
    const btn = _multiTrackBar?.querySelector(`[data-track-id="${trackId}"]`);
    if (btn) await _toggleSecondaryTrack(trackId, t.name || '', btn);
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
  });
}

if (btnLoopClear) {
  btnLoopClear.addEventListener('click', () => {
    if (!playback) return;
    playback.clearLoop();
    loopASet = false;
    if (btnLoopA) { btnLoopA.classList.remove('active'); btnLoopA.title = 'Set loop start (A)'; }
    if (btnLoopB) { btnLoopB.classList.remove('active'); btnLoopB.title = 'Set loop end (B)'; }
  });
}

if (btnFingering) {
  btnFingering.addEventListener('click', () => {
    if (!renderer) return;
    renderer.showFingering = !renderer.showFingering;
    btnFingering.classList.toggle('active', renderer.showFingering);
    renderer.render();
  });
}

if (btnSound) {
  btnSound.addEventListener('click', () => {
    if (!playback) return;
    if (soundOn) {
      playback.disableAudio();
      soundOn = false;
      btnSound.classList.remove('active');
      btnSound.textContent = '🔇';
      btnSound.title = 'Sound OFF — click to enable';
    } else {
      playback.enableAudio();
      soundOn = true;
      btnSound.classList.add('active');
      // Don't overwrite text here — onSynthStatusChange will set it to ⏳ then 🔊/🔇
      // Only set it now if synth is already ready (or not loading)
      if (!playback._synthLoading) {
        btnSound.textContent = '🔊';
        btnSound.title = playback._synth
          ? 'Sound ON (SF2) — click to mute'
          : 'Sound ON — click to mute';
      }
    }
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

if (btnBackFiles) {
  btnBackFiles.addEventListener('click', () => {
    loadFiles();
  });
}

// ── Legend overlay ───────────────────────────────────────────────────
let _legendBuilt = false;

if (btnLegend) {
  btnLegend.addEventListener('click', () => {
    legendOverlay.style.display = '';
    if (legendContent && !_legendBuilt) {
      buildLegendHTML(legendContent);
      _legendBuilt = true;
    }
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

// ── Track switcher ──────────────────────────────────────────────────

if (trackSwitcher) {
  trackSwitcher.addEventListener('change', () => {
    const id = parseInt(trackSwitcher.value, 10);
    const t = currentTracks.find(x => x.id === id);
    if (t && id !== currentTrackId) {
      selectTrack(t.id, t.name);
    }
  });
}

// ── Mode change re-solve ────────────────────────────────────────────

if (selMode) {
  selMode.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

if (selRepresentationMode) {
  selRepresentationMode.addEventListener('change', () => {
    if (currentFile && currentTrackId != null) {
      selectTrack(currentTrackId, songArtist.textContent);
    }
  });
}

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
 * Layout: chord name → x/o markers → nut/grid → fret dots with finger numbers.
 */
function chordDiagramSVG(cd) {
  const nStr   = cd.string_count || 6;
  const nFret  = 5;       // fret rows shown
  const S      = 13;      // px between adjacent strings
  const F      = 13;      // px between adjacent frets
  const ML     = 8;       // left margin
  const dotR   = 5;       // finger dot radius
  const boxW   = (nStr - 1) * S;
  const boxH   = nFret * F;
  const gridY  = 30;      // y where the string/fret grid starts
  const hasPos = cd.base_fret > 1;
  const svgW   = ML + boxW + ML + (hasPos ? 22 : 0);
  const svgH   = gridY + boxH + 8;

  // x of string i: i=0 → high e (right), i=nStr-1 → low E (left)
  const strX = i => ML + (nStr - 1 - i) * S;

  let p = `<svg width="${svgW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg"
    style="display:block">`;

  // ── Chord name ──
  p += `<text x="${ML + boxW / 2}" y="13"
    font-family="Arial,sans-serif" font-weight="bold" font-size="13"
    text-anchor="middle" fill="#222">${sanitize(cd.name)}</text>`;

  // ── Nut bar (open position) or fret label (position chord) ──
  if (!hasPos) {
    p += `<rect x="${ML}" y="${gridY - 3}" width="${boxW}" height="3.5"
      fill="#222" rx="0.5"/>`;
  } else {
    p += `<text x="${ML + boxW + 5}" y="${gridY + F / 2 + 4}"
      font-family="Arial,sans-serif" font-size="9" fill="#555">${_toRoman(cd.base_fret)}fr</text>`;
  }

  // ── Grid: vertical string lines ──
  for (let i = 0; i < nStr; i++) {
    const x = strX(i);
    p += `<line x1="${x}" y1="${gridY}" x2="${x}" y2="${gridY + boxH}"
      stroke="#bbb" stroke-width="0.8"/>`;
  }

  // ── Grid: horizontal fret lines ──
  for (let f = 0; f <= nFret; f++) {
    const y = gridY + f * F;
    p += `<line x1="${ML}" y1="${y}" x2="${ML + boxW}" y2="${y}"
      stroke="#bbb" stroke-width="0.8"/>`;
  }

  // ── Muted (x) and open (o) markers above grid ──
  for (let i = 0; i < nStr; i++) {
    const x = strX(i);
    const fv = cd.frets[i];
    if (fv === -1) {
      // × muted
      p += `<text x="${x}" y="26" font-family="Arial,sans-serif"
        font-size="9" font-weight="bold" text-anchor="middle" fill="#444">x</text>`;
    } else if (fv === 0) {
      // ○ open string
      p += `<circle cx="${x}" cy="21" r="3.5"
        fill="none" stroke="#444" stroke-width="1.2"/>`;
    }
  }

  // ── Barre detection: ≥2 strings at the minimum fretted fret ──
  const frettedNotes = cd.frets
    .map((fv, i) => ({ i, fv }))
    .filter(n => n.fv > 0);
  const barreSet = new Set();
  if (frettedNotes.length >= 2) {
    const minFret  = Math.min(...frettedNotes.map(n => n.fv));
    const barreSt  = frettedNotes.filter(n => n.fv === minFret);
    if (barreSt.length >= 2) {
      const row = minFret - Math.max(cd.base_fret, 1);
      if (row >= 0 && row < nFret) {
        const cy  = gridY + row * F + F / 2;
        const xs  = barreSt.map(n => strX(n.i));
        const bx0 = Math.min(...xs), bx1 = Math.max(...xs);
        p += `<rect x="${bx0 - dotR}" y="${cy - dotR}"
          width="${bx1 - bx0 + 2 * dotR}" height="${2 * dotR}"
          rx="${dotR}" fill="#222"/>`;
        const bf = cd.fingers?.[barreSt[0].i] || 0;
        if (bf) p += `<text x="${(bx0 + bx1) / 2}" y="${cy + dotR * 0.42}"
          font-family="Arial,sans-serif" font-size="7" font-weight="bold"
          text-anchor="middle" fill="white">${bf}</text>`;
        for (const n of barreSt) barreSet.add(n.i);
      }
    }
  }

  // ── Individual finger dots ──
  for (let i = 0; i < nStr; i++) {
    const fv = cd.frets[i];
    if (fv <= 0 || barreSet.has(i)) continue;
    const row = fv - Math.max(cd.base_fret, 1);
    if (row < 0 || row >= nFret) continue;
    const cx = strX(i);
    const cy = gridY + row * F + F / 2;
    p += `<circle cx="${cx}" cy="${cy}" r="${dotR}" fill="#222"/>`;
    const finger = cd.fingers?.[i] || 0;
    if (finger) {
      p += `<text x="${cx}" y="${cy + dotR * 0.42}"
        font-family="Arial,sans-serif" font-size="7" font-weight="bold"
        text-anchor="middle" fill="white">${finger}</text>`;
    }
  }

  p += '</svg>';
  return p;
}

// ── Red cursor overlay ──────────────────────────────────────────────

let _cursorRaf = null;
let _autoScrollTarget = null;

function startCursorLoop() {
  if (_cursorRaf) cancelAnimationFrame(_cursorRaf);
  function loop() {
    _drawCursorOverlay();
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
