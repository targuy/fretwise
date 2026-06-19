/**
 * modeConfig.js — Central notation mode definitions.
 *
 * Single source of truth for all mode-dependent logic on the frontend.
 * Any component that needs to branch on notation mode should import
 * helpers from this module rather than comparing string literals inline.
 *
 * The canonical mode strings must stay in sync with
 * ``fretwise.core.notation_mode`` (Python backend).
 */

/** Canonical mode identifier constants. */
export const MODES = /** @type {const} */ ({
  STANDARD: 'standard',
  TABLATURE: 'tablature',
  STANDARD_TABLATURE: 'standard_tablature',
  TABLATURE_RHYTHM: 'tablature_rhythm',
  SLOPE: 'slope',
  HAND_3D: 'hand_3d',
});

/** Human-readable labels for each mode (used in UI badges and selects). */
export const MODE_LABELS = /** @type {Record<string, string>} */ ({
  standard: 'Standard',
  tablature: 'Tab',
  standard_tablature: 'Standard + Tab',
  tablature_rhythm: 'Tab + Rhythm',
  slope: 'Slope',
  hand_3d: '3D',
});

/** Default mode when none is specified. */
export const DEFAULT_MODE = MODES.STANDARD_TABLATURE;

/**
 * Return true when *mode* includes a tablature staff.
 *
 * @param {string} mode
 * @returns {boolean}
 */
export function hasTab(mode) {
  return mode === MODES.TABLATURE
    || mode === MODES.TABLATURE_RHYTHM
    || mode === MODES.STANDARD_TABLATURE
    || mode === MODES.SLOPE
    || mode === MODES.HAND_3D;
}

/**
 * Return true when *mode* includes a standard-notation staff.
 *
 * @param {string} mode
 * @returns {boolean}
 */
export function hasStandard(mode) {
  return mode === MODES.STANDARD || mode === MODES.STANDARD_TABLATURE;
}

/**
 * Return true when *mode* is one of the four known notation modes.
 *
 * @param {string} mode
 * @returns {boolean}
 */
export function isValidMode(mode) {
  return Object.values(MODES).includes(mode);
}

// ── Track kind ──────────────────────────────────────────────────────
//
// The backend tags every track with a ``kind`` field
// (``guitar`` | ``bass`` | ``drums`` | ``vocal`` | ``other``) on both
// ``/api/tracks`` and the ``/api/solve`` response. Only guitar tracks
// carry tablature + fingering data; every other kind is rendered as
// standard staff notation with the tablature-only / mixed view toggles
// and the fingering UI disabled.

/** Canonical track-kind identifier constants. */
export const TRACK_KINDS = /** @type {const} */ ({
  GUITAR: 'guitar',
  BASS: 'bass',
  DRUMS: 'drums',
  VOCAL: 'vocal',
  OTHER: 'other',
});

/**
 * Return true when *kind* denotes a fretted instrument FretWise can finger.
 *
 * Defensive by design: a missing / unknown ``kind`` is treated as guitar so
 * the UI degrades to today's behaviour if the backend has not yet shipped the
 * field. Only an explicit non-guitar kind switches the UI into staff-only
 * mode.
 *
 * @param {string | null | undefined} kind
 * @returns {boolean}
 */
export function isGuitarKind(kind) {
  if (kind == null || kind === '') return true;
  return String(kind).toLowerCase() === TRACK_KINDS.GUITAR;
}

/**
 * Short uppercase badge label for a track *kind* (e.g. ``BASS``, ``DRUMS``).
 * Guitar tracks return an empty string — they need no badge.
 *
 * @param {string | null | undefined} kind
 * @returns {string}
 */
export function trackKindLabel(kind) {
  if (isGuitarKind(kind)) return '';
  return String(kind).toUpperCase();
}
