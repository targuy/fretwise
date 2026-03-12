# FretWise — Statut du projet

> Dernière mise à jour : 2026-03-12

---

## Statut global

| Phase | Description | Statut |
|---|---|---|
| **Phase 1 — MVP** | Parser + Viterbi + ASCII/PDF export | ✅ **COMPLÈTE** |
| **Phase 2 — Notation enrichment** | Enrichissement modèle + symboles PDF | ✅ **COMPLÈTE** |
| **Phase 3 — Chord diagrams** | Extraction GP + rendu PDF | ✅ **COMPLÈTE** |
| Phase 4 — Musical intelligence | C_music, parsers MusicXML/MIDI, patterns | 📋 Planifiée |
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

## Métriques actuelles

| Métrique | Valeur |
|---|---|
| Tests automatisés | **358 passants**, 1 ignoré |
| Couverture de test | ~65 % (export couvert par test_export.py + test_chord_diagram.py) |
| Fichiers GP traités | 36/36 (100 %) |
| Fichiers avec sortie utilisable | 35/36 (97 %) |
| Notes totales traitées | ~44 000 |
| Drops (aucun état valide) | < 0.1 % |
| Croisements de doigts dans les accords | **0** (corpus complet) |
| Spans `!` non résolvables | 5 (genuins — barré > 4 frets) |
| PDFs générés (benchmark) | 141 (tab + diagrammes + légende) |
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
│   ├── guitarpro_adapter.py  GP3/4/5 — articulations, let_ring, section_markers
│   └── gpif_adapter.py       GP7/8  — idem + chord_diagrams, DiagramCollection
├── generator/          StateGenerator (hint-based fallback, tunings alternatifs)
├── scoring/            CostFunction, CostWeights, 5 resolvers
├── optimizer/          ViterbiOptimizer O(N×S²)
├── patterns/           recognize_chord() (pitch-class matching)
├── pipeline.py         split_by_voice + run_pipeline (passe inter-voix)
├── export/
│   ├── ascii_tab.py    Tab ASCII
│   ├── pdf_tab.py      PDF A4 (rythme + légende + checksums + diagrammes)
│   └── chord_diagram.py  Rendu diagrammes accords (box diagram standard)
└── cli.py              fretwise parse / solve
```

**Tests :** `pytest -v` (358 passants)
**Benchmark :** `python scripts/run_fingering.py` → `docs/benchmarks/`
