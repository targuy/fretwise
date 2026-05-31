# Color Palette — FretWise

## Dark Theme (Default)

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Background – App | `bg-app` | `#1A1A2E` | Main window background |
| Background – Panel | `bg-panel` | `#16213E` | Score, fretboard, and info panel backgrounds |
| Background – Widget | `bg-widget` | `#0F3460` | Toolbar, status bar, dialog backgrounds |
| Surface | `surface` | `#1E2A4A` | Card-like surfaces, panel headers |
| Border | `border` | `#2E4070` | Panel borders, dividers, splitter lines |
| Text – Primary | `text-primary` | `#E0E0E0` | Main readable text |
| Text – Secondary | `text-secondary` | `#A0AEC0` | Labels, placeholders, help text |
| Text – Disabled | `text-disabled` | `#4A5568` | Disabled controls |
| Accent – Primary | `accent-primary` | `#E94560` | Playhead line, active note highlight, CTA buttons |
| Accent – Secondary | `accent-secondary` | `#F5A623` | Selected note / range, capo marker |
| Fretboard – Wood | `fret-wood` | `#8B5E3C` | Guitar neck wood grain base color |
| Fretboard – Fret | `fret-metal` | `#C0C0C0` | Fret wires |
| Fretboard – String | `fret-string` | `#D4AF37` | String lines (warm gold) |
| Fretboard – Dot | `fret-dot-bg` | `#2C3E50` | Inlay position dot fill |
| Finger – Index | `finger-1` | `#E94560` | Finger 1 (index) dot |
| Finger – Middle | `finger-2` | `#4CAF50` | Finger 2 (middle) dot |
| Finger – Ring | `finger-3` | `#2196F3` | Finger 3 (ring) dot |
| Finger – Pinky | `finger-4` | `#FF9800` | Finger 4 (pinky) dot |
| Open String | `open-string` | `#FFFFFF` | Open string indicator circle |
| Muted String | `muted-string` | `#E94560` | Muted / dead string indicator (×) |
| Success | `success` | `#4CAF50` | Positive feedback, loaded OK |
| Warning | `warning` | `#FF9800` | Non-fatal issues |
| Error | `error` | `#F44336` | Parse errors, missing files |

---

## Light Theme (Optional)

| Role | Name | Hex | Usage |
|------|------|-----|-------|
| Background – App | `bg-app` | `#F5F5F5` | Main window background |
| Background – Panel | `bg-panel` | `#FFFFFF` | Score, fretboard, and info panel backgrounds |
| Background – Widget | `bg-widget` | `#E8EAF6` | Toolbar, status bar, dialog backgrounds |
| Surface | `surface` | `#EDE7F6` | Card surfaces, panel headers |
| Border | `border` | `#BDBDBD` | Panel borders, dividers |
| Text – Primary | `text-primary` | `#212121` | Main readable text |
| Text – Secondary | `text-secondary` | `#757575` | Labels, placeholders |
| Text – Disabled | `text-disabled` | `#BDBDBD` | Disabled controls |
| Accent – Primary | `accent-primary` | `#C62828` | Playhead line, active note, CTA buttons |
| Accent – Secondary | `accent-secondary` | `#E65100` | Selected note / range |
| Fretboard – Wood | `fret-wood` | `#A0522D` | Guitar neck base color |
| Fretboard – Fret | `fret-metal` | `#9E9E9E` | Fret wires |
| Fretboard – String | `fret-string` | `#B8860B` | String lines |

---

## Color Usage Rules

1. **Never** place `text-primary` on `bg-widget` directly — always add a `surface` layer in between for minimum 4.5:1 contrast ratio (WCAG AA).
2. Finger-color dots must be visible against both `fret-wood` and highlighted backgrounds — use a **2 px white border** around each dot.
3. The playhead (`accent-primary` `#E94560`) should stand out from all panel backgrounds — test against both themes.
4. Barre chord arcs use `accent-secondary` with 60 % opacity so underlying fret numbers remain readable.
5. Status-bar severity indicators follow: `success` → `warning` → `error` traffic-light pattern.
