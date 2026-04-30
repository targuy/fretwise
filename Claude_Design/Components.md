# Components — FretWise

Describes every reusable GUI widget used in the application.

---

## 1. FretboardView

**Purpose**: Renders the guitar neck and highlights current fingering positions.

### Visual Structure
```
Nut  Fret 1   Fret 2   Fret 3   Fret 4   Fret 5
 |---+--------+--------+--------+--------+-----
 |   |        |        |  [2]   |        |      ← e (high)
 |   |        |  [1]   |        |        |      ← B
 |   |        |        |  [3]   |        |      ← G
 |---+--------+--------+--------+--------+-----  (inlay dot at 3rd fret)
 |   |        |        |  [4]   |        |      ← D
 |   |   [O]  |        |        |        |      ← A (open)
 |   |        |        |        |        |      ← E (low)
```

### Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `num_strings` | int | 6 | Number of strings |
| `num_frets_visible` | int | 12 | Frets shown at once |
| `first_fret` | int | 0 | Starting fret (scroll window) |
| `tuning` | list[str] | `["E","A","D","G","B","e"]` | Open-string notes |
| `capo` | int | 0 | Capo fret (0 = no capo) |
| `fingering` | list[dict] | `[]` | Active finger positions |
| `orientation` | str | `"horizontal"` | `"horizontal"` or `"vertical"` |
| `show_labels` | str | `"finger"` | `"finger"` / `"note"` / `"none"` |
| `animate` | bool | `True` | Animate dot appearance |

### Fingering Dict Schema
```json
{
  "string": 2,       // 0-indexed from low E
  "fret": 3,         // 0 = open, -1 = muted
  "finger": 1,       // 1–4, or 0 for thumb
  "barre_end": null  // fret number if this is a barre chord start
}
```

### Events emitted
- `note_clicked(string, fret)` — user clicks a fret position
- `string_muted(string)` — user clicks the muted (×) marker

---

## 2. ScoreView

**Purpose**: Displays musical score — standard notation and / or tablature.

### Modes
| Mode | Description |
|------|-------------|
| `STANDARD` | Staff with clef, key, time signature, notes |
| `TAB` | Guitar tablature (6-line staff with numbers) |
| `BOTH` | Standard notation on top, TAB staff below |

### Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `mode` | ScoreMode | `BOTH` | Render mode |
| `zoom` | float | `1.0` | Scale factor (0.5 – 3.0) |
| `scroll_pos` | int | `0` | Horizontal scroll position in ticks |
| `playhead_tick` | int | `0` | Current playback position |
| `selection` | tuple[int,int] | `None` | Selected tick range |

### Events emitted
- `note_selected(tick, pitch)` — user clicks a note
- `measure_clicked(measure_index)` — user clicks a measure number

---

## 3. PlaybackBar

**Purpose**: Transport controls (play, pause, stop, seek, loop, tempo).

### Layout
```
[ ◀◀ ]  [ ◀ ]  [ ▶ / ⏸ ]  [ ⏹ ]  [ ↺ Loop ]
━━━━━━━━━━━━━━━●━━━━━━━━━━━━━━━━━━━━━  (seek bar)
  0:34                              3:12
  [Tempo: ─────●─── 120 BPM]  [Metronome 🔔]
```

### Properties
| Property | Type | Default | Description |
|----------|------|---------|-------------|
| `tempo` | int | `120` | Current BPM |
| `tempo_range` | tuple | `(20, 300)` | Min / max BPM |
| `position` | float | `0.0` | Position 0.0 – 1.0 |
| `loop_enabled` | bool | `False` | Loop playback |
| `metronome_on` | bool | `False` | Metronome click |

### Events emitted
- `play_requested()`, `pause_requested()`, `stop_requested()`
- `seek_requested(position: float)` — 0.0 to 1.0
- `tempo_changed(bpm: int)`
- `loop_toggled(enabled: bool)`

---

## 4. ChordDiagram

**Purpose**: Small pop-up or inline chord voicing diagram (nut-view).

### Visual (C major)
```
  E A D G B e
  × 3 2 0 1 0
  ┌─┬─┬─┬─┬─┐
  │ │ │ │ ● │  ← fret 1
  │ ● ● │ │ │  ← fret 2  (● = finger dot)
  │ │ │ │ │ │  ← fret 3
  └─┴─┴─┴─┴─┘
```

### Properties
| Property | Type | Description |
|----------|------|-------------|
| `chord_name` | str | Display name (e.g. `"Cmaj7"`) |
| `fingering` | list[dict] | Same schema as FretboardView |
| `size` | str | `"small"` / `"large"` |

---

## 5. TuningSelector

**Purpose**: Dropdown / dialog to set guitar tuning and capo.

- Presets: Standard E, Drop D, Open G, Open D, DADGAD, etc.
- Custom: 6 individual note selectors (comboboxes)
- Capo spinner: 0 – 12

---

## 6. TrackList

**Purpose**: Lists all instrument tracks in the loaded file.

Each row:
```
[Solo ◉]  [Mute 🔇]  🎸 Guitar 1 (Electric)       Volume [━━●━] 80%
[Solo ◉]  [Mute 🔇]  🥁 Drums                      Volume [━●━━] 40%
```

### Events emitted
- `track_solo_toggled(track_id, solo: bool)`
- `track_mute_toggled(track_id, mute: bool)`
- `track_volume_changed(track_id, volume: int)` — 0–100
- `track_selected(track_id)`

---

## 7. SettingsDialog

**Purpose**: Modal dialog for application preferences.

Tabs:
1. **Guitar** — tuning preset, capo, number of strings
2. **Display** — theme, score mode, fretboard orientation, zoom defaults
3. **Playback** — default tempo, soundfont path, metronome volume, MIDI output
4. **Shortcuts** — editable key-binding table (action | current shortcut | edit button)

---

## 8. WelcomeScreen

**Purpose**: Shown when no file is loaded.

Content:
- App logo / icon (centered, 128 × 128 px)
- Title: "FretWise"
- Subtitle: "Guitar Partition Reader with Fingering"
- `[ Open a file… ]` button (primary)
- `[ Recent Files ]` list (last 5 files, clickable)
- Quick-start tips (3 bullet points)
