# Questions de FretWise à l'équipe ML / GuitarDataSet

> **À répondre** par l'équipe ML. Les réponses définissent les contrats de
> données et le périmètre du travail commun.

---

## 1. Périmètre et timeline

1. **Quel est le but du dataset ?**
   - [ ] Évaluer FretWise vs ground truth (mesure qualité)
   - [ ] Entraîner un classifieur finger-only (string+fret donnés, prédire finger)
   - [ ] Entraîner une fonction de coût globale C_méca apprise
   - [ ] Entraîner un modèle position-aware (segmentation + finger)
   - [ ] Autre — préciser

2. **Quand le premier échantillon utilisable sera-t-il disponible ?**
   Format préféré : date approximative + volume attendu (nombre de morceaux,
   nombre de notes annotées).

3. **Quelle est la couverture stylistique cible ?**
   Rock / blues / jazz / classique / fingerstyle / autre. FretWise est
   testé surtout rock / pop / blues / folk via le corpus `partitions/`.

---

## 2. Sources et annotation

4. **D'où viennent les annotations de doigts ?**
   - [ ] Iino 2025 (40 études classiques, doigt complet)
   - [ ] Vidéos YouTube via `guitar-fingerings-harvester` + MediaPipe Hands
   - [ ] Annotation manuelle
   - [ ] GAPS / GuitarSet / DadaGP avec doigts inférés
   - [ ] Plusieurs sources fusionnées
   - [ ] Autre

5. **Quelle est la qualité estimée des annotations ?**
   Taux d'erreur sur les doigts, méthodologie de contrôle qualité,
   inter-annotator agreement si applicable.

6. **Pour les annotations issues de vidéos (MediaPipe) :** quelle est la
   précision de l'alignement audio↔video↔tablature ? Avez-vous mesuré la
   fiabilité du finger-classification sur des cas de référence ?

7. **Y a-t-il une garantie que les doigts annotés correspondent à des
   choix biomécaniquement plausibles ?**
   Notre algo produit parfois des doigtés impossibles (étirements >
   4 frets, croisements). Si les annotations sont aussi bruitées, il
   faudra un filtre amont.

---

## 3. Format technique

8. **Sous quel format livreriez-vous chaque échantillon annoté ?**

   Suggestion FretWise (alignée sur notre modèle) :
   ```json
   {
     "source_file": "path/to/song.gp5",
     "source_hash": "sha256:...",
     "fretwise_commit": "2480d8e",
     "notes": [
       {
         "note_id": 0,
         "onset": 0.0,
         "duration": 0.5,
         "pitch": 64,
         "string_num": 1,
         "fret": 0,
         "finger": "open",
         "hand_position": 1,
         "confidence": 0.95,
         "annotator": "iino2025|harvester-mediapipe|manual"
       },
       ...
     ]
   }
   ```
   Acceptez-vous ce format ? Préférez-vous Parquet / CSV / autre ?

9. **Comment associer un échantillon annoté à un `NoteEvent` FretWise ?**
   - Par `(onset, string_num, fret)` ?
   - Par `note_id` après parsing FretWise ?
   - Par alignement audio si pas de source MIDI/GP ?

10. **Aurons-nous les fichiers source (.gp / .mid / .musicxml) ou
    seulement le ground truth ?**
    Si on a la source, FretWise peut tourner et on compare. Si on a
    seulement le ground truth, il faut une représentation séparée des
    NoteEvents.

11. **Quelle granularité temporelle pour `onset` ?** Beats ou secondes ?
    FretWise utilise des beats avec `tempo` séparé. Un ground truth
    purement audio (secondes) demandera un mapping.

---

## 4. API et intégration

12. **Comment voyez-vous l'intégration runtime ?**
    - [ ] Dataset livré one-shot, FretWise consomme offline
    - [ ] Service / API que FretWise peut appeler en live
    - [ ] Modèle exporté (PyTorch / ONNX) que FretWise charge en process
    - [ ] Pip package installable

13. **Quel volume de données prévoyez-vous in fine ?**
    De l'ordre de 10³, 10⁴, 10⁵ morceaux annotés ? Cela conditionne le
    type de modèle (gradient boosting léger vs deep learning).

14. **Aurez-vous accès aux mêmes 1500 fichiers `partitions/` que
    FretWise utilise pour ses audits ?**
    Sinon il faudra un protocole pour aligner les corpora — sinon les
    métriques ne sont pas comparables.

---

## 5. Coordination / gouvernance

15. **Cadence de sync souhaitée ?** Weekly ? Sprint ? Par milestone ?

16. **Qui modifie quoi ?** Si l'équipe ML produit un modèle qui remplace
    `cost_position_shift`, est-ce que vous proposez la PR sur FretWise
    ou nous donnez juste le code à intégrer ?

17. **Versioning du dataset.** Acceptez-vous de tagger les releases
    dataset avec le commit FretWise sur lequel elles s'alignent (cf.
    `MODEL_SPEC.md §6`) ?

18. **Tests d'intégration partagés.** Êtes-vous prêts à exposer un
    sous-corpus de 10–20 morceaux annotés comme « golden set » que les
    deux projets utilisent pour mesurer la régression ?

---

## 6. Au sujet du `guitar-fingerings-harvester`

19. **Quel est le pipeline exact du harvester ?**
    Inputs (URL YouTube ?), outputs (annotations JSON ? frames ?),
    dépendances majeures.

20. **Quelle est la limite de production actuelle ?**
    Nombre de morceaux annotés réalistement extractibles par jour de
    compute, taux d'échec par étape (download, hand detection,
    alignement).

21. **Filtrage qualité préalable** : tries-vous les vidéos avant
    extraction (caméra fretboard, éclairage, occultations) ? Sinon, à
    quel niveau les annotations basse-qualité sont-elles écartées ?

22. **Y a-t-il un humain dans la boucle quelque part**, ou est-ce
    100 % automatique ?

---

## 7. Bonus — fishing pour idées

23. **Au-delà du doigté, qu'est-ce que GuitarDataSet pourrait extraire
    qui aiderait FretWise** ?
    - Position de la main dans le temps (segments)
    - Style identifié (rock, blues, jazz, etc.)
    - Niveau de difficulté
    - Préférences du joueur identifié (profil)

24. **Avez-vous déjà identifié des paterns d'échec systématiques de
    FretWise** sur votre dataset ? Si oui, lesquels — ça affinerait
    notre roadmap.

---

**Réponses attendues** : éditer ce fichier en ajoutant les réponses inline
sous chaque question, ou répondre dans un fichier `ANSWERS_FROM_ML.md`
à côté. La forme la moins coûteuse pour vous est la bonne.
