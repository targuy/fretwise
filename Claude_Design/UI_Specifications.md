# UI Specifications — FretWise

## 1. Main Window

| Property | Value |
|----------|-------|
| Default size | 1280 × 800 px |
| Minimum size | 900 × 600 px |
| Resizable | Yes (all sides + corners) |
| Title bar | "FretWise – [filename]" |
| Theme | Dark (default) / Light (optional toggle) |

---

## 2. Top Menu Bar

Standard OS-native menu bar with the following top-level menus:

- **File** — Open, Recent Files, Save Session, Export (PDF / MusicXML / MIDI), Quit
- **View** — Zoom In / Out, Toggle Fretboard Panel, Toggle Score Panel, Full Screen
- **Playback** — Play, Pause, Stop, Loop, Metronome, Tempo
- **Settings** — Guitar Tuning, Number of Frets, Capo, Notation Style, Theme
- **Help** — Documentation, Keyboard Shortcuts, About

---

## 3. Toolbar (below menu bar)

Height: **40 px**. Contains icon buttons (24 × 24 px icons, 8 px padding):

```
[ Open ] [ Save ] | [ ◀◀ ] [ ◀ ] [ ▶ ] [ ⏹ ] [ ↺ ] | [ 🎵 ] [Tempo: 120 BPM▼] | [ 🔍− ] [ 🔍+ ] | [ ⚙ ]
```

All toolbar items have tooltips on hover.

---

## 4. Main Content Area

The content area below the toolbar is divided into three resizable panels using splitters:

```
┌─────────────────────────────────────────────────────────┐
│                    Score Panel (top)                     │
│              Standard notation / Tablature               │
├─────────────────────────────────────────────────────────┤
│                  Fretboard Panel (middle)                 │
│            Interactive guitar neck visualizer            │
├─────────────────────────────────────────────────────────┤
│                 Info / Lyrics Panel (bottom)              │
│          Chord names, lyrics, position markers           │
└─────────────────────────────────────────────────────────┘
```

### 4.1 Score Panel

- **Height**: 40 % of content area (resizable)
- **Content**: Scrolling standard musical notation and/or guitar tablature
- **Cursor**: A vertical playhead line advances in sync with playback
- **Selection**: Click a note to highlight it; shift-click to select a range
- **Scroll direction**: Horizontal (continuous scroll or page-by-page)
- **Zoom**: Independent zoom level (Ctrl +/−)

### 4.2 Fretboard Panel

- **Height**: 40 % of content area (resizable)
- **Content**: Guitar neck rendered with strings, frets, fret numbers, and nut
- **Orientation**: Horizontal, low E string at the bottom (configurable)
- **Highlights**: Active fingering dots animated in sync with the playhead
- **Finger labels**: Dots show finger number (1–4) or note name (configurable)
- **Fret range**: Displays the relevant fret window around the current position
- **Zoom**: Fret count visible is adjustable (e.g., 5–24 frets)

### 4.3 Info Panel

- **Height**: 20 % of content area (resizable, can be collapsed)
- **Content** (tabs):
  - **Chord**: Chord name, voicing diagram, alternatives
  - **Lyrics**: Synchronized lyrics text
  - **Markers**: Section labels (Intro, Verse, Chorus…)
  - **Log**: Application messages / parsing errors

---

## 5. Status Bar (bottom)

Height: **24 px**. Left-to-right sections:

```
| File: example.gp5 | Bar: 12 / 48 | Beat: 2 / 4 | Capo: 0 | Tuning: E A D G B e | BPM: 120 | Ready |
```

---

## 6. Side Panel (optional, collapsible)

Width: **220 px** (collapsed: **0 px**, toggled with a thin arrow button on the right edge).

Contains:
- **Structure tree**: Track list, measure navigator
- **Track list**: Multi-track files show each instrument track; click to solo/mute

---

## 7. Dialog Windows

### 7.1 Open File
Standard OS file chooser filtered to: `.gp`, `.gp3`, `.gp4`, `.gp5`, `.gpx`, `.musicxml`, `.xml`, `.mid`

### 7.2 Settings
Modal dialog, tabbed:
- **Guitar** — Tuning presets, capo, number of strings (6 / 7 / 12)
- **Display** — Theme, font size, tablature vs. standard notation vs. both
- **Playback** — Default tempo, sound font, metronome volume
- **Shortcuts** — Editable keyboard shortcuts table

### 7.3 Export
Modal dialog with format selector, page range, and destination path.
