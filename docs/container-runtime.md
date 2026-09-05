# Profils runtime : serveur web et poste PC

Cette séparation complète la carte web de
[`architecture-classes.md`](architecture-classes.md) sans modifier les contrats M1–M5 de
[`fretwise_architecture.md`](fretwise_architecture.md).

## Profil `server`

Profil utilisé par l'image Docker/NAS (`FRETWISE_RUNTIME_PROFILE=server`) :

- conserve FastAPI, bibliothèque, parsing GP/MusicXML/MIDI, calcul de doigtés CPU, rendu et exports ;
- conserve consultation, résolution et recommandation des rigs GP-180 ;
- autorise les dry-runs MIDI, qui produisent seulement les octets à envoyer ;
- ne publie aucune route de génération LLM automatisée et refuse tout accès aux sorties MIDI matérielles ;
- n'installe pas `python-rtmidi` et ne copie pas `tools/codex_song_rig.py` ;
- embarque les huit modèles ONNX de production depuis une image privée immuable ;
- valide tailles et SHA-256 du bundle avant de servir les requêtes.

Capacités actives : `GET /api/runtime`.

## Profil `desktop`

Profil par défaut des environnements Pixi locaux : pilotage MIDI GP-180 actif. La feature Pixi
`pc` fournit `python-rtmidi` aux environnements `default` et `dev`. La génération automatisée
des rigs reste un outil batch hors application web.

## Frontière de déploiement

Le NAS sert l'application web, Viterbi et l'inférence ONNX avec
`CPUExecutionProvider`. Aucun GPU ni LLM n'est requis au runtime. Le navigateur conserve le
workflow humain « copier le prompt, interroger un LLM externe, coller le JSON ». Le PC ne sert
qu'aux outils batch historiques et au transport USB/MIDI optionnel.

## Bundle ONNX privé

Les binaires ONNX proviennent de datasets dont la licence de redistribution doit encore être
confirmée. Ils restent donc hors Git et hors registry publique. Le manifeste suivi
`data/models/runtime_bundle.json` verrouille version, tailles et SHA-256.

Construction locale de l'artefact modèles :

```powershell
pixi run -e server python -m fretwise.model_bundle data/models
docker build -f docker/models.Dockerfile -t fretwise-models:local .
```

Construction application :

```powershell
docker build --build-arg FRETWISE_MODELS_IMAGE=fretwise-models:local -t fretwise-web .
```

En registry privée, remplacer tag mutable par référence épinglée au digest :

```text
registry.example/fretwise-models@sha256:<digest>
```

Variables runtime image :

- `FRETWISE_REQUIRE_ML_MODELS=1` : échec de démarrage si bundle absent ou altéré ;
- `FRETWISE_MODEL_DIR=/app/data/models` : emplacement interne ;
- `FRETWISE_ONNX_THREADS=1` : limite threads intra-op par session.

`GET /health/live` vérifie processus. `GET /health/ready` et `GET /api/runtime` publient état
du bundle sans exposer chemin local.

## Déploiement UGREEN `mblanche`

Le service web utilise [`docker/compose.web.yml`](../docker/compose.web.yml), distinct de la
pile d'acquisition SearXNG. Contrat de stockage :

- `/volume1/gp` → `/data/partitions` en lecture/écriture ;
- `/volume2/docker/fretwise/state/{config,auth,cache,sounds,gears}` → état durable ;
- `/volume2/docker/fretwise/shared/fretwise.env` → secrets runtime, mode `0600`, hors Git ;
- UID/GID runtime `1000:10` (`benoit:admin` sur `mblanche`) ;
- port `8080` publié seulement sur loopback, derrière reverse proxy HTTPS UGREEN ;
- `FRETWISE_ALLOWED_HOSTS` limite noms/IP acceptés. Un reverse proxy HTTPS UGREEN reste requis
  avant exposition hors LAN.

Endpoint navigateur LAN : `https://fretwise.mblanche.direct.ug.link`. Technitium sert une
zone locale isolée pour ce nom vers `192.168.1.50`; Nginx utilise certificat wildcard ZeroSSL
géré par UGOS. Le bloc versionné est
[`docker/nginx/fretwise-ugreen.conf`](../docker/nginx/fretwise-ugreen.conf). Un drop-in
systemd le restaure après chaque régénération de configuration Nginx par UGOS.

Client doit utiliser DNS LAN Technitium distribué par DHCP. DNS sécurisé tiers, VPN ou iCloud
Private Relay peut ignorer zone locale ; désactiver « Limiter suivi adresse IP » pour Wi-Fi
concerné si résolution échoue. Google OIDC éventuel doit autoriser callback
`https://fretwise.mblanche.direct.ug.link/auth/callback/google`.

Les variables `FRETWISE_PARTITIONS_DIR`, `FRETWISE_SOUNDFONTS_DIR` et
`FRETWISE_GEARS_DIR` sont autoritaires. Elles neutralisent tout chemin Windows résiduel dans
`config.json` et les réglages correspondants deviennent non modifiables via API.

Lancement depuis une release immuable :

```sh
cd /volume2/docker/fretwise/current
sudo docker compose -f docker/compose.web.yml config --quiet
sudo docker compose -f docker/compose.web.yml up -d --build
```

Une seule instance web doit écrire ces fichiers JSON. Ne pas monter socket Docker, USB ou
MIDI dans ce conteneur.

Le fichier de secrets est chargé avec `env_file.format: raw` : indispensable pour préserver
les caractères `$` des hashes PBKDF2.
