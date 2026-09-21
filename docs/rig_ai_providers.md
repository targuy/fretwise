# Création de rigs : texte manuel, Claude et OpenAI

Implémentation du 20 septembre 2026, commune à FretWise web et HeadRush Studio.
Elle conserve le binding `fretwise.device.binding.v1` et le validateur HeadRush.
Voir [conception HeadRush](headrush_core.md) et [qualité du prompt](headrush_prompt_quality.md).
Cette documentation décrit le code ; elle ne prouve pas son déploiement en production.

## Utilisation et droits

| Mode | Comportement |
|---|---|
| Texte manuel (`manual`, défaut) | Copier le prompt, consulter l'IA choisie, coller puis importer sa réponse. Aucun appel fournisseur par FretWise. |
| Claude API (`anthropic`) | Génération serveur avec le modèle Claude configuré. |
| OpenAI API (`openai`) | Génération serveur avec le modèle OpenAI configuré. |

Les préférences sont communes à l'installation, pas personnelles à chaque utilisateur.
En web multi-utilisateurs, modification des réglages et génération payante exigent
les droits administrateur. La lecture expose l'état et les capacités `canEdit` /
`canGenerate`, jamais une clé. Studio conserve son modèle d'opérateur local avec
contrôle d'hôte et d'origine ; il n'ajoute pas une authentification multi-utilisateurs.

Choisir un mode, renseigner son modèle et éventuellement remplacer sa clé, puis
**Enregistrer le mode IA**. Enregistrer ces préférences ne contacte aucun fournisseur.
Le champ de clé reste vide à la lecture : vide signifie conserver, une nouvelle valeur
remplace, la suppression demande l'action explicite correspondante. Une clé imposée
par l'environnement ne peut être remplacée ou supprimée depuis l'interface.

La génération part uniquement du bouton explicite. Elle envoie au fournisseur choisi
le catalogue, artiste/titre, consignes et éventuel rig existant. Les consignes libres
peuvent préciser version studio/live, partie, guitare, micros, niveau d'entrée et écoute.
La réponse conforme **est enregistrée dans FretWise**, puis affichée pour examen.
Aucun transfert au HeadRush ne découle de cette action : l'envoi à l'instrument reste
une opération distincte avec son aperçu et sa confirmation existants.

## Préférences et secrets hors Git

Les fichiers sont lus par le compte exécutant le serveur. Aucun secret ne doit figurer
dans le dépôt, une image Docker, un exemple de documentation ou une sortie de diagnostic.

| Configuration | Chemin / valeur |
|---|---|
| Répertoire | `FRETWISE_CONFIG_DIR`, sinon `~/.fretwise` du compte serveur |
| Préférences | `<répertoire>/rig-ai.json` |
| Secrets | `FRETWISE_RIG_AI_SECRETS_FILE`, sinon `<répertoire>/rig-ai-secrets.json` |
| Clé OpenAI | `OPENAI_API_KEY` dans l'environnement, sinon champ homonyme du fichier de secrets |
| Clé Claude | `ANTHROPIC_API_KEY` dans l'environnement, sinon champ homonyme du fichier de secrets |

Une variable de clé non vide prime sur le fichier. `FRETWISE_RIG_AI_SECRETS_FILE`
ne déplace que les secrets ; `rig-ai.json` reste sous `FRETWISE_CONFIG_DIR`.
Les modèles et le mode sont des préférences du fichier, sans substitution dédiée
par variable d'environnement. Exemple de préférences sans secrets :

```json
{
  "mode": "manual",
  "openai_model": "gpt-5.6-terra",
  "anthropic_model": "claude-sonnet-4-6",
  "web_search": true
}
```

Ces modèles sont les valeurs par défaut du code, pas une garantie d'accès du compte
fournisseur. Le nom reste éditable. Les états publics `configured`, `keySource`
(`environment`, `file`, `none`) et `editable` décrivent la configuration sans révéler
la valeur ni un préfixe de clé. Le serveur doit lire la clé pour appeler le fournisseur ;
aucune API de lecture de paramètres ne la restitue.

Le choix initial OpenAI est [GPT-5.6 Terra](https://developers.openai.com/api/docs/models/gpt-5.6-terra),
qui prend en charge la recherche web dans Responses. La
[page GPT-5 Mini](https://developers.openai.com/api/docs/models/gpt-5-mini) oriente
les nouvelles charges à faible latence et grand volume vers Terra. Cette recommandation
générale ne mesure pas la qualité d'un rig ; un modèle déjà enregistré reste inchangé.

Les fichiers sont remplacés atomiquement après écriture complète. Les secrets sont
en clair sur disque, protégés par les permissions du système : `0600` sous POSIX,
ACL limitée au compte courant et à SYSTEM sous Windows. Les liens symboliques et
points de réanalyse Windows sont refusés. Les permissions protègent le fichier,
elles ne constituent pas un chiffrement.

Sous Windows, emplacement habituel : `%USERPROFILE%\.fretwise` du compte qui lance
Pixi/FretWise. Pour un autre répertoire, définir `FRETWISE_CONFIG_DIR` **avant** de
lancer le serveur ; choisir un chemin hors dépôt.

Le [Compose web](../docker/compose.web.yml) définit déjà `FRETWISE_CONFIG_DIR=/data/config`
et monte `/volume2/docker/fretwise/state/config:/data/config:rw`. Les deux fichiers
doivent donc être provisionnés dans ce volume pour le compte du conteneur
(`FRETWISE_UID:FRETWISE_GID`), ou les clés fournies par son environnement privé.
Une configuration Windows n'est pas automatiquement copiée dans Docker.
Ce provisionnement et la vérification authentifiée en production restent à réaliser
lors d'une **release autorisée** ; aucune publication de cette fonction n'est implicite.

## Migration du fichier de clés local

Le [script de migration](../scripts/migrate_rig_ai_keys.py) accepte un fichier texte
contenant exactement une clé distincte de chaque fournisseur. Depuis la racine du
dépôt et avec l'environnement Pixi du projet :

```powershell
# Simulation : aucune modification, aucune valeur de clé affichée.
rtk pixi run python scripts/migrate_rig_ai_keys.py

# Application explicite : vérifier d'abord le résultat de la simulation.
rtk pixi run python scripts/migrate_rig_ai_keys.py --apply
```

La source par défaut est `fretwise-keys.txt`. `--source` et `--destination` permettent
des chemins explicites ; la destination par défaut est
`<FRETWISE_CONFIG_DIR ou ~/.fretwise>/rig-ai-secrets.json`. Le script ne reprend pas
automatiquement `FRETWISE_RIG_AI_SECRETS_FILE` : dans ce cas, passer `--destination`
avec le même chemin que le serveur.

L'application refuse une destination située dans le dépôt de la source, des clés
existantes différentes ou des clés imposées par l'environnement. Elle protège le
fichier destination, vérifie les deux valeurs en mémoire, puis retire la source
seulement après succès. En cas d'échec, la source est conservée et aucun secret
n'est imprimé. Ne pas relire le contenu des fichiers pour vérifier la migration :
utiliser le résultat du script et l'état public des paramètres.

## API et validation

| Route | Contrat |
|---|---|
| `GET /api/rig-ai/settings` | Mode, modèles, disponibilité/source des clés et capacités ; `Cache-Control: no-store`. |
| `POST /api/rig-ai/settings` | Administration des préférences et remplacement/suppression des clés locales. |
| `POST /api/devices/headrush/generate` | Administration ; objet `{ "artist": "…", "title": "…", "guidance": "…" }`. Aucun modèle ni secret dans cette demande. |

La route charge le catalogue local, construit le même prompt que le mode manuel,
appelle le fournisseur, valide les formes JSON puis les modules, paramètres et
placements avec `parse_rig_response` / `build_plan`. Artiste et titre restent ceux
de la demande. Un premier rejet par ce validateur peut déclencher **une seule correction
technique automatique**, chez le même fournisseur et avec le même modèle, sans nouvelle
recherche web. Un clic entraîne donc au maximum deux appels fournisseur, potentiellement
facturés. Si la correction reste incompatible, réponse `422 rig_refused`, sans sauvegarde.
Un changement concurrent du rig entraîne `409 rig_changed`, sans écrasement.
Les écritures du binding sont atomiques ; la génération est sérialisée dans chaque
processus serveur. Les erreurs fournisseur sont reformulées sans réponse brute.

Les appels ont des limites de durée et de taille, sans nouvelle tentative après une
erreur réseau, redirection HTTP ou bascule vers l'autre fournisseur. Après l'échec
final, une nouvelle génération demande une action explicite. Les paramètres réseau
de proxy hérités de l'environnement ne sont pas
repris par le client HTTP.

La recherche web est activée par défaut et peut entraîner un coût fournisseur.
FretWise limite les appels d'outil à trois. Si elle est demandée mais non exécutée,
la génération échoue. La correction technique éventuelle ne relance pas ces recherches
et conserve leurs sources ; `generation.validationRepair` indique si elle a eu lieu.
Les URL enregistrées proviennent des résultats/citations
natifs du fournisseur, jamais uniquement des URL écrites par le modèle dans son JSON.
Sans source retournée, la confiance documentaire devient `unknown` avec avertissement.
Une recherche exécutée et une URL obtenue ne prouvent pas que chaque affirmation
du rig soit étayée par cette page.

## Preuves, limites et références

### Vérifications du 20 septembre 2026

- 370 tests ciblés : catalogue/prompt, appareils, API web, fournisseurs, secrets,
  sécurité Studio/web et contrôles JavaScript des deux interfaces.
- Essais API réels, avec préférences et rigs de test isolés : Claude
  `claude-sonnet-4-6` a rendu un rig validé de six blocs ; OpenAI
  `gpt-5.6-terra` a rendu un rig validé de quatre blocs, sans correction nécessaire
  sur ce dernier essai. Cible : rythmique studio de Nirvana, « On A Plain ».
- Les essais précédents OpenAI ont produit des paramètres ou enums invalides.
  Le validateur a refusé les candidats sans sauvegarde. La correction unique est
  couverte par tests déterministes ; ces quelques essais ne mesurent pas un taux
  général de réussite et ne comparent pas la qualité sonore des fournisseurs.
- Navigateur local : modes manuel/Claude/OpenAI, champs de préférences adaptés,
  panneau automatique compact, progression, résultat et réactivation après erreur.
  Les vrais modules frontend étaient servis avec une API simulée pour ces contrôles.
- `pixi lock --check` valide le verrou ; aucune version de paquet n'a changé.
  Les deux clés réelles sont absentes des fichiers candidats Git ; stockage privé
  Windows vérifié, ancien fichier racine retiré après transfert.

Aucun rig de test n'a été envoyé au HeadRush. La nouvelle fonction IA n'a pas été
déployée durant ces vérifications. La release des icônes
`20260920-081700-70dd186f` restait saine, avec disponibilité HTTPS confirmée.

Le bilan de conformité JSON prouve la compatibilité avec le catalogue et l'importeur
hors ligne. Il ne prouve ni l'import réel sur l'appareil, ni les fichiers IR/clones
disponibles, ni la consommation CPU, ni la fidélité sonore. Le prompt distingue
**FAIT SOURCÉ**, **ADAPTATION**, **À TESTER** et décrit le placement comme une limite
de l'importeur. Une comparaison acoustique exige un essai à niveau égal avec
guitare/micros et chaîne d'écoute précisés ; voir les
[niveaux de preuve](headrush_prompt_quality.md#évaluation-séparée-des-niveaux-de-preuve).

| Fournisseur | API officielle utilisée |
|---|---|
| OpenAI | `POST https://api.openai.com/v1/responses`, outil `web_search`, sources `web_search_call.action.sources`, réponse demandée avec `store: false` ; [documentation officielle](https://developers.openai.com/api/docs/guides/tools-web-search). |
| Claude | `POST https://api.anthropic.com/v1/messages`, version `2023-06-01`, outil `web_search_20250305` avec `max_uses` ; [Messages](https://platform.claude.com/docs/en/api/messages/create), [recherche web](https://platform.claude.com/docs/en/agents-and-tools/tool-use/web-search-tool). |

Références consultées le 20 septembre 2026. L'option OpenAI `store: false` n'est
pas une promesse générale d'absence de conservation chez les fournisseurs.

Code : [settings.py](../src/fretwise/rig_ai/settings.py),
[providers.py](../src/fretwise/rig_ai/providers.py),
[routes communes](../src/fretwise/web/rig_ai_routes.py),
[prompt et parseur](../src/fretwise/devices/headrush_core/prompt.py),
[présentation du catalogue](../src/fretwise/devices/headrush_core/prompt_catalog.py),
[interface partagée](../src/fretwise/web/static/js/headrush.js).
