# FretWise

**Guitar Fingering Optimization System**

FretWise reads Guitar Pro files and computes optimal left-hand fingerings using the Viterbi algorithm. It renders the result as a professional PDF tablature with rhythm notation, chord diagrams, and guitar-specific articulations.

---

## Features

- **Multi-format parsing** — Guitar Pro 7/8 (`.gp` / GPIF-XML) and GP3/4/5 (`.gp5`) via PyGuitarPro
- **Viterbi optimizer** — O(N × S²) shortest-path over all valid (string, fret, finger, hand_position) states
- **Biomechanical cost function** — position shift, stretch, string change, finger difficulty, sequential crossing
- **Post-processing resolvers** — finger continuity, section consistency, chord conflicts, chord stretch, chord finger ordering
- **Multi-voice support** — per-voice Viterbi + inter-voice chord integrity pass
- **PDF tab renderer** — A4, rhythm notation (whole/half/quarter/eighth/16th/32nd + flags + beams + rests), let-ring dashes, section markers, tempo, time signature, chord names, finger annotations
- **Chord diagrams** — extracted from GP source, rendered as standard box diagrams with barre and finger numbers, embedded in PDF header and standalone PDF
- **ASCII tab** — plain-text tablature for quick inspection
- **Rhythm legend** — first PDF page shows all note values, rest symbols, and notation guide with per-measure checksums
- **Web UI** — FastAPI player with tab rendering, audio playback, hand visualization, per-song gear sheets
- **ML fingering models** — ONNX models (chord finger classifier, transition cost, phrase-window) refine finger choice, with graceful fallback to rules
- **Partitions library** (`fretwise.partitions`) — Songsterr library management: dedup, TSV index, daily sync, Notion/GDrive sync, download-prompt generation
- **Gear sheets** (`fretwise.gears`) — per-song GP-180/NAM rig sheets: LLM production pipeline + JSON schema + web rendering, delta managed by supersede-by-key
- **Training factory** (`fretwise.dataset`) — dataset harvesting + XGBoost→ONNX training pipeline for the fingering models

---

## Quickstart

```powershell
# Environment (pixi is the reference setup)
pixi install

# Parse a Guitar Pro file (shows note sequence)
pixi run fretwise parse song.gp

# Compute fingerings and export PDF + ASCII tab
pixi run fretwise solve song.gp

# With options
pixi run fretwise solve song.gp --mode performance --output song_fingered.pdf
pixi run fretwise solve song.gp --mode learning --verbose

# Web UI on http://localhost:8080
pixi run web
```

All command-line entry points live in [`scripts/`](scripts/README.md) —
`partitions_*` (library management), `gears_*` (gear-sheet production),
`dataset_*` (model training), plus the main `fretwise` CLI.
See [`docs/usage.md`](docs/usage.md) for end-to-end workflows.

---

## Installation

```powershell
git clone <url> fretwise
cd fretwise
pixi install              # default env: runtime + web + ML inference
pixi install -e train     # + XGBoost/sklearn/ONNX export for model training
```

Without pixi: `pip install -e ".[dev,ml,partitions,train]"` (Python 3.11+).

---

## Architecture

```
fretwise/
├── parser/       M1 — GP file → NoteEvent list (pitch, onset, duration, articulations, hints)
├── generator/    M2 — NoteEvent → all valid FingeringState candidates
├── patterns/     M3 — chord recognition by pitch-class matching
├── scoring/      M4 — composite cost C(s1,s2) = α·C_méca + β·C_music + γ·C_joueur + δ·C_péda
├── optimizer/    M5 — Viterbi shortest-path (interface never changes)
├── profile/      M6 — player profile stub (Phase 5)
├── core/         — notation/engraving engine (ingest → scene → backends)
├── export/       — PDF/SVG/ASCII tab, chord diagrams, GP & MusicXML writers, hand viz
├── ml/           — ONNX inference (finger classifier, transition cost, phrase window)
├── web/          — FastAPI app (player, playback, rig API) + auth/ + storage/
├── partitions/   — Songsterr library management (index, dedup, sync, prompts)
├── gears/        — per-song gear sheets: naming + adapter (consumer), production/ (LLM producer)
├── dataset/      — training factory: parsers, features, XGBoost→ONNX pipeline
├── pipeline.py   — run_pipeline(): per-voice Viterbi + resolver chain
└── cli.py        — Click CLI entry point
```

Full architecture: [`docs/architecture.md`](docs/architecture.md).

### Cost function

```
C(s1, s2) = α·C_méca(s1, s2) + β·C_music(s1, s2) + γ·C_joueur(s1, s2) + δ·C_péda(s1, s2)
```

| Mode | α | β | γ | δ |
|---|---|---|---|---|
| `reference` | 1 | 1 | 0 | 0 |
| `performance` | 1 | 0.5 | 2 | 0 |
| `musical` | 1 | 2 | 1 | 0 |
| `learning` | 1 | 0.5 | 1 | 1.5 |

---

## Testing

```powershell
pytest -v                          # run all 358 tests
pytest --cov=fretwise              # with coverage
python scripts/run_fingering.py    # benchmark all 36 GP files → docs/benchmarks/
```

---

## Output examples

Each file in `tests/fixtures/` produces three outputs in `docs/benchmarks/`:

- `*_tab.pdf` — full PDF tablature with rhythm notation and chord diagrams
- `*_tab.txt` — ASCII tablature
- `*_report.txt` — per-note fingering report

---

## Project status

| Phase | Description | Status |
|---|---|---|
| Phase 1 — MVP | Parser + Viterbi + ASCII/PDF export | ✅ Complete |
| Phase 2 — Notation enrichment | Bend, slide, harmonic, PM, tapping symbols; rhythm notation | ✅ Complete |
| Phase 3 — Chord diagrams | Extraction from GP, PDF header, standalone PDF | ✅ Complete |
| Phase 4 — Musical intelligence | C_music, MusicXML/MIDI parsers, pattern DB, web UI | ✅ Complete |
| Phase 5 — Player profile | Morphological parameters, calibration, web UI | Planned |
| Phase 6 — AI / ML | Learned cost function, RLHF, N-gram discovery | ⚠️ Partial — ONNX fingering models (chord classifier, transition cost, phrase-window v2) shipped and in production via `fretwise.ml` / `fretwise.dataset`; original LSTM/Transformer + RLHF scope still open |
| Phase 7 — Utility consolidation | Partitions library, gear-sheet production, ML training factory merged into `fretwise.*` + `scripts/` | ✅ Complete |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for detailed plans, [`docs/Chansons_creation_workflow.md`](docs/Chansons_creation_workflow.md) for the end-to-end song workflow, and [`STATUS.md`](STATUS.md) for current state.
