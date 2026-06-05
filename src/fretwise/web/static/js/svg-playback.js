/**
 * svg-playback.js — SVG cursor driver for playback in standard / standard+tab views.
 *
 * Injects transparent <rect> overlay elements into the SVG (one per measure)
 * that highlight the currently playing measure and respond to click-to-seek.
 * The rects are appended last, so they render on top of all notation.
 */

export class SvgCursorDriver {
  /**
   * @param {HTMLElement} svgContainer  - the #core-svg-view div
   * @param {Object}      data          - API response with measure_regions[]
   */
  constructor(svgContainer, data) {
    this.container = svgContainer;
    /** @type {Array<{measure_idx:number, x:number, y0:number, y1:number, width:number}>} */
    this.regions = (data.measure_regions || []).sort((a, b) => a.measure_idx - b.measure_idx);
    /** @type {SVGRectElement[]} */
    this._rects = [];
    /** @type {SVGLineElement|null} */
    this._line = null;
    /** @type {Array<{onset:number, x:number}>} sorted by onset */
    this._noteAnchors = [];
    /** When false the user is exploring freely — highlight() stops auto-scrolling
     *  (the red line still tracks). Mirrors main.js `_followPlayhead`; the Follow
     *  toolbar button / click-to-seek toggle it via main.js `_setFollowPlayhead`. */
    this.followPlayhead = true;
  }

  /**
   * Inject cursor overlay rects into the SVG.
   * Must be called AFTER the SVG has been injected into this.container.
   */
  init() {
    const svg = this.container.querySelector('svg');
    if (!svg || this._rects.length) return;

    for (const region of this.regions) {
      const rect = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
      rect.setAttribute('class', 'fw-cursor');
      rect.setAttribute('data-measure', String(region.measure_idx));
      rect.setAttribute('x', String(region.x));
      rect.setAttribute('y', String(region.y0));
      rect.setAttribute('width', String(region.width));
      rect.setAttribute('height', String(region.y1 - region.y0));
      svg.appendChild(rect);   // appended last → rendered on top
      this._rects.push(rect);
    }

    // Red cursor line — drawn on top of everything, hidden until playback starts
    this._line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    this._line.setAttribute('class', 'fw-cursor-line');
    this._line.setAttribute('x1', '0'); this._line.setAttribute('x2', '0');
    this._line.setAttribute('y1', '0'); this._line.setAttribute('y2', '0');
    this._line.setAttribute('visibility', 'hidden');
    svg.appendChild(this._line);

    // Build the note-anchor table once. Each tab note in the SVG carries
    // its onset (beats from song start) + its X position; the cursor's
    // tick() uses these to interpolate position by *actual note spacing*
    // instead of by uniform time fraction within the measure (which is
    // wrong whenever notes aren't evenly spaced — triplets, syncopes,
    // dotted figures…).
    const onsetToX = new Map();
    for (const noteText of svg.querySelectorAll('text.fw-tab-note')) {
      const onset = parseFloat(noteText.getAttribute('data-onset') || 'NaN');
      const x = parseFloat(noteText.getAttribute('x') || 'NaN');
      if (!isFinite(onset) || !isFinite(x)) continue;
      // Multiple strings at the same onset share the same X column — keep
      // the first encountered to avoid duplicate (and identical) anchors.
      if (!onsetToX.has(onset)) onsetToX.set(onset, x);
    }
    this._noteAnchors = Array.from(onsetToX, ([onset, x]) => ({ onset, x }))
      .sort((a, b) => a.onset - b.onset);
  }

  /**
   * Update highlight for the given measure index and loop range.
   * @param {number} measureIdx
   * @param {number} [loopStart=-1]
   * @param {number} [loopEnd=-1]
   */
  highlight(measureIdx, loopStart = -1, loopEnd = -1) {
    let activeRect = null;
    for (const rect of this._rects) {
      const m = parseInt(rect.getAttribute('data-measure') || '-1', 10);
      const isActive = m === measureIdx;
      const inLoop = loopStart >= 0 && m >= loopStart && m <= loopEnd;
      rect.classList.toggle('active', isActive);
      rect.classList.toggle('loop', inLoop && !isActive);
      if (isActive) activeRect = rect;
    }
    // Scroll the active measure into view — but ONLY within the score container
    // (#core-svg-view), never the page/body, and CLAMPED to the container's
    // scrollable range. The previous activeRect.scrollIntoView() scrolled every
    // scrollable ancestor and was unbounded, so after the first system playback
    // could fling the view far past the content into the blank tail (the user
    // then had to scroll way back up to find the staves). Centering on the
    // active rect and clamping to [0, scrollHeight - clientHeight] prevents that.
    if (this.followPlayhead && activeRect && this.container) {
      const c = this.container;
      const r = activeRect.getBoundingClientRect();
      const cr = c.getBoundingClientRect();
      if (r.height > 0 && cr.height > 0) {
        const relTop = (r.top - cr.top) + c.scrollTop;       // rect top in scroll space
        const target = relTop - c.clientHeight / 2 + r.height / 2;  // center it
        const maxTop = Math.max(0, c.scrollHeight - c.clientHeight);
        const clamped = Math.max(0, Math.min(target, maxTop));
        if (Math.abs(clamped - c.scrollTop) > 2) {
          c.scrollTo({ top: clamped, behavior: 'smooth' });
        }
      }
    }
  }

  /**
   * Scroll a measure into view (centered) and briefly flash it. Independent of
   * playback follow state — used by the review panel to locate a flagged spot.
   * @param {number} measureIdx  0-based measure index (matches data-measure).
   * @returns {boolean} true when the measure rect was found.
   */
  scrollToMeasure(measureIdx) {
    const rect = this._rects.find(
      (r) => parseInt(r.getAttribute('data-measure') || '-1', 10) === measureIdx,
    );
    if (!rect || !this.container) return false;
    const c = this.container;
    const r = rect.getBoundingClientRect();
    const cr = c.getBoundingClientRect();
    if (r.height > 0 && cr.height > 0) {
      const relTop = (r.top - cr.top) + c.scrollTop;
      const target = relTop - c.clientHeight / 2 + r.height / 2;
      const maxTop = Math.max(0, c.scrollHeight - c.clientHeight);
      c.scrollTo({ top: Math.max(0, Math.min(target, maxTop)), behavior: 'smooth' });
    }
    rect.classList.add('review-flash');
    setTimeout(() => rect.classList.remove('review-flash'), 1600);
    return true;
  }

  /**
   * Move the red cursor line to the given beat onset position.
   * @param {number} onset         - current playback position in beats (from song start)
   * @param {number} beatsPerMeasure
   */
  tick(onset, beatsPerMeasure) {
    if (!this._line) return;
    const measureIdx = Math.floor(onset / beatsPerMeasure);
    const region = this.regions.find(r => r.measure_idx === measureIdx);
    if (!region) { this._line.setAttribute('visibility', 'hidden'); return; }

    const x = this._noteSnappedX(onset, region, beatsPerMeasure).toFixed(2);
    this._line.setAttribute('x1', x); this._line.setAttribute('x2', x);
    this._line.setAttribute('y1', region.y0.toFixed(2));
    this._line.setAttribute('y2', region.y1.toFixed(2));
    this._line.setAttribute('visibility', 'visible');
  }

  /**
   * Compute the cursor's X by interpolating between *adjacent note anchors*
   * (each carrying onset + X), so the line lands exactly on each note at
   * its onset and slides linearly between consecutive notes by elapsed
   * time. Falls back to the uniform measure-width interpolation when no
   * tab-note anchors are available (e.g. pure standard-staff mode).
   *
   * @private
   * @returns {number} cursor X in SVG units
   */
  _noteSnappedX(onset, region, beatsPerMeasure) {
    const anchors = this._noteAnchors;
    if (anchors.length > 0) {
      // Binary search for the largest anchor with onset <= current onset.
      let lo = 0, hi = anchors.length - 1, prevIdx = -1;
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (anchors[mid].onset <= onset) { prevIdx = mid; lo = mid + 1; }
        else { hi = mid - 1; }
      }
      const next = prevIdx + 1;
      const a = prevIdx >= 0 ? anchors[prevIdx] : null;
      const b = next < anchors.length ? anchors[next] : null;
      if (a && b) {
        const span = b.onset - a.onset;
        if (span > 0) {
          const frac = Math.max(0, Math.min(1, (onset - a.onset) / span));
          return a.x + frac * (b.x - a.x);
        }
        return a.x;
      }
      if (a) return a.x;
      if (b) return b.x;
    }
    // Fallback — no anchors (standard-staff-only mode, or anchors not yet
    // built): use the legacy uniform-time interpolation within the measure.
    const measureIdx = Math.floor(onset / beatsPerMeasure);
    const fraction = Math.min(
      1, (onset - measureIdx * beatsPerMeasure) / beatsPerMeasure,
    );
    return region.x + fraction * region.width;
  }

  /** Hide the red cursor line (on pause / stop). */
  hideLine() {
    if (this._line) this._line.setAttribute('visibility', 'hidden');
  }

  /**
   * Resolve a DOM click event to a measure index via SVG coordinate transform.
   * @param {MouseEvent} e
   * @returns {number} measure index, or -1 if click is outside all measures
   */
  measureAtClick(e) {
    const svg = this.container.querySelector('svg');
    if (!svg) return -1;
    try {
      const pt = svg.createSVGPoint();
      pt.x = e.clientX;
      pt.y = e.clientY;
      const svgPt = pt.matrixTransform(svg.getScreenCTM().inverse());
      for (const region of this.regions) {
        if (
          svgPt.x >= region.x &&
          svgPt.x <= region.x + region.width &&
          svgPt.y >= region.y0 &&
          svgPt.y <= region.y1
        ) {
          return region.measure_idx;
        }
      }
    } catch (_) { /* SVG not yet rendered or off-screen */ }
    return -1;
  }
}
