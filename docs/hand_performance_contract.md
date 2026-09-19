# HandPerformance 1.1 — données musicales et temps

Implémentation additive des sections 7, 11 et 19 de
`specifications/notion_hand_replacement_2026-09-14.md`, et du lot L1 de
`specifications/notion_fingering_animation_2026-09-14.md`. L'interface de M5 reste intacte.

## Contrat livré

`src/fretwise/performance/hand_performance.py` définit les modèles Pydantic stricts,
le validateur de références et `build_hand_performance`. Le schéma JSON versionné
se trouve dans `src/fretwise/performance/schemas/hand-performance-1.1.schema.json`.
Le test de conformité vérifie que ce fichier correspond aux modèles exécutés.
Les contraintes entre objets (références, géométrie, courbes, temporalité) sont
contrôlées en plus par les validateurs Python et par le consommateur JavaScript.

Les dates sont des ticks absolus, PPQ initial 960, augmenté au besoin pour les
tuplets. Une seconde nominale est l'intégrale de `tempoMap`, en microsecondes par
noire. Les silences initiaux restent présents. La vitesse de lecture s'applique au
transport, une seule fois. `TempoMap` intègre aussi les changements pendant une note.

`NoteEvent` conserve désormais `source_finger`, `bend_points` (position 0..1,
cents), `tempo_points` (beats, BPM), `timing_diagnostics` et
`technique_to_source_note_id`. Les champs historiques restent disponibles.
Chaque occurrence possède un ID distinct, même si elle reprend un même ID source.
Les doigtés définitifs sont joints aux événements; le builder n'appelle aucun solveur.

`score_context['performanceByNoteId']` reçoit les directives `perf` déjà calculées
par `fretwise.playback.build_performance`, indexées par `str(result.note_id)`.
Ainsi `dur_beats` et `velocity` déterminent la fin sonore et l'exécution de la main.
Les révisions partition, doigtés et politique temporelle font partie du document.
Sans cette politique, une articulation raccourcie reçoit `TIMING_AMBIGUOUS`.

Le parseur GPIF conserve les points de bend d'origine, les bornes du plateau et
le retour, y compris les propriétés sœurs `Bended`, `BendOriginValue`,
`BendMiddleOffset1/2`, `BendDestinationValue`. La conversion GPIF est
`offset / 100`, `value * 2` cents : 25 unités correspondent à un quart de ton.
Référence de format : [importeur GPIF alphaTab](https://github.com/CoderLine/alphaTab/blob/develop/packages/alphatab/src/importer/GpifParser.ts).
Les enveloppes audio préservent ces points sans les remplacer par l'amplitude maximale.

Les liens hammer-on/pull-off/slide contigus, de même corde et voix, portent les
IDs origine/destination. L'attaque adoucie s'applique à la destination. Une origine
`HopoOrigin` descendante devient `pull_off`. Les courbes ou liens manquants restent
des expressions `unknown`, avec données source et diagnostic explicite.
Les contacts simultanés d'un même doigt à la même case produisent un intervalle
de barré; les doigts plantés existants produisent des préférences de maintien.

## Limites explicites

- Le builder reçoit l'ordre d'exécution du transport. Il ne déroule pas seul les
  reprises. Le GPIF qui contient reprises/fins alternatives reçoit
  `REPEAT_UNFOLDING_REQUIRED` tant que le transport n'a pas fourni les occurrences.
- Les rampes de tempo détectées reçoivent `TEMPO_RAMP_UNSUPPORTED`. Un diagnostic
  ne constitue pas une qualification de cette fonctionnalité.
- Sans carte source complète, les tempos sont reconstruits depuis les notes avec
  `TEMPO_MAP_INFERRED`; un changement dans un silence reste inconnaissable.
- Les profils anatomiques, la pression réelle, les courbes de vibrato non annotées,
  la calibration du bend et les techniques exigeant la main d'attaque demandent
  encore leur qualification dédiée. Le contrat ne revendique aucune validation
  anatomique ou musicale par un panel humain.

## Vérification

`pixi run python -m pytest tests/test_hand_performance.py tests/test_hand_viz.py
tests/test_gpif_adapter.py tests/test_playback_phrasing.py` couvre notamment silence
initial, tempo traversant une tenue, double croche à 240 BPM, tuplets, IDs répétés,
courbe avec plateau/release, pré-bend, liens, révisions et rejet des références invalides.
