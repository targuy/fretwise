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

### 2D — Standard Music Notation PDF
- Treble clef staff, notes, stems, beams, accidentals, ties, slurs
- Time signature, key signature, barlines, dynamics, articulation marks
- Architecture: `StaffRenderer` in `fretwise/export/staff_renderer.py`
- **Status: Planned (Phase 4)**

### 2E — Combined Notation + Tablature PDF
- Top half: standard notation staff; bottom half: tab (aligned beat columns)
- Module: `fretwise/export/combined_renderer.py`
- **Status: Planned (Phase 4)**

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

## Architecture Principles

1. **M5/Viterbi interface is stable** — never modify its public API. The cost function is always injected, never hardcoded.
2. **Cost injection** — α, β, γ, δ weights are always external parameters (`CostWeights`); no magic numbers.
3. **Data richness before calculation** — ALL information from the source file (GP, MusicXML, MIDI) must be captured in the data model (`NoteEvent`, `ChordDiagram`) before any solver runs. The solver only sees what the parser captured. Never infer notation from pitch alone.
4. **Separate data / solver / renderer** — each layer has a clean contract. Parser → models → optimizer → renderer. No renderer logic in the solver, no solver logic in the parser.
5. **Independent module evolution** — M1–M6 can change internally as long as the shared data contracts (`NoteEvent`, `FingeringState`, `FingeringResult`) are respected.

---

## Phase 4 — Musical Intelligence

- `C_music` cost function: articulation matching bonus (hammer-on prefers same string, slide prefers adjacent), same-string legato bonus, vibrato position reward
- Pattern database M3: chord shape library (`data/patterns/chords.yaml`), scale pattern library (`data/patterns/scales.yaml`), recognition via pitch-class matching
- MusicXML parser (M1v2): `music21`-based adapter for `.xml` and `.mxl` files
- MIDI parser: `mido`/`pretty_midi` adapter for `.mid` files
- Standard notation PDF (`StaffRenderer`) + combined notation+tab PDF
- Concordance validation against Iino et al. 2025 benchmark (40 annotated études)

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
