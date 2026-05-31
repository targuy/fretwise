# Interactions & Keyboard Shortcuts — FretWise

## 1. User Interaction Flows

### 1.1 Opening a File

```
User action                         Application response
──────────────────────────────────────────────────────────────────
File ▸ Open  OR  Ctrl+O             OS file chooser appears
User selects *.gp5 file             Dialog closes
                                    Status bar: "Loading…"
                                    File is parsed
                                    Score panel fills with notation
                                    Fretboard resets to bar 1, beat 1
                                    Status bar: "hotel_california.gp5 — Ready"
                                    Window title updated
```

### 1.2 Playback

```
User action                         Application response
──────────────────────────────────────────────────────────────────
Press Space  OR  click ▶            Audio starts; playhead advances
                                    Fretboard highlights sync to playhead
                                    Score scrolls automatically
Press Space again  OR  click ⏸     Audio pauses; playhead stays in place
Press Escape  OR  click ⏹          Audio stops; playhead returns to start
Click seek bar at 50 %              Playhead jumps to midpoint; audio resumes
                                    from that position if was playing
```

### 1.3 Clicking a Note in the Score

```
User action                         Application response
──────────────────────────────────────────────────────────────────
Click note in Score panel           Note is highlighted (selection color)
                                    Fretboard updates to show fingering
                                    Chord tab in Info panel updates
                                    If playing: continues from that note
```

### 1.4 Changing Tempo

```
User action                         Application response
──────────────────────────────────────────────────────────────────
Drag tempo slider in toolbar        BPM value updates live; audio pitch
                                    maintained (time-stretch)
Type value in BPM field + Enter     Same as above
Scroll wheel over BPM field         ± 1 BPM per scroll tick
                                    Shift + scroll: ± 5 BPM
```

### 1.5 Adjusting the Fretboard Window

```
User action                         Application response
──────────────────────────────────────────────────────────────────
Scroll wheel over Fretboard         Shift fret window left / right
Drag fretboard left/right           Same as scroll
Click fret number                   Center window on that fret
Ctrl + scroll over Fretboard        Zoom fretboard (change fret count)
```

### 1.6 Track Management

```
User action                         Application response
──────────────────────────────────────────────────────────────────
Click track name in TrackList       Score + fretboard show that track
Click Mute button                   Track excluded from audio; icon dims
Click Solo button                   All other tracks muted
Drag track volume slider            Volume adjusts in real time
```

---

## 2. Keyboard Shortcuts

### Playback

| Shortcut | Action |
|----------|--------|
| `Space` | Play / Pause toggle |
| `Escape` | Stop (return to start) |
| `L` | Toggle Loop |
| `M` | Toggle Metronome |
| `→` | Advance one beat |
| `←` | Go back one beat |
| `Ctrl+→` | Advance one measure |
| `Ctrl+←` | Go back one measure |
| `Home` | Go to beginning |
| `End` | Go to end |
| `+` / `=` | Increase tempo by 5 BPM |
| `-` | Decrease tempo by 5 BPM |

### Navigation

| Shortcut | Action |
|----------|--------|
| `Ctrl+O` | Open file |
| `Ctrl+S` | Save session |
| `Ctrl+E` | Export |
| `Ctrl+Q` | Quit |
| `Ctrl+=` | Zoom in (Score) |
| `Ctrl+-` | Zoom out (Score) |
| `Ctrl+0` | Reset zoom |
| `F11` | Toggle full screen |
| `Tab` | Cycle focus between panels |

### View

| Shortcut | Action |
|----------|--------|
| `1` | Score mode: Standard notation only |
| `2` | Score mode: Tablature only |
| `3` | Score mode: Both |
| `F` | Toggle fretboard panel visibility |
| `I` | Toggle info panel visibility |
| `T` | Toggle track list sidebar |
| `Ctrl+,` | Open Settings dialog |

### Score Editing (future / optional)

| Shortcut | Action |
|----------|--------|
| `Ctrl+Z` | Undo |
| `Ctrl+Shift+Z` | Redo |
| `Ctrl+C` | Copy selection |
| `Ctrl+V` | Paste |
| `Delete` | Delete selected notes |

---

## 3. Mouse Interactions Summary

| Target | Left Click | Right Click | Scroll | Drag |
|--------|-----------|-------------|--------|------|
| Score note | Select note | Context menu (copy, properties) | Scroll score | — |
| Score measure | Select measure | — | Scroll score | Select range |
| Fretboard fret | Highlight (preview mode) | Note info tooltip | Shift fret window | — |
| Playhead line | Start drag to seek | — | — | Seek |
| Seek bar (empty) | Jump to position | — | — | Seek |
| Panel splitter | — | — | — | Resize panels |
| Track volume | — | — | Adjust volume | Adjust volume |

---

## 4. Drag and Drop

- **Drop a file** onto the main window → opens the file (same as File ▸ Open)
- **Drag a measure** within the Score (edit mode) → reorder measures

---

## 5. Context Menus

### Score Note — Right-click
- Copy note
- Note Properties…
- Jump to bar N
- Select all notes in measure
- Add fingering annotation

### Fretboard Position — Right-click
- Show note name
- Add to custom chord
- Copy fingering

### Track row — Right-click
- Rename track
- Change instrument
- Delete track (edit mode)
