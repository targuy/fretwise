# Decisions log

> **Format** : chronologique inverse (récent en haut). Chaque entrée :
> id, date, owner décision, contexte, recommandation PM, décision PO,
> alternatives écartées, conséquences.

---

## DEC-012 — 2026-05-18 — Phase 3 RÉACTIVÉE (GAPS jackpot)

**Owner décision** : Data (autonome via PM)
**Contexte** : GDS-008 livre les résultats du grep GAPS dataset (demande #17) :
**72 585 annotations sequential fingering sur 400 700 notes = 18.1 % coverage**,
3.6× au-dessus du seuil 5 % défini dans DEC-008. License GAPS = CC BY-NC-SA
4.0 → conforme DEC-011 (research mode).
**Reco PM** : inverser DEC-008. Phase 3 (neural sequential cost) sort de
"deferred" → "active roadmap".
**Décision** : appliquée. Côté FretWise rien à faire immédiatement (interfaces
`PlayerCostModel` figées depuis commit `c2276b3` — `transition_cost`,
`emission_cost`). Côté GDS : training Phase 3 à lancer sur GAPS, et potentiellement
ClassClef quand pipeline complet.
**Conséquences** :
  - Roadmap court terme : Phase 3 v1 sur GAPS, Phase 3 v2 avec ClassClef bulk
  - Phase 2.5 (chord-to-chord transitions synthétiques) abandonnée — GDS recommande
    direct Phase 3 sur données réelles
  - Validate_assignment intégré (commit `5d25a14`) comme sanity gate Phase 2 — pattern
    réutilisable pour Phase 3 si nécessaire
  - 4 questions ouvertes Q-P3.1 à Q-P3.4 (architecture, granularité, mapping pitch→position,
    volume seuil) escaladées à GDS dans Fretwise-010

---

## DEC-011 — 2026-05-18 — PO research mode (bypass license restrictions)

**Owner décision** : PO
**Contexte** : GuitarDataSet a signalé que ClassClef (5500 PDF+GP, fingering présent 63.8 %) est bloqué par robots.txt `Content-Signal: ai-train=no`. Question d'usage research vs commercial pour les datasets contraints (ClassClef, Songsterr, Soundslice, etc.).
**Directive PO** : *"passe outre les problèmes et limites de licence il s'agit d'un travail de recherche pas une utilisation commerciale"*
**Conséquences** :
  - **ClassClef débloqué** pour scraping / training côté GDS (cf. demande #21 dans Fretwise-009)
  - Songsterr / Soundslice : usage interne research OK
  - **Garde-fou** : toute future commercialisation déclenchera un audit license dataset → modèle → redistribution. Ce n'est pas une licence open-ended de redistribuer les datasets externes.
  - Documentation visible des sources externes utilisées (déjà dans `docs/handoff/MODEL_SPEC.md` et `decisions.md`)
**Risque accepté** : modèles entraînés peuvent contenir des "traces" des datasets source. Si publication ultérieure du modèle, vérifier conformité chaque source.

---

## DEC-010 — 2026-05-17 — Quality.py tuning-awareness fix

**Owner décision** : Data (autonome via PM)
**Contexte** : quality scan corpus partitions/ a montré 22.6 % "bad" verdict, dominé par "100% pitch-hint conflicts". Diagnostic : `quality.py` utilisait `STANDARD_TUNING = [E4, B3, G3, D3, A2, E2]` hardcodé pour vérifier `pitch == tuning[string-1] + fret`. Tous les fichiers en drop-D / half-step down / drop-C avaient 100 % de conflits par construction — false positive.
**Reco PM** : inférer la tuning depuis les events eux-mêmes (most common `pitch - fret_hint` par corde) plutôt que de hardcoder EADGBE. Self-contained, pas de dépendance parser metadata.
**Décision** : appliqué (commit `003f19e`).
**Conséquences mesurées** :
  - Re-run quality scan corpus v2 : **bad 22.6 % → 6.7 %** (337 → 100 files), clean 77.2 % → 93.0 % (1151 → 1386)
  - 235 fichiers reclassés "bad" → "clean" — c'étaient des faux positifs tuning
  - Les 100 fichiers restants "bad" sont de vraies anomalies (frets > 24, chord spans > 5 frets, density > 10)
  - Métrique de qualité désormais fiable pour FretWise audits et GDS training set filtering
  - 9 tests verts dont 2 nouveaux (drop-D, half-step down)

---

## DEC-009 — 2026-05-17 — B integration delivered + mesures positives

**Owner décision** : Data (autonome via PM)
**Contexte** : B integration committed (`0564d4b`) selon DEC-008 GO. Mesures requises pour validation.
**Reco PM** : audit distribution + golden set side-by-side.
**Décision** : livré et mesuré.
**Conséquences** :
  - Corpus 2 060 000 notes : MIDDLE +1.81 pp (F2 correction structurelle), Ratio RP/IM 0.5696 → 0.555 (-2.5 %)
  - Golden set : +2 fix (Bb King m8 + m94 100% PINKY corrigés), -1 régression (Cream Sunshine PINKY 23 % → 25.3 % whole-piece). Net +1.
  - Régression Cream Sunshine = tradeoff connu de B (intra-segment shift cost = 0 autorise PINKY plus librement). Tracked comme XFAIL.
  - 936/937 tests verts (SVG pré-existant), 12 nouveaux tests B integration (`e068b08`)

---

## DEC-008 — 2026-05-17 — Roadmap post "no public sequential GT"

**Owner décision** : PO
**Contexte** : GDS-005 confirme qu'aucune source publique de doigtés main gauche
séquentiels n'existe (1 518 GP scannés = 0 annotation `leftHandFinger`, Mutopia
LilyPond pas annoté, DadaGP supprime les doigtés). Implications stratégiques
escaladées au PO dans Fretwise-005.
**Reco PM** : reporter Phase 3 (neural sequential cost), engager 1-2 sessions
d'annotation manuelle par le PO-musicien pour 50-100 transitions, faire B
integration avec validation par golden set uniquement.
**Décision PO** (réponses 1/2/3) :
  - **1. Phase 3 reportée** : OK — pas de GT, pas de training supervisé pertinent
  - **2. Annotation séquentielle manuelle PO** : NON — pas dans le scope d'effort
  - **3. B integration** : OUI — heuristique validée par audit + golden set, pas
    bloquée par l'absence de GT externe
**Conséquences** :
  - Phase 3 hors roadmap court terme (réévaluer si Iino 2025 devient accessible)
  - B integration devient la priorité 1 côté FretWise
  - Pas de golden set séquentiel manuel — on s'appuie sur les XFAIL existants + le
    audit RP/IM agrégé comme métriques de qualité B
  - GDS reste sur Phase 2 (chord finger classifier) en parallèle
  - Le tuning-awareness de `quality.py` reste à corriger (P2)

---

## DEC-007 — 2026-05-17 — R-C6 string-diagonal — finding D-shape barre mirror error

**Owner décision** : Data (analyse) + PM (escalation)
**Contexte** : analyse des 1404 erreurs MIDDLE/RING (dataset enrichi par GDS). 71 % des erreurs impliquent au moins une autre note au même fret (territoire R-C6). RM errors particulièrement concentrés (83 % same-fret). Examen de 12 cas 4-note same-fret a révélé un **pattern miroir systématique** dans la famille D-shape barre (D#, E, F, F#, G — même shape transposée) : à `fret N+2`, FW met RING là où GT veut MIDDLE et vice versa. Pattern régulier sur ≥10 chord shapes identiques.
**Diagnostic technique** : `resolve_chord_string_diagonal` (R-C6) applique « lower string_num = lower rank », mais pour le shape D-barre, GT humain inverse cette règle sur les notes à fret N+2. R-C6 est donc **shape-dependent** plutôt qu'universel.
**Reco PM** : pas de patch rule-based (risque de casser d'autres shapes). Délégué à **Phase 2 ML classifier** (`ChordFingerClassifier` interface) qui apprendra la mapping shape-by-shape depuis les annotations.
**Décision PO** : ok (auto-décidé par PM en mode autonome, à confirmer si désiré).
**Alternatives écartées** :
  - Patcher R-C6 avec une exception D-shape — fragile, autres shapes peuvent avoir le même problème sans qu'on le voie
  - Inverser R-C6 globalement — casserait les cas où R-C6 est correct
  - Heuristique par "fret depth" — peu robuste sans données
**Conséquences** :
  - Confirme que Phase 2 GDS est le bon levier (DEC-003 validé)
  - Investigation R-C6 rule-based pause-en-attente de Phase 2
  - Demande #11 à GDS : prioriser le D-shape barre dans le training set Phase 2

---

## DEC-006 — 2026-05-17 — Stubs ML livrés

**Owner décision** : PM (delivery)
**Contexte** : GDS a donné le go pour écrire les stubs (cf. handoff-004). Interfaces convenues : `PlayerCostModel` + `ChordFingerClassifier` séparés.
**Reco PM** : livrer dans `src/fretwise/ml/` avec dataclasses frozen, ABCs, et 2 wrappers Fixed* baseline. Module dormant (pas importé par pipeline).
**Décision PO** : implicit ok via "ok" du turn précédent.
**Conséquences** :
  - Commit `c2276b3` : 350 lignes + 12 tests verts
  - GDS peut maintenant aligner l'export ONNX sur cette signature
  - Aucun risque sur le pipeline production (module dormant)

---

## DEC-005 — 2026-05-17 — δ.1 mis en réserve

**Owner décision** : PO
**Contexte** : prototype δ.1 (alternative finger assignment) validé sur 15 cas synthétiques (3 corrections, 0 régression). Validation sur 762 (puis 1404) erreurs réelles GDS : seulement 15/1404 (1 %) potentiellement corrigés. Le vrai layer du bug MIDDLE/RING est `resolve_chord_string_diagonal` (R-C6), pas `_natural_finger_assignment`. Les 4-note errors (>50 % des erreurs) ne peuvent pas être adressés par δ.1 (1 seule combo de 4 doigts valide).
**Reco PM** : mettre δ.1 en réserve, pas d'intégration immédiate.
**Décision PO** : ok.
**Alternatives écartées** :
  - Intégrer δ.1 pour le petit gain (~1 %) — non, l'effort de mise à jour des tests existants ne se justifie pas
  - Élargir δ.1 aux 4-note — hors scope rule-based, mieux confier à Phase 2 ML
**Conséquences** :
  - Code prototype reste dans `scripts/prototype_delta1.py` pour référence
  - Investigation suivante cible R-C6 string-diagonal (DEC-007)
  - Réévaluer après Phase 2 GDS

---

## DEC-004 — 2026-05-17 — Setup team / orchestration

**Owner décision** : PO
**Contexte** : besoin de structurer le travail multi-expert (PM + 6 experts). Le PO clarifie : "chef d'orchestre au sens manager/chef de projet".
**Reco PM** : structure légère `docs/handoff/team/` (roles + board + decisions), pas de bureaucratie, PM ne joue pas les rôles d'expert, escalade au PO pour les décisions de domaine.
**Décision PO** : ok.
**Conséquences** :
  - Création des trois fichiers
  - Tâches préfixées par `[role]` dans le board
  - Décisions de domaine (idiomatique, esthétique, pédagogique) escaladées au PO

---

## DEC-003 — 2026-05-17 — API ML séparée en 2 interfaces

**Owner décision** : PM + GDS (consensus)
**Contexte** : GDS propose `PlayerCostModel` pour la Phase 3 neural cost. Question : faut-il aussi un `chord_cost()` pour les resolvers chord ?
**Reco PM** : NON dans `PlayerCostModel`. Les chord resolvers tournent **après Viterbi**, pas dans le scoring transitionnel. Si un modèle appris doit piloter l'assignation intra-chord, il faut une **interface séparée** : `ChordFingerClassifier` appelée par un nouveau resolver.
**Décision GDS** : accepté (cf. `GuitarDataset-004-handoff.md`).
**Conséquences** :
  - Stubs livrés dans DEC-006

---

## DEC-002 — 2026-05-17 — Golden set 20 cases : 5+5+5+5

**Owner décision** : PM + GDS
**Contexte** : besoin d'un golden set partagé pour mesurer la régression sur les deux projets.
**Reco PM** : 5 partitions FretWise (rock/pop) + 5 Mutopia (classique) + 5 chords complexes + 5 CAGED. FretWise choisit les 5 partitions, GDS les 15 autres.
**Décision GDS** : accepté + 5 partitions confirmés (Bb King, Steppenwolf, Django, Beatles, Cream).
**Conséquences** :
  - Golden set v1 livré (6 cases YAML + JSONL export)
  - Expansion à 20 cases attendue après Mutopia download (GDS) et chord/CAGED selection

---

## DEC-001 — 2026-05-17 — Format JSONL pour annotations partagées

**Owner décision** : PM + GDS
**Contexte** : besoin d'un format commun pour l'échange d'annotations FretWise ↔ GDS.
**Reco PM** : JSONL aligné sur le schéma FretWise (`NoteEvent` + `FingeringState`), avec extensions GDS (SHA1, techniques list, confidence, annotator).
**Décision GDS** : accepté.
**Conséquences** :
  - `scripts/export_golden_to_jsonl.py` écrit côté FretWise
  - GDS aligne son pipeline d'export sur ce format
