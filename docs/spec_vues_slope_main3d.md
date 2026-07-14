# Spécification — Vue Slope (arcade) & Vue Main 2D/3D

> **Statut** : cadrage validé utilisateur — référence pour la planification et
> l'implémentation. Chaque exigence porte un identifiant (`S-x` pour Slope,
> `H-x` pour la main 2D/3D) à citer dans les commits, tests et revues.
> Les critères d'acceptation sont écrits pour être vérifiables (test auto ou
> protocole visuel décrit en §5).

---

## 0. Contexte et périmètre

FretWise lit des partitions Guitar Pro à l'écran. Deux modes de vue sont
concernés par cette spec :

| Vue | État actuel | Fichiers principaux |
|---|---|---|
| **Slope** (arcade type Guitar Hero : les notes sont des barres lumineuses qui défilent le long des cordes) | Fonctionne bien, **sauf** netteté du texte en mouvement | [`slope-renderer.js`](../src/fretwise/web/static/js/slope-renderer.js), intégration dans [`main.js`](../src/fretwise/web/static/js/main.js) |
| **Main 2D/3D** (onglet « 3D » : main gauche articulée sur le manche ; bascule interne 2D/3D ; caméra libre + presets POV / Face) | 2D fonctionne mais mouvements peu réalistes ; 3D : clipping main/manche, courbure des doigts peu naturelle, contact imprécis, animation saccadée, oscillations au repos | [`hand_viz.html`](../src/fretwise/web/static/hand_viz.html) (simulateur 2D + hôte), [`hand3d.js`](../src/fretwise/web/static/js/hand3d.js) (rig 3D) |

Hors périmètre : les autres vues (Staff/Mixed/Tab), le solveur de doigtés
(pipeline Viterbi), l'audio.

---

## 1. Vue Slope — netteté du texte en mouvement

### Problème constaté
Les lettres (noms de notes, noms de cordes) et chiffres (frettes) défilant
avec les notes sont **flous pendant le mouvement**, alors que la vue est
par ailleurs satisfaisante.

### Exigences

- **S-1 — Netteté en défilement.** Tout texte porté par un objet mobile
  (numéro de frette dans la barre de note, nom de note) doit rester net à
  vitesse de lecture nominale (60–200 BPM), sur écran standard et HiDPI.
- **S-2 — Netteté du texte fixe.** Les textes fixes (noms de cordes, BPM,
  accords) restent nets quel que soit le `devicePixelRatio`.
- **S-3 — Aucune régression de fluidité.** La correction ne doit pas faire
  passer la vue sous 60 fps sur la machine de référence.

### Causes candidates (à diagnostiquer dans cet ordre)

1. **Coordonnées fractionnaires** : `fillText` à des positions non entières
   pendant la glissade → anticrénelage différent à chaque frame = « bavure ».
   Remède : arrondir la position de RENDU du texte au pixel device
   (`Math.round(x * dpr) / dpr`) tout en gardant la position logique continue.
2. **Petites tailles × perspective** : polices < ~9 px rendues puis
   rétrécies par le facteur de perspective. Remède : taille de police
   plancher + pré-rendu des glyphes dans un atlas à 2× puis blit entier.
3. **Backing store sous-dimensionné** : vérifier que le canvas est bien
   dimensionné à `cssSize × dpr` à CHAQUE resize (le `setTransform(dpr,…)`
   existe déjà — vérifier le chemin resize).
4. **Compositing navigateur** : si le canvas subit un `transform: scale`
   CSS, le texte est rééchantillonné. Remède : aucune échelle CSS sur le
   canvas, uniquement des tailles entières.

### Critères d'acceptation

- Capture d'écran en cours de lecture (note en défilement au centre) :
  les chiffres de frette sont lisibles sans halo, comparaison avant/après.
- Test auto : le backing store du canvas vaut exactement
  `clientWidth × dpr` après resize.

---

## 2. Vue Main 2D/3D — géométrie du manche

Référentiel monde 3D actuel (conservé) : `+X` = du sillet vers le chevalet,
`+Y` = au-dessus de la touche, `+Z` = côté joueur (corde 1 / mi aigu à `+Z`,
corde 6 / mi grave à `−Z`). Source : en-tête de
[`hand3d.js`](../src/fretwise/web/static/js/hand3d.js).

### Exigences

- **H-1 — 22 frettes, espacement réel.** Le manche porte **22 frettes**
  (fils métalliques) plus le **sillet (frette 0)**. L'espacement suit la
  loi des tempéraments : `x(f) = L · (1 − 2^(−f/12))` — **les cases ne sont
  pas de largeur uniforme** et toute géométrie de case doit être calculée
  frette par frette, jamais avec un pas constant.
  *(Déjà en place : `fretX()` dans `hand_viz.html`, forcé à 22 en vue
  dédiée via `configureGeometry` ; à préserver.)*
- **H-2 — 6 cordes distinctes.** Les 6 cordes sont visibles et
  différenciables en toutes circonstances (espacement constant ~10,5 mm,
  cordes filées vs unies déjà différenciées bronze/argent). Aucun objet ne
  doit masquer une corde dans la zone jouée.
- **H-3 — Zone jouable jamais occluse.** Les éléments décoratifs (corps,
  tête, mécanique) ne doivent **jamais masquer** les frettes dessinées ni
  la main dans les cadrages par défaut (POV, Face). Selon le cadrage on
  peut ne voir qu'un sous-ensemble des 22 frettes : acceptable, à condition
  que la **région active** (position de la main ± 2 frettes) soit toujours
  entièrement visible. Si un preset caméra ne peut garantir cela sur tout
  le manche (frettes 1 et 22), le cadrage suit la main (déjà le cas :
  `_lookAt.x` suit `_palmX`).
- **H-4 — Numérotation 0–22 lisible.** Les numéros de frettes sont affichés
  **en face du manche** (le long du bord), de **0** (sillet) à **22**,
  lisibles depuis n'importe quel angle de caméra (sprites face caméra,
  pré-mirrorés pour le preset POV — mécanisme `_addFretNumber` existant, à
  étendre : aujourd'hui la numérotation commence à 1, le **0 au sillet
  manque**).

### Définition formelle de la « case » (cellule)

- **H-5 — Case (s, f)** pour corde `s` ∈ [1..6] et frette `f` ∈ [1..22] :
  - **longitudinalement (X)** : du fil de frette `f−1` au fil de frette `f`
    (autrement dit : moitié de l'espace devant le doigt, moitié derrière,
    le doigt étant idéalement au centre-avant de la case) ;
  - **latéralement (Z)** : centrée sur la corde `s`, s'étendant de
    **½ espacement inter-cordes de chaque côté** (largeur totale = 1
    espacement inter-cordes) ;
  - la case est un concept **par corde** : appuyer la case (3, 5) n'allume
    ni la corde 2 ni la corde 4.
- **H-6 — Point de pression du doigt.** Le bout du doigt presse **dans la
  case**, sur la corde, dans la **moitié proche du fil de frette `f`**
  (côté chevalet) — convention guitariste standard. Implémentation
  actuelle : `_pressX(f)` = 75 % de l'espace de case ; conserver ce ratio
  (tunable 70–80 %).

### Corde à vide (frette 0)

- **H-7 — Frette 0 = corde à vide.** Quand une note est jouée à vide :
  - **aucun doigt** ne presse (la main reste dans sa position courante) ;
  - on allume **la corde elle-même** (surbrillance du tube de corde sur
    toute la longueur visible, ou au minimum du segment sillet→région
    active) **pendant la durée de la note** ;
  - on allume aussi **le chiffre « 0 »** au sillet pendant la même durée.
  *(État actuel : rien ne s'allume pour une corde à vide en 3D — à
  implémenter ; le payload expose déjà `openStrings` côté 2D.)*

### Allumage des cases jouées

- **H-8 — Case allumée = note qui sonne.** Quand un doigt presse et que la
  note **sonne** (`role = active`), la case (s, f) s'allume pendant toute
  la durée de la note puis s'éteint. Un doigt qui presse **sans** que la
  note sonne (`role = planted`, préparation) n'allume PAS la case — son
  état est signalé par la couleur du bout de doigt (vert = survol,
  bleu = planté, rouge = joue).
  *(Implémenté : `_updatePlayedFrets` + pool `_playedCells` — boîte émissive
  épaisse (pas un plan : un plan rasant est invisible en POV) dimensionnée
  case par case sur `fretX`. À faire évoluer vers la définition H-5 exacte :
  largeur = 1 espacement inter-cordes, longueur = espace de case complet.)*

---

## 3. Vue Main 2D/3D — biomécanique et animation

### Modèle de prise (contraintes structurelles)

- **H-9 — La paume ne traverse JAMAIS le manche.** Principe directeur :
  la **paume est posée contre le côté joueur du manche** (elle peut le
  toucher, jamais le pénétrer) ; le **pouce s'appuie sous/derrière le
  manche** (contre le galbe) ; ce sont **les articulations des doigts**
  (MCP → IPP → IPD) qui déploient les doigts par-dessus le bord pour
  atteindre les cases. Le poignet ne « plonge » pas la main dans le bois
  pour raccourcir un trajet.
  - Contrainte dure : à chaque frame rendue, aucun segment de phalange,
    ni la paume, ni le pouce n'intersecte le solide du manche
    (`_insideNeck` / `_segmentsHitNeck` / `_palmHitsNeck` existants).
  - Post-mortem à respecter (documenté dans `hand3d.js`) : ne JAMAIS
    corriger une collision en déplaçant le poignet en `+Z` ou en
    raccourcissant sa descente en `Y` — les deux cassent l'atteinte des
    cordes graves. La collision se prévient par la **pose de prise**
    (paume au bord, doigts par-dessus), pas par une poussée réactive.
- **H-10 — Courbure naturelle des doigts.** Chaque doigt = 3 phalanges avec
  limites articulaires anatomiques (déjà codées : MCP 0–90°, IPP 0–110°,
  IPD 0–80°, couplage IPD≈⅔·IPP en presse réduite). L'arc de courbure
  visé : **presse en « voûte »** — MCP modérément fléchi, IPP dominant,
  IPD presque droit, dernière phalange quasi perpendiculaire à la touche
  au contact. Interdit : doigt en « crochet » (IPD sur-plié) ou doigt
  tendu raide qui atteint la corde en biais rasant.
  - Critère : au contact, l'angle entre la phalange distale et la normale
    à la touche ≤ 30°.
- **H-11 — Contact au bon endroit.** Le bout du doigt termine sur le point
  de pression H-6 de SA case, à ≤ 1 mm-monde (`CONTACT_EPS`) en régime
  établi. Mesure automatisable : distance `tipWorld() → cible` sur un
  balayage complet du morceau (sweep déjà scripté en dev : moyenne
  actuelle 0,35 wu, max 0,84 — à maintenir sous 1,0).
- **H-12 — Doigts inactifs en repos naturel.** Tout doigt sans cible
  (ni active, ni planted, ni hover) adopte une **pose de repos** : courbure
  légère (MCP ~30–50°, IPP ~45–60°, IPD suiveur), bout de doigt flottant
  5–15 mm au-dessus des cordes, léger éventail latéral (`REST_SPLAY`).
  Jamais : doigt dressé, doigt écrasé sur une corde non jouée, poing serré.
- **H-13 — Répartition des rôles cinématiques.**
  - **Poignet / bras** : porte les déplacements **le long du manche**
    (changements de position = translation X) et les grands changements de
    rangée de cordes (translation Z + déviation).
  - **Doigts** : portent les mouvements **corde à corde** au sein d'une
    position (abduction/yaw plafonnée à 45°) et la presse/relâche.
  - Un déplacement de position (ex. case 5 → case 9) est donc : glissade
    du poignet + les doigts conservent/retrouvent leur courbure — pas des
    doigts qui « s'étirent » sur 4 cases.

### Animation (fluidité, continuité)

- **H-14 — Zéro téléportation.** Tout changement de cible produit un
  mouvement **continu** de chaque articulation. Aucune grandeur rendue
  (position poignet, angles) ne saute d'une frame à l'autre au-delà d'un
  seuil perceptible.
  - Presse / relâche d'un doigt : **40–80 ms** (attaque rapide, ease-out).
  - Déplacement corde à corde d'un doigt : **60–100 ms**.
  - Glissade de position du poignet : **100–180 ms** selon la distance
    (constante de temps actuelle τ=110 ms — bonne base).
  - Anticipation : un doigt `hover` (note à venir < 1,8 s) se place
    au-dessus de sa future case AVANT l'attaque, pour que la presse ne
    soit qu'une flexion courte.
- **H-15 — Zéro oscillation au repos.** À état musical constant (pause, ou
  note tenue), la main est **strictement immobile** : aucune vibration ni
  micro-oscillation.
  - Implémentation de référence : verrou de régime établi existant
    (`_kinSignature` + `_wristConverged` + cible d'easing verrouillée) —
    l'étendre aux DOIGTS : une fois un doigt au contact (ou au repos), ses
    angles sont **gelés** tant que sa cible (case + rôle) ne change pas ;
    on ne re-résout pas le CCD d'un doigt déjà arrivé.
  - Critère : caméra fixe, lecture en pause 5 s → différence d'image
    inter-frames nulle sur la zone main (hors clignotement de case).
- **H-16 — Cadence.** Le pipeline logique (pose + rendu) tient **60 fps
  cible, 30 fps plancher** sur la machine de référence :
  - budget par frame en régime établi : **≤ 2 ms** (le verrou H-15 rend
    cela naturel : coût quasi nul hors transitions) ;
  - budget d'une frame de **transition** (nouvelle note/accord) : ≤ 33 ms
    ponctuel toléré, jamais deux frames consécutives ;
  - les recherches coûteuses (compensation du poignet R11 : classement
    analytique des candidats + vérification CCD bornée) ne s'exécutent
    **que sur changement de note**, jamais par frame tenue.
- **H-17 — 2D alignée sur les mêmes règles.** Le rendu 2D (SVG,
  `hand_viz.html`) partage le même snapshot cinématique ; les corrections
  de naturel (repos H-12, timings H-14) doivent se répercuter dans le
  simulateur partagé (`HandSimulator` / `solveFinger`), pas seulement dans
  le rig 3D, pour que 2D et 3D racontent le même geste.

### Caméras

- **H-18 — Trois modes caméra, zéro effet sur la main.** Caméra **libre**
  (orbite/zoom à la souris — existant), preset **POV** (vue du guitariste,
  manche vertical, main à droite via miroir de présentation) et preset
  **Face** (spectateur, sillet à gauche). Changer de caméra ne modifie
  **jamais** la pose ni la cinématique (garanti aujourd'hui par
  `setCameraView` caméra-seule ; invariant vérifié : position monde du
  bout d'index identique au bit près avant/après bascule — à conserver
  comme test).

---

## 4. Défauts actuels → exigences (traçabilité)

| Défaut observé | Exigence(s) |
|---|---|
| Texte flou en défilement (Slope) | S-1, S-2 |
| Main/doigts traversent le manche | H-9 |
| Courbure des doigts peu naturelle | H-10 |
| Doigts n'appuient pas toujours au bon endroit | H-6, H-11 |
| Doigts inutilisés mal posés | H-12 |
| Saccades / téléportations entre notes | H-13, H-14 |
| Vibrations/oscillations même en pause | H-15 |
| Case pas assez visible à l'allumage (résolu : boîte émissive) | H-8 |
| Numérotation : « 0 » absent au sillet | H-4, H-7 |
| Corde à vide : aucun retour visuel 3D | H-7 |

---

## 5. Validation

### Tests automatisables (harnais dev déjà utilisés en session)

1. **Sweep de contact** (H-11) : dérouler tout le morceau hors temps réel,
   mesurer `dist(tip, cible)` par note active → moyenne < 0,5 wu, max < 1,0.
2. **Sweep de collision** (H-9) : même balayage, `_palmHitsNeck` +
   `_segmentsHitNeck(doigt)` + pouce → 0 frame en intersection.
3. **Sweep de perfs** (H-16) : temps de `update()` par frame → p50 ≤ 2 ms,
   p99 ≤ 33 ms, jamais 2 frames consécutives > 33 ms.
4. **Immobilité** (H-15) : 300 frames à kin constant → Σ|Δangle| = 0 et
   Δposition poignet = 0 après convergence (< 0,5 s).
5. **Invariant caméra** (H-18) : bascule POV↔Face → `tipWorld()` inchangé.
6. **Guards statiques** (suite pytest `test_web_hand_viz*.py`) : présence
   des mécanismes (0 au sillet, cellules par corde, etc.) dans les sources.

### Protocole visuel (captures à joindre aux PR)

- POV et Face : mesure avec accord tenu (case allumée + doigt rouge),
  mesure avec corde à vide (corde + « 0 » allumés), position de repos.
- Slope : capture pendant défilement rapide, zoom sur un chiffre.

---

## 6. Phasage proposé

| Phase | Contenu | Exigences |
|---|---|---|
| **P0 — Stabilité** | Gel des doigts arrivés (fin des oscillations), continuité des transitions, budget frame | H-14, H-15, H-16 |
| **P1 — Justesse** | Pose de prise anti-clipping structurelle (paume au bord, pouce dessous), courbure de presse en voûte, repos naturel, contact ≤ 1 wu partout | H-9, H-10, H-11, H-12, H-13 |
| **P2 — Lisibilité plateau** | Case H-5 exacte, corde à vide + « 0 » (H-7), numérotation 0–22, occlusion zéro | H-4, H-5, H-7, H-8, H-3 |
| **P3 — Slope** | Netteté du texte (indépendant du reste, peut se faire en parallèle) | S-1..S-3 |
| **P4 — Cohérence 2D** | Répercussion des règles dans le simulateur partagé | H-17 |

Chaque phase se termine par les sweeps §5 correspondants + captures.

---

## 7. Points d'ancrage code (état au 2026-07-13)

| Mécanisme | Où |
|---|---|
| Géométrie manche/frettes/cordes 3D | `hand3d.js` → `setGeometry()` (22 frettes forcées en vue dédiée, `fretX` loi 2^(−f/12)) |
| Point de pression 75 % | `hand3d.js` → `_pressX()` |
| Rig articulé (classes) | `Phalange`, `Doigt` (+CCD `fold()`), `Poignet`, `Main`, `AnimationMain` |
| Easing poignet + verrou régime établi | `_easeWristPose`, `_kinSignature`, `_wristEaseTarget`, skip dans `_updateArticulated` |
| Compensation poignet (R11) | `_nudgeWrist` (classement analytique + vérif CCD bornée) — ne s'exécute que sur transition |
| Collision manche | `_insideNeck`, `_segmentHitsNeck` (early-reject Z), `_palmHitsNeck`, `_clampPalmVisualOnly` (cosmétique seulement) |
| Cases allumées | `_updatePlayedFrets` + pool `_playedCells` (boîtes émissives) |
| Numéros de frettes (sprites) | `_addFretNumber` (pré-mirrorés pour POV) |
| Presets caméra + miroir POV | `CAMERA_PRESETS`, `setCameraView`, `_mirror` |
| Bascule 2D/3D dans l'onglet | `hand_viz.html` → `#btn-3d`, `enableHand3d`/`disableHand3d` |
| Simulateur 2D partagé | `hand_viz.html` → `HandSimulator`, `solveFinger`, `buildKinSnapshot` |
| Slope | `slope-renderer.js` (canvas 2D, DPR géré via `setTransform`) |

**Leçons apprises (à ne pas ré-explorer)** — détaillées dans les
commentaires post-mortem de `hand3d.js` :

1. Corriger une collision paume/manche en déplaçant le poignet (+Z ou Y
   raccourci) casse l'atteinte des cordes graves.
2. Estimer l'atteignabilité par distance euclidienne pure (sans CCD) fait
   sauter la compensation du poignet là où elle est nécessaire.
3. Re-viser chaque frame la cible d'easing « fraîche » pendant une note
   tenue fait osciller compensation ↔ baseline sans converger (30–90 ms
   par frame) : verrouiller la cible une fois la compensation trouvée,
   ne la rafraîchir que sur changement de signature.
