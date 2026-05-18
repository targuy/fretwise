# Web UI — chantier urgent (PO 2026-05-18)

> **Owner exécution** : `[web-be]` + `[design]`. PM coordinates.
> **Source des 5 issues** : PO direct dans la conversation.
> **Branche** : nouvelle `feature/web-ui-urgent` (ne pas mélanger avec `refactor/p0-notation-fixes`).

---

## 0. Vue d'ensemble

Cinq défauts UX dans la web app actuelle, à corriger dans cet ordre de dépendances :

| # | Défaut | Surface |
|---|---|---|
| **U1** | Pas de navigation retour depuis la page Setup | Nav / routing |
| **U2** | Centrage de la ligne de partition non fait | Scoring renderer |
| **U3** | Playhead non synchronisé entre voix | Playback engine |
| **U4** | Bouton mute manquant par voix + pas de "solo voice" | Track tabs + barre menu bas |
| **U5** | Édition fine du son d'un instrument absente (le soundfont change, le patch ne s'édite pas) | Instrument settings |

Les 5 défauts sont **indépendants logiquement** mais certaines paires partagent du code (U3 + U4 toucheront `playback.js`, U2 + U4 toucheront `renderer.js`). Ordonnés ci-dessous pour minimiser les rebases.

---

## U1 — Navigation retour depuis Setup

### État actuel (à confirmer)

Page Setup accessible depuis le lecteur ou la library. Pas de bouton "← Retour au morceau" ni "← Liste des morceaux". L'utilisateur doit utiliser le bouton browser back, ce qui parfois ne restaure pas l'état (playhead, voix sélectionnée).

### Proposition UI

**Header de la page Setup** : zone fixe en haut, gauche, avec deux boutons + breadcrumb.

```
┌─────────────────────────────────────────────────────────────┐
│  ← Retour au morceau  |  ⌂ Liste des morceaux               │
│                                                             │
│  Setup › Stairway To Heaven › Voice : Lead Guitar           │
└─────────────────────────────────────────────────────────────┘
```

- **Bouton "← Retour au morceau"** : reprend exactement où on était (playhead position, voix, mute state, zoom). Implémentation : stocker l'état playback dans `sessionStorage` avant transition vers Setup, restaurer au retour.
- **Bouton "⌂ Liste des morceaux"** : navigue vers la page library sans état (pas de retour). Implémentation : navigation simple via `location.hash` ou route SPA.
- **Breadcrumb** : indique le contexte. Click sur "Stairway To Heaven" = retour au morceau (équivalent au bouton ←).

### Edge cases

- Setup ouvert sans morceau actif (depuis library directe) → "← Retour au morceau" disabled / hidden.
- Modifications non sauvegardées en Setup → confirmation modale avant retour ("Quitter sans sauvegarder ?").
- Setup ouvert depuis URL profonde (deep-link) → fallback gracieux vers library.

### Acceptance criteria

- [ ] Boutons toujours visibles en haut de la page Setup
- [ ] "Retour au morceau" restaure playhead à ±100 ms de la position au moment du départ
- [ ] "Liste des morceaux" charge la library sans erreur
- [ ] Breadcrumb met à jour le nom du morceau si l'utilisateur change de morceau dans le Setup
- [ ] Confirmation modale si modifications pending

---

## U2 — Centrage vertical de la ligne de partition

### État actuel

Le scoring (staff + tab) est ancré en haut du conteneur. Sur des écrans hauts (≥ 16:9), beaucoup d'espace vertical inutilisé en bas. Sur des passages avec une seule voix monophonique, c'est encore plus visible.

### Proposition UI

**Centrage vertical du système courant dans le viewport** :

```
┌──────────────── viewport ────────────────┐
│ [header — fixe en haut]                  │
├──────────────────────────────────────────┤
│                                          │
│                                          │
│  ── staff line  current system  ────     │ ← centré
│  ── tab line                    ────     │
│                                          │
│                                          │
├──────────────────────────────────────────┤
│ [footer / playback controls — fixe bas]  │
└──────────────────────────────────────────┘
```

- **Mécanisme** : à chaque move de playhead, calculer le système courant, le centrer dans la zone visible (entre header et footer). Animation smooth-scroll, durée ≤ 200 ms.
- **Toggle utilisateur** : bouton dans footer "Center" (icône bullseye) pour activer / désactiver le centrage. Par défaut **activé**.
- **Désactivation auto** : si l'utilisateur scroll manuellement, désactiver le centrage (reprend que sur clic explicite ou nouveau morceau). Analog au "follow playhead" existant (`btn-follow`).

### Edge cases

- Système plus haut que la zone visible (multi-voix, hand viz attaché) → ne pas centrer, scroll au début du système.
- Plusieurs systèmes simultanément visibles → centrer celui du playhead.
- Mode fullscreen / overlay → recalcul des marges.

### Acceptance criteria

- [ ] Au playback, le système courant reste verticalement centré dans la zone visible (±20 px)
- [ ] Smooth-scroll fluide à 60 fps, pas de saccade visible
- [ ] Toggle "Center" fonctionne et persiste pendant la session
- [ ] Scroll manuel désactive temporairement le centrage
- [ ] Centrage respecte le header et footer fixes

---

## U3 — Synchronisation playhead entre voix

### État actuel

`main.js` gère plusieurs tracks (primary + secondary muted). Chaque track a son propre rendu mais le **playhead** peut diverger entre voix si elles sont jouées simultanément (la voice 2 ne montre pas la même position que la voice 1).

### Proposition UI

**Single source of truth** pour le temps de lecture (`playback.currentTime` ou équivalent).

```
┌─ Track 1 (voice 1, primary) ──────────────┐
│ ████████████░░░░░░░░░░░░░  [playhead]    │ ← position partagée
└────────────────────────────────────────────┘

┌─ Track 1 (voice 2, secondary) ────────────┐
│ ████████████░░░░░░░░░░░░░  [playhead]    │ ← même position
└────────────────────────────────────────────┘
```

- **Modèle de temps** : un seul `currentTime` global émis par l'audio engine. Tous les renderers s'y abonnent via un event bus (ex: `playback.on('tick', t => ...)`).
- **Render synchrone** : chaque voix affiche un playhead à `xForTime(t)` selon sa propre layout (les onsets sont alignés sur les beats partagés).
- **Précision cible** : ≤ 16 ms (un frame à 60 fps).

### Edge cases

- Voix avec tempo locaux différents (tempo changes par voix) — impossible en GP standard, pas à supporter pour l'instant.
- Tempo change : `currentTime` reste en secondes globales, les renderers convertissent en beats locaux.
- Voix muette : playhead toujours visible (utile pour suivre visuellement).

### Acceptance criteria

- [ ] Au playback, les playheads de toutes les voix visibles se déplacent en parallèle
- [ ] Pause : tous les playheads s'arrêtent au même temps
- [ ] Seek manuel sur une voix synchronise toutes les autres
- [ ] Drift ≤ 1 frame entre voix après 1 min de lecture continue

---

## U4 — Mute par voix + Solo voice courante

### État actuel

`main.js` lignes 1205-1220 émet un bouton mute (`track-mute-btn`, label "M") sur les onglets des **tracks** secondaires. Mais l'utilisateur dit qu'il manque mute par **voix** — voix = sous-unité d'une track GP (voice 1 = melody, voice 2 = bass dans la même track). Le mute actuel mute toute une track, pas une voix.

### Proposition UI

#### U4-a — Bouton mute dans le titre de l'onglet voix

```
┌─ Voice 1 (Lead) ─────┐  ┌─ Voice 2 (Bass) ─────┐
│  🔇  Voice 1 (Lead)  │  │  🔊  Voice 2 (Bass)  │
└──────────────────────┘  └──────────────────────┘
     ↑ muted (gris)            ↑ playing (vert)
```

- **Icône à gauche du nom de voix** dans l'onglet. Click toggle mute.
- **État visuel** : icône 🔇 (muted, gris) vs 🔊 (active, vert ou primary color).
- **Tooltip** : "Mute Voice 1" / "Unmute Voice 1".
- **Persistence** : mute par-voix stocké dans `sessionStorage` par track.

#### U4-b — Solo voice courante dans la barre menu bas

```
┌──────────────── footer ────────────────────┐
│  ◀◀  ▶  ▶▶  |  🎯 Solo voice  |  🔁 Loop  │
└────────────────────────────────────────────┘
                  ↑ cible (active la mute auto des autres)
```

- **Bouton "🎯 Solo voice"** : quand activé, mute automatiquement toutes les voix sauf la **voix sélectionnée** (= celle dont l'onglet est en focus / cliqué).
- **État** : bouton pressed-style (active background) quand mode solo actif.
- **Interaction** : changer d'onglet voix transfert automatiquement le solo à la nouvelle voix sélectionnée.
- **Désactivation** : clic sur le bouton restaure les states mute individuels précédents.

### Edge cases

- Une seule voix dans le morceau → bouton "Solo voice" disabled.
- Click répété sur le bouton mute d'une voix solo'ée → désactive solo et applique mute manuel.
- Voix muettes au moment d'activer solo → les mémoriser pour restauration.
- Voix sans audio (only chord diagrams) → mute affecte uniquement le rendu, pas l'audio (no-op pertinent).

### Acceptance criteria

- [ ] Chaque onglet voix a un bouton mute fonctionnel (toggle audio output de cette voix)
- [ ] État mute visible (icône 🔇 / 🔊) et persistant pendant la session
- [ ] Bouton "🎯 Solo voice" mute toutes les voix sauf celle en focus
- [ ] Changement d'onglet voix met à jour la voix solo
- [ ] Clic sur Solo voice à nouveau restaure l'état précédent
- [ ] Solo voice respecte les mute manuels (les conserve quand désactivé)

---

## U5 — Édition fine du son d'un instrument

### État actuel

Le **soundfont** (SF2) peut être changé (cf. `app.py` endpoint `/soundfont`). Mais une fois soundfont chargée, l'utilisateur ne peut pas choisir **quel patch / preset** utiliser pour chaque instrument (ex: "Steel String Guitar 25" vs "Nylon Guitar 24" dans GeneralUser GS). Et pas de fine-tuning (volume par instrument, pan).

### Proposition UI

**Modale Instrument Settings** ouverte depuis la page Setup, par voix ou par track :

```
┌─── Instrument Settings — Voice 1 (Lead) ───┐
│                                            │
│ Soundfont   : [GeneralUserGS-v2.0 ▼ ]      │
│ Bank        : [Melodic (0) ▼          ]    │
│ Preset      : [25 — Steel String ▼   ]     │
│                                            │
│ Volume      : ━━━━●━━ 75 %                 │
│ Pan         : L ━━━●━━━ R                  │
│                                            │
│ Reverb send : ━━●━━━━ 30 %                 │
│ Chorus send : ●━━━━━ 5 %                   │
│                                            │
│  [ Apply ]              [ Cancel ]         │
└────────────────────────────────────────────┘
```

- **Soundfont dropdown** : liste des SF2 dispo. Sélection charge la SF2 si nécessaire.
- **Bank + Preset dropdowns** : peuplent automatiquement depuis la SF2 chargée (lecture des metadata). Defaut : preset 0 du bank 0.
- **Volume slider** : 0–100 %, defaut 75 %.
- **Pan slider** : Left (-100) → Right (+100), défaut 0.
- **Effets sends** : reverb / chorus si soundfont les supporte.

### API backend (proposé)

Endpoint `GET /soundfont/{name}/presets` → JSON `[{bank, preset, name}]` extrait du SF2.
Endpoint `POST /track/{id}/instrument` → body `{soundfont, bank, preset, volume, pan, reverb, chorus}` → persist + apply.

### Edge cases

- SF2 absente ou corrompue → fallback sur soundfont par défaut, error toast.
- Volume = 0 → équivalent mute (mais distinct du bouton mute U4 ; mute = on/off binaire, volume = analogique).
- Preset change pendant playback → application immédiate sans glitch audio (release notes en cours, apply).
- Plusieurs voix sur la même track GP → settings par voix, pas par track.

### Acceptance criteria

- [ ] Modale s'ouvre depuis bouton "Instrument" dans la page Setup
- [ ] Dropdowns Bank + Preset peuplés correctement depuis SF2 chargée
- [ ] Volume / Pan / Reverb / Chorus appliqués en live (pas de redémarrage requis)
- [ ] Settings persistent dans `sessionStorage` (ou backend si user authentifié)
- [ ] Changement de soundfont reset les presets à defaut

---

## Step segmentation (4 sprints livrables indépendamment)

### Sprint 1 — U1 (Navigation Setup)
**Effort estimé** : 2-4 h. Risque faible (pas de touch playback ou audio).
**Livrable** : header avec breadcrumb + boutons retour, sessionStorage state, confirmation modale.

### Sprint 2 — U2 (Centrage partition)
**Effort estimé** : 3-5 h. Risque moyen (toucher au renderer + scroll logic, interaction avec `btn-follow` existant).
**Livrable** : centrage vertical, toggle "Center", désactivation auto au scroll manuel.

### Sprint 3 — U3 + U4 (Playhead sync + Mute voix + Solo voice)
**Effort estimé** : 6-10 h. Risque élevé (touche playback engine + tabs + state mute).
**Livrable** : event bus playback temps, playhead synchro, mute par voix avec persistence, bouton Solo voice dans footer.
**Note** : ces deux issues partagent l'architecture mute/voice/playback — sprint groupé pour cohérence.

### Sprint 4 — U5 (Édition instrument)
**Effort estimé** : 8-12 h. Risque élevé (backend SF2 metadata + modale + audio engine bank/preset switching).
**Livrable** : endpoint `/soundfont/{name}/presets`, modale Instrument Settings, persistence settings.

**Total estimé** : 19-31 h ≈ 3-5 sessions de dev.

---

## Protocole de test strict

### Test manuel par sprint (smoke test obligatoire)

Pour chaque sprint, exécuter dans Chrome + Firefox + Safari (au moins 2/3) :

1. **Charger un morceau de référence** (ex: `partitions/Led Zeppelin-Stairway to Heaven`)
2. **Reproduire chaque acceptance criterion** du sprint correspondant
3. **Capturer screenshots** des états critiques (avant/après chaque interaction)
4. **Mesurer perf** : durée de scroll, latence click → effet (cible < 100 ms)

### Test automatisé (à mettre en place via Playwright ou similaire)

Sprint-spécifiques :

**U1** :
- `test_setup_back_to_song_restores_playhead`
- `test_setup_back_to_library_navigates_correctly`
- `test_setup_pending_changes_show_confirmation`

**U2** :
- `test_playback_centers_current_system`
- `test_manual_scroll_disables_centering`
- `test_center_toggle_persistence`

**U3** :
- `test_playheads_sync_across_voices_during_playback`
- `test_seek_synchronizes_all_voices`
- `test_drift_under_1_frame_after_1_minute`

**U4** :
- `test_voice_mute_button_toggles_audio`
- `test_solo_voice_mutes_others`
- `test_solo_voice_restores_state_on_disable`
- `test_solo_voice_disabled_when_single_voice`

**U5** :
- `test_soundfont_presets_endpoint_returns_metadata`
- `test_instrument_settings_modal_applies_live`
- `test_settings_persist_in_session`

### Test cross-sprint (regression)

Après chaque sprint, re-run la suite manuelle des sprints précédents pour détecter régressions cross-feature.

### Test golden user-scenario

Scénario "musicien apprenant" (= profil PO) :
1. Charger un morceau Stairway To Heaven
2. Aller en Setup
3. Changer le preset de Voice 1 vers "Nylon Guitar"
4. Voice 2 : volume 30 %, pan +50
5. Retour au morceau via bouton (état restauré)
6. Lecture : Solo voice sur Voice 1, vérifier que Voice 2 n'est pas audible
7. Pause, désactiver solo, vérifier que Voice 2 reprend
8. Click sur Center off, scroll manuel, Center on : recentre

**Pass si** : toute la séquence sans erreur, < 5 s pour chaque transition.

### Acceptance gate par sprint

Un sprint n'est mergé que si :
- ✅ 100 % des acceptance criteria validés manuellement
- ✅ 100 % des tests automatisés du sprint passent
- ✅ Suite tests régression précédente : 0 régression
- ✅ Test golden user-scenario : pass
- ✅ Pas de console errors / warnings en dev mode
- ✅ Pas de memory leak après 5 min de playback

---

## Risques & mitigations

| Risque | Probabilité | Impact | Mitigation |
|---|---|---|---|
| U3 (sync voices) introduit drift dans certains tempos exotiques | Moyenne | Moyen | Test sur 5 morceaux avec tempo changes (Yes, Tool) |
| U5 (SF2 metadata) pas tous les soundfonts ont les bank/preset propres | Élevée | Faible | Fallback sur bank 0 preset 0 si metadata absente |
| U2 (centrage) conflit avec hand viz panel (overlay) | Moyenne | Moyen | Calculer la zone visible utile en soustrayant overlays |
| U4 (mute par voix) état mute perdu sur reload | Élevée | Faible | sessionStorage + restore on track load |

---

## Décisions PO attendues

1. **Ordre des sprints** : ordre proposé U1 → U2 → U3+U4 → U5 OK ? Ou prioriser U3+U4 (playback / mute) en premier car affectent l'usage quotidien ?
2. **Stack tests automatisés** : Playwright (Node, écran headless) ou alternative (Selenium, Cypress) ? Investissement infra à valider.
3. **Modale instrument U5** : ouverture depuis Setup OK ou aussi depuis l'onglet voix (right-click menu) pour rapidité ?
4. **Solo voice U4-b** : icône (🎯) ou texte ("Solo") dans la barre menu ? Texte plus accessible mais prend plus d'espace.

---

## Out of scope (à différer)

- MIDI controller live input (ouvre la route MIDI ↔ audio engine, gros chantier)
- Édition de l'arrangement (déplacer voix entre tracks)
- Export audio des mute/solo states (= bounce stems)
- Themes dark / light personnalisés

Ces items pourraient remonter en sprint 5+ si demandés.
