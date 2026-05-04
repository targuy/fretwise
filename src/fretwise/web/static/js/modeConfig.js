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
});

/** Human-readable labels for each mode (used in UI badges and selects). */
export const MODE_LABELS = /** @type {Record<string, string>} */ ({
  standard: 'Standard',
  tablature: 'Tab',
  standard_tablature: 'Standard + Tab',
  tablature_rhythm: 'Tab + Rhythm',
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
    || mode === MODES.STANDARD_TABLATURE;
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
