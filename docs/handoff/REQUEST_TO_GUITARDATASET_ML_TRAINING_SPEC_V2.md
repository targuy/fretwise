# Request To GuitarDataSet — ML Training Spec v2

> Date : 2026-05-21  
> Demandeur : FretWise  
> Destinataire : GuitarDataSet / équipe ML  
> Objet : entraîner les prochains modèles de doigté avec contexte de position et de phrase.

---

## 0. Constat

Le ML actuel charge correctement dans FretWise :

- `finger_classifier.onnx` -> `LearnedChordFingerClassifier`
- `transition_cost_v3.onnx` -> `LearnedPlayerCost`

Il sert un peu, mais il ne suffit pas. Sur un échantillon de morceaux, le modèle
de transition modifie quelques décisions, tandis que le classifieur d'accords
modifie peu de choses hors accords simultanés.

Exemple A/B récent :

| Morceau | Notes | Changements full ML vs règles | PlayerCost | ChordClassifier |
|---|---:|---:|---:|---:|
| Apache | 461 | 43 | 43 | 0 |
| Django Minor Swing | 1786 | 13 | 13 | 0 |
| Heart Crazy On You | 7244 | 7 | 7 | 0 |
| Deep Purple Highway Star | 541 | 8 | 8 | 0 |
| Megadeth Tornado of Souls | 2255 | 72 | 72 | 8 |

Les erreurs signalées par l'utilisateur récemment ne pouvaient pas être bien
résolues par le ML actuel, car elles nécessitent une vision de phrase et de
position de main :

- Django intro : `7-7-5-7-5` doit devenir `ring-ring-index-ring-index`, ancre 5.
- Apache mesure 7 : les frets 2 doivent être joués avec l'index en position 2,
  puis le fret 4 avec l'annulaire.
- Django mesure 16 : éviter un faux petit barré non contigu sur `6-7-6-8`.
- Heart : conserver un vrai barré large sur `5-7-7-7-5`.

Le besoin principal est donc un modèle `phrase/window aware`, pas seulement un
modèle de transition locale.

---

## 1. Contraintes d'intégration FretWise

Ne pas modifier l'interface publique de `ViterbiOptimizer`.

Les modèles doivent s'intégrer via :

1. `CostFunction` pour un coût additif compatible Viterbi.
2. Un resolver post-Viterbi optionnel.
3. Un préprocesseur de position/phrase fournissant des ancres.

Tous les modèles doivent avoir un fallback règle déterministe. Une prédiction ML
ne doit jamais produire de sortie finale biomécaniquement invalide.

---

## 2. Conventions communes

### Cordes

FretWise utilise :

```text
1 = high e
2 = B
3 = G
4 = D
5 = A
6 = low E
```

Si un modèle utilise `0 = high e`, le fichier `_spec.json` doit le documenter.

### Doigts

Valeurs textuelles attendues :

```text
open, index, middle, ring, pinky
```

### Position de main

`hand_position` dans FretWise signifie fret de l'index virtuel :

```text
index  -> offset 0
middle -> offset 1
ring   -> offset 2
pinky  -> offset 3
hand_position = fret - offset
```

Pour le ML, le concept plus stable est `anchor` : fret de référence de la
position de main dans une fenêtre. La règle musicale observée est : le pinky ne
doit pas créer l'ancre ; il sert d'extension depuis une ancre d'index justifiée.

---

## 3. Format dataset demandé

Format recommandé : JSONL, une ligne par morceau, phrase, fenêtre ou accord.

```json
{
  "schema_version": "fretwise-ml-v2",
  "dataset_version": "gds-vX.Y",
  "source_id": "sha1:...",
  "source_file": "relative/path.gp",
  "source_type": "gp|musicxml|midi|chord_library|manual|synthetic",
  "fretwise_commit": "<commit>",
  "quality_verdict": "clean|suspect|bad",
  "annotator": "human|mutopia|uci_chords|jguitar|caged|fretwise_silver|manual_review",
  "confidence": 1.0,
  "style": "rock|blues|jazz|classical|folk|metal|pop|unknown",
  "tuning": [64, 59, 55, 50, 45, 40],
  "notes": []
}
```

Note annotée :

```json
{
  "note_id": 123,
  "measure_index": 7,
  "voice": 0,
  "onset": 24.0,
  "duration": 1.0,
  "tempo": 130.0,
  "pitch": 57,
  "string_num": 3,
  "fret": 2,
  "finger": "index",
  "hand_position": 2,
  "position_anchor": 2,
  "phrase_id": "m7_main",
  "techniques": [],
  "dynamic": "mf",
  "articulation": "normal",
  "is_chord_member": false,
  "chord_id": null,
  "source_note_id": "gpif-note-id-if-available"
}
```

Filtrer les sources `quality_verdict=bad` hors entraînement principal. Les
garder seulement pour tests de robustesse.

Sources recommandées, par ordre de confiance :

1. Annotations humaines vérifiées dans FretWise.
2. Mutopia / classique avec doigtés explicites, après validation.
3. UCI / JGuitar / CAGED pour accords.
4. GP avec `LeftFingering` explicite.
5. Silver standard FretWise, seulement pour pré-entraînement.

---

## 4. Modèle A — `PhraseWindowFingeringModelV1`

### Objectif

Modèle prioritaire. Recevoir une fenêtre de 3 à 8 notes et prédire une ancre de
main + une séquence de doigts cohérente.

Exemples attendus :

```text
Django intro : 7 7 5 7 5 -> ring ring index ring index, anchor=5
Apache m7    : 2 2 2 4 2 -> index index index ring index, anchor=2
```

### Entrée

Fenêtre par voix ou phrase :

```json
{
  "window_id": "song:m7:voice0:24.0",
  "notes": [
    {"string_num": 3, "fret": 2, "pitch": 57, "onset": 24.0, "duration": 2.0},
    {"string_num": 4, "fret": 2, "pitch": 52, "onset": 26.0, "duration": 1.0},
    {"string_num": 4, "fret": 4, "pitch": 54, "onset": 28.0, "duration": 2.0}
  ],
  "candidate_anchors": [1, 2, 3, 4],
  "measure_span": [7, 8],
  "style": "surf_rock",
  "tempo": 130.0
}
```

### Features minimales

Par note :

```text
string_num
fret
pitch
fret_relative_to_min
fret_relative_to_candidate_anchor
onset_delta_from_window_start
duration
is_repeated_position
same_string_as_prev
same_fret_as_prev
measure_index_relative
techniques
```

Par fenêtre :

```text
min_fret
max_fret
fret_span
num_notes
num_strings
string_span
contains_open
contains_chord
starts_new_measure
ends_measure
candidate_anchor
```

Rôles de doigts :

```text
index_anchor_required
ring_natural_for_anchor_plus_2
pinky_natural_for_anchor_plus_3
pinky_used_without_lower_anchor
would_shift_hand_if_no_pinky
```

### Sortie recommandée

Retourner des candidats scorés, pas seulement un argmax :

```json
{
  "candidates": [
    {"anchor": 2, "fingers": ["index", "index", "ring"], "cost": 0.12},
    {"anchor": 1, "fingers": ["middle", "middle", "pinky"], "cost": 1.85}
  ]
}
```

### Métriques

```text
exact_window_match
per_note_finger_accuracy
anchor_accuracy
pinky_false_positive_rate
pinky_false_negative_rate
invalid_assignment_rate
mean_cost_gap_gold_vs_best_wrong
```

La métrique critique est `pinky_false_positive_rate` : le modèle ne doit pas
utiliser le petit doigt pour éviter une position d'index naturelle.

---

## 5. Modèle B — `TransitionPlayerCostV4`

### Objectif

Remplacer `transition_cost_v3.onnx` par un coût local plus riche. Il reste
additif pour Viterbi.

### Manque du modèle actuel

Le v3 ignore en pratique :

```text
hand_position
position_anchor
measure_index
tempo réel
duration en secondes
techniques
articulation
chord membership
phrase/window context
```

### Features v4 demandées

```text
prev_string, prev_fret, prev_finger, prev_hand_position
curr_string, curr_fret, curr_finger, curr_hand_position
prev_anchor, curr_anchor
fret_distance, string_distance, interval_semitones
same_string, same_fret, same_hand_position, same_anchor
duration_prev, duration_curr, tempo, seconds_to_move
measure_delta
voice_same
curr_fret_relative_to_anchor
finger_offset_error
pinky_is_anchor_plus_3
pinky_without_index_anchor
index_anchor_present_recently
articulation, slide_type, bend_value, vibrato, let_ring, staccato
is_chord_member, chord_size
```

### Sortie

Option préférée : distribution de probabilité sur le doigt courant :

```text
p(open), p(index), p(middle), p(ring), p(pinky)
cost = -log(p[curr_finger])
```

Si coût scalaire direct, fournir une calibration pour le rendre comparable au
coût mécanique FretWise. En mode performance, FretWise applique `gamma=2`.

### Métriques

```text
finger_accuracy_global
finger_accuracy_no_open
accuracy_by_finger
MIDDLE_RING_confusion
RING_PINKY_confusion
pinky_overuse_rate
position_anchor_accuracy
NLL
ECE calibration
```

---

## 6. Modèle C — `ChordFingerClassifierV2`

### Objectif

Améliorer le classifieur d'accords actuel. Il s'applique seulement aux accords
simultanés avec au moins deux notes frettées.

### Entrée

Features par note :

```text
string_num
fret
relative_fret
position_in_chord grave_to_treble
num_fretted
num_open
fret_span
min_fret
max_fret
same_fret_count
is_lowest_fret
is_barre_candidate
string_gap_below, string_gap_above
fret_gap_below, fret_gap_above
```

Features accord :

```text
chord_size
open_string_mask
fretted_string_mask
shape_signature_relative
style
tuning
```

### Sortie

Une classe par note frettée :

```text
index|middle|ring|pinky
```

### Contraintes

Les prédictions doivent être rejetées si elles violent :

- ordre naturel des doigts ;
- span biomécanique ;
- même doigt sur frettes différentes ;
- faux petit barré non contigu ;
- conflit non-barré.

### Métriques

```text
finger_accuracy_by_note >= baseline + 5 pp
exact_chord_assignment >= baseline + 5 pp
invalid_prediction_rate <= 0.5 % avant fallback
invalid_prediction_rate_final = 0 % après fallback
```

Reporter séparément : barrés, demi-barrés, accords ouverts, triades, accords 4+
notes, voicings jazz/étendus.

---

## 7. Modèles optionnels

### `PositionSegmentationModelV1`

Prédire :

```json
{
  "positions": [
    {"start_note_id": 120, "end_note_id": 128, "anchor": 5},
    {"start_note_id": 129, "end_note_id": 137, "anchor": 2}
  ]
}
```

Métriques : `boundary_F1`, `anchor_accuracy`, `mean_absolute_anchor_error`,
gain downstream sur doigté.

### `ResolverArbitrationModelV1`

Décider si un resolver doit accepter ou refuser une réécriture. Priorité faible
pour l'instant : FretWise corrige d'abord les règles explicites.

---

## 8. Golden set obligatoire

Créer un set de validation non utilisé à l'entraînement, avec passages courts
vérifiés humainement.

Cas minimum :

| ID | Source | Attendu |
|---|---|---|
| `django_intro_rriri` | Django Minor Swing mesure 1 | `7-7-5-7-5 -> ring-ring-index-ring-index`, anchor 5 |
| `django_m16_no_short_clamp` | Django mesure 16 | `6-7-6-8` sans petit barré index non contigu |
| `heart_wide_barre` | Heart Crazy On You | vrai barré large autorisé |
| `apache_m7_index_anchor` | Apache mesure 7 | f2 en index anchor 2, f4 en ring |
| `open_chord_basic` | C/A/G/E/D ouverts | doigtés traditionnels |
| `power_chord_shape` | rock/metal | index-root, ring/pinky fifth/octave selon forme |
| `position_shift_fast` | run rapide | pas de déplacement inutile |
| `legato_same_string` | hammer/pull/slide | continuité compatible technique |

Format d'un cas :

```json
{
  "case_id": "apache_m7_index_anchor",
  "source_file": "partitions/The Shadows - Apache - 09-03-2025.gp",
  "measure_range": [7, 8],
  "expected": [
    {"string_num": 3, "fret": 2, "finger": "index", "anchor": 2},
    {"string_num": 4, "fret": 2, "finger": "index", "anchor": 2},
    {"string_num": 4, "fret": 4, "finger": "ring", "anchor": 2}
  ],
  "rationale": "index anchors position 2; ring naturally covers fret 4"
}
```

---

## 9. Protocole d'évaluation

Toujours reporter séparément :

```text
rule_only
player_cost_only
chord_classifier_only
phrase_window_only
full_ml
full_pipeline_after_resolvers
```

Métriques globales :

```text
per_note_finger_accuracy
exact_phrase_accuracy
exact_chord_accuracy
anchor_accuracy
fatal_biomechanical_count
high_biomechanical_count
manual_preference_win_rate_on_golden_set
diff_count_vs_rule_only
```

Matrice de confusion obligatoire :

```text
INDEX -> MIDDLE
MIDDLE -> INDEX
MIDDLE -> RING
RING -> MIDDLE
RING -> PINKY
PINKY -> RING
```

Calibration :

```text
NLL
Brier score
expected calibration error
median entropy
uncertain ratio
```

---

## 10. Artefacts attendus

Pour chaque modèle :

```text
data/models/<model_name>.onnx
data/models/<model_name>_spec.json
data/models/<model_name>_calibration.json
data/models/<model_name>_metrics.json
data/models/<model_name>_golden_report.json
```

Le fichier `_spec.json` doit contenir :

```json
{
  "model_name": "phrase_window_fingering_v1",
  "model_version": "1.0.0",
  "fretwise_commit": "...",
  "dataset_version": "...",
  "feature_names": [],
  "output_schema": "...",
  "string_convention": "FretWise 1=high_e",
  "finger_classes": ["open", "index", "middle", "ring", "pinky"],
  "training_sources": {},
  "known_limitations": []
}
```

Le fichier `_calibration.json` doit inclure au moins 10 exemples lisibles par
humain avec features attendues et sorties attendues, pour tests FretWise.

---

## 11. Critères GO / NO-GO

### GO intégration expérimentale

- Le modèle charge via `onnxruntime` dans `pixi`.
- Les features passent les tests de calibration.
- Le golden set ne régresse pas.
- `fatal=0` après pipeline complet.
- Le modèle améliore au moins une métrique utile sans dégrader les cas validés.

### GO activation par défaut

- Gain net sur golden set manuel.
- Gain net sur corpus test propre.
- `invalid_rate_final = 0` après fallback.
- Surcoût d'inférence < 20 % sur morceau moyen.
- Rapport explicable des décisions changées vs règles.

### NO-GO

- Entraîner sur silver standard FretWise puis évaluer seulement sur la même
  distribution.
- Améliorer l'accuracy globale tout en augmentant le pinky parasite.
- Corriger les accords mais dégrader les phrases monophoniques.
- Exiger une modification de l'interface publique de `ViterbiOptimizer`.

---

## 12. Priorité demandée

Ordre recommandé :

1. Construire le golden set manuel section 8.
2. Exporter un dataset de fenêtres pour `PhraseWindowFingeringModelV1`.
3. Entraîner un baseline simple : gradient boosting ou petit modèle séquentiel.
4. Livrer ONNX + spec + calibration + metrics.
5. Ensuite améliorer `TransitionPlayerCostV4`.
6. Réentraîner `ChordFingerClassifierV2` si les accords restent problématiques.

La priorité est le modèle de phrase : c'est le manque observé dans les audits
récents. FretWise doit comprendre une position de main dans une phrase, pas
seulement une transition note à note.