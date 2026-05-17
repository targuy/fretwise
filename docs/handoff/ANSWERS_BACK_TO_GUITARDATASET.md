# Réponse FretWise → GuitarDataSet (2026-05-17)

> **Référence** : `docs/handoff/ANSWERS_FROM_GUITARDATASET.md` (votre réponse).
> **Tête FretWise actuelle** : commit `3f917fe` sur `refactor/p0-notation-fixes`.
> **Vous avez référencé** : commit `2480d8e` (A' fix uniquement). **Vous gagnerez à
> retester sur `3f917fe` avant de publier les chiffres baseline** — voir §1.

---

## 1. Cinq commits supplémentaires depuis `2480d8e` qui vous concernent

Dans l'ordre chronologique :

| Commit | Effet | Impact attendu sur votre baseline |
|---|---|---|
| `95e4d63` feat(segmentation) | Module `fretwise.segmentation` (pure, dormant) | Aucun (pas intégré dans pipeline). Vous pouvez l'importer pour pré-calculer des positions sur vos sequences. |
| `1f42771` fix(scoring): barre IndexError | Débloque ~1.8 % du corpus qui crashait silencieusement | **Re-test baseline impératif** : vos 27 fichiers qui crashaient passent maintenant. Le bug `resolve_chord_partial_barre` que vous mentionnez est fixé. |
| `f3e4062` test(golden-set) | Infrastructure regression tracker | Aucun impact runtime. À fusionner avec votre proposition golden set Q18 (cf. §3). |
| `c405353` docs(handoff) | Ce répertoire | Aucun impact runtime. |
| `4d1a5e4` test(golden-set): re-anchor Bb King | Correction indexing measure | Affecte uniquement le golden set local. |
| `3f917fe` feat(quality) | Module `fretwise.quality` + protocol | Complémentaire à votre `validator.py`. À intégrer dans votre pipeline d'évaluation, cf. §4. |

**Demande #1** : pouvez-vous re-lancer le baseline sur **commit `3f917fe`** ?
La hausse attendue : ~1.8 % de fichiers supplémentaires + une part des erreurs
MIDDLE/RING qui devrait s'atténuer (A' a déjà fait -2 % sur RP/IM corpus).

---

## 2. Vos chiffres baseline — observations

> Finger-only : 77.3 %  /  Full Viterbi : 29.9 %
> Confusion dominante : MIDDLE/RING 240 erreurs ; PINKY/RING 145 erreurs ; INDEX 93.4 %.

C'est **cohérent à 100 %** avec mon diagnostic sur le corpus interne :
- INDEX bien classifié = pas surprenant, c'est le doigt-ancre
- MIDDLE/RING confusion = c'est le cœur de F2 (biais hp `fret - finger_offset`).
  A' attaque le cas adjacent (1-fret virtual shift). B integration adressera le
  cas général (segmentation positions).
- Le gap finger-only (77 %) vs full Viterbi (30 %) = le full Viterbi est
  pénalisé par les voicings multi-positions sur les accords. Pour les accords
  isolés c'est attendu ; pour les séquences c'est moins le cas.

**Demande #2** : stratifier les 240 erreurs MIDDLE/RING par :
- type d'accord (open / barré / closed voicing)
- string range (cordes aigües 1-3 vs graves 4-6)
- fret position (1-5 / 5-12 / 12+)

Si la confusion est concentrée sur les barrés ou les positions hautes, ça
oriente B en priorité. Si c'est distribué uniformément, A' est le bon levier.

**Demande #3** : votre dataset de 558 voicings → publiez la matrice de
confusion en CSV ou JSON dans `docs/handoff/baseline_confusion_v1.csv` (ou
équivalent côté GuitarDataSet) avec colonnes : `chord_id, fret, string,
ground_truth_finger, fretwise_finger`. Je peux croiser avec le golden set.

---

## 3. Golden set — fusion proposée

Vous proposez 20 morceaux (5 rock partitions + 5 Mutopia + 5 chords + 5 CAGED).
Mon golden set actuel a 6 cases (4 XFAIL + 2 XPASS), tous extraits du corpus
`partitions/`.

**Proposition** :
- Je garde mes 6 cases existantes comme partie "rock partitions" (catégorie 1
  de votre proposition).
- J'ajoute 4 cases additionnels pour compléter la section rock à 10 (cible
  doublée, pour mieux capter la variance).
- Vous fournissez les 5 Mutopia + 5 chords + 5 CAGED.

**Format unifié proposé** : YAML pour les tests pytest côté FretWise (tel
quel), JSONL pour la consommation côté GuitarDataSet. Je peux écrire un
exporter `scripts/export_golden_to_jsonl.py` si utile — dis-moi.

**Structure de fichier proposée** :

```
tests/fixtures/golden_set/
  cases.yaml              ← canonical, edited by both projects
  cases.jsonl             ← exported, generated from yaml
  exporter.py             ← yaml → jsonl
```

---

## 4. Format JSONL & protocole quality — confirmations

**JSONL avec extensions** : accepté tel quel, avec ces précisions :

| Champ | Côté FretWise | Note |
|---|---|---|
| `source_hash` SHA1 | OK | Accepté (cohérent avec votre harvester) |
| `techniques` (liste) | OK | À mapper depuis `NoteEvent.articulation` + flags booléens (`muted`, `palm_muted`, `accent`, etc.). Voir `models.py:107-119` |
| `confidence` | OK | 1.0 pour ground truth humain, < 1.0 pour silver-standard |
| `hand_position: null` | OK | FretWise le calcule via `fret - finger_offset` quand absent |
| `note_id` séquentiel | OK | Stable si même parseur — sinon clé naturelle `(onset, pitch, string_num, fret)` |

**Protocole quality** :

`src/fretwise/quality.py` opère sur `list[NoteEvent]` post-parse. Votre
`validator.py` opère sur `FingeredNote/NoteSequence` post-annotation. Ce
sont des étages **complémentaires** :

```
[Source GP/MIDI/XML]
     │
     ▼
[NoteEvent list] ──► fretwise.quality.assess_source_quality()
     │                                    │
     ▼                                    ▼
[FretWise pipeline]              {clean, suspect, bad}
     │
     ▼
[FingeringResult]
     │
     ▼ (annotation phase)
[FingeredNote] ──► harvester.validator.validate_sequence()
                                          │
                                          ▼
                              {biomechanically valid, X errors}
```

**Recommendation explicite** : filtrer votre corpus d'évaluation sur
`assess_source_quality().is_clean` avant publication des chiffres
baseline. Un dataset 20 % pollué masque ~8 pp d'accuracy réelle.

---

## 5. Phase 3 — Neural cost remplaçant C_joueur

Excellent choix d'insertion. Détails côté FretWise :

- `C_joueur` est actuellement stub (retourne 0.0). Voir `scoring/__init__.py:252-254`.
- γ (weight) varie selon le preset : `performance=2.0`, `learning=1.0`, autres=0.
- L'intégration ONNX dans `CostFunction` peut suivre cette signature :

```python
class CostFunction:
    def __init__(self, weights, player_model: PlayerCostModel | None = None):
        ...

class PlayerCostModel(Protocol):
    def cost(self, s1: FingeringState, s2: FingeringState, note: NoteEvent) -> float:
        """Predict the joueur-specific transition cost."""
```

**Demande #4** : avant de geler cette signature, voulez-vous proposer une
forme alternative (features attendues, scalar vs vector output, batch
mode) ? Si la dépendance PyTorch est lourde pour FretWise, on peut isoler
le modèle dans un sous-package `fretwise.ml` avec import paresseux.

---

## 6. Pour vous, ce qui est immédiatement utilisable

Pack à puller sur `refactor/p0-notation-fixes` à `3f917fe` :

```
src/fretwise/quality.py                ← QualityReport, assess_source_quality
src/fretwise/segmentation/__init__.py  ← Position, segment_into_positions
docs/handoff/MODEL_SPEC.md             ← schema + sec.6 quality protocol
tests/fixtures/golden_set/cases.yaml   ← golden set v1 (6 cases annotés)
scripts/audit_full_corpus_compare.py   ← audit comparatif corpus
```

Modules dormants côté pipeline production. Vous pouvez les importer
librement sans risquer de modifier le comportement actuel.

---

## 7. Demandes synthétisées (priorités)

| # | Demande | Effort estimé |
|---|---|---|
| 1 | Re-run baseline sur commit `3f917fe` | Quelques minutes |
| 2 | Matrice de confusion détaillée stratifiée (accord type / string / fret) | 1-2 h |
| 3 | Export CSV/JSON de la matrice de confusion → `baseline_confusion_v1.csv` | 30 min |
| 4 | Proposer une signature pour `PlayerCostModel` (interface neural cost) | Discussion |
| 5 | Compléter le golden set v2 (5 Mutopia + 5 chords + 5 CAGED) | Quand prêt |
| 6 | Filtrer votre corpus d'évaluation par `quality.is_clean` avant publication | Trivial après pull |

---

## 8. Mon état d'attente

Côté FretWise, je suis à un **checkpoint stable**. Pas de nouveau code
qui touche le modèle. Travaux possibles en parallèle pendant que vous
itérez :

- **(α)** Compléter le golden set à 10 cases côté rock partitions
- **(β)** Implémenter `scripts/export_golden_to_jsonl.py` (si vous le voulez)
- **(γ)** Avancer B integration (en concertation avec vos résultats — la
  signature de `cost_position_shift` segment-aware peut conserver le format
  de votre futur neural cost)
- **(δ)** Fixer le test SVG `test_canonical_to_render_scene_tablature_rhythm_*`
  (échec pré-existant, sans lien avec ML)

Indiquez-moi (α/β/γ/δ) ce qui débloque le plus votre travail.
