/**
 * fretboard-diagram.js — shared inline-SVG fretboard renderers.
 *
 * `chordDiagramSVG` was originally private to main.js (chord-bar popups);
 * it's exported here so the training module can reuse it verbatim.
 * `scaleDiagramSVG` follows the same visual language for scale boxes.
 */

function _escapeHtml(str) {
  const el = document.createElement('span');
  el.textContent = str;
  return el.innerHTML;
}

function _toRoman(n) {
  const pairs = [[10, 'X'], [9, 'IX'], [8, 'VIII'], [7, 'VII'], [6, 'VI'],
                 [5, 'V'], [4, 'IV'], [3, 'III'], [2, 'II'], [1, 'I']];
  let r = '';
  for (const [v, s] of pairs) while (n >= v) { r += s; n -= v; }
  return r;
}

/**
 * Returns an inline SVG string for a chord diagram.
 * @param {object} cd  Chord diagram data (name, frets, fingers, base_fret, string_count)
 * @param {number} sc  Scale factor (1 = strip size, ~1.9 = popup size)
 */
export function chordDiagramSVG(cd, sc = 1) {
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
    text-anchor="middle" fill="#222">${_escapeHtml(cd.name)}</text>`;

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

// ── Scale box diagram (horizontal fretboard) ────────────────────────────────

// Row order is the tab convention used throughout the app: high e on top,
// low E at the bottom. Index = string_num - 1.
const _STRING_LABELS = ['e', 'B', 'G', 'D', 'A', 'E'];

// Open-string pitch class per string_num (standard tuning E2 A2 D3 G3 B3 E4).
const _OPEN_PC = { 1: 4, 2: 11, 3: 7, 4: 2, 5: 9, 6: 4 };
const _PC_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

// Conventional fretboard inlay markers.
const _SINGLE_INLAYS = new Set([3, 5, 7, 9, 15, 17, 19, 21]);
const _DOUBLE_INLAYS = new Set([12, 24]);

export const FINGER_LABELS = {
  1: 'index', 2: 'majeur', 3: 'annulaire', 4: 'auriculaire',
};

/** Note name produced by a (string, fret) pair in standard tuning. */
export function noteNameAt(stringNum, fret) {
  return _PC_NAMES[((_OPEN_PC[stringNum] ?? 4) + fret) % 12];
}

// Open-string MIDI pitch per string_num, standard tuning.
const _OPEN_MIDI = { 1: 64, 2: 59, 3: 55, 4: 50, 5: 45, 6: 40 };

/** Sounding MIDI pitch of a (string, fret) pair in standard tuning. */
export function midiAt(stringNum, fret) {
  return (_OPEN_MIDI[stringNum] ?? 40) + fret;
}

// Pitch class → [letter index within C D E F G A B, accidental].
// Sharp spelling throughout: correct for sharp keys, and a readable
// approximation for flat ones (Bb prints as A#).
const _PC_TO_STEP = [
  [0, ''], [0, '#'], [1, ''], [1, '#'], [2, ''], [3, ''],
  [3, '#'], [4, ''], [4, '#'], [5, ''], [5, '#'], [6, ''],
];

// Diatonic step index of E4, the bottom line of a treble staff.
// MIDI 64 → octave 4, letter E (index 2) → 4 * 7 + 2.
const _E4_STEP = 30;
const _TOP_LINE_STEP = 38;  // F5

/** Diatonic staff step and accidental for a MIDI pitch. */
function _staffStep(midi) {
  const [letter, accidental] = _PC_TO_STEP[midi % 12];
  const octave = Math.floor(midi / 12) - 1;
  return { step: octave * 7 + letter, accidental };
}

/** One finger per fret: 0→index, 1→middle, 2→ring, 3+→pinky. */
function _fingerForOffset(rel) {
  return rel <= 0 ? 1 : rel === 1 ? 2 : rel === 2 ? 3 : 4;
}

/**
 * Suggested left-hand finger for each note of a scale box.
 *
 * Boxes from the backend are positional — one fret window held across all six
 * strings — so fingering is one finger per fret measured from the box's hand
 * position, uniformly. Anchoring per string instead would contradict the hand
 * position: on a box held at fret 3, a string whose lowest note is fret 4
 * takes the middle finger, not the index.
 *
 * @param {Array<{string:number,fret:number}>} notes
 * @returns {Map<string, number>} key `${string}:${fret}` → finger 1–4 (0 = open)
 */
export function scaleBoxFingers(notes) {
  const fretted = notes.filter(n => n.fret > 0);
  const out = new Map();
  for (const n of notes) if (n.fret <= 0) out.set(`${n.string}:${n.fret}`, 0);
  if (!fretted.length) return out;

  const handPos = Math.min(...fretted.map(n => n.fret));
  for (const n of fretted) {
    out.set(`${n.string}:${n.fret}`, _fingerForOffset(n.fret - handPos));
  }
  return out;
}

/**
 * Returns an inline SVG string for a scale box, drawn as a horizontal
 * fretboard (strings as rows, frets as columns) — the orientation used by
 * the app's tablature, so a box reads the same way round as the score.
 *
 * @param {object} box    {name, min_fret, max_fret, notes:[{string,fret,is_root}]}
 * @param {number} sc     Scale factor (1 = default size)
 * @param {object} [opts] {labels: 'fingers'|'notes'} — what to print in each dot
 */
export function scaleDiagramSVG(box, sc = 1, opts = {}) {
  const labelMode = opts.labels === 'notes' ? 'notes' : 'fingers';

  const startFret = Math.max(box.min_fret, 1);
  const endFret   = Math.max(box.max_fret, startFret);
  const nCols     = endFret - startFret + 1;
  const hasOpen   = box.notes.some(n => n.fret === 0);

  const colW   = Math.round(34 * sc);
  const rowH   = Math.round(24 * sc);
  const dotR   = Math.round(9  * sc);
  const padL   = Math.round(20 * sc);   // string-name gutter
  const openW  = hasOpen ? Math.round(26 * sc) : 0;
  const padT   = Math.round(14 * sc);
  const padB   = Math.round(26 * sc);   // fret-number strip
  const padR   = Math.round(12 * sc);

  const nutX  = padL + openW;                     // first fret wire / nut
  const gridW = nCols * colW;
  const svgW  = nutX + gridW + padR;
  const svgH  = padT + 5 * rowH + padB;

  const rowY  = j => padT + j * rowH;                              // j = string - 1
  const colX  = f => nutX + (f - startFret) * colW + colW / 2;     // centre of a fret space

  const fingers = scaleBoxFingers(box.notes);
  const dotFill = f => (f >= 1 && f <= 4) ? `var(--f${f})` : 'var(--bg-3)';

  const txt = Math.max(8, Math.round(9.5 * sc));
  const lbl = Math.max(8, Math.round(9 * sc));

  let p = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}"
    xmlns="http://www.w3.org/2000/svg" style="display:block">`;

  // Inlay markers first, so strings and dots draw over them.
  const midY = (rowY(2) + rowY(3)) / 2;
  for (let f = startFret; f <= endFret; f++) {
    const x = colX(f);
    if (_DOUBLE_INLAYS.has(f)) {
      p += `<circle cx="${x}" cy="${rowY(1)}" r="${dotR * 0.42}" fill="var(--line-1)" opacity="0.55"/>`;
      p += `<circle cx="${x}" cy="${rowY(4)}" r="${dotR * 0.42}" fill="var(--line-1)" opacity="0.55"/>`;
    } else if (_SINGLE_INLAYS.has(f)) {
      p += `<circle cx="${x}" cy="${midY}" r="${dotR * 0.42}" fill="var(--line-1)" opacity="0.55"/>`;
    }
  }

  // Fret wires. The nut (fret 0 boundary) is drawn heavy.
  for (let i = 0; i <= nCols; i++) {
    const x = nutX + i * colW;
    const isNut = i === 0 && startFret === 1;
    p += `<line x1="${x}" y1="${rowY(0)}" x2="${x}" y2="${rowY(5)}"
      stroke="${isNut ? 'var(--fg-1)' : 'var(--line-1)'}" stroke-width="${isNut ? 3.2 : 1}"/>`;
  }

  // Strings + their names in the left gutter.
  for (let j = 0; j < 6; j++) {
    const y = rowY(j);
    p += `<line x1="${nutX}" y1="${y}" x2="${nutX + gridW}" y2="${y}"
      stroke="var(--line-1)" stroke-width="${0.7 + j * 0.22}"/>`;
    p += `<text x="${padL - Math.round(7 * sc)}" y="${y + Math.round(3.4 * sc)}"
      font-family="Arial,sans-serif" font-size="${lbl}" text-anchor="end"
      fill="var(--fg-2, var(--fg-1))">${_STRING_LABELS[j]}</text>`;
  }

  // Notes.
  for (const n of box.notes) {
    const y = rowY(n.string - 1);
    const finger = fingers.get(`${n.string}:${n.fret}`) ?? 0;
    const isOpen = n.fret === 0;
    const x = isOpen ? padL + openW / 2 : colX(n.fret);
    const label = labelMode === 'notes'
      ? noteNameAt(n.string, n.fret)
      : (isOpen ? '0' : String(finger));

    if (isOpen) {
      // Open string: hollow ring before the nut. An open tonic gets the same
      // heavy ring as a fretted one, so roots read consistently across the box.
      p += `<circle cx="${x}" cy="${y}" r="${dotR}" fill="var(--bg-1)"
        stroke="${n.is_root ? 'var(--fg-0)' : 'var(--fg-1)'}"
        stroke-width="${n.is_root ? 2.4 : 1.6}"/>`;
      p += `<text x="${x}" y="${y + Math.round(3.4 * sc)}" font-family="Arial,sans-serif"
        font-size="${txt}" font-weight="600" text-anchor="middle"
        fill="var(--fg-0)">${label}</text>`;
    } else {
      p += `<circle cx="${x}" cy="${y}" r="${n.is_root ? dotR + 1 : dotR}" fill="${dotFill(finger)}"`;
      // The tonic is the note you resolve to — ring it so it pops out of the shape.
      p += n.is_root ? ` stroke="var(--fg-0)" stroke-width="2.4"/>` : `/>`;
      p += `<text x="${x}" y="${y + Math.round(3.4 * sc)}" font-family="Arial,sans-serif"
        font-size="${txt}" font-weight="700" text-anchor="middle" fill="#111">${label}</text>`;
    }
  }

  // Absolute fret numbers under each column — the anchor for "where on the neck".
  const numY = rowY(5) + Math.round(17 * sc);
  for (let f = startFret; f <= endFret; f++) {
    p += `<text x="${colX(f)}" y="${numY}" font-family="Arial,sans-serif"
      font-size="${lbl}" text-anchor="middle" fill="var(--fg-2, var(--fg-1))">${f}</text>`;
  }

  p += '</svg>';
  return p;
}

// ── Staff notation of a scale run ───────────────────────────────────────────

/**
 * Returns an inline SVG string writing a scale box out as an ascending run on
 * a treble staff, so the shape on the fretboard can be read as music.
 *
 * Guitar notation convention: written an octave above sounding pitch, so the
 * printed staff matches what a player reads in any score.
 *
 * Noteheads carry no stems — this is a scale chart, where rhythm carries no
 * meaning and stems would only add clutter.
 *
 * @param {object} box  {notes:[{string,fret,is_root}]}
 * @param {number} sc   Scale factor (1 = default size)
 * @param {object} [opts] {labels: 'fingers'|'notes'} — caption under each note
 */
/**
 * Deduplicated, ascending run of a scale box's notes by sounding pitch (same
 * pitch on two strings collapses to one entry). Shared by the staff renderer
 * and by audio preview, so "what you see" and "what you hear" are always the
 * same sequence.
 * @param {Array<{string:number,fret:number,is_root:boolean}>} notes
 * @returns {Array<{string:number,fret:number,is_root:boolean,midi:number}>}
 */
export function scaleRun(notes) {
  const seen = new Set();
  return notes
    .map(n => ({ ...n, midi: midiAt(n.string, n.fret) }))
    .sort((a, b) => a.midi - b.midi)
    .filter(n => (seen.has(n.midi) ? false : seen.add(n.midi)));
}

export function staffScaleSVG(box, sc = 1, opts = {}) {
  const labelMode = opts.labels === 'notes' ? 'notes' : 'fingers';
  const fingers = scaleBoxFingers(box.notes);

  // Written an octave above sounding pitch (guitar convention) \u2014 the step and
  // accidental are resolved once, up front, because sizing the canvas needs
  // the full pitch range before anything can be drawn.
  const run = scaleRun(box.notes).map(n => ({ ...n, ..._staffStep(n.midi + 12) }));

  const lineGap = Math.round(9 * sc);   // distance between staff lines
  const halfGap = lineGap / 2;          // one diatonic step
  const noteGap = Math.round(23 * sc);
  const clefW  = Math.round(30 * sc);
  const padL   = Math.round(6 * sc);
  const padR   = Math.round(10 * sc);
  const rx     = Math.round(5.2 * sc);
  const ry     = Math.round(3.9 * sc);
  const ledgeW = rx + Math.round(3 * sc);
  const cap    = Math.max(8, Math.round(9 * sc));

  // The canvas must fit however far this specific run reaches past the staff
  // in either direction \u2014 a two-octave run needs far more headroom than a
  // four-fret pentatonic box, and a fixed margin either clips the far end or
  // wastes space on every other box. Both margins are sized from the run's
  // actual step range so the outermost note always lands the same safe
  // distance from its edge of the canvas, regardless of how many ledger
  // lines that takes.
  const steps = run.map(n => n.step);
  const maxStep = Math.max(_TOP_LINE_STEP, ...steps);
  const minStep = Math.min(_E4_STEP, ...steps);
  const aboveStaff = (maxStep - _TOP_LINE_STEP) * halfGap;  // >=0
  const belowStaff = (_E4_STEP - minStep) * halfGap;        // >=0

  const topMargin = ry + Math.round(6 * sc);       // clearance above the highest note
  const staffTop  = topMargin + aboveStaff;
  const staffBot  = staffTop + 4 * lineGap;
  // Caption row sits a fixed gap below the lowest ledger line actually used,
  // so it can never collide with a note however low the run dips.
  const captionY  = staffBot + belowStaff + Math.round(15 * sc);
  const svgH      = captionY + Math.round(4 * sc);

  const firstX = padL + clefW + Math.round(10 * sc);
  const svgW   = firstX + Math.max(run.length, 1) * noteGap + padR;

  // y of a diatonic step: bottom line is E4, each step is half a gap.
  const stepY = step => staffBot - (step - _E4_STEP) * halfGap;

  let p = `<svg width="${svgW}" height="${svgH}" viewBox="0 0 ${svgW} ${svgH}"
    xmlns="http://www.w3.org/2000/svg" style="display:block">`;

  // Staff.
  for (let i = 0; i < 5; i++) {
    const y = staffTop + i * lineGap;
    p += `<line x1="${padL}" y1="${y}" x2="${svgW - padL}" y2="${y}"
      stroke="var(--line-1)" stroke-width="1"/>`;
  }

  // Treble clef. The G line (second from bottom) is its anchor.
  p += `<text x="${padL + Math.round(4 * sc)}" y="${staffBot + Math.round(1 * sc)}"
    font-size="${Math.round(46 * sc)}" fill="var(--fg-0)"
    font-family="Bravura,'Noto Music','Segoe UI Symbol','Arial Unicode MS',serif"
    >\u{1D11E}</text>`;

  run.forEach((n, i) => {
    const x = firstX + i * noteGap;
    const y = stepY(n.step);

    // Ledger lines, drawn only on the line steps the note actually reaches.
    for (let s = _TOP_LINE_STEP + 2; s <= n.step; s += 2) {
      p += `<line x1="${x - ledgeW}" y1="${stepY(s)}" x2="${x + ledgeW}" y2="${stepY(s)}"
        stroke="var(--line-1)" stroke-width="1"/>`;
    }
    for (let s = _E4_STEP - 2; s >= n.step; s -= 2) {
      p += `<line x1="${x - ledgeW}" y1="${stepY(s)}" x2="${x + ledgeW}" y2="${stepY(s)}"
        stroke="var(--line-1)" stroke-width="1"/>`;
    }

    if (n.accidental) {
      p += `<text x="${x - rx - Math.round(5 * sc)}" y="${y + Math.round(3.2 * sc)}"
        font-family="Arial,sans-serif" font-size="${Math.max(9, Math.round(11 * sc))}"
        text-anchor="middle" fill="var(--fg-0)">\u266F</text>`;
    }

    // The tonic is filled with the accent so the octave landmarks stand out.
    const fill = n.is_root ? 'var(--signal)' : 'var(--fg-0)';
    p += `<ellipse cx="${x}" cy="${y}" rx="${rx}" ry="${ry}"
      transform="rotate(-20 ${x} ${y})" fill="${fill}"/>`;

    const caption = labelMode === 'notes'
      ? noteNameAt(n.string, n.fret)
      : String(fingers.get(`${n.string}:${n.fret}`) ?? 0);
    p += `<text x="${x}" y="${captionY}" font-family="Arial,sans-serif"
      font-size="${cap}" text-anchor="middle" fill="var(--fg-2, var(--fg-1))">${caption}</text>`;
  });

  p += '</svg>';
  return p;
}
