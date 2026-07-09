# FretWise — Architecture globale (post-consolidation)

Ce document décrit l'architecture d'ensemble après la consolidation (juillet 2026)
des trois projets utilitaires dans FretWise. Il complète, sans les remplacer :

- [fretwise_architecture.md](fretwise_architecture.md) — spécification fonctionnelle des modules M1–M6 ;
- [architecture-classes.md](architecture-classes.md) — carte des classes du code réel ;
- [ARCHITECTURE_CORE.md](ARCHITECTURE_CORE.md) — moteur de notation/gravure `core/` ;
- [usage.md](usage.md) — guide des workflows ; [../scripts/README.md](../scripts/README.md) — inventaire des CLI.

---

## 1. Vue d'ensemble

```
fretwise/
├── src/fretwise/
│   ├── parser/ generator/ patterns/ scoring/ optimizer/ profile/   # M1–M6 (cœur doigtés)
│   ├── segmentation/ biomechanics/ audit/ review/                  # passes qualité doigtés
│   ├── core/                       # moteur de notation/gravure (ingest → scene → backends)
│   ├── export/                     # PDF/SVG/ASCII, GP writer, MusicXML writer, hand viz
│   ├── ml/                         # INFÉRENCE ONNX (finger_classifier, transition_cost, phrase_window)
│   ├── web/  auth/  storage/       # FastAPI, OIDC multi-utilisateurs, backends cloud
│   ├── partitions/                 # ★ bibliothèque de partitions Songsterr (consolidé)
│   ├── gears/                      # fiches « son » par chanson
│   │   ├── naming.py adapter.py    #   consommateur (clé canonique, rendu web)
│   │   └── production/             # ★ producteur LLM + schémas + outils (consolidé)
│   ├── dataset/                    # ★ usine de données & ENTRAÎNEMENT des modèles (consolidé)
│   └── cli.py  models.py  pipeline.py  rig*.py  config/
├── scripts/                        # ★ TOUS les CLI (wrappers fins vers src/fretwise/*)
├── tools/                          # outillage opérationnel lourd (finger_batch, loupedeck…)
├── data/                           # gears/, models/, patterns/, profiles/, song_facts…
├── tests/                          # suite pytest unique (~1800 tests)
└── docs/
```

★ = domaines consolidés depuis les anciens projets `iCloudDrive\partitions`,
`SongsGear\SongsGears` et `GuitarDataSet` (les dépôts d'origine deviennent des
archives ; les données volumineuses d'entraînement restent sous
`FRETWISE_DATASET_ROOT`).

## 2. Cœur doigtés (inchangé — règle d'or M5)

Le pipeline `parse → generate → score → optimize` reste le contrat central :
la fonction de coût composite `C = α·C_méca + β·C_music + γ·C_joueur + δ·C_péda`
est **injectée** dans `ViterbiOptimizer` (M5), dont l'interface publique ne change
jamais. Les modèles ML n'interviennent que comme composantes injectées :
`LearnedPlayerCost` alimente γ/C_joueur, `LearnedChordFingerClassifier` et
`LearnedPhraseWindowFingerer` ne modifient que l'étiquette de **doigt**
(corde/frette/position restent choisies par les règles), avec repli silencieux
sur les règles biomécaniques si `onnxruntime` ou les modèles manquent.

## 3. Les trois domaines consolidés

### 3.1 `fretwise.partitions` — bibliothèque de partitions

Pipeline local-d'abord : le PC fait tout le travail lourd, les agents IA ne font
que l'enrichissement Notion et la découverte de nouveaux morceaux.

```
Downloads ──move_downloads──► <root>/partitions/*.gp  (dédup par identité normalisée)
                                   │ rebuild_indexes
                                   ▼
              songs_index.tsv (source de vérité, 10 colonnes)
              liste_partitions.txt
                    │                         │
        enrich_from_notion (file JSON)   propose_songs (anti-dup R1–R4)
                    ▼                         ▼
          _notion_queue/*.json      prompt-songsterr-<date>.md ──► Claude-in-Chrome
                                                                   (Songsterr Plus, IDs DOM stables)
```

Contrats :
- `lib.parse_filename` / `normalize_identity` définissent l'identité d'un morceau
  (artiste composé, décodage `_`) — partagés par tous les modules du package ;
- les colonnes `year/genre/guitar/rig/notion_id` du TSV appartiennent à Notion et
  sont **préservées** au rebuild ;
- `notion_ids.py` centralise les IDs Notion (canoniques + `LEGACY_*` documentés) ;
- `paths.py` centralise racine/downloads/GDrive (env vars, cf. usage.md §1) ;
- `daily_sync` orchestre par appels de fonctions (plus de subprocess).

Les watchers PowerShell (surveillance Downloads, tâches planifiées) restent dans
la racine partitions et appellent les wrappers `scripts/partitions_*.py`.

### 3.2 `fretwise.gears` — fiches « son » par chanson (producteur + consommateur)

```
producteur (gears/production)                          consommateur (gears + web)
─────────────────────────────                          ──────────────────────────
llm.py providers mock/ollama/openai/claude
tools/run_economic_production_batch  ──► JSON verbose
fretwise_export.build_fretwise_export ──► bloc rig.v1
tools/compact_fretwise_gears ──────────► data/gears/<clé>.json (gear.v2)
                                                       adapter.song_output_to_view
                                                       web /api/rig/<fichier>
                                                       tools/supersede_with_gears
```

Contrats :
- **Clé canonique unique** : `fretwise.gears.naming.gears_key(artist, title)`
  (`artiste__titre` slugifié). C'était un fichier dupliqué entre les deux anciens
  repos avec obligation d'identité octet par octet — il n'existe plus qu'ici.
  L'index web tolère les deux styles de nommage historiques des fichiers
  (kebab et TitleCase souligné) en re-slugifiant chaque moitié du stem.
- **Schémas** : `songsgear.fretwise.rig.v1` (bloc d'export, validé par
  `fretwise_export.validate_fretwise_export`) et `songsgear.fretwise.gear.v2`
  (fiche compacte de rendu, produite par `compact_fretwise_gears`). L'adapter
  consommateur accepte v2, v1 et le legacy.
- **Gestion du delta = supersede par clé** : une fiche `data/gears/<clé>.json`
  prime sur la fiche `.md` legacy au runtime (priorité API) et
  `gears_supersede` purge les données legacy correspondantes (idempotent).
- Point de vigilance connu : les tables GP-180 existent en deux exemplaires
  (`gears/production/fretwise_export.MODULE_BY_MODEL` côté producteur,
  `fretwise/rig.py` côté legacy) — voir ROADMAP.

### 3.3 `fretwise.dataset` — usine de données & entraînement des modèles

```
sources (ClassClef, gaps, chords, bulk GP…  sous FRETWISE_DATASET_ROOT)
   │ parsers/ (guitarpro, musicxml, midi, ascii_tab, chord_db)
   ▼
data_schema/ (schéma unifié)  ── features/ (chord 24, transition 26, phrase_window 74)
   │ pipeline/build_*                        │ pipeline/train_* (XGBoost)
   ▼                                         ▼
datasets .npy/.json                pipeline/export_onnx + build_specs + build_calibration
                                             ▼
                              data/models/*.onnx + *_spec.json + *_calibration.json
                                             ▼
                              fretwise.ml (inférence, INTOUCHÉ par ce package)
```

Contrats :
- **Parité des features** : `fretwise.dataset.features.*` (entraînement) et
  `fretwise.ml` (inférence) doivent produire des vecteurs identiques ; les JSON
  de calibration dans `data/models/` sont la preuve versionnée, vérifiée par
  `tests/test_ml_phrase_window.py` et `tests/test_dataset_port.py` ;
- convention cordes : 0-based (0 = mi aigu) côté dataset, 1-based côté FretWise ;
- `exporters/fretwise.py` importe désormais `fretwise.models` directement
  (le pont NoteEvent n'est plus conditionnel) ;
- le dossier de handoff `handoff-FretWise-GuitarDataset` est **déprécié** :
  l'export ONNX écrit directement dans `data/models/`.

## 4. Regroupement des CLI dans `scripts/`

Tous les points d'entrée sont des **wrappers fins** (`scripts/<domaine>_<action>.py`)
qui importent `fretwise.<domaine>.<module>.main` (fallback `sys.path` si le
package n'est pas installé). La logique vit toujours dans `src/fretwise/` —
un wrapper ne contient jamais de logique métier. Le CLI principal `fretwise`
(click) reste l'entrée pour le cœur doigtés/web. Les tâches pixi exposent les
commandes les plus courantes (`pixi run partitions-daily`, `gears-validate`…).

## 5. Environnements & dépendances

- **pixi** est l'environnement de référence (`default`, `dev`, `train` —
  cf. usage.md §1) ; `pyproject.toml` porte les mêmes groupes en
  `optional-dependencies` (`ml`, `cloud`, `auth`, `partitions`, `train`,
  `monitor`) pour une installation pip hors pixi.
- Les packages consolidés sont stdlib-only sauf : `partitions.notion_sync`
  (requests), `dataset.pipeline`/`scrapers` (feature `train`, imports gardés avec
  message d'installation clair).
- Toute la configuration machine-spécifique passe par variables d'environnement
  avec défauts raisonnables (tableau complet dans usage.md §1) ; plus aucun
  chemin absolu `C:\`/`G:\` codé en dur hors défauts documentés. Tous les
  environnements (dev, exécution, entraînement) vivent sous `D:\...\fretwise` —
  un seul checkout, plus de dépôt secondaire sur un autre lecteur.

## 6. Ce qui n'a volontairement PAS été porté

- **partitions** : `notion_finish_path_updates.py` (migration one-shot exécutée),
  `_gen_rigs.py`/`_md_to_pdf.py` (supersédés par les fiches gears),
  `_analyze_have.py`, le pseudo-`CLAUDE.md` cassé, les doublons iCloud (` 2`/` 3`).
- **SongsGears** : le corpus `Output/` (données générées), l'environnement
  `.pixi` local, les `.bat` (remplacés par les wrappers/tâches pixi).
- **GuitarDataSet** : les crawlers one-shot ClassClef/bcfz, le sous-projet
  `guitar-fingerings-harvester/` (version antérieure absorbée), les dumps
  regénérables (`gp7_all_sequences.json` 1 Go, `classclef_sequential_fingering.json`
  992 Mo), le prototype PyTorch abandonné.

La liste du code mort restant à purger dans le repo est tenue dans
[ROADMAP.md](ROADMAP.md) (§ nettoyage).
