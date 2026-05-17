# Decisions log

> **Format** : chronologique inverse (récent en haut). Chaque entrée :
> id, date, owner décision, contexte, recommandation PM, décision PO,
> alternatives écartées, conséquences.

---

## DEC-005 — 2026-05-17 — δ.1 mis en réserve

**Owner décision** : PO
**Contexte** : prototype δ.1 (alternative finger assignment) validé sur 15 cas synthétiques (3 corrections, 0 régression). Validation sur 762 erreurs réelles GDS : seulement 15/762 (2 %) potentiellement corrigés. Le vrai layer du bug MIDDLE/RING est `resolve_chord_string_diagonal` (R-C6), pas `_natural_finger_assignment`. Les 4-note errors (371, soit 49 % des erreurs) ne peuvent pas être adressés par δ.1 (1 seule combo de 4 doigts valide).
**Reco PM** : mettre δ.1 en réserve, pas d'intégration immédiate.
**Décision PO** : ok.
**Alternatives écartées** :
  - Intégrer δ.1 pour le petit gain (2 %) — non, l'effort de mise à jour des tests existants ne se justifie pas pour 2 %.
  - Élargir δ.1 aux 4-note (chercher une variante qui éliminerait un doigt) — non, hors scope rule-based, mieux confier à Phase 2 ML.
**Conséquences** :
  - Le code prototype reste dans `scripts/prototype_delta1.py` pour référence.
  - La prochaine investigation cible R-C6 string-diagonal sur les 4-note errors.
  - Réévaluer après Phase 2 GDS pour décider si δ.1 reste pertinent dans un monde où le chord finger est appris.

---

## DEC-004 — 2026-05-17 — Setup team / orchestration

**Owner décision** : PO
**Contexte** : besoin de structurer le travail multi-expert (PM + 6 experts). Le PO clarifie : "chef d'orchestre au sens manager/chef de projet".
**Reco PM** : structure légère `docs/handoff/team/` (roles + board + decisions), pas de bureaucratie, PM ne joue pas les rôles d'expert, escalade au PO pour les décisions de domaine.
**Décision PO** : ok.
**Conséquences** :
  - Création des trois fichiers (this commit).
  - Tâches préfixées par `[role]` dans le board.
  - Décisions de domaine (idiomatique, esthétique, pédagogique) escaladées au PO.

---

## DEC-003 — 2026-05-17 — API ML séparée en 2 interfaces

**Owner décision** : PM + GDS (consensus)
**Contexte** : GDS propose `PlayerCostModel` pour la Phase 3 neural cost. Question : faut-il aussi un `chord_cost()` pour les resolvers chord ?
**Reco PM** : NON dans `PlayerCostModel`. Les chord resolvers tournent **après Viterbi**, pas dans le scoring transitionnel. Si un modèle appris doit piloter l'assignation intra-chord, il faut une **interface séparée** : `ChordFingerClassifier` appelée par un nouveau resolver.
**Décision GDS** : accepté (cf. `GuitarDataset-004-handoff.md`).
**Conséquences** :
  - Stubs à écrire : `src/fretwise/ml/` avec `PlayerCostModel`, `ChordFingerClassifier`, `PlayerContext`, `ChordNote`.
  - `PlayerContext` en dataclass frozen. `finger` en str. `ChordNote.is_barre_candidate: bool`.

---

## DEC-002 — 2026-05-17 — Golden set 20 cases : 5+5+5+5

**Owner décision** : PM + GDS
**Contexte** : besoin d'un golden set partagé pour mesurer la régression sur les deux projets.
**Reco PM** : 5 partitions FretWise (rock/pop) + 5 Mutopia (classique) + 5 chords complexes + 5 CAGED. FretWise choisit les 5 partitions, GDS les 15 autres.
**Décision GDS** : accepté + 5 partitions confirmés (Bb King, Steppenwolf, Django, Beatles, Cream).
**Conséquences** :
  - Golden set v1 livré (6 cases YAML + JSONL export).
  - Expansion à 20 cases attendue après Mutopia download (GDS) et chord/CAGED selection.

---

## DEC-001 — 2026-05-17 — Format JSONL pour annotations partagées

**Owner décision** : PM + GDS
**Contexte** : besoin d'un format commun pour l'échange d'annotations FretWise ↔ GDS.
**Reco PM** : JSONL aligné sur le schéma FretWise (`NoteEvent` + `FingeringState`), avec extensions GDS (SHA1, techniques list, confidence, annotator).
**Décision GDS** : accepté.
**Conséquences** :
  - `scripts/export_golden_to_jsonl.py` écrit côté FretWise.
  - GDS aligne son pipeline d'export sur ce format.
