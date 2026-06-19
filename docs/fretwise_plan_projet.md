# FRETWISE — Plan projet

> Du MVP à la solution complète · Architecture incrémentale et jalons de livraison · Version 1.0 — Mars 2026

## 1. Principes directeurs
### 1.1 Philosophie incrémentale
Le projet suit une logique de construction par couches où chaque phase produit un livrable fonctionnel et autonome. Le MVP (phase 1) pose l’architecture centrale — le pipeline complet de la partition au doigté — même si chaque module est dans sa version la plus simple. Les phases suivantes enrichissent les modules un par un sans jamais remettre en cause l’architecture.
### 1.2 Règle d’or architecturale
Le système est conçu autour d’un contrat d’interface stable entre les six modules (M1 Parser, M2 Générateur, M3 Patterns, M4 Scoring, M5 Optimiseur, M6 Profil). Chaque module peut évoluer indépendamment tant qu’il respecte son contrat d’entrée/sortie. La fonction de coût est injectée dans l’optimiseur, jamais codée en dur : on peut passer d’une fonction manuelle à une fonction apprise sans toucher à Viterbi.
### 1.3 Stack technique retenue
- Python 3.11+ comme langage principal (NumPy, PyGuitarPro, music21, mirdata)
- Structure de projet : monorepo avec un package par module (fretwise.parser, fretwise.generator, fretwise.patterns, fretwise.scoring, fretwise.optimizer, fretwise.profile)
- Tests : pytest avec fixtures par format de partition. Couverture cible 80%+
- Stockage profil joueur : JSON versionné (phase 1-2), SQLite (phase 3+)
- Interface : CLI d’abord (phase 1-2), web React (phase 3+)
- CI/CD : GitHub Actions, lint (ruff), type checking (mypy)

## 2. Vue d’ensemble des phases
| Phase | Nom | Objectif clé | Durée estimée | Dépendances |
| --- | --- | --- | --- | --- |
| Phase 1 | MVP — Le pipeline complet | Prouver le concept de bout en bout | 4-6 semaines | Aucune |
| Phase 2 | Enrichissement — Musique et patterns | Qualité musicale des doigtés | 4-6 semaines | Phase 1 |
| Phase 3 | Personnalisation — Profil joueur | Adaptation individuelle | 6-8 semaines | Phase 2 |
| Phase 4 | Intelligence — IA et évolution | Apprentissage et progression | 8-12 semaines | Phase 3 |

Durée totale estimée : 22 à 32 semaines pour un développeur à temps partiel. Le MVP est utilisable dès la fin de la phase 1 ; chaque phase suivante améliore la qualité des résultats sans changer l’usage.

## 3. Phase 1 — MVP : le pipeline complet
L’objectif de la phase 1 est de faire fonctionner le pipeline de bout en bout : une partition GuitarPro entre, une séquence de doigtés sort. Chaque module est dans sa version minimale mais l’architecture complète est posée.
### 3.1 Sprint 1 : Fondations (semaines 1-2)
Objectif : Structures de données, parser GP, générateur d’états.
#### Tâches
- Setup projet : monorepo Python, pyproject.toml, pytest, ruff, structure de packages, CI GitHub Actions.
- Modèle de données : implémenter les dataclasses NoteEvent, FingeringState, FingeringResult. Typage strict avec mypy.
- Parser GP (M1) : adaptateur PyGuitarPro qui lit un fichier .gp5 et produit une liste ordonnée de NoteEvents. Extraire pitch, corde, fret, durée, tempo, articulations de base (hammer, pull-off, slide).
- Générateur d’états (M2) : pour chaque NoteEvent, calculer toutes les positions possibles (corde, fret) sur un manche standard 22 frets, accordage EADGBE. Filtrer les positions physiquement impossibles.
- Tests : 5-10 fichiers GP de test (morceaux simples connus). Vérifier que le parser produit les bonnes notes et que le générateur couvre bien toutes les positions valides.
Livrable S1 : fretwise parse song.gp5 affiche la séquence de notes avec leurs états possibles.

### 3.2 Sprint 2 : Scoring et Viterbi (semaines 3-4)
Objectif : Fonction de coût mécanique + algorithme d’optimisation.
#### Tâches
- Fonction de coût mécanique (M4 v0) : implémenter C_méca avec quatre composantes : coût de shift de position (proportionnel à la distance, pondré par le tempo), coût d’étirement (distance doigt-position), coût de changement de corde (proportionnel au saut), coût intrinsèque du doigt (index < majeur < annulaire < auriculaire).
- Inférence de doigt : quand le doigt n’est pas explicite dans la partition, le déduire de la position : si la fret est F et la position du poignet est P, le doigt est déterminé par F-P+1 (index=1, majeur=2, annulaire=3, auriculaire=4). Gérer les cas limites (corde à vide, étirement).
- Optimiseur Viterbi (M5) : implémenter l’algorithme de programmation dynamique. Entrée : graphe d’états + fonction de coût. Sortie : chemin optimal (séquence de FingeringState).
- Module patterns vide (M3 stub) : interface définie mais retourne zéro contrainte. Prêt à recevoir les patterns en phase 2.
- Module profil par défaut (M6 stub) : profil « guitariste moyen » avec des paramètres fixes. Prêt à être personnalisé en phase 3.
- Tests : sur 5 morceaux simples, vérifier manuellement que les doigtés produits sont raisonnables. Mesurer le temps de calcul.
Livrable S2 : fretwise solve song.gp5 produit une tablature annotée avec les doigtés optimisés. Output JSON + affichage texte.

### 3.3 Sprint 3 : Intégration et sortie (semaines 5-6)
Objectif : CLI complète, format de sortie exploitable, premiers benchmarks.
#### Tâches
- CLI complète : commandes parse, solve, export. Options : format d’entrée, mode (référence/performance), verbosité.
- Export : générer un fichier GP annoté avec les doigtés calculés (en remplissant leftHandFinger dans PyGuitarPro). Export JSON avec la séquence complète.
- Benchmark initial : exécuter le système sur 10-20 morceaux de difficulté variée. Documenter les cas où le résultat est bon/mauvais. Identifier les faiblesses de la fonction de coût.
- Documentation : README, guide d’installation, exemples d’utilisation.
Livrable phase 1 : outil CLI fonctionnel qui prend un fichier GuitarPro et produit des doigtés optimisés. Architecture modulaire complète avec interfaces stables.
#### 3.4 Critères de succès phase 1
- Le pipeline fonctionne de bout en bout sans erreur sur 20 morceaux de test.
- Les doigtés produits sont « raisonnables » : pas de shift impossible, pas d’étirement surhumain, pas de saut de 5 cordes en double croche.
- Temps de calcul < 1 seconde pour un morceau de 3 minutes.
- Le code est couvert à 80%+ par les tests unitaires.

## 4. Phase 2 — Enrichissement : musique et patterns
La phase 2 améliore la qualité des doigtés en ajoutant la dimension musicale et les patterns idiomatiques. L’architecture ne change pas ; seuls M3 et M4 évoluent.
### 4.1 Sprint 4 : Fonction de coût musicale (semaines 7-8)
- C_music v1 : implémenter les bonus/malus musicaux. Bonus pour rester sur la même corde dans une phrase mélodique (homogénéité de timbre). Bonus pour un doigté rendant possible un slide, hammer-on, pull-off demandé par la partition. Pénalité pour un doigté rendant impossible une articulation annotée.
- Parser MusicXML (M1 v2) : ajouter l’adaptateur music21 pour les fichiers MusicXML. Extraire les doigtés annotés (balise <fingering>) comme contraintes supplémentaires.
- Télécharger GuitarSet : intégrer via mirdata. Extraire les positions corde/fret comme référence de validation.
### 4.2 Sprint 5 : Base de patterns (semaines 9-10)
- Patterns d’accords (M3 v1) : encoder ~200 formes d’accords en YAML avec doigtés standards. Accords ouverts (C, D, E, G, A, Am, Em, Dm), barrés (formes E et A transposées), 7èmes, sus.
- Patterns de gammes : gammes pentatoniques dans les 5 positions, gammes majeures et mineures dans les positions CAGED. Doigtés standards.
- Reconnaissance de patterns : algorithme de matching qui identifie dans la séquence de notes les sous-séquences correspondant à des patterns connus. Les états correspondants sont contraints, réduisant l’espace de recherche.
### 4.3 Sprint 6 : Validation (semaines 11-12)
- Demander accès DadaGP : contacter Pedro Sarmento. Intégrer le pipeline d’extraction des positions corde/fret sur un sous-ensemble de 1 000 morceaux.
- Contacter Iino et al. : obtenir le dataset de 40 études annotées. L’utiliser comme benchmark principal.
- Benchmark de concordance : exécuter FretWise sur les études annotées. Mesurer le taux de concordance position (corde+fret) et la qualité subjective sur 5-10 morceaux de styles différents.
- Ajustement des poids : itérer sur les coefficients de la fonction de coût (α, β) en s’appuyant sur les résultats de benchmark. Objectif : >60% concordance position avec les doigtés de référence.
Livrable phase 2 : doigtés tenant compte des articulations musicales et des patterns idiomatiques. Support MusicXML. Benchmark de concordance documenté.
#### 4.4 Critères de succès phase 2
- Concordance position > 60% sur le benchmark Iino et al.
- Les articulations annotées (slide, hammer-on) sont respectées dans >90% des cas.
- Les accords standards sont reconnus et leurs doigtés appliqués automatiquement.

## 5. Phase 3 — Personnalisation : profil joueur
La phase 3 introduit l’adaptation au joueur individuel. Les modules M4 et M6 évoluent, et l’interface web apparaît.
### 5.1 Sprint 7 : Protocole de calibration (semaines 13-15)
- Modèle PlayerProfile : implémenter la structure complète avec paramètres morphologiques (étirement par position), dextérité (BPM limite par type de transition), et préférences.
- Exercices de calibration : générer 5 exercices structurés (gamme chromatique, indépendance, shifts, cordes croisées, barrés). Exporter en format GP jouable.
- Formulaire de saisie : interface web minimale (React) pour la saisie des résultats de calibration. Le joueur entre ses BPM limites par exercice.
- C_joueur v1 : intégrer le profil joueur dans la fonction de coût. Pénalité exponentielle au-delà des seuils calibrés.
### 5.2 Sprint 8 : Interface web (semaines 16-18)
- Visualisation du manche : composant React affichant le manche de guitare avec les doigtés proposés, note par note ou mesure par mesure. Code couleur par doigt.
- Upload et solve : upload de fichier GP via l’interface, lancement du calcul côté serveur (API FastAPI), affichage des résultats.
- Modes de calcul : sélection du mode (Référence / Performance / Apprentissage) avec ajustement automatique des pondérations α, β, γ, δ.
- Export enrichi : export GP annoté, export PDF tablature, export JSON.
### 5.3 Sprint 9 : Modes et validation utilisateur (semaines 19-20)
- Mode performance : γ dominant. Optimise pour la faisabilité au niveau actuel du joueur.
- Mode apprentissage : C_péda activé. Identifie les transitions dans la zone proximale et les intègre comme défis ciblés.
- Tests utilisateurs : recruter 3-5 guitaristes de niveaux différents. Leur faire calibrer leur profil, générer des doigtés pour 3 morceaux chacun, recueillir le feedback qualitatif.
Livrable phase 3 : application web avec profil joueur calibré, trois modes de calcul, visualisation du manche. Feedback utilisateur intégré.
#### 5.4 Critères de succès phase 3
- Les doigtés en mode performance sont jugés « jouables » par 80%+ des testeurs pour leur niveau.
- Les doigtés en mode apprentissage contiennent 2-4 transitions « challenging but doable » par morceau.
- Le profil joueur capture une différence mesurable entre un débutant et un intermédiaire.

## 6. Phase 4 — Intelligence : IA et évolution
La phase 4 introduit l’apprentissage automatique pour remplacer ou enrichir la fonction de coût manuelle, et le suivi de progression du joueur.
### 6.1 Sprint 10 : Apprentissage de la fonction de coût (semaines 21-24)
- Préparation des données : extraire de DadaGP complet (26 000 morceaux) les paires (contexte, choix de position). Aligner avec les doigtés Iino et al. et ClassClef.
- Modèle de scoring appris : entraîner un réseau de neurones (LSTM ou Transformer léger) qui prend en entrée le contexte (N notes précédentes + note courante + N notes suivantes) et prédit un score de qualité pour chaque état possible.
- Hybridation : utiliser le modèle appris comme composante de la fonction de coût injectée dans Viterbi. La garantie d’optimalité de la programmation dynamique est conservée.
- Benchmark : comparer la concordance du système hybride vs la fonction manuelle sur le benchmark Iino. Cible : >80%.
### 6.2 Sprint 11 : Évolution temporelle (semaines 25-28)
- Re-calibration périodique : rappeler au joueur de re-calibrer toutes les 4-6 semaines. Comparer les snapshots et calculer la progression par compétence.
- Ajustement automatique des doigtés : quand le profil évolue, les doigtés pour les morceaux déjà analysés sont recalculés. Le joueur voit l’évolution : « ce passage qui était simplifié en mode performance peut maintenant être joué en version musicalement optimale. »
- Dashboard de progression : visualisation des compétences dans le temps : étirement, vitesse de shift, indépendance des doigts. Identification des axes d’amélioration.
### 6.3 Sprint 12 : Apprentissage passif et patterns émergents (semaines 29-32)
- RLHF doigtés : collecter les modifications apportées par le joueur aux doigtés proposés. Ajuster les poids de la fonction de coût en conséquence. Le système apprend les préférences individuelles.
- Extraction de patterns DadaGP : analyse n-gram sur le corpus complet pour découvrir les patterns idiomatiques par genre. Enrichissement automatique de la base M3.
- Analyse audio avancée (exploratoire) : si un modèle de transcription audio vers tablature est intégré (TabCNN / GAPS), la calibration peut devenir automatique : le joueur joue, le système analyse.
Livrable phase 4 : fonction de coût hybride (manuelle + apprise), suivi de progression, apprentissage des préférences, patterns enrichis automatiquement.
#### 6.4 Critères de succès phase 4
- Concordance > 80% sur le benchmark Iino et al. avec la fonction de coût hybride.
- Le système propose des doigtés différents pour un même morceau quand le profil du joueur a évolué.
- Après 20+ corrections utilisateur, les propositions suivantes intègrent les préférences observées.

## 7. Architecture évolutive : ce qui reste stable
Le tableau suivant montre comment chaque module évolue entre les phases tout en maintenant des interfaces stables.
| Module | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
| --- | --- | --- | --- | --- |
| M1 Parser | GP uniquement | + MusicXML | Stable | + MIDI audio (exploratoire) |
| M2 Générateur | Toutes positions, accordage standard | Stable | + accordages alternatifs | Stable |
| M3 Patterns | Stub (aucune contrainte) | Accords + gammes (200+ patterns) | Stable | + patterns extraits de DadaGP |
| M4 Scoring | C_méca seul | + C_music | + C_joueur + C_péda | + composante IA apprise |
| M5 Optimiseur | Viterbi standard | Stable | Stable | Stable (la fonction de coût change, pas Viterbi) |
| M6 Profil | Profil fixe « moyen » | Stable | Calibration + évolution | + RLHF + progression |
| Interface | CLI | CLI enrichie | Web (React + FastAPI) | + dashboard progression |

Le module M5 (Viterbi) est le seul qui ne change jamais. C’est le point de stabilité de l’architecture : tout le reste peut évoluer autour de lui.

## 8. Gestion des risques projet
| Risque | Impact | Probabilité | Mitigation |
| --- | --- | --- | --- |
| Accès DadaGP refusé ou retardé | Élevé | Faible (dataset académique ouvert) | Contacter les auteurs dès la phase 1. Alternative : scraper des tablatures libres ou utiliser ClassClef seul |
| Fonction de coût mal calibrée | Moyen | Moyenne | Itération rapide grâce au benchmark Iino. Les poids sont des paramètres, pas du code |
| PyGuitarPro ne supporte pas un fichier GP | Faible | Moyenne (GP6/7 non supportés) | Convertir les fichiers problématiques via MuseScore en MusicXML avant parsing |
| Temps de calcul trop long pour polyphonie | Faible | Faible (Viterbi est O(N×S²)) | Pour la polyphonie, décomposer en voix séparées + contrainte de compatibilité |
| Peu de testeurs disponibles en phase 3 | Moyen | Moyenne | Auto-test intensif. Forums de guitaristes. Discord de développeurs musicaux |
| Modèle IA insuffisant en phase 4 | Faible | Moyenne | La fonction de coût manuelle reste le fallback. L’IA est additive, pas remplaçante |

## 9. Métriques de suivi
| Métrique | Phase 1 | Phase 2 | Phase 3 | Phase 4 |
| --- | --- | --- | --- | --- |
| Concordance position (Iino) | N/A | > 60% | > 70% | > 80% |
| Respect des articulations | N/A | > 90% | > 90% | > 95% |
| Temps de calcul (3 min à 120 BPM) | < 1 sec | < 1 sec | < 2 sec | < 5 sec |
| Couverture de tests | > 80% | > 80% | > 75% | > 75% |
| Formats d’entrée supportés | GP3/4/5 | + MusicXML | Stable | + MIDI |
| Nombre de patterns | 0 | > 200 | > 200 | > 1 000 |
| Satisfaction testeurs (qualitative) | N/A | N/A | > 3.5/5 | > 4/5 |

## 10. Synthèse et prochaines étapes
Le plan projet FretWise est conçu pour produire un outil utilisable dès 4-6 semaines (phase 1, MVP) tout en posant une architecture capable d’absorber des enrichissements majeurs sans refactoring. La clé est le découplage entre l’algorithme d’optimisation (Viterbi, stable) et la fonction de coût (qui évolue de manuelle simple à hybride IA).
Les prochaines actions immédiates sont les suivantes :
- Démarrer : setup du projet Python, structures de données, premiers tests avec un fichier GP simple.
- Contacter : Pedro Sarmento (DadaGP) et Nami Iino (benchmark fingering) pour l’accès aux datasets.
- Coder : le parser GP et le générateur d’états en premier — c’est la fondation sur laquelle tout le reste repose.
Chaque phase se termine par un livrable fonctionnel qui peut être utilisé, testé et validé indépendamment, garantissant que le projet avance de manière visible et mesurable.
