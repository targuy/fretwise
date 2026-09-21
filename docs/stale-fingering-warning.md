# Avertissement des doigtés calculés avec un ancien moteur

## Comportement

À l'ouverture d'une piste avec des doigtés enregistrés par une version antérieure
du moteur, un bandeau affiche la version enregistrée et la version actuelle.

- **Recalculer et enregistrer** lance le moteur actuel et sauvegarde la piste
  affichée. Les autres pistes ne sont pas recalculées par cette action.
- **Plus tard** ferme le bandeau pour cette ouverture, sans calcul ni écriture.
  L'avertissement revient à la prochaine ouverture de la partition.
- Pendant le calcul, l'action est désactivée. Une erreur reste visible et permet
  de réessayer ; une sauvegarde incomplète n'est jamais présentée comme réussie.
- Après enregistrement, la vue recharge les doigtés persistés et leur version.
  Une réponse tardive ne doit pas changer la partition ouverte entre-temps.

La comparaison porte sur la version de la **piste sélectionnée**, pas seulement
sur l'en-tête du fichier : recalculer une piste ne met pas les autres à jour.
Les versions numériques se comparent par composants (`2.10` est après `2.2`).
Une version inconnue, des annotations importées sans provenance ou un fichier
source modifié ne sont pas assimilés à une version connue plus ancienne.

L'enregistrement sur place reste celui des fichiers Guitar Pro 7/8 (`.gp`).
Cette fonction ne crée pas de nouvel exporteur pour les autres formats.

## Architecture et limites

Ce comportement prolonge le cycle de données décrit dans
[architecture-classes.md](architecture-classes.md), pipeline A et API web.
Il conserve les contrats M1–M6 décrits dans
[fretwise_architecture.md](fretwise_architecture.md) : aucun changement du moteur
de calcul ni de l'interface Viterbi.

`GET /api/solve/{filename}` expose `fingering_algo_version`,
`fingering_current_algo_version` et `fingering_is_outdated`, en complément du
statut de fraîcheur existant. Le simple affichage ne recalcule pas le morceau.
Le bouton utilise la sauvegarde existante `POST /api/save/gp/{filename}`.

Pour ce parcours, `?stream=true` renvoie des événements NDJSON `started`,
`heartbeat`, puis `result` ou `error`. Les messages périodiques maintiennent la
connexion pendant les calculs longs ; un seul calcul est lancé. Le client attend
le résultat d'enregistrement et ne relance jamais automatiquement une requête
interrompue. Le contrat JSON sans cette option est conservé.

Les caches du navigateur sont invalidés après sauvegarde ; les préchargements
commencés avant celle-ci ne doivent pas réintroduire l'ancienne réponse.
