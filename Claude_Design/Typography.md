# Typography — FretWise

## Font Stack

| Role | Primary Font | Fallback | Style |
|------|-------------|----------|-------|
| UI text (menus, labels, buttons) | `Inter` | `Segoe UI`, `Helvetica Neue`, `Arial`, sans-serif | Regular |
| Monospaced / tablature numbers | `JetBrains Mono` | `Fira Mono`, `Consolas`, monospace | Regular |
| Musical notation | `Bravura` (SMuFL) | `Gonville`, serif | — |
| Chord names, section labels | `Inter` | same as UI | Semi-Bold |

All fonts are **open-source / free** and should be bundled in `assets/fonts/` so the app works offline.

---

## Type Scale

| Token | Size (px) | Weight | Line Height | Usage |
|-------|-----------|--------|-------------|-------|
| `text-xs` | 10 | 400 | 1.4 | Status bar, micro-labels |
| `text-sm` | 12 | 400 | 1.5 | Toolbar tooltips, secondary info |
| `text-base` | 14 | 400 | 1.6 | Default UI text |
| `text-md` | 16 | 400 | 1.6 | Panel body, lyrics |
| `text-lg` | 18 | 600 | 1.4 | Panel headings, chord names |
| `text-xl` | 22 | 700 | 1.3 | Dialog titles |
| `text-2xl` | 28 | 700 | 1.2 | Welcome / empty-state headings |

---

## Tablature Numbers

- Font: `JetBrains Mono`, `text-base` (14 px)
- Each number is centered in a **fixed-width cell** equal to the string spacing (default: 20 px)
- Technique annotations (bend, slide, vibrato) use `text-xs` italic above the number
- Colors follow the standard text colors; highlighted (selected) numbers use `accent-secondary`

---

## Chord Labels

- Font: `Inter Semi-Bold`, `text-lg`
- Positioned above the first beat of the chord, centered horizontally
- Superscript for chord quality: maj7 → **C<sup>maj7</sup>**  (Inter Regular, `text-sm`)

---

## Fingering Dot Labels

| Mode | Content | Font | Size |
|------|---------|------|------|
| Finger number | 1 / 2 / 3 / 4 | Inter Bold | 11 px |
| Note name | C / F# / Bb | Inter Regular | 10 px |
| None | (empty dot) | — | — |

---

## Accessibility Notes

- Minimum body text contrast ratio: **4.5:1** against its background (WCAG AA).
- Never rely on color alone to convey meaning — pair color with a label or icon.
- Font sizes must **scale** when the system DPI / accessibility font-size setting changes (use relative units where the GUI toolkit allows).
