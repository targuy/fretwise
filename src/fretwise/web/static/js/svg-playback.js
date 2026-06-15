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
    /** When false the user is exploring freely — highlight() stops auto-scrolling.
     *  Mirrors main.js `_followPlayhead`; the Follow toolbar button / click-to-seek
     *  toggle it via main.js `_setFollowPlayhead`. */
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
    // The moving red cursor line was removed: the only playback indicator is the
    // highlighted current measure (the rects above), driven by the meter-aware
    // timeline. No per-beat line element / note-anchor table is built anymore.
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

  /** No-op: the moving cursor line was removed; the current-measure highlight
   *  (updated via {@link highlight}) is now the sole playback indicator. Kept as
   *  a stub so the playback loop can call it unconditionally. */
  tick() { /* cursor line removed — highlight only */ }

  /** No-op: kept for callers (pause/stop) now that there is no cursor line. */
  hideLine() { /* cursor line removed — nothing to hide */ }

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
