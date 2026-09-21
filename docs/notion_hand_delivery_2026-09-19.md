# Doigtés et main de référence — livraison du 19 septembre 2026

## Sources et périmètre

Spécifications : [remplacement de la main](specifications/notion_hand_replacement_2026-09-14.md),
[étude des doigtés](specifications/notion_fingering_animation_2026-09-14.md).
L'archive fournie `fretwise.zip` a été vérifiée : SHA-256
`d7da4707de2d34978b7e0e0dc84bdffa087eacc722ef59138139473cc8ae6470`.
Les requêtes signées temporaires Notion sont retirées des copies documentaires.
Le modèle MIT est livré avec sa licence et son manifeste ; les photographies de référence
personnelles et les captures du prototype ne sont pas intégrées au produit.

## Changements livrés

| Spécification | Réalisation | Preuve |
|---|---|---|
| Doigtés, contraintes toutes voix | Génération avec contractions/extensions ; préférence ou verrou source ; vérification des tenues, barrés et cordes ouvertes ; recherche corrective conjointe bornée | `test_hand_planning.py`, `test_generator.py`, `test_biomechanics.py` |
| Contrat HandPerformance 1.1, §19 | Schéma strict versionné, identités source/occurrence, révisions, tempo PPQ, expressions, exécution et diagnostics | `test_hand_performance.py` |
| API lecture seule, §11 | POST `/api/v2/hand-performance`, contrôles d'accès existants, 409 sur révision, 422 si données incomplètes, aucun recalcul implicite | `test_web_hand_performance.py` |
| Profils versionnés | GET `/api/v2/hand-profiles/adult-reference-left/revisions/1`, équivalent instrument `six-string-648` ; empreintes et licence | tests HTTP |
| Main continue, §§16–18 | Mesh gauche fourni, DQS, contacts pulpe, longueurs osseuses fixes, quatre vues caméra | `test_web_hand_motion_v2.py` |
| Mouvement, §§8–10 | Plan déterministe, anticipation, tenues, transitions quintiques, Worker annulable, invalidation vitesse/révision | tests moteur et Worker |
| Chronologie commune, §19 | Temps nominal issu de l'AudioContext quand actif ; tempo intégré ; pause/seek/vitesse ; bascule audio/métronome sans saut | `test_hand_transport.py`, `test_playback_clock_switch.py` |
| Échange iframe, §11 | Origine et fenêtre exactes, protocole/session/plan/séquence, gel après 250 ms et diagnostic de désynchronisation | tests transport |
| Migration, §13 | Main de référence unique ; moteur historique, sélecteur et flags supprimés ; vue dessus orthographique 90° | recette navigateur + tests caméra |

M5/Viterbi conserve son interface. Les données personnelles, configurations serveur,
modèles ONNX, partitions et travaux HeadRush ne font pas partie de cette release.

## Utilisation

Ouvrir un morceau avec doigtés enregistrés, puis choisir **3D**. La main de référence
marquée « aperçu » démarre directement. Le menu caméra passe entre doigts, pouce, paume
et profil ; **Vue dessus** affiche une projection orthographique à 90°. Les changements de piste
effacent immédiatement l'ancien plan ; une performance absente ne réutilise pas une main ancienne.
L'aperçu des accords garde les six cordes et se renouvelle à chaque partition.

Les doigtés existants sont lus tels qu'enregistrés. Le bouton de recalcul reste une action
explicite ; afficher la main ne modifie jamais une partition.

## Validation et limites

Les tests couvrent tempo variable et silences, capo GPIF, articulations, identités,
révisions, accès utilisateur/CSRF, Worker obsolète, contacts Am/C/position V, absence
d'étirement et échantillonnage indépendant du nombre d'images. La recette navigateur
utilise une partition synthétique Am → C → position V et VII, sans fichier personnel.

Mesures CPU locales de 240 poses DQS : médiane 0,207 ms, p95 0,646 ms. Ces mesures
ne comprennent pas le GPU et ne qualifient aucun téléphone. Les contacts Am mesurés
sur les données de l'API sont à 0,007 / 0,024 / 0,020 mm des cibles.

**Cette livraison est une intégration de la main de référence, pas la qualification finale
anatomique et artistique demandée par la spécification.** Restent ouverts : pouce indépendant,
barrés surfaciques, collisions globales et balayage continu certifié, correctifs sculptés,
forces de contact, calibration mécanique des bends et validation par guitaristes.
Le plan temporel passe en Worker ; certaines résolutions de contacts sont encore calculées
et mises en cache au rendu. Les reprises non déroulées et les rampes tempo sont diagnostiquées
comme non prises en charge ; les expressions dépourvues de données restent explicitement inconnues.
Une transition irréalisable dans le temps disponible est signalée et représentée en transparence,
sans raccourcir la tenue musicale ni prétendre à une exécution validée.

Une promotion de l'aperçu comme moteur par défaut nécessite ces validations. Voir
[contrat](hand_performance_contract.md), [moteur](hand_v2_runtime.md),
[contraintes](fingering_joint_planning.md).

La suite globale du dépôt de travail a initialement donné 2 558 réussites, 15 skips,
29 échecs. Les harness Windows des tests de main ont été réparés (stdin UTF-8 remplace
une ligne de commande trop longue), puis les 87 tests d'intégration concernés passent.
Les deux échecs de notation (bande de percussion et snapshot multiligne) ont été reproduits
sur le commit de production intact `c016312f`. Les tests HeadRush passent sur cette base
isolée ; ses données de travail sont exclues de la release.

## Déploiement et retour arrière

Base production : `20260911-130407-c016312f`. Livraison via commit Git isolé sur cette base,
archive du commit, image Docker immutable, contrôle readiness puis promotion de `current`.
Le précédent répertoire de release et son image sont conservés pour retour arrière.
Les résultats de déploiement et l'identifiant exact sont inscrits dans le compte rendu de livraison.
