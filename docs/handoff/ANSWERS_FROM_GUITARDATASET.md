# Réponses de GuitarDataSet aux questions FretWise

> **Date** : 2026-05-17
> **Projet** : GuitarDataSet (E:\DocumentsBenoit\pythonProject\GuitarDataSet)
> **Commit FretWise de référence** : branche `refactor/p0-notation-fixes`

---

## 1. Périmètre et timeline

**Q1. Quel est le but du dataset ?**

- [x] Évaluer FretWise vs ground truth (mesure qualité) — **étape 1**
- [x] Entraîner un classifieur finger-only (string+fret donnés, prédire finger) — **étape 2**
- [x] Entraîner une fonction de coût globale C_méca apprise — **étape 3**
- [ ] Entraîner un modèle position-aware (segmentation + finger) — **plus tard**

Stratégie en 3 phases :
1. **Baseline** : faire tourner FretWise sur les données annotées, mesurer accuracy/concordance
2. **Finger classifier** : modèle léger (gradient boosting ou petit MLP) qui prédit finger étant donnés (string, fret, contexte local)
3. **Neural cost** : remplacer C_joueur (gamma) par un réseau appris, injecté dans le Viterbi existant

**Q2. Quand le premier échantillon utilisable sera-t-il disponible ?**

- **Disponible maintenant** : 558 voicings d'accords avec doigts complets (JGuitar + built-in), 420 transpositions CAGED
- **Court terme (semaines)** : UCI Guitar Chords (2 633 accords avec doigté complet, open license) — téléchargement à lancer
- **Moyen terme (1-2 mois)** : Mutopia classical (395 pièces cataloguées, download à lancer, doigté dans le MusicXML), DadaGP (26 181 morceaux GP — accès à confirmer)
- **Synthétique (illimité)** : FretWise lui-même peut générer des annotations "silver standard" via Viterbi sur les 5.5M notes du corpus bulk (1519 fichiers GP sans doigté)

Volume estimé premier échantillon exploitable : ~3 000 accords annotés + premières séquences classiques Mutopia. Objectif 50K+ transitions annotées.

**Q3. Quelle est la couverture stylistique cible ?**

- **Immédiat** : accords (tous styles), classique (Mutopia, Iino si accessible)
- **Corpus bulk** : rock / metal (1519 fichiers GP communautaires) — input sans annotations, utilisable pour évaluation FretWise ou silver-standard via Viterbi
- **Cible** : rock / blues / folk / pop / classique / fingerstyle. La couverture jazz dépendra des sources trouvées.

Alignement avec le corpus FretWise `partitions/` (rock/pop/blues/folk) : bon recouvrement.

---

## 2. Sources et annotation

**Q4. D'où viennent les annotations de doigts ?**

- [x] Plusieurs sources fusionnées :
  - **Accords** : JGuitar scraper (558 voicings), UCI Guitar Chords (2 633, open license), JSON chord libraries
  - **Patterns** : CAGED (420 transpositions, 7 types de gammes × 5 shapes × 12 tonalités)
  - **Scores classiques** : Mutopia Project (395 pièces, MusicXML avec doigté), potentiellement Iino 2025
  - **GP avec doigté** : si des fichiers avec `LeftFingering` existent (0 dans le corpus bulk actuel, mais le parseur les détecte)
  - **Synthétique** : FretWise Viterbi comme annotateur silver-standard

- [ ] ~~Vidéos YouTube via MediaPipe Hands~~ — pas dans le scope actuel, phase ultérieure

**Q5. Quelle est la qualité estimée des annotations ?**

| Source | Qualité estimée | Contrôle |
|--------|----------------|----------|
| JGuitar accords | Haute (curé manuellement) | Validation biomécanique (`validator.py`) : span ≤5, pas de doigt sur multiple frets |
| UCI Guitar Chords | Haute (dataset académique) | À valider après import |
| CAGED patterns | Parfaite (règles déterministes) | Couverture exhaustive vérifiée |
| Mutopia MusicXML | Variable (dépend du transcripteur) | Validation post-import via `validate_sequence()` |
| FretWise silver-standard | Aussi bonne que FretWise lui-même | Justement ce qu'on mesure en phase 1 |

**Q6.** Pas de MediaPipe actuellement. La vision (photos/vidéos main sur manche) est identifiée comme phase R&D séparée, non prioritaire.

**Q7. Garantie biomécanique ?**

Oui, `src/processors/validator.py` applique :
- `validate_chord()` : span fret ≤ `MAX_FRET_SPAN` (5), pas de doigt sur multiple frets (sauf barre INDEX)
- `validate_transition()` : pas de même doigt sur position différente, pas de saut > 5 frets
- `validate_sequence()` : statistiques complètes sur taux de transitions valides

Le chord scraper a été durci (session en cours) avec vérification "same finger, different frets" à l'insertion.

---

## 3. Format technique

**Q8. Format de livraison des échantillons annotés ?**

Le format proposé par FretWise est **accepté avec extensions**. Voici le format aligné :

```json
{
  "source_file": "path/to/song.gp5",
  "source_hash": "sha1:abc123...",
  "fretwise_commit": "2480d8e",
  "dataset_version": "v0.1",
  "annotator": "uci_chords|jguitar|mutopia|caged|fretwise_viterbi",
  "notes": [
    {
      "note_id": 0,
      "onset": 0.0,
      "duration": 0.5,
      "pitch": 64,
      "string_num": 1,
      "fret": 0,
      "finger": "open",
      "hand_position": null,
      "confidence": 1.0,
      "techniques": ["hammer_on"],
      "annotator": "mutopia"
    }
  ]
}
```

Différences par rapport à la proposition FretWise :
- `source_hash` : on utilise SHA1 (cohérent avec le harvester), pas SHA256
- `hand_position` : `null` pour les sources qui ne l'annotent pas (accords, CAGED). FretWise peut le calculer.
- `techniques` : liste (plusieurs techniques possibles par note), aligné avec le champ `articulation` de NoteEvent
- `confidence` : 1.0 pour les sources humaines, <1.0 pour le synthétique

**Format bulk** : JSONL préféré (un record par ligne). Parquet disponible pour gros volumes. Le pipeline `scripts/harvest.py` produit les deux.

**Q9. Comment associer un échantillon annoté à un NoteEvent FretWise ?**

- **Pour les fichiers GP** : par `(onset, pitch, string_num, fret)` — les deux projets parsent le même GPIF avec la même logique (même lignée de code).
- **Pour les accords** : pas de NoteEvent à proprement parler (pas de timeline). Livraison comme chord diagrams avec doigté complet.
- **Fallback** : par `note_id` séquentiel si le même parseur est utilisé des deux côtés.

**Proposition** : FretWise fournit un script `parse_and_id.py` qui assigne des `note_id` stables à un fichier. GuitarDataSet aligne ses annotations sur ces IDs. Ou on utilise le tuple `(onset, pitch)` comme clé naturelle.

**Q10. Aurons-nous les fichiers source ?**

Oui. Les fichiers GP sont sur la même machine (`bulk data/guitarpro/`, 1519 fichiers). Les MusicXML Mutopia seront téléchargés localement. FretWise peut tourner sur n'importe lequel et comparer.

**Q11. Granularité temporelle pour onset ?**

Beats (quarter-note = 1.0). Même convention que FretWise. Le `tempo` est séparé dans les métadonnées du record.

---

## 4. API et intégration

**Q12. Comment voyez-vous l'intégration runtime ?**

- [x] Dataset livré one-shot, FretWise consomme offline — **phase 1-2**
- [x] Modèle exporté (PyTorch / ONNX) que FretWise charge en process — **phase 3**
- [ ] Service / API — pas nécessaire (même machine)
- [ ] Pip package — possible plus tard

Phase 1 : JSONL de ground truth → script d'évaluation.
Phase 3 : le neural cost sera un module PyTorch exportable en ONNX, appelable dans `scoring/` via un wrapper.

**Q13. Volume de données prévu in fine ?**

- **Court terme** : ~10³ morceaux annotés (accords + classique + CAGED)
- **Moyen terme** : ~10⁴ (DadaGP + silver-standard Viterbi)
- **Long terme** : ~10⁵ si silver-standard massif validé

Pour un gradient boosting finger classifier : 10³-10⁴ suffisent.
Pour un neural cost : 10⁴ minimum, 10⁵ idéal.

**Q14. Accès aux 1500 fichiers `partitions/` ?**

Oui — même utilisateur, même machine. Le corpus `partitions/` de FretWise et le corpus `bulk data/guitarpro/` de GuitarDataSet sont tous deux accessibles. On peut créer un golden set commun issu des deux.

---

## 5. Coordination / gouvernance

**Q15. Cadence de sync souhaitée ?**

Les deux projets sont pilotés par le même utilisateur via des sessions Claude distinctes. La synchronisation se fait via :
- Ce fichier `ANSWERS_TO_FRETWISE.md` (mis à jour à chaque changement)
- Le répertoire `docs/handoff/` de FretWise (copié ici dans `docs/`)
- Les mémoires projet persistantes de chaque session Claude

Sync : à chaque session de travail significative. Pas de sprint formel — le rythme est celui de l'utilisateur.

**Q16. Qui modifie quoi ?**

Même utilisateur → pas de conflit de gouvernance. En pratique :
- GuitarDataSet produit le dataset et le modèle
- FretWise intègre le modèle (PR sur FretWise)
- Les deux Claude instances peuvent proposer du code des deux côtés

**Q17. Versioning du dataset ?**

Accepté. Convention : `dataset-v{VERSION}-fretwise@{COMMIT}`.
Exemple : `dataset-v0.1-fretwise@2480d8e`.

**Q18. Golden set de 10-20 morceaux ?**

Oui. Proposition :
- 5 morceaux du corpus `partitions/` (rock/pop)
- 5 pièces Mutopia (classique)
- 5 accords complexes (barre, jazz voicings)
- 5 patterns CAGED comme sanity check

À constituer dès que les premières annotations sont prêtes.

---

## 6. Au sujet du guitar-fingerings-harvester

**Q19. Pipeline exact du harvester ?**

Le harvester a été **absorbé dans GuitarDataSet** (session 2026-05-17). Ce n'est plus un projet séparé. Pipeline :

```
[Fichiers source] → Parseurs (GP/MusicXML/MIDI/ASCII/ChordDB)
                          │
                          ▼
                  [Unified JSON Schema]
                          │
                   ┌──────┼──────┐
                   ▼      ▼      ▼
              [JSONL] [Parquet] [DadaGP tokens]
                   │
                   ▼
           [FingeredNote / NoteSequence]  ← converter
                   │
                   ▼
           [FretWise NoteEvent]  ← exporter
```

Pas de composant vidéo/audio. Pas de MediaPipe. C'est un pipeline de parsing de fichiers de notation.

**Q20. Limite de production actuelle ?**

- Parsing GP : ~1500 fichiers / 75 secondes (5.5M notes)
- Pas de limite réseau (tout est local)
- Le bottleneck sera l'annotation, pas le parsing

**Q21. Filtrage qualité ?**

- Track filtering : MIDI program 24-31 guitare, exclusion basse/drums/percussion
- Validation biomécanique post-parsing (`validator.py`)
- Pas de tri vidéo (pas de vidéo dans le pipeline)

**Q22. Humain dans la boucle ?**

L'utilisateur valide les résultats et décide des sources. Le pipeline est automatique mais pas autonome.

---

## 7. Bonus

**Q23. Au-delà du doigté, qu'est-ce que GuitarDataSet pourrait extraire ?**

Oui, plusieurs choses sont extractibles :
- **Position de la main** : via `segment_into_positions()` de FretWise sur les NoteEvents
- **Style** : classifiable depuis les métadonnées + distribution de techniques
- **Niveau de difficulté** : estimable via metrics (span moyen, vitesse, techniques)
- **Profil joueur** : pas encore, mais un jour via clustering de choix de doigté

**Q24. Patterns d'échec systématiques de FretWise ?**

**Premiers résultats (baseline chord dataset, 558 voicings, 2445 notes annotées) :**

| Mode | Finger Accuracy | Position Exact |
|------|----------------|----------------|
| Finger-only (string/fret hints) | **77.3%** | 77.3% |
| Full Viterbi (no hints) | **29.9%** | 18.3% |

Erreurs systématiques identifiées via matrice de confusion (mode finger-only) :
- **MIDDLE/RING confusion** : 240 erreurs (105 RING->MIDDLE + 135 MIDDLE->RING) — le pattern dominant
- **PINKY/RING confusion** : 145 erreurs (106 RING->PINKY + 39 PINKY->RING)
- **INDEX** : bien classifié (1053/1127 = 93.4%) — le doigt le plus fiable
- **MIDDLE/PINKY** sont les plus faibles (~57% et ~74% individuellement)

En mode full Viterbi (sans hints), FretWise choisit souvent des positions string/fret differentes du ground truth, ce qui est attendu pour des voicings d'accords (multiple positions possibles pour un meme pitch).

Hypotheses non encore testees (necessite donnees sequentielles) :
- Transitions entre positions eloignees (>5 frets)
- Barres partiels vs full barres
- Contexte musical (phrase legato vs detache) mal capte par les poids fixes

Le crash `resolve_chord_partial_barre` (~1.8% du corpus) est noté.

---

## Actions immédiates côté GuitarDataSet

1. **Écrire un loader FretWise** : script qui prend un fichier GP, le fait tourner dans FretWise, et compare le résultat aux annotations ground truth
2. **Finaliser l'acquisition UCI Guitar Chords** (2 633 accords)
3. **Lancer le téléchargement Mutopia** (395 pièces classiques)
4. **Générer un premier lot silver-standard** : faire tourner FretWise sur 100 fichiers du corpus bulk, sauvegarder les résultats comme données d'entraînement
5. **Constituer le golden set** de 20 morceaux pour tests d'intégration partagés
