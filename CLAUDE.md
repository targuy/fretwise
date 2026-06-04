# CLAUDE.md — FretWise

> **Guitar Fingering Optimization System**
> Ce fichier est lu automatiquement par Claude Code à chaque session.
> Il définit les règles du projet, les conventions et le contexte nécessaire pour contribuer efficacement.

---

## 📚 Documentation de référence

Avant toute action, consulter ces trois fichiers de spécifications situés à la racine du projet :

| Fichier | Contenu |
|---|---|
| `fretwise_architecture.docx` | Architecture fonctionnelle et technique — 6 modules (M1–M6), modèle de données, fonction de coût composite, formats de sortie, roadmap |
| `fretwise_conception_donnees.docx` | Acquisition des données externes — datasets (DadaGP, GuitarSet, GAPS, Iino 2025), formats d'entrée, pipeline de parsing, bibliothèques Python |
| `fretwise_plan_projet.docx` | Plan projet — 4 phases, 12 sprints, critères de succès, métriques de suivi, gestion des risques |

**Règle :** toute décision d'implémentation doit être traceable à l'une de ces spécifications. En cas d'ambiguïté, demander une clarification plutôt qu'inventer.

---

## 🏗️ Architecture du projet

### Vue d'ensemble

FretWise modélise l'optimisation des doigtés guitare comme un **problème de plus court chemin dans un graphe d'états**, résolu par l'algorithme de Viterbi.

### Six modules fonctionnels

```
fretwise/
├── parser/       # M1 — Lecture et normalisation (GP, MusicXML, MIDI)
├── generator/    # M2 — Génération des états possibles (corde, fret, doigt)
├── patterns/     # M3 — Reconnaissance de patterns (accords, gammes)
├── scoring/      # M4 — Fonction de coût composite C(s1, s2)
├── optimizer/    # M5 — Algorithme de Viterbi (NE JAMAIS MODIFIER l'interface)
└── profile/      # M6 — Profil joueur et calibration
```

### Contrat d'interface — RÈGLE D'OR

**M5 (Viterbi) est le seul module qui ne change jamais.** La fonction de coût est **injectée** dans l'optimiseur, jamais codée en dur. Chaque module peut évoluer indépendamment tant qu'il respecte son contrat d'entrée/sortie.

### Modèles de données centraux

```python
# Unité atomique du parser
@dataclass
class NoteEvent:
    pitch: int          # MIDI 0-127
    onset: float        # beats depuis le début
    duration: float     # durée en beats
    tempo: float        # BPM local
    articulation: str   # normal|legato|staccato|slide|hammer_on|pull_off|bend|vibrato
    dynamic: str        # pp|p|mp|mf|f|ff

# Choix complet pour jouer une note
@dataclass
class FingeringState:
    string_num: int     # 1-6
    fret: int           # 0-24
    finger: str         # open|index|middle|ring|pinky
    hand_position: int  # fret couverte par l'index
```

### Fonction de coût

```
C(s1, s2) = α·C_méca(s1, s2) + β·C_music(s1, s2) + γ·C_joueur(s1, s2) + δ·C_péda(s1, s2)
```

Modes de pondération (α, β, γ, δ) :
- **Performance** : (1, 0.5, 2, 0) — concert/enregistrement
- **Musical** : (1, 2, 1, 0) — travail d'interprétation
- **Apprentissage** : (1, 0.5, 1, 1.5) — travail technique
- **Référence** : (1, 1, 0, 0) — benchmark pur

---

## 📁 Structure du projet

```
fretwise/
├── CLAUDE.md                          ← ce fichier
├── fretwise_architecture.docx         ← spécifications architecture
├── fretwise_conception_donnees.docx   ← spécifications données
├── fretwise_plan_projet.docx          ← plan projet
│
├── pyproject.toml
├── README.md
├── .gitignore
├── .github/
│   └── workflows/
│       └── ci.yml
│
├── src/
│   └── fretwise/
│       ├── __init__.py
│       ├── cli.py                     ← point d'entrée CLI
│       ├── models.py                  ← NoteEvent, FingeringState, FingeringResult
│       ├── parser/
│       │   ├── __init__.py
│       │   ├── base.py                ← interface abstraite AdapterParser
│       │   ├── guitarpro_adapter.py   ← PyGuitarPro (.gp3/4/5)
│       │   ├── musicxml_adapter.py    ← music21 (.xml/.mxl)
│       │   └── midi_adapter.py        ← mido (.mid)
│       ├── generator/
│       ├── patterns/
│       │   └── data/                  ← fichiers YAML (accords, gammes)
│       ├── scoring/
│       ├── optimizer/
│       └── profile/
│
├── tests/
│   ├── fixtures/                      ← fichiers GP de test (5-10 morceaux simples)
│   ├── test_parser.py
│   ├── test_generator.py
│   ├── test_scoring.py
│   ├── test_optimizer.py
│   └── test_integration.py
│
├── data/
│   ├── patterns/                      ← patterns YAML versionés
│   └── profiles/                      ← profils joueur JSON
│
└── docs/
    └── benchmarks/                    ← résultats de concordance
```

---

## ⚙️ Stack technique

| Composant | Technologie | Version cible |
|---|---|---|
| Langage | Python | 3.11+ |
| Parsing GP | PyGuitarPro | 0.10.x |
| Parsing MusicXML | music21 | latest |
| Parsing MIDI | mido / pretty_midi | latest |
| Datasets audio | mirdata | latest |
| Calcul matriciel | NumPy | latest |
| Tests | pytest | latest |
| Lint | ruff | latest |
| Type checking | mypy | strict |
| CI/CD | GitHub Actions | — |
| Profil joueur (MVP) | JSON versionné | — |
| Profil joueur (Phase 3+) | SQLite | — |
| Interface web (Phase 3+) | React + FastAPI | — |
| IA (Phase 4) | PyTorch | latest |

---

## 🐍 Conventions Python

### Style et qualité

- **Type hints obligatoires** sur toutes les fonctions publiques (`mypy --strict`)
- **Docstrings** sur toutes les classes et méthodes publiques (format Google)
- **Dataclasses** pour les modèles de données (NoteEvent, FingeringState, etc.)
- **Pas de `Any`** sauf justification explicite en commentaire
- Longueur de ligne max : **100 caractères** (configuré dans `pyproject.toml`)

### Nommage

```python
# Modules et packages : snake_case
fretwise/scoring/cost_functions.py

# Classes : PascalCase
class GuitarProAdapter:
class ViterbiOptimizer:

# Fonctions et variables : snake_case
def compute_mechanical_cost(state_a: FingeringState, state_b: FingeringState) -> float:

# Constantes : UPPER_SNAKE_CASE
MAX_FRET = 24
STANDARD_TUNING = ["E2", "A2", "D3", "G3", "B3", "E4"]

# Types privés internes : préfixe _
_CostMatrix = np.ndarray
```

### Imports

```python
# Ordre : stdlib → third-party → local (séparés par lignes vides)
import json
from pathlib import Path
from typing import Optional

import numpy as np
import guitarpro

from fretwise.models import NoteEvent, FingeringState
from fretwise.scoring.base import CostFunction
```

### Gestion des erreurs

```python
# Créer des exceptions spécifiques au domaine
class FretwiseError(Exception): ...
class ParseError(FretwiseError): ...
class UnsupportedFormatError(ParseError): ...

# Ne jamais swallower les exceptions silencieusement
# Toujours logger avant de re-raise
```

---

## 🧪 Tests

### Règles

- **Couverture cible : 80%+** (mesuré par `pytest --cov`)
- Chaque module a son fichier `test_<module>.py`
- Les fixtures de fichiers GP sont dans `tests/fixtures/`
- **Tests d'intégration** couvrent le pipeline complet parse → generate → score → optimize

### Commandes

```powershell
# Lancer tous les tests
pytest

# Avec couverture
pytest --cov=fretwise --cov-report=html

# Module spécifique
pytest tests/test_parser.py -v

# Tests marqués
pytest -m "not slow"
```

### Conventions de test

```python
# Nommage : test_<ce_qui_est_testé>_<condition>_<résultat_attendu>
def test_guitarpro_adapter_valid_gp5_returns_note_events():
def test_viterbi_optimizer_empty_sequence_returns_empty():
def test_mechanical_cost_same_position_returns_zero():
```

---

## 🔧 Setup Windows

### Prérequis

```powershell
# Python 3.11+ (vérifier)
python --version

# Git
git --version
```

### Installation du projet

```powershell
# Cloner le repo
git clone <url> fretwise
cd fretwise

# Créer l'environnement virtuel (TOUJOURS dans le projet)
python -m venv .venv

# Activer l'environnement virtuel
.\.venv\Scripts\Activate.ps1

# Installer les dépendances de développement
pip install -e ".[dev]"
```

### Si erreur d'exécution de scripts PowerShell

```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
```

### `pyproject.toml` minimal attendu

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "fretwise"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "PyGuitarPro>=0.10",
    "music21",
    "mido",
    "pretty_midi",
    "numpy",
    "mirdata",
    "click",          # CLI
]

[project.optional-dependencies]
dev = [
    "pytest",
    "pytest-cov",
    "ruff",
    "mypy",
]

[project.scripts]
fretwise = "fretwise.cli:main"

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.mypy]
strict = true
python_version = "3.11"
```

---

## 🌿 Git

### Branches

```
main          ← production stable, tags de version
develop       ← intégration continue
feature/*     ← nouvelles fonctionnalités (ex: feature/m3-chord-patterns)
fix/*         ← corrections de bugs
phase/*       ← branches de phase complète (ex: phase/1-mvp)
```

### Convention de commits (Conventional Commits)

```
<type>(<scope>): <description courte>

[corps optionnel]

[footer optionnel]
```

Types :
- `feat` — nouvelle fonctionnalité
- `fix` — correction de bug
- `test` — ajout/modification de tests
- `refactor` — refactoring sans changement fonctionnel
- `docs` — documentation uniquement
- `chore` — maintenance (deps, CI, config)
- `perf` — amélioration de performance

Scopes : `parser`, `generator`, `patterns`, `scoring`, `optimizer`, `profile`, `cli`, `models`, `ci`

Exemples :
```
feat(parser): add GuitarPro adapter for .gp5 files
test(optimizer): add Viterbi integration test with 5 fixtures
fix(scoring): correct mechanical cost for open strings
chore(deps): upgrade PyGuitarPro to 0.10.2
```

### Workflow

```powershell
# Créer une feature branch
git checkout develop
git pull origin develop
git checkout -b feature/m1-guitarpro-parser

# Committer régulièrement
git add -p                    # ajouter par hunks, pas en bloc
git commit -m "feat(parser): implement NoteEvent extraction from GP beat"

# Avant de merger : rebase propre
git rebase develop
git push origin feature/m1-guitarpro-parser
```

### `.gitignore` essentiel

```gitignore
# Python
__pycache__/
*.py[cod]
*.pyo
.venv/
*.egg-info/
dist/
build/
.mypy_cache/
.ruff_cache/
.pytest_cache/
htmlcov/
.coverage

# Données (ne pas versionner les datasets volumineux)
data/dadagp/
data/guitarset/
data/gaps/

# Profils joueur (données personnelles)
data/profiles/*.json

# Fichiers GP personnels
tests/fixtures/private/

# Windows
Thumbs.db
desktop.ini
```

---

## 🖥️ CLI

Usage cible (Phase 1) :

```powershell
# Parser et afficher les notes d'un fichier
fretwise parse song.gp5

# Calculer les doigtés optimisés
fretwise solve song.gp5

# Avec options
fretwise solve song.gp5 --mode performance --output song_fingered.gp5
fretwise solve song.gp5 --mode learning --output song_fingered.json --verbose

# Calibrer le profil joueur
fretwise calibrate --output data/profiles/mon_profil.json

# Convertir entre formats (court terme — voir roadmap)
fretwise convert song.gp out.musicxml
fretwise convert song.musicxml out.gp --to gp
```

---

## 🚀 Phases de développement

### Phase 1 — MVP ✅ **terminée**

Pipeline complet parse → generate → score → optimize livré, et largement dépassé depuis :
- ✅ Modèles de données (`NoteEvent`, `FingeringState`, `FingeringResult`)
- ✅ Parsers : GuitarPro gp3/4/5 (PyGuitarPro), GP7/8 (GPIF), MusicXML (music21), MIDI (mido)
- ✅ Générateur d'états, scoring mécanique/musical, Viterbi, profil joueur
- ✅ CLI (`parse, solve, finger, info, formats, web, gui`), export GP annoté, PDF/SVG/ASCII tab
- ✅ Suite de tests verte (≥ 1090 tests), couverture large

> Le projet a depuis étendu son périmètre bien au-delà du MVP : moteur de notation/gravure (`core/`), web FastAPI + auth multi-utilisateurs OIDC, stockage cloud pluggable (S3/WebDAV/GDrive), composants ML (ONNX), biomécanique.

---

### 🎯 Plan à court terme — Interopérabilité des formats (priorité actuelle)

**Objectif :** faire de FretWise un convertisseur fiable entre **MusicXML** et **Guitar Pro**, en passant par le modèle canonique interne, avec les doigtés optimisés préservés.

**État de départ :**
- Import : MusicXML ✅, Guitar Pro ✅ (gp3/4/5 + gp7/8), MIDI ✅
- Export : Guitar Pro ⚠️ **partiel** (annotation LeftFingering dans un .gp existant, pas de génération from scratch), MusicXML ❌ **absent**, conversion croisée ❌ **absente**

**Tâches :**
- [x] **Export MusicXML** — `fretwise solve … -o out.musicxml` ([export/musicxml_writer.py](src/fretwise/export/musicxml_writer.py)) : notes, durées, mesures (quantifiées), tablature `<string>`/`<fret>` + doigté `<fingering>` par note (accords compris). S'ouvre dans MuseScore/Finale/Guitar Pro. Round-trip vérifié.
- [ ] **Export Guitar Pro complet** — génération d'un `.gp` from scratch (au-delà de la simple injection de doigtés dans un fichier source)
- [ ] **Conversion GP → MusicXML** et **MusicXML → GP** via le modèle canonique (round-trip)
- [ ] **CLI `convert`** — `fretwise convert in.gp out.musicxml` (+ option `--to {gp,musicxml}` ; doigtés optimisés optionnels)
- [ ] **Tests de round-trip** — invariants préservés (hauteurs, rythme, mesures, accordage, doigtés) sur les fixtures

**Critères de succès :**
- Conversion sans perte des informations communes aux deux formats sur les morceaux de test
- Doigtés (LeftFingering) préservés dans les deux sens
- Round-trip GP → MusicXML → GP stable (pas de dérive de hauteurs/rythme)
- Couverture de tests maintenue ≥ 80%

---

## ⚡ Commandes de référence rapide

```powershell
# Activer l'environnement
.\.venv\Scripts\Activate.ps1

# Lancer les tests
pytest -v

# Lint
ruff check src/ tests/

# Type check
mypy src/fretwise

# Tout en une fois (avant commit)
ruff check src/ tests/ && mypy src/fretwise && pytest --cov=fretwise

# Installer une nouvelle dépendance
pip install <package>
# Puis mettre à jour pyproject.toml manuellement
```

---

## 🚫 Ce qu'il ne faut pas faire

- **Ne jamais modifier l'interface publique de M5 (ViterbiOptimizer)** sans valider l'impact sur tous les modules
- **Ne jamais coder les coefficients α, β, γ, δ en dur** dans le scoring — ils doivent être des paramètres injectables
- **Ne jamais committer** des fichiers `.gp5` personnels ou des profils joueur JSON (données privées)
- **Ne jamais committer** les datasets volumineux (DadaGP, GuitarSet) — utiliser des liens/instructions d'accès
- **Ne pas utiliser `Any`** dans les types sans justification commentée
- **Ne pas merger** sur `main` sans passer par `develop` et les tests CI
- **Ne pas oublier** d'activer le venv avant d'installer des packages

---

## 📌 Contexte métier — rappels clés

- FretWise est analogue à un **moteur d'échecs** : base de patterns (ouvertures) + scoring heuristique (évaluation positionnelle) + Viterbi (recherche arborescente)
- Le **fingering gap** est le défi principal des données : la plupart des tablatures encodent corde+fret mais PAS le doigt. Seul Iino et al. 2025 fournit l'annotation complète (40 études)
- **PyGuitarPro** supporte GP3/4/5 mais PAS GP6/7 (GPX). Conversion via MuseScore si nécessaire
- **Performance cible** : < 100 ms pour ~720 notes (morceau 3 min à 120 BPM). Le goulot d'étranglement est la qualité de la fonction de coût, pas le calcul
- Le module **M5 (Viterbi) est O(N × S²)** : N notes, S états par note (10-30). Pour la polyphonie, décomposer en voix séparées
