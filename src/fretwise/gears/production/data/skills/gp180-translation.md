# Référentiels GP-180

Catalogue exhaustif des modèles et référentiels de travail du **Valeton GP-180**, organisé par module et enrichi de tables de conversion équipement réel → GP-180. Sources : screenshots de l'application d'édition officielle + documentation de travail.

<aside>
🎛️

**Objectif** — Créer une base cohérente pour traduire un équipement réel (guitare, ampli, cab, effets) vers le GP-180 en tenant compte de ses forces : **SnapTone / NAM**, **IR tierces**, **12 modules simultanés**, et **marge DSP supérieure au GP-50**. Chaque module a son propre soufflet ouvrable avec noms officiels, inspirations, charge DSP, paramètres exposés et conseils d'usage.

</aside>

<aside>
⚠️

**Règle importante** — Sur GP-180, les noms exacts des modèles peuvent varier selon le **firmware** et l'**application d'édition**. Ce référentiel donne une **méthode de conversion fiable** et des **familles d'équivalents**. Toujours **valider dans l'appareil / l'app** le nom exact du modèle disponible avant de figer un preset.

</aside>

---

# 🧩 Utilisation dans Songs Library

Cette section définit le **format standard** à utiliser quand une fiche de la base **Songs Library** doit produire une configuration **GP-180** pour une chanson et une guitare cible.

<aside>
✅

**Principe de sortie** — Une fiche chanson doit toujours distinguer : **son original recherché**, **guitare originale**, **guitare cible disponible**, **cœur sonore GP-180**, **chaîne complète**, **réglages de départ**, **compensation guitare** et **niveau de fiabilité**.

</aside>

## 🧾 Format standard d’une configuration GP-180

À utiliser comme gabarit dans les fiches chansons et dans les prompts de création / mise à jour.

```
Artiste :
Chanson :
Album / période :
Version ciblée : studio / live / reprise / autre
Guitariste :
Rôle guitare : rythmique / lead / riff / solo / mixte

Guitare originale :
Micros originaux :
Position micro :
Accordage :
Capo :
Guitare cible :
Compensation guitare :

Objectif sonore :
Référence sonore principale :
Sources utilisées :
Fiabilité : A / B / C / D

Cœur sonore GP-180 :
- SnapTone / NAM :
- AMP :
- CAB / IR :

Chaîne GP-180 :
NR → PRE → WAH → DST → N→S → AMP → CAB/IR → EQ → MOD → DLY → RVB → VOL

Réglages GP-180 :
NR :
PRE :
WAH :
DST :
N→S :
AMP :
CAB / IR :
EQ :
MOD :
DLY :
RVB :
VOL :

Notes de jeu :
Limites / compromis :
```

## 🎛️ Format court pour le tableau Settings

Quand la fiche chanson utilise un tableau compact, chaque cellule doit rester exploitable même si certains blocs sont désactivés.

| **Bloc** | **Contenu attendu** |
| --- | --- |
| NR | Actif ou Non · Modèle · Threshold / Attack / Release si applicable |
| PRE | Compresseur, boost, pitch, simulation micro/instrument · réglages essentiels |
| WAH | V-Wah / C-Wah / B-Wah / Hammy · assignation EXP · position ou plage |
| DST | Overdrive / distortion / fuzz · gain, tone, level |
| N→S | SnapTone actif ou Non · slot · nom · rôle : capture complète, ampli seul ou pédale |
| AMP | Modèle ou None · gain, bass, mid, treble, presence, level |
| CAB / IR | Cab interne, User IR ou None · niveau · justification si IR externe |
| EQ | Modèle · corrections principales · compensation guitare si nécessaire |
| MOD | Chorus, phaser, vibe, tremolo, etc. · rate/depth/mix |
| DLY | Type · time ou tempo · feedback · mix |
| RVB | Type · mix · decay · caractère |
| VOL | Niveau final · boost solo · rôle EXP si utilisé |

## 🧠 Règles minimales de décision

1. **Si une SnapTone chanson existe** dans les slots 60-101, elle est prioritaire comme point de départ.
2. **Si une SnapTone est une capture complète amp+cab**, régler **AMP = None** et **CAB = None**, sauf test contraire.
3. **Si la SnapTone correspond seulement à un ampli ou une pédale**, compléter avec **CAB / IR** et éventuellement EQ.
4. **Si aucune SnapTone pertinente n’existe**, utiliser **AMP + CAB** à partir des tables de conversion.
5. **Si le son vient surtout d’une pédale**, utiliser **PRE/DST + AMP clean ou edge-of-breakup**.
6. **Toujours documenter la guitare originale séparément de la guitare cible**.
7. **Toujours appliquer une compensation** quand la guitare cible diffère fortement de l’instrument original.
8. **Ne jamais inventer un modèle GP-180 absent de ce référentiel** : choisir le plus proche et documenter le compromis.

## 🛡️ Niveau de fiabilité

| **Niveau** | **Signification** | **Usage dans une fiche chanson** |
| --- | --- | --- |
| A — Vérifié | Donnée confirmée par documentation fiable, interview, rig rundown ou source officielle. | Le réglage peut être présenté comme très robuste. |
| B — Très probable | Plusieurs sources convergent, mais certains détails studio restent incertains. | Cas courant pour les sons historiques. |
| C — Approximation fonctionnelle | Le matériel exact est incertain, mais l’équivalent sonore GP-180 est cohérent. | À utiliser pour produire un preset jouable sans sur-vendre l’exactitude. |
| D — À confirmer | Information faible, contradictoire ou non trouvée. | Documenter clairement dans Comments / Notes. |

<aside>
⚠️

**Règle anti-régression** — Les anciennes fiches ou prompts GP-50 peuvent rester valides, mais toute nouvelle fiche destinée au GP-180 doit utiliser ce format GP-180 par défaut, sauf demande explicite de produire une configuration GP-50.

</aside>

---

## 📑 Sommaire des modules (12)

- 🟢 **NR** — Noise Reduction · 3 modèles documentés
- 🟢 **PRE** — Pre-effects · 23 modèles documentés
- 🟢 **WAH** — Wah / pitch shifter pédale · 4 modèles documentés
- 🟢 **DST** — Distortion / Overdrive / Fuzz · 26 modèles documentés (17 spécifiques + 9 partagés avec PRE)
- 🟢 **N→S** — SnapTone (NAM Captures) · 101 emplacements (1 vide + 100 captures factory & personnelles)
- 🟢 **AMP** — Amplificateurs · 58 modèles + None documentés · 2-21% DSP
- 🟢 **CAB / IR** — Cabinets et Impulse Responses · 35 modèles factory + 20 User IR + None · 22% DSP
- 🟢 **EQ** — Égaliseur · 4 modèles + None documentés · 1% DSP
- 🟢 **MOD** — Modulation · 17 modèles + None documentés · 1-35% DSP
- 🟢 **DLY** — Delay · 15 modèles + None documentés · 2-10% DSP
- 🟢 **RVB** — Reverb · 11 modèles + None documentés · 7-22% DSP
- 🟢 **VOL** — Volume / sortie / boost solo · utilitaire documenté

---

## 📋 Vue d'ensemble des blocs GP-180

| **Bloc GP-180** | **Rôle** | **Équivalent réel** | **Paramètres clés** | **Usage / Notes** |
| --- | --- | --- | --- | --- |
| NR | Réduction de bruit | Noise Gate | Threshold, release | À utiliser surtout avec sons saturés ou simple coils bruyants |
| PRE | Pré-effets dynamiques / filtre / boost / wah | Compresseur, boost, auto-wah, wah | Sustain, gain, range, Q, mix | Très utile pour funk, clean serré, ou pour pousser un ampli / SnapTone |
| DST | Overdrive / distorsion / fuzz | TS, DS-1, Dist+, fuzz, crunch box, etc. | Gain, tone, level | Utiliser en source principale de grain ou en boost devant un amp / NAM |
| AMP | Ampli modélisé interne | Familles Fender, Vox, Marshall, Mesa, ENGL, etc. | Gain, Bass, Mid, Treble, Presence, Level | Solution simple, stable, légère en DSP |
| SnapTone / NAM | Capture d'ampli | Capture réaliste d'un ampli réel | Niveau, éventuels réglages de base | Alternative premium au bloc AMP ; cœur du système GP-180 |
| CAB | Cab modélisé interne | 1x12 / 2x12 / 4x12 selon famille | Level, éventuels voicings | Pratique pour aller vite ; plus simple que gérer des IR |
| IR | Cab tiers | OwnHammer, Celestion, God's Cab, etc. | Niveau, choix du fichier | Souvent préférable avec SnapTone pour un rendu plus studio |
| EQ | Correction tonale | EQ graphique / paramétrique | Low, low-mid, mid, high-mid, high | À placer après amp / cab pour finaliser le preset |
| MOD | Modulations | Chorus, phaser, tremolo, rotary, vibrato | Depth, rate, mix | New wave, ambient, funk, textures vintage |
| DLY | Delay | Analog, digital, tape, dual, ping-pong | Time, feedback, mix | Épaisseur, lead, rythmes delay, spatialisation |
| RVB | Reverb | Room, plate, spring, hall, shimmer | Mix, decay, tone / damp | Toujours doser ; la spring est la base vintage clean |
| Utility / routing | Chaîne, volumes, assignations, pédale EXP | Switching / contrôle | Ordre, assign, mix | Le GP-180 permet une chaîne beaucoup plus flexible que le GP-50 |

---

# 🔊 Référence détaillée des modules

---

- **🟢 NR — Noise Reduction (Gate)** · 3 modèles · ~1% DSP chacun
    
    **Rôle** : portail de réduction du bruit, à placer en début de chaîne (avant DST/AMP) pour les sons saturés ou les guitares à single coils bruyantes. Charge DSP minimale (~1% par modèle). Le choix entre Gate 1/2/3 dépend du compromis entre simplicité de réglage et finesse de modulation du gate.
    
    | Modèle | Inspiration | Paramètres | Quand l'utiliser |
    | --- | --- | --- | --- |
    | Gate 1 | ISP® Decimator™ — Linearized Time Vector Processing | Threshold | Choix par défaut. Release linéaire, transparent sur la queue de note. Hi-gain, single coils bruyants. |
    | Gate 2 | Noise gate flexible générique | Threshold · Attack · Release | Métal moderne palm-muté, riffs serrés, contrôle fin attack/release. |
    | Gate 3 | Algorithme original Valeton « Inverse Expander » | Threshold · Attack · Release · Hold | Leads saturés longs, ambient saturé. Préserve sustain & dynamiques. |
    - ▸ **Gate 1** — détail
        
        **Description officielle** : Based on famous ISP® Decimator™ noise gate pedal. The Decimator features improvements in the expander tracking with their new Linearized Time Vector Processing™. This novel improvement provides a more linear release time-constant response for the exponential release curve of the downward expander.
        
        - **Threshold** — Controls the gate trigger level
        
        **Pédale d'origine** : ISP Technologies Decimator G-String II / Decimator II.
        
        **Conseil patch** : Threshold 30-40 sur SG/HB, 25-35 sur Strat. Le Linearized Time Vector évite le "pumping" classique des gates simples sur les notes longues.
        
    - ▸ **Gate 2** — détail
        
        **Description officielle** : Flexible noise gate with attack and release control.
        
        - **Threshold** — Controls the gate trigger level
        - **Attack** — Controls how soon the gate starts to process the signal
        - **Release** — Controls the noise fade-out duration time after the level drops below the threshold
        
        **Conseil patch** : utile en métal moderne pour resserrer le palm muting (Attack rapide, Release court). En clean, Attack lent + Release long pour respirer.
        
    - ▸ **Gate 3** — détail
        
        **Description officielle** : A new generation of original noise gate algorithm, the "Inverse Expander" can control noise accurately and agilely, which can not only effectively remove noise, but also retain sustain and dynamics well.
        
        - **Threshold** — Controls the gate trigger level
        - **Attack** — Controls the noise fade-out duration time after the level drops below the threshold
        - **Release** — Controls the noise fade-out
        - **Hold** — Controls the noise gate hold time for the previous state
        
        **Conseil patch** : préférer en lead saturé. Le Hold permet aux fins de notes de sustainer naturellement avant que le gate se referme. Algorithme propriétaire Valeton.
        
    
    > **Choix par défaut pour les Songs Library**
    - **Gate 1** — clean / crunch / hi-gain rythmique standard (90% des cas)
    - **Gate 2** — métal moderne palm-muté, djent, riffs serrés
    - **Gate 3** — leads saturés longs, ambient saturé
    > 

---

- **🟢 PRE — Pre-effects** · 23 modèles · 1-17% DSP
    
    **Rôle** : effets dynamiques, boosts, overdrives, filtres, pitch et simulations placés AVANT l'ampli. Module le plus riche du GP-180 (23 modèles répartis en 7 sous-catégories). À combiner avec un DST classique ou un SnapTone NAM.
    
    ## 🎚️ Compresseurs (2)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | COMP | 3% | Ross™ Compressor | Sustain · Volume |
    | COMP4 | 4% | Keeley® C4 4-knob | Sustain · Attack · Volume · Clipping |
    
    ## 🚀 Boosts / Clean boosts (4)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | Micro Boost | 5% | MXR® M133 Micro Amp2 (+20dB transparent) | Gain |
    | B-Boost | 7% | Xotic® BB Preamp (+30dB, OD creamy) | Gain · Volume · Bass · Treble |
    | 14 Boost | 1% | Fortin® Grind (+20dB tight, low noise) | Gain |
    | Boost | 5% | Xotic® EP Booster (+20dB stimulation) | Gain · +3dB · Bright |
    
    ## 🔥 Overdrives / Distortions (5)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | OD 9 | 7% | Ibanez® Tube Screamer TS9 | Gain · Tone · Volume |
    | Yellow OD | 6% | DOD® 250 / fuzz-OD vintage 70s | Gain · Volume |
    | Penesas | 17% | Klon® Centaur (transparent, amp-in-a-box) | Gain · Tone · Volume |
    | Super OD | 8% | OD asymétrique chaud (style Zendrive) | Gain · Tone · Volume |
    | Blues OD | 10% | BluesBreaker / Marshall BB | Gain · Tone · Volume |
    
    ## 🌊 Filtres / Wah (3)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | T-Wah | 3% | Mu-Tron III / Q-Tron (touch wah) | Sens · Range · Q · Mix · Mode (Guitar/Bass) |
    | A-WAH | 2% | Boss AW-3 / Auto wah | Depth · Rate · Volume · Low · High · Q · Sync |
    | Step Filter | 4% | Z.Vex Seek-Wah / EHX 8-step (synth-like) | Step 1-4 · Rate · Sync |
    
    ## 🎵 Pitch / Octave / Harmonizers (4)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | OCTA | 3% | EHX POG / Boss OC-3 (octaver poly) | Low Oct · High Oct · Dry |
    | Pitch | 4% | EHX POG / Eventide (pitch shifter poly) | Low/Hi Pitch · Dry · Low/Hi Vol |
    | P-Bend | 2% | DigiTech Drop (harmonizer) | Low/Hi Pitch · Wet · Dry · Range |
    | Hammy | 8% | DigiTech Whammy® (mono, pédale EXP) | Range · Harmony · Volume · Position |
    
    ## ✨ Spéciaux (2)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | Ring Mod | 2% | Moog MF-102 / ring modulator | Mix · Freq · Fine · Tone |
    | Saturate | 5% | Saturation bande analogique (Strymon Deco style) | Saturation · Mix · Volume · High Cut |
    
    ## 🎸 Sim instruments / pickups (3)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | AC Sim | 6% | Boss AC-3 / Fishman (acoustic simulator) | Body · Top · Volume · Mode (Standard/Jumbo/Enhanced/Piezo) |
    | H to S | 5% | Sim. Strat bridge depuis humbucker | Volume · Tone |
    | S to H | 5% | Sim. Les Paul bridge depuis single coil | Volume · Tone |
    - ▸ Détails complets des 23 modèles PRE
        
        **COMP** (Ross-style) — Based on the legendary Ross™ Compressor. Very natural and mellow compression. Sustain · Volume.
        
        **COMP4** (Keeley C4) — Recording studio-level compression. Sustain · Attack · Volume · Clipping.
        
        **Micro Boost** (MXR Micro Amp2) — Up to 20dB of transparent gain. Gain.
        
        **B-Boost** (Xotic BB Preamp) — Thick creamy OD or +30dB clean push. Gain · Volume · Bass · Treble.
        
        **14 Boost** (Fortin Grind) — +20dB of tight, aggressive boost with low noise floor. Gain.
        
        **Boost** (Xotic EP Booster) — +20dB de stimulation pure. Gain · +3dB · Bright.
        
        **OD 9** (Ibanez TS9) — Overdrive transparent emblématique. Gain · Tone · Volume.
        
        **Yellow OD** (asymétrique 70s) — Circuit asymétrique, son guitare 70s. Gain · Volume.
        
        **Penesas** (Klon Centaur) — Amp-in-a-box riche. ⚠️ 17% DSP. Gain · Tone · Volume.
        
        **Super OD** (asymétrique chaud) — OD au timbre traditionnel. Gain · Tone · Volume.
        
        **Blues OD** (BluesBreaker style) — De warm OD à full open distortion. Gain · Tone · Volume.
        
        **T-Wah** (touch wah) — Envelope filter touch-sensitive. Sens · Range · Q · Mix · Mode.
        
        **A-WAH** (auto wah) — Wah automatique. Depth · Rate · Volume · Low · High · Q · Sync.
        
        **Step Filter** (4-step synth filter) — Sons synth-like. Step 1-4 · Rate · Sync.
        
        **OCTA** (octaver poly) — Low Oct · High Oct · Dry.
        
        **Pitch** (pitch shifter) — Low/Hi Pitch · Dry · Low/Hi Vol.
        
        **P-Bend** (harmonizer DigiTech Drop) — Low/Hi Pitch · Wet · Dry · Range.
        
        **Hammy** (DigiTech Whammy) — Mono, pédale EXP. Range · Harmony · Volume · Position. ⚠️ Existe aussi dans WAH.
        
        **Ring Mod** — Spectres inharmoniques. Mix · Freq · Fine · Tone.
        
        **Saturate** (tape saturation) — Warmth analogique. Saturation · Mix · Volume · High Cut.
        
        **AC Sim** (acoustic simulator) — Body · Top · Volume · Mode (Standard/Jumbo/Enhanced/Piezo).
        
        **H to S** (humbucker → single coil) — Volume · Tone.
        
        **S to H** (single coil → humbucker) — Volume · Tone.
        
    
    > **Choix par défaut pour les Songs Library**
    - **Compresseur** : COMP pour funk/clean, COMP4 pour studio polish
    - **Boost devant ampli** : OD 9 (TS-style) en premier choix universel · 14 Boost si besoin de tightness sans coloration · Penesas pour amp-in-a-box premium
    - **Wah** : V-Wah / C-Wah dans le module **WAH** (pas ici) — le PRE T-Wah / A-WAH sert pour funk auto-wah ou ambient
    - **Pickup sim** : H to S pour avoir un quack Strat sur SG · S to H pour épaissir la Strat sur du rock
    > 

---

- **🟢 DST — Distortion / Overdrive / Fuzz** · 26 modèles · 1-17% DSP
    
    **Rôle** : cœur de saturation du signal. Place après PRE et avant AMP. 26 modèles dont 9 partagés avec PRE et 17 spécifiques DST. 6 sous-catégories : Overdrives, Distortions, Fuzz, Bass Drive, Bass Preamp, Boosts.
    
    > **Modèles partagés avec PRE** : OD 9, Yellow OD, Penesas, Super OD, Blues OD, Micro Boost, B-Boost, 14 Boost, Boost. Voir PRE pour descriptions complètes. La duplication permet de placer un boost/OD avant ET après un autre stage de saturation.
    > 
    
    ## 🔥 Overdrives (10)
    
    | Modèle | DSP | Inspiration | Paramètres | Note |
    | --- | --- | --- | --- | --- |
    | Green OD | 7% | Ibanez® TS-808 (1979) | Gain · Tone · Volume | Le TS originel — plus warm que TS9 |
    | OD 9 | 7% | Ibanez® TS9 | — | Voir PRE |
    | Yellow OD | 6% | DOD® 250 / asymétrique 70s | — | Voir PRE |
    | Penesas | 17% | Klon® Centaur | — | Voir PRE |
    | Super OD | 8% | Asymétrique chaud (Zendrive style) | — | Voir PRE |
    | Scream OD | 7% | Maxon® OD-808 / TS-style scream | Gain · Tone · Volume | — |
    | Blues OD | 10% | Marshall BluesBreaker | — | Voir PRE |
    | Force | 5% | Fulltone® OCD | Gain · Tone · Volume · Mode (HP/LP) | Tube-like, dynamique |
    | Tube Clipper | 5% | OD à lampe 12AX7 | Gain · VOL · Bass · Treble | Sustain violon, overtones riches |
    | TaiChi OD | 6% | Hermida® Zendrive® | Gain · Tone · Volume · Voice | Touch-sensitive, amp-like |
    
    ## ⚡ Distortions (6)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | Plustortion | 10% | MXR® M104 Distortion+ (Randy Rhoads) | Gain · Volume |
    | SM Dist | 12% | Boss DS-1 | Gain · Tone · Volume |
    | Darktale | 13% | ProCo™ The Rat (LM308 early) | Gain · Filter · Volume |
    | Chief | 7% | Marshall® Guv'nor (1988) | Gain · Volume · Bass/Middle/Treble |
    | La Charger | 6% | MI Audio® Crunch Box | Gain · Tone · Volume |
    | Flagman Dist | 13% | British high-gain modern dirt box | Gain · Volume · Bass/Treble · Presence · Tight |
    
    ## 💥 Fuzz (2)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | Lazaro | 17% | Electro-Harmonix® Big Muff Pi | Sustain · Tone · Volume |
    | Red Haze | 2% | Dallas-Arbiter® Fuzz Face (1966) | Fuzz · Volume |
    
    ## 🎸 Bass Drive (2) + Bass Preamp (2)
    
    | Modèle | DSP | Inspiration | Paramètres |
    | --- | --- | --- | --- |
    | Flex OD | 8% | OD/distortion guitare ET basse | Gain · Tone · Volume · Mode (Normal/Scoop/Edge) · Blend |
    | Bass OD | 10% | Drive spécifique basse | Gain · Blend · Volume · Bass/Treble |
    | Black Bass | 13% | Darkglass® Microtubes B7K | Gain · Blend · Volume · Low/Lo-mid/Hi-mid/Treble · Attack |
    | Bass Hammer | 12% | Aguilar® Tone Hammer | Gain · Master · Bass/Middle/Treble · Mid Freq · Drive |
    - ▸ Détails des modèles spécifiques DST
        
        **Green OD** (TS-808) — Premier modèle 1979, warm/mid-focused. TS808 vs TS9 : 808 plus warm, 9 plus transparent.
        
        **Force** (Fulltone OCD) — Sweet spot ampli, tones overdriven warm et full. Mode HP (plus de bottom) ou LP (sans changer le tone).
        
        **Tube Clipper** (12AX7 tube OD) — OD smooth, sustain violon. Excellent pour leads blues/fusion.
        
        **TaiChi OD** (Hermida Zendrive) — Le Dumble-in-a-box. Touch sensitivity. Voice contrôle les harmoniques.
        
        **Plustortion** (MXR Dist+) — Soft clipping germanium, Randy Rhoads. Hard rock 70s-80s.
        
        **SM Dist** (Boss DS-1) — Kurt Cobain, Joe Satriani. Disto franche.
        
        **Darktale** (ProCo Rat) — Large plage du Filter. David Gilmour à St. Vincent.
        
        **Chief** (Marshall Guv'nor) — Stack-in-a-box. Hard rock UK, NWOBHM.
        
        **La Charger** (MI Audio Crunch Box) — Distortion sensible, faible bruit en hi-gain.
        
        **Flagman Dist** (British high-gain) — Tight pour plus de modernité. Bogner / Friedman / Diezel territory.
        
        **Lazaro** (Big Muff Pi) — Wall-of-sound. Smashing Pumpkins, Pink Floyd.
        
        **Red Haze** (Fuzz Face) — Hendrix, Gilmour. Réagit au volume guitare.
        
        **Flex OD** — Mode Normal/Scoop/Edge. Blend garde l'attaque dry sur basse.
        
        **Bass OD** — Préserve dynamique basse. Aussi utilisable en boost.
        
        **Black Bass** (Darkglass B7K) — Référence métal moderne basse. Attack=Boost = pick definition.
        
        **Bass Hammer** (Aguilar Tone Hammer) — Préamp warm basse. Drive on = grit subtil.
        
    
    > **Choix par défaut pour les Songs Library**
    - **Crunch 70s/80s** : Plustortion ou SM Dist
    - **Hi-gain moderne** : Flagman Dist ou La Charger
    - **Alt rock / indie** : Darktale (Rat)
    - **OD transparent** : Green OD (TS808) ou OD 9 (TS9)
    - **OD warm / amp-like** : TaiChi OD, Force (OCD)
    - **Fuzz vintage** : Red Haze (Fuzz Face) pour Hendrix, Lazaro (Big Muff) pour Gilmour
    - **Basse métal** : Black Bass · **Basse jazz/funk** : Bass Hammer
    > 

---

- **🟢 WAH — Wah pédale d'expression** · 4 modèles · 3-8% DSP
    
    **Rôle** : wah commandé par la pédale d'expression externe (1/4" TRS). ⚠️ Toujours assigner la position à l'EXP avant d'activer le module.
    
    | Modèle | DSP | Inspiration | Caractère sonore |
    | --- | --- | --- | --- |
    | V-Wah | 3% | VOX® V846 | Premier wah — amplitude faible, médium-aigu, expressif vocal |
    | C-Wah | 3% | Dunlop® CryBaby® | Wah 60s classique — bas-médium, amplitude modérée, timbre neutre |
    | B-Wah | 3% | Wah dédié basse | Plage adaptée à la basse |
    | Hammy | 8% | DigiTech Whammy® | Pitch shifter mono pédale (cf. PRE) |
    
    > **Choix par défaut** : **C-Wah** universel (Hendrix, Slash, Kirk Hammett) · **V-Wah** funk/leads expressifs · **B-Wah** basse uniquement · **Hammy** pitch wah Tom Morello / Buckethead
    > 

---

- **🟢 N→S — SnapTone (NAM Captures)** · 101 emplacements · DSP variable
    
    **Rôle** : captures NAM (Neural Amp Modeler). Contenu **entièrement personnalisable** : chaque slot peut accueillir une capture officielle Valeton, TONE3000, ou personnelle.
    
    **Position dans la chaîne** : NR → PRE → WAH → DST → **N→S** → AMP → CAB → EQ → MOD → DLY → RVB → VOL
    
    Deux usages typiques :
    
    - **Seule** : désactiver AMP et CAB, la SnapTone fournit le son complet
    - **Stacking** : conserver AMP + CAB et utiliser la SnapTone comme préamp tone (rare)
    
    ## 🎸 Captures amplis guitare classiques · slots 02-29 & 36-45
    
    | # | Nom | Catégorie | Inspiration |
    | --- | --- | --- | --- |
    | 02 | Dark CL | Clean | Marshall JTM45 / 1987X |
    | 03 | Band CL | Clean | Friedman BE / Two-Rock clean |
    | 04 | Match 35 CL | Clean | Matchless DC-30 / SC-30 clean |
    | 05 | EV53 CH1 | Clean | EVH 5150-III · canal 1 |
    | 06 | Mess JP2C CH1 | Clean | Mesa Boogie JP-2C · canal 1 |
    | 07 | ARC OD | OD | Diezel VH4 / boutique high-gain (à confirmer) |
    | 08 | Bad KT OD | OD | Bad Cat-style OD à lampes KT (à confirmer) |
    | 09 | Band OD | OD | Friedman BE-100 OD |
    | 10 | Boger OD | OD | Bogner Ecstasy · Plexi/Blue |
    | 11 | Dark OD | OD | Marshall OD — JCM800 / 1987X |
    | 12 | EV53 CH2 | Crunch | EVH 5150-III · canal 2 |
    | 13 | Hiway OD | OD | Hiwatt DR504 / DR103 |
    | 14 | Match 35 OD | OD | Matchless DC-30 OD |
    | 15 | Mess JP2C CH2 | OD | Mesa JP-2C · canal 2 |
    | 16 | ToneK OD | OD | Tone King Imperial OD |
    | 17 | UK Force | OD | Marshall JCM800 |
    | 18 | Boger LD | Lead | Bogner Ecstasy · Lead Red |
    | 19 | Eagle RB | Lead | ENGL Powerball — Rhythm Blue |
    | 20 | Eagle Sava | Hi-gain | ENGL Savage 120 |
    | 21 | Eagle SM | Hi-gain | ENGL Steve Morse Signature 100 |
    | 22 | EV53 CH3 | Hi-gain | EVH 5150-III · canal 3 |
    | 23 | Flagman BE | Hi-gain | Friedman BE-100 (lead) |
    | 24 | H&K 40 LD | Lead | Hughes & Kettner TubeMeister 40 |
    | 25 | Mess JP2C CH3 | Lead | Mesa JP-2C · canal 3 |
    | 26 | Rev Green | OD | Revv Generator 120 · canal 2 |
    | 27 | Rev Purple | Lead | Revv Generator 120 · canal 3 |
    | 28 | Rev Red | Hi-gain | Revv Generator 120 · canal 4 |
    | 29 | Victor Krak | Hi-gain | Victory V4 Kraken |
    | 36 | Twin Rock JM | Clean / OD | Two-Rock / John Mayer Sig |
    | 37 | Dark DLX | OD | Marshall 1987X Deluxe (Plexi reissue) |
    | 38 | Dark PRI | OD | Marshall 1959SLP Plexi |
    | 39 | Foxy CL | Clean | Friedman Smallbox / Fender boutique clean (à confirmer) |
    | 40 | Foxy OD | OD | Friedman Smallbox / Fender boutique OD (à confirmer) |
    | 41 | J-120 Bright | Clean | Roland JC-120 Jazz Chorus (Bright) |
    | 42 | Juice Rock50 | Hi-gain | Diezel Herbert / boutique 50W rock (à confirmer) |
    | 43 | L-Star CH1 | Clean | Mesa LoneStar · canal 1 |
    | 44 | L-Star CH2 | Crunch | Mesa LoneStar · canal 2 |
    | 45 | UK 900 | OD | Marshall JCM900 |
    
    ## 🎚️ Captures pédales · slots 30-35
    
    | # | Nom | Inspiration |
    | --- | --- | --- |
    | 30 | 14 OD | Fortin Grind / OD serré |
    | 31 | Force OCD | Fulltone OCD |
    | 32 | Glass Bass Pre | Préamp basse boutique (Glassmaster) |
    | 33 | J-RAY OD | J. Rockett Archer (Klon-style) |
    | 34 | KOT OD | Analog Man King of Tone |
    | 35 | Mouse DST | ProCo Rat |
    
    ## 🎵 Captures amplis basse · slots 46-51
    
    | # | Nom | Inspiration |
    | --- | --- | --- |
    | 46 | AMPG BASS | Ampeg SVT |
    | 47 | AGUI BASS | Aguilar DB751 / Tone Hammer |
    | 48 | Hark BASS | Hartke LH500 (clean) — à confirmer |
    | 49 | Hark OD BASS | Hartke LH500 (overdriven) — à confirmer |
    | 50 | MATT BASS | Markbass / boutique bass (à confirmer) |
    | 51 | SBE BASS | SansAmp Bass Driver / Studio Bass (à confirmer) |
    
    ## 🎸 Amplis guitare modernes & boutique · slots 52-59
    
    | # | Nom | Catégorie | Inspiration |
    | --- | --- | --- | --- |
    | 52 | AC30H | Crunch | Vox AC30 Hot Rod |
    | 53 | BluesJunio | Crunch | Fender Blues Junior |
    | 54 | BuddaNoonB | OD | Budda Twinmaster / Noonworth mod (à confirmer) |
    | 55 | KochEdge | OD | Koch Powertone « Edge » (à confirmer) |
    | 56 | ModdedSLOC | Clean | Soldano SLO-100 modifié · clean |
    | 57 | ModdedSLOO | Hi-gain | Soldano SLO-100 modifié · OD |
    | 58 | Noon5150 | Hi-gain | EVH 5150 modifié Noon Custom |
    | 59 | Recto | Hi-gain | Mesa Dual / Triple Rectifier |
    
    ## ⭐ SnapTones « tonalité morceau » · slots 60-101
    
    | # | Nom | Morceau / référence | Artiste |
    | --- | --- | --- | --- |
    | 60 | StealthyBl | Friedman Stealth (Blue) | — |
    | 61 | StealthyRe | Friedman Stealth (Red) | — |
    | 62 | AnotherBri | Another Brick in the Wall, Pt. 2 | Pink Floyd |
    | 63 | CarryOnMy | Carry On My Wayward Son | Kansas |
    | 64 | HoldTheLin | Hold The Line | Toto |
    | 65 | HotelCalif | Hotel California | Eagles |
    | 66 | ILoveRNR | I Love Rock 'n' Roll | Joan Jett |
    | 67 | KillerQuee | Killer Queen | Queen |
    | 68 | LaGrange | La Grange | ZZ Top |
    | 69 | Limelight | Limelight | Rush |
    | 70 | MySharona | My Sharona | The Knack |
    | 71 | WalkThisWa | Walk This Way | Aerosmith |
    | 72 | BlackBetty | Black Betty | Ram Jam |
    | 73 | Boston | More Than a Feeling | Boston |
    | 74 | DontStopBe | Don't Stop Believin' | Journey |
    | 75 | FreebirdGa | Free Bird (rythmique) | Lynyrd Skynyrd |
    | 76 | IWantItAll | I Want It All | Queen |
    | 77 | KissAllNit | Rock and Roll All Nite | KISS |
    | 78 | Mississipi | Mississippi Queen | Mountain |
    | 79 | MoneyForNo | Money For Nothing | Dire Straits |
    | 80 | StairwaySo | Stairway to Heaven | Led Zeppelin |
    | 81 | StillGotTh | Still Got The Blues | Gary Moore |
    | 82 | SweetHomeA | Sweet Home Alabama | Lynyrd Skynyrd |
    | 83 | MasterOfPu | Master Of Puppets | Metallica |
    | 84 | EnterSandm | Enter Sandman | Metallica |
    | 85 | 80sClean | Clean 80s (générique) | — |
    | 86 | FunkyRhyth | Funk rhythm (générique) | — |
    | 87 | JazzClean | Jazz clean (générique) | — |
    | 88 | Lead | Lead (générique) | — |
    | 89 | Matchless | Matchless DC-30 (générique) | — |
    | 90 | Metal5150 | Métal type EVH 5150 | — |
    | 91 | ModernMeta | Métal moderne (djent/progressive) | — |
    | 92 | RockRhythm | Rock rhythm (générique) | — |
    | 93 | SLO100 | Soldano SLO-100 (générique) | — |
    | 94 | TimPierce | Tim Pierce — session guitarist signature | Tim Pierce |
    | 95 | CherryPie | Cherry Pie | Warrant |
    | 96 | CrazyTrain | Crazy Train | Ozzy (Randy Rhoads) |
    | 97 | DefLeppard | Pour Some Sugar / Photograph | Def Leppard |
    | 98 | DrFeelgood | Dr. Feelgood | Mötley Crüe |
    | 99 | HeManWoman | Référence à confirmer | — |
    | 100 | RockYouLik | Rock You Like a Hurricane | Scorpions |
    | 101 | StillOfNig | Still of the Night | Whitesnake |
    
    > **Tips SnapTone**
    - **N→S « tout-en-un »** : désactiver AMP + CAB si la capture inclut déjà ampli + cab.
    - **N→S ampli seul** : régler AMP = None, garder CAB / IR actif.
    - **N→S pédale / drive** : utiliser la SnapTone comme étage de gain, puis AMP + CAB adaptés.
    - **Direct match morceau→SnapTone** : les slots 60-101 sont pré-mappés à des classiques ; utiliser ces slots en priorité si la chanson correspond.
    - **Suffixes** : `CL` = Clean · `OD` = Overdrive · `LD` = Lead · `CH1`/`CH2`/`CH3` = canaux · `Re`/`Bl` = Red/Blue.
    - **Si le rôle exact de la capture est incertain** : documenter `Fiabilité : C` et tester avec AMP/CAB Off puis avec CAB actif.
    - **Slot 99 (HeManWoman)** : référence à clarifier ; ne pas l'utiliser comme correspondance chanson fiable sans validation.
    > 
    
    ## 🧭 Décision rapide SnapTone dans Songs Library
    
    | **Cas rencontré** | **Réglage recommandé** | **À documenter** |
    | --- | --- | --- |
    | Slot 60-101 correspond exactement au morceau | N→S actif prioritaire ; AMP/CAB selon rôle de la capture | Slot, nom, chanson, fiabilité B ou C selon source |
    | Capture nommée comme un ampli / canal | N→S actif · AMP = None · CAB/IR actif | Cab choisi et raison |
    | Capture probablement full rig | N→S actif · AMP = None · CAB = None | Préciser “full rig supposé” si non vérifié |
    | Capture pédale / OD | N→S avant AMP + CAB | Rôle : drive / boost / couleur |
    | Aucune capture pertinente | N→S = Non · construire AMP + CAB | Modèles GP-180 choisis par conversion |

---

- **🟢 AMP — Amplificateurs** · 58 modèles + None · 2-21% DSP
    
    **Rôle** : cœur de l'amplification modélisée. Après NR/PRE/WAH/DST/N→S, avant CAB/IR/EQ.
    
    ## 🚫 Bypass
    
    **None** (0% DSP) — À utiliser avec SnapTone full rig, capture NAM amp+cab, ou ampli externe.
    
    ## 🇺🇸 Cleans / edge-of-breakup US & Tweed
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | Tweedy | 8% | Fender® Tweed Deluxe | Blues, country, rock'n'roll, edge-of-breakup |
    | Bellman 59N | 9% | Fender® Bassman '59 — Normal | Blues, rock vintage, base clean/crunch |
    | Bellman 59B | 9% | Fender® Bassman '59 — Bright | Roots rock, blues lead |
    | Dark Twin | 10% | Fender® Twin Blackface — sombre | Clean US large, surf, country, jazz |
    | Silver Twin | 14% | Fender® Twin Reverb Silverface | Clean headroom élevé, funk, pop, pedal platform |
    | SUPDual CL | 15% | Supro® Dual-Tone — clean | Clean roots, garage, blues vintage |
    | SUPDual OD | 16% | Supro® Dual-Tone — overdrive | Crunch roots, slide, rock vintage |
    | J-120 CL | 2% | Roland® JC-120 Jazz Chorus | Clean ultra-propre, chorus 80s, funk, new wave |
    
    ## 🇬🇧 Vox / Matchless / boutique chime
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | Foxy 30N | 10% | Vox® AC30 — Normal | Clean/crunch british, Beatles, indie |
    | Foxy 30TB | 13% | Vox® AC30 Top Boost | Brian May, U2, jangly pop |
    | Match CL | 8% | Matchless® DC-30 — clean | Clean boutique, indie/ambient |
    | Match OD | 8% | Matchless® DC-30 — overdrive | Crunch boutique, leads chantants |
    | Bad-KT CL | 13% | Bad Cat® — clean | Clean boutique large |
    | Bad-KT OD | 14% | Bad Cat® — overdrive | Crunch épais, classic rock moderne |
    | Z38 CL | 10% | Dr. Z® — clean | Clean roots, country-rock, Americana |
    | Z38 OD | 14% | Dr. Z® — overdrive | Crunch roots, blues-rock |
    
    ## 🎩 Dumble / Two-Rock / boutique smooth
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | L-Star CL | 10% | Mesa Boogie® Lone Star — clean | Blues, pop, base pédales |
    | L-Star OD | 9% | Mesa Boogie® Lone Star — OD | Blues-rock, leads chauds |
    | BogSV CL | 12% | Bogner® Shiva — clean | Clean boutique sombre |
    | BogSV OD | 12% | Bogner® Shiva — OD | Crunch/lead boutique |
    | Bog BlueV | 14% | Bogner® Ecstasy Blue — vintage | Crunch vintage, Plexi boutique |
    | Bog BlueM | 14% | Bogner® Ecstasy Blue — modern | Crunch moderne, rock serré |
    | Bog RedV | 14% | Bogner® Ecstasy Red — vintage | Lead saturé vintage, hard rock |
    | Bog RedM | 14% | Bogner® Ecstasy Red — modern | Lead moderne, high-gain boutique |
    | Knight's CL | 11% | Tone King® / Dumble-style clean | Clean boutique, blues, John Mayer-like |
    | Knight's CL+ | 12% | Tone King® clean poussé | Edge-of-breakup boutique |
    | Knight's OD | 11% | Dumble / Tone King OD | Lead fusion, blues moderne |
    | Juice Ri100 | 8% | Hiwatt® DR103 / rig clean | Clean dynamique, The Who / Gilmour |
    
    ## 🇬🇧 Marshall / UK classic & hard rock
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | UK 45 | 18% | Marshall® JTM45 | Blues-rock, rock 60s |
    | UK 45+ | 20% | Marshall® JTM45 poussé | Crunch plus saturé |
    | UK 45JP | 20% | Marshall® JTM45 / Jimmy Page | Led Zeppelin, rock 70s |
    | UK 50 | 19% | Marshall® Plexi 50W | AC/DC, blues-rock |
    | UK 50+ | 20% | Marshall® Plexi 50W poussé | Hard rock, leads vintage |
    | UK 50JP | 21% | Marshall® Plexi / Jimmy Page | Led Zeppelin, hard rock 70s |
    | UK SLP | 12% | Marshall® Super Lead Plexi 1959SLP | Van Halen early avec boost |
    | UK 800 | 10% | Marshall® JCM800 | Hard rock 80s, punk |
    | UK 900 | 8% | Marshall® JCM900 | Rock 90s, hard rock serré |
    
    ## 🔥 High-gain moderne / US / boutique
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | Solo100 CL | 10% | Soldano® SLO-100 — clean | Clean US moderne |
    | Solo100 OD | 16% | Soldano® SLO-100 — OD | Lead 80s/90s, hard rock |
    | Solo100 LD | 12% | Soldano® SLO-100 — lead | Lead saturé, shred |
    | Flagman 1 | 14% | Friedman® BE | Rock moderne, gain serré |
    | Flagman +1 | 14% | Friedman® BE/HBE — gain+ | High-gain British moderne |
    | Mess2C+ 1 | 12% | Mesa/Boogie® Mark IIC+ — voicing 1 | Metallica-like, lead Mark |
    | Mess2C+ 2 | 12% | Mesa/Boogie® Mark IIC+ — voicing 2 | Rythmique metal serrée |
    | Mess 2C+ 3 | 12% | Mesa/Boogie® Mark IIC+ — voicing 3 | Lead Mark saturé, metal/prog |
    | Mess LD | 14% | Mesa/Boogie® Mark lead | Lead US saturé |
    | Mess DualV | 19% | Mesa/Boogie® Dual Recto — Vintage | Nu-metal, grunge, rock US massif |
    | Mess DualM | 19% | Mesa/Boogie® Dual Recto — Modern | Metal moderne, palm-mutes serrés |
    | EV 51 | 12% | EVH® 5150 / Peavey® 5150 | Van Halen, metal moderne |
    | Eagle 120 | 11% | ENGL® Savage / Powerball | Metal européen serré, prog |
    | Power LD | 10% | ENGL® Powerball Lead | Lead metal moderne |
    | Dizz VH | 19% | Diezel® VH4 | Metal moderne, Tool-like |
    
    ## 🎵 Basse / préamplis utilitaires
    
    | Modèle | DSP | Inspiration | Usage |
    | --- | --- | --- | --- |
    | Classic Bass | 2% | Préampli basse classique | Basse clean vintage |
    | Foxy Bass | 2% | Préampli basse Vox/UK | Basse vintage plus médium |
    | Mess Bass | 10% | Mesa/Boogie® Bass | Basse moderne, rock/metal |
    | Mini Bass | 8% | Mini préampli basse moderne | Son direct polyvalent |
    | Bass Pre | 3% | Préampli basse générique | Correction/level basse |
    | AC Pre | 2% | Préampli acoustique | Guitare acoustique, piezo |
    
    > **Choix par défaut pour les Songs Library**
    - **Clean polyvalent** : Silver Twin ou J-120 CL
    - **Blues / roots** : Tweedy ou Bellman 59N/59B
    - **Vox / Brit chime** : Foxy 30TB ou Match CL
    - **Classic rock 70s** : UK 45, UK 50 ou UK SLP
    - **Hard rock 80s** : UK 800, Solo100 OD/LD ou Flagman 1
    - **Metallica / Mark-series** : Mess2C+ 2 ou 3, ou SnapTone direct
    - **Recto / nu-metal** : Mess DualV ou Mess DualM
    - **Metal moderne serré** : EV 51, Eagle 120, Power LD, Dizz VH
    - **Avec SnapTone full rig** : AMP = **None**
    > 

---

- **🟢 CAB / IR — Cabinets et Impulse Responses** · 35 factory + 20 User IR + None · 22% DSP
    
    **Rôle** : simulation de baffle / haut-parleurs / micro après AMP ou SnapTone. Presque tous à **22% DSP**.
    
    ## 🇺🇸 Fender / Tweed / US
    
    | Modèle | Inspiration | Usage |
    | --- | --- | --- |
    | LUX 1x12 | Fender® Deluxe Reverb 1x12 | Clean US, blues, country, pop |
    | TWD LUX 1x12 | Fender® Tweed Deluxe 1x12 | Blues roots, rock'n'roll |
    | Twin 2x12 | Fender® Twin Reverb 2x12 | Clean large, funk, surf, jazz |
    | Bellman 4x10 | Fender® Bassman 4x10 | Blues, rock vintage |
    | Bellman 2x12 | Fender® Bassman 2x12 | Blues-rock, roots |
    | L-Star 2x12 | Mesa Boogie® Lone Star 2x12 | Clean/drive US moderne |
    
    ## 🇬🇧 Vox / Matchless / UK chime
    
    | Modèle | Inspiration | Usage |
    | --- | --- | --- |
    | Foxy 1x12 | Vox® AC 1x12 | Chime compact, indie, pop |
    | Foxy 2x12 | Vox® AC30 2x12 Blue | Beatles, Brian May, U2 |
    | L-120 2x12 | Roland® JC-120 2x12 | Clean 80s, chorus, funk |
    
    ## 🇬🇧 Marshall / classic rock
    
    | Modèle | Inspiration | Usage |
    | --- | --- | --- |
    | UK 2x12 | Marshall® 2x12 | Crunch britannique focalisé |
    | UK Vintage 4x12 | Marshall® Greenback 4x12 | Plexi, hard rock 70s, AC/DC |
    | UK Basket 4x12 | Marshall® Basketweave 4x12 | Rock 60s/70s, mids boisés |
    | UK 30 4x12 | Marshall® 4x12 Vintage 30 | Rock agressif, hard rock |
    
    ## 🎩 Boutique / high-gain / modern
    
    | Modèle | Inspiration | Usage |
    | --- | --- | --- |
    | REV 2x12 | Revv® 2x12 | Rock moderne, high-gain compact |
    | Bog 2x12 | Bogner® 2x12 | Boutique rock, leads modernes |
    | Bog 4x12 | Bogner® 4x12 | High-gain boutique |
    | Mess 4x12 | Mesa/Boogie® Rectifier 4x12 V30 | Metal, nu-metal, hard rock US |
    | Dizz 4x12 | Diezel® 4x12 | Metal moderne, riffs serrés |
    | Eagle 4x12 | ENGL® 4x12 | Metal européen, prog |
    | Flagman 4x12 | Friedman® 4x12 | Hard rock moderne, British high-gain |
    | Solo 4x12 | Soldano® 4x12 | Lead 80s/90s, shred |
    | Juice 4x12 | Hiwatt® 4x12 | Clean puissant, Gilmour-like |
    
    ## 🎵 Cabinets basse
    
    | Modèle | Inspiration | Usage |
    | --- | --- | --- |
    | AMPG 2x12 | Ampeg® 2x12 | Basse compacte, rock/pop |
    | AMPG 4x10 | Ampeg® 4x10 | Basse rock/funk, attaque rapide |
    | AMPG 8x10 | Ampeg® SVT 8x10 "fridge" | Basse rock classique, gros volume |
    | MATT 2x12 | Markbass® 2x12 | Basse moderne, articulation claire |
    | MATT 2x10 | Markbass® 2x10 | Basse rapide, funk, pop |
    | Tracy 4x10 | Trace Elliot® 4x10 | Basse 80s/90s, rock/funk |
    | Mess BS 1x12 | Mesa® bass 1x12 | Basse compacte moderne |
    | Mess BS 2x10 | Mesa® bass 2x10 | Basse moderne, rock/pop/funk |
    
    ## 🎸 Cabinets acoustiques
    
    AC · OM · JUMBO · Bird (Hummingbird-style) · GA (Grand Auditorium) — tous 22% DSP.
    
    ## 📥 User IR 1-20
    
    20 emplacements libres (22% DSP chacun). Format : WAV mono, 48 kHz, 1024/2048 points.
    
    > **Choix par défaut**
    - **Clean Fender** : LUX 1x12 ou Twin 2x12
    - **Blues / roots** : TWD LUX 1x12 ou Bellman 4x10
    - **Vox / chime** : Foxy 2x12
    - **Classic rock 70s** : UK Vintage 4x12 ou UK Basket 4x12
    - **Hard rock / Marshall 80s** : UK 30 4x12 ou Flagman 4x12
    - **Metal moderne** : Mess 4x12 ou Dizz 4x12
    - **Basse rock** : AMPG 8x10
    - **Acoustic** : AC ou OM
    - **Avec SnapTone full rig** : CAB = **None**
    > 

---

- **🟢 EQ — Égaliseurs** · 4 modèles + None · 1% DSP
    
    **Rôle** : correction tonale post-amp / post-cab. Très léger (1% DSP).
    
    | Modèle | Bandes | Usage |
    | --- | --- | --- |
    | Guitar EQ 1 | 125Hz · 400Hz · 800Hz · 1.6kHz · 4.4kHz · Volume | EQ guitare généraliste. Corriger graves/bas-médiums, présence et brillance. |
    | Guitar EQ 2 | 100Hz · 500Hz · 1kHz · 3kHz · 6kHz · Volume | EQ guitare plus moderne/brillant. Attaque, présence haute, air du son. |
    | Bass EQ 1 | 33Hz · 150Hz · 600Hz · 2kHz · 8kHz · Volume | EQ dédié basse. Sub, rondeur, médiums, attaque, brillance. |
    | Mess EQ | 80Hz · 240Hz · 750Hz · 2.2kHz · 6.6kHz · Volume | EQ 5-bandes Mesa/Boogie. Classique son Boogie en "V". |
    
    > **Choix par défaut** : Guitar EQ 1 (correction générale) · Guitar EQ 2 (sons modernes) · Bass EQ 1 (basse) · Mess EQ (Metallica / Mesa Mark / high-gain scooped)
    > 

---

- **🟢 MOD — Modulations** · 17 modèles + None · 1-35% DSP
    
    **Rôle** : effets de modulation après AMP/CAB/EQ.
    
    | Modèle | DSP | Famille | Inspiration | Usage |
    | --- | --- | --- | --- | --- |
    | G-Chorus | 6% | Chorus | Chorus guitare généraliste | Clean pop/rock, arpèges larges |
    | C-Chorus | 5% | Chorus | Chorus classique CE / analog | 80s, clean brillant, new wave |
    | B-Chorus | 5% | Chorus | Chorus basse | Basse fretless/funk/pop |
    | Jet | 3% | Flanger | Flanger / jet guitare | Rock 70s/80s, Van Halen-like |
    | B-Jet | 4% | Flanger | Flanger basse | Basse funk/rock |
    | V-Roto | 5% | Rotary | Rotary speaker / Leslie | Clean organique, blues, soul |
    | Vibrato | 3% | Vibrato | Vibrato pitch modulation | Indie, surf, lo-fi |
    | O-Phase | 4% | Phaser | MXR Phase 90 | Classic rock, funk, Van Halen clean |
    | Vibe | 12% | Univibe | Uni-Vibe optique | Hendrix, Gilmour, psyché blues-rock |
    | O-Trem | 3% | Tremolo | Tremolo optique / vintage | Surf, country, blues |
    | Sine Trem | 2% | Tremolo | Tremolo sinusoidal | Ambient, pulsation régulière |
    | Triangle Trem | 4% | Tremolo | Tremolo triangle | Plus marqué, indie/alt |
    | Bias Trem | 3% | Tremolo | Tremolo bias d'ampli à lampes | Vintage amp-like, roots, blues |
    | Detune | 3% | Pitch | Micro pitch / detune stéréo | Épaissir sans chorus audible, leads 80s |
    | Auto Swell | 1% | Volume | Volume swell automatique | Effet violoning, ambient |
    | Hold | 1% | Sustain | Maintien / sustain figé simple | Textures drone |
    | Freeze | 35% | Sustain | EHX Freeze / sustain infini | Ambient, pads, drones. ⚠️ Très gourmand DSP |
    
    > **Choix par défaut** : C-Chorus (clean 80s) · O-Phase (funk) · Vibe (Hendrix/Gilmour) · Bias Trem (surf/blues) · Detune (leads larges) · None (hi-gain rythmique)
    > 

---

- **🟢 DLY — Delays** · 15 modèles + None · 2-10% DSP
    
    
    | Modèle | DSP | Famille | Inspiration | Usage |
    | --- | --- | --- | --- | --- |
    | BBD Delay S | 10% | Analogique | Delay bucket brigade | Répétitions chaudes et sombres, leads vintage |
    | Digital Delay S | 6% | Digital | Delay digital propre | Répétitions nettes, rythmiques modernes |
    | Pure | 2% | Minimal | Delay simple / minimal | Épaissir discrètement |
    | Tape | 8% | Analogique | Echo bande / tape echo | Rock vintage, leads chantants |
    | Slapback | 2% | Court | Slapback court | Rockabilly, country, blues |
    | Tube Echo | 3% | Vintage | Echo à caractère tube | Leads old-school |
    | Ping Pong | 3% | Stéréo | Delay stéréo ping-pong | Largeur stéréo, pop moderne, ambient |
    | Sweep Echo | 7% | Spécial | Delay avec balayage tonal | Textures animées, psyché |
    | Ring Echo | 6% | Spécial | Echo modulé / résonant | Textures expérimentales |
    | 999 Echo | 4% | Long | Delay longue course | Répétitions longues, ambient |
    | Vintage Rack | 6% | Studio | Delay rack vintage 80s | Leads 80s, son studio |
    | Dual Echo | 3% | Multi | Delay double tête | Rythmiques syncopées, lead plus dense |
    | Sweet Echo | 9% | Ambient | Delay doux / lissé | Leads chantants, clean enveloppant |
    | Rev Echo | 5% | Ambient | Delay + queue de reverb | Ambient léger, patches simples |
    
    > **Choix par défaut** : Digital Delay S (lead polyvalent) · Tape (rock classique) · Slapback (rockabilly/country) · Ping Pong (stéréo) · Sweet Echo ou Rev Echo (ambient) · None (hi-gain rythmique)
    > 

---

- **🟢 RVB — Reverbs** · 11 modèles + None · 7-22% DSP
    
    
    | Modèle | DSP | Famille | Usage |
    | --- | --- | --- | --- |
    | Room | 7% | Petit espace | Ambiance courte et naturelle |
    | Hall | 7% | Moyen espace | Ballades, clean, leads chantants |
    | Church | 7% | Grand espace | Textures aériennes, ambient |
    | Concert | 12% | Grande room | Ampleur sans cathédrale |
    | Plate | 8% | Studio | Lead défini, voix chantante |
    | Spring | 8% | Ampli | Surf, blues, country, clean vintage |
    | Tube Spring | 22% | Spring riche | Vintage, roots, ampli poussé. ⚠️ Très gourmand |
    | N-Star | 7% | Moderne | Ambiances planantes, cinématiques |
    | Deepsea | 7% | Moderne | Ambient sombre, post-rock |
    | Sweet Space | 7% | Moderne | Clean large, pop moderne |
    | Shimmer | 14% | Ambient | Reverb + octave montante, post-rock, ambient éthéré |
    
    > **Choix par défaut** : Room (discret) · Spring (vintage) · Hall (ballades) · Plate (leads) · Shimmer (ambient) · None (sons secs, hi-gain)
    > 
    
    ## 🎚️ Règles de dosage RVB pour Songs Library
    
    | **Contexte** | **RVB recommandée** | **Réglage de départ** | **Notes** |
    | --- | --- | --- | --- |
    | Rythmique rock / hard rock | Room ou None | Mix 5-12 · Decay court | Éviter de flouter les riffs. |
    | Clean vintage / blues / surf | Spring | Mix 12-25 · Decay moyen | Base Fender / roots / country. |
    | Lead chantant | Plate ou Hall | Mix 12-20 · Decay moyen | Plate garde la définition ; Hall élargit davantage. |
    | Ballade / solo large | Hall ou Concert | Mix 15-25 · Decay moyen-long | À coupler avec delay discret. |
    | Ambient / post-rock | Shimmer, Deepsea, Sweet Space | Mix 25-45 · Decay long | Attention au DSP et à la lisibilité. |
    | Hi-gain serré | None ou Room très faible | Mix 0-8 | Delay uniquement sur lead si besoin. |

---

- **🟢 VOL — Volume / sortie / boost solo** · utilitaire · DSP négligeable ou nul
    
    **Rôle** : contrôler le niveau final du patch, créer un boost solo, ou affecter un contrôle de volume à une pédale d'expression. Le bloc VOL ne doit pas servir à corriger un mauvais gain staging : il finalise une chaîne déjà équilibrée.
    
    ## Usages principaux
    
    | **Usage** | **Position recommandée** | **Réglage de départ** | **Notes Songs Library** |
    | --- | --- | --- | --- |
    | Niveau final du patch | Fin de chaîne | Level 55-65 | Équilibrer tous les presets au même volume perçu. |
    | Boost solo | Après AMP/CAB/EQ, avant ou après DLY/RVB selon effet voulu | +3 à +6 dB équivalent | Après DLY/RVB = tout monte ; avant DLY/RVB = queues plus naturelles. |
    | Volume pédale EXP | Avant DLY/RVB pour swells naturels | Min 0 · Max 100 | Permet fade-in / violoning sans couper les queues de delay/reverb. |
    | Mute / sécurité | Fin de chaîne | Min 0 | Utile si assigné à un footswitch ou EXP. |
    
    ## Placement recommandé
    
    - **Volume général** : tout à la fin.
    - **Volume swell** : avant DLY/RVB pour conserver les répétitions et la reverb.
    - **Boost solo rock/lead** : après EQ ; tester avant ou après DLY/RVB selon le morceau.
    - **Ne pas utiliser VOL** pour compenser un AMP trop faible ou une DST trop forte : ajuster d'abord Level des blocs concernés.
    
    ## Format à écrire dans une fiche chanson
    
    ```
    VOL : Level 60 · rôle = niveau final
    VOL : Boost solo +4 dB · assign FS · placé après EQ
    VOL : EXP volume · Min 0 / Max 100 · placé avant DLY/RVB
    ```
    
    > **Choix par défaut Songs Library** : VOL = Level 60 en fin de chaîne. Ajouter boost solo uniquement si la chanson exige une différence nette rythmique / lead.
    > 

---

# 🔄 Tables de conversion

---

## 🎸 Équipement réel → GP-180

| **Équipement réel** | **Catégorie** | **Cible GP-180** | **Bloc conseillé** | **Notes** |
| --- | --- | --- | --- | --- |
| Fender Twin / Deluxe / Princeton | Amp clean US | Ampli clean US ou SnapTone Fender clean | AMP ou SnapTone + 1x12 / 2x12 | Pop, country, funk, Tom Petty, Knopfler |
| Vox AC30 | Amp british chime | Foxy 30TB ou SnapTone AC-style | AMP ou SnapTone + 2x12 Blue | Brian May, indie, clean brillant |
| Marshall JTM45 / Plexi / JMP | Amp crunch british | UK 45 / UK 50 / UK SLP ou SnapTone | AMP ou SnapTone + 4x12 Greenback | Rock 60s/70s, gros médiums |
| Marshall JCM800 / JCM900 | Amp rock moderne | UK 800 / UK 900 ou SnapTone | AMP ou SnapTone + 4x12 | Plus tranchant que Plexi, moins massif qu'un Recto |
| Mesa Rectifier / Dual | Amp hi-gain US | Mess DualV / DualM ou SnapTone Mesa | AMP ou SnapTone + 4x12 V30 | Grunge lourd, hard rock, métal moderne |
| ENGL / Diezel / 5150 | Amp hi-gain tight | EV 51, Eagle 120, Dizz VH ou SnapTone | SnapTone + IR 4x12 | Le GP-180 excelle grâce à NAM |
| Tube Screamer | Overdrive | OD 9 (TS9) / Green OD (TS808) | PRE ou DST | Boost devant ampli crunch ou hi-gain |
| Boss DS-1 | Distortion | SM Dist | DST | Sharp, agressif, grunge / rock 90s |
| MXR Dist+ | Distortion | Plustortion | DST | Plus brut, moins compressé |
| ProCo Rat | Distortion | Darktale | DST | Alt rock / indie / sludge |
| Fuzz Face / Tone Bender | Fuzz | Red Haze | DST | Combiner avec ampli ouvert |
| Big Muff Pi | Fuzz | Lazaro | DST | Wall-of-sound, Gilmour, Smashing Pumpkins |
| Klon Centaur | OD transparent | Penesas | PRE ou DST | Amp-in-a-box premium. ⚠️ 17% DSP |
| Fulltone OCD | OD dynamique | Force | DST | Mode HP/LP, tube-like |
| Memory Man | Delay analogique | BBD Delay S | DLY | Chaud, doux, musical |
| Boss DD series | Delay digital | Digital Delay S | DLY | Net, rythmes précis |
| CE-2 / chorus vintage | Modulation | C-Chorus | MOD | New wave, 80s, clean élargi |
| Phase 90 / Small Stone | Phaser | O-Phase | MOD | Mouvement, textures liquides |
| Uni-Vibe | Univibe | Vibe | MOD | Hendrix, Robin Trower. 12% DSP |
| Spring / EMT140 / Room studio | Reverb | Spring / Plate / Room | RVB | Choisir selon époque et densité |
| Cab 1x12 / 2x12 / 4x12 | Cab | Cab interne ou IR tierce correspondant | CAB ou IR | 1x12 focalisé, 2x12 compromis, 4x12 rock/métal |

---

## 🎤 Artiste → Stratégie GP-180

Cette section sert de pont entre **ce qui est connu du son d’un guitariste** et une **recette GP-180 exploitable** dans Songs Library. Les profils doivent toujours être adaptés à la chanson précise, à la période, et à la guitare cible.

## Vue rapide artistes

| **Artiste / période** | **Guitare / micros** | **Cœur sonore GP-180** | **Gain stage** | **Cab / IR** | **Effets typiques** | **Fiabilité par défaut** |
| --- | --- | --- | --- | --- | --- | --- |
| Jimi Hendrix — 1967-1970 | Strat SSS · surtout neck / bridge selon morceau | UK SLP / UK 45 / UK 50 ou SnapTone Plexi | Red Haze fuzz · wah V-Wah/C-Wah | UK Vintage 4x12 / UK Basket 4x12 | Wah, Fuzz Face, Vibe, Room/Plate | B |
| Jimmy Page — Led Zeppelin | Les Paul HB · parfois Telecaster selon période | UK 45JP / UK 50JP / UK SLP | Amp crunch · boost/fuzz léger selon morceau | UK Vintage 4x12 / UK Basket 4x12 | Room courte, slapback, wah fixe occasionnelle | B |
| Eric Clapton — Cream | SG / ES-335 / Les Paul HB | UK 45 / UK 50 / UK SLP | Amp poussé · OD légère si besoin | UK Vintage 4x12 | Peu d’effets, wah occasionnelle, room faible | B |
| Eric Clapton — 70s / solo | Strat SSS | Tweedy / Bellman / clean edge-of-breakup | Boost / OD légère | 1x12 / 2x12 Fender-style | Compression légère, spring/room discrète | B |
| Eddie Van Halen — early brown sound | Superstrat bridge humbucker | UK SLP / UK 50 poussé ou SnapTone EVH | Amp gain · éviter disto moderne excessive | UK Basket 4x12 / UK Vintage 4x12 | O-Phase, Jet flanger, plate/room, delay court | B |
| Jeff Beck — fusion / lyrical lead | Strat SSS ou Tele-Gib / HB selon époque | Silver Twin / L-Star / UK 45 selon morceau | OD légère · sustain dynamique | Twin 2x12 / UK Vintage 4x12 | Delay, Hall/Plate, volume/tone guitare essentiels | C |
| David Gilmour | Strat SSS | Juice Ri100 / Hiwatt-style ou clean Fender | Lazaro Big Muff ou Red Haze selon époque | Juice 4x12 / Twin 2x12 | Delay, Plate/Hall, Vibe/Chorus | B |
| Brian May | Red Special · single coils en série | Foxy 30TB / AC30-style | Treble boost avant amp | Foxy 2x12 | Delay harmonisé, chorus léger selon arrangement | B |
| Mark Knopfler | Strat SSS · positions 2/4 | Silver Twin / Dark Twin clean | Très faible gain | Twin 2x12 | Compression légère, delay discret, jeu aux doigts | B |
| Tony Iommi | SG HB / P90 selon époque | UK 800 / UK SLP sombre | Boost + amp saturé | UK Vintage 4x12 | Très peu d’effets, grave dense | B |
| Kurt Cobain | Jaguar / Mustang HB ou single selon guitare | Mess DualV / clean puissant + SM Dist | SM Dist / DS-1 style | Mess 4x12 / Modern 4x12 | Room faible, chorus selon morceau | B |
| Metallica — James Hetfield | Humbuckers actifs / EMG | Mess2C+ 2/3 ou SnapTone Metallica | OD 9 gain faible + high-gain serré | Mess 4x12 / IR V30 | Gate serré, Mess EQ en V, delay lead si besoin | B |
| Slash | Les Paul HB | UK 800 / Solo100 OD / Marshall hot-rodded | Amp crunch/lead + OD légère si besoin | UK 30 4x12 / UK Vintage 4x12 | Delay lead, Hall/Plate modérée, wah C-Wah | B |
| Stevie Ray Vaughan | Strat SSS · grosses cordes · neck/positions 2/4 | Bellman 59 / Silver Twin edge-of-breakup | Green OD / OD 9 léger | Bellman 4x10 / Twin 2x12 | Tube Screamer, spring/room, toucher fort | B |
| Angus Young | SG HB bridge | UK 45 / UK 50 / UK SLP | Amp crunch, pas trop de gain | UK Vintage 4x12 / UK Basket 4x12 | Quasi aucun effet, room faible | B |
| The Edge | Strat / Explorer / Tele selon morceau | Foxy 30TB / clean chime | Faible gain | Foxy 2x12 | Digital Delay S / Ping Pong tempo-synchronisé, shimmer selon époque | B |

## Profils détaillés prioritaires

- **Jimi Hendrix** — Strat + fuzz/wah + Marshall
    
    **Période utile** : 1967-1970, studio et live.
    
    **Guitares principales** : Fender Stratocaster SSS, souvent accordée 1/2 ton plus bas selon morceaux ; positions neck, bridge ou intermédiaires selon passage.
    
    **Amplis / cœur sonore** : Marshall Plexi / Super Lead / JTM45-like. GP-180 : **UK SLP**, **UK 45**, **UK 50**, ou SnapTone Marshall/Plexi si disponible.
    
    **Effets caractéristiques** : Fuzz Face → **Red Haze**, wah Vox/CryBaby → **V-Wah** ou **C-Wah**, Uni-Vibe → **Vibe**, reverb courte ou plate selon version.
    
    **Chaîne type GP-180** : Gate 1 léger → WAH V-Wah/C-Wah → DST Red Haze → AMP UK SLP/UK 45 → CAB UK Vintage 4x12 → EQ léger → MOD Vibe si nécessaire → RVB Room/Plate faible → VOL.
    
    **Réglage de départ** :
    
    ```
    NR: Gate 1 · Threshold 20-30
    WAH: V-Wah ou C-Wah · EXP active
    DST: Red Haze · Fuzz 60-75 · Volume 60-70
    AMP: UK SLP / UK 45 · Gain 60-75 · Bass 40-50 · Mid 65-75 · Treble 55-65 · Presence 55-65
    CAB: UK Vintage 4x12 ou UK Basket 4x12
    MOD: Vibe optionnel · Depth 30-45 · Rate lent
    RVB: Room/Plate · Mix 8-15
    ```
    
    **Pièges à éviter** : trop de gain moderne, gate trop serré, fuzz trop lisse, reverb excessive.
    
    **Chansons de référence** : Voodoo Child (Slight Return), Purple Haze, Little Wing, All Along the Watchtower.
    
    **Fiabilité par défaut** : **B** — famille de rig très documentée, mais détails studio exacts variables.
    
- **Jimmy Page** — Led Zeppelin / Marshall vintage
    
    **Périodes distinctes** : début Zeppelin Tele/Supro ; période classique Les Paul / Marshall ; multiples traitements studio.
    
    **Guitares principales** : Gibson Les Paul humbuckers pour beaucoup de sons live/classic rock ; Telecaster sur certains enregistrements ; acoustiques fréquentes.
    
    **Amplis / cœur sonore** : Marshall vintage, Plexi/JTM, parfois Supro pour les premiers sons studio. GP-180 : **UK 45JP**, **UK 50JP**, **UK SLP**, ou SnapTone Led Zeppelin si correspondance.
    
    **Effets caractéristiques** : peu d’effets ; room courte, slapback ou delay très court pour épaissir ; wah fixe/cocked wah occasionnelle.
    
    **Chaîne type GP-180** : Gate léger → boost léger ou fuzz selon morceau → AMP UK 45JP/UK 50JP → CAB UK Vintage 4x12 → EQ mids → DLY slapback optionnel → RVB Room faible → VOL.
    
    **Réglage de départ** :
    
    ```
    NR: Gate 1 · Threshold 15-25
    DST: Non ou Red Haze/Plustortion léger selon morceau
    AMP: UK 45JP / UK 50JP · Gain 45-65 · Bass 40-50 · Mid 65-75 · Treble 55-65 · Presence 55-65
    CAB: UK Vintage 4x12 ou UK Basket 4x12
    DLY: Slapback/Pure · Time 80-140 ms · Mix 5-12
    RVB: Room · Mix 5-12
    ```
    
    **Pièges à éviter** : gain trop haut, son trop moderne, graves excessifs avec SG/Les Paul, oublier les traitements studio.
    
    **Chansons de référence** : Whole Lotta Love, Heartbreaker, Black Dog, Stairway to Heaven.
    
    **Fiabilité par défaut** : **B** ; passer à **C** pour les sons studio très produits.
    
- **Eric Clapton** — distinguer Cream, 70s et moderne
    
    ## Cream / Bluesbreakers
    
    **Guitares** : Les Paul, SG, ES-335 selon période.
    
    **Cœur sonore** : Marshall JTM/Plexi poussé. GP-180 : **UK 45**, **UK 50**, **UK SLP**.
    
    **Effets** : peu d’effets, wah occasionnelle, sustain obtenu par volume et toucher.
    
    **Réglage type** :
    
    ```
    AMP: UK 45 / UK 50 · Gain 55-70 · Bass 45-55 · Mid 65-75 · Treble 50-60 · Presence 50-60
    CAB: UK Vintage 4x12
    DST: Non ou Blues OD / Tube Clipper léger si besoin
    RVB: Room faible
    ```
    
    ## 70s / solo Strat
    
    **Guitare** : Strat single coils.
    
    **Cœur sonore** : Fender/Tweed edge-of-breakup. GP-180 : **Tweedy**, **Bellman 59N/59B**, **Silver Twin** selon morceau.
    
    **Effets** : OD légère, compression légère, room/spring discrète.
    
    **Piège principal** : ne pas appliquer automatiquement le profil Clapton 70s à une chanson Cream.
    
    **Chansons de référence** : Crossroads, Sunshine of Your Love, Cocaine, Layla, Wonderful Tonight.
    
    **Fiabilité par défaut** : **B**.
    
- **Eddie Van Halen** — early brown sound / 5150
    
    **Périodes distinctes** : early brown sound Marshall/Variac ; période 5150 plus moderne.
    
    **Guitares principales** : Superstrat bridge humbucker, forte attaque, volume guitare important.
    
    **Cœur sonore GP-180** : **UK SLP** / **UK 50** poussé pour early ; **EV 51** ou SnapTone EVH/5150 pour sons plus modernes.
    
    **Effets caractéristiques** : **O-Phase** réglage modéré, **Jet** flanger sur certains morceaux, delay court/plate/room studio.
    
    **Chaîne type GP-180** : Gate léger → AMP UK SLP/EV 51 → CAB UK Basket/Vintage 4x12 → EQ présence → MOD O-Phase ou Jet selon passage → DLY court → RVB Plate/Room → VOL.
    
    **Réglage de départ** :
    
    ```
    NR: Gate 1 · Threshold 20-30
    AMP: UK SLP · Gain 70-80 · Bass 40-50 · Mid 60-70 · Treble 60-70 · Presence 60-70
    CAB: UK Basket 4x12 / UK Vintage 4x12
    MOD: O-Phase · Rate faible · Depth modéré
    DLY: Pure/Tape court · Mix 5-12
    RVB: Plate/Room · Mix 8-15
    ```
    
    **Pièges à éviter** : utiliser un high-gain moderne trop compressé, trop de basses, phaser trop présent, gate trop serré.
    
    **Chansons de référence** : Eruption, Ain’t Talkin’ ’Bout Love, Panama, You Really Got Me.
    
    **Fiabilité par défaut** : **B**.
    
- **Jeff Beck** — dynamique, volume/tone, lead expressif
    
    **Périodes distinctes** : Blow by Blow / fusion ; Strat moderne ; rigs Fender/Marshall/Magnatone selon époque.
    
    **Guitares principales** : Strat SSS pour beaucoup de sons modernes ; Tele-Gib / humbuckers pour certains sons historiques.
    
    **Cœur sonore GP-180** : **Silver Twin**, **L-Star CL/OD**, **UK 45** selon morceau ; OD légère pour sustain.
    
    **Effets caractéristiques** : delay discret, Hall/Plate, parfois wah/octaver ; surtout contrôle au volume/tone de la guitare.
    
    **Chaîne type GP-180** : Gate très léger → COMP léger → DST TaiChi OD / Tube Clipper faible → AMP clean/edge → CAB Twin 2x12 ou UK Vintage → EQ doux → DLY Sweet/Tape → RVB Hall/Plate → VOL.
    
    **Réglage de départ** :
    
    ```
    NR: Gate 1 · Threshold 10-20
    PRE: COMP ou COMP4 léger
    DST: TaiChi OD / Tube Clipper · Gain 25-45 · Tone doux · Level unité
    AMP: Silver Twin / L-Star / UK 45 · Gain 30-50 · Mid chantant · Treble contrôlé
    CAB: Twin 2x12 ou UK Vintage 4x12
    DLY: Tape/Sweet Echo · Mix 8-15
    RVB: Hall/Plate · Mix 15-25
    ```
    
    **Pièges à éviter** : trop de gain, trop de compression, ignorer le rôle du volume guitare, son trop hi-fi.
    
    **Chansons de référence** : Cause We’ve Ended As Lovers, Beck’s Bolero, Where Were You.
    
    **Fiabilité par défaut** : **C** — le toucher et le contrôle guitare comptent autant que le matériel.
    

<aside>
🧠

**Règle Songs Library** — Si un artiste a plusieurs périodes sonores, toujours choisir la période correspondant à la chanson. En cas de doute, écrire dans Comments : `Profil artiste utilisé : {profil} · Fiabilité : B/C · raison`.

</aside>

---

## 🎼 Fiches chansons de référence — tests GP-180

Ces fiches servent de **cas de validation** pour vérifier que le référentiel permet de produire une configuration GP-180 exploitable à partir d’une chanson, d’un guitariste et d’une guitare cible. Elles sont volontairement rédigées au format proche de **Songs Library**.

<aside>
🧪

**But des 5 tests** — Couvrir cinq profils difficiles : fuzz/wah psyché, Marshall studio classic rock, blues-rock Cream, brown sound, et lead expressif très dynamique. Chaque fiche indique la chaîne GP-180, les réglages de départ, les compensations Strat / SG, et un niveau de fiabilité.

</aside>

- **Jimi Hendrix — Voodoo Child (Slight Return)** · Strat / fuzz / wah / Marshall
    
    ```
    Artiste : Jimi Hendrix
    Chanson : Voodoo Child (Slight Return)
    Album / période : Electric Ladyland · 1968
    Version ciblée : studio / live-compatible
    Guitariste : Jimi Hendrix
    Rôle guitare : riff + lead + wah expressive
    Guitare originale : Fender Stratocaster SSS
    Micros originaux : single coils
    Position micro : neck / bridge selon passage ; wah très active
    Accordage : souvent Eb pour contexte Hendrix, à vérifier selon version jouée
    Guitare cible : Fender Strat Player II prioritaire ; Gibson SG possible avec compensation
    Objectif sonore : fuzz germanium ouvert, wah vocale, ampli Marshall poussé, attaque très dynamique
    Référence sonore principale : riff wah + fuzz de Voodoo Child (Slight Return)
    Fiabilité : B — famille de rig confirmée, détails studio exacts partiellement incertains
    ```
    
    ## Chaîne GP-180 recommandée
    
    ```
    NR → WAH → DST → AMP → CAB → EQ → MOD → DLY → RVB → VOL
    ```
    
    | **Bloc** | **Réglage GP-180 de départ** | **Notes** |
    | --- | --- | --- |
    | NR | Gate 1 · Threshold 20-28 | Très léger pour ne pas couper les attaques faibles. |
    | PRE | Non | Éviter de lisser le fuzz. |
    | WAH | V-Wah ou C-Wah · EXP active | V-Wah si priorité au caractère vocal vintage ; C-Wah si besoin d’un wah plus universel. |
    | DST | Red Haze · Fuzz 65-75 · Volume 65-70 | Équivalent Fuzz Face. |
    | N→S | Non, sauf SnapTone Marshall/Plexi validée | Si SnapTone Plexi : tester N→S + CAB, AMP=None. |
    | AMP | UK SLP ou UK 45 · Gain 65-75 · Bass 45 · Mid 70 · Treble 60 · Presence 60 · Level 60 | Marshall ouvert, pas métal. |
    | CAB / IR | UK Vintage 4x12 ou UK Basket 4x12 · Level 60 | Greenback / basketweave vintage. |
    | EQ | Guitar EQ 1 · léger boost 800Hz / 1.6kHz si besoin | Présence sans agressivité. |
    | MOD | Vibe optionnel · Depth 30-45 · Rate lent | À activer pour couleur psyché, pas obligatoire sur tout le morceau. |
    | DLY | Non ou Tape très discret · Mix 5-10 | Ne pas noyer le riff principal. |
    | RVB | Room ou Plate · Mix 8-15 | Ambiance courte. |
    | VOL | Level 60 | Finaliser le niveau perçu. |
    
    ## Compensation guitare
    
    ```jsx
    Original: Strat SSS, wah + fuzz + Marshall
    Cible Strat: Gain 70, Bass 45, Mid 70, Treble 60, Presence 60 [instrument original]
    Cible SG: Gain 62, Bass 42, Mid 64, Treble 64, Presence 62 [compensé humbucker]
    Notes: sur SG, baisser gain/bass pour éviter un fuzz trop sombre et compressé ; ouvrir Treble/Presence.
    ```
    
    **Avis résultat** : très bon cas d’usage pour le référentiel. La page fournit tous les blocs nécessaires : Red Haze, V-Wah/C-Wah, UK SLP/UK45, UK 4x12, Vibe et Room/Plate.
    
- **Led Zeppelin — Whole Lotta Love** · Les Paul / Marshall / studio rock
    
    ```
    Artiste : Led Zeppelin
    Chanson : Whole Lotta Love
    Album / période : Led Zeppelin II · 1969
    Version ciblée : studio avec adaptation live/jam
    Guitariste : Jimmy Page
    Rôle guitare : riff principal + solo
    Guitare originale : Gibson Les Paul humbuckers probable pour la période classique ; traitements studio possibles
    Micros originaux : humbuckers
    Position micro : bridge pour riff ; neck/bridge selon solo
    Accordage : standard à vérifier selon version
    Guitare cible : Gibson SG prioritaire ; Strat possible avec compensation forte
    Objectif sonore : crunch Marshall vintage, médiums ouverts, gain modéré, room courte
    Référence sonore principale : riff de Whole Lotta Love
    Fiabilité : B/C — famille sonore fiable, mais production studio et doublages à prendre en compte
    ```
    
    ## Chaîne GP-180 recommandée
    
    ```
    NR → DST/PRE optionnel → AMP → CAB → EQ → DLY → RVB → VOL
    ```
    
    | **Bloc** | **Réglage GP-180 de départ** | **Notes** |
    | --- | --- | --- |
    | NR | Gate 1 · Threshold 15-25 | Seulement pour stabiliser le bruit. |
    | PRE | Micro Boost très léger ou Non | Ne pas moderniser le son. |
    | WAH | Non ; C-Wah fixe optionnel pour certains passages solo | Utiliser comme cocked wah uniquement si la version ciblée le justifie. |
    | DST | Non ou Red Haze / Plustortion très léger | Le gain doit surtout venir de l’AMP. |
    | N→S | Pas de SnapTone direct identifié pour Whole Lotta Love | Construire plutôt AMP + CAB ; slot 80 StairwaySo réservé à Stairway. |
    | AMP | UK 45JP / UK 50JP / UK SLP · Gain 50-62 · Bass 45 · Mid 70 · Treble 60 · Presence 58 · Level 60 | Crunch clair, pas saturation moderne. |
    | CAB / IR | UK Vintage 4x12 ou UK Basket 4x12 · Level 60 | Cab Marshall vintage. |
    | EQ | Guitar EQ 1 · Mid présent · Bass contrôlé | Éviter un grave trop épais sur SG/Les Paul. |
    | MOD | Non | Garder sec. |
    | DLY | Slapback ou Pure · 80-120 ms · Mix 5-10 | Épaississement studio léger. |
    | RVB | Room · Mix 5-12 | Courte. |
    | VOL | Level 60 | Boost solo +3 dB optionnel. |
    
    ## Compensation guitare
    
    ```jsx
    Original: Les Paul bridge humbucker, Marshall vintage
    Cible SG: Gain 58, Bass 43, Mid 66, Treble 62, Presence 60 [compensé depuis Les Paul]
    Cible Strat: Gain 66, Bass 47, Mid 70, Treble 55, Presence 56 [alternative single coil]
    Notes: SG proche mais plus médium ; Strat nécessite plus de gain/mid et moins d'aigus.
    ```
    
    **Avis résultat** : très exploitable pour une version jouée. La limite principale est le traitement studio original ; il faut éviter de chercher une copie exacte uniquement avec les blocs d’ampli.
    
- **Cream — Crossroads** · humbuckers / Marshall poussé
    
    ```
    Artiste : Cream
    Chanson : Crossroads
    Album / période : Wheels of Fire / live 1968
    Version ciblée : live blues-rock
    Guitariste : Eric Clapton
    Rôle guitare : riff + lead improvisé
    Guitare originale : Gibson SG / ES-335 / Les Paul selon période et source
    Micros originaux : humbuckers
    Position micro : bridge ou neck selon attaque souhaitée
    Accordage : standard probable
    Guitare cible : Gibson SG prioritaire ; Strat possible avec compensation
    Objectif sonore : Marshall poussé, sustain blues-rock, médiums chauds, peu d’effets
    Référence sonore principale : Cream live Crossroads
    Fiabilité : B — famille Clapton/Cream fiable, guitare exacte selon performance à valider
    ```
    
    ## Chaîne GP-180 recommandée
    
    ```
    NR → DST optionnel → AMP → CAB → EQ → RVB → VOL
    ```
    
    | **Bloc** | **Réglage GP-180 de départ** | **Notes** |
    | --- | --- | --- |
    | NR | Gate 1 · Threshold 12-20 | Très léger. |
    | PRE | Non ou Micro Boost · Gain faible | Seulement si l’attaque manque. |
    | WAH | Non | Pas nécessaire pour la base Crossroads. |
    | DST | Non ou Blues OD / Tube Clipper · Gain 20-35 | À utiliser si l’AMP seul ne sature pas assez. |
    | N→S | Non ou SnapTone Marshall vintage | Si capture Marshall : AMP=None, CAB actif. |
    | AMP | UK 45 / UK 50 · Gain 60-70 · Bass 48 · Mid 70 · Treble 55 · Presence 55 · Level 60 | Son chaud, ouvert, touch-sensitive. |
    | CAB / IR | UK Vintage 4x12 · Level 60 | Base Marshall stack. |
    | EQ | Guitar EQ 1 · 800Hz/1.6kHz légèrement présents | Faire chanter les médiums. |
    | MOD | Non | Garder brut. |
    | DLY | Non | Optionnel uniquement pour confort casque. |
    | RVB | Room · Mix 5-10 | Ambiance live discrète. |
    | VOL | Level 60 | Boost solo inutile : tout est joué au toucher. |
    
    ## Compensation guitare
    
    ```jsx
    Original: Gibson humbucker, Marshall poussé
    Cible SG: Gain 64, Bass 46, Mid 68, Treble 58, Presence 56 [instrument proche original]
    Cible Strat: Gain 72, Bass 48, Mid 72, Treble 52, Presence 54 [compensé single coil]
    Notes: Strat = plus de gain et de mids, aigus réduits ; utiliser S to H si le son manque de corps.
    ```
    
    **Avis résultat** : très bon pour une fiche chanson. Le référentiel corrige le piège précédent : ne pas appliquer Clapton 70s/Strat à un morceau Cream.
    
- **Van Halen — Eruption** · Superstrat / brown sound / phaser
    
    ```
    Artiste : Van Halen
    Chanson : Eruption
    Album / période : Van Halen · 1978
    Version ciblée : studio early brown sound
    Guitariste : Eddie Van Halen
    Rôle guitare : solo instrumental lead
    Guitare originale : Superstrat bridge humbucker
    Micros originaux : humbucker bridge
    Position micro : bridge
    Accordage : standard ou Eb selon contexte live, à vérifier
    Guitare cible : Gibson SG possible ; Strat SSS moins idéale sans S to H / compensation
    Objectif sonore : Marshall brown sound, gain élevé mais ouvert, phaser léger, room/plate studio
    Référence sonore principale : Eruption studio
    Fiabilité : B — recette générale fiable, détails Variac/studio non reproduits directement
    ```
    
    ## Chaîne GP-180 recommandée
    
    ```
    NR → AMP → CAB → EQ → MOD → DLY → RVB → VOL
    ```
    
    | **Bloc** | **Réglage GP-180 de départ** | **Notes** |
    | --- | --- | --- |
    | NR | Gate 1 · Threshold 20-28 | Ne pas trop serrer. |
    | PRE | Non ou Micro Boost très léger | Pas de disto moderne devant. |
    | WAH | Non | Pas pour Eruption. |
    | DST | Non | Le grain doit venir de l’ampli. |
    | N→S | SnapTone EVH/5150 si disponible ; sinon Non | Si SnapTone pertinente, comparer à UK SLP. |
    | AMP | UK SLP ou UK 50 · Gain 72-80 · Bass 42 · Mid 65 · Treble 66 · Presence 66 · Level 60 | Brown sound ouvert. |
    | CAB / IR | UK Basket 4x12 ou UK Vintage 4x12 · Level 60 | Cab vintage, pas Recto moderne. |
    | EQ | Guitar EQ 1 · présence contrôlée | Éviter fizz excessif. |
    | MOD | O-Phase · Rate faible · Depth modéré | Phaser perceptible mais pas envahissant. |
    | DLY | Pure ou Tape court · Mix 5-10 | Épaississement léger. |
    | RVB | Plate ou Room · Mix 8-15 | Studio ambience. |
    | VOL | Level 60 | Prévoir marge niveau lead. |
    
    ## Compensation guitare
    
    ```jsx
    Original: Superstrat bridge humbucker
    Cible SG: Gain 68, Bass 40, Mid 62, Treble 68, Presence 68 [compensé humbucker SG]
    Cible Strat SSS: Gain 78, Bass 45, Mid 68, Treble 58, Presence 60 [compensé single coil + S to H conseillé]
    Notes: SG fonctionne mieux que Strat SSS pour ce cas ; Strat nécessite S to H ou beaucoup de mid/gain.
    ```
    
    **Avis résultat** : bon preset de départ. La limite est le Variac / ampli poussé réel ; le GP-180 peut approcher le caractère, pas reproduire toute l’interaction ampli/HP.
    
- **Jeff Beck — Cause We’ve Ended As Lovers** · lead expressif / dynamique
    
    ```
    Artiste : Jeff Beck
    Chanson : Cause We’ve Ended As Lovers
    Album / période : Blow by Blow · 1975
    Version ciblée : studio / lead expressif
    Guitariste : Jeff Beck
    Rôle guitare : lead mélodique très dynamique
    Guitare originale : Tele-Gib / humbuckers souvent citée pour cette période, à confirmer selon source
    Micros originaux : humbuckers
    Position micro : neck/bridge selon phrase ; contrôle volume/tone essentiel
    Accordage : standard probable
    Guitare cible : Gibson SG prioritaire ; Strat possible mais son différent
    Objectif sonore : sustain chantant, attaque douce, dynamique au volume, reverb/delay musical
    Référence sonore principale : lead de Cause We’ve Ended As Lovers
    Fiabilité : C — matériel et surtout toucher très déterminants
    ```
    
    ## Chaîne GP-180 recommandée
    
    ```
    NR → PRE → DST → AMP → CAB → EQ → DLY → RVB → VOL
    ```
    
    | **Bloc** | **Réglage GP-180 de départ** | **Notes** |
    | --- | --- | --- |
    | NR | Gate 1 · Threshold 10-18 | Le plus ouvert possible. |
    | PRE | COMP ou COMP4 léger · Sustain 20-35 · Volume unité | Ne pas écraser l’expression. |
    | WAH | Non | Optionnel selon interprétation, pas base. |
    | DST | TaiChi OD ou Tube Clipper · Gain 25-40 · Tone doux · Level unité | OD chantante, pas disto. |
    | N→S | Non ou clean/crunch boutique validé | Si SnapTone boutique : AMP=None + cab adapté. |
    | AMP | Silver Twin / L-Star CL/OD / UK 45 · Gain 35-50 · Bass 42 · Mid 60 · Treble 54 · Presence 55 · Level 60 | Base clean/edge, sustain via OD + toucher. |
    | CAB / IR | Twin 2x12 ou UK Vintage 4x12 · Level 60 | Choisir selon chaleur souhaitée. |
    | EQ | Guitar EQ 1 · Bass contrôlé · Mid chantant | Éviter graves flous. |
    | MOD | Non ou Vibrato très léger | À éviter si le vibrato main gauche suffit. |
    | DLY | Tape ou Sweet Echo · Time 300-420 ms · Mix 8-15 · Feedback 15-25 | Épaissir sans masquer l’attaque. |
    | RVB | Hall ou Plate · Mix 15-22 | Lead large et chantant. |
    | VOL | Level 60 · EXP volume optionnel avant DLY/RVB | Très utile pour phrasé expressif. |
    
    ## Compensation guitare
    
    ```jsx
    Original: Tele-Gib / humbuckers, lead dynamique
    Cible SG: Gain 38, Bass 40, Mid 58, Treble 57, Presence 56 [proche humbucker, bass réduit]
    Cible Strat: Gain 45, Bass 43, Mid 62, Treble 52, Presence 54 [compensé single coil]
    Notes: le plus important est le contrôle volume/tone et le toucher ; ne pas trop compresser.
    ```
    
    **Avis résultat** : musical et exploitable, mais c’est le cas où le matériel compte moins que le jeu. Le niveau de fiabilité reste C par prudence.
    

## ✅ Synthèse de validation des 5 tests

| **Test** | **Résultat obtenu avec le référentiel** | **Point fort** | **Limite restante** |
| --- | --- | --- | --- |
| Hendrix — Voodoo Child | Très bon | Tous les blocs critiques existent : wah, fuzz, Plexi, vibe. | Détails studio et interaction fuzz/volume guitare. |
| Page — Whole Lotta Love | Bon à très bon | Marshall vintage + cab + gain modéré bien couverts. | Traitements studio / doublages. |
| Clapton — Crossroads | Très bon | Distinction Cream vs Clapton 70s désormais claire. | Guitare exacte selon performance à valider. |
| EVH — Eruption | Bon | Brown sound approximé avec UK SLP + phaser. | Variac / volume ampli / studio non reproduits totalement. |
| Jeff Beck — Cause We’ve Ended As Lovers | Correct à bon | Chaîne lead expressive exploitable. | Toucher, volume/tone et matériel exact très déterminants. |

<aside>
✅

**Conclusion** — Avec ces 5 fiches test, le référentiel devient suffisant pour produire des réglages GP-180 crédibles dans Songs Library. Les limites restantes doivent être documentées via le niveau de fiabilité, pas masquées.

</aside>

---

## ⚖️ Compensation guitare → GP-180

### Principes généraux

La compensation sert à adapter un preset conçu pour une **guitare originale** vers une **guitare cible** utilisée dans Songs Library. Elle ne remplace pas l'écoute : elle donne un **point de départ fiable** pour que le GP-180 réagisse comme l'équipement d'origine.

<aside>
🎸

**Règle clé** — Toujours documenter séparément : **guitare originale**, **micros originaux**, **position micro**, **guitare cible**, puis les deltas appliqués sur Gain / Bass / Mid / Treble / Presence / EQ / Gate.

</aside>

## 🎛️ Caractère des principales familles de guitares

| **Guitare / micros** | **Caractère sonore** | **Risques dans le GP-180** | **Compensation typique** |
| --- | --- | --- | --- |
| Fender Strat SSS | Sortie modérée, attaque nette, aigus présents, graves serrés, positions 2/4 creusées. | Son trop brillant ou trop maigre si preset prévu pour humbuckers. | Gain +3 à +7 · Treble -2 à -5 · Mid +0 à +3 · Gate plus doux. |
| Telecaster single coils | Twang, attaque très franche, aigu fort, bas-médium sec. | Aigus agressifs, pick attack trop dure, manque de sustain. | Treble -3 à -6 · Presence -2 à -4 · Compression légère · Mid +1 à +3. |
| Gibson SG humbuckers | Médiums forts, sortie élevée, graves présents mais moins massifs qu'une Les Paul. | Son nasal ou trop dense dans les médiums, saturation trop rapide. | Gain -3 à -6 · Bass -1 à -3 · Treble +2 à +4 · Presence +1 à +3. |
| Les Paul humbuckers | Sortie élevée, sustain, graves épais, bas-médiums denses, aigus plus doux. | Preset trop sombre / boomy, saturation trop compressée. | Gain -4 à -8 · Bass -2 à -5 · Presence +2 à +5 · Treble +1 à +4. |
| Superstrat HSS / HSH | Sortie forte, attaque moderne, bridge humbucker serré, souvent plus brillant qu'une Les Paul. | Gain excessif sur hi-gain, haut-médium agressif. | Gain -2 à -6 · Presence -1 à +2 selon micro · Gate ajusté · Bass contrôlé. |
| P90 | Single coil puissant, médiums crus, attaque ouverte, bruit plus présent. | Bruit, haut-médium agressif, saturation rugueuse. | Gate + léger · Treble -1 à -4 · Mid -1 à +2 · Gain -1 à +3 selon cible. |
| Semi-hollow / ES-335 | Chaud, résonant, sustain, bas-médiums présents, attaque plus douce. | Feedback, graves flous, manque de précision en hi-gain. | Bass -2 à -5 · Gain modéré · Gate léger · Presence +1 à +3. |
| Acoustique / électro-acoustique | Large spectre, transitoires fortes, besoin de naturel et d'air. | Son plastique si AC Sim trop fort, larsen / graves envahissants. | Gain faible · EQ correctif · RVB légère · AC Sim seulement si guitare électrique. |

## 🔁 Conversions fréquentes

### SG → Strat

| **Paramètre** | **SG base** | **Strat ajustée** | **Delta** | **Pourquoi** |
| --- | --- | --- | --- | --- |
| Gain | X | X + 5 | +5 | Les single coils attaquent moins fort PRE / DST / AMP. |
| Bass | Y | Y - 2 ou inchangé | -2 à 0 | Éviter un grave artificiel ; ajuster selon cab / IR. |
| Mid | M | M + 0 à +2 | 0 à +2 | Redonner de la densité si le son devient trop creusé. |
| Treble | Z | Z - 3 | -3 | La Strat est naturellement plus brillante. |
| Gate | Threshold T | T - 3 à -8 | -3 à -8 | Préserver les attaques faibles et le sustain. |

### Strat → SG

| **Paramètre** | **Strat base** | **SG ajustée** | **Delta** | **Pourquoi** |
| --- | --- | --- | --- | --- |
| Gain | X | X - 5 | -5 | Les humbuckers saturent plus vite. |
| Bass | Y | Y - 1 à -3 | -1 à -3 | Limiter l'empâtement dans FRFR / IR sombre. |
| Mid | M | M - 1 à -3 | -1 à -3 | La SG ajoute naturellement des médiums. |
| Treble | Z | Z + 3 | +3 | Rendre de l'air et de l'attaque. |
| Presence | P | P + 1 à +3 | +1 à +3 | Rendre le son moins couvert sans trop monter Treble. |

### Les Paul → SG

| **Paramètre** | **Les Paul base** | **SG ajustée** | **Delta** | **Pourquoi** |
| --- | --- | --- | --- | --- |
| Gain | X | X + 0 à +2 | 0 à +2 | La SG a souvent un peu moins d'épaisseur / sustain qu'une Les Paul. |
| Bass | Y | Y - 1 à -2 | -1 à -2 | La SG peut devenir résonante dans le bas-médium. |
| Mid | M | M - 1 à -2 | -1 à -2 | Éviter le côté nasal. |
| Treble / Presence | Z / P | Z + 1 · P + 1 | +1 | Plus d'air si le preset est très Les Paul / sombre. |

### Les Paul → Strat

| **Paramètre** | **Les Paul base** | **Strat ajustée** | **Delta** | **Pourquoi** |
| --- | --- | --- | --- | --- |
| Gain | X | X + 6 à +10 | +6 à +10 | Compenser la sortie plus faible des single coils. |
| Bass | Y | Y + 0 à +2 | 0 à +2 | Redonner du corps si le son devient trop mince. |
| Mid | M | M + 2 à +5 | +2 à +5 | Recréer la densité humbucker. |
| Treble | Z | Z - 4 à -7 | -4 à -7 | Éviter une brillance excessive. |
| PRE optionnel | — | S to H | Selon besoin | Utiliser si le morceau exige vraiment une couleur humbucker. |

### Strat → Les Paul / SG

| **Paramètre** | **Strat base** | **Humbucker ajusté** | **Delta** | **Pourquoi** |
| --- | --- | --- | --- | --- |
| Gain | X | X - 5 à -8 | -5 à -8 | Éviter une saturation trop compressée. |
| Bass | Y | Y - 2 à -5 | -2 à -5 | Les humbuckers ajoutent du bas et bas-médium. |
| Mid | M | M - 1 à -4 | -1 à -4 | Limiter l'effet boxy / nasal. |
| Treble / Presence | Z / P | Z + 2 à +5 · P +1 à +3 | +2 à +5 | Récupérer de l'attaque et de l'air. |
| PRE optionnel | — | H to S | Selon besoin | Utiliser si le morceau exige vraiment un quack / single coil. |

## 🎚️ Ajustements par position micro

| **Position** | **Usage typique** | **Ajustement GP-180** |
| --- | --- | --- |
| Bridge single coil | Funk, surf, rock brillant, country. | Treble / Presence à surveiller · compression légère possible. |
| Neck single coil | Blues, Hendrix, clean rond, leads doux. | Couper un peu Bass si boueux · Mid léger pour sustain. |
| Positions Strat 2/4 | Funk, Knopfler, pop clean, quack. | Gain + · compression légère · éviter trop de mid. |
| Bridge humbucker | Rock, hard rock, métal, riffs. | Gain à contrôler · Bass / Low-mid à surveiller. |
| Neck humbucker | Leads chauds, blues, jazz-rock. | Bass - · Presence + · reverb/delay modérés. |
| Middle / mix humbuckers | Clean chaud, crunch vintage. | EQ selon densité ; attention au bas-médium. |

## 🧾 Format recommandé dans Songs Library

```jsx
Original: Les Paul bridge humbucker, Marshall Plexi, studio
Cible: Gibson SG bridge humbucker
SG: Gain 58, Bass 46, Mid 62, Treble 61, Presence 58 [compensé depuis Les Paul]
Strat: Gain 66, Bass 48, Mid 66, Treble 54, Presence 55 [alternative single coil]
Notes: SG proche de la Les Paul mais moins grave ; Strat nécessite S to H ou mid boost si le riff doit rester épais.
```

```jsx
Original: Strat neck single coil, fuzz + Marshall
Cible: Gibson SG neck humbucker
Strat: Gain 70, Bass 45, Mid 68, Treble 58, Presence 60 [instrument original]
SG: Gain 62, Bass 42, Mid 64, Treble 62, Presence 62 [compensé humbucker]
Notes: baisser gain et bass sur SG ; ouvrir Treble/Presence pour éviter un fuzz trop sombre.
```

<aside>
⚠️

**Important** — Ces deltas sont des points de départ. Les réglages finaux dépendent du volume de sortie réel des micros, de la hauteur des micros, du cab / IR, du monitoring FRFR/casque, et du niveau global du patch.

</aside>

---

## 🎼 Genre → Réglages par défaut GP-180

| **Genre** | **Décennie** | **Approche amp / NAM** | **Cab / IR** | **Gain stage** | **Espace / modulation** |
| --- | --- | --- | --- | --- | --- |
| Rock'n'roll | 1950s | Tweedy / clean US poussé | 1x12 | Pas d'OD ou OD légère | Room / spring légère |
| Blues | 1950s-60s | Tweedy / Bellman | 1x12 ou 2x12 | Boost ou OD légère | Room faible |
| Psychedelic | 1960s | UK crunch ouvert | 4x12 Greenback | Fuzz / boost | Phaser / rotary / spring |
| Hard rock | 1970s | UK Plexi / JMP | 4x12 | Amp saturé ou boost léger | Peu d'effets |
| Funk | 1970s | Clean US très net | 2x12 open back | Compression légère | Auto-wah, chorus discret, spring |
| New wave / pop 80s | 1980s | Clean US / british chime | 2x12 | Très faible | C-Chorus + Plate |
| Grunge | 1990s | Mess DualV (modern US gain) | 4x12 V30 | SM Dist ou amp hi-gain modéré | Room très légère |
| Métal | 1990s-2000s | Recto / 5150 / ENGL / Diezel | 4x12 IR | OD 9 boost + hi-gain | Gate serré, delay lead éventuel |
| Indie rock | 2000s-2020s | Foxy / clean british / Fender | 2x12 | Crunch léger | Delay digital / room |
| Ambient | 2010s-2020s | Clean US / NAM clean | 2x12 ou IR large | Faible | MOD + delay + shimmer / hall |

---

## 🧰 Règles pratiques GP-180

<aside>
💡

**En résumé** — Le GP-180 ne doit pas être abordé comme un GP-50 avec « plus d'effets ». Il faut penser en **familles de sons**, en **chaîne flexible**, et exploiter sa vraie force : **SnapTone / NAM + IR + marge DSP**.

</aside>

- **Choisir AMP ou SnapTone** comme cœur du son ; éviter de cumuler les deux sans raison claire.
- **Choisir CAB interne ou IR tierce** ; ne garder les deux que si un test précis le justifie.
- Avec un **SnapTone**, privilégier : `Gate → OD/Boost → SnapTone → IR → EQ → MOD/DLY/RVB`.
- Réserver le **DSP** aux blocs qui changent réellement le son.
- Pour le travail détaillé NAM / IR, voir [NAM / SnapTone — Guide GP-180](https://app.notion.com/p/NAM-SnapTone-Guide-GP-180-dfd01c948c75409eb74d00ce8a69093c?pvs=21).
- Pour la logique générale de construction sonore, voir [Conception d'un son — Méthode universelle](https://app.notion.com/p/Conception-d-un-son-M-thode-universelle-c6138b3444354e4d90560e4e7a3d5e59?pvs=21).