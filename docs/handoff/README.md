# Handoff FretWise ↔ GuitarDataSet

> **Objectif :** synchroniser FretWise (moteur de doigté) et GuitarDataSet
> (préparation dataset ML) pour qu'ils progressent en parallèle sans casser
> les contrats partagés.

---

## Statut au 2026-05-17

- **FretWise** : moteur Viterbi + scoring composite opérationnel. Patch A'
  (tolérance hp shift) livré, gain mesuré -1.98 % sur ratio RP/IM corpus 2M
  notes. Module `segmentation/` (B v0) prêt mais pas intégré.
- **GuitarDataSet** : intègre `guitar-fingerings-harvester`. Prépare un
  dataset annoté pour ML. (À compléter par l'équipe ML.)

## Documents de ce répertoire

| Fichier | Pour qui | Contenu |
|---|---|---|
| `README.md` | Les deux équipes | Ce fichier — orchestration |
| `MODEL_SPEC.md` | **Équipe ML** | Schémas FretWise, contrats pipeline, points d'intégration ML |
| `QUESTIONS_FROM_FRETWISE.md` | **Équipe ML** | Ce que FretWise a besoin de savoir |

## Règles de coordination

1. **Modèle de données = contrat figé** jusqu'à révision conjointe.
   `NoteEvent`, `FingeringState`, `FingeringResult`, `Position` sont
   exposés dans `src/fretwise/models.py` et `src/fretwise/segmentation/`.
   Toute modification de ces structures doit être annoncée dans une
   issue / PR avec migration documentée.

2. **Internes mutables** : tout ce qui est sous `scoring/`, `optimizer/`,
   `generator/`, `patterns/` peut bouger sans préavis tant que les
   contrats d'entrée/sortie sont respectés.

3. **Pas d'intégration B (segmentation → scoring) sans coordination.**
   L'intégration ajoutera probablement une annotation segment-level aux
   états. ML doit être consulté avant pour aligner l'apprentissage.

4. **FretWise reste opérationnel.** Branche `refactor/p0-notation-fixes`
   = main de travail. Toute modification ML-aligned passe par PR
   reviewable, jamais en force push.

5. **Cadence sync** : à définir avec l'équipe ML. Suggestion : un point
   par sprint, avec MODEL_SPEC.md à jour comme source de vérité.

## Workflow multi-agent recommandé

```
FretWise agent                     GuitarDataSet agent
     │                                       │
     ├─ Stabilise contrats ─────────────────►│
     │  (cf. MODEL_SPEC.md)                  │
     │                                       │
     │◄──── Format dataset proposé ──────────┤
     │      (cf. QUESTIONS répondues)        │
     │                                       │
     ├─ Valide format, écrit loader ────────►│
     │                                       │
     │◄──── Premier échantillon dataset ─────┤
     │                                       │
     ├─ Mesure FretWise vs ground truth ────►│
     │  (script à créer)                     │
     │                                       │
     │◄──── Itération annotation/coverage ───┤
     │                                       │
     └─ B integration alignée sur ML ────────►
```

## Points d'attention

- **Crash bug pré-existant** dans `resolve_chord_partial_barre` :
  ~1.8 % du corpus (27/1519 fichiers). Doit être documenté pour l'équipe
  ML qui hittera les mêmes cas. Fix prévu côté FretWise, ETA non
  bloquant pour le handoff.

- **Hand viz pivot** : le module `export/hand_viz.py` est en train de
  pivoter vers une approche template (cf. plan stratégique). Pas dans
  le scope du handoff ML — séparé.

- **Iino 2025** : si l'équipe ML utilise ce dataset (40 études classiques
  annotées doigt complet), prévenir tôt — le profil stylistique étroit
  pourrait limiter la généralisation au répertoire FretWise (rock/folk
  /pop).
