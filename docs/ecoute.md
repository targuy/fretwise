# FretWise — Écoute de la guitare

> Architecture du module d'écoute : capter le jeu réel de la guitare et s'en
> servir pour accorder, noter le jeu contre la partition, et travailler avec un
> DAW. Ce document est la référence de conception ; l'état d'avancement est en
> fin de fichier.

---

## 1. Sources d'entrée — une seule chaîne, générique

Toutes les sources passent par le même chemin, parce qu'elles arrivent toutes de
la même façon côté OS :

| Source | Ce que voit le navigateur |
|---|---|
| Micro acoustique sur la carte son du PC | une entrée audio |
| Interface audio USB (Valeton GP-180, boîtier d'enregistrement…) | une entrée audio |
| Micro de webcam | une entrée audio |

**Rien dans le code ne connaît un modèle d'appareil.** Le GP-180 n'est pas traité
autrement qu'une webcam : il est cité comme cas d'usage, jamais comme cas
particulier. (À ne pas confondre avec `fretwise.rig` / `control_surface.py`, qui
pilotent le GP-180 en **MIDI** pour changer de patch — c'est un sujet disjoint.)

### Capture dans le navigateur

Décision : la capture se fait côté navigateur (`getUserMedia`), pas côté serveur.

- zéro installation, et couvre les trois sources ci-dessus telles quelles ;
- `localhost` est un *secure context*, donc pas d'HTTPS à monter ;
- fonctionne depuis un autre appareil du réseau (tablette sur le pupitre).

Limite assumée : Chrome/Windows passe par WASAPI **partagé**, soit ~20–40 ms
d'aller-retour, et pas d'ASIO. C'est sans conséquence pour l'accordeur, et
absorbé par la calibration pour la notation du jeu. Ça ne suffirait pas pour du
monitoring temps réel — d'où le chemin natif optionnel prévu en phase 3
(`sounddevice`/PortAudio, WASAPI exclusive ou ASIO).

Trois contraintes sont posées à `false` dans `getUserMedia`, et c'est le point
qui décide de tout le reste :

```js
{ echoCancellation: false, noiseSuppression: false, autoGainControl: false }
```

Par défaut le navigateur applique un traitement réglé pour la voix. Sur une
guitare, la réduction de bruit mange les fins de notes et le gain automatique
fait dériver le niveau en plein sustain : le détecteur de hauteur devient
inutilisable. Quand le navigateur impose quand même ce traitement (certains
pilotes le forcent), `captureInfo().processing` le signale et l'interface
avertit au lieu d'afficher des mesures fausses.

---

## 2. Couches

```
navigateur                                          serveur (Python)
──────────                                          ────────────────
getUserMedia ─→ AudioWorklet « fretwise-pitch »
                  │  YIN : f0 + confiance + RMS      fretwise.listening.pitch
                  │  (~47 analyses/s)         ⇠ parité ⇢  (référence testée)
                  ▼
             audio-input.js  (périphériques, permission, abonnements)
                  │
      ┌───────────┴────────────┐
      ▼                        ▼
  tuner.js                 [P1] notation du jeu ─ WebSocket ─→ matcher Python
  (accordeur)                                                  (aligné sur la
                                                                partition)
```

### 2.1 DSP dans un AudioWorklet

L'analyse tourne ~47 fois par seconde sur des fenêtres de 64 ms. Sur le main
thread elle entrerait en concurrence avec le rendu de la partition : c'est le
rendu qui saccaderait, ou l'analyse qui sauterait des trames — immédiatement
visible sur une aiguille d'accordeur.

Le nœud est câblé `source → worklet → gain(0) → destination`. Le gain nul évite
le larsen (renvoyer un micro acoustique dans les haut-parleurs suffit à faire
hurler la pièce) et garantit que le worklet est bien tiré par le graphe.

### 2.2 Détection de hauteur — YIN, grossier puis fin

Implémentation de référence : [`fretwise/listening/pitch.py`](../src/fretwise/listening/pitch.py).
Miroir navigateur : [`worklets/pitch-worklet.js`](../src/fretwise/web/static/js/worklets/pitch-worklet.js).

1. **anti-repliement + décimation vers ~12 kHz** — les fondamentales de guitare
   plafonnent vers 1,4 kHz ; garder 48 kHz ne fait que rendre la fonction de
   différence, en O(W·τ), inutilement chère ;
2. **YIN sur le signal décimé** — différence, normalisation par la moyenne
   cumulative, seuil absolu, premier minimum local. Prendre le *premier* τ sous
   le seuil et non le plus profond est ce qui protège des erreurs d'octave
   basse ;
3. **raffinement au taux d'origine**, ±(DECIM+1) échantillons, interpolation
   parabolique. À 12 kHz, un échantillon de τ autour du E2 vaut ~18 cents —
   inutilisable pour un accordeur ; après raffinement à 48 kHz on passe sous le
   cent.

Garde-fou hors bande : la recherche démarre **sous** τ_min. Si le signal est
déjà périodique à un décalage plus court que ce que `F_MAX_HZ` autorise, sa
fondamentale est hors bande et on ne renvoie rien — sinon un sinus à 2 kHz
serait affiché à 1 kHz, une octave d'erreur annoncée avec aplomb.

### 2.3 Datation d'attaque (second rôle du worklet)

Le message d'analyse arrive toutes les 21 ms : sans commune mesure avec ce
qu'exige un chiffrage de latence. Le worklet accepte donc un message `arm` qui
arme un détecteur de transitoire scrutant **chaque échantillon**, et répond
`{ type: 'onset', time }` où `time = currentTime + i / sampleRate` — précis à
l'échantillon, soit ~0,02 ms.

Le seuil est relatif au plancher de bruit mesuré depuis l'armement (×8, borné à
[0,02 ; 0,5]), pas figé : entre un micro à condensateur dans une pièce calme et
une entrée d'interface avec un ampli en veille, le plancher varie de plusieurs
dizaines de dB.

Les deux flux partagent le même port ; `audio-input.js` les trie sur le champ
`type`, pour qu'aucun abonné n'ait à reconnaître un message à la forme de ses
champs.

### 2.4 Contrat de parité Python ↔ JS

Même règle que la parité `fretwise.dataset.features` ↔ `fretwise.ml` : le
comportement est épinglé côté Python par
[`tests/test_listening_pitch.py`](../tests/test_listening_pitch.py), et le
worklet reprend les mêmes constantes et les mêmes étapes dans le même ordre.
**Toute évolution algorithmique commence par le Python, puis est répercutée
dans le worklet.**

Parité mesurée sur signaux synthétiques (sinus, empilements harmoniques,
fondamentale manquante, corde pincée avec enveloppe, bruit, silence, hors
bande) : **écart maximal 0,0000 cent**, mêmes décisions de voisement.

---

## 3. Fonctionnalité 1 — Accordeur ✅

[`tuner.js`](../src/fretwise/web/static/js/tuner.js) — page autonome, même
schéma que `training.js` (construit son DOM, `showPage('tuner')` la bascule).

- **Deux modes de cible** : « Morceau » vise les cordes à vide de la piste
  ouverte — l'accordage réel arrive de `/api/tracks`, drop D et 7-cordes
  compris — ou « Chromatique », le demi-ton tempéré le plus proche.
- **Diapason réglable** (415–466 Hz), mémorisé.
- **Stabilité d'affichage** : médiane glissante sur 7 trames retenues (rejette
  les sauts d'octave isolés là où une moyenne les étalerait), confiance minimale
  0,85, maintien 600 ms avant retour au repos.
- **Suivi de corde avec hystérésis** : la cible ne change que si l'écart dépasse
  175 cents, sinon l'affichage saute de corde en corde pendant qu'on remonte une
  corde très détendue. Comparaison en cents et non en Hz — à 82 Hz trois hertz
  sont un demi-ton, à 330 Hz ils sont marginaux. Un clic sur une pastille
  verrouille la cible.
- **Vu-mètre en dB** et témoin de saturation : en échelle linéaire un signal
  parfaitement exploitable occupe 3 % de la barre et le vu-mètre a l'air mort.
- Quitter la page **libère l'entrée** : une interface tenue ouverte reste
  indisponible pour le DAW, et l'onglet garderait son témoin micro allumé.

---

## 4. Fonctionnalité 2 — Écoute et notation du jeu ✅ (mode guidé)

Jouer le morceau à l'écran, détecter les erreurs, les montrer, donner un score.
Bouton « Écouter mon jeu » dans la barre d'outils du lecteur.

### Où vit la décision musicale

Côté Python — [`fretwise/listening/`](../src/fretwise/listening/) —, alimenté
par WebSocket depuis le navigateur. Motif : la logique est testable dans la
suite existante et rejouable hors ligne sur un fichier, conformément à la règle
« logique dans `src/fretwise/`, wrapper fin ». Le navigateur ne garde que ce que
le serveur ne *peut pas* faire : les notes attendues, la conversion d'horloges,
la compensation de latence.

### Chaîne

```
trames (worklet, 8 ms)  →  notes jouées  →  appariement  →  score
   frames.py                 notes.py        matching.py    matching.py
```

`frames.py` est le miroir hors ligne du worklet : il redécoupe un signal comme
le navigateur le ferait. C'est lui qui rend la chaîne entière testable sur
fichier — les tests de bout en bout partent d'un signal synthétisé, pas de
trames fabriquées.

### Saut d'analyse : 8 ms, pas 21

L'accordeur se contente de 21 ms. Dater un jeu à 21 ms près rendrait
indiscernables « en place » et « approximatif » : à 120 BPM une double-croche ne
dure que 125 ms.

### Le retard d'analyse dépend de la hauteur

Le point le moins évident de tout le module. La fenêtre d'analyse fait 64 ms et
YIN n'accroche qu'une fois qu'elle contient assez de **périodes** de la nouvelle
note. Mesuré sur cordes pincées synthétiques :

| note | retard |
|---|---|
| mi grave (82 Hz) | 60 ms |
| sol (196 Hz) | 36 ms |
| do5 (523 Hz) | 28 ms |

Une correction constante laisserait donc un riff sur cordes graves
« systématiquement en retard » et un solo aigu « en avance ». Modèle retenu,
ajusté à quatre valeurs de saut (résidu ≤ 3 ms, soit moins d'un saut) :

```
retard = 17 ms + saut/2 + 3,1 période
```

### Notes répétées : c'est l'enveloppe qui tranche

Deux croches sur la même corde donnent une hauteur rigoureusement constante :
aucune segmentation par hauteur ne peut les séparer. Une ré-attaque est
détectée par la remontée du niveau (×1,7) au-dessus du creux des 100 ms
précédentes. Cette rétrospective doit dépasser la fenêtre d'analyse de 64 ms :
plus courte, le creux de référence est lui-même pris dans la montée que la
fenêtre lisse, et le rapport mesuré s'effondre sous le seuil.

### On raisonne par événement, pas par note

Les notes attendues simultanées sont regroupées : un accord plaqué est *un*
événement à cinq hauteurs possibles, validé si l'une d'elles est reconnue. La
détection étant monophonique, compter cinq notes manquées pour un accord
correctement plaqué serait faux — et décourageant. C'est la réponse pragmatique
à la polyphonie ; la vérification d'énergie aux partiels attendus reste la piste
si le besoin de finesse apparaît.

Les fenêtres d'appariement ne se chevauchent jamais : la tolérance nominale
(150 ms) est rabotée à la moitié de l'écart aux événements voisins. Sans cela,
sur un trait rapide, une note captée satisferait deux événements consécutifs et
la note réellement manquée passerait inaperçue.

### Verdicts et note

Par événement : `correct`, `wrong_pitch`, `missed`, `extra`. Agrégats : justesse
en %, RMS de l'écart de date, **biais** de date, écart moyen au tempérament.

Le biais est séparé de la dispersion à dessein : ils appellent des conseils
opposés. Systématiquement en retard se corrige en anticipant, imprécis se
corrige en ralentissant. Une moyenne unique confondrait les deux.

Note finale = 70 % justesse + 30 % rythme, moins un forfait plafonné à 20 points
pour les notes en trop — un doigt qui traîne ou une corde mal étouffée, pas une
faute aussi grave qu'une note ratée.

### Protocole WebSocket — `/ws/listen`

```
client → { "type": "start",  "notes": [...], "hop_sec": 0.008 }
client → { "type": "frames", "frames": [[t, hz, conf, rms, voiced], ...] }
client → { "type": "stop" }
serveur → ready | verdicts | score | error
```

Les trames sont des tableaux compacts et non des objets nommés : à 125 trames
par seconde, les noms de champs répétés pèseraient plus que les données. Elles
arrivent **déjà en position-morceau, latence compensée** — le client est seul à
connaître son horloge de capture, sa position de playback et la latence
calibrée de son périphérique.

Conversion d'horloge, côté client : on ne compare pas deux horloges qui n'ont
pas d'origine commune, on retranche l'**âge** de la trame (mesuré sur l'horloge
de capture) à la position courante du playback, puis la latence.

### Notes attendues et carte de tempo

`PlaybackEngine.songSecForOnsetBeats()` place chaque note attendue sur la carte
de tempo réelle du playback. Un tempo moyen (ce que fait la charge utile de la
visualisation de main) dériverait d'un temps entier sur un morceau à changement
de tempo — et la prise en serait tenue pour responsable.

### Affichage

Panneau flottant : score en direct, liste des fautes (les plus récentes en
tête), clic pour sauter à l'endroit fautif. Sur la partition, une couche DOM de
marqueurs positionnée via `renderer.getCursorLine(onset)` — couche superposée
plutôt que dessin dans le renderer, parce que la partition se rend en quatre
représentations et qu'y greffer un état de notation multiplierait par quatre la
surface à maintenir pour le même résultat visuel.

---

## 4bis. Calibration de latence ✅

[`latency.js`](../src/fretwise/web/static/js/latency.js), commandée depuis la
page accordeur.

### Pourquoi l'aller-retour, et pas la seule latence d'entrée

C'est le point qui décide du protocole. En mode guidé, le joueur se cale sur ce
qu'il **entend** :

```
note prévue à la position t
   → atteint ses oreilles à  t + L_sortie
   → il attaque la corde à   t + L_sortie
   → on la date à            t + L_sortie + L_entrée  =  t + aller-retour
```

Retrancher l'aller-retour complet de l'horodatage redonne donc exactement la
position voulue : **une mesure, une correction**, sans avoir à séparer entrée et
sortie ni à faire confiance à `AudioContext.outputLatency` (souvent à 0 selon
les pilotes ; il est relevé, mais à titre indicatif).

### Protocole

Sept clics brefs (4 ms de bruit large bande à attaque franche — large bande
parce qu'un creux de réponse du haut-parleur, de la pièce ou du micro peut
avaler une bande étroite), émis sur l'AudioContext **de la capture**. Deux
contextes ont deux horloges indépendantes : comparer une date d'émission de
l'un à une date de captation de l'autre ne mesurerait rien.

Retenu : la **médiane**, pas la moyenne — un seul essai pollué par un bruit de
chaise décalerait une moyenne, alors qu'il glisse en bout de tri sans effet. La
gigue rapportée est l'écart absolu médian ; au-delà de ~5 ms l'interface le dit
au lieu de laisser croire à une mesure fiable. Un essai muet ne condamne pas la
série : le verdict tombe sur le nombre d'essais exploitables (majorité requise).

La mesure est stockée **par périphérique** : la latence est une propriété du
pilote, et une interface USB dédiée n'a rien de comparable au micro intégré
d'une webcam. Fermeture de boucle à la charge de l'utilisateur — micro devant
les haut-parleurs, ou sortie de l'interface renvoyée vers son entrée.

Consommation en P1 : `storedLatency(deviceId)`.

---

## 5. Fonctionnalité 3 — DAW (P3, à faire)

Le navigateur ne peut pas parler à un DAW. Tout se passe côté Python, où `mido`
et `python-rtmidi` sont déjà des dépendances et déjà utilisés.

**Rôle retenu : FretWise esclave du DAW.** On lance le transport du DAW, la
partition défile en synchro, on enregistre la guitare dans le DAW. FretWise
reçoit MIDI Clock / MTC via un port virtuel (loopMIDI sous Windows) et cale son
curseur dessus.

Complémentaire : enregistrement WAV local + export de la carte de tempo, pour
les prises à glisser dans le DAW. Le routage *audio* vers le DAW reste du
ressort d'un câble virtuel (VB-Audio / Voicemeeter) — documentation, pas du
code.

---

## 6. État

| Phase | Contenu | État |
|---|---|---|
| P0 | Capture navigateur, worklet YIN, référence Python + parité, accordeur | ✅ fait |
| P0b | Calibration de latence (clic recapté, offset par périphérique) | ✅ fait |
| P1 | Segmentation + appariement Python, WebSocket, notation en mode guidé | ✅ fait |
| P2 | Mode suivi (DTW en ligne), historique de progression | à faire |
| P3 | DAW : esclave MIDI Clock/MTC, enregistrement WAV, backing track | à faire |

**Vérifié en P0** : 56 tests Python verts ; parité worklet ↔ référence à
0,0000 cent sur 9 signaux synthétiques ; worklet exécuté dans Chrome via
`OfflineAudioContext` — 196,00000 Hz détecté sur un sinus à 196 Hz, 44 analyses
en 1 s, confiance 0,999.

**Vérifié en P0b** : datation d'attaque mesurée contre une vérité terrain
(`DelayNode` de délai exact, rendu hors-ligne) — 0,0000 ms sans délai,
37,5000 ms pour 37,5 ms, 75,0000 ms pour 75 ms, une seule attaque par armement.
Erreur nulle à la résolution affichée.

**Vérifié en P1** : 115 tests Python, dont quatre de bout en bout partant d'un
signal synthétisé — prise fidèle notée > 90 avec un biais de date < 15 ms,
fausse note pointée à la bonne place, note sautée signalée manquante, jeu
précipité rendu par un biais négatif. Transport éprouvé depuis Chrome sur une
prise simulée : verdicts rendus **en cours de prise** (4 messages successifs et
non un bilan groupé), fausse note identifiée (attendu 57, joué 58) avec les
`note_ids` qu'attend le marquage.

**Non vérifié** : la capture micro réelle de bout en bout — chaîne complète
guitare → verdicts —, qui demande un navigateur avec permission accordée et un
instrument branché.
