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
    // Scroll active measure into view within the SVG container
    if (activeRect) {
      activeRect.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }
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
