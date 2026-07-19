/**
 * svg-playback.js — SVG cursor driver for playback in standard / standard+tab views.
 *
 * Injects transparent <rect> overlay elements into the SVG (one per measure)
 * that highlight the currently playing measure and respond to click-to-seek,
 * plus a thin vertical <line> playhead that glides note-to-note within the
 * current measure (sub-measure resolution). The overlays are appended last, so
 * they render on top of all notation.
 */

export class SvgCursorDriver {
  /**
   * @param {HTMLElement} svgContainer  - the #core-svg-view div
   * @param {Object}      data          - API response with measure_regions[]
   */
  constructor(svgContainer, data) {
    this.container = svgContainer;
    /** @type {Array<{measure_idx:number, x:number, y0:number, y1:number, width:number,
     *                 beats:number, columns:Array<{beat:number,x:number}>}>} */
    this.regions = (data.measure_regions || []).sort((a, b) => a.measure_idx - b.measure_idx);
    /** measure_idx → region, for O(1) lookup during per-frame ticks. */
    this._byIdx = new Map(this.regions.map((r) => [r.measure_idx, r]));
    /** @type {SVGRectElement[]} */
    this._rects = [];
    /** @type {SVGLineElement|null} the gliding sub-measure playhead. */
    this._playhead = null;
    /** y0 of the system row the cursor was last on — used so we scroll only when
     *  the playhead crosses into a NEW system, keeping the page still while a
     *  system is being played (far easier to read along to). */
    this._lastSystemKey = null;
    /** When false the user is exploring freely — highlight() stops auto-scrolling.
     *  Mirrors main.js `_followPlayhead`; the Follow toolbar button / click-to-seek
     *  toggle it via main.js `_setFollowPlayhead`. */
    this.followPlayhead = true;
  }

  /**
   * Inject cursor overlay rects + the playhead line into the SVG.
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

    // Thin gliding playhead line (hidden until the first tick positions it).
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('class', 'fw-playhead');
    line.style.display = 'none';
    svg.appendChild(line);
    this._playhead = line;
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
    // Scroll only when the playhead enters a NEW system row. While the cursor
    // stays inside one system the page is held still — the eye reads the line
    // without the staves sliding underneath — then advances one system at a
    // time, landing the current system near the top third so the following
    // lines are already visible for look-ahead. Scoped to #core-svg-view and
    // clamped to its scroll range (never scrolls the page/body).
    const region = this._byIdx.get(measureIdx);
    const systemKey = region ? Math.round(region.y0) : null;
    if (
      this.followPlayhead && activeRect && this.container &&
      systemKey !== null && systemKey !== this._lastSystemKey
    ) {
      this._scrollSystemIntoView(activeRect, 0.32);
    }
    if (systemKey !== null) this._lastSystemKey = systemKey;
  }

  /**
   * Position the gliding playhead line at a continuous sub-measure position.
   * Called every animation frame by the playback cursor loop.
   * @param {number} measureIdx     current cursor measure.
   * @param {number} localBeats     elapsed quarter-beats inside that measure.
   */
  tickFine(measureIdx, localBeats) {
    const line = this._playhead;
    const region = this._byIdx.get(measureIdx);
    if (!line || !region) return;
    const x = this._xForBeat(region, localBeats);
    line.setAttribute('x1', String(x));
    line.setAttribute('x2', String(x));
    line.setAttribute('y1', String(region.y0));
    line.setAttribute('y2', String(region.y1));
    line.style.display = '';
  }

  /**
   * Interpolate the playhead x inside a measure from its note columns. Glides
   * proportionally between consecutive onsets; past the last column it slides
   * to the measure's right edge (barline). Before the first column it holds on
   * that column (a leading rest doesn't drag the line behind the first note).
   * @param {{x:number,width:number,beats:number,columns:Array<{beat:number,x:number}>}} region
   * @param {number} localBeats
   * @returns {number}
   */
  _xForBeat(region, localBeats) {
    const cols = region.columns || [];
    if (!cols.length) return region.x + region.width * 0.5;
    // Anchor list: the note columns plus the measure's right edge at beat=beats.
    const endBeat = region.beats > 0 ? region.beats : (cols[cols.length - 1].beat + 1);
    if (localBeats <= cols[0].beat) return cols[0].x;
    for (let i = 0; i < cols.length; i++) {
      const lo = cols[i];
      const hi = i + 1 < cols.length
        ? cols[i + 1]
        : { beat: endBeat, x: region.x + region.width };
      if (localBeats < hi.beat) {
        const span = hi.beat - lo.beat;
        const t = span > 1e-6 ? Math.min(1, Math.max(0, (localBeats - lo.beat) / span)) : 0;
        return lo.x + (hi.x - lo.x) * t;
      }
    }
    return region.x + region.width;
  }

  /** Smooth-scroll so `rect`'s top lands at `frac` of the container height.
   *  Clamped to [0, scrollHeight - clientHeight]. */
  _scrollSystemIntoView(rect, frac = 0.32) {
    const c = this.container;
    const r = rect.getBoundingClientRect();
    const cr = c.getBoundingClientRect();
    if (r.height <= 0 || cr.height <= 0) return;
    const relTop = (r.top - cr.top) + c.scrollTop;   // rect top in scroll space
    const target = relTop - c.clientHeight * frac;
    const maxTop = Math.max(0, c.scrollHeight - c.clientHeight);
    const clamped = Math.max(0, Math.min(target, maxTop));
    if (Math.abs(clamped - c.scrollTop) > 2) {
      c.scrollTo({ top: clamped, behavior: 'smooth' });
    }
  }

  /**
   * Scroll a measure into view (centered) and briefly flash it. Independent of
   * playback follow state — used by the review panel to locate a flagged spot,
   * and by click-to-seek. Resets the system-scroll anchor so the next play tick
   * re-evaluates cleanly.
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
    const region = this._byIdx.get(measureIdx);
    this._lastSystemKey = region ? Math.round(region.y0) : null;
    rect.classList.add('review-flash');
    setTimeout(() => rect.classList.remove('review-flash'), 1600);
    return true;
  }

  /** No-op: the gliding playhead is driven by {@link tickFine} from the cursor
   *  loop, not from a per-tick call here. Kept so the playback loop can call it
   *  unconditionally. */
  tick() { /* playhead updated via tickFine */ }

  /** Hide the gliding playhead (called on pause/stop). */
  hideLine() {
    if (this._playhead) this._playhead.style.display = 'none';
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
