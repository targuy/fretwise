# Plan d'implémentation — Vue Slope & Vue Main 2D/3D

> **Référence spec** : [`spec_vues_slope_main3d.md`](spec_vues_slope_main3d.md)
> (exigences `S-x` / `H-x`). Ce document découpe la spec en tâches ordonnées,
> chacune ancrée sur une fonction réelle, avec approche, test d'acceptation et
> risque. À lire avant d'ouvrir un fichier.
>
> **Convention** : une tâche = un identifiant `T-Px.y`. Chaque commit cite la
> tâche et l'exigence couverte (`feat(web): T-P0.1 latch doigt figé (H-15)`).
> Branches `fix/hand3d-*` et `fix/slope-*`.

---

## A. Diagnostic ancré (ce que le code fait aujourd'hui)

Vérifié en lecture ([`hand3d.js`](../src/fretwise/web/static/js/hand3d.js),
[`slope-renderer.js`](../src/fretwise/web/static/js/slope-renderer.js)) :

1. **Oscillation main (H-15)** — `_updateArticulated` a un verrou de régime
   établi *au poignet seulement* : si `sig` inchangé + `_wristConverged` +
   `_lastFoldOk` → return anticipé (pas de fold du tout). Deux fuites :
   - **Les doigts n'ont pas de verrou** : tant que le poignet n'a pas
     convergé, `_foldAllFingers` relance le **CCD complet** de chaque doigt
     par frame, avec cible lissée (`_animatedFingerTarget`, τ 45–75 ms). Le
     scan discret `fold()` (`FOLD_STEP = 1°`) choisit l'argmin de distance :
     sur des quasi-égalités entre frames, l'angle oscille de ±1°.
   - **`_nudgeWrist` peut battre** entre deux candidats quasi-égaux
     (seuil `1e-3` trop fin) → poignet jamais « convergé » → le skip ne se
     déclenche jamais → CCD relancé indéfiniment (les 30–90 ms/frame vus en
     session sur note tenue difficile).
   - `_easeWristPose` est exponentiel : convergence **asymptotique**, jamais
     exactement nulle → micro-reptation résiduelle sous le seuil `0.05`.

2. **Clipping (H-9)** — `AnimationMain.wristTarget` place le nœud poignet
   **sous** la touche (`MCP_NODE_Y = −16`), rangée MCP **au-dessus**
   (`MCP_LAUNCH_Y = 2.5`) ; le pont de paume (`bridgePalm`) est une ligne
   droite wrist→knuckles qui **peut traverser le galbe**. `_clampPalmVisualOnly`
   ne fait que **rétrécir la maille** de paume (cosmétique), il ne repose pas
   la paume sur le côté. → il n'existe aujourd'hui **aucun modèle de prise
   « paume au bord »** ; c'est le gros manque de P1.

3. **Courbure (H-10)** — `Doigt.fold` minimise gloutonnement la distance
   pointe→cible joint par joint (MCP→PIP→DIP), **sans a priori de forme** :
   rien ne garantit l'arche (IPP dominant, distale droite). La silhouette
   dépend de la géométrie de la cible, pas d'une contrainte de posture.

4. **Slope flou (S-1)** — `_drawFretDisc` fait
   `fillText(String(note.fret), point.x, point.y…)` **en direct chaque frame**,
   à des positions `point.x/point.y` **fractionnaires** (note en glissade) et
   des tailles de police **non entières** dérivées du `radius`
   (perspective). En plus, `_renderDpr()` **plafonne le DPR à 1,5** en
   qualité ≥ 2. Trois causes cumulées (fractionnaire + taille + DPR réduit) ;
   `noteName` tombe à `6px` (bouillie). Le texte n'est **pas** blitté depuis
   un cache — donc c'est purement de l'anticrénelage instable.

---

## B. Harnais de validation (à faire EN PREMIER — pré-P0)

Toutes les acceptations §5 de la spec s'appuient sur des « sweeps » déroulés
hors temps réel. Aujourd'hui ils sont tapés à la main dans la console. On les
fige une fois pour toutes.

- **T-B.1 — Mode self-test** dans [`hand_viz.html`](../src/fretwise/web/static/hand_viz.html) :
  exposer `window.__handSelfTest(opts)` qui, sur le morceau démo (ou un
  payload injecté), déroule tout le temps par pas fixe et renvoie un objet :
  ```
  { contact:{avg,max,over1}, collision:{palmHits,fingerHits,thumbHits},
    perf:{p50,p95,p99,maxConsecutiveOver33}, still:{sumDAngle,dWrist},
    camInvariant:{tipDeltaPovFace}, distalAngle:{avg,max} }
  ```
  Réutilise `CURRENT_SIM.update` + `buildKinSnapshot` + `HAND3D_RENDERER`.
  Chaque métrique mappe une exigence (§5). **Aucune logique produit dedans** —
  pur observateur.
- **T-B.2 — Guards pytest** : `tests/test_web_hand_viz_selftest.py` vérifie
  la **présence** du hook et des mécanismes en cliquant sur les sources
  (comme les guards existants), pas l'exécution WebGL (headless sans GPU).
- **Fait** : les captures écran restent best-effort (l'outil a été instable
  en session) — la validation **primaire** est le self-test programmatique,
  la capture est un complément.

Sortie de B : `__handSelfTest()` renvoie les métriques de référence
actuelles (baseline gelée pour mesurer les régressions).

---

## C. Phases

### P0 — Stabilité (H-14, H-15, H-16)

But : main **strictement immobile** hors transition, transitions continues,
budget frame tenu. C'est le socle : sans lui, tout réglage de P1 vibre.

- **T-P0.1 — Verrou par doigt.**
  *Fichier* : `hand3d.js` → `_foldAllFingers`, nouvel état `_fingerLatch[f]`.
  *Approche* : pour chaque doigt, calculer une signature `(role, fret, string)`
  et suivre la convergence de son **eased target** (`_animatedFingerTarget`
  renvoie déjà `motion`; ajouter un `arrived` quand `|target−motion| < eps`).
  Quand `sig doigt inchangée` **ET** `arrived` **ET** dernier `fold()` non
  `UNREACHABLE` → **réutiliser les angles gelés** (`applyThetas(dernier θ)`),
  sauter le CCD. Ne re-folder que les doigts dont la cible bouge encore ou
  dont la signature change.
  *Accept.* : sweep `still` → `sumDAngle == 0` après convergence (< 0,5 s).
  *Risque* : geler trop tôt (mid-glide) → snap. Garde-fou : ne latcher que si
  `arrived` **et** `fold()==CONTACT` la frame précédente.

- **T-P0.2 — Snap-to-target de fin d'ease.**
  *Fichier* : `_easeWristPose` (+ analogue `_animatedFingerTarget`).
  *Approche* : sous un seuil serré (`moveMag < 0.005`), poser `p = target`
  exactement (fin de la reptation asymptotique) et marquer converged. Kill la
  micro-dérive résiduelle.
  *Accept.* : `dWrist == 0` (pas `< ε`) après convergence.

- **T-P0.3 — Anti-battement `_nudgeWrist`.**
  *Fichier* : `_nudgeWrist`.
  *Approche* : (a) élargir la deadband d'amélioration (`> 0.05 wu`, pas
  `1e-3`) ; (b) hystérésis : ne changer de candidat que s'il bat le
  **candidat courant** d'au moins la deadband (préférence au statu quo) ;
  (c) une fois `unreachable` vide, ne PAS relancer la boucle de compensation.
  *Accept.* : sur note tenue, `perf.p50 ≤ 2 ms` et `still.dWrist == 0`.
  *Risque* : sous-compensation (contact raté). Mesuré par le sweep contact —
  si régression, baisser la deadband, pas la retirer.

- **T-P0.4 — Tiebreak stable dans le CCD.**
  *Fichier* : `Doigt.fold`.
  *Approche* : dans le scan d'angle, garder l'angle **courant** si un autre
  n'améliore pas d'au moins `1e-3` (déjà `bestD - 1e-4` → passer à
  `bestD - 1e-3` et initialiser `bestA = cur`). Empêche le flip ±1° sur
  quasi-égalité.
  *Accept.* : composante `fold` du sweep `still` = 0.

- **T-P0.5 — Gel global en pause.**
  *Fichier* : `_updateArticulated` (garde existante) + vérifier le chemin
  d'appel `update()` en pause dans `hand_viz.html`.
  *Approche* : étendre la garde « return anticipé » pour exiger **poignet ET
  tous doigts** convergés/latchés. Confirmer que l'hôte continue de `render()`
  (caméra orbitable) mais que la **pose** ne recalcule rien.
  *Accept.* : sweep `still` sur 300 frames kin constant.

**Sortie P0** : `still.sumDAngle==0`, `still.dWrist==0`, `perf.p50 ≤ 2 ms`,
`perf.maxConsecutiveOver33 == 0`, sweep contact non régressé.

---

### P1 — Justesse biomécanique (H-9, H-10, H-11, H-12, H-13)

But : prise physiquement crédible, doigts en voûte, repos naturel, contact
juste — **sans jamais** retomber dans les 3 post-mortems (§E).

- **T-P1.1 — Modèle de prise « paume au bord » (LE gros morceau).**
  *Fichier* : `hand3d.js` → nouvelle `restGripPose()` remplaçant la logique
  Y de `wristTarget` ; `Main`/`bridgePalm` pour la pose de paume.
  *Approche* : dériver la pose de repos de la **géométrie du manche**, pas
  d'une descente Y arbitraire :
  - plan de contact = côté joueur du manche (`z = +neckHW`, `y ∈ [bellyY..0]`);
  - poser la **face −Z de la paume tangente** à ce plan (paume contre le
    bord, jamais dedans) ;
  - rangée MCP **juste au-dessus** du bord haut +Z (`y ≈ 0..+2`), d'où les
    doigts **arquent par-dessus** vers les cases ;
  - pouce ancré à `−Z` (galbe), pose fixe de brace (déjà `animation_pouce`).
  Le poignet ne descend plus **sous** la touche ; il **flanque** le manche.
  *Accept.* : `collision.palmHits == 0` **et** `fingerHits == 0` **et**
  `thumbHits == 0` sur tout le sweep, **toutes positions** (frettes 1→22,
  cordes 1→6). Contact maintenu (`contact.max < 1.0`).
  *Risque* : casser l'atteinte des graves (cf. post-mortem 1). Garde-fou :
  la pose vient de la géométrie, la compensation R11 reste seule à ajuster
  l'atteinte — **jamais** de poussée réactive +Z/Y.
  *Rollback* : la pose est derrière un flag `?grip=side` le temps de valider
  côte à côte avec l'actuelle.

- **T-P1.2 — Courbure en voûte (H-10).**
  *Fichier* : `Doigt.fold` (a priori de forme) ou passe post-fold.
  *Approche* : après convergence CCD, appliquer une **répartition d'arche** :
  redistribuer le total de flexion vers IPP (dominant), garder IPD proche de
  la valeur qui rend la distale ⊥ touche (couplage `DIP_PIP_COUPLING_PRESS`
  existe côté 2D — porter le principe). Alternative plus simple : biaiser le
  scan pour pénaliser un IPD > seuil quand IPP a de la marge.
  *Accept.* : `distalAngle.max ≤ 30°` (angle distale/normale-touche) sur le
  sweep, contact toujours < 1,0.

- **T-P1.3 — Repos naturel (H-12).**
  *Fichier* : `IDLE_CURL`, `relax()`, `REST_SPLAY`, branche `else` de
  `_foldAllFingers`.
  *Approche* : régler la courbe de repos (MCP ~30–50°, IPP ~45–60°) pour que
  la pointe flotte 5–15 mm au-dessus des cordes avec léger éventail.
  *Accept.* : pour chaque doigt idle, `tipY ∈ [STRING_SURFACE+mm(5),
  STRING_SURFACE+mm(15)]` et aucune pointe idle à moins de `CONTACT_EPS`
  d'une corde.

- **T-P1.4 — Rôles cinématiques (H-13).**
  *Fichier* : `_updateArticulated` (choix `idxFret`/`maxZ`) + cap yaw dans
  `_placeFingerTo`.
  *Approche* : quand la case cible sort de l'empan courant, **repositionner le
  poignet en X** (slide) au lieu d'étirer le doigt ; yaw doigt reste plafonné
  45° (`MCP_ABD_HALF`, déjà là — vérifier qu'aucun chemin ne le dépasse).
  *Accept.* : sur sweep, `max |yaw doigt| ≤ 45°` ; `wrist.x` suit la frette
  active la plus basse (corrélation vérifiée).

- **T-P1.5 — Garde de contact (H-11).** Pas de code neuf : régression guard.
  *Accept.* : `contact.avg < 0.5`, `contact.max < 1.0` (baseline 0,35/0,84).

**Sortie P1** : les 4 sweeps (contact, collision, distale, repos) au vert,
sur `?grip=side`, puis bascule du flag en défaut + retrait de l'ancienne pose.

---

### P2 — Lisibilité du plateau (H-3, H-4, H-5, H-7, H-8)

But : le manche « se lit » — cases exactes, cordes à vide, numéros 0–22, zéro
occlusion.

- **T-P2.1 — Case (s,f) exacte (H-5).**
  *Fichier* : `_updatePlayedFrets` / pool `_playedCells`.
  *Approche* : largeur Z = **1 espacement inter-cordes** (`_stringSpacing`),
  longueur X = **espace de case complet** `|fretX(f)−fretX(f−1)|`, centre X
  au **milieu de case** (pas au point de presse 75 %), hauteur fine émissive.
  Aujourd'hui : `width*0.85`, `depth*0.78` — passer aux valeurs exactes (léger
  retrait ε pour ne pas mordre le fil voisin).
  *Accept.* : guard source + capture ; dimension cellule == géométrie case.

- **T-P2.2 — Corde à vide (H-7).**
  *Fichiers* : `buildKinSnapshot` (`hand_viz.html`) doit **ajouter
  `openStrings`** au payload (déjà calculé côté 2D `sampleState`, pas transmis
  au 3D) ; `hand3d.js` allume le **tube de corde** (stocké dans `stringMeshes`)
  en émissif + un **sprite « 0 »** au sillet, pour la durée de la note. Aucun
  doigt ne bouge.
  *Accept.* : sur une note à vide du sweep, matériau corde == émissif ET
  sprite 0 visible ; aucun doigt en `active` sur cette corde.

- **T-P2.3 — Numérotation 0–22 (H-4).**
  *Fichier* : `_addFretNumber` + sa boucle d'appel dans `setGeometry`.
  *Approche* : ajouter le **« 0 » au sillet** (aujourd'hui la boucle démarre
  à la 1re case). Vérifier lisibilité sur les deux presets (sprites déjà
  pré-mirrorés POV).
  *Accept.* : guard source (`0` émis) + capture POV/Face.

- **T-P2.4 — Occlusion (H-3).**
  *Fichier* : `_buildLiteGuitar` / `_buildStrat` (placement corps/tête).
  *Approche* : garantir que corps/tête/mécanique restent **hors** du couloir
  caméra→région active ; si un extrême (frette 22) les met dans le champ,
  reculer/fondre l'objet décoratif. Ne jamais masquer une corde/frette de la
  zone jouée.
  *Accept.* : raycast caméra→cellules actives ne traverse aucun mesh
  décoratif ; capture aux positions extrêmes.

**Sortie P2** : guards + captures (accord tenu, corde à vide, numéros).

---

### P3 — Netteté Slope (S-1, S-2, S-3) — **indépendant, parallélisable**

But : texte net même en défilement, sans coût fps.

- **T-P3.1 — Positions de rendu texte alignées device-pixel (S-1).**
  *Fichier* : `slope-renderer.js` → `_drawFretDisc`.
  *Approche* : pour les `fillText` uniquement, arrondir
  `x = Math.round(point.x*dpr)/dpr`, idem y — la position **logique** du
  disque reste continue (le disque glisse doux, le glyphe ne bave plus).
  *Accept.* : capture zoom d'un chiffre en glissade, sans halo.

- **T-P3.2 — Tailles de police entières + planchers (S-1/S-2).**
  *Approche* : arrondir `fretSize`/nameSize à l'entier, plancher chiffre
  ≥ 11 px **device**, nom de note ≥ 8 px — sinon **ne pas dessiner le nom**
  plutôt qu'un 6 px illisible.
  *Accept.* : aucune police < plancher émise (grep runtime).

- **T-P3.3 — Découpler la netteté texte du palier qualité (S-1/S-3).**
  *Fichier* : `_renderDpr` / passage de rendu.
  *Approche* : le texte critique ne doit pas subir le plafond DPR 1,5. Option
  A (simple) : relever le plancher DPR à 2 pour la passe texte. Option B (si
  A insuffisant) : atlas de glyphes pré-rendu à 2× blitté en `drawImage`
  entier (`imageSmoothingEnabled=false`). Commencer par A, mesurer fps.
  *Accept.* : `S-3` — fps ≥ 60 sur machine de référence après changement.

- **T-P3.4 — Backing store & pas d'échelle CSS (S-2).**
  *Fichier* : `resize()` + CSS du canvas.
  *Approche* : vérifier `canvas.width == round(clientWidth*dpr)` après resize
  (déjà le cas — ajouter le test) ; s'assurer qu'aucune règle CSS ne
  `transform: scale` le canvas.
  *Accept.* : **test auto** `tests/test_web_slope_dpr.py` (guard source : la
  taille du backing store dérive de `clientWidth*dpr`, pas de `scale` CSS sur
  `#slope-canvas`).

**Sortie P3** : test DPR vert + captures avant/après.

---

### P4 — Cohérence 2D (H-17)

But : le simulateur 2D partagé raconte le même geste (repos, timings).

- **T-P4.1** — Porter les constantes de repos (H-12) et de timing (H-14) dans
  `HandSimulator`/`solveFinger` (`hand_viz.html`) pour que la vue 2D adopte
  les mêmes poses de repos et lissages. Basse priorité (2D « marche » déjà) ;
  cadre : ne pas diverger cinématiquement du 3D.
  *Accept.* : mêmes rôles/positions sur un snapshot donné (les guards de
  parité existants restent verts).

---

## D. Séquencement & dépendances

```
B (harnais)  ─┬─► P0 ─► P1 ─► P2 ─► P4
              └─► P3 (Slope, en parallèle, aucune dépendance)
```

- **B avant tout** : sans les sweeps figés, aucune phase n'est mesurable.
- **P0 avant P1** : régler la biomécanique sur une base qui vibre = illusoire.
- **P1 avant P2** : la case (H-5) et la corde à vide (H-7) se valident mieux
  une fois la main juste.
- **P3 totalement indépendant** — peut être fait en premier si priorité
  utilisateur, ou par un second contributeur.
- **P4 en dernier** — polish de parité.

Estimation relative (pas de dates) : P1.1 (prise) est la tâche la plus lourde
et la plus risquée ; tout le reste est incrémental.

---

## E. Registre de risques (garde-fous durs — issus des post-mortems)

| # | Piège | Règle |
|---|---|---|
| R1 | Corriger collision paume/manche en **poussant le poignet** (+Z) ou en **raccourcissant sa descente Y** | **INTERDIT** — casse l'atteinte des graves. Prévenir par la pose de prise (T-P1.1), jamais réactivement. |
| R2 | Scorer l'atteignabilité par **distance euclidienne pure** (sans CCD) | Faux — ignore limites articulaires/collision. Garder le classement analytique **suivi** d'une vérif CCD bornée (`_nudgeWrist` actuel). |
| R3 | **Re-viser chaque frame** la cible d'easing « fraîche » sur note tenue | Oscillation perpétuelle. Verrouiller la cible une fois trouvée, ne rafraîchir que sur changement de signature. |
| R4 | Geler un doigt **mid-glide** (T-P0.1) | Snap visible. Ne latcher qu'après `arrived` **et** `CONTACT`. |
| R5 | Relever le DPR partout (P3) | Coût fps. Cibler la **passe texte** seule ; mesurer S-3. |

---

## F. Livrables par phase

Chaque phase se clôt par : (1) le sweep §5 correspondant au vert dans
`__handSelfTest()`, (2) captures POV+Face (best-effort), (3) `pixi run pytest
tests/test_web_hand_viz*.py` sans **nouvelle** régression (les 26 échecs
`WinError 206` / `cp1252` sont préexistants et hors périmètre — cf. sessions
antérieures), (4) commits citant `T-Px.y` + `H-x`/`S-x`.
