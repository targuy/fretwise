/**
 * icons.js — swap built-in button glyphs for the metallic knob icon set.
 *
 * Reads img/icons/manifest.json and, for every mapped button id, inserts a
 * `.fw-ico fw-ico--<size> fw-ico--<name>` span (the CSS in leather-icons.css
 * paints it with the PNG) and marks the button `.fw-iconified` so its inline
 * SVG / text glyph is hidden. Inputs (e.g. the search box) are skipped — a
 * background icon can't live inside an <input>.
 *
 * Idempotent: re-running skips buttons that already carry a `.fw-ico`. Safe to
 * call after dynamic UI (track tabs, panels) is (re)built.
 */

const _SIZE_CLASS = { S: 'fw-ico--s', M: 'fw-ico--m', L: 'fw-ico--l' };
let _manifestPromise = null;

function _loadManifest() {
  if (!_manifestPromise) {
    _manifestPromise = fetch('/static/img/icons/manifest.json')
      .then((r) => (r.ok ? r.json() : null))
      .catch(() => null);
  }
  return _manifestPromise;
}

function _applyOne(el, name, sizeClass) {
  if (!el || el.tagName === 'INPUT') return;
  if (el.querySelector(':scope > .fw-ico')) return;  // already iconified
  const span = document.createElement('span');
  span.className = `fw-ico ${sizeClass} fw-ico--${name}`;
  span.setAttribute('aria-hidden', 'true');
  el.classList.add('fw-iconified');
  el.insertBefore(span, el.firstChild);
}

/**
 * Apply the leather/knob icons to every button named in the manifest.
 * @returns {Promise<void>}
 */
export async function applyLeatherIcons() {
  const manifest = await _loadManifest();
  if (!manifest || !Array.isArray(manifest.icons)) return;
  for (const icon of manifest.icons) {
    const sizeClass = _SIZE_CLASS[icon.size] || 'fw-ico--s';
    for (const id of icon.buttons || []) {
      _applyOne(document.getElementById(id), icon.name, sizeClass);
    }
  }
}
