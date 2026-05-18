# Board — Kanban léger

> **Format** : 4 colonnes (TODO / DOING / BLOCKED / DONE).
> **Tags** : `[role]` au début de chaque carte (cf. `roles.md`).
> **Mise à jour** : à chaque commit ou status check par le PM.
> **Dernière revue** : 2026-05-18 (post Fretwise-012 envoyé).

---

## DOING

- `[pm]` **Migration v2 → v3 LIVRÉE** sur `feature/phase3-integration`. Artefacts v3 copiés dans `data/models/`, loaders CLI+web pointent v3, tests re-anchored sur v3 calibration. v2 artefacts supprimés (spec + calibration + onnx local). Suite 972/0 fail (parité ONNX probas ±1e-4, cost 0.4845 sur ex1). Production : web app `performance` mode utilise v3 dès rechargement.

## TODO — Priority 1 (next 24h)

- `[music]` Valider GT (ground truth) idiomatique pour les 4 XFAIL du golden set :
  - Bb King - The Thrill Is Gone, m8 et m94 (PINKY-spam — quels doigts un humain joue ?)
  - Steppenwolf - Born To Be Wild, m23 (PINKY run)
  - Django Reinhardt - Nuages whole-piece (42% PINKY — vraiment trop ou idiomatique jazz manouche ?)
- `[data]` Demande #11 à GDS : per-string mapping complet pour D-shape barre family (≥10 chord shapes affectés) — input pour Phase 2 ML
- `[pm]` Attendre réponse GDS aux demandes #8 / #9 / #10 (per-string mapping, analyse R-C6 friendly, sous-corpus curé)

## TODO — Priority 2 (cette semaine)

- `[qa]` Étendre golden set à 20 cases (= 5 rock + 5 Mutopia + 5 chords + 5 CAGED)
- `[design]` Templates positions main (8-10 photos canoniques) — voir plan B' dans `~/.claude/plans/ce-programme-de-lecture-sparkling-boole.md`
- `[edu]` Specs mode `learning` Phase 5 : quelles infos un apprenant voit ? quel feedback ?
- `[web-be]` Audit endpoints `/api/*`, doc OpenAPI, perf solve sur fichiers > 1000 notes

## TODO — Priority 3 (backlog)

- `[pm]` Fix test `test_canonical_to_render_scene_tablature_rhythm_*` (échec pré-existant SVG)
- `[pm]` Décision finale sur intégration δ.1 (en réserve actuellement, cf. decisions.md)
- `[data]` Re-auditer corpus avec quality filter (clean only), comparer baselines
- `[qa]` Coverage report sur src/fretwise/, identifier modules < 80 %

## BLOCKED

- `[qa]` Mutopia cases dans golden set — `BLOCKED on GDS` (Mutopia download + conversion LilyPond → MusicXML en cours côté GDS)
- `[pm]` Phase 3 PlayerCostModel intégration concrète — `BLOCKED on GDS` (modèle ONNX pas encore entraîné)

## DONE

### Session 2026-05-17 / 2026-05-18

- `[pm]` **Phase 3 ML câblée dans CostFunction (branche `feature/phase3-integration`)** — `CostFunction.__init__` accepte `player_cost_model`; `transition_cost` court-circuite quand γ=0 (reference/musical) et appelle le modèle quand γ>0 (performance/learning) avec fallback graceful exception → c_joueur=0. CLI + web auto-load `data/models/transition_cost_v2.onnx` (mirroir Phase 2). +4 tests wiring (recorder double + γ=0 short-circuit + exception safety + état sans modèle). Suite 972/0 fail.
- `[pm]` **Phase 3 implémentée (branche `feature/phase3-integration`)** — commit `1e1e6ac` : `LearnedPlayerCost` ONNX-backed + `extract_transition_features` 26 features. Parity bit-pour-bit sur 3 cas calibration (probas ±1e-4, cost ±1e-3). Artefacts copiés `data/models/` (ONNX gitignored, spec + calibration commités). 13 tests parity.
- `[pm]` **Fretwise-012 envoyé** — ACK Phase 3 v2 + 3 blockers identifiés (artefacts absents shared dir, format ONNX vs XGB JSON, GAPS holdout vs baseline FW rule-based, calibration JSON manquante). 4 demandes consolidées #23-26.
- `[pm]` **SVG test fix** (`180f783`) — drop string_label emission in tab modes. Suite tests 100 % verte (951/0). Note : commit a embarqué WIP user pré-existant sur `builders.py` (tempo-by-measure logic), à split si besoin.
- `[pm]` **Phase 2 calibration #13 LIVRÉE** (`33d3561`) — 3 bugs corrigés dans `extract_chord_features` (sort direction, string_gap signed/abs, ctx_fret indexation). ALL FEATURES MATCH GDS reference sur les 3 chords de calibration.
- `[pm]` `chore(deps)` `3f75bd2` — onnxruntime dans extras `[ml]`
- `[pm]` DEC-011 PO research mode (`775ea70`) — ClassClef + similar débloqués
- `[pm]` Trigger remote wake-up 2026-05-19 04:00 Paris (id `trig_01J7zaYE66bTBy1zNy4TeDMJ`)
- `[pm]` **Phase 2 activée par défaut** (`a7d38f8`) — CLI + web app. Fallback gracieux si model absent. Validation empirique sur 7 fichiers : ZZ Top La Grange PINKY 185→13, MIDDLE +340. Sequence cases (Bb King, Cream) inchangés (Phase 2 n'agit qu'aux chord onsets).
- `[pm]` **Phase 2 ML INTÉGRÉE** (`7261f0f`) — LearnedChordFingerClassifier + extract_chord_features + resolve_chord_learned_fingers. ONNX 97.7% accuracy. Opt-in via `run_pipeline(chord_finger_classifier=...)`. 950/951 tests verts. Fretwise-007 envoyé.
- `[data]` **Quality.py tuning-awareness fix** (`003f19e`) — DEC-010 — infère tuning per-string depuis events. Corpus bad 22.6 % → **6.7 %** (re-classified 235 false positives drop-D/half-step). Métrique fiable maintenant.
- `[pm]` Fretwise-006-handoff.md à GDS — B integration livrée + mesures + roadmap implications
- `[data]` **Mesure B integration** : MIDDLE +1.81 pp, ratio RP/IM 0.5696 → 0.555, golden set +1 net (2 fix Bb King, 1 régression Cream)
- `[pm]` 12 tests B integration (`e068b08`)
- `[pm]` **B integration livrée** (`0564d4b`) — segment-aware `cost_position_shift`. ViterbiOptimizer passe `index` à `transition_cost`. Pipeline calcule segments per voice, active sur cost_fn via `set_segment_anchors`. 936/937 tests verts (SVG pré-existant).
- `[pm]` Roadmap décisions DEC-008 (`dc23363`) — Phase 3 reportée, B GO
- `[data]` Quality scan corpus (`dc23363`) — 77.2 % clean, 22.6 % bad (mais dominé par bug tuning-awareness de quality.py → P2 fix)
- `[pm]` Stubs ML `src/fretwise/ml/` (`c2276b3`) — PlayerCostModel + ChordFingerClassifier + 12 tests verts. Module dormant.
- `[pm]` Team docs setup (`4390daf`) — roles + board + decisions
- `[data]` Validation δ.1 sur 1404 erreurs réelles (échantillon enrichi par GDS) — confirme 1 % fix, le bug est au layer R-C6 → δ.1 en réserve
- `[data]` Analyse R-C6 : 71 % des erreurs same-fret, D-shape barre miroir systématique identifié → escalade Phase 2 ML
- `[pm]` Round-trips 1-4 GDS avec watcher actif (`br8tt1kxp`)
- `[pm]` A' tolérance hp shift (`2480d8e`) — gain -1.98 % RP/IM corpus 2M notes
- `[pm]` B v0 segmentation module (`95e4d63`) — module pur, 15 tests, dormant
- `[pm]` Fix bug `resolve_chord_partial_barre` IndexError (`1f42771`) — débloque 27 morceaux
- `[qa]` Golden set v1 infrastructure (`f3e4062`, `4d1a5e4`) — 6 cases, 4 XFAIL + 2 XPASS
- `[pm]` Handoff docs initiaux (`c405353`) — README + MODEL_SPEC + QUESTIONS
- `[data]` Quality protocol `fretwise.quality` (`3f917fe`) — 7 tests, golden set annoté
- `[pm]` Round-trip 1 GDS : answers back + 4 demandes (`a28a2c0`)
- `[pm]` Golden set export JSONL (`6d7d49d`) — 6 records pour GDS
- `[pm]` Round-trip 2 GDS : prototype δ.1 (`ac39354`) — 3 corrections synthétiques, 0 régression
- `[data]` Validation δ.1 sur 762 erreurs réelles — 15/762 fix potentiel (2 %), confirme mauvais layer → δ.1 mis en réserve
- `[pm]` Handoff Fretwise-001, -002, -003 dans répertoire partagé
- `[pm]` Watcher background `br8tt1kxp` actif sur shared dir
