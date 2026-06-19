# FretWise — pile d'acquisition des sources brutes (Synology)

Tourne **24/7 sur le NAS, PC éteint**. Remplit `data/song_raw_sources.json`.
Le PC lit ensuite ce fichier, appelle ollama/gemma4 localement, et produit `song_facts.json`.

## Architecture (séparation des charges)

```
NAS (Docker, PC éteint)                          PC (quand allumé)
┌──────────────────────────────────────┐        ┌──────────────────────────────────┐
│ searxng   — recherche keyless         │        │ ollama + gemma4 (lourd)          │
│ facts-worker                          │  sync  │                                  │
│   → search + fetch pages brutes  ─────┼──────>─┤ tools/extract_facts.py           │
│   → song_raw_sources.json             │        │   → lit sources brutes           │
└──────────────────────────────────────┘        │   → extrait avec ollama local    │
   I/O réseau pur, pas de modèle IA              │   → écrit song_facts.json        │
                                                 │                                  │
                                                 │ tools/rig_batch.py               │
                                                 │   → génère les fiches .md        │
                                                 └──────────────────────────────────┘
```

**Deux artefacts de rendez-vous :**
- `song_raw_sources.json` — NAS → PC (pages téléchargées, pas encore interprétées)
- `song_facts.json` — PC → batch (faits extraits, prêts pour la génération)

Ollama (extraction ET génération) **tourne uniquement sur le PC**.

## Prérequis Synology

- Modèle **x86 avec Container Manager** (DS220+/420+/720+/920+/1520+…). Pas les séries ARM `j`/`play`.
- ~1 Go RAM libres (SearXNG + worker stdlib-only, pas de modèle IA).

## Démarrage NAS

```bash
# 1) Générer un secret_key unique et le coller dans searxng/settings.yml :
python -c "import secrets; print(secrets.token_hex(32))"

# 2) Préparer le dossier data :
mkdir -p data
cp ../data/songs_index_clean.tsv data/songs.tsv   # liste artist/title

# 3) Lancer les containers (2 seulement : searxng + facts-worker)
docker compose up -d
docker compose logs -f facts-worker               # suivre l'acquisition
```

Le worker remplit `data/song_raw_sources.json` au fil du temps (~3-4 morceaux/min).
Il reprend tout seul après un redémarrage (`song_raw_sources.json` = checkpoint).

## Côté PC — extraction puis génération

Synchroniser `docker/data/song_raw_sources.json` du NAS vers `data/` du repo
(dossier partagé SMB ou rsync), puis :

```powershell
# Étape 1 : extraction ollama (lit les pages brutes, écrit song_facts.json)
pixi run python tools/extract_facts.py

# Étape 2 : génération des fiches ancrées
pixi run python tools/rig_batch.py
```

Tu peux lancer `extract_facts.py` **en cours de route** pendant que le NAS continue :
les morceaux déjà extraits sont sautés, les nouveaux sont traités à chaque lancement.

## Notes

- `searxng/settings.yml` : **change `server.secret_key`** avant la prod.
- Le worker est en stdlib pure (image Python standard, aucune dépendance pip).
- Tout est idempotent : `docker compose restart` ne perd rien.
