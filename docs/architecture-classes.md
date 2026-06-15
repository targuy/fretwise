# FRETWISE — Grandes classes, affichage et front/back office

> Carte des grandes classes du **code réel** : modèles, moteur de doigté (M1–M6),
> biomécanique/audit/révision, pipeline de notation, export, API web, et front
> office (vues, mains, lecture). Pour le **contrat fonctionnel** et la fonction de
> coût, voir la spec [`fretwise_architecture.md`](fretwise_architecture.md). Ce
> document décrit les noms de classes, les fichiers, et le lien front ↔ back.

---

## 1. Vue d'ensemble — deux pipelines

- **Pipeline A — Doigté** ([`pipeline.py`](../src/fretwise/pipeline.py)) : moteur de
  production. `NoteEvent[]` → génération d'états → patterns → Viterbi → chaîne de
  résolveurs → garde biomécanique → audit/export. Répond à `GET /api/solve` et
  `POST /api/save/gp`.
- **Pipeline B — Notation** ([`core/`](../src/fretwise/core/)) : architecture en
  couches qui transforme une partition brute en glyphes SVG/PDF. **Indépendant** du
  pipeline A (ne calcule aucun doigté).

Le **front office** (web FastAPI + JS vanilla) consomme les deux via l'API HTTP.

```
            ┌──────────────── FRONT OFFICE (navigateur) ─────────────────┐
            │  main.js · renderer.js · playback.js · hand_viz.html ...    │
            └─────────────────────────────┬──────────────────────────────┘
                                          │ HTTP /api/*
            ┌─────────────────────────────┴──────────────────────────────┐
            │                   BACK OFFICE (FastAPI)                      │
            │                 src/fretwise/web/app.py                      │
            ├──────────────────────────────┬───────────────────────────────┤
            │  Pipeline A (doigté)         │  Pipeline B (notation)         │
            │  pipeline.py + M1..M6        │  core/ (ingest→scene→backends) │
            └──────────────────────────────┴───────────────────────────────┘
```

---

## 2. Modèles de données centraux

[`models.py`](../src/fretwise/models.py) — dataclasses partagées par le pipeline A :

| Classe | Rôle |
|---|---|
| `NoteEvent` | Événement atomique : `pitch`, `onset`, `duration`, `tempo`, `articulation`, `dynamic` (+ indices corde/fret, bends/slides/harmoniques de la source). |
| `FingeringState` | Choix complet pour une note : `string_num`, `fret`, `finger`, `hand_position`. |
| `FingeringResult` | Sortie de l'optimiseur : `NoteEvent` + état retenu + coût + alternatives + `planted_fingers`. |
| `ChordDiagram` | Diagramme d'accord extrait du fichier GP (nom, frets, base, doigts, `source_id`). |
| `Articulation`, `Dynamic`, `Finger` | Énumérations (`StrEnum`). |
| `BendType`, `SlideType`, `HarmonicType` | Constantes de techniques. |

---

## 3. Moteur de doigté — les six modules (M1–M6)

| Module | Classe / fonction publique | Fichier | Rôle |
|---|---|---|---|
| **M1 Parser** | `get_adapter(path)` → `BaseParser` (`GuitarProAdapter`, `GpifAdapter`, `MusicXmlAdapter`, `MidiAdapter`) | [`parser/`](../src/fretwise/parser/) | GP3-5 / GP7-8 (GPIF) / MusicXML / MIDI → `list[NoteEvent]`. |
| **M2 Générateur** | `StateGenerator.states_for_sequence(notes)` | [`generator/`](../src/fretwise/generator/) | Toutes les positions valides (corde, fret) par note. |
| **M3 Patterns** | `PatternMatcher.apply(notes, state_lists)` | [`patterns/`](../src/fretwise/patterns/) | Reconnaissance accords/gammes ; **réordonne** les états (ne supprime ni ne recoûte). |
| **M4 Scoring** | `CostFunction`, `CostWeights`, `RulePreferences` | [`scoring/`](../src/fretwise/scoring/) | Coût composite `C = α·C_méca + β·C_music + γ·C_joueur + δ·C_péda`. |
| **M5 Optimiseur** | `ViterbiOptimizer.solve(notes, state_lists)` | [`optimizer/`](../src/fretwise/optimizer/) | Chemin de coût minimal (O(N·S²)). |
| **M6 Profil** | `PlayerProfile`, `default_profile()` | [`profile/`](../src/fretwise/profile/) | Paramètres morphologiques/dextérité. **Stub** Phase 1 : profil « moyen » fixe. |

**Contrat M5 (immuable) :** `ViterbiOptimizer(cost_fn).solve(notes, state_lists)` →
`list[FingeringResult]`. La fonction de coût est **injectée** (`CostFunctionProtocol` :
`transition_cost` + `emission_cost`), jamais codée en dur. Toute évolution de scoring
se fait dans M4, jamais dans Viterbi.

**Modes de pondération** : `CostWeights.reference() / .performance() / .musical() / .learning()`
(valeurs α/β/γ/δ par mode dans [`../CLAUDE.md`](../CLAUDE.md) § Fonction de coût).

---

## 4. Pipeline A — orchestration et résolveurs post-Viterbi

[`pipeline.py`](../src/fretwise/pipeline.py) :

- `run_pipeline(notes, ...)` → `(results, stats)` : sépare les voix (`split_by_voice`),
  exécute génération → `PatternMatcher.apply` → `ViterbiOptimizer.solve` → chaîne de
  résolveurs, fusionne.
- `run_pipeline_with_guard_report(...)` → `PipelineResult` : enrobe le résultat de la
  garde biomécanique (`validate_fingering_results`).

**Chaîne de résolveurs** (dans [`scoring/`](../src/fretwise/scoring/), **l'ordre compte**
— ne pas réordonner sans vérifier les dépendances) : `resolve_arpeggio_chord_fingering` ·
`resolve_finger_continuity` · `resolve_chord_conflicts` · `resolve_chord_stretch` ·
`resolve_chord_finger_ordering` · `resolve_chord_finger_span` ·
`resolve_chord_string_diagonal` · `resolve_chord_learned_fingers` (ML, optionnel) ·
`resolve_section_consistency` · `resolve_pinky_run_to_index` · `_resolve_final_chord_guards`
(stabilisation 3 passes) · `resolve_sedentary_fingers` (annote les doigts plantés).

---

## 5. Biomécanique, audit & révision (boucle qualité)

| Module | Classe / fonction | Rôle |
|---|---|---|
| [`biomechanics/`](../src/fretwise/biomechanics/) | `validate_fingering_results()` → `BiomechanicalReport` (`BiomechanicalViolation`, `BiomechanicalSeverity`) | Garde finale **pure** (sans mutation) : codes `BIO-STATE/CHORD/TRANS-*`, sévérité, indices de notes. |
| [`audit/`](../src/fretwise/audit/) | `audit_score()` → `AuditReport` (`MovementVerdict`, `MovementSpan`, `split_by_movement`) | Verdict **par mouvement** : `clean` / `suspect` / `bad` (qualité source + incertitude algo + confiance ML). |
| [`review/`](../src/fretwise/review/) | `flag_fingerings()` → `ReviewReport` (`ReviewItem`, `Severity`) | Liste les doigtés `IMPOSSIBLE` / `SUSPECT` / `HIGH_COST`. |
| [`review/alternatives.py`](../src/fretwise/review/alternatives.py) | `measure_alternatives()` (+ `DiversityCostFunction`) | Re-résout une mesure en contexte → N variantes diversifiées. |
| [`review/feedback.py`](../src/fretwise/review/feedback.py) | `save_choice()` (`SongFeedback`, `FeedbackRecord`) ; [`bias.py`](../src/fretwise/review/bias.py) `FeedbackBiasedPlayerCost` | Persiste le choix utilisateur et re-biaise le scoring (γ). |

Côté UI : `audit.js` (bandeau qualité) et `review.js` (panneau révision).

---

## 6. Pipeline B — notation (core/)

Couches journalisées et indépendantes :

```
RawScore → NormalizedScore → CompletedScore → Score (canonique) → RenderScene → SVG/PDF
```

| Couche | Classe principale | Fichier |
|---|---|---|
| ingest | `RawScore`, `SourceTrace` | [`core/ingest/`](../src/fretwise/core/ingest/) |
| normalize | `NormalizedScore`, `NormalizationLog` | [`core/normalize/`](../src/fretwise/core/normalize/) |
| complete | `CompletedScore`, `CompletionLog` | [`core/complete/`](../src/fretwise/core/complete/) |
| canonical | `Score`, `Track`, `Measure`, `Voice`, … (mappers depuis `CompletedScore`) | [`core/canonical/`](../src/fretwise/core/canonical/) |
| scene | `RenderScene` (graphe de glyphes) | [`core/scene/`](../src/fretwise/core/scene/) |
| validate | `ValidationReport`, `DecisionOutcome` | [`core/validate/`](../src/fretwise/core/validate/) |
| graphics | `RepresentationMode`, `ConformanceIssue`, `check_scene_conformance()` | [`core/graphics/`](../src/fretwise/core/graphics/) |
| backends | `render_scene_to_svg()`, `render_scene_to_pdf_bytes()` | [`core/backends/`](../src/fretwise/core/backends/) |

Point d'entrée : `run_core_pipeline_from_raw()` ([`core/pipeline.py`](../src/fretwise/core/pipeline.py))
→ `CorePipelineResult`. `RepresentationMode` (TAB / STANDARD / STANDARD_TAB / TAB_RHYTHM)
doit rester synchronisé avec `modeConfig.js` côté front (voir §9.2).

> ⚠️ Le `NoteEvent` **canonique** (`core/canonical`) est distinct de `models.NoteEvent`.

---

## 7. Export

[`export/`](../src/fretwise/export/) — sorties multiples :

| Fonction | Fichier | Sortie |
|---|---|---|
| `render_pdf_tab()` | `pdf_tab.py` | PDF tab + notation (export PDF principal, aussi utilisé pour sérialiser `/api/solve`). |
| `render_staff_pdf()` · `render_combined_pdf()` | `staff_renderer.py` · `combined_renderer.py` | PDF portée seule / multi-pistes. |
| `render_musicxml()` / `render_musicxml_multi()` / `write_musicxml()` | `musicxml_writer.py` | MusicXML (mono/multi-pistes). |
| `write_gp_with_fingerings()` (+ `fingerings_by_source_id`) | `gp_writer.py` | Ré-injecte `LeftFingering` dans le GP source via `source_note_id`. |
| `export_hand_viz_json()` | `hand_viz.py` | JSON de poses (frames : `note_id`, corde, fret, doigt, `hand_position`, doigts plantés) pour la **main** côté navigateur. |
| `render_ascii_tab()` · `render_text_report()` | `ascii_tab.py` | Tablature / rapport ASCII (terminal). |

---

## 8. Composants ML (optionnels)

[`ml/`](../src/fretwise/ml/) — dégradent silencieusement vers des fallbacks à base de règles :

- `ChordFingerClassifier` (ABC) → `LearnedChordFingerClassifier` (ONNX `finger_classifier.onnx`, 24 features) / `FixedChordFingerClassifier`. Utilisé par `resolve_chord_learned_fingers`.
- `PlayerCostModel` (ABC) → `LearnedPlayerCost` (ONNX `transition_cost_v3.onnx`, 26 features) / `FixedPlayerCost`. Composante γ du scoring.
- `LearnedPhraseWindowFingerer` + `resolve_phrase_window_fingers()` ([`phrase_window.py`](../src/fretwise/ml/phrase_window.py)) — override des doigtés mélodiques (hors accords) + « pinky demotion belt », avant l'annotation sédentaire.

---

## 9. Front office — affichage et logique

Fichiers : [`web/static/`](../src/fretwise/web/static/).

### 9.1 Orchestration & navigation

- [`main.js`](../src/fretwise/web/static/js/main.js) — machine à états des pages
  (`files` → `tracks` → `viewer` / `settings`), câblage des composants, cache client
  `_solveCache` / `_notesCache` (évite de re-télécharger au changement de piste).
- [`api.js`](../src/fretwise/web/static/js/api.js) — wrapper `fetch` centralisé
  (`fetchSolve`, `fetchTracks`, `fetchNotes`, `fetchSaveGp`, `fetchReview`,
  exports, soundfonts, storage, `fetchMe`…).
- [`modeConfig.js`](../src/fretwise/web/static/js/modeConfig.js) — constantes de mode
  (`STANDARD`, `TABLATURE`, `STANDARD_TABLATURE`, `TABLATURE_RHYTHM`) et helpers
  (`hasTab`, `hasStandard`, `isGuitarKind`). **Miroir** de `core/graphics` / `RepresentationMode`.

### 9.2 Rendu (affichage des vues)

- [`renderer.js`](../src/fretwise/web/static/js/renderer.js) — **`TabRenderer`** :
  tablature canvas 2D façon Songsterr (frettes, rythme/hampes, accords, articulations,
  doigtés colorés par doigt, `setMaskedMeasures` pour masquer les doigtés audités `bad`).
- [`svg-playback.js`](../src/fretwise/web/static/js/svg-playback.js) —
  **`SvgCursorDriver`** : curseur transparent + ligne rouge superposés à la portée
  SVG rendue serveur (vues Staff / Mixed), via `measure_regions` et `note_anchors`.

**Modes de vue** — contrôle segmenté `.view-seg` (Staff / Mixed / Tab) :

| Bouton | Valeur | Représentation | Renderer(s) |
|---|---|---|---|
| Staff | `standard` | Portée seule | `SvgCursorDriver` + SVG serveur |
| Mixed (défaut) | `standard_tablature` | Portée + Tab | `TabRenderer` + `SvgCursorDriver` |
| Tab | `tablature` | Tab seule | `TabRenderer` + `#cursor-canvas` |

`main.js` re-frappe `GET /api/solve?representation_mode=…` via `selectTrack()` lors
de chaque changement de mode. `playback.usesSvgCursor = !!_svgDriver` arbitre le scroll.

**Zoom et mesures-par-ligne (Staff / Mixed)** — architecture en deux niveaux :

- `_ZOOM_BASE` : décalage baseline de chaque vue en % (20 = Staff, 40 = Mixed).
- `_viewZoom[mode]` : décalage slider utilisateur (−50 … +50).
- `_svgRenderWidth(mode)` : arrondit `(innerWidth − 48) / factor` à 50 px près
  (bucket) et le transmet comme `svg_width` au backend. Le backend génère le SVG à
  cette largeur réduite ; le SVG affiché à `width:100%` crée l'effet de zoom.
- `_refreshSvgView()` : async, garde per-mode `_lastSvgWidth[mode]` pour éviter les
  re-fetchs inutiles. **Recrée systématiquement `_svgDriver`** après toute mise à jour
  du SVG (les rects `.fw-cursor` injectés par `init()` sont détruits par le remplacement
  `innerHTML` — ne pas recréer le driver rendait highlights et click-to-seek silencieusement
  cassés après chaque zoom/resize).
- Tab (canvas) n'a pas ces contraintes : zoom = CSS `zoom` direct ; resize =
  `renderer._buildSystems()` synchrone. C'est pourquoi Tab n'a jamais régressé.

### 9.3 Affichage des mains (hand viz)

- [`hand_viz.html`](../src/fretwise/web/static/hand_viz.html) — page embarquée
  (iframe `#hand-viz-panel`, popout possible) : scène SVG 2.5D du manche + main animée
  image par image, pilotée par le temps de lecture via `postMessage`. Les poses
  proviennent du JSON `export_hand_viz_json()` (le solveur de pose est **côté navigateur**).
- [`hand3d.js`](../src/fretwise/web/static/js/hand3d.js) — **`Hand3DRenderer`** :
  rendu 3D three.js **optionnel** (flag `window.FRETWISE_3D_HAND_ENABLED`, off par défaut ;
  maillage riggé `models/rigged_hand.glb`, fallback FK procédural). Partage exactement
  les mêmes poses que le SVG (échelle réelle ~2.31 mm/unité) ; fallback SVG si WebGL
  indisponible.

### 9.4 Lecture & audio

- [`playback.js`](../src/fretwise/web/static/js/playback.js) — **`PlaybackEngine`** :
  curseur au tempo, synthèse MIDI (SpessaSynth → soundfont-player → fallback), métronome,
  boucle A/B, vitesse, mixage multi-pistes (gain/mute par piste secondaire), résilience
  de l'`AudioContext` (auto-reprise). Callbacks `onMeasureChange`, `onPositionChange`,
  `onSynthStatusChange`, `onTimeChange`. **Timeline par mesure** (`_ensureTimeline`) :
  l'avance du curseur et le placement des notes utilisent les longueurs réelles de
  chaque mesure (`measure_beats` fourni par l'API) au lieu d'un `beats_per_measure`
  scalaire — toutes les pistes partagent le **même** début de mesure, ce qui les garde
  synchronisées (et calées sur la notation) à travers les changements de signature /
  mesures de levée. Sans `measure_beats` (MusicXML/MIDI), repli sur le tempo uniforme.

### 9.5 Panneaux (boucle de feedback)

- [`audit.js`](../src/fretwise/web/static/js/audit.js) — bandeau qualité : verdicts par
  mouvement, masquage des doigtés `bad` (`getMaskedMeasures`).
- [`review.js`](../src/fretwise/web/static/js/review.js) — panneau flottant « doigtés
  à revoir » : filtres par sévérité, comparaison d'alternatives (avec hand-viz embarquée),
  persistance du choix.

---

## 10. Lien front ↔ back (principaux endpoints)

[`web/app.py`](../src/fretwise/web/app.py) — FastAPI. `_run_legacy_pipeline()` enveloppe
`run_pipeline()` + `CostFunction` + `PatternMatcher` + classifieurs ML optionnels.
Les doigtés sont persistés dans un sidecar `*.gp_fingerings.json`.

| Méthode · Route | Module back | Résultat UI |
|---|---|---|
| `GET /api/files` | `storage.list_scores()` + catalogue | Table bibliothèque |
| `GET /api/tracks/{file}` | `adapter.list_all_tracks()` | Sélecteur de piste |
| `GET /api/solve/{file}` | `run_core_pipeline_from_raw()` + sidecar | Canvas + portée + bandeau qualité |
| `GET /api/notes/{file}` | `_run_legacy_pipeline()` | Moteur de lecture (audio) |
| `POST /api/save/gp/{file}` | `_run_legacy_pipeline()` + `write_gp_with_fingerings()` | Calcule et persiste les doigtés |
| `GET /api/export/{pdf,gp,musicxml}/{file}` | `export.*` | Téléchargements |
| `POST /api/library/cleanup` | post-traitement par lot | Nettoyage bibliothèque |
| `GET /api/review/{file}` · `/alternatives` · `POST /choice` | `review.flag_fingerings` / `measure_alternatives` / `save_choice` | Panneau révision |
| `GET/POST /api/settings`, `/api/storage*`, `/api/soundfonts*`, `/api/me` | config / `storage.factory` / soundfonts / auth | Page paramètres, en-tête |

---

## 11. Stockage & auth

[`storage/`](../src/fretwise/storage/) — `StorageBackend` (ABC) → `LocalStorageBackend`,
`S3StorageBackend`, `WebDAVBackend`, `GoogleDriveBackend` ; `build_backend()` choisit au
runtime. Auth OIDC multi-utilisateurs optionnelle (désactivée en mode mono-utilisateur local).

---

## 12. Pour aller plus loin

- Contrat fonctionnel & fonction de coût : [`fretwise_architecture.md`](fretwise_architecture.md)
- Datasets & parsing : [`fretwise_conception_donnees.md`](fretwise_conception_donnees.md)
- Phases & jalons : [`fretwise_plan_projet.md`](fretwise_plan_projet.md)
