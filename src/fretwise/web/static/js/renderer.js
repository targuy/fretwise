/**
 * renderer.js — Songsterr-style Canvas tab renderer
 *
 * Draws horizontal-scrolling tablature with:
 *  - 6-string tab staff with fret numbers
 *  - Rhythm stems, beams, flags below the tab
 *  - Chord names above
 *  - Section markers, tempo, time signature
 *  - All notation symbols (H/P arcs, bends, slides, vibrato, let-ring,
 *    palm mute, harmonics, tapping, accents, dynamics, muted notes, etc.)
 *  - Songsterr-style colors and proportions
 */

// ── Zoom factor (change to rescale all notation proportionally) ──────
const ZOOM = 1.25;

// ── Layout constants (px at 1× DPR) ────────────────────────────────
const MARGIN_L = Math.round(60 * ZOOM);   // left margin (TAB label + string names)
const MARGIN_R = Math.round(20 * ZOOM);
const MARGIN_T = Math.round(12 * ZOOM);
const STRING_SPACING = Math.round(16 * ZOOM);  // distance between strings
const NUM_STRINGS = 6;
const STRINGS_H = (NUM_STRINGS - 1) * STRING_SPACING;
const STRING_NAMES = ['e', 'B', 'G', 'D', 'A', 'E'];

// System vertical layout
const ABOVE_STRINGS = Math.round(80 * ZOOM);  // space above string 1
const BELOW_STRINGS = Math.round(70 * ZOOM);  // space below string 6
const SYSTEM_H = ABOVE_STRINGS + STRINGS_H + BELOW_STRINGS;
const INTER_SYSTEM = Math.round(16 * ZOOM);

// Note rendering
const NOTE_RX = Math.round(8 * ZOOM);    // oval x radius
const NOTE_RY = 5.5 * ZOOM;              // oval y radius
const COL_STEP = Math.round(30 * ZOOM);  // fixed px between consecutive note columns
const LEFT_PAD = Math.round(28 * ZOOM);  // left margin in measure (room for measure number)
const RIGHT_PAD = Math.round(18 * ZOOM); // right margin in measure

// Stem / rhythm (below tab)
const STEM_GAP = Math.round(20 * ZOOM);  // room for PM/let ring annotation band
const STEM_H = Math.round(16 * ZOOM);
const BEAM_H = Math.round(3 * ZOOM);
const BEAM_GAP_Y = Math.round(4 * ZOOM);

// Colors (Songsterr palette)
const COL_STRING     = '#c4bfb5';  // soft warm grey on cream bg
const COL_STRING_LW  = 0.9;
const COL_TEXT        = '#1a1a1a';
const COL_FRET        = '#1a1a1a';
const COL_GREY        = '#888880';
const COL_GREEN       = '#4caf50';
const COL_CHORD       = '#1a1a1a';
const COL_SECTION     = '#2c2c2c';
const COL_BEND        = '#c0392b';
const COL_VIBRATO     = '#2a8a2a';
const COL_LET_RING    = '#4466bb';
const COL_PM          = '#666655';
const COL_HP_ARC      = '#666655';
const COL_TAPPING     = '#1a45aa';
const COL_FINGER      = '#c0392b';
const COL_HARMONIC    = '#8a6200';
const COL_SLIDE       = '#555548';
const COL_ACCENT      = '#c0392b';
const COL_MUTED       = '#1a1a1a';
const COL_EXPORT_WARN = '#d32f2f';
const COL_EXPORT_WARN_FILL = '#ffe3e3';
const COL_REVIEW_IMPOSSIBLE = '#d32f2f';
const COL_REVIEW_IMPOSSIBLE_FILL = '#ffd6d6';
const COL_REVIEW_SUSPECT = '#f59e0b';
const COL_REVIEW_SUSPECT_FILL = '#fff1c7';
const COL_MEASURE_NUM = '#bbb8b0';  // subtle on cream
const COL_CURSOR      = 'rgba(76, 175, 80, 0.10)';
const COL_CURSOR_LINE = '#4caf50';

// Fonts
const MONO            = '"JetBrains Mono", monospace';
const SANS            = 'Inter, system-ui, sans-serif';
const SERIF           = '"Fraunces", Georgia, serif';
const _z = (n) => Math.round(n * ZOOM);
const FONT_FRET       = `bold ${_z(11)}px ${MONO}`;
const FONT_FRET_SM    = `bold ${_z(10)}px ${MONO}`;
const FONT_STRING     = `500 ${_z(10)}px ${SANS}`;
const FONT_TAB        = `bold ${_z(13)}px ${MONO}`;
const FONT_CHORD      = `600 ${_z(12)}px ${SANS}`;
const FONT_SECTION    = `italic 600 ${_z(11)}px ${SERIF}`;
const FONT_TEMPO      = `500 ${_z(10)}px ${MONO}`;
const FONT_MNUM       = `400 ${_z(9)}px ${SANS}`;
const FONT_FINGER     = `bold ${_z(8)}px ${MONO}`;
const FONT_SYMBOL     = `500 ${_z(10)}px ${SANS}`;
const FONT_SYMBOL_SM  = `400 ${_z(9)}px ${SANS}`;
const FONT_DYNAMIC    = `italic bold ${_z(11)}px ${SERIF}`;
const FONT_LEGEND_H   = `600 ${_z(14)}px ${SANS}`;
const FONT_LEGEND     = `400 ${_z(12)}px ${SANS}`;

/**
 * @typedef {Object} Note  – from API /api/solve
 * @property {number} note_id
 * @property {number} pitch
 * @property {number} onset
 * @property {number} duration
 * @property {number} tempo
 * @property {string} articulation
 * @property {string} dynamic
 * @property {number} string        1-6
 * @property {number} fret          0-24
 * @property {string} finger
 * @property {number} hand_position
 * @property {number} cost
 * @property {boolean} let_ring
 * @property {number|null} bend_value
 * @property {string|null} bend_type
 * @property {string|null} slide_type
 * @property {boolean} vibrato_wide
 * @property {string|null} harmonic_type
 * @property {number|null} harmonic_fret
 * @property {number|null} harmonic_resultant_pitch
 * @property {boolean} muted
 * @property {boolean} palm_muted
 * @property {boolean} tapping
 * @property {boolean} accent
 * @property {boolean} accent_strong
 * @property {boolean} tremolo_picking
 * @property {boolean} ghost
 * @property {boolean} staccato
 * @property {string|null} strum_direction
 * @property {boolean} slap
 * @property {boolean} pop
 * @property {boolean} rasgueado
 * @property {boolean} golpe
 * @property {number|null} tuplet_actual
 * @property {number|null} tuplet_normal
 * @property {string} gp_fingering_export_status
 * @property {string} review_severity
 */

// ── Public interface ────────────────────────────────────────────────

export class TabRenderer {
  /**
   * @param {HTMLCanvasElement} canvas
   * @param {Object} data — response from /api/solve
   */
  constructor(canvas, data) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.data = data;
    this.results = data.results || [];
    this.bpm = data.beats_per_measure || 4;
    this.measureBeats = Array.isArray(data.measure_beats)
      ? data.measure_beats.map(v => Number(v))
      : null;
    this.tempo = data.tempo || 120;
    this.sectionMarkers = data.section_markers || {};
    this.chordDiagrams = data.chord_diagrams || [];
    this.chordMarkers = data.chord_markers || {};  // onset_str → chord name from file
    this.dpr = window.devicePixelRatio || 1;

    // Finger colors — read from CSS custom properties so themes apply
    const _cs = getComputedStyle(document.documentElement);
    const _cv = (v, fallback) => { const t = _cs.getPropertyValue(v).trim(); return t || fallback; };
    this._fingerColors = {
      index:  _cv('--f1', '#e07060'),
      middle: _cv('--f2', '#60c060'),
      ring:   _cv('--f3', '#6090e0'),
      pinky:  _cv('--f4', '#c060c0'),
    };
    this._bgScore = _cv('--bg-score', '#faf8f2');

    // Derived from result grouping
    this.measures = [];
    this.systems = [];
    this.cursorMeasure = 0;

    // Loop range (measure indices, -1 = not set)
    this.loopStart = -1;
    this.loopEnd = -1;

    // Chord label positions for click detection: [{x,y,name}]
    this.chordLabelPositions = [];

    // Note columns for cursor overlay: [{onset, x, yTop, yBottom}]
    this.noteColumns = [];

    // Dynamic tracking: only show dynamic marking when it changes
    this._lastDynamic = '';

    // Fingering display toggle
    this.showFingering = true;

    // Playback state
    this.cursorBeat = 0;
    this.isPlaying = false;

    this._groupMeasures();
    this._buildSystems();
  }

  /** Compute total canvas height needed */
  get totalHeight() {
    return MARGIN_T + this.systems.length * (SYSTEM_H + INTER_SYSTEM) + 20;
  }

  /** Compute width per system */
  get systemWidth() {
    return Math.max(800, window.innerWidth - 40);
  }

  /** Full render */
  render() {
    const w = this.systemWidth;
    const h = this.totalHeight;

    this.canvas.style.width = w + 'px';
    this.canvas.style.height = h + 'px';
    this.canvas.width = Math.round(w * this.dpr);
    this.canvas.height = Math.round(h * this.dpr);

    const ctx = this.ctx;
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    this.chordLabelPositions = [];  // reset before re-render
    this.noteColumns = [];           // reset for cursor overlay
    this._lastDynamic = '';          // reset dynamic tracking

    for (let si = 0; si < this.systems.length; si++) {
      const sys = this.systems[si];
      const sysY = MARGIN_T + si * (SYSTEM_H + INTER_SYSTEM);
      this._drawSystem(ctx, sys, sysY, w);
    }
  }

  /** Get measure index at a canvas Y/X click */
  getMeasureAtPoint(x, y) {
    for (let si = 0; si < this.systems.length; si++) {
      const sysY = MARGIN_T + si * (SYSTEM_H + INTER_SYSTEM);
      if (y >= sysY && y < sysY + SYSTEM_H) {
        const sys = this.systems[si];
        let mx = MARGIN_L;
        for (let mi = 0; mi < sys.measures.length; mi++) {
          const mw = sys.widths[mi];
          if (x >= mx && x < mx + mw) {
            return sys.startMeasure + mi;
          }
          mx += mw;
        }
      }
    }
    return -1;
  }

  /** Return chord name if click (x,y) is near a chord label, else null */
  getChordNameAtPoint(x, y) {
    for (const lbl of this.chordLabelPositions) {
      if (Math.abs(x - lbl.x) < 50 && Math.abs(y - lbl.y) < 14) {
        return lbl.name;
      }
    }
    return null;
  }

  /**
   * Return the note column whose onset is <= the given onset (last played).
   * Used by the cursor overlay in main.js.
   * @param {number} onset
   * @returns {{onset:number,x:number,yTop:number,yBottom:number}|null}
   */
  getCursorX(onset) {
    let best = null;
    for (const col of this.noteColumns) {
      if (col.onset <= onset + 0.001) {
        if (!best || col.onset > best.onset) best = col;
      }
    }
    return best;
  }

  // ── Grouping ──────────────────────────────────────────────────────

  _groupMeasures() {
    if (!this.results.length) return;
    // Group by measure_index (1-based, correctly assigned by the parser even for variable meter)
    const byMeasure = new Map();
    for (const n of this.results) {
      const mi = n.measure_index ?? 1;
      if (!byMeasure.has(mi)) byMeasure.set(mi, []);
      byMeasure.get(mi).push(n);
    }
    const keys = [...byMeasure.keys()].sort((a, b) => a - b);
    const minM = keys[0], maxM = keys[keys.length - 1];
    const measures = [];
    const measureNumbers = []; // parallel array: actual 1-based measure number for each slot
    for (let m = minM; m <= maxM; m++) {
      measures.push(byMeasure.get(m) ?? []);
      measureNumbers.push(m);
    }
    this.measures = measures;
    this.measureNumbers = measureNumbers;
  }

  _buildSystems() {
    const measures = this.measures;
    if (!measures.length) return;
    const availW = this.systemWidth - MARGIN_L - MARGIN_R;

    // Measure width: margins + (nCols-1) inter-note gaps, so last note sits at mW-RIGHT_PAD
    const measureWidth = (notes, measureNum) => {
      const nCols = notes.length ? new Set(notes.map(n => n.onset.toFixed(6))).size : 1;
      if (!notes.length) return LEFT_PAD + COL_STEP + RIGHT_PAD;

      const measureStart = this._measureStartBeat(measureNum);
      const measureBeats = this._measureBeatCount(measureNum);
      const onsets = [...new Set(notes.map(n => Number(n.onset)))]
        .filter(v => Number.isFinite(v))
        .sort((a, b) => a - b);
      let minGap = Infinity;
      for (let j = 1; j < onsets.length; j++) {
        const gap = onsets[j] - onsets[j - 1];
        if (gap > 0.001) minGap = Math.min(minGap, gap);
      }
      const firstGap = onsets.length ? onsets[0] - measureStart : Infinity;
      if (firstGap > 0.001) minGap = Math.min(minGap, firstGap);
      const lastGap = onsets.length
        ? (measureStart + measureBeats) - onsets[onsets.length - 1]
        : Infinity;
      if (lastGap > 0.001) minGap = Math.min(minGap, lastGap);

      const indexedIntervals = Math.max(nCols - 1, 1);
      const timedIntervals = Number.isFinite(minGap)
        ? Math.ceil(measureBeats / Math.max(minGap, 0.001))
        : indexedIntervals;
      return LEFT_PAD + Math.max(indexedIntervals, timedIntervals) * COL_STEP + RIGHT_PAD;
    };

    const systems = [];
    let cur = [];
    let curW = 0;
    for (let i = 0; i < measures.length; i++) {
      const w = measureWidth(measures[i], this.measureNumbers[i]);
      if (cur.length >= 1 && curW + w > availW) {
        systems.push(cur);
        cur = [];
        curW = 0;
      }
      cur.push({ idx: i, w });
      curW += w;
    }
    if (cur.length) systems.push(cur);

    this.systems = systems.map(s => ({
      measures: s.map(c => measures[c.idx]),
      widths: s.map(c => c.w),
      startMeasure: s[0].idx,                          // 0-based index for cursor tracking
      firstMeasureNum: this.measureNumbers[s[0].idx],  // actual 1-based number for display
    }));
  }

  // ── System drawing ────────────────────────────────────────────────

  _drawSystem(ctx, sys, sysY, canvasW) {
    const strY = (si) => sysY + ABOVE_STRINGS + si * STRING_SPACING;
    const x0 = MARGIN_L;
    const xEnd = x0 + sys.widths.reduce((a, b) => a + b, 0);

    // ── TAB label + string names
    ctx.font = FONT_TAB;
    ctx.fillStyle = COL_GREY;   // subtle, not full black
    ctx.textAlign = 'center';
    const tabX = 20;
    ctx.fillText('T', tabX, strY(1) + 1);
    ctx.fillText('A', tabX, strY(2) + 1);
    ctx.fillText('B', tabX, strY(3) + 1);

    ctx.font = FONT_STRING;
    ctx.fillStyle = COL_GREY;
    ctx.textAlign = 'right';
    for (let si = 0; si < NUM_STRINGS; si++) {
      ctx.fillText(STRING_NAMES[si], x0 - 6, strY(si) + 4);
    }

    // ── String lines
    ctx.strokeStyle = COL_STRING;
    ctx.lineWidth = COL_STRING_LW;
    for (let si = 0; si < NUM_STRINGS; si++) {
      const y = strY(si);
      ctx.beginPath();
      ctx.moveTo(x0, y);
      ctx.lineTo(xEnd, y);
      ctx.stroke();
    }

    // ── Tempo (first system)
    if (sys.startMeasure === 0) {
      ctx.font = FONT_TEMPO;
      ctx.fillStyle = COL_GREY;
      ctx.textAlign = 'left';
      const tsBpm = this.bpm;
      ctx.fillText(`${tsBpm}/4  ·  ♩ = ${Math.round(this.tempo)}`, x0, sysY + 10);
    }

    // ── Draw measures
    let mX = x0;
    for (let mi = 0; mi < sys.measures.length; mi++) {
      const mNotes = sys.measures[mi];
      const mW = sys.widths[mi];
      const absMeasure = sys.startMeasure + mi;          // 0-based index for cursor
      const measureNum = sys.firstMeasureNum + mi;        // actual 1-based measure number

      // Section marker
      const sectionLabel = this.sectionMarkers[String(measureNum)];
      if (sectionLabel) {
        ctx.font = FONT_SECTION;
        ctx.fillStyle = COL_SECTION;
        ctx.textAlign = 'left';
        ctx.fillText(sectionLabel, mX + 4, sysY + 22);
      }

      // Chord name (first note's onset → check for chord recognition)
      this._drawChordName(ctx, mNotes, mX, mW, sysY, measureNum);

      // Measure number
      ctx.font = FONT_MNUM;
      ctx.fillStyle = COL_MEASURE_NUM;
      ctx.textAlign = 'left';
      ctx.fillText(String(measureNum), mX + 2, sysY + ABOVE_STRINGS - 6);

      // Barline at start
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = mi === 0 ? 1.5 : 0.7;
      ctx.beginPath();
      ctx.moveTo(mX, strY(0) - 1);
      ctx.lineTo(mX, strY(NUM_STRINGS - 1) + 1);
      ctx.stroke();

      // Cursor highlight
      if (absMeasure === this.cursorMeasure) {
        ctx.fillStyle = COL_CURSOR;
        ctx.fillRect(mX, strY(0) - 2, mW, STRINGS_H + 4);
        // Draw left border line for cursor
        ctx.strokeStyle = COL_CURSOR_LINE;
        ctx.lineWidth = 1.5;
        ctx.beginPath();
        ctx.moveTo(mX + 1, strY(0) - 2);
        ctx.lineTo(mX + 1, strY(NUM_STRINGS - 1) + 2);
        ctx.stroke();
      }

      // Loop range highlight
      if (this.loopStart >= 0 && this.loopEnd >= this.loopStart) {
        if (absMeasure >= this.loopStart && absMeasure <= this.loopEnd) {
          ctx.fillStyle = 'rgba(255, 152, 0, 0.08)';
          ctx.fillRect(mX, strY(0) - 2, mW, STRINGS_H + 4);
        }
        // A marker
        if (absMeasure === this.loopStart) {
          ctx.fillStyle = '#ff9800';
          ctx.font = 'bold 8px Arial';
          ctx.textAlign = 'left';
          ctx.fillText('A', mX + 2, strY(0) - 4);
        }
        // B marker
        if (absMeasure === this.loopEnd) {
          ctx.fillStyle = '#ff9800';
          ctx.font = 'bold 8px Arial';
          ctx.textAlign = 'right';
          ctx.fillText('B', mX + mW - 2, strY(0) - 4);
        }
      }

      // Draw notes
      this._drawMeasureNotes(ctx, mNotes, mX, mW, sysY, measureNum);

      mX += mW;
    }

    // Final barline
    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(xEnd, strY(0) - 1);
    ctx.lineTo(xEnd, strY(NUM_STRINGS - 1) + 1);
    ctx.stroke();
    ctx.lineWidth = 0.7;
    ctx.beginPath();
    ctx.moveTo(xEnd - 3, strY(0) - 1);
    ctx.lineTo(xEnd - 3, strY(NUM_STRINGS - 1) + 1);
    ctx.stroke();
  }

  // ── Notes in a measure ────────────────────────────────────────────

  _measureBeatCount(measureNum) {
    const idx = Math.max(0, Math.trunc(Number(measureNum || 1)) - 1);
    const beats = this.measureBeats?.[idx];
    if (Number.isFinite(beats) && beats > 0) return beats;
    const fallback = Number(this.bpm);
    return Number.isFinite(fallback) && fallback > 0 ? fallback : 4;
  }

  _measureStartBeat(measureNum) {
    const target = Math.max(1, Math.trunc(Number(measureNum || 1)));
    if (Array.isArray(this.measureBeats) && this.measureBeats.length) {
      let acc = 0;
      for (let i = 1; i < target; i++) {
        const beats = this.measureBeats[i - 1];
        acc += Number.isFinite(beats) && beats > 0 ? beats : this._measureBeatCount(i);
      }
      return acc;
    }
    return (target - 1) * this._measureBeatCount(target);
  }

  _xForOnset(onset, mX, mW, measureStart, measureBeats) {
    const usable = Math.max(1, mW - LEFT_PAD - RIGHT_PAD);
    const local = Math.min(Math.max(Number(onset) - measureStart, 0), measureBeats);
    return mX + LEFT_PAD + (local / Math.max(measureBeats, 0.001)) * usable;
  }

  _drawMeasureNotes(ctx, notes, mX, mW, sysY, measureNum = 1) {
    if (!notes.length) {
      // Draw whole rest centered in measure
      this._drawRest(ctx, mX + mW / 2, sysY, 4.0);
      return;
    }

    // Group by onset into columns (one column per unique onset)
    const onsetMap = new Map();
    for (const n of notes) {
      const key = n.onset.toFixed(6);
      if (!onsetMap.has(key)) onsetMap.set(key, []);
      onsetMap.get(key).push(n);
    }

    // Sort onsets → compute x per column
    const sortedKeys = [...onsetMap.keys()].sort((a, b) => parseFloat(a) - parseFloat(b));
    const measureStart = this._measureStartBeat(measureNum);
    const measureBeats = this._measureBeatCount(measureNum);
    const colXs = sortedKeys.map(key =>
      this._xForOnset(parseFloat(key), mX, mW, measureStart, measureBeats)
    );

    const notePositions = [];
    sortedKeys.forEach((key, colIdx) => {
      const nx = colXs[colIdx];
      // Store column x for cursor overlay
      this.noteColumns.push({
        onset: parseFloat(key),
        x: nx,
        yTop: sysY + ABOVE_STRINGS - 5,
        yBottom: sysY + ABOVE_STRINGS + STRINGS_H + 5,
      });
      for (const n of onsetMap.get(key)) {
        const stringIdx = n.string - 1;
        const ny = sysY + ABOVE_STRINGS + stringIdx * STRING_SPACING;
        notePositions.push({ note: n, x: nx, y: ny });
      }
    });

    notePositions.sort((a, b) => a.note.onset - b.note.onset);

    // Draw all notation (arcs, slides, bends first — behind notes)
    this._drawConnections(ctx, notePositions, sysY);

    // Draw each note
    for (const { note, x, y } of notePositions) {
      this._drawNote(ctx, note, x, y, sysY);
    }

    // (finger color is now baked into the oval fill in _drawNote — no second pass needed)

    // Draw dynamic marking once per measure column (only on change)
    for (let i = 0; i < sortedKeys.length; i++) {
      const key = sortedKeys[i];
      const col = onsetMap.get(key)[0];
      if (col.dynamic && col.dynamic !== this._lastDynamic) {
        this._lastDynamic = col.dynamic;
        ctx.font = FONT_DYNAMIC;
        ctx.fillStyle = COL_GREY;
        ctx.textAlign = 'center';
        ctx.fillText(col.dynamic, colXs[i], sysY + ABOVE_STRINGS + STRINGS_H + 60);
      }
    }

    // Draw PM / let-ring spans between staff and rhythm zone
    this._drawSpanAnnotations(ctx, notePositions, sysY, mX, mW);

    // Draw rhythm below
    this._drawRhythm(ctx, notePositions, sysY, mX, mW, measureStart, measureBeats);
  }

  // ── Span annotations: PM and let-ring bands below the TAB staff ───

  _drawSpanAnnotations(ctx, notePositions, sysY, mX, mW) {
    const staffBottom = sysY + ABOVE_STRINGS + STRINGS_H;
    const sorted = notePositions
      .slice()
      .sort((a, b) => a.note.onset - b.note.onset);

    this._drawAnnotationBand(ctx, sorted, 'palm_muted',  staffBottom + 5,  'P.M.', COL_PM);
    this._drawAnnotationBand(ctx, sorted, 'let_ring',    staffBottom + 14, 'let ring', COL_LET_RING);
  }

  _drawAnnotationBand(ctx, sortedPositions, field, y, label, color) {
    // Build unique x-positions per onset (chords share one x)
    const seen = new Set();
    const pts = [];
    for (const np of sortedPositions) {
      const key = np.note.onset.toFixed(6);
      if (np.note[field] && !seen.has(key)) {
        seen.add(key);
        pts.push(np.x);
      }
    }
    if (!pts.length) return;

    // Group consecutive x-positions into spans (gap > 1.5× COL_STEP breaks a span)
    const spans = [];
    let start = pts[0], end = pts[0];
    for (let i = 1; i < pts.length; i++) {
      if (pts[i] - pts[i - 1] <= COL_STEP * 1.6) {
        end = pts[i];
      } else {
        spans.push({ start, end });
        start = pts[i]; end = pts[i];
      }
    }
    spans.push({ start, end });

    ctx.save();
    ctx.font = `500 7.5px ${SANS}`;
    ctx.fillStyle = color;
    ctx.textBaseline = 'middle';

    for (const span of spans) {
      const lw = ctx.measureText(label).width;
      const lx = span.start - NOTE_RX;
      const ex = span.end + NOTE_RX + 6;

      // Label
      ctx.textAlign = 'left';
      ctx.fillText(label, lx, y);

      // Dashed line from after label to span end
      const lineX0 = lx + lw + 3;
      if (ex > lineX0 + 4) {
        ctx.strokeStyle = color;
        ctx.lineWidth = 0.75;
        ctx.setLineDash([3, 2]);
        ctx.beginPath();
        ctx.moveTo(lineX0, y);
        ctx.lineTo(ex, y);
        ctx.stroke();
        ctx.setLineDash([]);
        // Closing tick (small downward bar)
        ctx.lineWidth = 0.75;
        ctx.beginPath();
        ctx.moveTo(ex, y - 3);
        ctx.lineTo(ex, y + 4);
        ctx.stroke();
      }
    }
    ctx.restore();
  }

  // ── Single note rendering ─────────────────────────────────────────

  _drawNote(ctx, note, x, y, sysY) {
    const fret = note.fret;
    const isMuted = note.muted;
    const isHarmonic = !!note.harmonic_type;
    const isExportWarning = note.gp_fingering_export_status === 'missing_source_note_id';
    const isImpossible = note.review_severity === 'impossible';
    const isSuspect = note.review_severity === 'suspect';

    // ── White oval (erases string line)
    const label = note.ghost ? `(${fret})` : String(fret);
    const ovalRX = label.length > 1 ? NOTE_RX + 3 : NOTE_RX;

    // Oval fill: finger color when assigned, white otherwise
    const fingerFill = (!isMuted && !isHarmonic && note.finger && note.finger !== 'open' && fret > 0)
      ? (this._fingerColors[note.finger] || '#ffffff')
      : '#ffffff';
    let noteFill = fingerFill;
    if (isImpossible) noteFill = COL_REVIEW_IMPOSSIBLE_FILL;
    else if (isSuspect) noteFill = COL_REVIEW_SUSPECT_FILL;
    else if (isExportWarning) noteFill = COL_EXPORT_WARN_FILL;

    if (isHarmonic) {
      this._drawDiamond(ctx, x, y, ovalRX, NOTE_RY);
    } else {
      ctx.fillStyle = noteFill;
      ctx.beginPath();
      ctx.ellipse(x, y, ovalRX + 1, NOTE_RY + 1, 0, 0, Math.PI * 2);
      ctx.fill();
      if (isImpossible || isSuspect || isExportWarning) {
        ctx.strokeStyle = isImpossible
          ? COL_REVIEW_IMPOSSIBLE
          : (isSuspect ? COL_REVIEW_SUSPECT : COL_EXPORT_WARN);
        ctx.lineWidth = 1.5;
        ctx.stroke();
      }
    }

    // ── Fret number (or X for muted, ghost in parens, harmonic label)
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    if (isMuted) {
      ctx.font = 'bold 12px Arial';
      ctx.fillStyle = COL_MUTED;
      ctx.fillText('X', x, y);
    } else if (note.ghost) {
      ctx.font = label.length > 3 ? '8px Arial' : FONT_FRET_SM;
      ctx.fillStyle = '#888888';
      ctx.fillText(label, x, y + 0.5);
    } else {
      ctx.font = label.length > 1 ? FONT_FRET_SM : FONT_FRET;
      // Dark text on colored ovals; keep existing dark color — all finger colors are light enough
      ctx.fillStyle = isImpossible
        ? COL_REVIEW_IMPOSSIBLE
        : (isSuspect ? COL_REVIEW_SUSPECT : (isExportWarning ? COL_EXPORT_WARN : COL_FRET));
      ctx.fillText(label, x, y + 0.5);
    }

    // Harmonic type label (P.H. / A.H. / H.H.)
    if (isHarmonic && note.harmonic_type !== 'natural') {
      const hLabel = { pinch: 'P.H.', artificial: 'A.H.', harp: 'H.H.' }[note.harmonic_type] || '';
      if (hLabel) {
        ctx.font = '7px Arial';
        ctx.fillStyle = '#6a1b9a';
        ctx.textAlign = 'left';
        ctx.fillText(hLabel, x + ovalRX + 2, y - 6);
      }
    }

    // ── Notation overlays (above/around the note)

    // Tapping "T"
    if (note.tapping) {
      ctx.font = FONT_SYMBOL;
      ctx.fillStyle = COL_TAPPING;
      ctx.textAlign = 'center';
      ctx.fillText('T', x, y - NOTE_RY - 8);
    }

    // Slap "S" / Pop "P" (right-hand techniques)
    if (note.slap) {
      ctx.font = 'bold 10px Arial';
      ctx.fillStyle = '#1565c0';
      ctx.textAlign = 'center';
      ctx.fillText('S', x, y - NOTE_RY - 8);
    } else if (note.pop) {
      ctx.font = 'bold 10px Arial';
      ctx.fillStyle = '#1565c0';
      ctx.textAlign = 'center';
      ctx.fillText('P', x, y - NOTE_RY - 8);
    }

    // Golpe "*" (percussive body tap)
    if (note.golpe) {
      ctx.font = '14px Arial';
      ctx.fillStyle = '#5d4037';
      ctx.textAlign = 'center';
      ctx.fillText('*', x, y - NOTE_RY - 8);
    }

    // Accent ">" or "^"
    if (note.accent_strong) {
      ctx.font = 'bold 14px Arial';
      ctx.fillStyle = COL_ACCENT;
      ctx.textAlign = 'center';
      ctx.fillText('∧', x, y - NOTE_RY - 8);
    } else if (note.accent) {
      ctx.font = 'bold 13px Arial';
      ctx.fillStyle = COL_ACCENT;
      ctx.textAlign = 'center';
      ctx.fillText('>', x, y - NOTE_RY - 8);
    }

    // Bend arrow
    if (note.bend_value) {
      this._drawBend(ctx, x, y, note.bend_value, note.bend_type, note.duration);
    }

    // Vibrato wavy line
    if (note.articulation === 'vibrato' || note.articulation === 'wide_vibrato' || note.vibrato_wide) {
      this._drawVibrato(ctx, x, y, note.vibrato_wide || note.articulation === 'wide_vibrato');
    }

    // Tremolo picking slashes on stem
    if (note.tremolo_picking) {
      this._drawTremoloPicking(ctx, x, sysY);
    }

    // Staccato dot (•) above the oval
    if (note.staccato) {
      ctx.fillStyle = '#333333';
      ctx.beginPath();
      ctx.arc(x, y - NOTE_RY - 5, 1.8, 0, Math.PI * 2);
      ctx.fill();
    }

    // Strum direction: V (upstroke) or ⊓ (downstroke) above note
    if (note.strum_direction === 'up') {
      ctx.font = 'bold 11px Arial';
      ctx.fillStyle = '#37474f';
      ctx.textAlign = 'center';
      ctx.fillText('V', x, y - NOTE_RY - (note.tapping || note.accent || note.accent_strong ? 20 : 8));
    } else if (note.strum_direction === 'down') {
      ctx.font = 'bold 11px Arial';
      ctx.fillStyle = '#37474f';
      ctx.textAlign = 'center';
      ctx.fillText('\u22a4', x, y - NOTE_RY - (note.tapping || note.accent || note.accent_strong ? 20 : 8));
    }

    // Rasgueado: "Rasp." label below strings with dashes
    if (note.rasgueado) {
      const dashLen = 28;
      ctx.strokeStyle = '#795548';
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 2]);
      const ry = sysY + ABOVE_STRINGS + STRINGS_H + 20;
      ctx.beginPath();
      ctx.moveTo(x + ovalRX + 2, ry);
      ctx.lineTo(x + ovalRX + dashLen, ry);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.font = '7px Arial';
      ctx.fillStyle = '#795548';
      ctx.textAlign = 'left';
      ctx.fillText('Rasp.', x - ovalRX - 12, ry + 1);
    }

    // Finger color is applied to the oval background above (fingerFill).

    // Dynamic marking: rendered by _drawMeasureNotes, not per-note.
    // (removed from here to avoid showing on every note)
  }


  // ── Harmonic diamond ──────────────────────────────────────────────

  _drawDiamond(ctx, x, y, rx, ry) {
    ctx.fillStyle = '#ffffff';
    ctx.beginPath();
    ctx.moveTo(x, y - ry - 2);
    ctx.lineTo(x + rx + 2, y);
    ctx.lineTo(x, y + ry + 2);
    ctx.lineTo(x - rx - 2, y);
    ctx.closePath();
    ctx.fill();

    ctx.strokeStyle = COL_HARMONIC;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x, y - ry - 1);
    ctx.lineTo(x + rx + 1, y);
    ctx.lineTo(x, y + ry + 1);
    ctx.lineTo(x - rx - 1, y);
    ctx.closePath();
    ctx.stroke();
  }

  // ── Bend arrow ────────────────────────────────────────────────────

  _drawBend(ctx, x, y, bendValue, bendType, duration = 1) {
    const arrowH = 22;
    const tipY = y - NOTE_RY - arrowH;
    const isPre = bendType === 'pre_bend' || bendType === 'pre_bend_release';
    const isRelease = bendType === 'bend_release' || bendType === 'pre_bend_release';

    ctx.strokeStyle = COL_BEND;
    ctx.fillStyle = COL_BEND;
    ctx.lineWidth = 1.2;

    // Curved arrow going up
    ctx.beginPath();
    ctx.moveTo(x, y - NOTE_RY - 2);
    ctx.quadraticCurveTo(x + 6, tipY + arrowH * 0.3, x, tipY);
    ctx.stroke();

    // Arrow head
    ctx.beginPath();
    ctx.moveTo(x - 3, tipY + 5);
    ctx.lineTo(x, tipY);
    ctx.lineTo(x + 3, tipY + 5);
    ctx.stroke();

    // Label ("full" for 1-step bends, Guitar Pro convention)
    let label;
    if (bendValue <= 0.5) label = '½';
    else if (bendValue <= 1.0) label = 'full';
    else if (bendValue <= 1.5) label = '1½';
    else label = '2';

    if (isPre) label = '(' + label + ')';

    ctx.font = 'bold 8px Arial';
    ctx.textAlign = 'left';
    ctx.fillText(label, x + 3, tipY - 3);

    // Hold-plateau dashed line extending right from bend tip
    const plateauW = Math.max(10, Math.min(duration * COL_STEP * 0.75, 48));
    const plateauX0 = x + 3 + ctx.measureText(label).width + 2;
    const plateauX1 = x + plateauW;
    if (plateauX1 > plateauX0 + 4) {
      ctx.lineWidth = 0.9;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.moveTo(plateauX0, tipY - 3 - 4); // align with label cap-height
      ctx.lineTo(plateauX1, tipY - 3 - 4);
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // Release arrow: small downward curve at plateau end
    if (isRelease) {
      ctx.lineWidth = 1.2;
      const rx = plateauX1;
      ctx.beginPath();
      ctx.moveTo(rx, tipY - 3 - 4);
      ctx.quadraticCurveTo(rx + 4, tipY + arrowH * 0.3, rx, y - NOTE_RY - 2);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(rx - 3, y - NOTE_RY - 7);
      ctx.lineTo(rx, y - NOTE_RY - 2);
      ctx.lineTo(rx + 3, y - NOTE_RY - 7);
      ctx.stroke();
    }

    ctx.textAlign = 'center';
  }

  // ── Vibrato wave ──────────────────────────────────────────────────

  _drawVibrato(ctx, x, y, isWide) {
    const amp = isWide ? 3.5 : 2.0;
    const waveLen = 6;
    const length = 25;

    ctx.strokeStyle = COL_VIBRATO;
    ctx.lineWidth = isWide ? 1.5 : 1.0;
    ctx.beginPath();
    for (let dx = 0; dx < length; dx += 0.5) {
      const wy = y - NOTE_RY - 4 + Math.sin((dx / waveLen) * Math.PI * 2) * amp;
      if (dx === 0) ctx.moveTo(x + NOTE_RX + 2 + dx, wy);
      else ctx.lineTo(x + NOTE_RX + 2 + dx, wy);
    }
    ctx.stroke();

    // "~" style indicator (wide vibrato gets thicker waves)
    if (isWide) {
      ctx.font = '8px Arial';
      ctx.fillStyle = COL_VIBRATO;
      ctx.textAlign = 'left';
    }
  }

  // ── Tremolo picking (slashes on stem) ─────────────────────────────

  _drawTremoloPicking(ctx, x, sysY) {
    const baseY = sysY + ABOVE_STRINGS + STRINGS_H + STEM_GAP + 3;
    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 1.5;
    for (let i = 0; i < 3; i++) {
      const sy = baseY + STEM_H * 0.3 + i * 3;
      ctx.beginPath();
      ctx.moveTo(x - 3, sy + 2);
      ctx.lineTo(x + 3, sy - 2);
      ctx.stroke();
    }
  }

  // ── Connections: H/P arcs, slides ─────────────────────────────────

  _drawConnections(ctx, notePositions, sysY) {
    for (let i = 0; i < notePositions.length; i++) {
      const { note, x, y } = notePositions[i];
      const nextOnSameString = this._findNext(notePositions, i, note.string);

      // Hammer-on / Pull-off arcs — note is the ORIGIN; arc goes to next note on same string.
      // HopoOrigin/HopoDestination from GP7 are both mapped to HAMMER_ON/PULL_OFF at parse time.
      // Determine H vs P by comparing frets: ascending = H, descending = P.
      if ((note.articulation === 'hammer_on' || note.articulation === 'pull_off') && nextOnSameString) {
        const { x: nx, y: ny, note: nextNote } = nextOnSameString;
        const label = (nextNote.fret > note.fret) ? 'H'
                    : (nextNote.fret < note.fret) ? 'P'
                    : (note.articulation === 'pull_off' ? 'P' : 'H');
        this._drawSlurArc(ctx, x, y, nx, ny, label);
      }

      // Legato articulation (general)
      if (note.articulation === 'legato' && nextOnSameString) {
        const { x: nx, y: ny } = nextOnSameString;
        this._drawSlurArc(ctx, x, y, nx, ny, '');
      }

      // Slide lines
      if (note.slide_type && nextOnSameString) {
        const { x: nx, y: ny } = nextOnSameString;
        this._drawSlideLine(ctx, x, y, nx, ny, note.slide_type);
      } else if (note.slide_type && !nextOnSameString) {
        // Slide in/out with no target
        this._drawSlideInOut(ctx, x, y, note.slide_type);
      }

      if (note.articulation === 'slide' && nextOnSameString) {
        const { x: nx, y: ny } = nextOnSameString;
        this._drawSlideLine(ctx, x, y, nx, ny, 'shift');
      }
    }
  }

  _findNext(notePositions, fromIdx, stringNum) {
    for (let j = fromIdx + 1; j < notePositions.length; j++) {
      if (notePositions[j].note.string === stringNum) return notePositions[j];
    }
    return null;
  }

  // ── Slur arc (H/P) ───────────────────────────────────────────────

  _drawSlurArc(ctx, x1, y1, x2, y2, label) {
    const midX = (x1 + x2) / 2;
    const arcY = Math.min(y1, y2) - NOTE_RY - 10;

    ctx.strokeStyle = COL_HP_ARC;
    ctx.lineWidth = 1.2;
    ctx.beginPath();
    ctx.moveTo(x1 + NOTE_RX, y1 - NOTE_RY);
    ctx.quadraticCurveTo(midX, arcY, x2 - NOTE_RX, y2 - NOTE_RY);
    ctx.stroke();

    if (label) {
      ctx.font = FONT_SYMBOL_SM;
      ctx.fillStyle = COL_HP_ARC;
      ctx.textAlign = 'center';
      ctx.fillText(label, midX, arcY - 1);
    }
  }

  // ── Slide line ────────────────────────────────────────────────────

  _drawSlideLine(ctx, x1, y1, x2, y2, slideType) {
    const isLegato = slideType === 'legato';

    ctx.strokeStyle = COL_SLIDE;
    ctx.lineWidth = 1.2;
    ctx.setLineDash([]);

    // For legato slide: draw a small arc above the diagonal to distinguish from shift slide
    const sx = x1 + NOTE_RX + 2;
    const ex = x2 - NOTE_RX - 2;
    const mx = (sx + ex) / 2;
    const my = (y1 + y2) / 2;

    if (isLegato) {
      // Curved arc above the line (ties the two notes together)
      const arcY = Math.min(y1, y2) - 6;
      ctx.strokeStyle = COL_SLIDE;
      ctx.lineWidth = 0.8;
      ctx.beginPath();
      ctx.moveTo(sx, y1);
      ctx.quadraticCurveTo(mx, arcY, ex, y2);
      ctx.stroke();
      ctx.lineWidth = 1.2;
    }

    // Diagonal line from note 1 to note 2
    ctx.beginPath();
    ctx.moveTo(sx, y1);
    ctx.lineTo(ex, y2);
    ctx.stroke();
    ctx.setLineDash([]);
  }

  _drawSlideInOut(ctx, x, y, slideType) {
    ctx.strokeStyle = COL_SLIDE;
    ctx.lineWidth = 1.2;
    const len = 12;

    if (slideType === 'slide_in_below' || slideType === 'slide_in_above') {
      // Slide in: diagonal FROM below/above TO the note
      const fromY = slideType === 'slide_in_below' ? y + 6 : y - 6;
      ctx.beginPath();
      ctx.moveTo(x - len, fromY);
      ctx.lineTo(x - NOTE_RX - 1, y);
      ctx.stroke();
    } else if (slideType === 'slide_out_up' || slideType === 'slide_out_down') {
      const toY = slideType === 'slide_out_up' ? y - 6 : y + 6;
      ctx.beginPath();
      ctx.moveTo(x + NOTE_RX + 1, y);
      ctx.lineTo(x + len, toY);
      ctx.stroke();
    }
  }

  // ── Chord name detection ──────────────────────────────────────────

  _drawChordName(ctx, notes, mX, mW, sysY, measureNum = 1) {
    if (!notes.length) return;

    // Build onset→group map
    const onsetMap = new Map();
    for (const n of notes) {
      const key = n.onset.toFixed(6);
      if (!onsetMap.has(key)) onsetMap.set(key, []);
      onsetMap.get(key).push(n);
    }
    const sortedKeys = [...onsetMap.keys()].sort((a, b) => parseFloat(a) - parseFloat(b));
    const measureStart = this._measureStartBeat(measureNum);
    const measureBeats = this._measureBeatCount(measureNum);
    const chordColXs = sortedKeys.map(key =>
      this._xForOnset(parseFloat(key), mX, mW, measureStart, measureBeats)
    );

    let drawn = 0;
    const drawnNames = new Set();
    sortedKeys.forEach((key, colIdx) => {
      const group = onsetMap.get(key);
      // 1. Try explicit chord marker from the file (any group size)
      let name = this.chordMarkers[key] || null;
      // 2. Fall back to auto-detection (2+ simultaneous notes matching a diagram)
      if (!name && group.length >= 2) {
        name = this._matchChordName(group);
      }
      if (name && !drawnNames.has(name) && drawn < 3) {
        drawnNames.add(name);
        const nx = chordColXs[colIdx];
        const ly = sysY + 38;
        ctx.font = FONT_CHORD;
        const textW = ctx.measureText(name).width;
        const labelLeft = nx - 4;
        const lastLabel = this.chordLabelPositions.at(-1);
        if (lastLabel && Math.abs(ly - lastLabel.y) < 14 && labelLeft < lastLabel.rightEdge + 3) {
          return;
        }
        ctx.fillStyle = COL_CHORD;
        ctx.textAlign = 'left';
        ctx.fillText(name, labelLeft, ly);
        this.chordLabelPositions.push({
          x: labelLeft + textW / 2,
          y: ly,
          name,
          rightEdge: labelLeft + textW,
        });
        drawn++;
      }
    });
  }

  _matchChordName(notes) {
    if (!this.chordDiagrams.length) return null;
    // Match by comparing which frets are played against chord diagram frets
    const playedFrets = notes.map(n => n.fret);
    const playedStrings = notes.map(n => n.string - 1); // 0-indexed

    for (const cd of this.chordDiagrams) {
      let matchCount = 0;
      for (let i = 0; i < playedFrets.length; i++) {
        const si = playedStrings[i];
        // cd.frets is 6-element array for strings 1-6 (index 0=string1)
        if (si < cd.frets.length && cd.frets[si] === playedFrets[i]) {
          matchCount++;
        }
      }
      if (matchCount >= Math.min(playedFrets.length, 3)) {
        return cd.name;
      }
    }
    return null;
  }

  // ── Rhythm notation below tab ─────────────────────────────────────

  _drawRhythm(
    ctx,
    notePositions,
    sysY,
    mX = 0,
    mW = Infinity,
    measureOnset = null,
    measureBeats = null,
  ) {
    const baseY = sysY + ABOVE_STRINGS + STRINGS_H + STEM_GAP;

    // Group by onset for beam grouping
    const onsetGroups = new Map();
    for (const np of notePositions) {
      const key = np.note.onset.toFixed(4);
      if (!onsetGroups.has(key)) onsetGroups.set(key, []);
      onsetGroups.get(key).push(np);
    }

    const cols = [];
    for (const [key, group] of onsetGroups) {
      const x = group[0].x;
      const dur = Math.min(...group.map(g => g.note.duration));
      const ta = group[0].note.tuplet_actual ?? null;
      const tn = group[0].note.tuplet_normal ?? null;
      cols.push({
        x,
        duration: dur,
        notatedDuration: this._notatedDuration(dur, ta, tn),
        onset: parseFloat(key),
        tuplet_actual: ta,
        tuplet_normal: tn,
      });
    }
    cols.sort((a, b) => a.onset - b.onset);

    const rhythmMeasureOnset = Number.isFinite(measureOnset)
      ? Number(measureOnset)
      : (cols.length > 0 ? Math.floor(cols[0].onset + 1e-6) : 0);
    const rhythmMeasureBeats = Number.isFinite(measureBeats) && measureBeats > 0
      ? Number(measureBeats)
      : this._measureBeatCount(1);

    // Draw stems
    for (const col of cols) {
      if (col.notatedDuration >= 4.0) continue; // whole note: nothing in rhythm zone

      const stemLen = col.notatedDuration >= 2.0 ? STEM_H / 2 : STEM_H;

      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(col.x, baseY);
      ctx.lineTo(col.x, baseY + stemLen);
      ctx.stroke();

    }

    // Beat-aware beams
    this._drawBeams(ctx, cols, baseY, rhythmMeasureOnset, rhythmMeasureBeats);

    // Dotted notes: draw augmentation dots after beams so they are never
    // half-covered by a beam bar.
    for (const col of cols) {
      if (!this._isDotted(col.notatedDuration)) continue;
      const dotX = col.x + 5;
      const dotY = baseY + STEM_H - 2;
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(dotX, dotY, 2.5, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COL_TEXT;
      ctx.beginPath();
      ctx.arc(dotX, dotY, 1.3, 0, Math.PI * 2);
      ctx.fill();
    }

    // Flags for unbeamed notes (drawn after beams to know which are beamed)
    const beamedOnsets = this._getBeamedOnsets(cols, rhythmMeasureOnset, rhythmMeasureBeats);
    for (const col of cols) {
      const nFlags = this._numFlags(col.notatedDuration);
      if (nFlags > 0 && !beamedOnsets.has(col.onset.toFixed(4))) {
        for (let fi = 0; fi < nFlags; fi++) {
          this._drawFlag(ctx, col.x, baseY + STEM_H, fi);
        }
      }
    }

    // ── Rest symbols for gaps within the measure ──────────────────────
    const measureEnd = rhythmMeasureOnset + rhythmMeasureBeats;
    const rightBound = mX + mW - RIGHT_PAD - 4;
    for (let i = 0; i <= cols.length; i++) {
      const gapStart = i === 0 ? rhythmMeasureOnset
        : cols[i - 1].onset + cols[i - 1].duration;
      const gapEnd   = i === cols.length ? measureEnd : cols[i].onset;
      const gapDur   = gapEnd - gapStart;
      if (gapDur < 0.12) continue;  // too small (< 1/32 beat) — skip

      let restX;
      if (i === 0) {
        // Leading rest: place before first note
        restX = cols.length > 0 ? cols[0].x - COL_STEP * 0.6 : mX + LEFT_PAD;
      } else if (i === cols.length) {
        // Trailing rest: midpoint between last note and measure barline
        const lastX = cols[cols.length - 1].x;
        const barlineX = mX + mW - RIGHT_PAD;
        restX = (lastX + barlineX) / 2;
      } else {
        // Mid-measure rest: midpoint between surrounding note columns
        restX = (cols[i - 1].x + cols[i].x) / 2;
      }
      // Clamp to measure boundaries
      if (restX < mX + LEFT_PAD || restX > rightBound) continue;
      this._drawRestOnStaff(ctx, restX, sysY, gapDur);
      this._drawRestStem(ctx, restX, baseY, gapDur);
    }

    // ── Tuplet brackets ─────────────────────────────────────────────
    this._drawTupletBrackets(ctx, cols, baseY);
  }

  _drawTupletBrackets(ctx, cols, baseY) {
    // Scan contiguous same-ratio tuplets and emit a bracket only when the
    // covered real duration equals the source tuplet window.  Mixed values such
    // as 1/3 + 1/6 + 1/3 + 1/6 therefore form one 1-beat 3:2 bracket, not two
    // half-beat fragments.
    let run = [];
    let curRatio = null;
    let prevEnd = null;

    const flush = () => {
      if (run.length < 2 || curRatio === null) {
        run = [];
        curRatio = null;
        prevEnd = null;
        return;
      }
      let group = [];
      let notatedTotal = 0;
      for (const col of run) {
        if (group.length === 0) {
          notatedTotal = 0;
        }
        group.push(col);
        notatedTotal += col.notatedDuration || col.duration;
        const unit = this._completeTupletBaseUnit(notatedTotal, curRatio.actual);
        if (unit !== null) {
          const targetSpan = curRatio.normal * unit;
          const span = (col.onset + col.duration) - group[0].onset;
          if (group.length >= 2 && Math.abs(span - targetSpan) <= Math.max(0.01, targetSpan * 0.001)) {
            this._drawTupletBracket(
              ctx,
              group[0].x,
              group[group.length - 1].x,
              baseY,
              curRatio.actual,
            );
          }
          group = [];
          notatedTotal = 0;
        }
      }
      run = [];
      curRatio = null;
      prevEnd = null;
    };

    for (const col of cols) {
      const ta = col.tuplet_actual;
      const tn = col.tuplet_normal;
      if (ta === null || ta === undefined || tn === null || tn === undefined) {
        flush();
        continue;
      }
      if (prevEnd !== null && col.onset - prevEnd >= 0.115) {
        flush();
      }
      const ratio = `${ta}:${tn}`;
      if (curRatio !== null && ratio !== curRatio.key) {
        flush();
      }
      if (curRatio === null) {
        curRatio = { key: ratio, actual: ta, normal: tn };
      }
      run.push(col);
      prevEnd = col.onset + col.duration;
    }
    flush();
  }

  _completeTupletBaseUnit(notatedTotal, actual) {
    const unit = notatedTotal / actual;
    for (const candidate of [0.125, 0.25, 0.5, 1.0, 2.0, 4.0]) {
      if (Math.abs(unit - candidate) <= 0.0001) return candidate;
    }
    return null;
  }

  _drawTupletBracket(ctx, x1, x2, baseY, number) {
    // Bracket below the rhythm stems: vertical ticks at each end, horizontal
    // line with a gap for the number, number centered in the gap.
    const by = baseY + STEM_H + 5;  // horizontal bar Y
    const tickH = 4;                 // downward tick height
    const numStr = String(number);
    ctx.font = 'bold 8px Arial';
    const numW = ctx.measureText(numStr).width / 2 + 2; // half-width + padding
    const mid = (x1 + x2) / 2;

    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 0.9;

    // Left vertical tick
    ctx.beginPath();
    ctx.moveTo(x1, by);
    ctx.lineTo(x1, by + tickH);
    ctx.stroke();

    // Right vertical tick
    ctx.beginPath();
    ctx.moveTo(x2, by);
    ctx.lineTo(x2, by + tickH);
    ctx.stroke();

    // Horizontal line left segment (tick base to number gap)
    ctx.beginPath();
    ctx.moveTo(x1, by + tickH);
    ctx.lineTo(mid - numW, by + tickH);
    ctx.stroke();

    // Horizontal line right segment (number gap to right tick)
    ctx.beginPath();
    ctx.moveTo(mid + numW, by + tickH);
    ctx.lineTo(x2, by + tickH);
    ctx.stroke();

    // Number centered in gap
    ctx.fillStyle = COL_TEXT;
    ctx.textAlign = 'center';
    ctx.fillText(numStr, mid, by + tickH + 7);
  }

  // ── Rest symbol on the TAB staff (vertically centered between strings) ───
  //
  // Uses the proper rest SVG glyphs shipped in /static/img/rests/ rather than
  // hand-drawn approximations. Images are pre-loaded once on the first call
  // and cached on the renderer instance so subsequent paints are synchronous.

  _ensureRestGlyphsLoaded() {
    if (this._restGlyphs) return;
    this._restGlyphs = {};
    const PATHS = {
      half:         '/static/img/rests/half.svg',
      quarter:      '/static/img/rests/quarter.svg',
      eighth:       '/static/img/rests/eighth.svg',
      sixteenth:    '/static/img/rests/sixteenth.svg',
      thirtysecond: '/static/img/rests/thirtysecond.svg',
    };
    for (const [kind, src] of Object.entries(PATHS)) {
      const img = new Image();
      img.onload = () => {
        // Re-render once the SVG is decoded so the rest replaces the
        // empty placeholder oval. Cheap (debounced by browser frame).
        try { this.render(); } catch (_) { /* renderer torn down */ }
      };
      img.src = src;
      this._restGlyphs[kind] = img;
    }
  }

  _selectRestGlyph(duration) {
    if (duration >= 2.0)  return this._restGlyphs.half;
    if (duration >= 1.0)  return this._restGlyphs.quarter;
    if (duration >= 0.5)  return this._restGlyphs.eighth;
    if (duration >= 0.25) return this._restGlyphs.sixteenth;
    return this._restGlyphs.thirtysecond;
  }

  _drawRestOnStaff(ctx, x, sysY, duration) {
    this._ensureRestGlyphsLoaded();
    const midY = sysY + ABOVE_STRINGS + STRINGS_H / 2;

    // Clear an oval behind the glyph so the string lines do not cut through.
    ctx.fillStyle = this._bgScore;
    ctx.beginPath();
    ctx.ellipse(x, midY, 9, 14, 0, 0, Math.PI * 2);
    ctx.fill();

    const img = this._selectRestGlyph(duration);
    if (!img || !img.complete || img.naturalWidth === 0) {
      // Still loading — leave the cleared oval. _invalidate will trigger a
      // repaint once the image is decoded.
      return;
    }

    // Target visual heights tuned to the existing zigzag/dot dimensions
    // (≈ 20 px for quarter, smaller for shorter values; half-rest is short
    // because it sits on top of a staff line in real notation).
    const targetH = duration >= 2.0 ? 8
                  : duration >= 1.0 ? 22
                  : duration >= 0.5 ? 18
                  : duration >= 0.25 ? 22
                  : 26;
    const aspect = img.naturalWidth / img.naturalHeight;
    const targetW = targetH * aspect;
    ctx.drawImage(img, x - targetW / 2, midY - targetH / 2, targetW, targetH);
  }

  _drawRestStem(ctx, x, baseY, duration) {
    if (duration >= 4.0) return; // whole rest: nothing in rhythm zone

    const stemLen = duration >= 2.0 ? STEM_H / 2 : STEM_H;

    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 0.9;
    ctx.beginPath();
    ctx.moveTo(x, baseY);
    ctx.lineTo(x, baseY + stemLen);
    ctx.stroke();

    if (this._isDotted(duration)) {
      ctx.fillStyle = COL_TEXT;
      ctx.beginPath();
      ctx.arc(x + 4, baseY + stemLen - 2, 1.3, 0, Math.PI * 2);
      ctx.fill();
    }

    const nFlags = this._numFlags(duration);
    for (let fi = 0; fi < nFlags; fi++) {
      this._drawFlag(ctx, x, baseY + stemLen, fi);
    }
  }

  _numFlags(duration) {
    if (duration >= 1.0) return 0;
    if (duration >= 0.5) return 1;
    if (duration >= 0.25) return 2;
    return 3;
  }

  _notatedDuration(duration, tupletActual, tupletNormal) {
    const actual = Number(tupletActual);
    const normal = Number(tupletNormal);
    if (Number.isFinite(actual) && Number.isFinite(normal) && normal > 0 && actual > 0) {
      return duration * actual / normal;
    }
    return duration;
  }

  _drawFlag(ctx, x, stemEnd, flagIdx) {
    // Straight horizontal tick — one per sub-beat division (8th=1, 16th=2, 32nd=3)
    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 1.4;
    ctx.lineCap = 'round';
    const fy = stemEnd - flagIdx * BEAM_GAP_Y;
    ctx.beginPath();
    ctx.moveTo(x, fy);
    ctx.lineTo(x + 8, fy);
    ctx.stroke();
    ctx.lineCap = 'butt';
  }

  _drawBeams(ctx, cols, baseY, measureOnset, measureBeats) {
    if (cols.length < 2) return;
    const groups = this._computeBeamGroups(cols, measureOnset, measureBeats);
    const BEAMLET_W = 6; // partial-beam stub width (px)

    for (const group of groups) {
      const y = baseY + STEM_H;
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = BEAM_H;

      // Primary beam: spans the full group
      ctx.beginPath();
      ctx.moveTo(group[0].x, y);
      ctx.lineTo(group[group.length - 1].x, y);
      ctx.stroke();

      // Secondary beams + beamlets for 16th-or-shorter notes
      let runStart = null;
      let runEnd = null;
      let runStartIdx = -1;

      const flushRun = () => {
        if (runStart === null) return;
        ctx.lineWidth = BEAM_H;
        if (runEnd > runStart) {
          // Full secondary beam over a run of 2+ sub-8th notes
          ctx.beginPath();
          ctx.moveTo(runStart, y + BEAM_GAP_Y);
          ctx.lineTo(runEnd, y + BEAM_GAP_Y);
          ctx.stroke();
        } else {
          // Single isolated sub-8th note → partial beam (beamlet).
          // Direction matches the backend renderer: toward the next note when
          // one exists, otherwise back toward the previous note.
          const dir = (runStartIdx < group.length - 1) ? 1 : -1;
          ctx.beginPath();
          ctx.moveTo(runStart, y + BEAM_GAP_Y);
          ctx.lineTo(runStart + dir * BEAMLET_W, y + BEAM_GAP_Y);
          ctx.stroke();
        }
        runStart = null;
        runEnd = null;
        runStartIdx = -1;
      };

      for (let i = 0; i < group.length; i++) {
        const col = group[i];
        if (col.notatedDuration < 0.5) {
          if (runStart === null) { runStart = col.x; runStartIdx = i; }
          runEnd = col.x;
        } else {
          flushRun();
        }
      }
      flushRun();
    }
  }

  /** Compute beam groups respecting beat boundaries and rests */
  _computeBeamGroups(cols, measureOnset, measureBeats = this.bpm) {
    const bpm = Number.isFinite(measureBeats) && measureBeats > 0 ? measureBeats : this.bpm;
    // Build beat boundary list
    const beatBounds = [];
    for (let i = 1; i <= Math.ceil(bpm); i++) {
      beatBounds.push(measureOnset + i);
    }

    const groups = [];
    let curGroup = [];

    for (let i = 0; i < cols.length; i++) {
      const col = cols[i];
      // Only sub-quarter notes (duration < 1.0) can be beamed
      if (col.notatedDuration >= 1.0) {
        if (curGroup.length >= 2) groups.push([...curGroup]);
        curGroup = [];
        continue;
      }

      // Check if we cross a beat boundary from previous note in group
      if (curGroup.length > 0) {
        const lastOnset = curGroup[curGroup.length - 1].onset;
        const crossesBeat = beatBounds.some(bb => lastOnset < bb && col.onset >= bb);

        // Check for gap/rest between previous note and this one
        const prev = cols[i - 1];
        const prevEnd = prev.onset + prev.duration;
        const gap = col.onset - prevEnd;
        const hasRest = gap >= 0.115; // >= 1/32 beat gap

        if (crossesBeat || hasRest) {
          if (curGroup.length >= 2) groups.push([...curGroup]);
          curGroup = [col];
          continue;
        }
      }

      curGroup.push(col);
    }
    if (curGroup.length >= 2) groups.push(curGroup);
    return groups;
  }

  /** Returns a Set of onset keys that are beamed (for suppressing flags) */
  _getBeamedOnsets(cols, measureOnset, measureBeats = this.bpm) {
    const groups = this._computeBeamGroups(cols, measureOnset, measureBeats);
    const beamed = new Set();
    for (const group of groups) {
      for (const col of group) {
        beamed.add(col.onset.toFixed(4));
      }
    }
    return beamed;
  }

  // ── Rest symbol ───────────────────────────────────────────────────

  _drawRest(ctx, x, sysY, duration) {
    const midY = sysY + ABOVE_STRINGS + STRINGS_H / 2;

    ctx.fillStyle = COL_TEXT;
    ctx.strokeStyle = COL_TEXT;

    if (duration >= 4.0) {
      // ── Whole rest: filled rectangle hanging below string 2
      const ry = sysY + ABOVE_STRINGS + STRING_SPACING;
      // White disc to clear string lines
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(x, ry + 2.5, 8, 0, Math.PI * 2);
      ctx.fill();
      // Filled rectangle
      ctx.fillStyle = COL_TEXT;
      ctx.fillRect(x - 6, ry, 12, 5);
    } else if (duration >= 2.0) {
      // ── Half rest: filled rectangle sitting on string 3
      const ry = sysY + ABOVE_STRINGS + 2 * STRING_SPACING;
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(x, ry - 2.5, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COL_TEXT;
      ctx.fillRect(x - 6, ry - 5, 12, 5);
    } else if (duration >= 1.0) {
      // ── Quarter rest: drawn as zigzag path (standard notation)
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(x, midY, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = 1.6;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      const top = midY - 8;
      ctx.moveTo(x + 3, top);
      ctx.lineTo(x - 2, top + 4);
      ctx.lineTo(x + 2, top + 8);
      ctx.lineTo(x - 3, top + 12);
      ctx.lineTo(x + 1, top + 16);
      ctx.stroke();
      ctx.lineCap = 'butt';
      ctx.lineJoin = 'miter';
    } else if (duration >= 0.5) {
      // ── Eighth rest: angled line with one dot/flag
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(x, midY, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = 1.4;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x + 3, midY - 6);
      ctx.lineTo(x - 2, midY + 6);
      ctx.stroke();
      // Dot/flag at top
      ctx.fillStyle = COL_TEXT;
      ctx.beginPath();
      ctx.arc(x + 3, midY - 6, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineCap = 'butt';
    } else {
      // ── Sixteenth rest: angled line with two dots/flags
      ctx.fillStyle = this._bgScore;
      ctx.beginPath();
      ctx.arc(x, midY, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = 1.4;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x + 3, midY - 8);
      ctx.lineTo(x - 3, midY + 6);
      ctx.stroke();
      // Two dots/flags
      ctx.fillStyle = COL_TEXT;
      ctx.beginPath();
      ctx.arc(x + 3, midY - 8, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x + 1, midY - 3, 2, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineCap = 'butt';
    }
  }

  // ── Helpers ───────────────────────────────────────────────────────

  _isDotted(duration) {
    // Check if duration is a dotted value: 1.5, 3.0, 0.75, etc.
    const base = [4, 2, 1, 0.5, 0.25, 0.125];
    for (const b of base) {
      if (Math.abs(duration - b * 1.5) < 0.01) return true;
    }
    return false;
  }
}



// ── Legend HTML builder ─────────────────────────────────────────────────────
// Generates the full "Table des matières" guide as HTML cards with mini-canvas
// previews, matching the FretWise documentation.
// ───────────────────────────────────────────────────────────────────────────

/** Draw 3 horizontal string lines into a mini canvas, returns {top, spacing}. */
function _lgStr(ctx, w, h, n = 3) {
  const top = 12, bot = h - 12;
  const sp = n < 2 ? 0 : (bot - top) / (n - 1);
  ctx.strokeStyle = '#888'; ctx.lineWidth = 0.5;
  for (let i = 0; i < n; i++) {
    ctx.beginPath(); ctx.moveTo(6, top + i * sp); ctx.lineTo(w - 6, top + i * sp); ctx.stroke();
  }
  return { top, sp, n };
}

/** Draw a fret oval with label at (x,y). */
function _lgNote(ctx, x, y, fret = 9, col = '#1a1a1a', ghost = false) {
  const s = ghost ? `(${fret})` : String(fret);
  const rx = s.length > 2 ? 11 : s.length > 1 ? 9 : 7, ry = 5;
  ctx.fillStyle = '#fff';
  ctx.beginPath(); ctx.ellipse(x, y, rx + 1, ry + 1, 0, 0, Math.PI * 2); ctx.fill();
  ctx.font = `${s.length > 2 ? 6.5 : s.length > 1 ? 7.5 : 9}px Arial`;
  ctx.fillStyle = ghost ? '#888' : col;
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  ctx.fillText(s, x, y);
}

/** Draw a slur arc between two x positions at height y. */
function _lgArc(ctx, x1, y1, x2, y2, label = '') {
  const mx = (x1 + x2) / 2, cy = Math.min(y1, y2) - 8;
  ctx.strokeStyle = '#666'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.quadraticCurveTo(mx, cy, x2, y2); ctx.stroke();
  if (label) {
    ctx.font = 'bold 8px Arial'; ctx.fillStyle = '#444'; ctx.textAlign = 'center';
    ctx.fillText(label, mx, cy - 1);
  }
}

/** Draw a vibrato wavy line at y. */
function _lgVib(ctx, x, y, w, wide = false) {
  ctx.strokeStyle = wide ? '#2e7d32' : '#388e3c';
  ctx.lineWidth = wide ? 1.2 : 0.9;
  const amp = wide ? 3 : 2, freq = wide ? 6 : 5;
  ctx.beginPath();
  for (let i = 0; i <= w; i++) {
    const yy = y + Math.sin(i / freq * Math.PI) * amp;
    if (i === 0) ctx.moveTo(x + i, yy); else ctx.lineTo(x + i, yy);
  }
  ctx.stroke();
}

/** Draw a bend arrow upward from (x,y). */
function _lgBend(ctx, x, y, semis = 1) {
  ctx.strokeStyle = '#c62828'; ctx.lineWidth = 1.2;
  ctx.beginPath(); ctx.moveTo(x, y - 2); ctx.lineTo(x, y - 18); ctx.stroke();
  // arrowhead
  ctx.beginPath(); ctx.moveTo(x - 4, y - 14); ctx.lineTo(x, y - 18); ctx.lineTo(x + 4, y - 14); ctx.stroke();
  ctx.font = '7px Arial'; ctx.fillStyle = '#c62828'; ctx.textAlign = 'center';
  ctx.fillText(semis === 0.5 ? '½' : semis === 1.5 ? '1½' : String(semis), x + 7, y - 14);
}

/** Draw a diagonal slide line from (x1,y1) to (x2,y2). */
function _lgSlide(ctx, x1, y1, x2, y2) {
  ctx.strokeStyle = '#555'; ctx.lineWidth = 1;
  ctx.beginPath(); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2); ctx.stroke();
}

/** Create and draw a mini-canvas for a legend card. */
function _makeMiniCanvas(drawFn) {
  const c = document.createElement('canvas');
  c.width = 160; c.height = 64;
  c.style.cssText = 'width:160px;height:64px;background:#fafafa;border-radius:4px;';
  const ctx = c.getContext('2d');
  drawFn(ctx, 160, 64);
  return c;
}

// ─── All 50 legend entries grouped by section ───────────────────────────────

const _LG_SECTIONS = [
  {
    id: 'fondamentaux', title: 'Fondamentaux',
    items: [
      {
        title: 'Comprendre la tab',
        desc: 'La tablature représente les six cordes de la guitare vues de dessus quand on regarde la manche vers le bas.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          // black fretboard square
          ctx.fillStyle = '#333';
          ctx.fillRect(w - 32, top - 4, 22, sp * 5 + 8);
          ctx.strokeStyle = '#fff'; ctx.lineWidth = 0.5;
          for (let i = 1; i < 3; i++) {
            ctx.beginPath(); ctx.moveTo(w - 32 + i * 7, top - 2); ctx.lineTo(w - 32 + i * 7, top + sp * 5 + 4); ctx.stroke();
          }
        },
      },
      {
        title: 'Accords en tab guitare',
        desc: 'Un accord se lit verticalement : plusieurs frettes jouées sur des cordes différentes au même instant.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          const x = w / 2;
          [0, 1, 2, 3, 4, 5].forEach((i, idx) => {
            if ([0,1,2,3].includes(idx)) _lgNote(ctx, x, top + i * sp, [0,0,2,2,0,0][idx]);
          });
        },
      },
    ],
  },
  {
    id: 'articulations', title: 'Articulations de note',
    items: [
      {
        title: 'Hammer-on',
        desc: 'La seconde note est produite par la main gauche sans nouvelle attaque de la main droite.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 45, y, 9); _lgNote(ctx, 115, y, 11);
          _lgArc(ctx, 52, y - 5, 108, y - 5, 'H');
        },
      },
      {
        title: 'Pull-off',
        desc: 'La note suivante est déclenchée en retirant le doigt de la main gauche.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 45, y, 9); _lgNote(ctx, 115, y, 11);
          _lgArc(ctx, 52, y - 5, 108, y - 5, 'P');
        },
      },
      {
        title: 'Tires (Bend)',
        desc: 'Le tire modifie la hauteur de la note : le rendu montre la valeur montée au-dessus de la note.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 60, y, 14); _lgBend(ctx, 60, y - 6, 1);
        },
      },
      {
        title: 'Relâche du tiré',
        desc: 'Le relâche du tire indique le retour de la corde à sa hauteur initiale.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 50, y, 14);
          ctx.strokeStyle = '#c62828'; ctx.lineWidth = 1.2;
          ctx.beginPath(); ctx.moveTo(50, y - 2); ctx.lineTo(50, y - 16); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(50, y - 16); ctx.lineTo(85, y - 16); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(85, y - 16); ctx.lineTo(85, y - 4); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(81, y - 8); ctx.lineTo(85, y - 4); ctx.lineTo(89, y - 8); ctx.stroke();
          ctx.font = '7px Arial'; ctx.fillStyle = '#c62828'; ctx.textAlign = 'center';
          ctx.fillText('1', 56, y - 19);
        },
      },
      {
        title: 'Slide',
        desc: 'Un slide relie deux frettes sur une même corde par une diagonale.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 50, y, 11); _lgNote(ctx, 110, y, 9);
          _lgSlide(ctx, 59, y - 1, 101, y + 1);
        },
      },
      {
        title: 'Legato slide',
        desc: 'Le legato slide conserve le lien entre les deux notes sans ré-attaque.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 50, y, 9); _lgNote(ctx, 110, y, 11);
          _lgArc(ctx, 57, y - 3, 103, y - 3);
          _lgSlide(ctx, 57, y, 103, y);
        },
      },
    ],
  },
  {
    id: 'effets', title: 'Effets de main gauche',
    items: [
      {
        title: 'Vibrato léger de la main gauche',
        desc: 'Une vague courte au-dessus de la note indique un vibrato léger.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 55, y, 9); _lgVib(ctx, 62, y - 10, 55, false);
        },
      },
      {
        title: 'Vibrato large de la main gauche',
        desc: 'Une vague plus longue indique un vibrato plus ample.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 45, y, 9); _lgVib(ctx, 53, y - 11, 75, true);
        },
      },
      {
        title: 'Vibrato avec barre de tremolo',
        desc: 'Variation ample appliquée avec la barre de vibrato (whammy bar).',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 40, y, 9);
          // wider sinusoidal representing tremolo bar
          ctx.strokeStyle = '#1565c0'; ctx.lineWidth = 1.2;
          ctx.beginPath();
          for (let i = 0; i <= 80; i++) {
            const yy = y - 11 + Math.sin(i / 7 * Math.PI) * 4;
            if (i === 0) ctx.moveTo(48 + i, yy); else ctx.lineTo(48 + i, yy);
          }
          ctx.stroke();
        },
      },
      {
        title: 'Son prolongé (Let ring)',
        desc: 'Le marqueur let ring prolonge la résonance jusqu\'à la fin du trait pointillé.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 40, y, 0);
          ctx.font = '7px Arial'; ctx.fillStyle = '#1a237e'; ctx.textAlign = 'left';
          ctx.fillText('let ring', 50, y - 7);
          ctx.strokeStyle = '#1a237e'; ctx.lineWidth = 0.7; ctx.setLineDash([3, 2]);
          ctx.beginPath(); ctx.moveTo(50, y); ctx.lineTo(150, y); ctx.stroke();
          ctx.setLineDash([]);
        },
      },
    ],
  },
  {
    id: 'main_droite', title: 'Techniques de main droite',
    items: [
      {
        title: 'Palm mute',
        desc: 'Le marqueur P.M. indique un étouffement partiel de la corde avec la paume.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top;
          [30, 60, 90, 120].forEach(x => _lgNote(ctx, x, top + sp, 9));
          ctx.font = '7px Arial'; ctx.fillStyle = '#bf360c'; ctx.textAlign = 'left';
          ctx.fillText('P.M.', 22, top + 2 * sp + 12);
          ctx.strokeStyle = '#bf360c'; ctx.lineWidth = 0.7; ctx.setLineDash([3, 2]);
          ctx.beginPath(); ctx.moveTo(48, top + 2 * sp + 12); ctx.lineTo(140, top + 2 * sp + 12); ctx.stroke();
          ctx.setLineDash([]);
        },
      },
      {
        title: 'Tapping',
        desc: 'Le tapping est affiché par un T placé au-dessus de la note concernée.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 55, y, 5); _lgNote(ctx, 100, y, 7);
          ctx.font = 'bold 9px Arial'; ctx.fillStyle = '#ad1457'; ctx.textAlign = 'center';
          ctx.fillText('T', 55, y - 12);
          ctx.fillText('T', 100, y - 12);
        },
      },
      {
        title: 'Slap',
        desc: 'Le slap percute la corde au pouce ; il est souvent noté par la lettre S.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          [45, 80, 115].forEach(x => {
            _lgNote(ctx, x, y, 0);
            ctx.font = 'bold 8px Arial'; ctx.fillStyle = '#1565c0'; ctx.textAlign = 'center';
            ctx.fillText('S', x, y - 11);
            ctx.fillStyle = '#1565c0'; ctx.beginPath(); ctx.arc(x, y - 18, 1.5, 0, Math.PI * 2); ctx.fill();
          });
        },
      },
      {
        title: 'Popping',
        desc: 'Le popping est une attaque tirée vers le haut, souvent notée par la lettre P.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          [45, 80, 115].forEach(x => {
            _lgNote(ctx, x, y, 0);
            ctx.font = 'bold 8px Arial'; ctx.fillStyle = '#1565c0'; ctx.textAlign = 'center';
            ctx.fillText('P', x, y - 11);
          });
        },
      },
      {
        title: 'Tremolo (picking)',
        desc: 'Le tremolo picking multiplie rapidement les attaques d\'une même note.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 55, y, 1); _lgNote(ctx, 100, y, 0);
          // 3 diagonal slashes above notes
          [55, 100].forEach(x => {
            const sy = y - 18;
            ctx.strokeStyle = '#444'; ctx.lineWidth = 1;
            [-4, 0, 4].forEach(dx => {
              ctx.beginPath(); ctx.moveTo(x + dx - 3, sy + 5); ctx.lineTo(x + dx + 3, sy - 5); ctx.stroke();
            });
          });
        },
      },
      {
        title: 'Rasgueado',
        desc: 'Le rasgueado flamenco est un balayage rapide successif des doigts.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          ctx.font = '7px Arial'; ctx.fillStyle = '#795548'; ctx.textAlign = 'left';
          ctx.fillText('Rasp.', 8, top + 1.5 * sp + 1);
          ctx.strokeStyle = '#795548'; ctx.lineWidth = 0.7; ctx.setLineDash([3, 2]);
          ctx.beginPath(); ctx.moveTo(42, top + 1.5 * sp); ctx.lineTo(148, top + 1.5 * sp); ctx.stroke();
          ctx.setLineDash([]);
        },
      },
      {
        title: 'Attaque vers le haut',
        desc: 'Le symbole V indique un balayage ascendant du médiator (upstroke).',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 0);
          ctx.font = 'bold 12px Arial'; ctx.fillStyle = '#37474f'; ctx.textAlign = 'center';
          ctx.fillText('V', 80, y - 14);
        },
      },
      {
        title: 'Attaque vers le bas',
        desc: 'Le symbole ⊤ (ou π) indique un balayage descendant du médiator (downstroke).',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 0);
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#37474f'; ctx.textAlign = 'center';
          ctx.fillText('\u22a4', 80, y - 14);
        },
      },
      {
        title: 'Golpe',
        desc: 'Le golpe combine un coup percussif sur la table avec le jeu de la main droite.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          const cx = 80, cy = y - 10;
          ctx.strokeStyle = '#4caf50'; ctx.lineWidth = 1; ctx.fillStyle = 'transparent';
          ctx.beginPath(); ctx.arc(cx, cy, 12, 0, Math.PI * 2); ctx.stroke();
          ctx.font = '14px Arial'; ctx.fillStyle = '#4caf50'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('*', cx, cy);
          ctx.textBaseline = 'alphabetic';
        },
      },
    ],
  },
  {
    id: 'types_notes', title: 'Types de notes',
    items: [
      {
        title: 'Note fantôme',
        desc: 'Une note fantôme est affichée entre parenthèses pour signaler une attaque très faible.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 15, '#888', true);
        },
      },
      {
        title: 'Note morte',
        desc: 'Une note morte est jouée en étouffant complètement la corde — notée X.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          [0,1,2,3,4,5].forEach(i => {
            const y = top + i * sp;
            const x = [40, 60, 80, 100, 120, 140][i];
            ctx.fillStyle = '#fff'; ctx.beginPath(); ctx.ellipse(x, y, 8, 5, 0, 0, Math.PI * 2); ctx.fill();
            ctx.font = 'bold 10px Arial'; ctx.fillStyle = '#c62828'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
            ctx.fillText('X', x, y);
          });
        },
      },
      {
        title: 'Harmoniques naturelles',
        desc: 'Le losange signal une harmonique naturelle — le chiffre indique la frette effleurée.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          const x = 70;
          // Diamond
          ctx.strokeStyle = '#6a1b9a'; ctx.lineWidth = 1;
          ctx.fillStyle = '#fff';
          ctx.beginPath(); ctx.moveTo(x, y - 7); ctx.lineTo(x + 7, y); ctx.lineTo(x, y + 7); ctx.lineTo(x - 7, y); ctx.closePath(); ctx.fill(); ctx.stroke();
          ctx.font = '8px Arial'; ctx.fillStyle = '#6a1b9a'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('12', x, y);
          ctx.textBaseline = 'alphabetic';
        },
      },
      {
        title: 'Harmonique pincée',
        desc: 'L\'harmonique pincée est un cas particulier d\'harmonique affiché avec le marqueur P.H.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          const x = 50;
          ctx.strokeStyle = '#6a1b9a'; ctx.lineWidth = 1;
          ctx.fillStyle = '#fff';
          ctx.beginPath(); ctx.moveTo(x, y - 7); ctx.lineTo(x + 7, y); ctx.lineTo(x, y + 7); ctx.lineTo(x - 7, y); ctx.closePath(); ctx.fill(); ctx.stroke();
          ctx.font = '8px Arial'; ctx.fillStyle = '#6a1b9a'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('3', x, y); ctx.textBaseline = 'alphabetic';
          ctx.font = '7px Arial'; ctx.fillStyle = '#6a1b9a'; ctx.textAlign = 'left';
          ctx.fillText('P.H.', x + 10, y - 7);
          ctx.strokeStyle = '#6a1b9a'; ctx.lineWidth = 0.7; ctx.setLineDash([3, 2]);
          ctx.beginPath(); ctx.moveTo(x + 28, y - 4); ctx.lineTo(x + 90, y - 4); ctx.stroke();
          ctx.setLineDash([]);
        },
      },
      {
        title: 'Note accentuée',
        desc: 'Le symbole > accentue légèrement l\'attaque de la note.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 0);
          ctx.font = 'bold 13px Arial'; ctx.fillStyle = '#c62828'; ctx.textAlign = 'center';
          ctx.fillText('>', 80, y - 14);
        },
      },
      {
        title: 'Note fortement accentuée',
        desc: 'Le symbole ^ ou >> renforce l\'attaque de façon plus marquée.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 0);
          ctx.font = 'bold 13px Arial'; ctx.fillStyle = '#c62828'; ctx.textAlign = 'center';
          ctx.fillText('∧', 80, y - 14);
        },
      },
      {
        title: 'Staccato',
        desc: 'Un point au-dessus de la note indique une attaque courte et détachée.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 80, y, 0);
          ctx.fillStyle = '#333';
          ctx.beginPath(); ctx.arc(80, y - 13, 2, 0, Math.PI * 2); ctx.fill();
        },
      },
      {
        title: 'Polyphonie',
        desc: 'Des voix superposées peuvent partager le même système tout en gardant leurs propres attaques.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          const x = w / 2;
          [[0, 0], [1, 1], [2, 1], [3, 2], [4, 0], [5, 0]].forEach(([str, fret], i) => {
            if ([1,2,3].includes(i)) _lgNote(ctx, x, top + str * sp, fret);
          });
          _lgNote(ctx, x - 25, top, 0); _lgNote(ctx, x - 25, top + 4 * sp, 0);
        },
      },
    ],
  },
  {
    id: 'slides', title: 'Slides en entrée/sortie',
    items: [
      {
        title: 'Slide In',
        desc: 'Une diagonale entrante indique une arrivée glissée depuis une frette indéfinie.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 90, y, 9);
          ctx.strokeStyle = '#555'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(68, y + 7); ctx.lineTo(82, y); ctx.stroke();
        },
      },
      {
        title: 'Slide Out',
        desc: 'Une diagonale sortante indique une sortie glissée vers une frette indéfinie.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 3);
          const y = top + sp;
          _lgNote(ctx, 70, y, 11);
          ctx.strokeStyle = '#555'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(79, y); ctx.lineTo(93, y + 7); ctx.stroke();
        },
      },
    ],
  },
  {
    id: 'arpege', title: 'Coups et arpèges',
    items: [
      {
        title: 'Coup ascendant/descendant doux',
        desc: 'Les flèches indiquent le sens du balayage doux à travers les cordes.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          const xC = 55, xD = 105;
          // Up arrow
          ctx.strokeStyle = '#37474f'; ctx.lineWidth = 1.3;
          ctx.beginPath(); ctx.moveTo(xC, top + 5 * sp); ctx.lineTo(xC, top); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(xC - 4, top + 6); ctx.lineTo(xC, top); ctx.lineTo(xC + 4, top + 6); ctx.stroke();
          // Down arrow
          ctx.beginPath(); ctx.moveTo(xD, top); ctx.lineTo(xD, top + 5 * sp); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(xD - 4, top + 5 * sp - 6); ctx.lineTo(xD, top + 5 * sp); ctx.lineTo(xD + 4, top + 5 * sp - 6); ctx.stroke();
        },
      },
      {
        title: 'Arpège ascendant/descendant',
        desc: 'Les notes du chord sont jouées l\'une après l\'autre selon le sens de l\'arpège.',
        draw(ctx, w, h) {
          const { top, sp } = _lgStr(ctx, w, h, 6);
          const x = 80;
          [0,1,2,3,4,5].forEach(i => _lgNote(ctx, x, top + i * sp, [0,0,1,2,2,0][i]));
          // Zig-zag arrow representing arpeggio
          ctx.strokeStyle = '#1565c0'; ctx.lineWidth = 1.2;
          const ax = x - 18;
          ctx.beginPath();
          ctx.moveTo(ax, top + 5 * sp);
          for (let i = 4; i >= 0; i--) ctx.lineTo(ax + (i % 2 === 0 ? 3 : -3), top + i * sp);
          ctx.stroke();
          ctx.beginPath(); ctx.moveTo(ax - 3, top + 5); ctx.lineTo(ax, top); ctx.lineTo(ax + 3, top + 5); ctx.stroke();
        },
      },
    ],
  },
  {
    id: 'rythme', title: 'Notation rythmique',
    items: [
      {
        title: 'Notation rythmique',
        desc: 'Les hampes, ligatures et silences indiquent quand jouer et combien de temps tenir la note.',
        draw(ctx, w, h) {
          const my = h / 2 + 5;
          // quarter + eighth + sixteenth
          const notes = [
            { x: 30, flags: 0 }, { x: 70, flags: 1 }, { x: 110, flags: 2 },
          ];
          notes.forEach(({ x, flags }) => {
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 20); ctx.stroke();
            for (let f = 0; f < flags; f++) {
              ctx.beginPath(); ctx.moveTo(x, my - 20 + f * 5);
              ctx.quadraticCurveTo(x + 10, my - 16 + f * 5, x + 7, my - 10 + f * 5);
              ctx.stroke();
            }
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 3, 0, Math.PI * 2); ctx.fill();
          });
        },
      },
      {
        title: 'Le temps',
        desc: 'Le temps est la pulsation régulière sur laquelle se base le groupement rythmique.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          // whole, half, quarter at ascending heights
          [[30, 0], [80, 1], [130, 2]].forEach(([x, flags]) => {
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
            if (flags > 0) { ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 18); ctx.stroke(); }
            for (let f = 0; f < flags - 1; f++) {
              ctx.beginPath(); ctx.moveTo(x, my - 18 + f * 5);
              ctx.quadraticCurveTo(x + 10, my - 14 + f * 5, x + 6, my - 8 + f * 5); ctx.stroke();
            }
            ctx.fillStyle = flags === 0 ? '#fff' : '#333';
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1.2;
            ctx.beginPath(); ctx.ellipse(x, my, 6, 4.5, -0.2, 0, Math.PI * 2);
            if (flags === 0) { ctx.stroke(); } else { ctx.fill(); }
          });
        },
      },
      {
        title: 'Mesures',
        desc: 'Les mesures découpent la musique en blocs délimités par des barres verticales.',
        draw(ctx, w, h) {
          const my = h / 2;
          // 3 string lines + 2 barlines
          ctx.strokeStyle = '#888'; ctx.lineWidth = 0.5;
          [my - 12, my, my + 12].forEach(y => {
            ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
          });
          [45, 110].forEach(x => {
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1.5;
            ctx.beginPath(); ctx.moveTo(x, my - 12); ctx.lineTo(x, my + 12); ctx.stroke();
          });
          // some notes
          [25, 68, 80, 130].forEach(x => {
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 2.5, 0, Math.PI * 2); ctx.fill();
            ctx.strokeStyle = '#333'; ctx.lineWidth = 0.8;
            ctx.beginPath(); ctx.moveTo(x + 2, my); ctx.lineTo(x + 2, my - 12); ctx.stroke();
          });
        },
      },
      {
        title: 'Chiffrage de mesure',
        desc: 'La signature indique le nombre de temps et la valeur de base de chaque temps.',
        draw(ctx, w, h) {
          ctx.font = 'bold 24px Arial'; ctx.fillStyle = '#1a1a1a';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('4', w / 2, h / 2 - 10);
          ctx.fillText('4', w / 2, h / 2 + 10);
        },
      },
      {
        title: 'Notes et silences',
        desc: 'La durée relative des notes et des silences est rendue par la même grammaire rythmique.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          const col = '#333';
          // quarter note
          ctx.strokeStyle = col; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(35, my); ctx.lineTo(35, my - 18); ctx.stroke();
          ctx.fillStyle = col; ctx.beginPath(); ctx.arc(35, my, 3.5, 0, Math.PI * 2); ctx.fill();
          // quarter rest (zigzag)
          ctx.lineWidth = 1.2; ctx.lineCap = 'round'; ctx.lineJoin = 'round';
          ctx.beginPath();
          ctx.moveTo(72, my - 8); ctx.lineTo(68, my - 4); ctx.lineTo(72, my); ctx.lineTo(67, my + 4); ctx.lineTo(71, my + 8);
          ctx.stroke(); ctx.lineCap = 'butt'; ctx.lineJoin = 'miter';
          // dotted quarter
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(110, my); ctx.lineTo(110, my - 18); ctx.stroke();
          ctx.fillStyle = col; ctx.beginPath(); ctx.arc(110, my, 3.5, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(116, my - 3, 1.5, 0, Math.PI * 2); ctx.fill();
          // whole rest
          ctx.fillRect(138, my - 5, 12, 4);
          ctx.lineWidth = 0.6;
          ctx.beginPath(); ctx.moveTo(136, my - 5); ctx.lineTo(152, my - 5); ctx.stroke();
        },
      },
      {
        title: 'Ligatures',
        desc: 'Les petites valeurs sont regroupées par ligatures au-dessus de la tablature.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
          [25, 55, 85, 115].forEach(x => {
            ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 18); ctx.stroke();
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 3, 0, Math.PI * 2); ctx.fill();
          });
          // Beam
          ctx.fillStyle = '#333'; ctx.fillRect(25, my - 19, 90, 3);
        },
      },
      {
        title: 'Note pointée',
        desc: 'Un point ajoute la moitié de la durée de base à une note ou à un silence.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
          // dotted note
          ctx.beginPath(); ctx.moveTo(55, my); ctx.lineTo(55, my - 18); ctx.stroke();
          ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(55, my, 3.5, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(62, my - 3, 2, 0, Math.PI * 2); ctx.fill();
          // = sign
          ctx.font = '14px Arial'; ctx.fillStyle = '#666'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('=', 80, my - 8);
          // two 8ths
          [96, 112].forEach(x => {
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 18); ctx.stroke();
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 3, 0, Math.PI * 2); ctx.fill();
          });
          ctx.fillStyle = '#333'; ctx.fillRect(96, my - 19, 16, 3);
        },
      },
      {
        title: 'Note doublement pointée',
        desc: 'Deux points ajoutent successivement la moitié puis le quart de la durée.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(40, my); ctx.lineTo(40, my - 18); ctx.stroke();
          ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(40, my, 3.5, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(47, my - 3, 2, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(53, my - 3, 2, 0, Math.PI * 2); ctx.fill();
          ctx.font = '13px Arial'; ctx.fillStyle = '#666'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('=', 70, my - 8);
          // q + e + s
          [85, 101, 114].forEach((x, i) => {
            ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
            ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 18); ctx.stroke();
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 3, 0, Math.PI * 2); ctx.fill();
            for (let f = 0; f < i; f++) {
              ctx.beginPath(); ctx.moveTo(x, my - 18 + f * 5);
              ctx.quadraticCurveTo(x + 8, my - 14 + f * 5, x + 5, my - 8 + f * 5); ctx.stroke();
            }
          });
        },
      },
      {
        title: 'Liaisons (ties)',
        desc: 'Une liaison prolonge la durée d\'une note sur l\'attaque suivante sans duplique.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          _lgNote(ctx, 45, my, 9); _lgNote(ctx, 115, my, 9);
          ctx.strokeStyle = '#555'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(53, my); ctx.quadraticCurveTo(80, my - 12, 107, my); ctx.stroke();
        },
      },
      {
        title: 'Triolets',
        desc: 'Le chiffre 3 sous le groupe indique trois notes dans l\'espace de deux.',
        draw(ctx, w, h) {
          const my = h / 2 + 4;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
          [30, 65, 100].forEach(x => {
            ctx.beginPath(); ctx.moveTo(x, my); ctx.lineTo(x, my - 18); ctx.stroke();
            ctx.fillStyle = '#333'; ctx.beginPath(); ctx.arc(x, my, 3, 0, Math.PI * 2); ctx.fill();
          });
          ctx.fillStyle = '#333'; ctx.fillRect(30, my - 19, 70, 3);
          // bracket + 3
          ctx.strokeStyle = '#444'; ctx.lineWidth = 0.8;
          ctx.beginPath(); ctx.moveTo(30, my + 8); ctx.lineTo(30, my + 12); ctx.lineTo(100, my + 12); ctx.lineTo(100, my + 8); ctx.stroke();
          ctx.font = 'bold 9px Arial'; ctx.fillStyle = '#444'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('3', 65, my + 18);
        },
      },
      {
        title: 'Rythme swing',
        desc: 'Le swing transforme une subdivision régulière en alternance longue/courte.',
        draw(ctx, w, h) {
          ctx.font = 'italic 10px Arial'; ctx.fillStyle = '#444'; ctx.textAlign = 'left';
          ctx.fillText('Swing...', 10, h / 2 - 4);
          ctx.font = 'bold 10px Arial'; ctx.fillStyle = '#1a237e';
          ctx.fillText('8ths = triplet feel', 10, h / 2 + 12);
        },
      },
    ],
  },
  {
    id: 'structure', title: 'Structure',
    items: [
      {
        title: 'Reprises',
        desc: 'Les doubles barres avec points signalent un retour à une section précédente.',
        draw(ctx, w, h) {
          const my = h / 2;
          ctx.strokeStyle = '#888'; ctx.lineWidth = 0.5;
          [my - 12, my, my + 12].forEach(y => {
            ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
          });
          // start repeat :|
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(40, my - 14); ctx.lineTo(40, my + 14); ctx.stroke();
          ctx.lineWidth = 3;
          ctx.beginPath(); ctx.moveTo(44, my - 14); ctx.lineTo(44, my + 14); ctx.stroke();
          ctx.lineWidth = 1;
          ctx.fillStyle = '#333';
          ctx.beginPath(); ctx.arc(50, my - 4, 2, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(50, my + 4, 2, 0, Math.PI * 2); ctx.fill();
          // end repeat |:
          ctx.beginPath(); ctx.arc(110, my - 4, 2, 0, Math.PI * 2); ctx.fill();
          ctx.beginPath(); ctx.arc(110, my + 4, 2, 0, Math.PI * 2); ctx.fill();
          ctx.lineWidth = 3;
          ctx.beginPath(); ctx.moveTo(116, my - 14); ctx.lineTo(116, my + 14); ctx.stroke();
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(120, my - 14); ctx.lineTo(120, my + 14); ctx.stroke();
        },
      },
      {
        title: 'Fins alternatives',
        desc: 'Des crochets numérotés distinguent les sorties alternatives d\'une reprise.',
        draw(ctx, w, h) {
          const my = h / 2;
          ctx.strokeStyle = '#888'; ctx.lineWidth = 0.5;
          [my - 8, my + 8].forEach(y => {
            ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
          });
          // bracket 1
          ctx.strokeStyle = '#1a237e'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(15, my + 4); ctx.lineTo(15, my - 20); ctx.lineTo(65, my - 20); ctx.stroke();
          ctx.font = 'bold 9px Arial'; ctx.fillStyle = '#1a237e'; ctx.textAlign = 'left'; ctx.textBaseline = 'top';
          ctx.fillText('1.', 18, my - 19);
          // bracket 2
          ctx.beginPath(); ctx.moveTo(75, my - 20); ctx.lineTo(140, my - 20); ctx.lineTo(140, my + 4); ctx.stroke();
          ctx.fillText('2.', 78, my - 19);
          ctx.textBaseline = 'alphabetic';
        },
      },
      {
        title: 'Anacrouse',
        desc: 'Une mesure incomplète d\'entrée ou de sortie ne doit pas être marquée comme erreur.',
        draw(ctx, w, h) {
          const my = h / 2;
          ctx.strokeStyle = '#888'; ctx.lineWidth = 0.5;
          [my - 10, my + 10].forEach(y => {
            ctx.beginPath(); ctx.moveTo(10, y); ctx.lineTo(w - 10, y); ctx.stroke();
          });
          ctx.font = 'italic 8px Arial'; ctx.fillStyle = '#888'; ctx.textAlign = 'left';
          ctx.fillText('pickup bar', 12, my - 14);
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(60, my - 10); ctx.lineTo(60, my + 10); ctx.stroke();
          // arc bow for pickup
          ctx.lineWidth = 1;
          ctx.beginPath(); ctx.moveTo(15, my + 10); ctx.quadraticCurveTo(37, my + 20, 58, my + 10); ctx.stroke();
        },
      },
    ],
  },
  {
    id: 'dynamiques', title: 'Dynamiques',
    items: [
      {
        title: 'Dynamiques',
        desc: 'Les indications mf, f, ff ou pp décrivent l\'intensité souhaitée.',
        draw(ctx, w, h) {
          const items = [['pp','#1565c0'],['p','#1976d2'],['mp','#388e3c'],['mf','#f57c00'],['f','#e65100'],['ff','#b71c1c']];
          items.forEach(([s, c], i) => {
            ctx.font = 'bold italic 10px serif'; ctx.fillStyle = c; ctx.textAlign = 'left';
            const row = Math.floor(i / 3), col = i % 3;
            ctx.fillText(s, 15 + col * 48, 18 + row * 26);
          });
        },
      },
      {
        title: 'Crescendo',
        desc: 'Un coin ouvert indique une montée progressive d\'intensité.',
        draw(ctx, w, h) {
          const my = h / 2;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(25, my); ctx.lineTo(130, my - 12); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(25, my); ctx.lineTo(130, my + 12); ctx.stroke();
        },
      },
      {
        title: 'Diminuendo',
        desc: 'Un coin fermé indique une baisse progressive d\'intensité.',
        draw(ctx, w, h) {
          const my = h / 2;
          ctx.strokeStyle = '#333'; ctx.lineWidth = 1.5;
          ctx.beginPath(); ctx.moveTo(25, my - 12); ctx.lineTo(130, my); ctx.stroke();
          ctx.beginPath(); ctx.moveTo(25, my + 12); ctx.lineTo(130, my); ctx.stroke();
        },
      },
    ],
  },
  {
    id: 'doigtes', title: 'Doigtés main gauche',
    items: [
      {
        title: 'Index (1)',
        desc: 'Disque jaune ambré. Le chiffre indique la case à jouer.',
        draw(ctx, w, h) {
          const cs = getComputedStyle(document.documentElement);
          const col = cs.getPropertyValue('--f1').trim() || '#c8a820';
          ctx.fillStyle = col;
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.fill();
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#333';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('5', w / 2, h / 2 + 0.5);
        },
      },
      {
        title: 'Majeur (2)',
        desc: 'Disque vert. Deuxième doigt de la main gauche.',
        draw(ctx, w, h) {
          const cs = getComputedStyle(document.documentElement);
          const col = cs.getPropertyValue('--f2').trim() || '#60c060';
          ctx.fillStyle = col;
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.fill();
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#333';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('7', w / 2, h / 2 + 0.5);
        },
      },
      {
        title: 'Annulaire (3)',
        desc: 'Disque bleu. Troisième doigt de la main gauche.',
        draw(ctx, w, h) {
          const cs = getComputedStyle(document.documentElement);
          const col = cs.getPropertyValue('--f3').trim() || '#6090e0';
          ctx.fillStyle = col;
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.fill();
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#333';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('9', w / 2, h / 2 + 0.5);
        },
      },
      {
        title: 'Auriculaire (4)',
        desc: 'Disque magenta. Quatrième doigt (petit doigt) de la main gauche.',
        draw(ctx, w, h) {
          const cs = getComputedStyle(document.documentElement);
          const col = cs.getPropertyValue('--f4').trim() || '#c060c0';
          ctx.fillStyle = col;
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.fill();
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#333';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('10', w / 2, h / 2 + 0.5);
        },
      },
      {
        title: 'Corde à vide (0)',
        desc: 'Disque blanc — pas de doigt appuyé, corde jouée à vide.',
        draw(ctx, w, h) {
          ctx.fillStyle = '#ffffff';
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.fill();
          ctx.strokeStyle = '#bbb'; ctx.lineWidth = 1;
          ctx.beginPath(); ctx.ellipse(w / 2, h / 2, 13, 9, 0, 0, Math.PI * 2); ctx.stroke();
          ctx.font = 'bold 11px Arial'; ctx.fillStyle = '#333';
          ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
          ctx.fillText('0', w / 2, h / 2 + 0.5);
        },
      },
    ],
  },
];

/**
 * Build the full legend as HTML cards with mini-canvas previews into `container`.
 * Called once and cached by main.js.
 * @param {HTMLElement} container
 */
export function buildLegendHTML(container) {
  container.innerHTML = '';

  // Build flat TOC sidebar
  const layout = document.createElement('div');
  layout.style.cssText = 'display:flex;gap:20px;align-items:flex-start;';

  const toc = document.createElement('nav');
  toc.style.cssText = 'min-width:140px;position:sticky;top:10px;background:#f5f5f5;border-radius:6px;padding:10px 12px;font-size:12px;line-height:1.9;';
  const tocTitle = document.createElement('div');
  tocTitle.style.cssText = 'font-weight:700;font-size:11px;color:#666;text-transform:uppercase;letter-spacing:.5px;margin-bottom:6px;';
  tocTitle.textContent = 'Sections';
  toc.appendChild(tocTitle);

  const main = document.createElement('div');
  main.style.cssText = 'flex:1;min-width:0;';

  for (const section of _LG_SECTIONS) {
    // TOC link
    const a = document.createElement('a');
    a.href = `#lg-${section.id}`;
    a.style.cssText = 'display:block;color:#1a237e;text-decoration:none;padding:1px 0;';
    a.textContent = section.title;
    a.addEventListener('mouseenter', () => (a.style.textDecoration = 'underline'));
    a.addEventListener('mouseleave', () => (a.style.textDecoration = 'none'));
    toc.appendChild(a);

    // Section heading
    const h3 = document.createElement('h3');
    h3.id = `lg-${section.id}`;
    h3.style.cssText = 'font-size:14px;font-weight:700;color:#1a237e;border-bottom:2px solid #c5cae9;padding-bottom:4px;margin:18px 0 10px;scroll-margin-top:8px;';
    h3.textContent = section.title;
    main.appendChild(h3);

    // Grid of cards — 3 per row
    const grid = document.createElement('div');
    grid.style.cssText = 'display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-bottom:6px;';

    for (const item of section.items) {
      const card = document.createElement('div');
      card.style.cssText = 'background:#fff;border:1px solid #e0e0e0;border-radius:6px;padding:8px;box-shadow:0 1px 3px rgba(0,0,0,.06);';

      // Mini canvas preview
      const preview = _makeMiniCanvas(item.draw);
      preview.style.width = '100%';
      preview.style.height = '64px';
      card.appendChild(preview);

      // Title
      const title = document.createElement('div');
      title.style.cssText = 'font-weight:700;font-size:12px;margin:5px 0 2px;color:#1a1a1a;';
      title.textContent = item.title;
      card.appendChild(title);

      // Description
      const desc = document.createElement('div');
      desc.style.cssText = 'font-size:11px;color:#555;line-height:1.4;';
      desc.textContent = item.desc;
      card.appendChild(desc);

      grid.appendChild(card);
    }
    main.appendChild(grid);
  }

  layout.appendChild(toc);
  layout.appendChild(main);
  container.appendChild(layout);
}

/** Legacy stub kept for backward compatibility. */
export function renderLegend(canvas) {
  // No-op: legend now uses buildLegendHTML()
}
