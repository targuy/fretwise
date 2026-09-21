# Qualité du prompt HeadRush et limites vérifiées

## Contrat et portée

Amélioration du workflow décrit dans [HeadRush Core](headrush_core.md), conforme
à la séparation des responsabilités de [l'architecture](fretwise_architecture.md).
La signature de `build_rig_prompt` et `parse_rig_response`, les routes et le
binding `fretwise.device.binding.v1` restent inchangés. Aucun nouveau champ de
contexte ou d'audit n'est ajouté : `guidance`, `tone.summary`, `why`, `sources`
et `confidence` portent les précisions.

Sources de vérité examinées :

- [`prompt.py`](../src/fretwise/devices/headrush_core/prompt.py), génération et validation;
- [`catalog.py`](../src/fretwise/devices/headrush_core/catalog.py) et catalogue
  `data/devices/headrush-core/catalog/5.1.0.2a63755.json`;
- [`chain.py`](../src/fretwise/devices/headrush_core/chain.py), attribution réelle des slots;
- [`plan.py`](../src/fretwise/devices/headrush_core/plan.py) et
  [`params.py`](../src/fretwise/devices/headrush_core/params.py), validation et conversion;
- [`provision.py`](../src/fretwise/devices/headrush_core/provision.py), départ depuis
  `#FW - SCRATCH` ou rig existant; seuls les paramètres demandés sont écrits.

## Bénéfices identifiables

| Problème confirmé | Modification | Ce que cela ne prouve pas |
|---|---|---|
| Recherche mélangeant studio, tournée et période actuelle | Priorité à la prise/partie; portée de chaque source explicitée | Matériel exact d'une prise non documentée |
| Version, partie, guitare/micros et écoute absents | Exploitation du contexte libre; hypothèse de travail explicitée si contexte incomplet | Adaptation acoustique sans essai |
| 4 enums complètes, autres réduites à un nombre de choix | Toutes les enums proposées complètes, listes identiques dédupliquées | Applicabilité d'un contrôle à chaque modèle d'ampli |
| Paramètres booléens parfois accompagnés d'enums | `true/false`, conformément à la priorité de `device_value` | État initial du rig de départ |
| Filtre suffixe `2` cachant des contrôles réels | Seul le deuxième canal des blocs doublables est masqué; `8-Bit Crush.Bit2` reste visible | Gestion des scènes ou doublement dans ce binding |
| Formats `% .1f dB` ou `%.3f` mal nettoyés | Unités extraites sans inventer une unité absente | Interprétation perceptive du réglage |
| Consigne minimale de cinq blocs et extrapolation CPU | Chaîne utile sans minimum; neuf blocs reste une préférence explicite | Coût CPU d'un rig non mesuré |
| Profil de slots décrit comme propriété universelle du Core | Limite de l'importeur explicitée | Autres chaînes matériel impossibles |

`why` distingue **FAIT SOURCÉ**, **ADAPTATION** et **À TESTER**. `sources` reste
une liste de chaînes de texte. `confidence` garde ses cinq valeurs existantes
et désigne la solidité documentaire, pas une note de ressemblance sonore.

## Limites techniques toujours présentes

- Les sélecteurs de fichiers (`LoadedClone`, `IR`, `ReverbFile`, etc.) sont des
  chaînes non énumérées. `device_value` ne sait pas les écrire. Le catalogue
  n'inventorie pas les fichiers effectivement chargés. Le prompt explique cette
  limite et ne propose pas ces paramètres comme réglages importables.
- `ReValver Cab.Proximity` publie minimum `3`, maximum `-3` en pouces. Le
  convertisseur actuel refuse toutes les valeurs de cette plage inversée.
  Ce contrôle est signalé comme indisponible dans le prompt, sans modifier le
  convertisseur ni inventer une plage corrigée.
- `8-Bit Crush.Resampling` publie `0.0033333334140479565` à `1`, format `%.3f`,
  sans unité. Le prompt préserve ces bornes; il ne les transforme pas en Hz.
- Les propriétés conditionnelles selon le modèle ne sont pas décrites par le
  catalogue. Le prompt ne peut donc pas certifier leur effet sonore.
- Omettre un paramètre ne signifie pas zéro, neutre ou valeur catalogue. Le
  modèle de départ ou le rig corrigé peut conserver une valeur précédente.
- Un seul bloc peut occuper chaque slot figé. `Amp` et `Amp 2` existent dans le
  catalogue mais ne peuvent pas cohabiter avec ce profil; même limite pour deux
  réverbes. Aucun bloc n'est ajouté pour remplir une case.

## Validation des réponses

La validation de formes précède `build_plan` : objets `rig/device/song/tone`,
liste non vide `blocks`, modules textuels, paramètres scalaires finis, listes
textuelles de sources/intention, confiance autorisée et Program Change entier
0–127. Les identifiants de schéma/appareil/firmware fournis doivent correspondre.
Les champs facultatifs absents conservent leurs réparations historiques.
Les erreurs deviennent `PromptError`, au lieu d'une erreur Python inattendue.
`build_plan` et ses autres usages ne sont pas modifiés.

Les [tests dédiés](../tests/test_headrush_prompt_quality.py) confrontent les
listes et bornes imprimées au catalogue et au convertisseur réels, importent
l'exemple JSON, vérifient un rig existant et couvrent les réponses mal formées.
La vérification finale du prompt associe chaque clé de paramètre à son module,
après les consignes utilisateur. Une régression concrète couvre la confusion entre
`Graphic EQ.LoGain` et `G EQ.Gain100Hz` : chaque contrôle est valide pour son propre
module et refusé pour l'autre. Un rig Amp + Cab valide n'exige aucun effet de remplissage.
La [génération API](rig_ai_providers.md#api-et-validation) peut demander une correction
technique bornée après un rejet ; elle n'assouplit pas ce validateur et ne transforme
pas la confiance documentaire en évaluation acoustique.

## Évaluation séparée des niveaux de preuve

1. **Conformité JSON/import hors ligne** : tests déterministes via
   `parse_rig_response` et `build_plan`.
2. **Import appareil** : nécessite une création confirmée puis relecture réelle;
   aucun test unitaire ne vaut cette preuve.
3. **Exactitude documentaire** : contrôle indépendant des sources, de leur date
   et de leur lien avec la version/partie demandée.
4. **Fidélité sonore** : écoute comparative à niveau égal, même guitare/micros,
   entrée et écoute, critères séparés du jugement documentaire.

Les neuf JSON de la conversation fournie ne constituent pas un benchmark
indépendant. Aucun gain sonore, statistique ou comparatif entre variantes de
prompt n'est établi par cette modification. Un futur essai A/B doit utiliser
des appels isolés, même modèle/réglages/contexte, références d'évaluation cachées
des entrées et évaluation de ces quatre dimensions séparément.
