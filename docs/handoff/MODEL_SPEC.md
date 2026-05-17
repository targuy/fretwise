# FretWise — Spec du modèle pour l'équipe ML

> **Audience** : équipe GuitarDataSet / ML.
> **But** : tout ce qu'il faut savoir pour aligner le format du dataset
> annoté avec ce que FretWise consomme et produit, et pour identifier les
> points où un modèle appris peut s'insérer.

---

## 1. Vue d'ensemble du pipeline

```
[Fichier source] → M1 (Parser) → list[NoteEvent]
                                       │
                                       ▼
                 M2 (Generator) → list[list[FingeringState]]
                                       │
                                       ▼
                 M3 (PatternMatcher) → list[list[FingeringState]] (réordonné)
                                       │
                                       ▼
                 M5 (Viterbi) ── coût C(s_i, s_{i+1}) ──► list[FingeringResult]
                                       │
                                       ▼
                 M4 (Resolvers) → list[FingeringResult] (post-process)
```

- **M1** : `src/fretwise/parser/` — supporte GP3/4/5 (PyGuitarPro), MusicXML
  (music21), MIDI (mido). GP6/7 (.gpx) **non supportés** (conversion via
  MuseScore requise).
- **M2** : `src/fretwise/generator/` — pour chaque NoteEvent, énumère toutes
  les positions physiquement valides. En mode hint (GP), génère 4 doigts
  par fret hinté. En mode libre (MIDI), énumère toutes les cordes.
- **M3** : `src/fretwise/patterns/` — promote en tête de liste les états
  cohérents avec un pattern d'accord/gamme (data YAML
  dans `data/patterns/`).
- **M5** : `src/fretwise/optimizer/` — Viterbi O(N×S²), interface **non
  modifiable**. Le coût est injecté, jamais codé en dur.
- **M4** : `src/fretwise/scoring/` — fonction de coût composite + 12
  resolvers post-process. C'est le point d'insertion principal pour ML.

Voir `CLAUDE.md` et `docs/ROADMAP.md` pour le contexte historique.

---

## 2. Schémas de données — figés pour le handoff

### NoteEvent (`src/fretwise/models.py:52`)

Unité atomique du parser. Toutes les annotations stylistiques s'y trouvent.

| Champ | Type | Source | Note |
|---|---|---|---|
| `pitch` | `int` | toujours | MIDI 0–127 |
| `onset` | `float` | toujours | en beats depuis début |
| `duration` | `float` | toujours | en beats |
| `tempo` | `float` | toujours | BPM local |
| `articulation` | `Articulation` (StrEnum) | défaut NORMAL | 13 valeurs |
| `dynamic` | `Dynamic` (StrEnum) | défaut MF | 6 valeurs |
| `string_hint` | `int \| None` | GP | 1–6 |
| `fret_hint` | `int \| None` | GP | 0–24 |
| `voice_hint` | `int \| None` | GP | voix polyphonique |
| `let_ring` | `bool` | GP | sustain jusqu'à note suivante même corde |
| `bend_value` | `float \| None` | GP | en semitones |
| `bend_type` | `str \| None` | GP | 6 types — cf. `BendType` |
| `slide_type` | `str \| None` | GP | 6 types — cf. `SlideType` |
| `vibrato_wide` | `bool` | GP | |
| `harmonic_type` | `str \| None` | GP | 4 types — cf. `HarmonicType` |
| `harmonic_fret` | `int \| None` | GP | fret overtone naturel |
| `muted`, `palm_muted`, `tapping`, `accent`, `accent_strong`, `tremolo_picking`, `ghost`, `staccato`, `slap`, `pop`, `rasgueado`, `golpe` | `bool` | GP | modifieurs performance |
| `strum_direction` | `str \| None` | GP | `"up"` / `"down"` |
| `note_step`, `note_accidental`, `note_octave` | `str/str/int \| None` | parser | spelling notation |
| `is_tie_dest` | `bool` | parser | continuation de liaison |
| `measure_index` | `int \| None` | parser | mesure 1-based source |
| `tuplet_actual`, `tuplet_normal` | `int \| None` | GP | nuplets |

### FingeringState (`src/fretwise/models.py:166`)

Choix complet pour jouer une note. **Sortie attendue d'un classifieur ML**.

```python
@dataclass
class FingeringState:
    string_num: int       # 1..6 (1 = aigu, 6 = grave)
    fret: int             # 0..24 (0 = open)
    finger: Finger        # OPEN | INDEX | MIDDLE | RING | PINKY
    hand_position: int    # fret où l'index repose (= fret - finger_offset)
```

**Note importante pour ML** : `hand_position` est défini comme « fret de
l'index virtuel ». Pour un état non-INDEX, hp = fret - offset (offset INDEX=0,
MIDDLE=1, RING=2, PINKY=3). C'est un héritage du modèle Viterbi-1. Le module
`segmentation/` introduit un concept plus propre (`Position.anchor`) au
niveau du segment — cf. section 4.

### FingeringResult (`src/fretwise/models.py:187`)

Sortie du pipeline pour une note. Contient le choix final + alternatives.

```python
@dataclass
class FingeringResult:
    note_id: int
    note_event: NoteEvent
    state: FingeringState
    cost: float
    alternatives: list[tuple[FingeringState, float]]  # top-3 trié coût croissant
    planted_fingers: dict[str, tuple[int, int]]       # finger.value → (string, fret)
```

`planted_fingers` est rempli par `resolve_sedentary_fingers` post-Viterbi.
Voir `docs/finger_placement_strategy.md`.

### Position (`src/fretwise/segmentation/__init__.py`)

Nouveau (B v0). Span de notes jouables dans une fenêtre de 4 frets.

```python
@dataclass(frozen=True)
class Position:
    start_idx: int   # index première note du span (inclusive)
    end_idx: int     # index dernière note (inclusive)
    anchor: int      # fret où repose INDEX (= fret le plus bas du span)
```

**Calculé par** : `segment_into_positions(events: list[NoteEvent]) → list[Position]`.

---

## 3. Fonction de coût — point d'intégration principal

```
C(s1, s2) = α·C_méca(s1, s2) + β·C_music(s1, s2) + γ·C_joueur(s1, s2) + δ·C_péda(s1, s2)
```

Pondérations injectables (`CostWeights`), 4 presets exposés :
- `CostWeights.performance()` — (1, 0.5, 2, 0) — défaut concert
- `CostWeights.musical()` — (1, 2, 1, 0) — interprétation
- `CostWeights.learning()` — (1, 0.5, 1, 1.5) — travail technique
- `CostWeights.reference()` — (1, 1, 0, 0) — benchmark

### Composantes mécaniques actives

| Coût | Fichier | Sémantique |
|---|---|---|
| `cost_position_shift` | `scoring/__init__.py:276` | Shift hp pondéré tempo. **A' tolerance=1 appliqué** depuis commit 2480d8e. |
| `cost_stretch` | `scoring/__init__.py:312` | Doigt à un offset != naturel par rapport à hp |
| `cost_string_change` | `scoring/__init__.py:349` | Cordes traversées |
| `cost_finger_difficulty` | `scoring/__init__.py:365` | INDEX=1.0, MID=1.15, RING=1.3, PINKY=1.5 |
| `cost_same_finger_motion` | `scoring/__init__.py:385` | Doigt déjà utilisé déplacé rapidement |
| `cost_sequential_crossing` | `scoring/__init__.py:466` | R-S1 — rang doigt vs sens fret |

### Composantes musicales actives

Documentées et testées (cf. `tests/test_scoring.py`) :
- legato/hammer/pull/slide même corde
- vibrato fret bas / open
- bend corde wound vs plain
- harmonics, tapping, dynamic

### Composantes en stub (à remplacer par ML)

- `C_joueur` : profil joueur (gamma=0 actuellement)
- `C_péda` : objectif pédagogique (delta=0 actuellement)

Ce sont les **deux meilleurs points d'insertion** pour un modèle appris :
remplacer ou augmenter avec un cost prédit par un réseau.

### Resolvers (post-Viterbi)

12 resolvers tournent après Viterbi pour corriger des contraintes
non-locales : `resolve_chord_conflicts`, `resolve_chord_stretch`,
`resolve_chord_finger_ordering`, `resolve_chord_finger_span`,
`resolve_chord_string_diagonal`, `resolve_section_consistency`,
`resolve_chord_partial_barre`, `resolve_chord_unified_hand_position`,
`resolve_pinky_run_to_index`, `resolve_sedentary_fingers`,
`resolve_arpeggio_chord_fingering`, `resolve_finger_continuity`.

Bug connu : **`resolve_chord_partial_barre` crash sur ~1.8 % du corpus**
(IndexError `_FRETTED_FINGERS[off]`). Fix prévu.

---

## 4. Points d'intégration ML — du moins au plus invasif

| # | Approche | Effort | Où ça plug | Risque |
|---|---|---|---|---|
| 1 | Évaluer FretWise vs ground truth | faible | hors prod | nul |
| 2 | Remplacer `C_joueur` par un modèle appris | moyen | `scoring/` (alpha=0, gamma=2 dans performance) | faible — déjà un slot vide |
| 3 | Apprendre `C_méca` directement | fort | `scoring/__init__.py` complet | medium — touche au cœur |
| 4 | Modèle de position end-to-end | très fort | remplace `segmentation/` + scoring | élevé — change l'architecture |
| 5 | Modèle finger-only (étant données string+fret) | moyen | post-generator, pré-Viterbi | faible — string+fret restent fixés |

**Recommandation** : commencer par (1) — évaluation pure FretWise vs
ground truth — pour calibrer baseline et identifier où l'algo échoue.
Puis (2) ou (5) selon volume de données.

---

## 5. Comment exécuter FretWise programmatiquement

```python
from pathlib import Path
from fretwise.parser import get_adapter
from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

def solve(gp_path: Path) -> list:
    adapter = get_adapter(gp_path)
    events = adapter.parse(gp_path)   # list[NoteEvent]
    if not events:
        return []
    gen = StateGenerator()
    cost = CostFunction(weights=CostWeights.performance())
    opt = ViterbiOptimizer(cost)
    matcher = PatternMatcher()
    results, stats = run_pipeline(events, gen, opt, pattern_matcher=matcher)
    return results   # list[FingeringResult]
```

**Setup** : Python 3.11+, `pip install -e ".[dev]"`. Activer le venv.

**Test corpus** : 39 GP files dans `tests/fixtures/` (privé / gitignored) +
~1500 GP files dans `partitions/` (privé / gitignored).

**Audit script de référence** : `scripts/audit_full_corpus_compare.py`
— compare deux tolérances de shift sur le corpus complet.

---

## 6. Versionning et compatibilité

- **Version du modèle** : pas de schema version explicite aujourd'hui.
  L'équipe ML devrait taguer son dataset avec le commit FretWise sur
  lequel il a été aligné. Suggestion : `dataset-v0.1-fretwise@2480d8e`.

- **Évolutions prévues** :
  - B integration ajoutera potentiellement un champ `position_id` à
    `FingeringState` (ou un mapping séparé `note_id → Position`)
  - Le bug `resolve_chord_partial_barre` sera corrigé, devrait débloquer
    ~27 fichiers du corpus partitions/
  - `cost_position_shift` deviendra segment-aware (intra-segment = 0,
    boundary = anchor delta) — change sa sémantique sans changer sa
    signature publique

Toutes ces évolutions sont **annonçables avant exécution** côté ML pour
éviter les écueils de version drift.
