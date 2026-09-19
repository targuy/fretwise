# Main v2 : intégration de la référence du 14 septembre 2026

Traçabilité : `specifications/notion_hand_replacement_2026-09-14.md`, sections 7–11,
16–19. La sélection `handRenderer=v2` conserve le moteur historique disponible.

## Actif livré

La main de la maquette Notion est importée intégralement : mesh WebXR générique
gauche, 25 articulations, deux subdivisions, 18 514 sommets et 37 024 triangles.
La surface et les ombres utilisent le même skinning dual-quaternion ; la recherche
de contact évalue les sommets distaux de cette même surface sur CPU.

`static/models/hand-reference/manifest.json` conserve les hashes des sources,
du GLB et des données runtime. `LICENSE.txt` conserve la licence MIT Amazon.
`source.glb` est l'actif source ; `hand_reference_asset.js` contient les données
runtime extraites, sans appel réseau externe. `scripts/import_reference_hand.cjs`
permet de reproduire cette extraction depuis l'archive fournie par l'utilisateur.
Le script ne fait pas partie du démarrage de l'application.

La conversion de repère reprend la correction de latéralité du prototype.
Les échanges publics emploient des mètres, X vers le chevalet, Y vers l'aigu,
Z vers le dessus de la touche. Le solveur de référence utilise des millimètres,
X vers le chevalet, Y vers le dessus, Z vers l'aigu. Les longueurs d'os restent
constantes. Une cible inaccessible produit un résidu et une pose translucide ;
elle ne déclenche plus le repli à trois angles fixes de la maquette.

## Transport et cycle de vie

`hand_motion.js` compile HandPerformance 1.0/1.1 en contacts indépendants par doigt,
fenêtres de préparation, événements et trajectoires de racine. Les secondes
nominales proviennent de l'intégration de tous les segments de tempo. La vitesse
ne multiplie que les contraintes motrices pendant compilation : `renderAt()`
reçoit directement les secondes nominales du lecteur parent.

`hand_motion_worker.js` réalise la compilation temporelle dans un Worker module.
`hand_compiler.js` termine le Worker remplacé, ignore les identifiants obsolètes,
gère AbortSignal et délai maximal. Aucun Worker ne calcule le son. Le solveur IK
et le contact DQS restent dans le composant de rendu, avec caches bornés ; il ne
s'agit donc pas encore d'un plan articulaire complet calculé hors rendu.

`hand_v2.js` expose `create(container, {onDiagnostics})`, puis :

- `setPerformance(performance)` : compile et remplace le plan, asynchrone ;
- `clearPerformance()` : annule immédiatement le Worker et efface l'ancienne main ;
- `setPlaybackRate(rate)` : recompile, y compris pendant un premier chargement ;
- `renderAt(nominalScoreSec)` : échantillonne directement, sans horloge locale ;
- `setCamera('fingers'|'thumb'|'palm'|'profile')`, `setDiagnostics(enabled)` ;
- `getCapabilities()`, `getDiagnostics()`, `getMetrics()`, `dispose()`.

Le moteur ne reçoit pas de messages iframe et ne crée pas de boucle RAF.
Le parent gère transport et sécurité du protocole. Le composant ignore les rendus
hors écran ; il libère géométries, matériaux, textures, Workers et écouteurs à sa
destruction. Une perte WebGL suspend le rendu ; sa restauration réaffiche le même
instant musical. Un échec d'import ou de création remonte au parent pour son repli SVG.

## Couverture et limites affichées

Les notes simultanées et tenues conservent leur durée. Une répétition au même
contact ne lève pas inutilement le doigt. Les transitions ordinaires sont continues
en position et suivent une quintique à vitesse/accélération nulles aux extrémités.
Les conflits de maintien ne réaffectent pas les doigts et ne coupent pas les notes.
Une recherche temporelle ne dépend pas des images précédemment affichées.

Les liens hammer-on/pull-off/slide sont contrôlés contre les doigts, cordes et cases.
Le pull-off prépare le doigt inférieur et possède une déviation tangentielle.
Les courbes de bend/vibrato restent absolues ; sans courbe métrique calibrée,
le déplacement est illustratif et porte `BEND_CALIBRATION_MISSING`.
Une technique inconnue reste dans le document et invalide sa plage.

Le badge reste « modèle de référence ». Ne pas qualifier cette livraison de main
photoréaliste validée ni de simulateur physique. Restent non qualifiés :

- pouce en prise et chaîne complète épaule/coude/poignet ;
- barrés surfaciques, substitutions et balayage continu des collisions ;
- force, tension/friction des cordes et anatomie des amplitudes extrêmes ;
- correctifs sculptés, LOD et performances matérielles iPhone/iPad ;
- trilles non normalisés, harmoniques et gestes de la main qui pince les cordes.

Les profils livrés sont `adult-reference-left/1` et `six-string-648/1`.
Un profil inconnu est rejeté. Les reprises non déroulées et rampes de tempo
non prises en charge rendent explicitement le plan partiel/invalide.

## Vérification

`pixi run python -m pytest tests/test_web_hand_motion_v2.py -q` exécute les modules
réels dans Node : carte de tempo, vitesse, maintien, conflits, seeks, raccords,
pull-off/bend, annulation Worker, profils et contacts de peau Am/C/position V.
Les tests de contact exigent un résidu inférieur à 0,5 mm et des longueurs d'os
invariantes à 1e-10 mm. Ce corpus ne certifie pas toutes les prises de guitare.
