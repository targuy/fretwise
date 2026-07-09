# FretWise — Roadmap

## ✅ Phase 1 — MVP (DONE)

**What was built:**
- Full project scaffolding: `pyproject.toml`, GitHub Actions CI, ruff/mypy config
- Core data models: `NoteEvent`, `FingeringState`, `FingeringResult` with strict typing
- M1 Parser: `GpifAdapter` for GP7/8 (`.gp` ZIP/GPIF-XML), `GuitarProAdapter` for `.gp3/.gp4/.gp5` via PyGuitarPro
  - Multi-voice support (`voice_hint`), hint-based tuning fallback, section markers
  - Score-based guitar track selection (explicit type + string count)
- M2 Generator: `StateGenerator` — all valid (string, fret, finger, hand_position) states per pitch
- M4 Scoring: composite mechanical cost `C_méca` — position shift, stretch, string change, finger difficulty, sequential crossing
  - Post-processing resolvers: finger continuity, section consistency, chord conflicts, chord stretch, chord finger ordering, chord finger span, chord string diagonal
- M5 Optimizer: `ViterbiOptimizer` (O(N×S²)) with injected cost function
- `pipeline.py`: per-voice Viterbi + multi-pass resolver chain, `split_by_voice()`, `run_pipeline()`
- Export: ASCII tab renderer, PDF tab renderer (A4, proportional layout, let-ring dashes, chord names, rhythm stems/beams, section markers)
- CLI: `fretwise parse`, `fretwise solve`
- 203+ tests passing, benchmark script across 36 GP files

---

## ✅ Phase 2 — Notation Enrichment (DONE)

### 2A — Data Model Enrichment ✅
- Enriched `NoteEvent` with all guitar notation fields: bend (value + type), slide type, harmonics (type + overtone fret), muted, palm mute, tapping, accent, accent strong, tremolo picking, vibrato wide
- Added `BendType`, `SlideType`, `HarmonicType` string-constant classes to `models.py`
- Added new `Articulation` enum values: `WIDE_VIBRATO`, `HARMONIC`, `TAPPING`, `MUTED`, `TREMOLO`
- All new fields have defaults → fully backward-compatible

### 2B — GP Parser Enrichment ✅
- `GpifAdapter`: parse all notation from GPIF XML — bend points, slide flags, harmonic type/fret, palm mute, tapping, accent (note + beat level), tremolo picking, wide vibrato
- `GuitarProAdapter`: read corresponding fields from PyGuitarPro's beat/note objects for `.gp3/.gp4/.gp5`

### 2C — Tab PDF Rhythm Notation ✅
- **Convention correcte** : l'ovale fret IS le notehead (jamais de ronds au-dessus de la table)
- **Ronde** : ovale visible + pas de hampe
- **Blanche** : ovale visible (trait noir) + hampe
- **Noire/croche/double croche** : fond blanc invisible + hampe
- **Crochets** : 1 flag = croche, 2 = double croche, 3 = triple croche
- **Ligatures** (beaming) pour groupes de croches/doubles croches dans la mesure
- **Silences** : pause, demi-pause, soupir, demi-soupir, quart de soupir (symboles corrects)
- **Checksum par mesure** : `Σ=X.XX` en rouge au-dessus si déviation > 0.1 beat
- **Page de légende** : toutes les valeurs de notes + silences + guide symboles (H, P, T, >, >>, !)

### 2D — Standard Music Notation PDF ✅
- Treble clef staff, notes, stems, flags, accidentals, ledger lines
- Time signature, barlines, measure numbers, section markers
- Architecture: `StaffRenderer` in `fretwise/export/staff_renderer.py`
- **Status: Implemented in Sprint 4D**

### 2E — Combined Notation + Tablature PDF ✅
- Top half: standard notation staff; bottom half: tab (aligned beat columns)
- Module: `fretwise/export/combined_renderer.py`
- **Status: Implemented in Sprint 4D**

---

## ✅ Phase 3 — Chord Diagrams (DONE)

### 3A — Chord Data Extraction ✅
- `ChordDiagram` dataclass: `name`, `frets` (-1=muted/0=open/>0=fret), `string_count`, `base_fret`, `source_id`, `fingers`
- `_parse_diagram_collection()` in `GpifAdapter`: reads `DiagramCollection` from GPIF XML
- `_compute_chord_fingers()`: auto-assigns finger 1–4 in ascending fret order; equal-fret strings share finger number (barre detection)
- `adapter.chord_diagrams` attribute available after `parse_track()`

### 3B — Chord Diagram Renderer ✅
- `draw_chord_diagram()` in `fretwise/export/chord_diagram.py`
- Open circles with finger number inside (not filled black dots)
- Barre: filled rounded bar with finger number centered in white
- X (muted) and O (open) markers above diagram
- Nut (thick bar) when `base_fret == 0`; Roman numeral label when `> 0`
- `render_chord_diagrams_pdf()`: standalone A4 PDF grid of all diagrams

### 3C — Chord Diagrams in PDF Headers ✅
- Compact diagram strip on the legend page (max 8 per row)
- Passed from `run_fingering.py` to `render_pdf_tab()` via `chord_diagrams` parameter
- Shown only when source GP file contains named chord definitions

---

## ✅ Phase 3.5 — PDF Rendering v2 (DONE)

> Full specification in `docs/rendering_spec_v2.md`. All 12 RENDER tasks implemented.

### P0 — Critical Readability Bugs ✅
- **RENDER-01**: Rests drawn inside staff vertically (at `sys_y - REST_CENTER_Y` = midpoint strings 3–4), white disc for small rests erases string lines
- **RENDER-02**: Rests break beam groups — `_get_beam_groups()` detects gaps ≥ 0.115 beats between note end and next onset
- **RENDER-03**: Beat-aware beam grouping — groups split at beat boundaries (max 2 eighths or 4 sixteenths per beat in 4/4)

### P1 — Layout & Proportionality ✅
- **RENDER-04**: Variable measure widths — `_measure_w_raw()` computes density-based width, `_normalize_measure_widths()` scales to fill page
- **RENDER-05**: Variable measures per system — `_build_systems()` greedy algorithm packs measures until they exceed `available_w × 1.05`
- **RENDER-06**: Partial secondary beams — `_draw_secondary_beam()` renders 16th-note bars only over consecutive sub-eighth runs within a group
- **RENDER-07**: Text zone separation — `CHORD_Y=22pt`, `MNUM_Y=31pt`, `SECTION_Y=ABOVE_STRINGS-4pt`; chord name truncation with `…`

### P2 — Visual Quality ✅
- **RENDER-08**: Finger annotation collision avoidance — clearance check against next string's oval; shift 3.5pt left when tight
- **RENDER-09**: Stem height reduced — `STEM_H = 14pt` (was 16pt)
- **RENDER-10**: Legend layout spacing fixed — REST_ROW_Y properly offset from dotted-notes row
- **RENDER-11**: Rest symbols in legend use same `_draw_rest()` with white disc as real rendering
- **RENDER-12**: Post-render collision checker — `collision_checker.py` with BBox tracking

---

## Architecture Principles

1. **M5/Viterbi interface is stable** — never modify its public API. The cost function is always injected, never hardcoded.
2. **Cost injection** — α, β, γ, δ weights are always external parameters (`CostWeights`); no magic numbers.
3. **Data richness before calculation** — ALL information from the source file (GP, MusicXML, MIDI) must be captured in the data model (`NoteEvent`, `ChordDiagram`) before any solver runs. The solver only sees what the parser captured. Never infer notation from pitch alone.
4. **Separate data / solver / renderer** — each layer has a clean contract. Parser → models → optimizer → renderer. No renderer logic in the solver, no solver logic in the parser.
5. **Independent module evolution** — M1–M6 can change internally as long as the shared data contracts (`NoteEvent`, `FingeringState`, `FingeringResult`) are respected.

---

## Phase 4 — Musical Intelligence ✅

### Sprint 4A — Musical Cost Function `C_music` ✅
- ✅ **Legato same-string requirement**: hammer-on, pull-off, and legato penalised when crossing strings (penalty 5.0)
- ✅ **Slide same-string requirement**: all slide types penalised across strings (penalty 5.0)
- ✅ **Vibrato position quality**: open string impossible (4.0), low frets awkward (1.5), wide vibrato extra penalty (1.0)
- ✅ **Bend feasibility**: open string impossible (6.0), wound strings scaled by bend value (1.5× for strings 5-6, 0.8× for string 4)
- ✅ **Natural harmonic matching**: wrong fret for harmonic_fret penalised (4.0)
- ✅ **Tapping low-fret penalty**: tapping near the nut harder (1.5 when fret < 5)
- ✅ Implementation: `compute_musical_cost(s1, s2, note) -> float` in `scoring/__init__.py`
- ✅ Wired into `CostFunction.transition_cost()` via β weight (replaces `c_music = 0.0` stub)
- ✅ 20+ unit tests + 2 integration tests (393 total, 5 skipped, 0 regressions)

### Sprint 4B — Pattern Database M3 ✅
- ✅ **Chord voicings expanded**: +15 entries in `chord_voicings.yaml` — diminished (Bdim, C#dim), augmented (Caug, Eaug), ninth (G9, A9, E9), barre shapes (F#, F#m, Bb, Bbm, C#, C#m, Eb, Ebm, Ab). Now ~80+ voicings.
- ✅ **Scale pattern library**: `data/patterns/scales.yaml` — 10 scale types (major, natural_minor, harmonic_minor, minor/major_pentatonic, blues, dorian, mixolydian, phrygian, lydian) with box positions
- ✅ **Scale recognition**: `scale_library.py` — `recognize_scale(pitches)` tries 12 roots × 10 patterns, confidence scoring, prefers 7-note specificity over pentatonic subsets
- ✅ **PatternMatcher rewrite**: `patterns/__init__.py` — full `PatternMatcher` with chord promotion (group by onset → recognize chord → lookup voicing → reorder states) and scale promotion (detect prevailing scale → promote in-scale pitch-class states). Never removes states, only reorders.
- ✅ **Pipeline wiring**: `PatternMatcher` injected into `run_pipeline()` (optional, backward-compatible), wired in `cli.py` and `run_fingering.py`
- ✅ 33 tests across 8 classes (422 total, 5 skipped, 0 regressions)

### Sprint 4C — Multi-Format Parsers ✅
- ✅ **MusicXML adapter**: `MusicXmlAdapter` in `musicxml_adapter.py` — parses `.xml`, `.mxl`, `.musicxml` via music21. Guitar part selection (MIDI program → name → first). Handles chords, tied notes (skips continuations), rehearsal marks, tempo changes, velocity→Dynamic mapping.
- ✅ **MIDI adapter**: `MidiAdapter` in `midi_adapter.py` — parses `.mid`, `.midi` via pretty_midi. Guitar instrument selection (MIDI program → name → pitch range → first non-drum). Seconds-to-beats conversion with tempo change tracking. Velocity→Dynamic mapping.
- ✅ **Auto-detection**: `get_adapter()` updated to route `.xml/.mxl/.musicxml` → MusicXmlAdapter, `.mid/.midi` → MidiAdapter
- ✅ **CLI updated**: `_SUPPORTED_INPUT` expanded, help text and docstrings updated for all commands
- ✅ **No string/fret hints**: MusicXML and MIDI carry no tab data — `string_hint` and `fret_hint` are None; the state generator enumerates all valid positions
- ✅ 59 new tests (21 MusicXML + 38 MIDI): supports, errors, integration with real files, dynamic mapping, pure functions, get_adapter routing (481 total, 5 skipped, 0 regressions)

### Sprint 4D — Validation & Standard Notation ✅
- ✅ **Concordance validation framework**: `validation.py` — `ConcordanceReport` dataclass with string/fret/position concordance metrics; `compute_concordance()` compares optimizer output vs source tab hints; `format_concordance_report()` human-readable output with deviation table
- ✅ **Validation script**: `scripts/validate_concordance.py` — processes all GP fixtures, per-track + aggregate reporting
- ✅ **Baseline result**: **99.98% position concordance** — 36,223/36,230 hinted notes match across 23 tracks (6 GP files). Only 3 tracks with minor deviations: Ziggy Stardust Guitar II (99.3%), Green Day Lead (99.9%), Metallica Lead (99.7%)
- ✅ **StaffRenderer**: `export/staff_renderer.py` — standard music notation PDF with treble clef, 5-line staff, filled/open noteheads, stems (up/down by pitch), flags (eighth/sixteenth/32nd), accidentals (sharps), ledger lines (above/below), bar lines, time signature, measure numbers, section markers. Same page geometry as pdf_tab.py for alignment.
- ✅ **CombinedRenderer**: `export/combined_renderer.py` — stacks treble clef staff above tab for each system. Delegates to StaffRenderer (notation) and pdf_tab (tab) drawing helpers. Shares measure grouping/packing for column alignment.
- ✅ **CLI wiring**: `--format staff` and `--format combined` output options added to `fretwise solve`. Updated format list and help text.
- ✅ **Export `__init__.py` updated**: `render_staff_pdf` and `render_combined_pdf` exported
- ✅ 28 new tests: 6 staff smoke (file creation, empty, multi-measure, sections, accidentals, ledger lines) + 3 combined smoke + 12 staff helper unit tests (midi_to_staff_pos, staff_pos_to_y, num_flags, is_filled) + 7 concordance validation tests (import, empty, perfect, deviation, unhinted, format_report)
- ✅ **509 total tests**, 5 skipped, 0 regressions

### Sprint 4E — Songsterr-style Web Interface ✅
- ✅ **FastAPI backend** (`web/app.py`): `create_app(fixtures_dir)` factory; endpoints: GET `/api/files` (list score files), GET `/api/tracks/{filename}` (multi-track listing via list_guitar_tracks), GET `/api/solve/{filename}?track_id=N&mode=M` (full pipeline execution → JSON). Path traversal protection. Serializes all 20+ notation fields per note + chord diagrams + section markers.
- ✅ **HTML5 SPA** (`web/static/index.html`): 3-page routing (file selector → track selector → tab viewer), dark header bar, Songsterr-style green accents, responsive CSS, bottom toolbar with playback controls.
- ✅ **Canvas tab renderer** (`web/static/js/renderer.js`): 6-string tab staff with TAB label, string names, fret numbers in white ovals, measure grouping, tempo/time signature display, section markers, chord names, measure numbers, barlines, cursor highlight. System-based layout with greedy measure packing.
- ✅ **Notation symbols**: hammer-on/pull-off arcs with H/P label, bend arrows with fraction labels (½, 1, 1½, 2), slide diagonal lines (legato + shift + in/out), vibrato waves (normal + wide), harmonics (diamond shape), palm mute (P.M.), tapping (T), accents (>/∧), staccato (dot), tremolo picking (slashes on stem), let-ring dashed lines, dotted notes, finger annotations (dark red SW), muted notes (X). Same visual conventions as PDF renderer.
- ✅ **Rhythm below tab** (Songsterr convention): stems, beams (primary + secondary for 16ths), flags, rest symbols (whole/half/quarter/eighth/sixteenth). Beams grouped by beat.
- ✅ **Visual playback** (`web/static/js/playback.js`): `PlaybackEngine` — measure-by-measure cursor at song tempo, speed scaling (25–125%), loop mode, metronome (Web Audio API click), keyboard shortcuts (Space=play, ←→=prev/next, Home/End, M=metronome), auto-scroll to cursor.
- ✅ **Tab notation legend**: interactive overlay canvas showing all symbols (techniques, rhythm, dynamics, structure) with French + English descriptions.
- ✅ **CLI command**: `fretwise web [--dir DIR] [--port PORT] [--host HOST]` launches the uvicorn server serving the full SPA.
- ✅ Dependencies: FastAPI ≥ 0.110, uvicorn[standard] ≥ 0.29 (added to pyproject.toml dev extras)
- ✅ 509 tests still passing, 0 regressions

---

## Phase 5 — Player Profile

- `PlayerProfile` dataclass: morphological parameters (hand span, finger independence) + dexterity scores
- Calibration exercises: short GP snippets with known difficulty, scored live
- `C_joueur` cost function using profile parameters
- Profile storage: JSON (MVP) → SQLite (Phase 5+)
- Web interface: FastAPI backend + React frontend for profile management and score display

---

## Phase 6 — AI / Machine Learning

- Learned hybrid cost function: LSTM or Transformer trained on (NoteEvent sequence, FingeringResult sequence) pairs
- RLHF pipeline: player corrections feed back into cost function weights
- N-gram pattern discovery: mine the DadaGP corpus for common fingering sequences
- Transfer learning from the Iino 2025 annotated dataset as training seed

---

## Data Architecture Principle

> **"Data richness before calculation"**: ALL information from the source file (GP, MusicXML, MIDI) must be captured in the data model (`NoteEvent`, `ChordDiagram`) before any solver runs. The solver only sees what the parser captured. Never infer notation from pitch alone.

This principle ensures that notation symbols (bends, slides, harmonics, muted notes) are correctly preserved through the pipeline and accurately rendered in the output, regardless of whether the optimizer uses them in its cost function at any given phase.

---

## ✅ Phase 7 — Consolidation des utilitaires (juillet 2026)

Les trois projets utilitaires ont été consolidés dans FretWise
(voir [architecture.md](architecture.md) §3 et [usage.md](usage.md)) :

- ✅ `iCloudDrive\partitions` → `src/fretwise/partitions/` (16 modules, chemins/IDs
  Notion centralisés, orchestrateur sans subprocess) + 13 wrappers `scripts/partitions_*.py`
- ✅ `SongsGear\SongsGears` → `src/fretwise/gears/production/` (pipeline LLM, schémas
  rig.v1/gear.v2, outils compact/export/normalize/validate/batch, naming unifié dans
  `fretwise.gears.naming`) + 10 wrappers `scripts/gears_*.py`
- ✅ `GuitarDataSet` → `src/fretwise/dataset/` (parsers, features source-de-vérité,
  exporters, pipeline build/train/export ONNX) + 13 wrappers `scripts/dataset_*.py`
- ✅ Tous les CLI regroupés dans `scripts/` (inventaire : [scripts/README.md](../scripts/README.md)),
  tâches pixi pour les commandes courantes, environnement `train` dédié
- ✅ Tests : `test_partitions_lib.py` (16), `test_gears_production.py` (25),
  `test_dataset_port.py` ; non-régression ML/gears/web verte ; ruff propre sur les
  trois packages ; 127 fichiers AppleDouble `._*` purgés

### Reste à faire — tests
- [ ] Test de parité complet entraînement↔inférence pour `transition_cost` et
  `finger_classifier` (le test de parité couvre phrase_window ; généraliser via
  les calibrations JSON de `data/models/`)
- [ ] Tests d'intégration `gears_production_batch` (mock des providers HTTP,
  checkpoint/resume) et `partitions_notion_sync` (requests mocké)
- [ ] Corriger les 28 échecs préexistants `test_web_hand_viz_*` /
  `test_core_scene_svg` / `test_visual_standard_tab` (indépendants de la
  consolidation — liés au chantier hand-viz/playback en cours)
- [ ] mypy strict sur les packages portés (le code hérité n'est pas typé strict)

### Reste à faire — implémentations
- [ ] Adapter les watchers PowerShell iCloud (`_watch_partitions.ps1`,
  `_maintain_partitions.ps1`, `run-*.ps1`, tâches planifiées) pour appeler
  `scripts/partitions_*.py` du repo (substitutions détaillées dans le rapport de
  portage ; poser `FRETWISE_PARTITIONS_ROOT` suffit ensuite)
- [ ] Fusionner les tables GP-180 dupliquées : `gears/production/fretwise_export.py`
  (MODULE_BY_MODEL/alias) vs `fretwise/rig.py` (_canon_effect/GP180_CHAIN)
- [ ] Réconcilier définitivement les IDs Notion (canoniques vs `LEGACY_*` dans
  `partitions/notion_ids.py` — vraisemblablement database-id API vs data-source-id MCP)
- [ ] Régénérer `phrase_window` v2 côté entraînement : v2 est actif en prod mais
  seuls les artefacts v1 existent côté dataset (recette v1→v2 à rejouer/documenter)
- [ ] `transition_cost_v4` : spec draft 55 features + extracteur existent,
  entraînement jamais lancé
- [ ] Export Guitar Pro from scratch (bloque MusicXML → GP, cf. plan court terme CLAUDE.md)

### Reste à faire — nettoyage (code mort / orphelins identifiés)
Racine du repo : `_archive_dupes.py`, `_diff_missing.py`, `_find_dupes.py`
(one-shots pointant l'ancien lib iCloud — remplacés par `fretwise.partitions`),
`inspect_measures.py`, `app_full.diff`, `patch_gears.diff`, `killing_solve.json`,
`debug.png`, `rising_sun_test.svg`, `sultans_test.svg`, `WASimClient.log*` (hors
sujet), fichiers vides `canonical-` et `scene`, `_tmp_after_fingerings/`,
`maintenance_backups/` (à archiver hors repo). `scripts/` : `run_fingering.py` et
les éval golden historiques à réévaluer après stabilisation du pipeline dataset.
Anciens dépôts : `SongsGear/`, `GuitarDataSet/` et les scripts Python de
`iCloudDrive\partitions` deviennent des archives en lecture seule (données
brutes d'entraînement toujours référencées via `FRETWISE_DATASET_ROOT`).

### Évolutions envisagées
- [ ] Intégrer les wrappers dans le CLI click (`fretwise partitions …`,
  `fretwise gears …`, `fretwise dataset …`) en gardant les wrappers comme alias
- [ ] Rapatrier les données d'entraînement de `FRETWISE_DATASET_ROOT` vers un
  stockage versionné (DVC ou S3 via `fretwise.storage`)
- [ ] Watcher Downloads multiplateforme en Python (remplacer les .ps1)
