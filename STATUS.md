# FretWise — Statut du projet

> Dernière mise à jour : 2026-03-18

---

## Statut global

| Phase | Description | Statut |
|---|---|---|
| **Phase 1 — MVP** | Parser + Viterbi + ASCII/PDF export | ✅ **COMPLÈTE** |
| **Phase 2 — Notation enrichment** | Enrichissement modèle + symboles PDF | ✅ **COMPLÈTE** |
| **Phase 3 — Chord diagrams** | Extraction GP + rendu PDF | ✅ **COMPLÈTE** |
| **Phase 3.5 — PDF Rendering v2** | Layout proportionnel, rythme, silences | ✅ **COMPLÈTE** |
| Phase 4 — Musical intelligence | C_music, parsers MusicXML/MIDI, patterns, web | ✅ **COMPLÈTE** |
| Phase 5 — Player profile | Profil joueur, calibration, web UI | 📋 Planifiée |
| Phase 6 — AI / ML | Fonction de coût apprise, RLHF | 📋 Planifiée |

---

## Phase 1 — MVP ✅

### Sprint 1 — Fondations ✅

| Tâche | Statut |
|---|---|
| Setup projet (pyproject.toml, pytest, ruff, mypy, CI) | ✅ |
| Modèles de données : `NoteEvent`, `FingeringState`, `FingeringResult` | ✅ |
| Parser GP5 via PyGuitarPro (`.gp3/.gp4/.gp5`) | ✅ |
| Parser GPIF via XML (`.gp` Guitar Pro 7/8) | ✅ |
| Générateur d'états : manche 22 frets, accordage EADGBE | ✅ |
| Fallback tuning alternatif (Eb, open, etc.) via `string_hint/fret_hint` | ✅ |
| 36 fichiers GP de test (corpus de référence) | ✅ |

### Sprint 2 — Scoring et Viterbi ✅

| Tâche | Statut |
|---|---|
| Fonction de coût mécanique C_méca (shift, stretch, corde, doigt) | ✅ |
| Inférence doigt depuis position (`hand_position = fret - finger_offset`) | ✅ |
| Algorithme de Viterbi O(N × S²) | ✅ |
| 4 modes de pondération : `reference`, `performance`, `musical`, `learning` | ✅ |
| Stub M3 (patterns) et M6 (profil joueur) | ✅ |
| Post-traitement : `resolve_finger_continuity` | ✅ |
| Post-traitement : `resolve_section_consistency` | ✅ |
| Post-traitement : `resolve_chord_conflicts` | ✅ |
| Post-traitement : `resolve_chord_stretch` | ✅ |

### Sprint 3 — Intégration ✅

| Tâche | Statut |
|---|---|
| Pipeline voix-séparé (Viterbi indépendant par voix GP) | ✅ |
| CLI `fretwise parse / solve` via Click | ✅ |
| Export ASCII tab | ✅ |
| Export PDF A4 professionnel | ✅ |
| Script de benchmark `scripts/run_fingering.py` (36 morceaux) | ✅ |
| Détection de piste guitare améliorée (GPIF : score multi-critères) | ✅ |
| `track_name` transmis depuis les adaptateurs jusqu'au PDF | ✅ |
| Post-traitement : `resolve_chord_finger_ordering` (doigts monotones) | ✅ |
| Pénalité de croisement séquentiel (`cost_sequential_crossing`) | ✅ |
| Passe inter-voix après fusion | ✅ |

---

## Phase 2 — Notation Enrichment ✅

### 2A — Enrichissement du modèle de données ✅

| Tâche | Statut |
|---|---|
| `NoteEvent` : `bend_value`, `bend_type` (normal/release/pre_bend/…) | ✅ |
| `NoteEvent` : `slide_type` (legato/shift/slide_in_above/…) | ✅ |
| `NoteEvent` : `harmonic_type`, `harmonic_fret` | ✅ |
| `NoteEvent` : `muted`, `palm_muted`, `tapping`, `accent`, `accent_strong`, `tremolo_picking`, `vibrato_wide` | ✅ |
| `BendType`, `SlideType`, `HarmonicType` constantes dans `models.py` | ✅ |
| Nouveaux `Articulation` : `WIDE_VIBRATO`, `HARMONIC`, `TAPPING`, `MUTED`, `TREMOLO` | ✅ |

### 2B — Enrichissement des parseurs GP ✅

| Tâche | Statut |
|---|---|
| `GpifAdapter` : bend points, slide flags, harmonic type/fret | ✅ |
| `GpifAdapter` : palm mute, tapping, accent (note + beat), tremolo picking, wide vibrato | ✅ |
| `GuitarProAdapter` : champs correspondants via PyGuitarPro beat/note | ✅ |

### 2C — Notation rythmique PDF ✅

| Tâche | Statut |
|---|---|
| Convention tab correcte : l'ovale fret IS le notehead (pas de ronds au-dessus) | ✅ |
| Ronde : ovale visible + pas de hampe | ✅ |
| Blanche : ovale visible + hampe | ✅ |
| Noire/croche/double croche : fond blanc invisible + hampe | ✅ |
| Hampes avec crochets (1 flag=croche, 2=double croche, 3=triple croche) | ✅ |
| Ligatures de hampes (beaming) pour groupes de croches/doubles croches | ✅ |
| Silences : pause, demi-pause, soupir, demi-soupir, quart de soupir | ✅ |
| Checksum par mesure (Σ=X.XX en rouge si déviation > 0.1 beat) | ✅ |
| Page de légende rythmique (toutes valeurs + silences + guide symboles) | ✅ |

---

## Phase 3 — Chord Diagrams ✅

### 3A — Extraction des données d'accords ✅

| Tâche | Statut |
|---|---|
| `ChordDiagram` dataclass dans `models.py` | ✅ |
| `_parse_diagram_collection()` dans `GpifAdapter` (XML DiagramCollection) | ✅ |
| `_compute_chord_fingers()` : assignation automatique doigts 1–4 par fret ascendant | ✅ |
| `adapter.chord_diagrams` disponible après `parse_track()` | ✅ |

### 3B — Rendu des diagrammes ✅

| Tâche | Statut |
|---|---|
| `draw_chord_diagram()` dans `export/chord_diagram.py` | ✅ |
| Cercles ouverts avec numéro de doigt à l'intérieur (pas de points noirs) | ✅ |
| Barre : rectangle arrondi plein avec numéro de doigt centré | ✅ |
| X (corde étouffée) et O (corde à vide) au-dessus du diagramme | ✅ |
| Noix (nut) quand `base_fret == 0`, chiffre romain quand `> 0` | ✅ |
| `render_chord_diagrams_pdf()` : PDF A4 standalone grille de diagrammes | ✅ |

### 3C — Diagrammes dans les en-têtes PDF ✅

| Tâche | Statut |
|---|---|
| Diagrammes compacts sur la page de légende (max 8 par ligne) | ✅ |
| Transmission `chord_diagrams` depuis `run_fingering.py` vers `render_pdf_tab()` | ✅ |
| Affichage conditionnel (section présente seulement si fichier GP contient des accords) | ✅ |

---

## Phase 3.5 — PDF Rendering v2 ✅

> Corrections critiques et améliorations du rendu PDF (spécifications dans `docs/rendering_spec_v2.md`)

### P0 — Bugs critiques de lisibilité ✅

| Tâche | Statut |
|---|---|
| RENDER-01 : Silences dans le staff + disque blanc (`_draw_rest` centré à `sys_y - REST_CENTER_Y`) | ✅ |
| RENDER-02 : Silences interrompent les barres de liaison (`_get_beam_groups` détecte gaps ≥ 0.115 b) | ✅ |
| RENDER-03 : Regroupement des liaisons par temps / beat-aware (`beat_boundaries`) | ✅ |

### P1 — Layout et proportionnalité ✅

| Tâche | Statut |
|---|---|
| RENDER-04 : Largeur de mesure variable (`_measure_w_raw` + `_normalize_measure_widths`) | ✅ |
| RENDER-05 : mps variable par système (`_build_systems` — algorithme glouton) | ✅ |
| RENDER-06 : Barres secondaires partielles 16e (`_draw_secondary_beam` — runs partiels) | ✅ |
| RENDER-07 : Séparation zones texte (`CHORD_Y=22`, `MNUM_Y=31`, troncature `…`) | ✅ |

### P2 — Qualité visuelle ✅

| Tâche | Statut |
|---|---|
| RENDER-08 : Annotations doigt sans collision (clearance check + décalage 3.5pt) | ✅ |
| RENDER-09 : Hauteur hampes réduite (`STEM_H = 14pt`, était 16pt) | ✅ |
| RENDER-10 : Légende sans chevauchement (espacement REST_ROW_Y ajusté) | ✅ |
| RENDER-11 : Silences dans la légende avec disque (`_draw_rest()` appelé dans légende) | ✅ |
| RENDER-12 : Vérificateur de collisions post-rendu (`collision_checker.py` — BBox tracker) | ✅ |

---

## Phase 4 — Musical Intelligence ✅

> Complète — C_music, multi-format parsers, pattern database, validation, standard notation, web interface

### 4A — C_music et scoring musical

| Tâche | Statut |
|---|---|
| Fonction de coût musicale `compute_musical_cost()` | ✅ |
| Composante legato same-string (hammer-on, pull-off, legato) | ✅ |
| Composante slide same-string | ✅ |
| Composante vibrato position quality (open-string, low-fret penalty) | ✅ |
| Composante bend feasibility (open-string, wound-string scaling) | ✅ |
| Composante harmonic position matching (natural harmonics) | ✅ |
| Composante tapping low-fret penalty | ✅ |
| Câblage `C_music` dans `transition_cost()` via β weight | ✅ |
| 20+ tests unitaires C_music (legato, slide, vibrato, bend, harmonic, tapping) | ✅ |
| 2 tests d'intégration (β active/inactive influences total cost) | ✅ |

### 4B — Pattern Database M3 ✅

| Tâche | Statut |
|---|---|
| Bibliothèque accords YAML (`chord_voicings.yaml`) étendue : +15 voicings (dim, aug, 9e, barre) | ✅ |
| Bibliothèque gammes YAML (`scales.yaml`) : 10 types × box positions | ✅ |
| `scale_library.py` : `recognize_scale()` (12 roots × 10 patterns, confidence scoring) | ✅ |
| `PatternMatcher` : chord promotion (reorder states → canonical voicing first) | ✅ |
| `PatternMatcher` : scale promotion (detect prevailing scale, promote in-scale states) | ✅ |
| Câblage `PatternMatcher` dans `pipeline.py` et `cli.py` (backward-compatible) | ✅ |
| 33 tests patterns (8 classes : matcher, chord promo, scale promo, recognition, libraries) | ✅ |

### 4C — Multi-Format Parsers ✅

| Tâche | Statut |
|---|---|
| `MusicXmlAdapter` via music21 (`.xml`, `.mxl`, `.musicxml`) | ✅ |
| `MidiAdapter` via pretty_midi (`.mid`, `.midi`) | ✅ |
| Auto-détection du format par extension (`get_adapter()` mis à jour) | ✅ |
| Sélection de piste guitare (MIDI program, nom, pitch range) | ✅ |
| Tempo tracking et conversion sec→beats (MIDI) | ✅ |
| Gestion des tied notes (MusicXML) | ✅ |
| Dynamic mapping velocity→Dynamic enum (les deux parsers) | ✅ |
| CLI et info/parse/solve mis à jour pour tous formats | ✅ |
| 21 tests MusicXML (supports, errors, mock, integration ×5, dynamic, get_adapter) | ✅ |
| 38 tests MIDI (supports, errors, integration ×7, velocity, tempo, beats, get_adapter) | ✅ |

### 4D — Validation & Standard Notation ✅

| Tâche | Statut |
|---|---|
| Concordance validation framework (`validation.py`) | ✅ |
| `compute_concordance()` : compare optimizer output vs source string/fret hints | ✅ |
| `format_concordance_report()` : human-readable report with deviation table | ✅ |
| `scripts/validate_concordance.py` : runs pipeline on all GP fixtures, aggregate report | ✅ |
| Baseline : **99.98% position concordance** (36 223/36 230 hinted notes, 23 tracks) | ✅ |
| `StaffRenderer` (`export/staff_renderer.py`) : treble clef standard notation PDF | ✅ |
| 5-line staff, noteheads (filled/open), stems, flags, accidentals, ledger lines, bar lines | ✅ |
| Time signature, treble clef glyph, measure numbers, section markers | ✅ |
| `CombinedRenderer` (`export/combined_renderer.py`) : staff + tab stacked PDF | ✅ |
| CLI `--format staff` and `--format combined` output options | ✅ |
| Updated `export/__init__.py` with new renderer exports | ✅ |
| 28 new tests: 6 staff smoke + 3 combined smoke + 12 staff helpers + 7 concordance | ✅ |

### 4E — Web Interface (Songsterr-style) ✅

| Tâche | Statut |
|---|---|
| FastAPI backend (`web/app.py`) with file/track/solve endpoints | ✅ |
| Path traversal protection (`_resolve_file`) | ✅ |
| JSON API: full FingeringResult serialization (20+ notation fields) | ✅ |
| Section markers, chord diagrams, artist/title auto-parsing | ✅ |
| HTML5 SPA (`static/index.html`) — Songsterr-style layout | ✅ |
| CSS styling (`static/css/style.css`) — dark header, green accents, responsive | ✅ |
| Canvas tab renderer (`static/js/renderer.js`) — 6-string tab, fret ovals, measures | ✅ |
| Notation symbols: H/P arcs, bends, slides, vibrato, harmonics (diamond), let-ring | ✅ |
| Notation symbols: palm mute, tapping (T), accents (>/∧), staccato, tremolo picking | ✅ |
| Rhythm stems/beams/flags below tab (Songsterr convention) | ✅ |
| Visual playback engine (`static/js/playback.js`) — cursor, speed, loop, metronome | ✅ |
| App routing (`static/js/main.js`) — file picker → track picker → tab viewer | ✅ |
| Keyboard shortcuts (Space=play, ←→=prev/next, M=metronome) | ✅ |
| Tab notation legend (interactive overlay with all symbols + descriptions) | ✅ |
| CLI `fretwise web` command (--port, --dir, --host) | ✅ |

### 4F — Web UI Improvements ✅

| Tâche | Statut |
|---|---|
| PDF export : titre et artiste dessinés directement sur le canvas (pas de page blanche) | ✅ |
| PDF export : suppression du `page-break-inside: avoid` qui forçait l'image sur page 2 | ✅ |
| UI : suppression bouton Search non fonctionnel | ✅ |
| UI : menu mode déplacé dans la toolbar (depuis le header) | ✅ |
| UI : sélecteur de piste dans la toolbar (changement de voix sans quitter le viewer) | ✅ |
| Upload de fichier depuis la page d'accueil (POST `/api/upload`) | ✅ |

---

## Métriques actuelles

| Métrique | Valeur |
|---|---|
| Tests automatisés | **574 passants**, 5 ignorés |
| Couverture de test | ~65 % |
| Fichiers GP de test (fixtures) | 6 (corpus de référence) |
| Notes totales traitées (benchmark) | ~44 000 |
| Drops (aucun état valide) | < 0.1 % |
| Croisements de doigts dans les accords | **0** (corpus complet) |
| Spans `!` non résolvables | 5 (genuins — barré > 4 frets) |
| Temps de calcul | < 1 s / morceau |

---

## Problèmes connus restants

| # | Description | Sévérité |
|---|---|---|
| R-01 | **Adele-Someone Like You** : aucune piste guitare (arrangement piano/vocal). Comportement correct. | Faible |
| R-02 | **`!` dans And I Love Her** (3), **Bon Jovi** (1), **Desert Song** (1) : spans impossibles genuins. | Faible |
| R-03 | **Barré** : un seul doigt couvrant plusieurs cordes non modélisé dans l'optimiseur. | Moyenne |
| R-04 | **Principe diagonal** : la diagonale naturelle de la main non encodée dans la fonction de coût. | Faible |
| R-05 | **Diagrammes GP incorrects** : certains fichiers (Rebel Rebel, Bon Jovi) ont des diagrammes par défaut identiques — limitation source. | Faible |
| R-06 | **7 fichiers** avec checksums Σ anormaux : pickup bars, multi-voix 12/8 — anomalies GP source confirmées. | Information |

---

## Architecture actuelle

```
src/fretwise/
├── models.py           NoteEvent (20+ champs), FingeringState, FingeringResult, ChordDiagram
├── parser/
│   ├── base.py              Interface abstraite AdapterParser
│   ├── guitarpro_adapter.py GP3/4/5 — articulations, let_ring, section_markers
│   ├── gpif_adapter.py      GP7/8  — idem + chord_diagrams, DiagramCollection
│   ├── musicxml_adapter.py  MusicXML (.xml/.mxl/.musicxml) via music21
│   └── midi_adapter.py      MIDI (.mid/.midi) via pretty_midi
├── generator/          StateGenerator (hint-based fallback, tunings alternatifs)
├── scoring/            CostFunction, CostWeights, 7 resolvers
├── optimizer/          ViterbiOptimizer O(N×S²)
├── patterns/
│   ├── __init__.py            PatternMatcher (chord + scale promotion)
│   ├── chord_recognition.py   recognize_chord() (pitch-class matching)
│   ├── chord_library.py       Chord voicing database (YAML lookup)
│   └── scale_library.py       Scale recognition (12 roots × 10 patterns)
├── pipeline.py         split_by_voice + run_pipeline (passe inter-voix)
├── export/
│   ├── ascii_tab.py         Tab ASCII
│   ├── pdf_tab.py           PDF A4 (rythme + légende + checksums + layout proportionnel)
│   ├── staff_renderer.py    Standard notation PDF (treble clef, 5-line staff)
│   ├── combined_renderer.py Staff + tab stacked PDF
│   ├── chord_diagram.py     Rendu diagrammes accords (box diagram standard)
│   └── collision_checker.py Détection de collisions post-rendu (BBox tracker)
├── validation.py       Concordance validation (optimizer vs source tab hints)
├── web/
│   ├── app.py               FastAPI backend (files/tracks/solve API)
│   └── static/              Songsterr-style SPA (HTML/CSS/JS Canvas renderer)
├── profile/            Stub profil joueur (Phase 5)
└── cli.py              fretwise parse / solve / web
```

**Tests :** `pytest -v` (574 passants, 5 ignorés)
**Benchmark :** `python scripts/run_fingering.py` → `docs/benchmarks/`
