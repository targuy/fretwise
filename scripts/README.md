# scripts/ — Tous les CLI FretWise

Ce répertoire regroupe **tous les points d'entrée en ligne de commande** du projet :
le CLI principal `fretwise` (installé via pixi), les wrappers des trois domaines
consolidés (`partitions_*`, `gears_*`, `dataset_*`) et les utilitaires de
développement historiques.

Tout s'exécute depuis la racine du repo, dans l'environnement pixi :

```powershell
pixi run python scripts/<script>.py [args]
# ou pour les tâches courantes définies dans pixi.toml :
pixi run partitions-daily
pixi run gears-validate
```

Les wrappers sont autonomes : si `fretwise` n'est pas installé dans
l'environnement, ils ajoutent `src/` au `sys.path` automatiquement.

---

## CLI principal

Le point d'entrée `fretwise` (défini dans `pyproject.toml`) n'est pas dans ce
répertoire mais reste le CLI central :

| Commande | Rôle |
|---|---|
| `fretwise parse <fichier>` | Affiche la séquence de notes d'un fichier GP/MusicXML/MIDI |
| `fretwise solve <fichier>` | Calcule les doigtés optimaux → JSON/PDF/ASCII |
| `fretwise finger <fichier.gp>` | Annote un `.gp` en place avec les doigtés |
| `fretwise convert <in> <out>` | Conversion GP/MIDI → MusicXML, réannotation GP |
| `fretwise info` / `formats` | Métadonnées / formats supportés |
| `fretwise web` / `gui` | Interface web FastAPI |
| `fretwise hash-password` | Aide à la configuration multi-utilisateurs |

---

## Bibliothèque de partitions — `partitions_*` (→ `fretwise.partitions`)

Gestion de la bibliothèque de partitions Songsterr (racine : `FRETWISE_PARTITIONS_ROOT`,
défaut `C:\Users\benoit\iCloudDrive\partitions`). L'index `songs_index.tsv` est la
source de vérité locale ; le téléchargement Songsterr se fait via un prompt généré
pour Claude-in-Chrome (pas d'API Songsterr).

| Script | Rôle |
|---|---|
| `partitions_daily_sync.py` | **Orchestrateur quotidien** : move → rebuild → enrich → propose → archive |
| `partitions_move_downloads.py` | Déplace les `.gp` de Downloads vers la bibliothèque, dédup par identité |
| `partitions_rebuild.py` | Régénère `songs_index.tsv` + `liste_partitions.txt` (préserve les colonnes Notion) |
| `partitions_propose.py` | Propose N morceaux (anti-dup, équilibrage artistes/genres) + prompt Songsterr |
| `partitions_check.py` | Filtre une liste de candidats contre le TSV avant téléchargement |
| `partitions_songsterr_prompt.py` | Régénère le prompt de téléchargement Songsterr (IDs DOM stables) |
| `partitions_curate_beginners.py` | Prompt Songsterr depuis le pool "débutants" intégré |
| `partitions_tag_genres.py` | Auto-tag genre/guitare dans le TSV (table artiste→genre) |
| `partitions_enrich_notion.py` | Construit la file `_notion_queue/` pour l'agent d'enrichissement (aucun appel réseau) |
| `partitions_notion_sync.py` | Sync directe vers Notion (nécessite `NOTION_TOKEN`, dép. `requests`) |
| `partitions_sync_songs.py` | rebuild/diff/fetch-missing/propose-writes/sync avec un export Notion |
| `partitions_sync_gdrive.py` | Copie la bibliothèque vers Google Drive (`FRETWISE_GDRIVE_DIR`) |
| `partitions_archive_old.py` | Archive les artefacts datés dans `_archive_logs/` |

Variables d'environnement : `FRETWISE_PARTITIONS_ROOT`, `FRETWISE_DOWNLOADS_DIR`,
`FRETWISE_GDRIVE_DIR`, `NOTION_TOKEN`.

## Fiches gears — `gears_*` (→ `fretwise.gears.production`)

Production des fiches « son » par chanson (schémas `songsgear.fretwise.rig.v1` /
`gear.v2`), stockées dans `data/gears/<artiste>__<titre>.json` et servies par
l'interface web (`/api/rig`). La clé canonique vient de `fretwise.gears.naming`.

| Script | Rôle |
|---|---|
| `gears_run.py` | Batch : CSV/TSV de chansons → payloads Notion + `rigs.jsonl` |
| `gears_recommend.py` | Génère un rig pour une chanson (providers mock/ollama/openai/claude) |
| `gears_prompt.py` | Émet le prompt LLM (complet ou par étage) sans appel API |
| `gears_assemble_stages.py` | Assemble 3 JSON d'étages en un rig complet (sans API) |
| `gears_production_batch.py` | **Pipeline de production économique** : draft Ollama → juge OpenAI → escalade Claude ; reprise par checkpoint |
| `gears_export.py` | Extrait le bloc `fretwiseExport` (rig.v1) des sorties verboses |
| `gears_compact.py` | Compacte les sorties verboses en fiches `gear.v2` |
| `gears_normalize.py` | Normalise les exports existants |
| `gears_validate.py` | Valide les fiches contre le schéma |
| `gears_supersede.py` | Fait des fiches gears la source unique (purge `curated_facts` + `.md` legacy) |

Variables d'environnement : `FRETWISE_GEARS_DIR` (défaut `data/gears`), clés API
via `.env` (voir `fretwise.gears.production.env`).

## Dataset & entraînement doigtés — `dataset_*` (→ `fretwise.dataset`)

Usine de données et d'entraînement des modèles ONNX consommés par `fretwise.ml`
(finger_classifier, transition_cost, phrase_window). Nécessite l'environnement
`train` : `pixi run -e train python scripts/dataset_*.py`. Les données brutes
restent sous `FRETWISE_DATASET_ROOT` (défaut `D:\DocumentsBenoit\pythonProject\GuitarDataSet`).

| Script | Rôle |
|---|---|
| `dataset_build_chords.py` | Construit le dataset d'accords unifié |
| `dataset_build_transitions.py` | Features de transition (X/y .npy) |
| `dataset_build_phrase_window.py` | Dataset fenêtres de phrase (74 features) |
| `dataset_build_sequential.py` | Set d'entraînement séquentiel depuis les sources annotées |
| `dataset_build_calibration.py` | Exemples de calibration (parité train/inférence) |
| `dataset_build_specs.py` | Génère les specs JSON des modèles |
| `dataset_train_finger_classifier.py` | Entraîne le classifieur de doigts d'accords (XGBoost) |
| `dataset_train_transition_cost.py` | Entraîne le coût de transition v3 |
| `dataset_train_phrase_window.py` | Entraîne le modèle phrase-window (6 têtes) |
| `dataset_export_onnx.py` | Export XGBoost → ONNX vers `data/models/` |
| `dataset_eval_fretwise.py` | Évalue le pipeline fretwise contre le dataset annoté |
| `dataset_eval_phrase_window.py` | Évaluation du modèle phrase-window |
| `dataset_validate_quality.py` | Contrôle qualité des doigtés du dataset |

Variables d'environnement : `FRETWISE_DATASET_ROOT`, `FRETWISE_HANDOFF_DIR`.

---

## Utilitaires historiques (dev / QA / assets)

| Groupe | Scripts | Rôle |
|---|---|---|
| Install / run | `install.{sh,ps1,bat}`, `run.{sh,ps1,bat}`, `run_local.{sh,ps1,bat}`, `pixi-helpers.{ps1,bat}`, `validate_p0.sh` | Wrappers d'installation et de lancement multi-OS |
| Audits doigtés | `audit_finger_distribution.py`, `audit_ring_pinky_measures.py`, `audit_fingering_consistency_views.py`, `audit_full_corpus_compare.py`, `quality_scan_corpus.py`, `compare_partition_fingerings.py` | Audits qualité sur le corpus |
| Diagnostics notation | `check_tuplet_brackets.py`, `diag_tab_rhythm_tuplets.py`, `debug_beams.py` | Diagnostics de gravure |
| Éval ML (golden set) | `eval_phrase_window_golden.py`, `eval_phrase_window_triplet.py`, `export_golden_to_jsonl.py`, `prototype_delta1.py`, `validate_delta1_on_real_errors.py`, `validate_feature_extraction.py`, `validate_phase2_active.py` | Évaluations historiques des modèles |
| Drivers | `run_fingering.py`, `validate_concordance.py` | Benchmarks batch (antérieurs au CLI) |
| Assets | `build_leather_icons.py`, `slice_wood.py`, `generate_hand_viz.py`, `bake_hand_scale.cjs`, `sf2_to_sf3.mjs`, `sf3_validate.mjs`, `docx_to_md.py` | Génération d'assets web/soundfonts/docs |

Voir aussi `tools/` pour l'outillage opérationnel lourd (batch de doigtés
`finger_batch.py`, génération de rigs legacy, profils Loupedeck/GP-180) et
[docs/usage.md](../docs/usage.md) pour les workflows complets.
