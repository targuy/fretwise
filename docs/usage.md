# FretWise — Guide d'usage

Ce guide couvre les workflows de bout en bout de FretWise après la consolidation
des trois domaines utilitaires (bibliothèque de partitions, fiches gears,
entraînement des modèles de doigtés). Pour l'inventaire script par script, voir
[scripts/README.md](../scripts/README.md). Pour l'architecture, voir
[architecture.md](architecture.md).

---

## 1. Environnement

Le projet est géré par **pixi** (Python 3.11) :

```powershell
cd D:\DocumentsBenoit\pythonProject\fretwise
pixi install                 # environnement par défaut (runtime + web + ML inférence)
pixi install -e train        # + XGBoost/sklearn/onnxmltools pour l'entraînement
pixi run test                # suite pytest complète
```

Environnements définis dans `pixi.toml` :

| Env | Contenu | Usage |
|---|---|---|
| `default` | runtime complet (parsers, web, onnxruntime, cloud, auth, requests) | usage quotidien |
| `dev` | + pytest-cov, ruff, mypy | développement |
| `train` | + xgboost, scikit-learn, onnx(mltools), pandas, pyarrow, bs4, lxml, tqdm | entraînement des modèles |

Variables d'environnement (toutes optionnelles, défauts raisonnables) :

| Variable | Défaut | Rôle |
|---|---|---|
| `FRETWISE_PARTITIONS_ROOT` | `C:\Users\benoit\iCloudDrive\partitions` | racine de la bibliothèque de partitions |
| `FRETWISE_DOWNLOADS_DIR` | `~/Downloads` | dossier surveillé pour les `.gp` téléchargés |
| `FRETWISE_GDRIVE_DIR` | `G:\Mon Drive\partitions` | miroir Google Drive |
| `FRETWISE_GEARS_DIR` | `<repo>/data/gears` | fiches gears JSON |
| `FRETWISE_DATASET_ROOT` | `D:\...\GuitarDataSet` | données brutes/intermédiaires d'entraînement |
| `FRETWISE_HANDOFF_DIR` | `D:\...\handoff-FretWise-GuitarDataset` | tampon d'échange historique (déprécié) |
| `NOTION_TOKEN` | — | requis uniquement pour la sync Notion directe |

---

## 2. Doigtés : parse → solve → export

Le cœur historique de FretWise :

```powershell
fretwise parse song.gp                    # inspecter les notes
fretwise solve song.gp                    # doigtés optimaux → PDF + ASCII
fretwise solve song.gp --mode performance --output song.pdf
fretwise finger song.gp                   # annote le .gp en place
fretwise convert song.gp out.musicxml     # conversion via le modèle canonique
fretwise web                              # interface web complète (port 8080)
```

Modes de pondération : `reference`, `performance`, `musical`, `learning`
(voir la fonction de coût dans [architecture.md](architecture.md)).

Les modèles ML (si présents dans `data/models/` et `onnxruntime` installé) sont
chargés automatiquement et améliorent le choix des doigts ; sans eux, le pipeline
retombe proprement sur les règles biomécaniques.

Batch sur toute la bibliothèque : `pixi run python tools/finger_batch.py`
(reprise sur interruption, multi-cœurs).

---

## 3. Bibliothèque de partitions (Songsterr)

### Cycle quotidien

```powershell
pixi run partitions-daily      # move → rebuild → enrich → propose → archive
```

Étapes individuelles :

```powershell
pixi run partitions-move       # déplace les .gp de Downloads (dédup par identité)
pixi run partitions-rebuild    # régénère songs_index.tsv + liste_partitions.txt
pixi run partitions-propose    # propose des morceaux + prompt Songsterr du jour
pixi run python scripts/partitions_tag_genres.py --dry-run
pixi run python scripts/partitions_archive_old.py
```

### Télécharger de nouvelles partitions

Songsterr n'a pas d'API de téléchargement : FretWise **génère un prompt** que
Claude-in-Chrome exécute (compte Songsterr Plus requis, IDs DOM stables
`#control-export` / `#control-export-gp`).

1. `pixi run partitions-propose` (ou `partitions_curate_beginners.py` pour le
   pool débutants) → produit `prompt-songsterr-<date>.md` dans la racine partitions.
2. Vérification anti-doublons obligatoire : `partitions_check.py candidats.txt`.
3. Donner le prompt à Claude-in-Chrome ; les `.gp` arrivent dans Downloads.
4. `pixi run partitions-move` puis `pixi run partitions-rebuild`.

### Synchronisation Notion et Google Drive

```powershell
# File de travail token-éco pour l'agent Notion (aucun appel réseau) :
pixi run python scripts/partitions_enrich_notion.py

# Sync directe (écrit dans Notion, nécessite NOTION_TOKEN) :
$env:NOTION_TOKEN = "..."
pixi run python scripts/partitions_notion_sync.py --dry-run

# Miroir Google Drive (jamais de suppression côté Drive) :
pixi run python scripts/partitions_sync_gdrive.py --dry-run
```

`songs_index.tsv` (10 colonnes, dont `genre`/`guitar`/`rig`/`notion_id` possédées
par Notion et préservées au rebuild) est la **source de vérité locale** : toute
recherche par genre/rig se fait par grep du TSV, pas par appel Notion.

Les watchers PowerShell (surveillance de Downloads, tâche planifiée) restent dans
la racine partitions ; ils appellent désormais les modules `fretwise.partitions.*`.

---

## 4. Fiches gears (son par chanson)

Les fiches JSON `data/gears/<artiste>__<titre>.json` (schéma
`songsgear.fretwise.gear.v2`) décrivent le rig GP-180/NAM par chanson et sont
servies par l'interface web (`/api/rig/<fichier>`), avec priorité sur les fiches
`.md` legacy.

### Consulter / valider l'existant

```powershell
pixi run gears-validate        # valide les fiches contre le schéma
pixi run gears-supersede       # purge les données legacy supersédées par les fiches
```

### Produire de nouvelles fiches

```powershell
# Une chanson, provider au choix (mock = sans réseau) :
pixi run python scripts/gears_recommend.py --artist "Dire Straits" --title "Sultans of Swing" --provider mock

# Prompt seul (pour un LLM externe) :
pixi run python scripts/gears_prompt.py --artist ... --title ...

# Pipeline de production économique (Ollama draft → juge OpenAI → escalade Claude),
# reprise par checkpoint, clés API via .env :
pixi run python scripts/gears_production_batch.py --input songs.tsv

# Post-traitement : export du bloc rig.v1, normalisation, compaction en gear.v2 :
pixi run python scripts/gears_export.py
pixi run python scripts/gears_normalize.py
pixi run gears-compact
```

Le « delta » est géré par **supersede-par-clé** : la clé canonique
`artiste__titre` (`fretwise.gears.naming`, partagée producteur/consommateur)
fait qu'une fiche JSON remplace automatiquement la fiche legacy du même morceau,
au runtime (priorité API) comme au nettoyage (`gears_supersede`).

---

## 5. Entraînement des modèles de doigtés

Trois familles de modèles XGBoost→ONNX, consommées par `fretwise.ml` :

| Modèle | Features | Fichiers dans `data/models/` |
|---|---|---|
| `finger_classifier` (accords) | 24 | `finger_classifier.onnx` + spec |
| `transition_cost` v3 (C_joueur/γ) | 26 | `transition_cost_v3.onnx` + spec/calibration |
| `phrase_window` v2 (mélodique, **actif**) | 74 | 6 têtes ONNX + manifest/spec/calibration |

Cycle complet (environnement `train`, données sous `FRETWISE_DATASET_ROOT`) :

```powershell
# 1. Construire les datasets de features
pixi run -e train python scripts/dataset_build_chords.py
pixi run -e train python scripts/dataset_build_sequential.py
pixi run -e train python scripts/dataset_build_transitions.py
pixi run -e train python scripts/dataset_build_phrase_window.py

# 2. Entraîner
pixi run -e train python scripts/dataset_train_finger_classifier.py
pixi run -e train python scripts/dataset_train_transition_cost.py
pixi run -e train python scripts/dataset_train_phrase_window.py

# 3. Exporter en ONNX + specs vers data/models/
pixi run -e train python scripts/dataset_export_onnx.py
pixi run -e train python scripts/dataset_build_specs.py
pixi run -e train python scripts/dataset_build_calibration.py

# 4. Évaluer avant déploiement
pixi run -e train python scripts/dataset_eval_fretwise.py
pixi run -e train python scripts/dataset_eval_phrase_window.py
```

**Contrat de parité** : les extracteurs de features d'entraînement
(`fretwise.dataset.features`) et d'inférence (`fretwise.ml`) doivent produire
des vecteurs identiques ; les JSON de calibration dans `data/models/` sont
vérifiés bit à bit par les tests (`tests/test_ml_phrase_window.py`,
`tests/test_dataset_port.py`). Toute évolution de features doit mettre à jour
les deux côtés + la calibration.

Convention : cordes 0-based (0 = mi aigu) côté dataset, 1-based côté FretWise ;
seule l'étiquette de doigt est modifiée par les modèles (corde/frette/position
restent choisies par les règles).

---

## 6. QA avant commit

```powershell
pixi run -e dev ruff check src/ tests/
pixi run -e dev mypy src/fretwise
pixi run test                          # pytest -v (couverture cible ≥ 80 %)
```
