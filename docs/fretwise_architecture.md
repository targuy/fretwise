# FRETWISE — Architecture fonctionnelle et technique

> Guitar Fingering Optimization System · Document de conception · Version 1.0 — Mars 2026

## 1. Vision et périmètre
### 1.1 Problème
Déterminer les doigtés optimaux à la guitare est un problème d’optimisation multidimensionnel. Pour chaque note d’une partition, le guitariste doit choisir une position (corde + fret) et un doigt (index, majeur, annulaire, auriculaire). Ce choix dépend du contexte immédiat (notes précédentes et suivantes), des contraintes ergonomiques (morphologie de la main, étirement, tempo), des intentions musicales (timbre, expressivité) et du niveau technique du joueur.
### 1.2 Solution proposée : FretWise
FretWise est un système qui calcule et propose des doigtés optimisés en combinant quatre couches de décision, calibrées sur le profil individuel du guitariste et évoluant dans le temps avec sa progression.
### 1.3 Analogie stratégique
Comme un moteur d’échecs moderne, FretWise combine trois approches complémentaires :
- Base de connaissances : patterns pré-optimisés (accords, gammes, arpèges) comme les ouvertures aux échecs.
- Scoring heuristique : fonction de coût multi-critères comme l’évaluation positionnelle.
- Calcul optimal : programmation dynamique (Viterbi) comme la recherche arborescente.

## 2. Architecture fonctionnelle
Le système s’organise en six modules fonctionnels qui interagissent selon un flux de données linéaire avec des boucles de rétroaction.
| Module | Fonction | Entrées / Sorties |
| --- | --- | --- |
| M1 — Parser | Lecture et normalisation de la partition | MusicXML, Guitar Pro, MIDI → Séquence de NoteEvents |
| M2 — Générateur | Calcul des états possibles pour chaque note | NoteEvent → Liste d’états (corde, fret, doigt, position) |
| M3 — Patterns | Reconnaissance et application de patterns connus | Séquence → Segments contraints + segments libres |
| M4 — Scoring | Calcul du coût de transition entre états | Profil joueur + 2 états → Coût composite |
| M5 — Optimiseur | Recherche du chemin optimal (Viterbi) | Graphe d’états + coûts → Séquence optimale |
| M6 — Profil | Gestion du profil joueur et évolution temporelle | Calibration + historique → Paramètres personnalisés |

### 2.1 Flux de données principal
Le flux principal suit un pipeline linéaire en cinq étapes :
- Ingestion : M1 parse la partition et produit une séquence ordonnée de NoteEvents (hauteur, durée, position temporelle, articulations).
- Expansion : M2 génère pour chaque NoteEvent l’ensemble des états possibles en tenant compte de l’accordage et de la tessiture de l’instrument.
- Filtrage : M3 identifie les patterns connus (accords, gammes, séquences idiomatiques) et contraint les états correspondants, réduisant l’espace de recherche.
- Scoring : M4 calcule la matrice de coûts de transition entre chaque paire d’états consécutifs, paramétrée par le profil joueur fourni par M6.
- Optimisation : M5 exécute Viterbi sur le graphe complet et extrait la séquence de doigtés de coût minimal.

## 3. Modèle de données
### 3.1 NoteEvent
Unité atomique produite par le parser. Représente une note à jouer dans son contexte temporel et musical.
| Champ | Type | Description |
| --- | --- | --- |
| pitch | int (MIDI) | Hauteur de la note (0–127) |
| onset | float | Position temporelle en beats depuis le début |
| duration | float | Durée en beats |
| tempo | float | BPM local (peut varier au cours du morceau) |
| articulation | enum | normal, legato, staccato, slide, hammer_on, pull_off, bend, vibrato |
| dynamic | enum | pp, p, mp, mf, f, ff (influence le contrôle requis) |

### 3.2 FingeringState
Un état représente un choix complet pour jouer une note donnée.
| Champ | Type | Description |
| --- | --- | --- |
| string_num | int (1–6) | Corde utilisée |
| fret | int (0–24) | Fret appuyée (0 = corde à vide) |
| finger | enum | open, index, middle, ring, pinky |
| hand_position | int | Fret couverte par l’index (définit la position du poignet) |

### 3.3 PlayerProfile
Le profil joueur contient les paramètres de calibration individuels, organisés en trois catégories.
#### 3.3.1 Paramètres morphologiques
- Matrice d’étirement maximal par position sur le manche (l’écart confortable entre index et auriculaire varie selon que l’on joue en position 1 ou en position 9).
- Accessibilité par doigt et par corde (coût de l’auriculaire sur la 6ème corde en position basse, etc.).
- Angle de confort du poignet selon la position sur le manche.
#### 3.3.2 Paramètres de dextérité
- Vitesse maximale par type de transition (shift de position, changement de corde, changement de doigt) mesurée en BPM.
- Taux d’erreur par type de mouvement (donnée statistique issue de la calibration).
- Seuils de faisabilité : la transition est-elle impossible, difficile, ou confortable au tempo du morceau ?
#### 3.3.3 Paramètres d’évolution
- Historique des calibrations avec horodatage.
- Courbe de progression par type de compétence.
- Zone proximale de développement : transitions à la frontière entre « difficile » et « impossible », candidates à l’apprentissage ciblé.

## 4. Fonction de coût composite
Le cœur du système est la fonction de coût qui évalue chaque transition entre deux états consécutifs. Elle combine quatre dimensions pondérées.
C(s₁, s₂) = α·C_méca(s₁, s₂) + β·C_music(s₁, s₂) + γ·C_joueur(s₁, s₂) + δ·C_péda(s₁, s₂)
### 4.1 C_méca — Coût mécanique
Mesure la difficulté physique pure de la transition, indépendamment du joueur.
| Composante | Description |
| --- | --- |
| Shift de position | Coût proportionnel au nombre de frets de déplacement du poignet, pondré par le tempo local. Un shift de 3 frets en double croche à 120 BPM coûte beaucoup plus qu’en noire. |
| Étirement | Pénalité croissante avec l’écart entre le doigt utilisé et la position du poignet, ajustée par la position sur le manche (frets plus rapprochées en haut). |
| Changement de corde | Coût proportionnel au nombre de cordes sautées. Cordes adjacentes = faible coût. Saut de 4 cordes = coût élevé. |
| Difficulté du doigt | Coût intrinsèque par doigt : index < majeur < annulaire < auriculaire, modulé par la corde et la position. |
| Barré | Surcoût pour la mise en place ou le maintien d’un barré, et bonus si un barré déjà en place couvre la note suivante. |

### 4.2 C_music — Coût/bonus musical
Capture les préférences musicales et expressives. Ce coût peut être négatif (bonus) lorsqu’un choix produit un meilleur résultat sonore.
- Homogénéité de timbre : bonus pour rester sur la même corde pendant une phrase mélodique.
- Articulations : bonus pour un doigté qui rend possible un slide, hammer-on, pull-off ou vibrato demandé par la partition. Pénalité si l’articulation devient impossible.
- Legato naturel : bonus pour des transitions qui permettent de lier les notes sans interruption.
- Registre expressif : certaines cordes ont un timbre différent (6ème corde plus chaude, 1ère plus brillante). Selon le style, l’un ou l’autre est préférable.
### 4.3 C_joueur — Coût de faisabilité
Pénalité calibrée sur le profil individuel du joueur. Ce coût transforme les limites mesurées lors de la calibration en contraintes douces.
- Transitions au-delà du seuil : si la vitesse requise dépasse la vitesse maximale mesurée du joueur pour ce type de mouvement, le coût monte exponentiellement.
- Étirement excessif : si l’écart demandé dépasse l’étirement maximal calibré, pénalité très élevée (quasi-interdiction).
- Préférences apprises : bonus ou malus basé sur les habitudes observées du joueur (préférence pour certains doigts, évitement de certaines positions).
### 4.4 C_péda — Coût/bonus pédagogique
Activé uniquement en mode apprentissage. Introduit un bonus négatif pour les transitions dans la zone proximale de développement du joueur.
- Zone cible : transitions légèrement au-dessus du seuil de confort mais en dessous du seuil d’impossibilité.
- Dosage : le système ne propose qu’un nombre limité de défis par morceau pour éviter la surcharge.
- Ciblage : les défis sont choisis dans les compétences les plus proches de la progression (les « low-hanging fruits » de l’amélioration).
### 4.5 Pondération et modes
Les coefficients α, β, γ, δ sont ajustés selon le mode d’utilisation :
| Mode | Priorité | Pondération | Cas d’usage |
| --- | --- | --- | --- |
| Performance | Faisabilité | α=1, β=0.5, γ=2, δ=0 | Concert, enregistrement |
| Musical | Expressivité | α=1, β=2, γ=1, δ=0 | Travail d’interprétation |
| Apprentissage | Progression | α=1, β=0.5, γ=1, δ=1.5 | Travail technique |
| Référence | Optimal pur | α=1, β=1, γ=0, δ=0 | Benchmark, comparaison |

## 5. Module de calibration (M6)
### 5.1 Protocole de calibration initiale
La calibration initiale consiste en une série d’exercices structurés dont les résultats alimentent le profil joueur. Chaque exercice cible une compétence spécifique.
| Exercice | Ce qu’il mesure | Méthode |
| --- | --- | --- |
| Gamme chromatique | Étirement maximal par position sur le manche | Jouer 4 notes chromatiques consécutives, position par position, noter où l’étirement devient inconfortable |
| Indépendance | Vitesse par combinaison de doigts (1-3, 1-4, 2-4…) | Trilles entre deux doigts, augmenter le tempo jusqu’au seuil d’erreur |
| Shifts | Temps de repositionnement par amplitude de shift | Gamme avec shifts obligatoires de 1, 2, 3, 5 frets, mesurer le tempo limite |
| Cordes croisées | Coût des sauts de corde | Arpèges avec sauts de corde croissants, mesurer la propreté à différents tempos |
| Barrés | Capacité de barré et transitions | Enchaînements de barrés à différentes positions, mesurer propreté et fatigue |

### 5.2 Méthode de mesure
Deux approches complémentaires sont possibles pour la mesure :
- Approche simplifiée (MVP) : protocole avec métronome. Le joueur exécute chaque exercice en augmentant progressivement le tempo et rapporte le BPM auquel les erreurs deviennent fréquentes. Saisie manuelle.
- Approche avancée : analyse audio/MIDI en temps réel. Le système détecte automatiquement les notes jouées, mesure le timing, identifie les erreurs (buzz, notes étouffées, timing irrégulier). Calibration automatique.
### 5.3 Évolution temporelle
Le profil joueur n’est pas statique. Le module M6 gère l’historique des calibrations et calcule les tendances de progression. Chaque re-calibration met à jour les seuils, et le système peut détecter les progressions (ou les régressions) pour ajuster les doigtés proposés et les défis pédagogiques.
Le système peut aussi apprendre passivement en observant les doigtés que le joueur choisit spontanément (via une tablature interactive ou un retour MIDI), capturant ainsi des préférences individuelles difficiles à mesurer par des exercices.

## 6. Stratégie de validation
### 6.1 Validation par corpus annoté
Des partitions de guitare classique avec doigtés annotés par des professionnels (Segovia, Carlevaro, éditions Naxos) servent de référence. Le système calcule le taux de concordance entre ses propositions et les doigtés humains.
- Concordance totale : même corde, même fret, même doigt.
- Concordance partielle : même position sur le manche mais doigt différent (souvent acceptable).
- Divergence : position différente. À analyser : est-ce une différence d’intention musicale, de morphologie, ou une erreur du modèle ?
### 6.2 Validation par modèles IA
Des travaux académiques existent sur l’apprentissage automatique des doigtés (modèles séquence-à-séquence, LSTM, Transformer entraînés sur des corpus de tablatures). Ces modèles peuvent servir de seconde référence de validation, et à terme, la fonction de coût elle-même pourrait être apprise plutôt que conçue manuellement.
### 6.3 Score global de qualité
Un score de qualité global est calculé pour chaque solution de doigté proposée, agrégeant le coût total du chemin (somme des coûts de transition), le nombre de shifts de position et leur amplitude, le nombre de transitions dépassant le seuil de confort du joueur, et la concordance avec les patterns idiomatiques reconnus. Ce score permet de comparer différentes solutions (par exemple en faisant varier les pondérations) et de mesurer l’amélioration du système au fil des itérations.

## 7. Architecture technique
### 7.1 Stack technologique
| Composant | Technologie |
| --- | --- |
| Moteur de calcul | Python (NumPy pour les matrices de coût, algorithme de Viterbi optimisé) |
| Parser de partitions | music21 (MusicXML), mido (MIDI), pyguitarpro (Guitar Pro) |
| Profil joueur | JSON/SQLite pour le stockage, versionné par date de calibration |
| Base de patterns | Fichiers YAML décrivant accords, gammes, séquences idiomatiques avec doigtés |
| Interface | CLI pour le MVP, interface web (React) pour la visualisation du manche et des doigtés |
| Validation IA | PyTorch pour les modèles d’apprentissage de la fonction de coût (phase ultérieure) |

### 7.2 Estimation de performance
Pour une chanson de 3 minutes à 120 BPM, voix unique :
- Notes : ~720 (en croches).
- États par note : 10 à 30 (selon la hauteur et l’instrument).
- Transitions évaluées : 30 × 30 × 720 = ~650 000 (borne haute).
- Temps de calcul : < 100 ms sur un ordinateur standard (les opérations sont de simples additions et comparaisons sur des matrices).
Le goulot d’étranglement n’est pas le calcul mais la qualité de la modélisation de la fonction de coût.

## 8. Formats de sortie
Un système d’optimisation de doigtés n’a de valeur que si le guitariste peut exploiter le résultat pour jouer. FretWise produit trois formats de sortie complémentaires, chacun servant un usage différent.
| Format | Description | Usage | Phase |
| --- | --- | --- | --- |
| GuitarPro annoté | Réinjection des doigtés calculés dans le fichier GP source via le champ leftHandFinger de PyGuitarPro (enum Fingering : open, index, middle, annular, little). Le fichier s’ouvre dans Guitar Pro avec les doigtés affichés directement sur la tablature. | Sortie principale. Le guitariste ouvre le fichier et joue. | Phase 1 (MVP) |
| ASCII tablature | Représentation texte classique (6 lignes e/B/G/D/A/E) avec les doigtés annotés au-dessus (1/2/3/4). Affichée directement dans le terminal via la CLI. | Feedback immédiat en ligne de commande pendant le développement. | Phase 1 (MVP) |
| JSON structuré | Format machine contenant toutes les données par note : note_id, string, fret, finger, hand_position, cost, alternatives. Sert de représentation intermédiaire entre Viterbi et les exporteurs. | Interface web future, tests automatisés, pipeline d’apprentissage, API. | Phase 1 (MVP) |

### 8.1 GuitarPro annoté — Sortie principale
Le format GuitarPro supporte nativement le doigté main gauche par note via le champ NoteEffect.leftHandFinger. Les valeurs possibles sont : open (-1), thumb (0), index (1), middle (2), annular (3), little (4). Guitar Pro affiche ces doigtés comme des chiffres au-dessus ou en dessous de la tablature, avec le choix entre notation T1234 (internationale) ou P1234 (française).
PyGuitarPro permet la lecture ET l’écriture de ce champ note par note, ce qui rend possible un round-trip complet : lire un fichier GP, calculer les doigtés, et réécrire le fichier avec les annotations. C’est le canal de sortie le plus naturel car c’est le format que le guitariste utilise déjà pour apprendre.
### 8.2 ASCII tablature enrichie — Sortie CLI
Pour le développement et le feedback rapide, FretWise affiche une tablature ASCII classique dans le terminal avec les doigtés annotés au-dessus de chaque note. Ce format ne nécessite aucun logiciel externe et permet de vérifier visuellement les doigtés proposés pendant le développement.
### 8.3 JSON structuré — Format machine
Le JSON interne sert de représentation pivot entre le moteur Viterbi et les différents exporteurs. Chaque note est décrite par un objet contenant l’identifiant de la note, la corde, la fret, le doigt, la position de la main, le coût calculé et la liste des alternatives classées par coût. Ce format alimente les tests automatisés, la visualisation web future (phase 3) et le pipeline d’apprentissage (phase 4).
### 8.4 Format non retenu : MusicXML
MusicXML supporte la balise <fingering> pour la main gauche et <pluck> pour la main droite, avec une interopérabilité MuseScore, Finale, Dorico et Sibelius. Ce format reste une option future si la demande apparaît, mais n’est pas prioritaire pour le MVP car le rendu du doigté en tablature est moins intégré que dans Guitar Pro.

## 9. Roadmap fonctionnelle
Le développement est envisagé en quatre phases itératives :
| Phase | Livrable | Validation |
| --- | --- | --- |
| Phase 1 | Parser + Générateur + Viterbi avec coût mécanique simple. CLI produisant un doigté pour un fichier MIDI. | Tests unitaires, vérification manuelle sur 5 morceaux simples. |
| Phase 2 | Ajout du coût musical (articulations) + base de patterns (accords majeurs/mineurs, gammes pentatoniques). Calibration manuelle. | Concordance avec doigtés de référence (corpus classique). Cible : >60%. |
| Phase 3 | Profil joueur complet, protocole de calibration, modes (performance/apprentissage). Interface web. | Tests utilisateurs avec 3–5 guitaristes de niveaux différents. Feedback qualitatif. |
| Phase 4 | Apprentissage de la fonction de coût par IA. Apprentissage passif des préférences du joueur. Évolution temporelle. | Comparaison avec modèles IA publiés. Amélioration de la concordance. Cible : >80%. |

## 10. Synthèse
FretWise modélise l’optimisation des doigtés comme un problème de plus court chemin dans un graphe d’états, résolu efficacement par programmation dynamique. Sa valeur ajoutée repose sur trois différenciateurs : une fonction de coût composite à quatre dimensions (mécanique, musicale, faisabilité, pédagogique), une calibration personnalisée sur le profil individuel du guitariste, et un modèle évolutif qui accompagne la progression du joueur dans le temps.
L’architecture est conçue pour être implémentée incrémentalement, avec un MVP fonctionnel dès la phase 1 et des enrichissements progressifs guidés par la validation contre des références humaines et IA.
