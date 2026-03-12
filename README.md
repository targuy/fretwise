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

---

## Quickstart

```powershell
# Activate virtual environment
.\.venv\Scripts\Activate.ps1

# Parse a Guitar Pro file (shows note sequence)
fretwise parse song.gp

# Compute fingerings and export PDF + ASCII tab
fretwise solve song.gp

# With options
fretwise solve song.gp --mode performance --output song_fingered.pdf
fretwise solve song.gp --mode learning --verbose
```

---

## Installation

```powershell
git clone <url> fretwise
cd fretwise
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

**Requirements:** Python 3.11+, see `pyproject.toml` for dependencies.

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
├── export/
│   ├── pdf_tab.py         — PDF tablature renderer
│   ├── ascii_tab.py       — ASCII tab renderer
│   └── chord_diagram.py   — chord box diagram renderer
├── pipeline.py   — run_pipeline(): per-voice Viterbi + resolver chain
└── cli.py        — Click CLI entry point
```

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
| Phase 4 — Musical intelligence | C_music, MusicXML/MIDI parsers, pattern DB | Planned |
| Phase 5 — Player profile | Morphological parameters, calibration, web UI | Planned |
| Phase 6 — AI / ML | Learned cost function, RLHF, N-gram discovery | Planned |

See [`docs/ROADMAP.md`](docs/ROADMAP.md) for detailed plans and [`STATUS.md`](STATUS.md) for current state.
