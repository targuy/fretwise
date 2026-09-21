# Continuité des propositions de doigté ML

## Problème

Le modèle `phrase_window_v2` remplaçait les doigts après Viterbi et les règles
de continuité. Son vote par note pouvait introduire un changement de doigt sur
une répétition de même corde/case, même si le coût M4 pénalisait ce changement.
Le planificateur final validait la faisabilité physique sans réoptimiser ce coût.

Le cas de diagnostic est l'introduction de *By The Way*, piste guitare :
mesure 3, index ×2 puis annulaire ×6 ; mesure 6, annulaire puis majeur ×7 ;
mesure 7, majeur puis annulaire ×7. Avant la passe ML, les doigts restaient
respectivement index, majeur et index sur les huit croches de chaque mesure.

Les mutations d'états partagés pouvaient aussi altérer les candidats autorisés,
y compris un doigt source verrouillé.

## Contrat

Cette correction suit le contrat de coût injecté et de recherche de séquence de
[`fretwise_architecture.md`](fretwise_architecture.md). L'interface publique de M5
reste inchangée ; aucun modèle ONNX n'est réentraîné ou remplacé.

- Les états candidats et les résultats des résolveurs ne partagent plus d'état
  mutable susceptible de modifier une contrainte.
- Le chemin issu des règles et de la validation physique sert de référence.
- Le modèle propose des doigts ; seuls les états admissibles entrent dans un
  nouvel arbitrage par voix, avec le Viterbi et le coût injectés existants.
- Les accords restent fixés à la référence. Les verrouillages source et les
  contraintes physiques restent applicables.
- Une proposition qui échoue à la validation finale ou augmente le coût total
  de la voix est remplacée par la référence. Une amélioration admissible peut
  être conservée.
- Une erreur d'inférence ne laisse pas de modifications partielles dans la
  référence.

Le maintien d'un doigt n'est pas une règle universelle absolue : un changement
utile pour la suite d'une phrase reste possible si son coût global le justifie.
Le correctif évite de prendre cette décision à partir du seul vote local du ML.

## Cycle de sauvegarde

La version des doigtés passe de `2.1` à `2.2`. Les anciens sidecars ne sont plus
déclarés à jour pour ce calcul. L'ouverture d'une partition ne lance toujours
aucun recalcul automatique ; les annotations GP existantes restent affichables.
La commande explicite de calcul/sauvegarde produit le nouveau résultat.

La version est également conservée dans chaque entrée de piste du sidecar.
Recalculer une piste ne promeut plus les résultats anciens des autres pistes ;
ils restent conservés et identifiés comme anciens. Le rafraîchissement par lot
ne saute pas un fichier qui conserve de telles pistes.

La migration ne recalcule pas toute la bibliothèque. Une réparation ciblée doit
conserver une sauvegarde du GP et de ses deux sidecars, vérifier que la source
n'a pas changé pendant le calcul, puis vérifier le résultat sauvegardé.

L'export GP possède toujours une annotation par définition de note source,
alors que le sidecar distingue ses occurrences. La réutilisation d'un même
identifiant GP dans plusieurs contextes reste une limite distincte de cet export.
