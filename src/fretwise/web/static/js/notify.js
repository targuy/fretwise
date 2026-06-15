/**
 * notify.js — Unified user-feedback system so the user always knows what's
 * happening during any time-consuming action (sync or async).
 *
 * Two presentations, no OK buttons:
 *   • toast(msg)        — transient pill, auto-dismisses (or click to dismiss).
 *   • task(msg, opts)   — persistent feedback that stays for the whole action,
 *                         with an animated spinner, a clear message and (when a
 *                         fraction is known) a progress bar. `blocking:true`
 *                         dims the app behind a translucent backdrop. It
 *                         disappears on its own when the action ends, and can be
 *                         dismissed by clicking outside the frame once finished.
 *
 * Usage:
 *   import { toast, task } from './notify.js';
 *   const t = task('Computing fingerings…');          // indeterminate spinner
 *   t.progress(0.4); t.message('Optimising…');         // optional updates
 *   t.done('Ready');                                   // success → auto-dismiss
 *   t.error('Export failed');                          // failure → stays until clicked
 *
 * Also exposed as window.fwNotify for non-module callers.
 */

let _host = null;
function host() {
  if (!_host) {
    _host = document.createElement('div');
    _host.id = 'fw-notify-host';
    document.body.appendChild(_host);
  }
  return _host;
}

const SPINNER = '<span class="fw-spinner" aria-hidden="true"></span>';

function fadeRemove(el, delay = 0) {
  setTimeout(() => {
    el.classList.remove('fw-in');
    el.classList.add('fw-out');
    let removed = false;
    const kill = () => { if (!removed) { removed = true; el.remove(); } };
    el.addEventListener('transitionend', kill, { once: true });
    setTimeout(kill, 450);  // fallback if no transition fires
  }, delay);
}

/**
 * Transient toast notification.
 * @param {string} message
 * @param {{duration?:number, type?:'info'|'success'|'warn'|'error', spinner?:boolean}} [opts]
 * @returns {{close:()=>void, message:(t:string)=>void}}
 */
export function toast(message, opts = {}) {
  const { duration = 3200, type = 'info', spinner = false } = opts;
  const el = document.createElement('div');
  el.className = `fw-toast fw-toast--${type}`;
  el.setAttribute('role', 'status');
  el.innerHTML = `${spinner ? SPINNER : ''}<span class="fw-toast-msg"></span>`;
  el.querySelector('.fw-toast-msg').textContent = message;
  host().appendChild(el);
  requestAnimationFrame(() => el.classList.add('fw-in'));

  let timer = null;
  const close = () => { if (timer) clearTimeout(timer); fadeRemove(el); };
  el.addEventListener('click', close);
  if (duration > 0) timer = setTimeout(close, duration);
  return { close, message: (t) => { el.querySelector('.fw-toast-msg').textContent = t; } };
}

/**
 * Persistent task feedback (spinner + message + optional progress bar).
 * @param {string} message
 * @param {{blocking?:boolean, title?:string, progress?:number|null}} [opts]
 * @returns {{message:(t:string)=>void, progress:(f:number|null)=>void,
 *            done:(finalMsg?:string)=>void, error:(msg?:string)=>void, close:()=>void}}
 */
export function task(message, opts = {}) {
  const { blocking = false, title = '' } = opts;

  const wrap = document.createElement('div');
  wrap.className = `fw-task ${blocking ? 'fw-task--blocking' : 'fw-task--inline'}`;
  wrap.setAttribute('role', 'status');
  wrap.setAttribute('aria-live', 'polite');
  wrap.innerHTML = `
    <div class="fw-task-card">
      <div class="fw-task-head">
        ${SPINNER}
        <div class="fw-task-text">
          ${title ? `<div class="fw-task-title"></div>` : ''}
          <div class="fw-task-msg"></div>
        </div>
      </div>
      <div class="fw-task-progress" hidden><div class="fw-task-progress-fill"></div></div>
    </div>`;
  const card = wrap.querySelector('.fw-task-card');
  const msgEl = wrap.querySelector('.fw-task-msg');
  const titleEl = wrap.querySelector('.fw-task-title');
  const barWrap = wrap.querySelector('.fw-task-progress');
  const barFill = wrap.querySelector('.fw-task-progress-fill');
  msgEl.textContent = message;
  if (titleEl) titleEl.textContent = title;

  host().appendChild(wrap);
  requestAnimationFrame(() => wrap.classList.add('fw-in'));

  let finished = false;
  const close = () => fadeRemove(wrap);

  const setProgress = (frac) => {
    if (frac == null || Number.isNaN(frac)) {
      barWrap.hidden = true; card.classList.remove('fw-determinate'); return;
    }
    barWrap.hidden = false;
    card.classList.add('fw-determinate');
    barFill.style.width = `${Math.max(0, Math.min(1, frac)) * 100}%`;
  };
  if (opts.progress != null) setProgress(opts.progress);

  // Click outside the frame dismisses it — but only once the task has finished,
  // so a still-running blocking action can't be clicked away by accident.
  wrap.addEventListener('click', (e) => {
    if (e.target === wrap && finished) close();
  });

  return {
    message(t) { msgEl.textContent = t; },
    progress: setProgress,
    done(finalMsg) {
      finished = true;
      card.classList.add('fw-done');
      card.classList.remove('fw-determinate');
      barWrap.hidden = true;
      if (finalMsg) msgEl.textContent = finalMsg;
      fadeRemove(wrap, finalMsg ? 900 : 250);  // brief success flash, then auto-dismiss
    },
    error(errMsg) {
      finished = true;
      card.classList.add('fw-error');
      card.classList.remove('fw-determinate');
      barWrap.hidden = true;
      if (errMsg) msgEl.textContent = errMsg;
      // Errors linger so they can be read; dismiss by clicking outside or after a while.
      fadeRemove(wrap, 6000);
    },
    close,
  };
}

// Non-module global access.
if (typeof window !== 'undefined') {
  window.fwNotify = { toast, task };
}
