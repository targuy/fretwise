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

// ── Layout constants (px at 1× DPR) ────────────────────────────────
const MARGIN_L = 60;          // left margin (TAB label + string names)
const MARGIN_R = 20;
const MARGIN_T = 12;
const STRING_SPACING = 16;    // distance between strings
const NUM_STRINGS = 6;
const STRINGS_H = (NUM_STRINGS - 1) * STRING_SPACING; // 80px
const STRING_NAMES = ['e', 'B', 'G', 'D', 'A', 'E'];

// System vertical layout
const ABOVE_STRINGS = 80;     // space above string 1 (tempo, chord, section, stems)
const BELOW_STRINGS = 55;     // space below string 6 (rhythm, lyrics)
const SYSTEM_H = ABOVE_STRINGS + STRINGS_H + BELOW_STRINGS;
const INTER_SYSTEM = 16;

// Note rendering
const NOTE_RX = 8;            // oval x radius
const NOTE_RY = 5.5;          // oval y radius
const COL_STEP = 30;          // fixed px between consecutive note columns
const LEFT_PAD = 14;          // left pad in measure
const RIGHT_PAD = 8;          // right pad in measure

// Stem / rhythm (below tab)
const STEM_GAP = 4;
const STEM_H = 18;
const BEAM_H = 3;
const BEAM_GAP_Y = 4;

// Colors (Songsterr palette)
const COL_STRING     = '#999999';
const COL_STRING_LW  = 0.8;
const COL_TEXT        = '#222222';
const COL_FRET        = '#222222';
const COL_GREY        = '#888888';
const COL_GREEN       = '#4caf50';
const COL_CHORD       = '#222222';
const COL_SECTION     = '#222222';
const COL_BEND        = '#cc1111';
const COL_VIBRATO     = '#2a8a2a';
const COL_LET_RING    = '#5577cc';
const COL_PM          = '#555555';
const COL_HP_ARC      = '#555555';
const COL_TAPPING     = '#2255cc';
const COL_FINGER      = '#cc1111';
const COL_HARMONIC    = '#996600';
const COL_SLIDE       = '#444444';
const COL_ACCENT      = '#cc1111';
const COL_MUTED       = '#222222';
const COL_MEASURE_NUM = '#aaaaaa';
const COL_CURSOR      = 'rgba(76, 175, 80, 0.12)';
const COL_CURSOR_LINE = '#4caf50';

// Fonts
const FONT_FRET       = 'bold 11px Arial';
const FONT_FRET_SM    = 'bold 10px Arial';
const FONT_STRING     = '11px Arial';
const FONT_TAB        = 'bold 13px Arial';
const FONT_CHORD      = 'bold 12px Arial';
const FONT_SECTION    = 'italic bold 11px Arial';
const FONT_TEMPO      = '10px Arial';
const FONT_MNUM       = '9px Arial';
const FONT_FINGER     = 'bold 8px Arial';
const FONT_SYMBOL     = '10px Arial';
const FONT_SYMBOL_SM  = '9px Arial';
const FONT_DYNAMIC    = 'italic bold 11px Arial';
const FONT_LEGEND_H   = 'bold 14px Arial';
const FONT_LEGEND     = '12px Arial';

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
 * @property {boolean} muted
 * @property {boolean} palm_muted
 * @property {boolean} tapping
 * @property {boolean} accent
 * @property {boolean} accent_strong
 * @property {boolean} tremolo_picking
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
    this.tempo = data.tempo || 120;
    this.sectionMarkers = data.section_markers || {};
    this.chordDiagrams = data.chord_diagrams || [];
    this.chordMarkers = data.chord_markers || {};  // onset_str → chord name from file
    this.dpr = window.devicePixelRatio || 1;

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
    const bpm = this.bpm;
    const measures = [];
    let curBucket = [];
    let curStart = 0;
    for (const n of this.results) {
      while (n.onset >= curStart + bpm - 0.001) {
        measures.push(curBucket);
        curBucket = [];
        curStart += bpm;
      }
      curBucket.push(n);
    }
    if (curBucket.length) measures.push(curBucket);
    this.measures = measures;
  }

  _buildSystems() {
    const measures = this.measures;
    if (!measures.length) return;
    const availW = this.systemWidth - MARGIN_L - MARGIN_R;

    // Measure width = LEFT_PAD + nCols * COL_STEP + RIGHT_PAD (fixed step)
    const measureWidth = (notes) => {
      if (!notes.length) return LEFT_PAD + COL_STEP + RIGHT_PAD; // empty = 1 column
      const nCols = new Set(notes.map(n => n.onset.toFixed(6))).size;
      return LEFT_PAD + nCols * COL_STEP + RIGHT_PAD;
    };

    const systems = [];
    let cur = [];
    let curW = 0;
    for (let i = 0; i < measures.length; i++) {
      const w = measureWidth(measures[i]);
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
      startMeasure: s[0].idx,
    }));
  }

  // ── System drawing ────────────────────────────────────────────────

  _drawSystem(ctx, sys, sysY, canvasW) {
    const strY = (si) => sysY + ABOVE_STRINGS + si * STRING_SPACING;
    const x0 = MARGIN_L;
    const xEnd = x0 + sys.widths.reduce((a, b) => a + b, 0);

    // ── TAB label + string names
    ctx.font = FONT_TAB;
    ctx.fillStyle = COL_TEXT;
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
      const absMeasure = sys.startMeasure + mi;
      const measureNum = absMeasure + 1; // 1-based

      // Section marker
      const sectionLabel = this.sectionMarkers[String(measureNum)];
      if (sectionLabel) {
        ctx.font = FONT_SECTION;
        ctx.fillStyle = COL_SECTION;
        ctx.textAlign = 'left';
        ctx.fillText(sectionLabel, mX + 4, sysY + 22);
      }

      // Chord name (first note's onset → check for chord recognition)
      this._drawChordName(ctx, mNotes, mX, mW, sysY);

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
      this._drawMeasureNotes(ctx, mNotes, mX, mW, sysY);

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

  _drawMeasureNotes(ctx, notes, mX, mW, sysY) {
    if (!notes.length) {
      // Draw whole rest
      this._drawRest(ctx, mX + LEFT_PAD + COL_STEP / 2, sysY, 4.0);
      return;
    }

    // Group by onset into columns (one column per unique onset)
    const onsetMap = new Map();
    for (const n of notes) {
      const key = n.onset.toFixed(6);
      if (!onsetMap.has(key)) onsetMap.set(key, []);
      onsetMap.get(key).push(n);
    }

    // Sort onsets → assign fixed x per column index
    const sortedKeys = [...onsetMap.keys()].sort((a, b) => parseFloat(a) - parseFloat(b));

    const notePositions = [];
    sortedKeys.forEach((key, colIdx) => {
      const nx = mX + LEFT_PAD + colIdx * COL_STEP;
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

    // Second pass: finger annotations drawn on top of all note ovals
    const fingerMaxX = mX + mW - 8;  // 8px buffer before barline
    for (const { note, x, y } of notePositions) {
      this._drawFingerAnnotation(ctx, note, x, y, fingerMaxX);
    }

    // Draw dynamic marking once per measure column (only on change)
    for (const key of sortedKeys) {
      const col = onsetMap.get(key)[0];
      if (col.dynamic && col.dynamic !== this._lastDynamic) {
        this._lastDynamic = col.dynamic;
        const colIdx = sortedKeys.indexOf(key);
        const dx = mX + LEFT_PAD + colIdx * COL_STEP;
        ctx.font = FONT_DYNAMIC;
        ctx.fillStyle = COL_GREY;
        ctx.textAlign = 'center';
        ctx.fillText(col.dynamic, dx, sysY + ABOVE_STRINGS + STRINGS_H + 47);
      }
    }

    // Draw rhythm below
    this._drawRhythm(ctx, notePositions, sysY, mX, mW);
  }

  // ── Single note rendering ─────────────────────────────────────────

  _drawNote(ctx, note, x, y, sysY) {
    const fret = note.fret;
    const isMuted = note.muted;
    const isHarmonic = !!note.harmonic_type;

    // ── White oval (erases string line)
    const label = note.ghost ? `(${fret})` : String(fret);
    const ovalRX = label.length > 1 ? NOTE_RX + 3 : NOTE_RX;

    if (isHarmonic) {
      this._drawDiamond(ctx, x, y, ovalRX, NOTE_RY);
    } else {
      // White background oval
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.ellipse(x, y, ovalRX + 1, NOTE_RY + 1, 0, 0, Math.PI * 2);
      ctx.fill();
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
      ctx.fillStyle = COL_FRET;
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

    // Palm mute "P.M."
    if (note.palm_muted) {
      ctx.font = FONT_SYMBOL_SM;
      ctx.fillStyle = COL_PM;
      ctx.textAlign = 'center';
      ctx.fillText('P.M.', x, sysY + ABOVE_STRINGS + STRINGS_H + 14);
    }

    // Let ring dashes
    if (note.let_ring) {
      // Scale dashes to the note's duration
      const dashLen = Math.max(12, Math.min(50, note.duration * 20));
      ctx.strokeStyle = COL_LET_RING;
      ctx.lineWidth = 0.8;
      ctx.setLineDash([3, 2]);
      ctx.beginPath();
      ctx.moveTo(x + ovalRX + 2, y);
      ctx.lineTo(x + ovalRX + dashLen, y);
      ctx.stroke();
      ctx.setLineDash([]);

      // "let ring" label
      ctx.font = '7px Arial';
      ctx.fillStyle = COL_LET_RING;
      ctx.textAlign = 'left';
      ctx.fillText('let ring', x + ovalRX + 2, y - 6);
    }

    // Bend arrow
    if (note.bend_value) {
      this._drawBend(ctx, x, y, note.bend_value, note.bend_type);
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

    // Finger annotation (SW of oval, dark red) — rendered in a second pass
    // by _drawFingerAnnotation() to avoid being overwritten by lower-string ovals.

    // Dynamic marking: rendered by _drawMeasureNotes, not per-note.
    // (removed from here to avoid showing on every note)
  }

  /** Draw finger annotation (second pass so it's always visible on top). */
  _drawFingerAnnotation(ctx, note, x, y, maxX = Infinity) {
    const fret = note.fret;
    if (!note.finger || note.finger === 'open' || fret <= 0) return;
    const fingerChar = { index: 'i', middle: 'm', ring: 'r', pinky: 'p' }[note.finger] || '';
    if (!fingerChar) return;
    const ovalRX = String(fret).length > 1 ? NOTE_RX + 3 : NOTE_RX;
    const annoX = x + ovalRX + 2;
    if (annoX > maxX) return;  // would collide with/overflow past barline
    ctx.font = FONT_FINGER;
    ctx.fillStyle = COL_FINGER;
    ctx.textAlign = 'left';
    ctx.textBaseline = 'alphabetic';
    // Place to the lower-right of the oval — avoids overwriting by adjacent strings
    ctx.fillText(fingerChar, annoX, y + NOTE_RY + 7);
    ctx.textBaseline = 'middle';
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

  _drawBend(ctx, x, y, bendValue, bendType) {
    const arrowH = 22;
    const tipY = y - NOTE_RY - arrowH;
    const isPre = bendType === 'pre_bend' || bendType === 'pre_bend_release';

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

    // Label
    let label;
    if (bendValue <= 0.5) label = '½';
    else if (bendValue <= 1.0) label = '1';
    else if (bendValue <= 1.5) label = '1½';
    else label = '2';

    if (isPre) label = '(' + label + ')';

    ctx.font = 'bold 9px Arial';
    ctx.textAlign = 'center';
    ctx.fillText(label, x, tipY - 3);
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

      // Hammer-on / Pull-off arcs
      if ((note.articulation === 'hammer_on' || note.articulation === 'pull_off') && nextOnSameString) {
        const { x: nx, y: ny } = nextOnSameString;
        const label = note.articulation === 'hammer_on' ? 'H' : 'P';
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

  _drawChordName(ctx, notes, mX, mW, sysY) {
    if (!notes.length) return;

    // Build onset→group map
    const onsetMap = new Map();
    for (const n of notes) {
      const key = n.onset.toFixed(6);
      if (!onsetMap.has(key)) onsetMap.set(key, []);
      onsetMap.get(key).push(n);
    }
    const sortedKeys = [...onsetMap.keys()].sort((a, b) => parseFloat(a) - parseFloat(b));

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
        const nx = mX + LEFT_PAD + colIdx * COL_STEP;
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

  _drawRhythm(ctx, notePositions, sysY, mX = 0, mW = Infinity) {
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
      cols.push({ x, duration: dur, onset: parseFloat(key) });
    }
    cols.sort((a, b) => a.onset - b.onset);

    // Determine beat boundaries for this set of notes
    const bpm = this.bpm;
    let measureOnset = 0;
    if (cols.length > 0) {
      measureOnset = Math.floor(cols[0].onset / bpm) * bpm;
    }

    // Draw stems
    for (const col of cols) {
      if (col.duration >= 4.0) continue; // whole note: no stem

      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = 0.9;
      ctx.beginPath();
      ctx.moveTo(col.x, baseY);
      ctx.lineTo(col.x, baseY + STEM_H);
      ctx.stroke();

      // Dotted note: augmentation dot next to stem base
      if (this._isDotted(col.duration)) {
        ctx.fillStyle = COL_TEXT;
        ctx.beginPath();
        ctx.arc(col.x + 4, baseY + STEM_H - 2, 1.3, 0, Math.PI * 2);
        ctx.fill();
      }
    }

    // Beat-aware beams
    this._drawBeams(ctx, cols, baseY, measureOnset);

    // Flags for unbeamed notes (drawn after beams to know which are beamed)
    const beamedOnsets = this._getBeamedOnsets(cols, measureOnset);
    for (const col of cols) {
      const nFlags = this._numFlags(col.duration);
      if (nFlags > 0 && !beamedOnsets.has(col.onset.toFixed(4))) {
        for (let fi = 0; fi < nFlags; fi++) {
          this._drawFlag(ctx, col.x, baseY + STEM_H, fi);
        }
      }
    }

    // ── Rest symbols for gaps within the measure ──────────────────────
    const measureEnd = measureOnset + this.bpm;
    const rightBound = mX + mW - RIGHT_PAD - 4;
    for (let i = 0; i <= cols.length; i++) {
      const gapStart = i === 0 ? measureOnset
        : cols[i - 1].onset + cols[i - 1].duration;
      const gapEnd   = i === cols.length ? measureEnd : cols[i].onset;
      const gapDur   = gapEnd - gapStart;
      if (gapDur < 0.12) continue;  // too small (< 1/32 beat) — skip

      let restX;
      if (i === 0) {
        // Leading rest: place before first note
        restX = cols.length > 0 ? cols[0].x - COL_STEP * 0.6 : mX + LEFT_PAD;
      } else if (i === cols.length) {
        // Trailing rest: place after last note
        restX = cols[cols.length - 1].x + COL_STEP;
      } else {
        // Mid-measure rest: midpoint between surrounding note columns
        restX = (cols[i - 1].x + cols[i].x) / 2;
      }
      // Clamp to measure boundaries
      if (restX < mX + LEFT_PAD || restX > rightBound) continue;
      this._drawRhythmRest(ctx, restX, baseY, gapDur);
    }
  }

  // ── Rest symbol in the rhythm zone (below tab, at stem level) ─────

  _drawRhythmRest(ctx, x, baseY, duration) {
    // Place rest at mid-stem height so it aligns visually with stems
    const y = baseY + STEM_H * 0.45;
    ctx.fillStyle = COL_TEXT;
    ctx.strokeStyle = COL_TEXT;

    if (duration >= 1.0) {
      // Quarter rest: small zigzag
      ctx.lineWidth = 1.4;
      ctx.lineCap = 'round';
      ctx.lineJoin = 'round';
      ctx.beginPath();
      ctx.moveTo(x + 2, y - 5);
      ctx.lineTo(x - 1, y - 2);
      ctx.lineTo(x + 1, y + 1);
      ctx.lineTo(x - 2, y + 4);
      ctx.lineTo(x + 1, y + 7);
      ctx.stroke();
      ctx.lineCap = 'butt'; ctx.lineJoin = 'miter';
    } else if (duration >= 0.5) {
      // Eighth rest: diagonal stroke + dot
      ctx.lineWidth = 1.2;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x + 2, y - 4);
      ctx.lineTo(x - 2, y + 5);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x + 2, y - 4, 1.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineCap = 'butt';
    } else {
      // Sixteenth rest: diagonal stroke + two dots
      ctx.lineWidth = 1.2;
      ctx.lineCap = 'round';
      ctx.beginPath();
      ctx.moveTo(x + 2, y - 5);
      ctx.lineTo(x - 2, y + 6);
      ctx.stroke();
      ctx.beginPath();
      ctx.arc(x + 2, y - 5, 1.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.beginPath();
      ctx.arc(x, y, 1.7, 0, Math.PI * 2);
      ctx.fill();
      ctx.lineCap = 'butt';
    }
  }

  _numFlags(duration) {
    if (duration >= 1.0) return 0;
    if (duration >= 0.5) return 1;
    if (duration >= 0.25) return 2;
    return 3;
  }

  _drawFlag(ctx, x, stemEnd, flagIdx) {
    ctx.strokeStyle = COL_TEXT;
    ctx.lineWidth = 1.0;
    const fy = stemEnd - flagIdx * 4;
    ctx.beginPath();
    ctx.moveTo(x, fy);
    ctx.quadraticCurveTo(x + 8, fy + 4, x + 3, fy + 10);
    ctx.stroke();
  }

  _drawBeams(ctx, cols, baseY, measureOnset) {
    if (cols.length < 2) return;
    const groups = this._computeBeamGroups(cols, measureOnset);

    // Draw primary beam for each group
    for (const group of groups) {
      const y = baseY + STEM_H;
      ctx.strokeStyle = COL_TEXT;
      ctx.lineWidth = BEAM_H;
      ctx.beginPath();
      ctx.moveTo(group[0].x, y);
      ctx.lineTo(group[group.length - 1].x, y);
      ctx.stroke();

      // Secondary beam: partial, only over runs of 16th notes
      let runStart = null;
      let runEnd = null;
      for (const col of group) {
        if (col.duration < 0.5) {
          if (runStart === null) runStart = col.x;
          runEnd = col.x;
        } else {
          if (runStart !== null && runEnd !== null && runEnd > runStart) {
            ctx.lineWidth = BEAM_H;
            ctx.beginPath();
            ctx.moveTo(runStart, y + BEAM_GAP_Y);
            ctx.lineTo(runEnd, y + BEAM_GAP_Y);
            ctx.stroke();
          }
          runStart = null;
          runEnd = null;
        }
      }
      // Flush trailing run
      if (runStart !== null && runEnd !== null && runEnd > runStart) {
        ctx.lineWidth = BEAM_H;
        ctx.beginPath();
        ctx.moveTo(runStart, y + BEAM_GAP_Y);
        ctx.lineTo(runEnd, y + BEAM_GAP_Y);
        ctx.stroke();
      }
    }
  }

  /** Compute beam groups respecting beat boundaries and rests */
  _computeBeamGroups(cols, measureOnset) {
    const bpm = this.bpm;
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
      if (col.duration >= 1.0) {
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
  _getBeamedOnsets(cols, measureOnset) {
    const groups = this._computeBeamGroups(cols, measureOnset);
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
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(x, ry + 2.5, 8, 0, Math.PI * 2);
      ctx.fill();
      // Filled rectangle
      ctx.fillStyle = COL_TEXT;
      ctx.fillRect(x - 6, ry, 12, 5);
    } else if (duration >= 2.0) {
      // ── Half rest: filled rectangle sitting on string 3
      const ry = sysY + ABOVE_STRINGS + 2 * STRING_SPACING;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(x, ry - 2.5, 8, 0, Math.PI * 2);
      ctx.fill();
      ctx.fillStyle = COL_TEXT;
      ctx.fillRect(x - 6, ry - 5, 12, 5);
    } else if (duration >= 1.0) {
      // ── Quarter rest: drawn as zigzag path (standard notation)
      ctx.fillStyle = '#ffffff';
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
      ctx.fillStyle = '#ffffff';
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
      ctx.fillStyle = '#ffffff';
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

