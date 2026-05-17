# Board — Kanban léger

> **Format** : 4 colonnes (TODO / DOING / BLOCKED / DONE).
> **Tags** : `[role]` au début de chaque carte (cf. `roles.md`).
> **Mise à jour** : à chaque commit ou status check par le PM.
> **Dernière revue** : 2026-05-17 (post round-trip 4 avec GDS).

---

## DOING

- `[data]` R-C6 string-diagonal investigation préliminaire — pattern miroir D-shape barre identifié (DEC-007). Findings dans decisions log.

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

### Session 2026-05-17

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
