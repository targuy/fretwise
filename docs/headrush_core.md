# HeadRush Core — concevoir, générer et activer un rig par chanson

> Document de conception. Successeur du chemin GP-180 (`src/fretwise/gears/`).
> Convention de fiabilité, reprise des pages Notion :
> **FAIT** = vérifié sur l'appareil ou dans le code · **HYPOTHÈSE** = déduit, à tester ·
> **RECO** = recommandation de conception.
>
> État du matériel au moment de la rédaction : firmware `5.1.0.2a63755`,
> `DeviceName = HeadRush Core_3570`, 118 rigs, aucun `loadedProgMIDICC` assigné.

---

## 1. L'idée en une page

FretWise connaît déjà 1982 chansons (fiches `data/gears/`) et leurs partitions.
Le HeadRush Core expose, en local et sans authentification, **une API de contrôle
complète** qui permet de lire son catalogue, de construire une chaîne de blocs,
d'en régler chaque paramètre, de sauvegarder le rig et de lui assigner un numéro
de Program Change. Le chaînon manquant entre les deux n'est donc plus technique.

Le workflow cible, pour une chanson :

```
partition .gp  ─┐
                ├─►  tone.intent.v1     (LLM : intention musicale, par section)
fiche gears     ┘         │                 aucun nom de modèle, aucune valeur numérique
                          ▼
                    compilateur          (déterministe : catalogue live du device)
                          │
                          ▼
                device.binding.v1        (L2 : 14 slots, params en unités d'affichage,
                          │                   scènes, MIDI PROG)
                          ▼
                     push HTTP            (PUT/POST sur /api/v1, rig bac à sable)
                          │
                          ▼
                device.state.v1          (L3 : relecture, diff, dérive)
                          │
                          ▼
              activation : PC MIDI au pied  ·  loadRig() en HTTP depuis FretWise
```

**Le pivot de conception :** le LLM n'écrit jamais un nom de bloc ni un nombre.
Il écrit une *intention* dans un vocabulaire fermé. Un compilateur déterministe,
adossé aux énumérations lues en direct sur l'appareil, produit les noms et les
valeurs. C'est ce qui sépare une fiche qu'un humain relit d'un document qui pilote
un instrument.

---

## 2. L'API du Core — ce qui est établi

### 2.1 Surface

**FAIT** — Le Core sert un SPA React « Headrush Remote Editor » sur
`http://headrushcore.local/`, au-dessus d'une API d'arbre d'objets :

```
GET  /api/v1/subtree/<path>              # dump meta + valeurs d'un sous-arbre
GET  /api/v1/object-meta/<path>          # schéma : type, minimum, maximum, x-options
GET  /api/v1/object-properties/<path>    # valeurs courantes
PUT  /api/v1/object-properties/<path>    # écriture      {"Prop": value}
POST /api/v1/object-method/<path>/<m>    # appel méthode {"arguments":[...]}
                                         #   -> {"methodReturnValue": ...}
POST /api/auth                           # pairDevice()
WS   ws://headrushcore.local/            # objectAdd / propertyAdd / propertyRemove
```

**FAIT** — Les GET passent sans aucune authentification. Aucun header
`Authorization` n'existe dans tout le bundle SPA ; `setObjectProperties` est un PUT nu.

**FAIT — Les écritures aussi.** Testé le 2026-09-10 sur `#FW - SCRATCH` :
`PUT /object-properties/Evil/API/Rigs {"loadedProgMIDICC": 112}` renvoie
**HTTP 200**, corps vide, sans le moindre en-tête d'authentification, et
`POST /object-method/…/saveRig` renvoie `true`. **`POST /api/auth` est inutile** —
il n'y a pas d'appairage à faire. Ce qui confirme du même coup le risque du §5.5 :
n'importe quoi sur le réseau peut réécrire la bibliothèque.

### 2.6 La recette d'écriture, et ses deux pièges

**FAIT — Un `PUT` seul n'est que de la RAM. `saveRig()` commite.**
Séquence mesurée :

| Étape | `loadedProgMIDICC` | Survit au changement de rig |
|---|---|---|
| `PUT {"loadedProgMIDICC": 112}` | 112 (visible à l'écran : « 113 ») | **non** — revient à −1 |
| `PUT` **puis** `saveRig()` | 112 | **oui** |

Toute mutation doit donc être suivie d'un `saveRig()` explicite. Un `PUT` isolé
donne une interface qui affiche la bonne valeur et un rig qui ne la garde pas —
le pire des deux mondes, parce que rien ne signale l'erreur.

**PIÈGE 1 — `dirty` ne couvre pas tout.** Il passe bien à `True` sur une
modification de chaîne (`setModuleTypeInternal`), mais **est resté à `False` sur
tout le cycle `PUT loadedProgMIDICC` → `saveRig()`**, c'est-à-dire avec une
modification non commitée en attente. Un writer ne peut donc pas s'appuyer sur
`dirty` pour décider s'il doit sauvegarder : il doit sauvegarder systématiquement.

**PIÈGE 3 — une modification en attente BLOQUE le chargement de rig, par un
dialogue modal.** `loadRigConfirm()` renvoie sans erreur mais **ne charge rien**
tant que `RigSaveDialog.displayDialog` est à `true` ; l'écran affiche
Cancel / Discard / Save New Rig / Save. Le piège est vicieux : les lectures
suivantes retournent l'état de l'**ancien** rig, et un script naïf en conclut ce
qu'il veut. *C'est exactement l'erreur commise pendant la session de test — un
chargement bloqué a été lu comme la preuve que les modifications de chaîne
persistaient sans `saveRig()`. Elles ne persistent pas.*

**RECO** — Tout writer doit, avant et après chaque `loadRig`, lire
`/Evil/API/RigSaveDialog.displayDialog` et le résoudre explicitement :
`discard()` pour abandonner, `save()` pour committer. Ne jamais supposer qu'un
`loadRigConfirm` a abouti — relire `loadedID` et comparer.

### 2.7 `setModuleTypeInternal` — deux comportements à connaître

**FAIT — Poser un type déjà présent DÉPLACE l'instance, il n'en crée pas une seconde.**
Découvert en gâchant une campagne de mesure : la chaîne contenait `Amp` en slot 3 ;
un `setModuleTypeInternal(9, "Amp")` n'a pas ajouté un second ampli en slot 10, il a
**déménagé** celui du slot 3. Vider ensuite le slot 10 a donc supprimé l'ampli du rig,
silencieusement.
**RECO** — Pour une deuxième instance d'un type, utiliser explicitement le jumeau
(`"Amp 2"`, `"BBD Delay 2"`…). Un builder doit vérifier après chaque pose que les
autres slots n'ont pas bougé — `GET Chain` coûte une requête.

**FAIT — `RigSaveDialog.discard()` ne laisse AUCUN rig chargé.** Après un `discard`,
`loadedID` est `""`, `loadedName` est vide et la chaîne est vide. Il faut enchaîner
un `loadRig` explicite. Ne pas le faire donne l'impression que le rig a été détruit.

#### L'argument de slot est 0-indexé

**FAIT — vérifié deux fois.** `setModuleTypeInternal(n, type)` écrit
`ModuleType(n+1)` :

| Appel | Slot réellement occupé |
|---|---|
| `setModuleTypeInternal(1, Gate)` | slot **2** |
| `setModuleTypeInternal(9, Volume)` | slot **10** |
| `setModuleTypeInternal(11, "Amp 2")` | slot **12** |

Les blocs déjà en place n'ont pas bougé : c'est bien une écriture à l'index, pas
une insertion. **Une confusion 0/1 décalerait tout le gabarit FW-14 d'un cran et
rendrait fausse toute la carte CC 75-88** — le CC est indexé sur le slot *physique*
(CC = 74 + slot), donc sur `n+1`.

### 2.8 `AutoAmpCab` et `AutoAssignments` n'affectent pas le chemin API

**FAIT — testé, contrairement à ce que ce document affirmait initialement.**
Les deux réglages sont à `true` sur l'appareil, et sur trois modifications de
chaîne par l'API (`Gate`, `Volume`, `Amp 2`) :

- **aucune** assignation de footswitch n'a été réécrite (`Module1..10` et
  `FootSwitchText1..10` inchangés) ;
- **aucun** Cab n'a été ajouté automatiquement en posant un ampli.

Seul `ModuleList1..10` a évolué — c'est la liste des cibles assignables, dérivée
du contenu de la chaîne (`['Unassigned', 'Looper', 'Practice Tool', 'Drum Machine',
'Gate', 'Amp', 'Cab', 'Tempo', 'Metronome', 'Signal Chain', 'Mic Dry Out',
'Ext Amp', 'Hold Functions', 'MIDI Out']`).

**Ces automatismes appartiennent donc au flux tactile, pas à l'API.** L'exigence
« refuser de générer tant qu'ils sont à `true` » (§5.1) tombe.

**FAIT** — Les footswitches ciblent un module **par nom** (`Module6 = "Amp"`,
`Module7 = "Cab"`), pas par position de slot. C'est l'indirection qui rend
CC 49-53 stable au réordonnancement, là où CC 75-88 ne l'est pas (§5.1).

**PIÈGE 2 — `availableProgMIDICC` est relatif au rig chargé, pas global.**
Le rig chargé voit **son propre** Program Change comme disponible :

| Rig chargé | `len(available)` | 112 dedans ? |
|---|---|---|
| `#FW - SCRATCH` (qui détient PC 112) | 128 | **oui** |
| `Accoustique` | 127 | non |

Calculer « quels PC sont pris » depuis le seul rig chargé donne donc toujours un
faux positif sur lui-même. C'est un argument de plus pour que `allocation.json`
côté FretWise soit la source de vérité (§4.2) plutôt que l'appareil.

### 2.2 Objets qui comptent

| Chemin | Rôle |
|---|---|
| `/Evil/API/Rigs` | inventaire, `loadRig`, `saveRigAs`, `makeNewRig`, `deleteRig`, **`loadedProgMIDICC` (writable)** |
| `/Evil/API/Blocks` | `ModuleTypes` (278), 21 catégories, `categoryBlocks`, `categoryBlocksFlags`, `serializeBlock`/`deserializeBlock`, `blockPresets` |
| `/Evil/Engine/Patch/Chain` | `ModuleType1..14`, `Routing`, `Tails`, `CanDouble1..14`, `setModuleTypeInternal(slot, type)` |
| `/Evil/Engine/Patch/<Bloc>` | 282 objets, un par instance de bloc — **tous les paramètres** |
| `/Evil/Engine/Patch/Rig` | `PresetName`, `Tempo`, `TempoFromMaster`, `MIDIOut`, `ExtAmp` |
| `/Evil/Engine/FootSwitch` | modèle de scènes complet (972 propriétés), `FootSwitchText/On/Colour 1..10` |
| `/Evil/Engine/Settings/Midi` | `Channel`, `ReceiveProgramChange`, `MBCIn`, `MIDIThrough` |
| `/Evil/Engine/Settings/General` | **`AutoAmpCab`, `AutoAssignments`** — les deux à `true` en live |
| `/Evil/Engine/CPUMeter` | `CPUTimeSmoothed` |
| `/Evil/Gui` | `AppVersion`, `DeviceName` — l'ancre de version du contrat |
| `/Evil/API/Setlists` | `getSetlist`, `saveSetlist`, `loadSetlist` |
| `/Evil/Engine/MIDIOutCtrl` | le Core **émet** 5 messages au chargement d'un rig |

### 2.3 Trois faits contre-intuitifs

**FAIT — Le compteur CPU s'affiche à 200 × la valeur lue.**
`object-meta` déclare `CPUTimeSmoothed {minimum: 0, maximum: 200, format: "%.0f %%"}`.
Sous la convention de normalisation générale du device, l'affichage est
`min + (max−min)·x`. Relevé live 0,295 puis 0,33 → **59 % puis 66 %** pour un rig de
9 blocs. Il ne reste donc ~35-40 points de budget, pas 70. Tout le dimensionnement
du générateur en dépend. *(Une observation de l'écran tranche définitivement — cf. §7.)*

**FAIT — Le suffixe « X 2 » désigne la deuxième instance du type dans la chaîne,
pas le canal droit.** 278 = 1 `Empty Slot` + 139 bases + 138 jumeaux ; `FX-Loop` est
le seul type sans jumeau. Le doublage stéréo, lui, utilise les propriétés suffixées
`2` du *même* objet (`Cab.CabType` / `Cab.CabType2`), et `Cab` possède **en plus** un
objet frère `Cab_2`. Conséquence : **plafond structurel de 2 instances par type de bloc**.

**FAIT — Les amplis ne sont pas des blocs.** Le bloc `Amp` porte `Type`, une
énumération de **53 modèles** (`59 Tweed Deluxe`, `64 Black Lux Vib`, `82 Lead 800`…) ;
`ReValver_Amp.Type` en porte 48, `Cab.CabType` 15, `Cab.MicType` 8,
`Eleven_Reverb.Mode` 25. Le vocabulaire réel est donc bien plus large que les
145 blocs sélectionnables, et il est **entièrement publié par `object-meta`** sous
`x-options.strings` (394 énumérations, 3779 libellés).

### 2.4 Le catalogue est dans l'appareil

**FAIT** — `object-meta` publie pour chaque paramètre : `type`, `minimum`, `maximum`,
`x-options.strings` (énumérations), `x-options.format` (unité d'affichage),
`x-options.grid` (pas), `x-options.default`, `x-options.normalizeAlgo`.
139 blocs, 7579 propriétés, 3831 flottants continus.

**RECO** — Remplacer `gp180_catalog.py` (qui scrape au regex un dump markdown Notion)
par un **artefact généré depuis l'appareil**, versionné sur `Gui.AppVersion` :
`data/devices/headrush-core/catalog/5.1.0.2a63755.json`.
Le catalogue Notion actuel ne contient **aucun** nom de bloc réel du Core : il
propose `Blue Comp`, `Tube Scream`, `Klone`, `Cry Baby Wah`, `4x12 Greenback` —
aucun n'existe, et il confond blocs et modèles d'ampli.

**RECO** — Injecter le catalogue au LLM comme **`enum` de JSON Schema** dans
`output_schema` (mécanisme déjà présent dans `llm.request_json`), réduit aux
catégories des rôles demandés (~40 entrées), jamais comme prose markdown.
Le catalogue complet fait 1,5 Mo : il ne peut pas entrer dans un prompt, et une
liste en prose est une suggestion, pas une contrainte.

### 2.5 Paramètres : normalisé ↔ affiché

**FAIT** — Tous les paramètres continus sont des flottants **0.0–1.0**.
`minimum`/`maximum` sont en unités d'affichage, mais `x-options.default` est
normalisé (piège : `BBD Delay` min 32, max 1520, default 0.180107) — un clamp naïf
sur min/max laisse donc tout passer.

**FAIT** — Les 11 algorithmes de conversion sont extraits verbatim du bundle
(tables `xf`/`Af`) : `Linear, Db, Volume, DelayRatio, TimeBiSquared, Squared,
Exponential, MixerGain, H3Volume, AllenHeathFaderVolume, H3ReverbTime`.
Vérifications numériques : `Rig.Tempo 0.4285714 → 120.00 BPM` (linéaire 30–240),
`BBD Delay 0.18010753 → 300.0 ms`, `PreGain 0.5 → 0.0 dB`.
`Lf()` applique `Math.fround` (float32), `If()` non — les deux doivent être reproduits.

**FAIT — Refuser d'écrire tout paramètre dont `normalizeAlgo == 3` (`DelayRatio`).**
L'algo 3 est déclaré dans l'enum du bundle mais n'a **aucune entrée** dans la table
de dénormalisation `Af` ; le JS retombe silencieusement sur `Af[0]` = Linear. L'éditeur
officiel HeadRush affiche donc lui-même ces paramètres avec une courbe probablement fausse.
**Mesuré depuis le catalogue généré : zéro paramètre ne l'utilise sur le firmware
5.1.0.2a63755.** Le garde-fou coûte donc une ligne et ne bloque rien aujourd'hui —
c'est de l'assurance contre un firmware futur, pas une contrainte actuelle.

**FAIT — Seules 5 courbes sur 11 servent réellement.** Distribution mesurée sur les
6661 paramètres du catalogue :

| `normalizeAlgo` | Paramètres |
|---|---|
| absent = **Linear** | 5691 |
| 6 **Exponential** | 906 |
| 5 **Squared** | 58 |
| 8 **H3Volume** | 4 |
| 10 **H3ReverbTime** | 2 |
| tous les autres (Db, Volume, DelayRatio, TimeBiSquared, MixerGain, AllenHeath…) | **0** |

`params.py` doit donc implémenter les 11 pour rester fidèle au firmware, mais le test
de parité ne peut en exercer que 5 sur des données réelles. Les six autres restent
non couvertes tant qu'un firmware ne les emploie pas — à documenter comme tel plutôt
qu'à faire passer pour testées.

**RECO** — Les fiches stockent des valeurs **en unités d'affichage typées**
(`{value: 300, unit: "ms"}`, ou le libellé exact pour une énumération), jamais le
flottant normalisé. Diff git lisible ; et si `normalizeAlgo` change entre firmwares,
une valeur en dB reste juste là où `0.412` ne l'est plus.
Le writer convertit au moment du PUT et **vérifie en boucle fermée** :
PUT → GET → redénormalisation → `assert |écart| <= grid`.

---

## 3. Partie musicale

### 3.1 Une chanson n'est pas un son

**RECO — Une chanson = un rig ; une section = une scène ; un stomp = un bypass.**

| Levier | Coupe les queues ? | Unité |
|---|---|---|
| **RIG** | **non** (FAIT — testé, cf. ci-dessous) | persistance : nom = `gears_key`, numéro = `loadedProgMIDICC` |
| **SCÈNE** | non | musicale : la section du morceau |
| **BYPASS de bloc** | non | gestuelle : un stomp dans une section |
| **DOUBLAGE A/B** | non (**FAIT** — testé) | deux amplis / deux baffles dans un seul rig |

**~~FAIT — changer de rig coupe les queues.~~ RÉFUTÉ le 2026-09-10.**
Affirmation héritée de la base Notion, reprise sans test, et **fausse**. Protocole :
accord tenu sur un rig à `BBD Delay` (feedback 68 %) + `Eleven Reverb` (decay 80 %),
puis `loadRigConfirm` vers un autre rig pendant que ça résonne. **La queue a décru
normalement**, deux fois, et le chargement a été vérifié (`loadedID` effectivement
changé, chaîne du rig destination lue). Refait avec `Chain.Tails = no` sur le rig
source : **queue toujours préservée**.

*Nuance non tranchée :* `Chain.Tails` est une propriété **par rig**, et le rig
destination avait `Tails = yes`. Il se peut que ce soit le réglage du rig **entrant**
qui autorise la queue sortante à finir. Le tester demanderait un second rig bac à
sable avec `Tails = no`.

**Ce que ça change :** l'argument principal derrière « une chanson = un rig » tombe.
Il reste la **latence** de chargement, qui elle est réelle et mesurée
(0,16 s à 2,86 s pour l'aller-retour HTTP seul), et le fait qu'un rig est l'unité de
persistance. Mais la contrainte « 1 seul NAM / 1 seul C-Verb par rig » cesse d'être
un mur : un morceau qui a besoin de deux captures peut passer par deux rigs sans
sacrifier l'ambiance.

**FAIT — Il y a quatre leviers, pas trois.** `Chain.CanDouble4 = true` (slot ampli),
`CanDouble6 = true` (slot IR) sur le rig live ; le bloc `Amp` expose `Type` **et**
`Type2` avec deux jeux complets de potards, commutables par scène via
`SceneDoubleSwitch{N}`. Un rig peut donc porter deux amplis sans changement de rig,
donc sans coupure de queues. Cela déplace franchement la frontière 1-rig / N-rigs.
*(Seuls Amp, Amp Clone, Cab, IR, IR (1024), Pedal Clone, ReValver Amp/Cab, SuperClone
sont doublables — pas le NAM.)*

**RECO — Interdire le changement automatique de rig en cours de morceau.**
Une queue de reverb coupée net sur l'accord final avant un pont est parfaitement
audible, et la latence de chargement est non bornée (NAM/IR lus depuis le stockage).
Un deuxième rig ne se justifie que par une ressource unique-par-rig épuisée.

### 3.2 Le modèle de scène : ce qu'une scène stocke réellement

**FAIT** — Relevé exhaustif de `/Evil/Engine/FootSwitch` : `Scene<S>_<N>_Mode`
(10 scènes × 14 slots), `Scene<S>Slot<N>Preset` (idem), plus un second état par scène.
Enum confirmée dans le bundle : `{NO CHANGE: 0, ON: 1, OFF: 2}`.

**FAIT — Nomenclature complète des scènes**, lue dans le bundle. Pour la scène `s`
(0-based) et le slot `n` (0-based), avec le préfixe `State2` pour le second état :

| Propriété | Contenu |
|---|---|
| `Scene{s+1}_{n+1}_Mode` | **0 = NO CHANGE · 1 = ON · 2 = OFF** |
| `Scene{s+1}_{n+1}_Effect` | nom du bloc occupant ce slot (chaîne) |
| `Scene{s+1}Slot{n+1}Preset` | nom de preset de bloc, défaut `"No Preset"` |
| `SceneDoubleSwitch{s+1}` | 0 = NO CHANGE · 1 = A · 2 = B |
| `ScenePathSwitch{s+1}` | 0 = NO CHANGE · 1 = A · 2 = B |
| `SceneExtAmp{s+1}` | 0 = NO CHANGE · 1 = NONE · 2 = TIP |
| `SceneMIDIOut{s+1}` | message MIDI émis par la scène |

L'interface fait défiler le mode par incrément avec bouclage
(`NO CHANGE → ON → OFF → NO CHANGE`).

**Une scène ne stocke aucune valeur de paramètre** — seulement des bypass par slot
et des **noms de presets de bloc**. Toute variation de réglage entre deux sections
passe donc obligatoirement par un preset de bloc nommé, à créer sur l'appareil.

C'est aussi ce qui rend possible le rig unique par morceau : `Scene{n}Slot{k}Preset`
permet à une scène de charger un preset différent par slot, donc de changer le
modèle d'ampli entre couplet et refrain sans deuxième bloc et sans deuxième rig.

**RECO — Carte sémantique de scènes gelée, identique dans toute la bibliothèque :**

| Scène | Rôle | CC (**FAIT**, manuel v5.1.0 p. 71) |
|---|---|---|
| 1 | CLEAN | 21 |
| 2 | CRUNCH | 22 |
| 3 | RHYTHM (défaut) | 23 |
| 4 | LEAD | 24 |
| 5 | AMBIENT | 25 |
| 6–10 | spécifiques au morceau | 26–30 |

Tout rig-chanson doit définir au minimum 1, 3 et 4. Le pied ne se réapprend jamais
d'une chanson à l'autre, et FretWise mappe section → CC sans rien connaître du rig.
Les slots non concernés restent à `NO CHANGE`, ce qui préserve le pilotage manuel.

**FAIT — Le gabarit à 5 scènes est dimensionné, pas deviné.** Mesuré sur les
1320 partitions de la bibliothèque qui portent des marqueurs (§3.3), en classant
chaque section vers l'une des 5 scènes :

| Scènes distinctes requises | Morceaux |
|---|---|
| 5 | 305 |
| **4** | **537** |
| 3 | 292 |
| 2 | 106 |
| 1 | 54 |
| 0 (aucune section classée) | 26 |

Le mode est à 4 scènes et la queue à 5 : **aucun morceau de la bibliothèque n'a
besoin de plus de 5 scènes**, et les 5 emplacements 6-10 restent donc entièrement
libres pour les cas particuliers. Répartition des 12 640 sections classées :
CLEAN 4622 · RHYTHM 4310 · CRUNCH 1584 · AMBIENT 1089 · LEAD 1035.

### 3.3 Ce que la partition prouve, et ce qu'elle ne prouve pas

**RECO — Deux sources de vérité, avec règle d'arbitrage explicite :**
la **partition** prouve le *comportement* du son (gain, serrage, ambiance, niveau,
registre, sections, tempo) ; la **connaissance artiste** prouve son *identité*
(ampli, baffle, micro, pédale). En cas de conflit : la partition l'emporte sur les
quantités, la connaissance sur les modèles.

Aucune information d'une partition ne désigne un ampli. Inversement la connaissance
artiste ne sait rien de la section jouée. Mélanger les deux sans règle produit
exactement le défaut mesuré dans `data/gears/AC_DC__Highway_To_Hell.json`, où trois
étages de gain contredisent le `tone.mustHave` du même fichier (« slight crunch,
not high gain »).

**FAIT — Les sections sont une donnée déterministe, pas une invention du LLM.**
Mesuré sur la bibliothèque complète (`C:\Users\benoit\iCloudDrive\partitions`) :

- **1986 fichiers, tous en `.gp` (GP7/8, format GPIF).** PyGuitarPro n'en lit
  **aucun** — toute mesure doit passer par `fretwise.parser.gpif_adapter`, qui expose
  déjà `section_markers: dict[int, str]` via `_build_section_markers()`
  (`gpif_adapter.py:618`). 1985/1986 se parsent, 1 fichier est corrompu.
- **1320 fichiers (66 %) portent au moins un marqueur nommé** ; 64 % en ont ≥ 3,
  54 % en ont ≥ 8. 665 (34 %) n'en ont aucun.
- **13 644 sections nommées au total, 1775 libellés distincts** — mais la masse est
  très régulière : `chorus` 2012, `intro` 962, `outro` 742, `verse 2` 737,
  `verse 1` 710, `bridge` 638, `pre-chorus` 485, `interlude` 473, `solo` 317.
- **Une table de 11 expressions régulières classe 92,6 % des sections** vers les
  5 scènes du gabarit, et couvre **intégralement 72 % des morceaux** (951/1320),
  partiellement 26 %. La queue non classée (1004 instances, 661 libellés) est
  essentiellement de l'espagnol (`verso`, `coro`, `refrão`), des variantes sans
  espace (`verse1`, `verse2`) et des indications non tonales (`band enters`, `fill`,
  `harmony`) — le premier lot s'absorbe par quelques règles de plus.

**RECO** — `sections[]` devient un **champ dérivé** de la partition, régénérable ;
le LLM n'a plus qu'à affecter un `toneId` par section. Cela divise la surface
d'hallucination et rend le champ reproductible. Pour les 34 % sans marqueurs :
repli sur des sections proposées par le LLM, explicitement marquées
`sectionsSource: "inferred"` et `needsReview: true`.

| Signal de la partition | Force | Ce qu'il informe |
|---|---|---|
| sections / marqueurs de mesure | **forte, mesurée** (66 % de couverture) | découpage en scènes |
| tempo, signature | forte | `Rig.Tempo`, subdivisions de delay |
| accordage, capo | forte | structure de gain, low-cut |
| densité rythmique, palm-mute | forte | serrage, gate, compression |
| registre, polyphonie / voicings | moyenne | headroom, EQ |
| densité de bends / vibrato | moyenne | voicing lead, compression |
| **dynamiques `pp..ff`** | **faible** | à écarter automatiquement |

**RECO — Écarter les dynamiques dégénérées automatiquement.** `MF` est la valeur
par défaut du dataclass `NoteEvent` et la majorité des tabs Songsterr/DadaGP n'encodent
aucune nuance. Calculer l'entropie de Shannon de `NoteEvent.dynamic` sur la section
et retirer le champ de l'ensemble de preuves si `H < 0.2 bit`. Sans ça, le générateur
traite une constante comme une information et fabrique des justifications.

### 3.4 NAM : la ressource rare

**RECO** — Le slot NAM est réservé aux amplis **sans équivalent interne**
(Two-Rock, Dumble, Friedman, Hiwatt, AC15, OR120, Supro, Trainwreck) et aux
cleans / edge-of-breakup très caractéristiques.
**Interdit** pour la rythmique haut gain (`99 PV51 II Lead` / `05 Peavey 6505` sont
déjà la référence) et pour tout morceau dont deux sections demandent des gains
différents sur le même ampli — le gain d'une capture est cuit, elle interdit la
variation par scène.

**RECO** — Prototyper d'abord avec les modèles internes (rapides, CPU prévisible),
remplacer par une capture NAM/TONE3000 une fois la structure du rig validée.

### 3.5 Adaptation guitare et discipline de niveau

**RECO — L'adaptation guitare/micros est une couche d'offsets**
(`d_input_db`, `d_gain_pct`, `d_presence`, `d_treble`, `d_bass`) dans un document
unique `data/profiles/guitars.json`, appliquée à la compilation — jamais dupliquée
dans les fiches. Dupliquer un rig par guitare multiplierait 1982 fiches par 5 et
rendrait la calibration de niveau impossible.
Point d'application privilégié : `GlobalEQMain`/`GlobalEQAmp` s'ils sont globaux
(**HYPOTHÈSE**, cf. §7) ; repli sur le `PreGain` du slot 1 (±12 dB, présent sur tous
les blocs) ou l'`Input` du bloc NAM (±20 dB).

**RECO — Une seule autorité de niveau par rig : le bloc `Volume` du slot 14,
calibré en LUFS-I intégré (± 0,5 LU), jamais en crête.** Le device offre au moins
huit points de réglage de volume ; sans autorité unique la dérive est mécanique.
Et un rig haut gain, bien plus compressé, sonne 4 à 6 dB plus faible qu'un clean
à crêtes égales. Le boost de solo est un **preset** de ce bloc rappelé par la scène
(`Scene{N}Slot14Preset`), pas un changement du `Master` de l'ampli — qui modifierait
aussi le comportement de l'étage de puissance modélisé.

### 3.6 Comment savoir si un rig est juste

Protocole en 4 niveaux, dont le **niveau 0 est entièrement automatique** :

- **N0 — validation statique (CI).** Cohérence interne `tone.avoid` ↔ blocs actifs,
  comptage des étages de gain, budget CPU estimé, existence de chaque nom dans le
  catalogue, présence des scènes 1/3/4, unité déclarée == `format` du meta.
  *Ce seul niveau aurait rejeté sans écoute la fiche AC/DC actuelle.*
- **N1 — reamp d'un DI de référence.** Le canal USB 5 est la DI sèche de l'entrée
  guitare (FAIT : 6 in / 4 out). Enregistrer une fois trois phrases de référence,
  les reamper dans chaque rig candidat : supprime la première source d'erreur d'un
  A/B, la variation de jeu.
- **N2 — A/B contre le disque, aligné en LUFS.** Sans alignement, le plus fort gagne
  toujours et le test ne mesure rien.
- **N3 — répétition.** Le seul niveau qui juge l'ergonomie au pied.

---

## 4. Partie fonctionnelle

### 4.1 Plan de contrôle et plan de données

**RECO — HTTP est le plan de contrôle, MIDI est le plan de données.**

128 valeurs de Program Change pour 118 rigs déjà présents et 1982 fiches : toute
conception « une chanson = un PC » est arithmétiquement morte. À l'inverse, HTTP
met mDNS + Wi-Fi + un ordinateur allumé dans le chemin critique sous le pied.

- L'**adressage général** se fait par `loadRig(rigId)` en HTTP — espace UUID, illimité.
- Le **Program Change** est une ressource rare, réservée exclusivement à ce qu'un
  pied doit atteindre sans réseau. HTTP écrit les `loadedProgMIDICC` ; MIDI exécute
  au moment du jeu.

**FAIT — Et ce n'est plus un choix : FretWise ne PEUT PAS envoyer de MIDI au Core.**
Le Core n'expose **aucun endpoint MIDI sur USB-B** (§7 q. 13) : Windows l'énumère
sans interface `&MI_xx`, et le manuel v5.1.0 restreint le contrôle MIDI entrant au
**MIDI Input 5 broches** ou au **port USB-A** — lequel est un port *hôte*, donc
inutilisable pour s'y connecter depuis un PC.

Les deux plans sont donc **physiquement disjoints**, et pas seulement par choix
de conception :

| Chemin | Transport | Qui l'emprunte |
|---|---|---|
| FretWise → Core | **HTTP uniquement** (`loadRig`, PUT, `saveRig`) | l'ordinateur |
| Pied → Core | **MIDI uniquement** (PC/CC) | M-Vave Chocolate Plus, via USB-A ou DIN |

**Conséquence directe sur le code :** `RigProfile.midi_bytes()` et
`send_profile_program_change()` (`fretwise.rig_bank`), qui activent le GP-180 en
envoyant un Program Change depuis le PC, **n'ont aucun équivalent utilisable pour
le Core**. La branche `device == "headrush_core"` envisagée en §5.4 n'a pas lieu
d'être : l'activation depuis FretWise passe par HTTP.
Le seul intérêt d'un chemin MIDI PC→Core serait l'horloge (§4.4), et il coûterait
une interface MIDI-DIN pour un bénéfice que le §4.4 écarte déjà.

### 4.2 Allocation des Program Change

**RECO** — Cinq plages à propriétaire explicite, persistées côté FretWise
(`data/devices/headrush-core/allocation.json`), jamais lues depuis l'appareil :

| Plage | Propriétaire | Contenu |
|---|---|---|
| **0–15** FOOT | FretWise | réécrite à chaque set, miroir des 16 slots du M-Vave |
| **16–31** CORE | humain | permanent, jamais touché |
| **32–111** SONG | FretWise | 80 slots en LRU |
| **112–125** SCRATCH | libre | volatile, tests |
| **126** PANIC | humain | gelé — le rig de secours |
| **127** | — | jamais assigné : sentinelle de contrôleur parasite |

PANIC en 126 et non 0 : 0 est la valeur qu'émet un contrôleur mal configuré ou un
DAW au démarrage — l'accident doit tomber sur la première chanson du set, pas sur
un lead saturé.

**RECO** — `allocation.json` est la source de vérité ; `reconcile()` **rapporte** les
divergences sans jamais les corriger en silence, et refuse la réécriture en masse
après une restauration cloud tant qu'un humain n'a pas validé. Une réécriture aveugle
de 80 `loadedProgMIDICC` après restauration est le scénario qui casse un concert.

**RECO** — La réconciliation après reset (qui change **tous** les UUID) passe par le
nom : les rigs-chanson sont nommés exactement comme le stem de la partition
(`Muse - Plug In Baby`), et `gears.naming.gears_key_from_filename` fait déjà le bon
découpage. Zéro convention supplémentaire, et le nom reste lisible sur l'écran.

### 4.3 Répartition au pied

**RECO — Le M-Vave Chocolate Plus est TRANSVERSE et ne change jamais ;
les 5 switches du Core sont SPÉCIFIQUES à la chanson.**

Reprogrammer le Chocolate exige de le débrancher et d'ouvrir CubeSuite : tout ce qui
varie doit donc vivre dans le rig — les switches du Core sont sauvegardés avec lui.
C'est l'inverse de la répartition des configs Notion A–F, écrites quand un rig était
un « son » et pas une chanson.

| Banque Chocolate | Rôle | Messages |
|---|---|---|
| **A** — SET | 4 chansons du set | PC (plage FOOT) — *actuellement 01A = rig précédent (CC 16), 01D = rig suivant (CC 17)* |
| **B** — SECTIONS | scènes | CC 21–24 (**FAIT**) |
| **C** — BLOCS | bypass ponctuel (tête de chaîne figée) | CC 77 (wah), 78 (drive), 80 (ampli), 81 (cab) |
| **D** — UTILITAIRE | tap, looper, drums, **D4 = PC 126 PANIC** | CC 64 / 70 / 42 / PC 126 |

D4 en PC 126 plutôt qu'en CC16 « rig up » : le bouton de secours ne doit reposer sur
aucune HYPOTHÈSE.

Sur le Core : FS1 CLEAN, FS2 RHYTHM, FS3 LEAD, FS4 signature du morceau, FS5 tap/tuner.

**FAIT — Câblage en place (2026-09-10).** Le M-Vave Chocolate Plus est branché
**en USB au PC et en MIDI DIN au Core** — donc le chemin au pied existe, et le PC
peut en plus *lire* le pédalier (Windows l'énumère sous `FootCtrlPlus`,
`USB\VID_4353&PID_4B4D&MI_01`). Configuration actuelle : **01A = rig précédent
(CC 16), 01D = rig suivant (CC 17)** — les deux hypothèses du manuel v5.1.0 se
trouvent ainsi confirmées à l'usage.

**FAIT** — Les CC de type footswitch exigent **127 puis 0** (momentané). Le manuel
v5.1.0 p. 72 est explicite : *« If you only send the press data value, the current
assigned hold function to that internal footswitch will be activated. »*
C'est la cause n°1 de « ça ne fait pas ce que j'ai demandé ».

### 4.6 Table MIDI de référence — FAIT, manuel v5.1.0 p. 71-72

Extraite du PDF constructeur, firmware cible. **Elle corrige trois erreurs de la page
Notion**, qui reposait sur des numéros déduits ou hérités de la v4.0.0 :

| CC# | Action | CC# | Action |
|---|---|---|---|
| **1 / 2** | Pédale d'expression (valeur exacte 0-127) | 49–53 | **Footswitch 1 à 5** (127 puis 0) |
| **12** | Global Tempo − | 64 | Tap Tempo (envoyer plusieurs fois) |
| **13** | Global Tempo + | 65–74 | Looper |
| **14** | External Pedal Switch (A/B) | **75–88** | **Block 1 à 14 Toggle (On/Off)** |
| 16 / 17 | Rig Up / Rig Down | 89 | Mic Dry (On/Off) |
| 18 / 19 | Bank Up / Bank Down | **90–93** | Hands-Free / Looper / Tuner / Lock Screen |
| 20 | Footswitch Bank (A/B) | **94–98** | Enter Stomp / Hybrid / Setlist / Rig / 5-Rig FS Mode |
| **21–30** | **Scene 1 à Scene 10** | **102–112** | Practice Tool |
| 31–47 | Drum Machine | | |

**Corrections apportées à la page Notion :**
1. **Tempo et pedal switch décalés d'un cran.** Notion donnait CC 13 = Tempo −,
   CC 14 = Tempo +, CC 15 = External Pedal Switch. Le manuel donne **12 / 13 / 14**.
2. **Practice Tool renuméroté entre v4.0.0 et v5.1.0.** La v5.1 insère
   `CC#104 = Stop`, ce qui décale tout le reste : Loop In passe de 106 à **107**,
   Loop Out de 107 à **108**, Speed − de 108 à **109**. La « Config E » de Notion
   utilise les numéros v4 et est donc **fausse sur le firmware actuel**.
3. **CC 90-98 n'existaient pas** dans la liste Notion (Hands-Free, Looper, Tuner,
   Lock Screen, et les 5 modes de footswitch).

Les hypothèses Notion qui se confirment : scènes 21-30, rig up/down 16/17,
bank up/down 18/19, footswitch bank 20.

*(Note : la table imprimée étiquette `CC#1` « External Expression Pedal » alors que
la prose de la page suivante parle de « Internal and External Expression Pedal
(CC#1 and CC#2) ». Le manuel se contredit ; à trancher à l'oreille au bring-up.)*

### 4.4 Tempo

**RECO — Écriture HTTP directe au chargement, pas de MIDI Clock permanente.**

**FAIT — mais sur le bon objet.** `Rig.Tempo` est **inerte** tant que
`TempoFromMaster = true` (le défaut, enum `["Fixed","Current"]`) : écrit à 150 BPM,
l'appareil affichait toujours 85,96 au tuner. Le tempo effectif vit dans
**`/Evil/Engine/Tempo`** :

```
PUT /api/v1/object-properties/Evil/Engine/Tempo   {"Tempo": (bpm-30)/210}
```

Vérifié : le tuner est passé à 150,00 BPM, `TempoMaj` a suivi, et `Rig.Tempo` s'est
aligné tout seul — **sans toucher à `TempoFromMaster` ni à `MBCIn`**, donc sans
modifier le comportement des rigs existants.

**PIÈGE — écrire le tempo salit le rig.** `dirty` passe à `true`, et un rig sale
bloque le chargement suivant derrière le dialogue modal (§2.6, piège 3). Un
enchaînement « régler le tempo puis passer à la chanson suivante » se coincerait donc.
**RECO** : après une écriture de tempo, soit `saveRig()` pour l'inscrire dans le rig,
soit `RigSaveDialog.discard()` **suivi d'un `loadRig` explicite** (le discard ne
laisse aucun rig chargé, §2.7).

Le mapping est linéaire sur [30, 240] et vérifié exactement. Une horloge issue de `setInterval` dérive de
plusieurs millisecondes ; à 24 PPQN (48 messages/s à 120 BPM) cela module directement
le temps de delay du Core. **Un delay pointé qui ne bouge jamais vaut mieux qu'un
delay qui respire au rythme de l'ordonnanceur Windows.** MIDI Clock uniquement pour
les morceaux à tempo variable, et jamais émise depuis le navigateur.

### 4.5 La boucle inverse

**RECO — Construire le retour appareil → FretWise sur le WebSocket, pas sur
`MIDIOutCtrl`.** Le WS émet un changement sur `/Evil/API/Rigs.loadedName` à *chaque*
chargement — y compris manuel et depuis une setlist — avec l'identité complète
(UUID + nom), sans câble et sans configuration. `MIDIOutCtrl` réimposerait le plafond
de 128 dans le sens inverse : seuls les rigs ayant un PC pourraient ouvrir une
partition, or les rigs les moins joués sont précisément ceux dont on cherche la partition.

**RECO — L'auto-follow PROPOSE, ne force pas** (le guitariste qui feuillette ses rigs
ne doit pas voir sa partition disparaître). En revanche **l'alarme de dérive**
(partition ouverte ≠ rig chargé) est un badge permanent : jouer la bonne partition
avec le mauvais son est l'erreur la plus fréquente en situation réelle.

**RECO** — Une seule connexion WS, détenue par le backend FastAPI, liste blanche de
chemins, throttle CPU à 2 Hz, watchdog 5 s, backoff ; re-exposée au navigateur en
**SSE** (`GET /api/core/stream`) + snapshot (`GET /api/core/state`). Le flux brut est
un firehose sur 282 objets, le Core est un embarqué, et le navigateur peut être un
téléphone hors LAN.

---

## 5. Partie technique

### 5.1 Le gabarit de 14 slots — l'invariant central

**FAIT** — CC 75–88 adressent la **position de slot**, pas la fonction. Sans gel du
gabarit, CC 78 bypasse un overdrive dans un rig et une réverbe dans un autre.

*Étayage :* le manuel v5.1.0 les nomme `Block 1..14 Toggle (On/Off)` — « Block N »,
pas « Slot N ». Mais la même source décrit le réordonnancement ainsi :
*« tap and drag a block to another slot […] the blocks after that position will
shift one slot further down the signal chain »*, et l'API expose `ModuleType1..14`
indexé par slot. Bloc N ≡ slot N. **Reste à confirmer** qu'un `Empty Slot` consomme
bien son index (cf. §7).

**FAIT — Et c'est ce qui rend CC 49-53 complémentaire, pas redondant.** Le manuel
avertit : *« The sequence of blocks in your signal chain is not necessarily reflected
in the footswitches. You can freely assign blocks to available footswitches without
changing your signal chain at all—and vice versa. »* Donc :

| | adresse | survit au réordonnancement | portée |
|---|---|---|---|
| **CC 75-88** | la position de slot | **non** — exige le gabarit gelé | générique, toute la bibliothèque |
| **CC 49-53** | l'assignation de footswitch | **oui** — indirection par le rig | spécifique à la chanson |

C'est l'argument décisif pour la répartition du §4.3 : le Chocolate transverse tape
sur les positions (donc sur les rigs générés au gabarit), les 5 switches du Core
tapent sur des assignations propres au morceau.

**FAIT — Mesuré sur les 119 rigs de l'appareil.** Les 39 rigs guitare
(`#HR - *` d'usine et `NN-GTR-*`) ont été chargés un par un et leur chaîne relevée.
Résultat : **il existe un ordre, mais c'est un ordre PARTIEL, pas un gabarit fixe.**
Seuls **3 rigs sur 39 (8 %)** respectent un ordre total ; le taux moyen d'inversions
par rig est de 11,9 %. Un gabarit à 14 positions figées est donc contredit par 92 %
d'un corpus fait par des professionnels.

**La tête de chaîne est rigide** (règles à 100 %, robustes sur les rigs `autre` aussi) :

| Règle | Rigs guitare | Rigs « autre » |
|---|---|---|
| `Filter (wah) < Overdrive` | **100 %** (n=21) | 100 % (n=5) |
| `Overdrive < Amp` | **100 %** (n=31) | 100 % (n=14) |
| `Amp < Cab` | **100 %** (n=34) | 97 % (n=34) |
| `Utility (gate) < tout` | **100 %** | — |

**La queue de chaîne est délibérément libre** — ce sont de vraies pile-ou-face :

| Règle | Rigs guitare | Rigs « autre » |
|---|---|---|
| `Cab < Delay` | **57 %** (n=46) | 54 % (n=28) |
| `Chorus < Cab` | **59 %** (n=34) | 50 % (n=16) |
| `Volume < Delay` | **53 %** (n=43) | 59 % (n=17) |
| `EQ < Cab` | 68 % (n=22) | 64 % (n=25) |

Seule la réverbe se re-rigidifie en fin de chaîne : `Delay < Reverb` 94 %,
médiane slot 12.

Positions médianes observées (rigs guitare) :

| Catégorie | n | Slot médian | Étendue |
|---|---|---|---|
| Utility (gate) | 14 | 1 | 1-2 |
| Filter (wah) | 22 | 1 | 1-3 |
| Compressor | 14 | 2 | 1-10 |
| Overdrive | 41 | 3 | 1-5 |
| Phaser | 29 | 4 | 1-10 |
| **Amp** | 34 | **6** | 1-12 |
| **Cab / IR** | 35 | **8** | 6-14 |
| EQ | 23 | 7 | 2-11 |
| Chorus | 37 | 9 | 2-12 |
| Volume | 30 | 9 | 2-13 |
| Delay | 54 | 10 | 1-14 |
| Reverb | 42 | 12 | 3-14 |

**RECO — Ne figer que ce que le corpus fige : les slots 1 à 7.**
`1` gate · `2` wah/filtre · `3` compresseur · `4` overdrive · `5` modulation pré-ampli
· `6` **ampli** (ou clone/NAM) · `7` **cab/IR** — l'ordre des deux premiers suit les
médianes mesurées (Filter slot 1, Compressor slot 2). Les slots 8 à 13 restent **libres**, choisis par
morceau (EQ, chorus, volume, delay, pitch), et le slot 14 est réservé à la réverbe.

Conséquence sur le pied : **CC 75 à 81 sont stables** — gate, compresseur, wah, drive,
modulation, ampli, cab — c'est-à-dire exactement les blocs qu'on veut commuter au pied.
CC 82-88 ne le sont pas, mais ils couvrent delay/reverb/chorus/volume, mieux servis par
les **scènes** (CC 21-30) de toute façon.

**Deux idées reçues corrigées par les données.** Le volume n'a pas de place canonique
(médiane slot 9, étendue 2-13) : le mettre « toujours en 14 » était une invention.
Et placer le delay **avant** le baffle est un choix à 50/50 dans un corpus professionnel,
pas une excentricité — le générateur doit pouvoir en décider par morceau.

**FAIT — Les rigs d'usine ne tassent pas la chaîne à gauche** : 29 des 39 laissent des
slots vides intercalés. La règle « ne jamais compacter » est donc conforme à l'usage.

**RECO** — Vérifier le gabarit à **chaque** `loadRig`, jamais le supposer :
`GET /Evil/Engine/Patch/Chain` rend la comparaison triviale (14 entiers). En cas de
divergence : badge rouge et désactivation des CC de bypass pour ce rig. Envoyer CC 79
en croyant couper le delay alors que le slot 5 contient un ampli est le pire échec
possible du système.

**~~FAIT — `AutoAmpCab` et `AutoAssignments` doivent passer à `false`.~~ RÉFUTÉ
par le test.** Les deux sont bien à `true` en live, mais **n'ont aucun effet sur
les modifications de chaîne faites par l'API** (§2.8) : ni réassignation de
footswitch, ni ajout automatique de cab. Ils gouvernent le flux tactile.
Le pusher n'a donc pas à les exiger à `false` — il doit en revanche **vérifier le
dialogue de sauvegarde** avant et après chaque `loadRig` (§2.6, piège 3).

**RECO** — `Chain.Routing = 0` (Straight Path) en dur. `Routing` est un entier 0–9 ;
les topologies 1–4 réaffectent les slots 4–11 en branches A/B sans changer leur numéro,
ce qui détruit la sémantique de CC 75–88 ; les 5–9 exigent la voie voix.

**RECO** — Adresser les blocs par **nom d'instance** (`"BBD Delay"` / `"BBD Delay 2"`),
jamais par numéro de slot : il n'existe aucun objet « paramètres du slot N ». Deux
delays identiques dans un rig écrivent dans deux objets distincts, et se tromper
écrase l'autre silencieusement.

**RECO** — Interroger `categoryBlocksFlags(catégorie, slot)` comme **oracle
d'exclusivité** plutôt que coder « 1 NAM / 1 C-Verb » en dur : le SPA dérive
`isEnabled = !!(flag & 2)` par slot et pour l'état courant de la chaîne. Les jumeaux
`Neural Amp Modeler 2` et `C-Verb 2` existent dans `ModuleTypes` — l'interdiction est
une politique du sélecteur, pas une absence de type, donc une règle en dur serait
fausse dès qu'elle change.

**RECO — Échelle de dégradation en 5 étapes journalisées** quand un morceau ne rentre
pas : fusion de rôles → slot polyvalent (10 ou 12) → scène → dégradation CPU →
scission en deux rigs (qui force `needsReview = true`). Le gabarit n'a pas de spare
libre : il faut une politique explicite plutôt qu'un débordement silencieux.

### 5.2 Schémas — trois couches

**RECO — Ne migrer AUCUN des 1982 fichiers de `data/gears/`.**
Mesuré sur le corpus : 1779 `gear.v2` + 203 `rig.v1` ; **0 fichier sur 1982** porte
une clé `sections` ; 25168 valeurs de `settings` sur 35224 sont du texte libre
(`"Bright"`, `"Slow"`) ; `role` a 509 valeurs distinctes pour 12 modules.
Aucun de leurs champs device n'est convertible en paramètres normalisés. Les geler
comme legacy lisible coûte zéro et garde la documentation GP-180 consultable
(l'appareil peut être revendu).

**FAIT — Le hard-require `gp180` de `schema.validate_rig()` est déjà mort.**
1779 des 1982 fiches échoueraient à cette fonction aujourd'hui, et ses seuls appelants
sont `llm.py:131`, `run_economic_production_batch.py:1773`, `run_ollama_staged_preview.py:324`
— **aucun chemin de lecture ne l'appelle** (le rendu passe par
`adapter.song_output_to_view()` et `verify.validate_gear_v2()`).
**RECO** — la renommer `validate_gp180_rig_v1()` avec alias, la figer, ne jamais
l'étendre. Réparer un mur porteur qui ne porte rien serait du travail perdu.

Nouvelle famille de schémas, avec discriminant dès la v1 :

| Couche | Schéma | Répertoire | Auteur |
|---|---|---|---|
| **L1** intention | `fretwise.tone.intent.v1` | `data/tones/<key>.json` | LLM |
| **L2** binding | `fretwise.device.binding.v1` (`device.deviceId`) | `data/devices/<id>/rigs/<key>.json` | compilateur |
| **L3** état | `fretwise.device.state.v1` | `data/devices/<id>/state/<key>.json` | relecture post-push |

La séparation L2/L3 est **imposée par l'API** : on ne peut pas lire le contenu d'un
rig sans le charger (`AllRigIds`/`AllRigNames` ne donnent que l'identité ;
`Chain`/`Patch` ne reflètent que `loadedID`). L3 est donc une capture coûteuse et
datée, pas un miroir dérivable de L2.

**RECO — Upcast paresseux en lecture** (`src/fretwise/gears/upcast.py`), zéro écriture
disque : `adapter.py` gagne une 4ᵉ branche de dispatch en tête, les 3 existantes
restent intactes, les 1982 fichiers restent bit-à-bit inchangés dans git.

**RECO — Deux grades affichés au lieu d'un** : `toneGrade` (L1 — sait-on ce que le
disque sonne ?) et `rigGrade` (L2 — ce rig rend-il ce son ?). Mesuré : 1447/1779 fiches
sont en `medium` donc grade C — 81 % du catalogue porte la même note, le grade unique
n'a aucun pouvoir discriminant parce qu'il conflate deux questions indépendantes.

**RECO** — `realisation.fidelity` remplace `matchQuality` avec une échelle sémantique :
`same-unit-capture` / `same-circuit-capture` / `same-circuit-model` / `same-family` /
`voiced-approximation` / `unrelated`, plus un objet `asset` traçable
(`source: tone3000|local|factory`, `id`, `url`, `deviceFile`, `presentOnDevice`).
Le Core introduit la capture NAM : la distinction capture réelle / modèle interne /
substitut devient la question centrale et doit être encodée.

### 5.3 Identité et idempotence

**RECO** — Identité = **GUID `rigId`** persisté dans
`data/devices/headrush-core/bindings.json`. Le nom est une sortie dérivée avec préfixe
garde-fou `#FW - ` ; le PC est une allocation révocable, jamais une identité
(128 valeurs pour 1982 morceaux).

**RECO — Idempotence par `bindingHash`** (sha256 du document L2) : push no-op si
inchangé ; mise à jour par `loadRig(rigId)` + `saveRig()` qui **conserve le GUID** ;
`makeNewRig` + `saveRigAs` seulement à la première création, avec relecture immédiate
de `Rigs.loadedID` pour capturer le nouveau GUID. `saveRigAs` crée toujours un nouveau
GUID — c'est le seul chemin qui duplique, donc distinguer explicitement création et
mise à jour est la seule façon d'éviter d'accumuler des doublons à chaque régénération.

### 5.4 Où va le code

**RECO — `src/fretwise/devices/headrush_core/`, pas sous `gears/`.**
`gears/` est un domaine documentaire stdlib-only importé par `web/app.py` à chaque
requête `/api/rig` ; y injecter `httpx` + `websockets` ferait dépendre le rendu d'une
fiche d'un stack réseau. La séparation intention/matériel existe déjà à la racine
(`gears/` vs `rig_bank.py` + `control_surface.py`).

```
src/fretwise/devices/
├── base.py                    # Protocols (écrit en dernier, cf. §8)
└── headrush_core/
    ├── client.py              # transport /api/v1 + WebSocket
    ├── catalog.py             # sonde + cache du catalogue versionné
    ├── params.py              # 11 algos normalisé↔affiché, float32, trou DelayRatio
    ├── chain.py               # gabarit fw-standard-v1, setModuleTypeInternal
    ├── scenes.py              # Scene<S>_<N>_Mode / Scene<S>Slot<N>Preset
    ├── rig_builder.py         # tone.intent.v1 -> device.binding.v1
    ├── pusher.py              # binding -> device, idempotent, 3 verrous
    ├── snapshot.py            # sauvegarde GET-only + diff
    └── midi.py                # carte CC + allocation PC
```

**RECO — NE PAS créer `binding_store.py` : étendre `fretwise.rig_bank`.**
FAIT vérifié : `rig_bank.py` fait 51,9 Ko, contient `RigProfile`/`RigBinding`/`RigBank`/
`resolve()`/`recommend()`/`send_profile_program_change()`, est testé
(`tests/test_rig_bank.py`), servi par 7 routes `/api/rig-bank/*` dont `/activate`, et
**`RigProfile.device` existe déjà avec le défaut `"valeton_gp180"`**
(`rig_bank.py:428`). Un second store créerait deux sources de vérité pour « quel rig
pour quelle chanson ».

**~~FAIT — `RigProfile.midi_bytes()` a besoin d'une branche `headrush_core`.~~
ANNULÉ.** Cette branche n'a pas d'objet : **le Core n'expose aucun port MIDI au PC**
(§4.1), donc `send_profile_program_change()` n'a aucun port où écrire et
`_DEVICE_PORT_HINTS["headrush_core"]` ne matcherait jamais rien.
L'activation depuis FretWise se fait en HTTP (`Rigs.loadRig`).
*Le détail reste vrai pour mémoire :* le code émet un `CC0` de Bank Select puis
attend `_INTER_MESSAGE_DELAY_S = 0.2` — un contournement d'un bug propre au GP-180,
confirmé matériel le 2026-07-27 (`docs/valeton_gp180_midi.md`). Un futur appareil
piloté en MIDI depuis le PC devra éviter d'hériter de ce délai.

**RECO — Wrappers CLI `scripts/device_*.py`, avec `--device`.**
`scripts/core_*.py` collisionne frontalement avec `src/fretwise/core/` (moteur de
notation/gravure) : « core_push » se lirait « push du moteur de gravure ».
`device_` absorbe le GP-180 et un futur troisième appareil sans nouveau préfixe.

```
scripts/device_probe.py          # inventaire, état, IP résolue
scripts/device_catalog_dump.py   # sonde -> data/devices/<id>/catalog/<AppVersion>.json
scripts/device_backup.py         # snapshot GET-only d'un rig
scripts/device_plan.py           # binding -> plan d'écriture, hors ligne
scripts/device_push.py           # applique un plan (--dry-run par défaut)
scripts/device_pc_alloc.py       # allocation / reconcile des Program Change
```

**RECO — Routes web dans un `web/device_routes.py` neuf** exposant
`register_device_routes(app)` : `web/app.py` fait déjà 195 Ko.
Nouvelle `RuntimeCapability` **`device_http`** distincte de `midi_output` — un NAS sans
port MIDI peut légitimement parler au Core sur le même LAN, les deux capacités ne
coïncident pas.

### 5.5 Enveloppe de sûreté

Il n'existe **aucune écriture transactionnelle** : provisionner N rigs = N ×
`loadRig`/mutate/`saveRig`, sans rollback. Un échec après `saveRig` laisse un rig
réel écrasé à moitié.

**RECO — Toute écriture se fait dans un rig bac à sable `#FW - SCRATCH`.**
Le rig de production n'est créé qu'à la fin par `saveRigAs`, après validation CPU +
`FileMissing` + relecture des paramètres. Le CPU n'est mesurable qu'**après**
chargement de la chaîne : la validation ne peut donc pas être un pré-vol.

**RECO — Trois verrous d'écriture indépendants**, chacun couvrant un mode d'échec
distinct :
1. variable d'environnement `FRETWISE_HEADRUSH_ALLOW_WRITE` — le script lancé par erreur ;
2. `--confirm` — la faute de frappe interactive ;
3. `confirm_token` = sha256 des étapes du plan — la course. `apply()` re-diffe avant
   la première écriture et lève `DeviceBusy` si l'appareil a bougé.

**RECO — Deux `Protocol` distincts, `DeviceTransport` (lecture) et
`DeviceWriteTransport` (lecture+écriture).** Sous `mypy --strict`, `catalog`/`snapshot`/
`diff` typés `DeviceTransport` sont **statiquement incapables** d'écrire : la règle de
sûreté devient une propriété du type, pas une discipline.

**RECO — Préfixe de nom réservé `#FW - ` + couleur dédiée.** Cohérent avec les
conventions déjà sur l'appareil (`#HR - 01 Super Classic Crunch`), donc les rigs
générés se trient ensemble à l'écran. `pusher` refuse tout rig dont le nom ne commence
pas par le préfixe : **rayon de destruction nul sur les 118 rigs faits main**.

**RECO — Sauvegarde primaire GET-only.** `GET /object-properties/Evil/Engine/Patch/<Bloc>`
renvoie tous les paramètres plus `labels`/`order` : c'est déjà une description complète
et restaurable, diffable, et qui ne viole pas la règle lecture-seule.
`serializeBlock` (POST, format opaque, sémantique non validée) devient un blob
redondant optionnel.

**RECO — Écritures uniquement contre une IP littérale** (`FRETWISE_CORE_HOST`) avec
vérification de `Gui.DeviceName`, jamais via mDNS : `headrushcore.local` est spoofable
sur le Wi-Fi d'une salle.

**RECO — Contrat de version pinné, sans flag d'override** :
`data/devices/headrush-core/contract-5.1.0.2a63755.json` porte `AppVersion` +
`product` + `sha256(ModuleTypes)` + `sha256(object-meta)` par bloc utilisé, asserté
avant toute écriture. `ModuleTypes` est un tableau **positionnel** : une mise à jour
qui insère un module décale tous les identifiants.
**RECO corollaire — ne persister QUE des noms** dans les plans et les backups, jamais
les index entiers. Un index périmé écrit silencieusement le mauvais bloc ; un nom
périmé lève une exception.

### 5.6 Tests

- **Parité `params.py`** — les 11 algos reproduits en float32 contre un golden JSON,
  `Math.fround` inclus, trou `DelayRatio` inclus. Exactement le pattern de
  `tests/test_dataset_port.py`. C'est la différence entre écrire la bonne valeur et
  écrire une valeur plausible mais fausse dans l'ampli.
- **Transport factice** — les dumps `subtree_api.json` / `subtree_patch.json` sont
  déjà un arbre device enregistré : ils deviennent la fixture.
- **Contrat de catalogue** — `test_core_catalog_snapshot_matches_recorded_device_tree`
  lève l'alarme au premier firmware qui bouge.
- Nommage projet : `test_<quoi>_<condition>_<attendu>`.

---

## 6. Ce qu'on ne construit pas

- **Le LLM ne produit aucune valeur numérique ni aucun nom de modèle.** Il n'entend
  pas ; toute valeur générée est une hallucination bien formée. Les 1982 fiches
  existantes étaient de la prose lue par un humain qui filtrait le n'importe quoi —
  en branchant la sortie sur la machine on supprime ce filtre. Le mapping
  intention → blocs+valeurs est une **table écrite à la main**, auditable, et corriger
  un tag corrige tous les morceaux qui l'utilisent.
- **Pas de migration des 1982 fiches.** Coût de réécriture pour zéro gain : les données
  device sont inutilisables et le vrai manque (les sections) ne peut pas être inventé
  par une migration.
- **Pas de normalisation des 118 rigs existants.** Destructif, hors périmètre, et le
  delay avant le baffle dans « Lorenzo solo 1 » est un choix, pas une erreur.
- **Pas de changement de rig automatique en cours de morceau.**
- **Pas de MIDI Clock permanente.**
- **Pas de proxy du Core derrière FastAPI en écriture** : l'API du device n'est pas
  authentifiée ; exposer une route d'écriture ferait de FretWise un proxy ouvert vers
  l'instrument physique de quelqu'un.
- **Pas de `devices/base.py` en premier.** Abstraire avant d'avoir deux implémentations
  vivantes, c'est deviner.
- **Pas de doublage stéréo par défaut** : il double le coût CPU du bloc le plus cher,
  alors que 59-66 % sont déjà consommés.

**L'argument honnête contre tout le système** : Benoit est seul, joue chez lui, et
poser neuf blocs à l'écran tactile prend deux minutes — qu'il faudra de toute façon
retoucher à l'oreille. Une infrastructure de plusieurs jours pour économiser ces deux
minutes est un mauvais calcul **si l'objectif est la génération de rigs**.
Ce qui tient, en revanche : la bibliothèque de 118 rigs n'est **pas pilotable au pied
aujourd'hui** (`loadedProgMIDICC = -1` partout), FretWise connaît déjà le tempo de
chaque partition, et personne ne sait ce que contiennent ces 118 rigs. L'inventaire,
l'allocation PC et le tempo valent leur coût immédiatement. La génération complète,
elle, doit attendre d'avoir prouvé sa valeur sur trois morceaux.

---

## 7. Ce qui reste à prouver

Ordonné par rentabilité. Les quatre premiers tiennent en une session d'une heure,
instrument sous les yeux.

> **Quatorze questions sur quinze tranchées.** Deux par écriture réelle sur `#FW - SCRATCH`
> (n° 1, 5 et 6, session du 2026-09-10), les autres sans rien écrire : la n° 2
> (scènes = CC 21-30, lue dans le manuel v5.1.0), la n° 7 (canal MIDI en Omni) et
> la n° 14 (sections dérivables de la partition). Elles sont barrées et conservées
> avec leur réponse. La n° 13 est mesurée mais demande une action matérielle.
>
> **Relevés live complémentaires** (rig « Accoustique » chargé) :
> `AutoAmpCab = true` et `AutoAssignments = true` — mais **sans effet sur le chemin
> API**, cf. §2.8 : ce ne sont pas des verrous à lever. `Chain.Tails = true`, `Routing = 0` (`"S"`,
> parmi `["S","SPS-1","SPS-2","SPS-3","PS-1","Vocal","Dual","Dual Vox-4","Dual Vox-2","DualGuit"]`).
> `product = "HV01"`, `hasVocals = true`, `hasSongView = false` (donc pas de
> regroupement par chanson dans les setlists). Modèle de scènes **confirmé exactement** :
> 140 = 10 × 14 propriétés pour chacun de `Scene<S>_<N>_Mode`, `Scene<S>Slot<N>Preset`
> et `Scene<S>_<N>_Effect`, sur 1089 propriétés `FootSwitch` au total.
> `ModeNew1..10 = 0` (tous en Toggle) et `LastScene = -1` sur ce rig.

| # | Question | Expérience | Bloque |
|---|---|---|---|
| ~~1~~ | ~~Les écritures passent-elles sans appairage ?~~ | **RÉSOLUE — FAIT, testé le 2026-09-10 : oui, sans aucune authentification.** `PUT` → HTTP 200, `saveRig()` → `true`, `POST /api/auth` inutile. **Mais un `PUT` seul n'est que de la RAM** : il faut `saveRig()` pour commiter, et `dirty` reste `False` même avec une modification en attente (§2.6). | — |
| ~~2~~ | ~~CC 21–30 = scènes 1–10 ?~~ | **RÉSOLUE — FAIT, manuel v5.1.0 p. 71 : `CC#21 Scene 1` … `CC#30 Scene 10`.** Table complète et corrections en §4.6. Plus besoin de test au pied pour cette question. | — |
| ~~3~~ | ~~Le compteur CPU est-il bien 200 × la valeur ?~~ | **RÉSOLUE — FAIT : oui.** Écran = 24 %, API = 0,12. Le rig 9 blocs à 0,295 tournait donc bien à ~59 % : **la moitié du budget est déjà consommée**, le dimensionnement du §2.3 tient. | — |
| ~~4~~ | ~~`Scene{n}_{k}_Mode` : 1 = ON et 2 = OFF, ou l'inverse ?~~ | **RÉSOLUE — FAIT, lu verbatim dans le bundle SPA :** `e[e["NO CHANGE"]=0], e[e.ON=1], e[e.OFF=2]`. Donc **0 = NO CHANGE · 1 = ON · 2 = OFF**, aucune inversion. Le bundle livre au passage toute la nomenclature des scènes (§3.2). Aucune écriture n'a été nécessaire — `object-meta` ne publiait pas d'`x-options` pour ce champ, mais le code de l'interface, si. | — |
| ~~5~~ | ~~`AutoAssignments` réécrit-il les footswitches via l'API ?~~ | **RÉSOLUE — FAIT : non, ni lui ni `AutoAmpCab`.** Trois poses de bloc par l'API, `Module1..10` et `FootSwitchText1..10` inchangés, aucun Cab ajouté d'office. Ces automatismes sont propres au flux tactile (§2.8). **Découvert au passage : l'argument de slot de `setModuleTypeInternal` est 0-indexé** (§2.7), et une modification en attente bloque `loadRig` derrière un dialogue modal (§2.6, piège 3). | — |
| ~~6~~ | ~~`loadedProgMIDICC` est-il global ou relatif à la setlist ?~~ | **RÉSOLUE — FAIT : global.** Aucune setlist n'était chargée, et depuis `Accoustique` le PC 112 attribué à `#FW - SCRATCH` disparaissait bien de `availableProgMIDICC` (127 au lieu de 128). L'allocation est donc à l'échelle de l'appareil : **128 au total**, pas par setlist. Le plan des 5 plages du §4.2 tient tel quel. | — |
| ~~7~~ | ~~`Settings/Midi.Channel = 0` = canal 1 ou Omni ?~~ | **RÉSOLUE — FAIT : `0` = `Omni`.** `object-meta` publie `Channel.x-options.strings = ["Omni","1","2",…,"16"]`. Le Core obéit donc aux PC/CC de **n'importe quel canal**, et le Loupedeck CT est un port MIDI actif sur ce poste. Combiné à `MBCIn = true`, il suit déjà toute MIDI Clock qui traîne. **À écarter avant de diagnostiquer le moindre comportement de tempo bizarre**, et à basculer sur un canal dédié dès le bring-up validé. | — |
| ~~8~~ | ~~Écrire `Rig.Tempo` a-t-il un effet ?~~ | **RÉSOLUE — FAIT : non, `Rig.Tempo` est INERTE.** Écrit à 150 BPM avec les drapeaux par défaut, l'appareil est resté à 85,96 BPM (lu au tuner). **Le bon objet est `/Evil/Engine/Tempo`** : un `PUT {"Tempo": …}` dessus a immédiatement affiché 150,00 au tuner, `TempoMaj` a suivi, et `Rig.Tempo` s'est aligné — **sans toucher à `TempoFromMaster` ni à `MBCIn`**. Voir §4.4. | — |
| ~~9~~ | ~~Le doublage A/B préserve-t-il les queues, et à quel coût ?~~ | **RÉSOLUE — FAIT : oui, et il est quasi gratuit.** Ampli doublé (`64 Black Lux Vib` / `99 PV51 II Lead`), niveaux égalisés, bascule `Chain.DoubleSwitch` en **0,07 s** pendant qu'un accord résonne : queue préservée, décroissance normale. Coût mesuré en alterné (3 cycles concordants) : **`Switch` +2,7 pts**, `Stereo` +6,0 pts sur une base de 35 %. En `Switch` un seul ampli tourne. **Corollaire : l'affirmation du §5.1 « le doublage double le coût du bloc le plus cher » n'est vraie qu'en `Stereo`.** | — |
| 10 | Coût CPU réel par famille de blocs | **Première campagne INVALIDÉE — résultat négatif documenté.** Deux causes : (a) `setModuleTypeInternal` a déplacé l'ampli existant au lieu d'en ajouter un (§2.7), faisant chuter la base de 24 % à ~13 % en cours de série sans le signaler ; (b) **le compteur oscille de ±3 points au repos** (13 relevés sur 60 s, chaîne figée : min 11, max 14), soit l'ordre de grandeur de la plupart des coûts cherchés. Seuls `ReValver Amp` (+16) et `IR` (+9) émergent du bruit. **Protocole corrigé :** base re-mesurée AVANT et APRÈS chaque bloc, ordre aléatoire, ≥ 5 répétitions par bloc, jamais deux instances du même type, et **guitare en train de jouer** (à vérifier : le moteur consomme-t-il autant au repos ?). | le refus d'un rig trop lourd **avant** de le pousser |
| ~~11~~ | ~~Les presets de bloc sont-ils globaux ou attachés au rig ?~~ | **RÉSOLUE — FAIT : globaux au TYPE de bloc.** `blockPresets()` rend des listes strictement identiques depuis deux rigs différents. Le préfixe `+` marque les presets d'usine (`+Default`, `+Slapback`…), les autres sont des presets utilisateur partagés par toute la bibliothèque. **La convention de nommage stricte est donc obligatoire** : un preset « LEAD » créé pour une chanson apparaît dans la liste de tous les rigs. Préfixer par la `gears_key` (`fw-<artiste>-<titre>-<rôle>`). *Détail utile : `blockPresets("Amp")` rend les 53 modèles d'ampli — les « presets » du bloc Amp sont ses `Type`.* | — |
| ~~12~~ | ~~Longueur max d'un nom de rig ?~~ | **RÉSOLUE — FAIT : aucune limite de stockage.** `renameLoadedRig()` accepte 32, 40, 64 et **96 caractères** rendus intacts, sans troncature. Les 31 caractères observés sur les 118 rigs n'étaient qu'un usage. La convention `Artiste - Titre` passe donc sans contrainte. *(Reste ouverte, mais cosmétique : la troncature à l'affichage sur l'écran 4 pouces.)* | — |
| ~~13~~ | ~~Le Core énumère-t-il un port MIDI en USB-B ?~~ | **RÉSOLUE — FAIT : non, et il ne le fera jamais.** Le câble USB-B *est* branché en permanence (interface audio). Windows énumère `HeadRush Core` en classe MEDIA, `USB\VID_0763&PID_4019\<série>`, **sans aucune interface `&MI_xx`** — là où le Loupedeck CT (`&MI_02`), le GP-180 (`&MI_03`) et le FootCtrlPlus (`&MI_01`) en exposent une. Le manuel v5.1.0 confirme : USB-B = « digital audio signal » + transfert de fichiers ; le contrôle MIDI passe « **par le MIDI Input 5 broches ou la connexion USB-A** ». **Conséquence : aucun chemin MIDI PC→Core** sans interface MIDI-DIN dédiée — et l'USB-A est un port *hôte*, on ne peut pas y brancher le PC. Voir §4.1. | — |
| ~~14~~ | ~~Les sections peuvent-elles venir de la partition ?~~ | **RÉSOLUE — oui, sur les deux tiers de la bibliothèque.** 1320/1985 fichiers portent des marqueurs, 11 règles classent 92,6 % des 13 644 sections, 72 % des morceaux sont couverts intégralement (§3.3). `sections[]` devient un champ dérivé. Au passage : **toute la bibliothèque est en `.gp` GP7/8, illisible par PyGuitarPro** — passer par `fretwise.parser.gpif_adapter`. | — |
| ~~15~~ | ~~Le gabarit de slots convient-il ?~~ | **RÉSOLUE — par la statistique, pas par arbitrage.** Les 119 rigs de l'appareil ont été relevés ; sur les 39 rigs guitare, **seuls 3 (8 %) respectent un ordre total**. Le corpus impose un ordre **partiel** : tête rigide (`gate < wah < drive < ampli < cab`, 100 %), queue libre (`Cab < Delay` 57 %, `Chorus < Cab` 59 %, `Volume < Delay` 53 %), réverbe en dernier (94 %). **Ne figer que les slots 1-7** ; 8-13 libres, 14 = réverbe. Voir §5.1. | — |

---

## 8. Plan de livraison

Ordonné pour retirer l'inconnu le plus dangereux en premier, et pour que chaque phase
reste utile si la suivante ne sort jamais.

**P0 — Lecture — ✅ LIVRÉ.** `src/fretwise/devices/headrush_core/`
(`client.py`, `catalog.py`, `cli.py`), `scripts/device_probe.py`,
`scripts/device_catalog_dump.py`, 29 tests. Vérifié en direct sur l'appareil.
Catalogue généré : 278 module types, 6661 paramètres, 833 énumérations,
`contractHash` du tableau positionnel.
*Écarts par rapport au plan :* `DeviceTransport` est un `Protocol` sans membre
d'écriture (la règle est portée par le type), et la liste blanche `PURE_METHODS`
refuse tout appel de méthode mutant **avant** d'ouvrir une connexion.

**P0.5 — Une écriture prouvée à la main (une heure).** Les questions 1 à 5 du §7,
instrument sous les yeux, sur un `#FW - SCRATCH` créé à la main.
*Sans cette heure, tout ce qui suit est spéculatif.*

**P1 — Sauvegarde et diff — ✅ LIVRÉ (moitié lecture).** `snapshot.py` GET-only,
`scripts/device_backup.py`, 10 tests. Deux captures consécutives du vrai appareil
diffent à zéro : la tolérance float32 et la primitive de vérification tiennent.
*Limite structurelle découverte :* l'API n'expose que le rig **chargé**, donc
sauvegarder un autre rig exigerait `loadRig()` — une écriture. **Une sauvegarde de
toute la bibliothèque est impossible en lecture seule.** Ce qui est livré couvre le
cas qui compte : capturer le bac à sable avant que la phase d'écriture n'y touche.
La *restauration* appartient donc à P3, pas ici.

**P2 — Plan hors ligne (moyen).** `params.py` + test de parité, `chain.py`, gabarit,
`device_plan.py` produisant un plan d'écriture lisible sans toucher l'appareil.
*Livrable utile seul :* une notice de montage par morceau, applicable à la main.

**P3 — Push (moyen).** `pusher.py`, les trois verrous, le bac à sable, la boucle
fermée PUT→GET→assert. Trois morceaux, pas 1982.

**P4 — Activation (petit) — périmètre réduit.** `device_pc_alloc.py` (allocation et
`reconcile` des Program Change, écrits en HTTP) et l'export du mapping M-Vave.
**Plus de branche MIDI côté FretWise** : le Core n'a pas de port MIDI vers le PC
(§4.1). FretWise attribue les PC par HTTP ; c'est le pédalier qui les émet.
*C'est ici que la bibliothèque devient pilotable au pied.*

**P5 — Web (moyen).** `web/device_routes.py`, capacité `device_http`, SSE d'état,
panneau des 14 slots, badge de dérive, activation en un clic.

**P6 — Abstraction (petit).** `devices/base.py`, extraction des Protocols communs
au GP-180 et au Core — **seulement maintenant**, avec deux implémentations vivantes
sous les yeux.

Le compilateur `tone.intent.v1 → binding` (§3, §5.2) s'insère en P2/P3 et n'est
généralisé au corpus qu'après validation N1/N2 sur trois morceaux.
