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
├── css/style.css
├── hand_viz.html           ← optional hand-viz prototype (consumes hand_viz_data.json)
├── js/
│   ├── main.js             ← routing: file picker → track picker → tab viewer
│   ├── api.js              ← REST helpers
│   ├── modeConfig.js       ← MIRROR of core/notation_mode.py — keep in sync
│   ├── renderer.js         ← Canvas tab renderer (Songsterr-style)
│   ├── svg-playback.js     ← consumes /api/solve `core_svg` + measure_regions
│   ├── playback.js         ← cursor / speed / loop / metronome
│   ├── lib/                ← in-tree helpers
│   └── vendor/             ← third-party libs (e.g. soundfont synth)
```

Key conventions:
- **Mode strings**: the 4 canonical values (`standard`, `tablature`, `standard_tablature`, `tablature_rhythm`) live in both `core/notation_mode.py` (Python) and `static/js/modeConfig.js` (JS). When adding a mode, update both and update `_parse_representation_mode` aliases.
- **Cursor positioning**: `svg-playback.js` overlays a cursor on the `core_svg` using `measure_regions` (`{measure_idx, x, y0, y1, width}`) returned by `/api/solve`.
- **PDF download**: `/api/export/pdf/{filename}` is the only PDF route; the legacy `export/pdf_tab.py` is not exposed via the web app.
- **Keyboard shortcuts**: Space = play/pause, ← → = prev/next, M = metronome (handled in `playback.js`).

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
