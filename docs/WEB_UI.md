# Web UI — FastAPI app + SPA

> Implementation: `src/fretwise/web/app.py` (FastAPI factory + endpoints) and `src/fretwise/web/static/` (vanilla HTML/CSS/JS SPA). Launched via `fretwise web` or `fretwise gui` (gui = web + open browser).

---

## App factory

`create_app(fixtures_dir: Path | None = None) -> FastAPI`

- Default `fixtures_dir` = `partitions/` at repo root (personal score library, gitignored).
- Mounts `/static` from `src/fretwise/web/static/`.
- Injects a no-cache middleware on `/static/*.js` and `/static/*.css` to prevent stale assets during development.
- Module-level `app = create_app()` is the ASGI entry point used by uvicorn.

---

## API endpoints

| Method | Path | Purpose |
|---|---|---|
| GET | `/` | Serves `static/index.html` (the SPA shell). |
| GET | `/api/files` | Lists score files in `fixtures_dir` whose extension is in `{.gp3, .gp4, .gp5, .gp, .xml, .mxl, .musicxml, .mid, .midi}`. Returns `[{name, stem, format}]`. |
| GET | `/api/tracks/{filename}` | Lists guitar tracks. GP adapters use `list_guitar_tracks(filepath)`; MusicXML/MIDI return a synthetic single track. Returns `[{id, name, tuning}]`. |
| GET | `/api/notes/{filename}` | Light endpoint: runs the legacy pipeline only and returns the fingered note list. Used by the multi-track audio mixer to load secondary tracks without re-rendering. Query params: `track_id`, `same_finger_motion_penalty`, `infer_implicit_legato`. |
| GET | `/api/solve/{filename}` | Full pipeline: runs legacy fingering + core notation pipeline. Returns metadata (title/artist/track_name/tempo/beats_per_measure), section markers, chord diagrams, `core_svg` string, `core_conformance_issues` count, `measure_regions` (for SVG cursor), `stats`, and serialized `results`. Query params: `track_id`, `representation_mode`, `same_finger_motion_penalty`, `infer_implicit_legato`. |
| GET | `/api/export/pdf/{filename}` | Renders a PDF via `core/backends/render_scene_to_pdf_bytes`. Response headers include `X-Fretwise-Pdf-Engine: core`, `X-Fretwise-Conformance-Issues`, `X-Fretwise-Conformance-Report`. Query params: `track_id`, `representation_mode`. |
| POST | `/api/upload` | Uploads a new score file into `fixtures_dir`. Validates the extension and sanitises the filename (basename only). |
| GET | `/api/soundfont` | Streams `data/sounds/Shan SGM-Pro 11.SF2` for in-browser SF2 synthesis. Returns 404 when absent (the file is gitignored due to size). |

### Path-traversal protection

All file lookups route through `_resolve_file(app, filename)` which:
1. Takes the basename only (`Path(filename).name`).
2. Joins with `fixtures_dir`.
3. Calls `.resolve().relative_to(fixtures_dir.resolve())` and raises 403 on `ValueError`.

### Representation-mode parsing

`_parse_representation_mode(value)` normalises arbitrary spellings to `RepresentationMode`:
- `""` → `STANDARD_TAB` (default)
- `tab` / `tablature` → `TAB`
- `staff` / `standard` / `notation` → `STANDARD`
- `standard_tab` / `standard_tablature` / `hybrid` / `mixed` → `STANDARD_TAB`
- `tab_rhythm` / `tablature_rhythm` / `tab_and_rhythm` / `tablature_and_rhythm` → `TAB_RHYTHM`

Unknown values → HTTP 400. The canonical mode strings are owned by `core/notation_mode.py`.

---

## Static SPA

`src/fretwise/web/static/` layout:

```
static/
├── index.html              ← single-page shell
├── login.html              ← auth pages (multi-user mode only)
├── register.html
├── css/
│   ├── style.css           ← base design tokens + layout
│   ├── leather-icons.css   ← wood/metal theme: knob-icon classes + wood backgrounds
│   └── auth.css            ← login/register theme (wood plaque + copper buttons)
├── hand_viz.html           ← optional hand-viz prototype (consumes hand_viz_data.json)
├── js/
│   ├── main.js             ← routing: file picker → track picker → tab viewer
│   ├── api.js              ← REST helpers
│   ├── icons.js            ← swaps button glyphs for the metallic knob icon set
│   ├── modeConfig.js       ← MIRROR of core/notation_mode.py — keep in sync
│   ├── renderer.js         ← Canvas tab renderer (Songsterr-style)
│   ├── svg-playback.js     ← consumes /api/solve `core_svg` + measure_regions
│   ├── playback.js         ← cursor / speed / loop / metronome
│   ├── lib/                ← in-tree helpers
│   └── vendor/             ← third-party libs (e.g. soundfont synth)
└── img/
    ├── wood/               ← generated wood tiles (scripts/slice_wood.py)
    ├── icons/              ← generated knob icons (scripts/build_leather_icons.py)
    ├── backgrounds.png            ← SOURCE sheet: wood tiles (light/dark, all borders)
    └── backgrounds with knobs.png ← SOURCE sheet: same tiles + metal knob
```

Key conventions:
- **Mode strings**: the 4 canonical values (`standard`, `tablature`, `standard_tablature`, `tablature_rhythm`) live in both `core/notation_mode.py` (Python) and `static/js/modeConfig.js` (JS). When adding a mode, update both and update `_parse_representation_mode` aliases.
- **Cursor positioning**: `svg-playback.js` overlays a cursor on the `core_svg` using `measure_regions` (`{measure_idx, x, y0, y1, width}`) returned by `/api/solve`.
- **PDF download**: `/api/export/pdf/{filename}` is the only PDF route; the legacy `export/pdf_tab.py` is not exposed via the web app.
- **Keyboard shortcuts**: Space = play/pause, ← → = prev/next, M = metronome (handled in `playback.js`).

---

## Visual theme — wood + metal knobs

The whole UI is skinned as a wood-panelled amp: **dark rosewood** chrome (header,
toolbar, track-tabs, body) and **light maple** reading panels (library, settings,
song-info, floating panels, auth cards), with every button rendered as a brushed
**metal knob** carrying its symbol engraved into the metal.

Two build scripts produce all the artwork from the designer's source sheets. The
generated PNGs are committed (so the app needs no build step), but re-run the
scripts whenever the source sheets or glyph definitions change.

### `scripts/slice_wood.py` — wood tiles

- **Input:** `static/img/backgrounds.png` (1407×768 contact sheet — 8×4 grid of
  light/dark wood tiles in every border variant; `backgrounds with knobs.png` is
  the same set with a knob, kept for reference).
- **Output:** `static/img/wood/`
  - `dark.png` / `light.png` — seamless mirror-tiled base tiles (used **uncut**,
    `background-repeat`, native 128px). Cores are cropped from verified *clean*
    interior boxes so no bright cell-edge lands on the mirror fold (a stray light
    row would otherwise double into a visible seam line).
  - `dark-strip.png` — wide chrome band.
  - `light-frame.png` / `dark-frame.png` — fully-framed plaques cropped to the
    frame's outer edge, for CSS `border-image` 9-slice on panels/cards.

### `scripts/build_leather_icons.py` — knob icons

- **Input:** `static/img/icons/ICON.png` (the metallic volume-knob model).
- **Output:** `static/img/icons/<name>.png` + `@2x` — one transparent icon per
  `manifest.json` entry: the button's glyph **engraved** into the brushed-metal
  disc (intaglio emboss via `_engrave()` — lit lower-right edge, recessed
  upper-left). `_knob_base.png` / `_disc_base.png` / `_contact.png` are build
  intermediates (untracked).
- The glyph for each icon name is a vector primitive in the `GLYPHS` dispatch
  table; add a button by adding a `manifest.json` entry + a `GLYPHS` lambda.

### Wiring (CSS/JS)

- `css/leather-icons.css` — `--wood-dark`/`--wood-light` tile vars; paints the
  knob-icon classes (`.fw-ico--<name>`); applies dark wood to chrome and light
  maple to panels. Light panels work by **re-tokening** `--fg`/`--bg` on the
  container, which flips the whole subtree to dark-ink-on-light automatically.
- `js/icons.js` — reads `icons/manifest.json` and swaps each mapped button's
  inline glyph for a `.fw-ico` span. Idempotent; safe to call after dynamic UI
  (re)builds.
- `css/auth.css` — login/register: maple plaque card with the carved wood frame,
  copper machined buttons, on the dark wood backdrop. Only visible in multi-user
  mode (single-user serves `index.html` directly with no auth).

### Regenerating

```bash
python scripts/slice_wood.py          # wood tiles  → img/wood/
python scripts/build_leather_icons.py # knob icons  → img/icons/*.png (+ legacy BACKGROUND)
```

> Pillow is the only dependency. `build_leather_icons.py`'s `__main__` also
> rebuilds the legacy `BACKGROUND.png`, which the CSS no longer references —
> import `generate_all()` directly to regenerate only the icons.

---

## Launching

```powershell
# Headless server
fretwise web --port 8000 --host 127.0.0.1 --dir partitions/

# Server + auto-open browser (CLI default when invoked with no subcommand)
fretwise gui
python -m fretwise
```

`fixtures_dir` defaults to `<repo>/partitions/` — the personal score library (gitignored). Override with `--dir` for a different corpus (e.g. `tests/fixtures/`).
