# Refactorisation Notation Core (Audit + Plan d'execution)

## 1. Audit du depot actuel

- Branche de travail active: `refactor/notation-core-hardening`.
- Etat git au moment de cet audit: propre apres commit `19bed8b`.
- Base de non-regression actuelle: `585 passed, 5 skipped` (pytest), lint core OK (ruff).
- Stack actuelle: Python 3.11, CLI Click, parsing GP/GPIF/MusicXML/MIDI, rendu PDF ReportLab, UI FastAPI + frontend statique.
- Architecture existante historique encore en production:
  - `parser` -> `pipeline` (generator + optimizer + scoring resolvers) -> `export` / `web`.
- Nouvelle architecture en cours d'introduction dans `src/fretwise/core`:
  - `ingest`, `normalize`, `complete`, `validate`, `decision`, `canonical`, `scene`, `backends`, `pipeline`.
- Couverture normative externe disponible et verifiee:
  - `C:\Users\benoi\iCloudDrive\partitions\Notation-musicale.pdf`.
  - Points utilises pour arbitrage:
    - systeme solfege + tablature (pages 87-91),
    - reduction tablature+rythme presentee comme exception (page 88),
    - effets de jeu ancrés sur tablature (pages 88-89),
    - regles rythmiques (hampes/silences/liaisons, pages 40-44),
    - lisibilite/ligatures/collisions (pages 59-60).

## 2. Modules existants et cartographie fonctionnelle

- `src/fretwise/parser`
  - Adaptateurs GPIF (`.gp`), GuitarPro (`.gp3/.gp4/.gp5`), MusicXML, MIDI.
  - Detection auto via `get_adapter`.
  - Actif strategique: gestion cas particuliers de parsing et selection de piste.
- `src/fretwise/generator`, `src/fretwise/optimizer`, `src/fretwise/scoring`
  - Generation des etats de doigtes, Viterbi, resolvers post-Viterbi.
  - Actif strategique principal: qualite metier du calcul de doigtes.
- `src/fretwise/pipeline.py`
  - Orchestration voix-separees + passe inter-voix.
- `src/fretwise/export`
  - `pdf_tab.py`, `staff_renderer.py`, `combined_renderer.py`, `chord_diagram.py`.
  - Actifs strategiques: PDF, collisions existantes, rendu rythme/tab, diagrammes.
- `src/fretwise/web`
  - API FastAPI + UI web, bibliotheque de morceaux, selection voix, playback/metronome/tempo/boucles.
- `src/fretwise/core` (nouveau chantier)
  - `ingest`: `RawScore`, traces source, logs de normalisation/completion.
  - `normalize`: harmonisation deterministe sans reecriture musicale.
  - `complete`: frontiere explicite de completion prudente.
  - `validate`: validation 5 niveaux + severites.
  - `decision`: arbitrage policy-based (`accept/reject/review/...`).
  - `canonical`: modele semantique canonique + mapper depuis `CompletedScore`.
  - `scene` + `backends.svg`: scene canonique et export SVG minimal.
  - `pipeline`: chaine minimale `raw -> normalized -> validated -> canonical -> scene -> svg`.
- Tests
  - Suite large existante sur pipeline historique + nouveaux tests core.
  - Nouveaux contrats deja testes: input phases, validation, decision, canonical, scene/svg.

## 3. Risques de regression

- Bloquant
  - Regression de qualite de doigtes si le nouveau canonical/layout court-circuite les resolvers historiques (`resolve_*`).
  - Regression PDF/UI si l'integration remplace trop vite `export/pdf_tab.py` et `web/app.py`.
  - Regression parsing GP/GPIF multi-voix/track selection.
- Important
  - Desalignement temporel entre notation standard et tablature en mode hybride.
  - Perte des effets de jeu (hammer/pull/slide/bend/palm mute/tapping) pendant migration scene/layout.
  - Rupture de compatibilite avec tempo variable, boucles et scrolling playback.
- Differable
  - Ecarts cosmetiques de glyphes si conformance checks n'est pas encore strict.
  - Performance layout/svg avant optimisation.

## 4. Ecarts entre Fretwise actuel et la cible normative

- Bloquant
  - Le nouveau pipeline core couvre des plans standard/tab minimaux, mais la gravure standard complete (cles, alter, hampes/flags) n'est pas encore migree dans `core`.
  - Les regles normatives sont encore dispersees (surtout dans `export/pdf_tab.py`), pas centralisees dans `notation_policy` + `layout_rules` + `conformance_checks`.
  - Pas encore de `reference_glyph_set` ni `parametric_recipes` normatives explicites.
- Important
  - Absence de vraie couche `layout engine` declarative (zones, ancres, priorites, collisions, deformations autorisees).
  - Validation notation/musical/instrumental encore baseline (pas de couverture complete tuplets/ties/metric-hybrid).
  - Pas encore de registries explicites pour formats/backends/glyphes/recettes/validateurs/transformations.
- Differable
  - `CorrectedCandidateScore` existe mais sans pipeline de correction policy-gated complet.
  - Backend PDF vectoriel via `RenderScene` pas encore branche (SVG minimal seulement).

## 5. Architecture cible adaptee au depot reel

- Couches cibles et mapping incremental
  - Ingestion/parsing: conserver `parser/*`, encapsuler via frontiere `core.ingest`.
  - Raw model: `RawScore` (deja introduit), preservation des champs inconnus.
  - Normalisation: `core.normalize` (deja introduit).
  - Completion prudente: `core.complete` (deja introduit, actuellement noop traceable).
  - Validation: `core.validate` (deja introduit, a etendre).
  - Decision: `core.decision` (deja introduit).
  - Canonical semantic model: `core.canonical` (deja introduit).
  - Layout engine: a extraire depuis `export/pdf_tab.py` vers `core.layout`.
  - Couche graphique norme: a creer dans `core.graphics` (`notation_policy`, `reference_glyph_set`, `parametric_recipes`).
  - Render scene: `core.scene` (deja introduit, a enrichir).
  - Backends: `core.backends.svg` present, PDF/UI bridge a brancher.
  - Integration Fretwise: conserver `cli.py`, `pipeline.py`, `web/app.py`, brancher progressivement le nouveau core.

## 6. Plan de refactorisation par phases

- Phase 0 Audit (fait)
  - Cartographie des modules, actifs critiques, ecarts normatifs.
- Phase 1 Securisation (partiellement fait)
  - Tests de smoke critiques: parsing, fingering, PDF, web solve/playback.
  - Baseline non-regression versionnee.
- Phase 2 Frontiere d'entree (fait v1)
  - `RawScore/NormalizedScore/CompletedScore` + traces + logs.
- Phase 3 Validation/Decision (fait v1)
  - Validation 5 niveaux baseline + arbitrage policy.
- Phase 4 Canonical model (fait v1)
  - Mapping `CompletedScore -> Score`.
- Phase 5 Scene + SVG minimal (fait v1)
  - Pipeline minimal complet vers SVG.
- Phase 6 Layout core (prochaine priorite)
  - Extraire moteur de placement depuis `export/pdf_tab.py` vers `core.layout`.
  - Definir contrats `PageLayout/SystemLayout/StaffLayout`.
- Phase 7 Couche graphique normative (prochaine priorite)
  - Introduire `notation_policy`, `reference_glyph_set`, `parametric_recipes`, `conformance_checks`.
- Phase 8 Integration progressive
  - Brancher PDF puis UI sur `RenderScene`, maintenir cohabitation ancien/nouveau pipeline.
- Phase 9 Durcissement normatif
  - Standard notation complete, mode hybride strict, convergence des ecarts historiques.

## 7. Decoupage multi-agents recommande

- Agent 1 `refactor/input-hardening`
  - Ownership: `core/ingest`, `core/normalize`, `core/complete`, `core/validate`.
  - Livrable: validation complete + reports diffables + registry validateurs.
- Agent 2 `refactor/canonical-model`
  - Ownership: `core/canonical`, mappers, contrats de serialisation.
  - Livrable: modele edit-friendly + transformation-safe.
- Agent 3 `refactor/layout-engine`
  - Ownership: `core/layout` + extraction de regles depuis `export/pdf_tab.py`.
- Agent 4 `refactor/render-scene-svg`
  - Ownership: `core/scene`, `core/graphics`, `core/backends`.
- Agent 5 `refactor/fretwise-integration`
  - Ownership: `cli.py`, `web/app.py`, branchement dual pipeline.
- Agent 6 `refactor/conformance-tests`
  - Ownership: tests de contrat, tests normatifs, fixtures GP/MIDI.

## 8. Contrats de donnees a figer

- Input pipeline
  - `RawScore`, `NormalizedScore`, `CompletedScore`, `CorrectedCandidateScore`.
  - `SourceTraceMap`, `NormalizationLog`, `CompletionLog`, `CorrectionDiff`.
- Validation/decision
  - `ValidationIssue`, `ValidationReport`, `DecisionPolicy`, `DecisionOutcome`.
- Canonical
  - `Score`, `Track`, `StaffGroup`, `Staff`, `Measure`, `Voice`, `Event` + sous-types.
- Layout (a figer prochainement)
  - `PageLayout`, `SystemLayout`, `StaffLayout`.
- Scene/backends
  - `RenderScene`, `DocumentScene`, `PageScene`, `SystemScene`, `StaffScene`, `LayerGroup`, `GlyphInstance`, `RecipeInstance`, `TextInstance`.
  - Contrat `RenderScene -> SVG/PDF`.

## 9. Composants a conserver / encapsuler / remplacer

- A conserver absolument
  - Parseurs existants (`parser/*`).
  - Moteur de doigtes (`generator`, `optimizer`, `scoring`, resolvers).
  - Fonctions UI critiques: bibliotheque, choix de voix, accords, playback, metronome, tempo, boucles, scrolling.
  - Export PDF existant tant que layout core n'est pas equivalent.
- A encapsuler
  - `fretwise/pipeline.py` derriere une facade d'integration.
  - `export/pdf_tab.py` comme backend legacy pendant migration.
- A remplacer progressivement
  - Regles de placement hardcodees dans `export/*` vers `core/layout` + `core/graphics`.
  - Choix implicites de notation dans les renderers vers `notation_policy` explicite.

## 10. Premiers tests a ajouter

- Contrats de couche
  - Tests schema/diff pour `ValidationReport.to_dict()` et `DecisionOutcome.to_dict()`.
  - Tests de non-regression pour `completed_to_canonical_score()` avec poly-voix et changements metriques.
- Normatifs
  - Tests alignement vertical strict standard/tab en mode hybride.
  - Tests de placement des liaisons/ligatures (voix haute vs voix basse, collisions).
  - Tests de silences multi-voix et regles de hampes.
- Integration
  - Snapshot tests `RenderScene -> SVG` sur corpus fixe.
  - Tests A/B ancien PDF vs nouveau backend scene-PDF sur morceaux de reference.
  - Tests API web garantissant absence de regression sur track switcher, loops, tempo, metronome.

## 11. Premiers commits concrets a realiser

- Deja realises sur cette branche
  - `cb8f12f` scaffold des couches core.
  - `15a2566` modeles d'entree + traceabilite.
  - `7f2a829` validation 5 niveaux baseline.
  - `6aa22cb` decision policy-based.
  - `c4cabaf` canonical model + mapper.
  - `3d2ea71` render scene + backend SVG + pipeline minimal end-to-end.
  - `365ce57` registries explicites input/output/glyph/recipe/validator/transform.
  - `1176786` contrats de layout page/system/staff + bridge scene.
  - `5c0b80a` `notation_policy` + glyph set + recipe catalog + conformance checks.
  - `bb13e7a` regles de layout centralisees et collision policies explicites.
  - `25c9057` backend PDF vectoriel pour `RenderScene` + tests de contrat.
  - `139c0e0` CLI `--pdf-engine` (legacy/core) avec cohabitation.
  - `1625c5e` endpoint web `/api/export/pdf` (legacy/core) + fallback.
  - `b83cb5d` UI web: branchement export PDF API + selecteur d'engine.
  - `8ef2ad9` en-tetes de conformite API PDF + statut d'export en toolbar.
  - `7854998` scene: modes `standard` et `standard_tablature` avec plans explicites.
  - `d0b942a` checks de conformite hybrides (presence + alignement horizontal par `event_id`).
  - `ae89c9d` scene standard: glyphes `clef`, `time_signature`, `rest` dans RenderScene + SVG/PDF.
  - `8bc1bf2` conformance hybride: checks verticaux stricts (plans, overlap, string rows).
  - `885d7c3` layout rhythm core: recipes `stem_line` et `beam_group` + rendu SVG/PDF.
  - `fcb5985` spans tab core: `let_ring_span` et `palm_mute_span` de canonical->layout->scene->SVG/PDF.
  - `f9bacc3` arcs standard core: `tie_arc` et `slur_arc` dans scene + rendu SVG/PDF.
  - `2c45c1c` accidentals standard core: `accidental_sharp/flat` policy + scene + SVG/PDF.
  - `f4c006e` flags standard core: recipe `flag_stack` + rendu SVG/PDF.
  - `3ad73d2` beams secondaires partiels: niveaux `beam_group` 2+ pour groupes mixtes.
  - `dafa113` layout voix-aware: directions de hampes + orientation beams/flags + arcs tie/slur cote oppose.
  - `c1b8437` conformance rhythmique: checks explicites sur direction/geometrie des hampes + direction beams/flags.
  - `01eabf2` scene standard: placement des silences affine par voix (haut/bas) + trace `voice_number`.
  - `c537a37` layout standard: liaisons tie/slur groupees par voix + profil de courbure/offset adapte a la portee.
  - `19bed8b` integration web: export PDF legacy avec shadow core pour remonter les issues de conformite sans casser l'existant.
- Prochains commits recommandes
  - `feat(integration): expose legacy-shadow conformance diagnostics in CLI pdf export`.

## 12. Proposition de branche principale et sous-branches

- Branche principale chantier
  - `refactor/notation-core-hardening`.
- Sous-branches recommandees
  - `refactor/input-hardening`
  - `refactor/canonical-model`
  - `refactor/layout-engine`
  - `refactor/render-scene-svg`
  - `refactor/fretwise-integration`
  - `refactor/conformance-tests`
- Regle de merge
  - Merge interdit sans tests de contrat, note d'impact inter-couches, et liste explicite des ecarts normatifs temporaires.

## 13. Strategie d'extensibilite future

- Ajouter des registries explicites
  - `InputFormatRegistry`, `OutputBackendRegistry`, `GlyphRegistry`, `RecipeRegistry`, `TransformationRegistry`, `ValidatorRegistry`.
- Extension par adaptation, pas par modification coeur
  - Nouveaux formats d'entree via extracteurs enregistrés.
  - Nouveaux backends via adaptateurs `RenderScene`.
  - Nouveaux glyphes/recettes via catalogues versionnes.
  - Nouvelles transformations via operations pures sur le canonical model.
- Tracabilite
  - Toute transformation structurelle produit diff explicite et map de trace.

## 14. Preparation a l'ouverture open source

- Documentation
  - ADR courtes par couche + contrats publics versionnes.
  - Guide contributeur (`CONTRIBUTING.md`) et conventions de nommage.
- Qualite
  - CI multi-OS (Linux/macOS/Windows), lint/type/tests obligatoires.
  - Suites de tests de contrat + fixtures minimales partageables.
- Packaging
  - Installation reproductible en venv (`pip install -e .[dev]`).
  - Separation claire coeur metier vs integration UI.
- Gouvernance technique
  - Politique de deprecation des contrats.
  - Politique de compatibilite formats d'entree/sortie.
  - Roadmap publique des convergences normatives restantes.
