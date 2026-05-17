# Team — charters et RACI

> **Format** : minimal. Un paragraphe par rôle. Pas de hiérarchie formelle.
> Le PM (Claude FretWise) coordonne ; le PO (Benoît) tranche.

## Rôles

### 🎯 PO — Product Owner
**Qui** : Benoît (utilisateur).
**Décide** : priorités, scope, arbitrages techniques majeurs, budget temps, périmètre de release.
**Surface** : reçoit du PM les décisions formatées (contexte + reco + alternatives écartées). Réponse minimale acceptée (1 mot / 1 ligne).

### 🎼 PM — Project Manager
**Qui** : Claude (session FretWise).
**Mission** : coordonne les canaux, alloue les tâches, tient le board, journalise les décisions, gère le handoff multi-projet (ML), surface les blocages au PO.
**Délivre** : code FretWise (commits, branches), docs handoff, status snapshots, decisions log.
**Ne décide pas** : choix idiomatiques guitare, esthétique UI, pédagogie. Délègue ou escalade au PO.

### 📊 Data
**Mission** : qualité corpus, schémas, métriques baseline, validation statistique de modèles, croisement de sources.
**Délivre** : audits dans `scripts/`, rapports dans `docs/benchmarks/`, validation des assertions ML.
**Plug-in** : `fretwise.quality`, audit scripts, golden set.

### 🧪 QA
**Mission** : tests automatiques, golden set, régression, CI/CD, couverture, tests cross-projet.
**Délivre** : `tests/test_*`, `tests/fixtures/golden_set/cases.yaml`, configuration pytest, badges.
**Plug-in** : CI hooks, pytest config.

### 🌐 Web BE — Web Backend
**Mission** : API FastAPI, endpoints, contrats JSON, performance, sécurité.
**Délivre** : `src/fretwise/web/app.py`, specs OpenAPI, validation request/response.

### 🎸 Music — Musicien
**Mission** : validation idiomatique des doigtés, ground truth, edge cases stylistiques, golden set qualitatif.
**Délivre** : annotations dans `golden_set/cases.yaml` (champ `annotation_status: verified`), commentaires par style (jazz, blues, classique, …).
**Plug-in** : ground-truth manuel pour les XFAIL.

### 🎨 Design — Webdesigner
**Mission** : UI/UX, accessibilité, design system, animation visualisation main.
**Délivre** : maquettes, prototypes, `web/static/` (CSS, SVG, animations), tokens de design.

### 🎓 Edu — Expert pédagogie & formation musicale
**Mission** : modes d'apprentissage, parcours utilisateur, feedback didactique, indicateurs de progression.
**Délivre** : specs mode `learning`, scoring weights pédagogiques, voix UX apprentissage.
**Plug-in** : `CostWeights.learning()`, futur module profil joueur (Phase 5).

### 🧠 GDS — Agent GuitarDataSet
**Mission** (équipe distincte) : préparation dataset ML, harvester, finger classifier Phase 2, neural cost Phase 3.
**Canal** : `E:\DocumentsBenoit\pythonProject\handoff-FretWise-GuitarDataset\`.
**Contrat** : `docs/handoff/MODEL_SPEC.md`.

## RACI rapide par chantier

| Chantier | Responsible | Accountable | Consulted | Informed |
|---|---|---|---|---|
| A' tolérance hp | PM | PO | Data (mesure) | GDS, QA |
| B segmentation positions | PM | PO | Data, QA | GDS |
| δ.1 chord finger | PM | PO | Music (idiomatique), Data | GDS, QA |
| Bug barre `resolve_chord_partial_barre` | PM | PO | QA | — |
| Golden set | QA + PM | PO | Music | GDS |
| Hand viz templates | Design | PO | Music | — |
| Mode learning | Edu | PO | Music, Web BE | — |
| Endpoint solve perf | Web BE | PO | Data | — |
| Phase 2 finger classifier | GDS | PO | Data, QA | PM |
| Phase 3 neural cost | GDS + PM | PO | Data | QA |

## Règle d'escalade

1. Si un chantier nécessite une décision de domaine (idiomatique, pédagogique, esthétique) → escalader **PO** via decisions log + message court.
2. Si un blocage technique > 1 h → escalader **PO** ou marquer `BLOCKED` dans board.
3. Si un risque de release ou de version drift inter-équipes → escalader **PO**, copier **GDS**.
