# FRETWISE — Acquisition des données externes

> Plan de conception · Datasets, formats, bibliothèques et pipeline d’intégration · Version 1.0 — Mars 2026

## 1. Cartographie des sources de données
FretWise a besoin de trois catégories de données externes : des partitions lisibles par machine (pour alimenter le parser M1), des doigtés annotés par des humains (pour calibrer et valider la fonction de coût), et des données audio alignées (pour la calibration du joueur et l’apprentissage IA à terme). Le paysage des datasets disponibles est riche mais fragmenté ; chaque source couvre un angle différent du problème.
### 1.1 Datasets majeurs identifiés
| Dataset | Volume | Contenu | Doigtés ? | Licence |
| --- | --- | --- | --- | --- |
| DadaGP | 26 181 morceaux, 739 genres | Fichiers GuitarPro tokenisés. Tablatures avec corde/fret, articulations (slide, bend, hammer-on…) | Corde+fret : oui. Doigt main gauche : partiel | Recherche, sur demande |
| GuitarSet | 360 extraits, ~3h, 6 guitaristes | Audio hexaphonique + annotations JAMS : pitch par corde, fret, accords, tempo, style | Corde+fret : oui. Doigt : non | CC BY 4.0 |
| GAPS | 300 pièces, 14h, 200+ interprètes | Guitare classique. Audio + MusicXML + MIDI alignés. Source ClassClef (~5 500 pièces GP/PDF) | Tablature dans GP ClassClef : oui. Doigt explicite : partiel | Recherche, accord QMUL |
| Iino et al. 2025 | 40 études classiques | Dataset annoté pour le fingering classique (Carcassi, Sor). Modèle : 90.3% accuracy doigt | Oui : corde + doigt complet | Académique |
| Guitar-TECHS | ~12 extraits + techniques | Électrique, multi-perspective audio + MIDI, techniques de jeu annotées | Fret/corde via MIDI : oui. Doigt : non | CC BY 4.0 |
| ClassClef | ~5 500 pièces | Guitare classique/flamenco. Fichiers GuitarPro + PDF. Certains avec vidéos YouTube | Tablature GP : oui. Doigt explicite : variable | Gratuit, permission obtenue |

### 1.2 Constat clé : le « fingering gap »
La plupart des datasets fournissent la position sur le manche (corde + fret) mais PAS le doigt de la main gauche utilisé. C’est une distinction cruciale : savoir qu’une note est jouée en fret 5 sur la corde 3 ne dit pas si c’est l’index en position 5 ou le majeur en position 4. Seul le dataset de Iino et al. (2025) fournit cette annotation complète, mais sur seulement 40 études. Le format GuitarPro stocke l’information de doigt (leftHandFinger / rightHandFinger dans PyGuitarPro) mais elle est rarement remplie par les transcripteurs communautaires.
Cela signifie que FretWise devra d’abord fonctionner avec les données corde+fret (abondantes) pour valider le positionnement sur le manche, puis enrichir progressivement avec des doigtés complets annotés manuellement ou inférés.

## 2. Formats d’entrée et pipeline de parsing
### 2.1 Formats supportés
| Format | Bibliothèque Python | Données extraites | Limites |
| --- | --- | --- | --- |
| GuitarPro (.gp3/4/5) | PyGuitarPro 0.10. Accès direct aux objets Note, NoteEffect, Fingering, Beat, Track | Pitch, corde, fret, doigt (si renseigné), durée, tempo, articulations complètes | Ne supporte pas GP6/GP7 (GPX). Doigt rarement renseigné dans les fichiers communautaires |
| MusicXML (.xml/.mxl) | music21. Module tablature : FretNote, ChordWithFretBoard, Fingering | Pitch, corde, fret, doigt (balise <fingering>), durée, tempo, dynamiques | Support tablature moins riche que GP. Conversion GP possible via MuseScore |
| MIDI (.mid) | mido ou pretty_midi | Pitch, onset, durée, velocity, tempo. Pas d’info corde/fret/doigt | Aucune info tablature. Entrée « partition pure » uniquement |
| JAMS | jams (Python). Format d’annotation de GuitarSet | Pitch contours par corde, notes MIDI par corde, accords, tempo, style | Spécifique à GuitarSet. Pas de doigt |
| DadaGP tokens | dadagp.py encoder/decoder. GP ↔ tokens | Séquence tokenisée : note, corde, fret, durée, effets. Optimisé pour modèles de séquence | Nécessite PyGuitarPro 0.6. Pas de doigt dans les tokens |

### 2.2 Architecture du parser M1
Le parser adopte une architecture à adaptateurs : un noyau commun produit des NoteEvents normalisés, et chaque format d’entrée dispose d’un adaptateur dédié.
Priorité : GuitarPro d’abord (via PyGuitarPro), car c’est le format le plus riche en information de tablature et le plus représenté. MusicXML en second (via music21) pour les partitions classiques annotées. MIDI en troisième pour l’entrée minimaliste.
#### 2.3 Extraction des doigtés depuis GuitarPro
Le modèle PyGuitarPro expose directement les informations nécessaires. L’objet Note contient value (fret) et string (corde). NoteEffect contient leftHandFinger et rightHandFinger (enum Fingering : open, index, middle, annular, little), plus les booléens hammer, staccato, palmMute, letRing, vibrato, et les objets slides, bend, grace, trill. Le pipeline itère sur Track, Measure, Voice, Beat, Note pour construire la séquence de NoteEvents.
#### 2.4 Extraction depuis MusicXML
MusicXML 4.0 supporte les doigtés guitare via deux mécanismes : la balise <fingering> dans <notations><technical> qui porte le numéro de doigt (1-5) par note, et la balise <frame-note> dans <harmony><frame> qui encode les diagrammes d’accords avec corde, fret, doigt et barré. La bibliothèque music21 expose ces données via son module tablature et les classes Articulations.

## 3. Pipeline d’ingestion des datasets
### 3.1 DadaGP : la source volumique
Ce qu’il apporte : 26 181 morceaux couvrant 739 genres. Plus grande collection de tablatures guitare structurées pour la recherche. Positions corde/fret, articulations, rythmes, tempos.
Comment l’exploiter : Accès sur demande (Dadabots / Pedro Sarmento). Extraction via PyGuitarPro 0.6. Conversion vers NoteEvent interne.
Valeur : Même sans doigtés explicites, les 26 000 tablatures encodent implicitement des choix de position faits par des humains. Un La3 joué en fret 5 corde 6 plutôt qu’en corde à vide corde 5 révèle une préférence exploitable pour l’entraînement.
Limite : Tablatures communautaires pouvant contenir des erreurs ou choix non optimaux.
### 3.2 GuitarSet : la source audio calibrée
Ce qu’il apporte : Enregistrements réels avec pickup hexaphonique. 360 extraits, 5 styles, 6 guitaristes, annotations JAMS riches avec vérité terrain par corde.
Comment l’exploiter : Téléchargement via Zenodo (CC BY 4.0) ou bibliothèque mirdata. Loader Python mirdata.datasets.guitarset fournissant accès structuré aux pitch contours et notes par corde.
Valeur : Validation du générateur d’états (M2) et, à terme, référence pour la calibration audio du joueur.
### 3.3 GAPS + ClassClef : la source classique
Ce qu’il apporte : Plus grand corpus classique aligné (14h audio, 300 performances, 200+ interprètes). Les GP ClassClef incluent souvent tablatures avec positions et parfois doigtés explicites.
Comment l’exploiter : GP ClassClef via classclef.com (gratuit). Dataset GAPS via Zenodo (accord recherche QMUL). Conversion GP vers MusicXML via MuseScore.
Valeur : Source idéale pour la couche interprétative (C_music) car les doigtés classiques sont choisis pour des raisons musicales (timbre, legato), pas seulement ergonomiques.
### 3.4 Iino et al. 2025 : la référence fingering
Ce qu’il apporte : Seul dataset avec annotation complète corde + doigt sur 40 études (Carcassi, Sor). Modèle publié : 94.4% accuracy corde, 90.3% doigt. Approche en cascade (corde puis doigt).
Comment l’exploiter : Contacter les auteurs (Nami Iino, JSPS KAKENHI). Dataset et/ou modèle entraîné comme benchmark et baseline.
Valeur : Référence de validation par excellence. >90% concordance = fonction de coût bien calibrée.

## 4. Construction de la base de patterns (M3)
La base de patterns est l’équivalent du livre d’ouvertures aux échecs : des blocs pré-optimisés appliqués sans calcul.
### 4.1 Sources pour les patterns
| Catégorie | Source | Méthode d’acquisition |
| --- | --- | --- |
| Accords standards | Dictionnaires d’accords (~2 000 formes) : majeurs, mineurs, 7èmes, diminués, sus, barrés | Encodage YAML initial. Enrichissement via extraction des Chord objects PyGuitarPro |
| Gammes | Majeures, mineures, pentatoniques, blues, modes dans les 5 positions CAGED | Génération algorithmique. Doigté standard déterministe par gamme et position |
| Arpèges | Arpèges des accords majeurs/mineurs dans différentes positions | Génération algorithmique à partir des formes d’accords |
| Patterns idiomatiques | Riffs récurrents, walking bass, picking patterns, turnarounds blues, cadences | Extraction par fréquence depuis DadaGP : séquences 4-8 notes les plus fréquentes |

### 4.2 Extraction automatique de patterns fréquents
L’approche n-gram sur les séquences de positions (corde, fret) extraites de DadaGP permet d’identifier les séquences de 4 à 8 notes apparaissant dans plus de N morceaux différents. Ces patterns sont ensuite validés et leurs doigtés optimaux enregistrés. Cette approche capture les spécificités de genre : un pattern blues récurrent sur les cordes 5-6 en position ouverte n’apparaîtra pas dans un dictionnaire classique mais sera très fréquent dans le corpus.

## 5. Données de calibration du joueur
Les données de calibration sont produites par le joueur lui-même. Le module M6 a besoin de deux types de données.
### 5.1 Méthodes de calibration par phase
| Méthode | Données produites | Technologie | Phase |
| --- | --- | --- | --- |
| Saisie manuelle | BPM limites par type de transition, étirement max, préférences subjectives | Formulaire web. Le joueur exécute les exercices avec métronome et rapporte les résultats | Phase 1-2 (MVP) |
| Entrée MIDI temps réel | Notes jouées, timing, velocity. Détection auto des erreurs de timing | Guitare MIDI, pickup hexaphonique, ou convertisseur audio-MIDI | Phase 3 |
| Analyse audio | Pitch par corde, onset/offset, propreté du son (buzz, étouffement) | Micro + algorithme de transcription (TabCNN ou modèle GAPS) | Phase 4 |

### 5.2 Évolution temporelle
Chaque session de calibration produit un snapshot daté des capacités. Stockage : JSON versionné par date, indexé par type de compétence. L’historique permet de calculer la progression et d’identifier les compétences en zone proximale de développement.
### 5.3 Apprentissage passif des préférences
Quand le joueur modifie les doigtés proposés via l’interface, ces modifications sont un signal d’apprentissage implicite. Le système enregistre la paire (doigté proposé, doigté choisi) et ajuste la fonction de coût. C’est un mécanisme de type RLHF (reinforcement learning from human feedback) appliqué aux doigtés.

## 6. Travaux académiques de référence
Le problème de l’optimisation des doigtés guitare est un sujet de recherche actif. Voici les travaux les plus pertinents pour FretWise.
### 6.1 Approches par optimisation
- López-Sánchez et al. 2022 : Algorithme évolutionnaire multi-objectif (Applied Soft Computing). Optimise facilité mécanique et qualité musicale simultanément. Pertinent pour la fonction de coût multi-critères.
- Ramos et al. 2015-2016 : Étude comparative algorithmes génétiques vs colonies de fourmis pour tablature. Confirme la supériorité de la programmation dynamique pour ce problème.
### 6.2 Approches par apprentissage automatique
- Iino et al. 2025 (MMM 2025) : Approche ensemble en cascade (corde puis doigt). 40 études annotées. Accuracy 94.4% corde, 90.3% doigt. Référence directe.
- Kaliakatsos-Papakostas et al. 2022 : Transformer pour conversion MIDI vers tablature. Utilise DadaGP. Démontre l’importance de l’historique pour la prédiction.
- Wiggins & Kim 2019 (TabCNN, ISMIR) : CNN pour estimation tablature depuis audio. Entraîné sur GuitarSet. Référence pour la transcription audio.
### 6.3 Approches cognitives
- Marmorini et al. 2010 : Modèle cognitif intégrant facteurs psychomoteurs. Pertinent pour la calibration joueur.
- Godoy & Norgaard 2021 : Rôle de la mémoire musculaire dans la performance experte. Pertinent pour la couche pédagogique (zone proximale).

## 7. Plan d’action par phase
| Phase | Données à acquérir | Actions | Livrable données |
| --- | --- | --- | --- |
| 1 | 5-10 fichiers GP de test. Dictionnaire d’accords de base (~200 formes) | Implémenter le parser GP. Encoder les accords ouverts/barrés en YAML | Pipeline GP → NoteEvent fonctionnel. Base de patterns v0 |
| 2 | Accès DadaGP. Télécharger GuitarSet. Obtenir les 40 études Iino et al. | Extraire positions de DadaGP. Intégrer GuitarSet via mirdata. Parser les études | Corpus de validation. Premiers benchmarks concordance |
| 3 | Accès GAPS. Télécharger ClassClef GP. Protocole calibration joueur | Parser les GP ClassClef pour doigtés. Implémenter formulaire calibration | Corpus classique enrichi. Profil joueur fonctionnel |
| 4 | Données d’usage (paires proposé/choisi). MIDI temps réel du joueur | Collecter corrections utilisateur. Entraîner fonction de coût apprise | Fonction de coût apprise. Modèle personnalisé |

## 8. Formats de sortie exploités par le guitariste
Le résultat de FretWise n’a de valeur que si le guitariste peut l’exploiter pour jouer. Trois formats de sortie sont retenus, chacun servant un usage différent.
### 8.1 GuitarPro annoté — Sortie principale
Mécanisme : Réinjection des doigtés calculés dans le fichier GP source via le champ NoteEffect.leftHandFinger de PyGuitarPro (enum Fingering : open, index, middle, annular, little). Le fichier s’ouvre dans Guitar Pro avec les doigtés affichés directement sur la tablature.
Notation : Guitar Pro affiche les doigtés comme des chiffres 0-4 au-dessus ou en dessous de la tablature. Notation T1234 (internationale) ou P1234 (française).
Round-trip : PyGuitarPro permet la lecture ET l’écriture du champ leftHandFinger note par note, rendant le round-trip complet : lire un fichier GP, calculer les doigtés, réécrire le fichier annoté.
### 8.2 ASCII tablature enrichie — Sortie CLI
Représentation texte classique (6 lignes e/B/G/D/A/E) avec les doigtés annotés au-dessus de chaque note (1/2/3/4). Affichée dans le terminal pour le feedback immédiat pendant le développement, sans nécessiter de logiciel externe.
### 8.3 JSON structuré — Format machine
Représentation pivot entre le moteur Viterbi et les exporteurs. Chaque note est décrite par un objet contenant : note_id, string, fret, finger, hand_position, cost, alternatives. Ce format alimente les tests automatisés, la visualisation web (phase 3) et le pipeline d’apprentissage (phase 4).
### 8.4 MusicXML — Non retenu pour le MVP
MusicXML supporte la balise <fingering> pour la main gauche et <pluck> pour la main droite. Ce format reste une option future pour les utilisateurs MuseScore/Dorico/Sibelius, mais n’est pas prioritaire car le rendu du doigté en tablature est moins intégré que dans Guitar Pro.

## 9. Risques et contraintes
### 9.1 Droits et licences
DadaGP et les tablatures communautaires posent des questions de droits d’auteur. Pour la recherche, le fair use académique couvre généralement l’usage. Pour un produit commercial, FretWise a l’avantage de ne pas utiliser les mélodies mais les choix de positionnement, qui ne sont pas protégés par le droit d’auteur.
### 9.2 Qualité des données communautaires
Les tablatures communautaires contiennent des erreurs de transcription et des choix non optimaux. Un filtrage par qualité est nécessaire. Pour l’entraînement IA, le bruit peut être atténué par le volume (26 000 morceaux).
### 9.3 Biais de représentativité
DadaGP est orienté rock/metal, GuitarSet et GAPS orientés acoustique/classique. Les doigtés optimaux varient selon le style. FretWise devra être testé et calibré sur plusieurs styles pour éviter un biais systématique.
### 9.4 Le « fingering gap » résiduel
Même après exploitation de toutes les sources, le volume de doigtés explicites restera limité. Stratégie double : inférer le doigt à partir de la position (souvent déterministe à 1-2 choix près), et construire un corpus de validation annoté manuellement (50-100 extraits) spécifiquement pour FretWise.

## 9. Synthèse
L’écosystème de données pour l’optimisation des doigtés guitare est riche et en croissance rapide, porté par la communauté MIR. FretWise peut s’appuyer sur des dizaines de milliers de tablatures structurées (DadaGP), des enregistrements calibrés avec vérité terrain par corde (GuitarSet), le plus grand corpus classique aligné (GAPS/ClassClef), et un benchmark de doigtés annotés par des experts (Iino et al.).
Le défi principal est le « fingering gap » : l’information de quel doigt est utilisé est rarement explicite. La stratégie est de commencer avec l’information de position (abondante), de l’enrichir par inférence algorithmique, puis de calibrer finement avec des données annotées et le feedback du joueur. Les bibliothèques Python existantes (PyGuitarPro, music21, mirdata, mido) fournissent tous les outils de parsing nécessaires dès la phase 1.
