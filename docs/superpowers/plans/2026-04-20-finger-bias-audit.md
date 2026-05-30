# Finger Bias Audit — Plan d'analyse

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mesurer et caractériser le biais RING/PINKY dans l'algorithme de placement de main — quantifier dans quelle proportion les mesures sont jouées majoritairement avec annulaire et auriculaire alors qu'un guitariste humain utiliserait index et majeur.

**Architecture:** Trois scripts d'audit indépendants : (1) statistiques globales de distribution des doigts par corpus, (2) détection des mesures "annulaire/auriculaire dominantes", (3) simulation du coût de transition pour démontrer la mécanique du biais sur des exemples synthétiques.

**Tech Stack:** Python, pytest pour les tests unitaires, corpus `tests/fixtures/` (36 fichiers GP)

---

## Contexte et hypothèse

Le générateur d'états (`StateGenerator._states_for_position`) crée pour chaque note `(string, fret=F)` exactement 4 états :

```
INDEX  → hand_position = F
MIDDLE → hand_position = F - 1
RING   → hand_position = F - 2
PINKY  → hand_position = F - 3
```

La fonction de coût favorise l'état avec le **shift de main le plus bas** :
- `cost_position_shift = |Δhp| × tempo_factor` (très élevé pour notes rapides)
- `cost_finger_difficulty` : INDEX=1.0, MIDDLE=1.15, RING=1.3, PINKY=1.5 (faible)

Résultat : pour une transition fret 5 → fret 7 (quarter note, 120 BPM) :
- INDEX@7 coûte : shift=2 × tf=2.0 + diff=1.0 = **5.0**
- RING@7 coûte  : shift=0 × tf=2.0 + diff=1.3 = **1.3** ← gagnant

**L'algorithme verrouille la main** et monte avec RING/PINKY plutôt que de décaler l'index.

---

## Fichiers concernés (lecture seule — pas de modification)

| Fichier | Rôle |
|---|---|
| `src/fretwise/scoring/__init__.py` | Fonctions de coût à analyser |
| `src/fretwise/generator/__init__.py` | Génération des états |
| `src/fretwise/pipeline.py` | Orchestration pipeline → résultats |
| `tests/fixtures/*.gp` | Corpus de 36 morceaux |

Fichiers **créés** par ce plan :
| Fichier | Rôle |
|---|---|
| `scripts/audit_finger_distribution.py` | Stats globales doigts par corpus |
| `scripts/audit_ring_pinky_measures.py` | Mesures dominées par RING/PINKY |
| `tests/test_finger_bias.py` | Tests unitaires sur la mécanique du biais |

---

### Task 1 : Vérifier la mécanique du biais — tests unitaires

**But** : Prouver analytiquement, sur des cas synthétiques, que l'algorithme préfère RING/PINKY à l'INDEX pour les intervalles ascendants courts.

**Files:**
- Create: `tests/test_finger_bias.py`

- [ ] **Step 1: Écrire le test "RING bat INDEX pour un intervalle montant de 2 frets"**

```python
"""Tests unitaires démontrant le biais RING/PINKY de la fonction de coût."""
from __future__ import annotations

import pytest
from fretwise.models import Articulation, Dynamic, Finger, FingeringState, NoteEvent
from fretwise.scoring import CostWeights, RulePreferences, compute_mechanical_cost


def _note(duration: float = 1.0, tempo: float = 120.0) -> NoteEvent:
    return NoteEvent(
        pitch=64, onset=0.0, duration=duration, tempo=tempo,
        articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
    )


def _state(fret: int, finger: Finger) -> FingeringState:
    offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    return FingeringState(
        string_num=1, fret=fret, finger=finger,
        hand_position=fret - offsets[finger],
    )


def test_ring_cheaper_than_index_ascending_2fret_at_120bpm() -> None:
    """Fret 5 (INDEX) → fret 7: RING coûte moins que INDEX malgré sa difficulté plus élevée."""
    s1 = _state(5, Finger.INDEX)  # hp=5
    s2_ring  = _state(7, Finger.RING)   # hp=5, shift=0
    s2_index = _state(7, Finger.INDEX)  # hp=7, shift=2
    note = _note(duration=1.0, tempo=120.0)  # quarter note, tf=2.0

    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note)
    cost_index = compute_mechanical_cost(s1, s2_index, note)
    assert cost_ring < cost_index, (
        f"RING ({cost_ring:.3f}) should be cheaper than INDEX ({cost_index:.3f}) "
        f"for an ascending 2-fret interval at 120 BPM"
    )
```

- [ ] **Step 2: Lancer le test pour confirmer qu'il passe**

```bash
pytest tests/test_finger_bias.py::test_ring_cheaper_than_index_ascending_2fret_at_120bpm -v
```
Attendu : `PASSED`

- [ ] **Step 3: Écrire le test "le biais disparaît pour les notes très lentes"**

```python
def test_index_wins_for_very_slow_notes() -> None:
    """À très basse vitesse (whole note à 30 BPM), shift peu coûteux → INDEX préféré."""
    s1 = _state(5, Finger.INDEX)   # hp=5
    s2_ring  = _state(7, Finger.RING)   # hp=5, shift=0
    s2_index = _state(7, Finger.INDEX)  # hp=7, shift=2
    note = _note(duration=4.0, tempo=30.0)  # whole note, tf très faible

    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note)
    cost_index = compute_mechanical_cost(s1, s2_index, note)
    # Ici tf = 1/max(8.0, 0.1) = 0.125 → shift cost INDEX = 2×0.125=0.25, diff=1.0 → 1.25
    # RING: shift=0, diff=1.3 → 1.3 > 1.25 → INDEX gagne
    assert cost_index < cost_ring, (
        f"INDEX ({cost_index:.3f}) should be cheaper than RING ({cost_ring:.3f}) "
        f"for very slow notes (4 beats at 30 BPM)"
    )
```

- [ ] **Step 4: Écrire le test "seuil de bascule INDEX↔RING"**

```python
def test_bias_breakeven_duration() -> None:
    """Calculer la durée à partir de laquelle INDEX redevient moins coûteux que RING
    pour un intervalle montant de 2 frets à 120 BPM.

    RING cost   = 0 + 1.3 = 1.3  (constant)
    INDEX cost  = 2 * tf + 1.0   où tf = 1 / max(duration * 60/120, 0.1)
                                       = 1 / max(duration/2, 0.1)
    INDEX < RING quand : 2*tf + 1.0 < 1.3
                         2*tf < 0.3
                         tf < 0.15
                         1/max(d/2, 0.1) < 0.15
                         max(d/2, 0.1) > 6.67
                         d > 13.33 beats (impossible en pratique musicale)
    """
    s1 = _state(5, Finger.INDEX)
    s2_ring  = _state(7, Finger.RING)
    s2_index = _state(7, Finger.INDEX)

    # A 120 BPM, la durée seuil théorique est > 13 beats
    # On vérifie qu'à 10 beats (durée extrême), RING gagne encore
    note_10b = _note(duration=10.0, tempo=120.0)
    cost_ring_10b  = compute_mechanical_cost(s1, s2_ring,  note_10b)
    cost_index_10b = compute_mechanical_cost(s1, s2_index, note_10b)
    assert cost_ring < cost_index_10b or abs(cost_ring - cost_index_10b) < 0.5, (
        "Even at 10 beats, RING should be cheaper or very close to INDEX"
    )

    # A 14 beats, INDEX doit gagner
    note_14b = _note(duration=14.0, tempo=120.0)
    cost_ring_14b  = compute_mechanical_cost(s1, s2_ring,  note_14b)
    cost_index_14b = compute_mechanical_cost(s1, s2_index, note_14b)
    assert cost_index_14b < cost_ring_14b, (
        f"At 14 beats, INDEX ({cost_index_14b:.3f}) should beat RING ({cost_ring_14b:.3f})"
    )
```

- [ ] **Step 5: Écrire le test "asymétrie ascendant vs descendant"**

```python
def test_ascending_favors_ring_descending_favors_index() -> None:
    """Le biais est asymétrique : il favorise RING en montée, INDEX en descente."""
    note = _note(duration=1.0, tempo=120.0)

    # MONTÉE : fret 5 → fret 7
    s1_low = _state(5, Finger.INDEX)  # hp=5
    c_ring_up  = compute_mechanical_cost(s1_low, _state(7, Finger.RING),  note)
    c_index_up = compute_mechanical_cost(s1_low, _state(7, Finger.INDEX), note)
    assert c_ring_up < c_index_up, "Ascending: RING should be preferred"

    # DESCENTE : depuis hp=7 (INDEX@7) vers fret 5
    s1_high = _state(7, Finger.INDEX)  # hp=7
    c_ring_down  = compute_mechanical_cost(s1_high, _state(5, Finger.RING),  note)
    c_index_down = compute_mechanical_cost(s1_high, _state(5, Finger.INDEX), note)
    assert c_index_down < c_ring_down, "Descending: INDEX should be preferred"
```

- [ ] **Step 6: Lancer tous les tests**

```bash
pytest tests/test_finger_bias.py -v
```
Attendu : 4 tests PASSED

- [ ] **Step 7: Commit**

```bash
git add tests/test_finger_bias.py
git commit -m "test(scoring): démontrer le biais RING/PINKY analytiquement"
```

---

### Task 2 : Audit de distribution des doigts sur le corpus

**But** : Mesurer la distribution INDEX/MIDDLE/RING/PINKY/OPEN sur l'ensemble du corpus, et la comparer à une distribution "naturelle" humaine.

**Files:**
- Create: `scripts/audit_finger_distribution.py`

- [ ] **Step 1: Créer le script**

```python
#!/usr/bin/env python3
"""Audit de la distribution des doigts sur l'ensemble du corpus GP.

Usage: python scripts/audit_finger_distribution.py
Sortie: tableau de distribution par fichier + total corpus.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.generator import StateGenerator
from fretwise.models import Finger
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"
CORPUS_TOTAL: Counter[str] = Counter()
CORPUS_NOTES = 0


def audit_file(path: Path) -> None:
    global CORPUS_NOTES
    try:
        adapter = get_adapter(path)
        events = adapter.parse(path)
    except Exception as exc:
        print(f"  SKIP {path.name}: {exc}")
        return

    if not events:
        return

    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(events, generator, optimizer, pattern_matcher=matcher)

    counter: Counter[str] = Counter()
    for r in results:
        finger_name = str(r.state.finger).replace("Finger.", "")
        counter[finger_name] += 1

    total = sum(counter.values())
    CORPUS_NOTES += total
    for k, v in counter.items():
        CORPUS_TOTAL[k] += v

    print(f"\n{path.stem}")
    print(f"  Total notes : {total}")
    for finger in ["OPEN", "INDEX", "MIDDLE", "RING", "PINKY"]:
        count = counter.get(finger, 0)
        pct = 100 * count / total if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {finger:<8} {count:5d}  {pct:5.1f}%  {bar}")

    ring_pinky = counter.get("RING", 0) + counter.get("PINKY", 0)
    idx_mid    = counter.get("INDEX", 0) + counter.get("MIDDLE", 0)
    rp_pct = 100 * ring_pinky / total if total else 0
    im_pct = 100 * idx_mid / total if total else 0
    print(f"  → INDEX+MIDDLE: {im_pct:.1f}%   RING+PINKY: {rp_pct:.1f}%")


def main() -> None:
    files = sorted(FIXTURES.glob("*.gp*"))
    if not files:
        print(f"No GP files found in {FIXTURES}")
        return

    print(f"Corpus: {len(files)} fichiers\n{'=' * 60}")
    for f in files:
        audit_file(f)

    print(f"\n{'=' * 60}")
    print(f"TOTAL CORPUS ({CORPUS_NOTES} notes)")
    total = sum(CORPUS_TOTAL.values())
    for finger in ["OPEN", "INDEX", "MIDDLE", "RING", "PINKY"]:
        count = CORPUS_TOTAL.get(finger, 0)
        pct = 100 * count / total if total else 0
        bar = "█" * int(pct / 2)
        print(f"  {finger:<8} {count:6d}  {pct:5.1f}%  {bar}")

    ring_pinky = CORPUS_TOTAL.get("RING", 0) + CORPUS_TOTAL.get("PINKY", 0)
    idx_mid    = CORPUS_TOTAL.get("INDEX", 0) + CORPUS_TOTAL.get("MIDDLE", 0)
    print(f"\n  INDEX+MIDDLE : {100 * idx_mid  / total:.1f}%")
    print(f"  RING+PINKY   : {100 * ring_pinky / total:.1f}%")
    print(f"\n  Ratio RP/IM  : {ring_pinky / max(idx_mid, 1):.3f}  (humain attendu: ~0.5-0.7)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lancer l'audit**

```bash
python scripts/audit_finger_distribution.py 2>&1 | tee docs/benchmarks/finger_distribution_audit.txt
```

Attendu (hypothèse à valider) : RING+PINKY > 35% (potentiellement 40-50% ce qui serait sur-représenté par rapport à un guitariste humain dont l'annulaire et l'auriculaire représentent généralement ~25-35% des notes dans un morceau standard).

- [ ] **Step 3: Commit**

```bash
git add scripts/audit_finger_distribution.py
git commit -m "chore(audit): script de distribution des doigts sur corpus"
```

---

### Task 3 : Détecter les mesures "RING/PINKY dominantes"

**But** : Identifier les mesures où ≥ 60% des notes sont jouées avec RING ou PINKY, et les annoter pour vérification manuelle.

**Files:**
- Create: `scripts/audit_ring_pinky_measures.py`

- [ ] **Step 1: Créer le script**

```python
#!/usr/bin/env python3
"""Détecte les mesures où RING+PINKY > seuil et les compare à une estimation humaine.

Usage: python scripts/audit_ring_pinky_measures.py [--threshold 0.6]
Seuil par défaut : 60% des notes dans la mesure jouées avec RING ou PINKY.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

from fretwise.generator import StateGenerator
from fretwise.models import Finger
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

FIXTURES = Path(__file__).parents[1] / "tests" / "fixtures"

_RP = {Finger.RING, Finger.PINKY}
# Normalise "Finger.RING" → Finger.RING
_FINGER_MAP = {str(f): f for f in Finger}
_FINGER_MAP.update({f.name: f for f in Finger})


def _parse_finger(raw: str) -> Finger:
    # raw may be "Finger.RING" or "RING"
    key = raw.split(".")[-1].upper()
    return Finger[key]


def audit_file(path: Path, threshold: float) -> list[dict]:
    try:
        adapter = get_adapter(path)
        events = adapter.parse(path)
    except Exception as exc:
        print(f"  SKIP {path.name}: {exc}")
        return []

    if not events:
        return []

    beats_pm = float(getattr(adapter, "beats_per_measure", 4.0))
    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(events, generator, optimizer, pattern_matcher=matcher)

    # Group by measure
    by_measure: dict[int, list] = defaultdict(list)
    for r in results:
        m_idx = int(r.note_event.onset // beats_pm)
        by_measure[m_idx].append(r)

    flagged = []
    for m_idx in sorted(by_measure):
        notes = by_measure[m_idx]
        total = len(notes)
        if total == 0:
            continue
        rp_count = sum(
            1 for r in notes
            if _parse_finger(str(r.state.finger)) in _RP
        )
        rp_pct = rp_count / total
        if rp_pct >= threshold:
            frets = [r.state.fret for r in notes]
            fingers = [str(r.state.finger).replace("Finger.", "") for r in notes]
            flagged.append({
                "measure": m_idx + 1,
                "total_notes": total,
                "rp_pct": rp_pct,
                "frets": frets,
                "fingers": fingers,
            })

    return flagged


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.6,
                        help="Fraction de RING/PINKY pour signaler une mesure (défaut: 0.6)")
    args = parser.parse_args()

    files = sorted(FIXTURES.glob("*.gp*"))
    total_flagged = 0
    total_measures = 0

    for path in files:
        flagged = audit_file(path, args.threshold)
        if flagged:
            print(f"\n{path.stem}  ({len(flagged)} mesure(s) > {args.threshold*100:.0f}% RP)")
            for m in flagged[:10]:  # max 10 par fichier pour la lisibilité
                print(
                    f"  Mesure {m['measure']:3d} : "
                    f"{m['rp_pct']*100:.0f}% RP "
                    f"({m['total_notes']} notes) "
                    f"frets={m['frets']} "
                    f"fingers={m['fingers']}"
                )
            total_flagged += len(flagged)

    print(f"\n{'=' * 60}")
    print(f"Mesures > {args.threshold*100:.0f}% RING/PINKY : {total_flagged}")
    print("(Vérifier manuellement si un guitariste humain utiliserait INDEX/MIDDLE)")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Lancer avec seuil 60%**

```bash
python scripts/audit_ring_pinky_measures.py --threshold 0.6 2>&1 | tee docs/benchmarks/ring_pinky_measures_60pct.txt
```

- [ ] **Step 3: Lancer avec seuil 80% (cas les plus extrêmes)**

```bash
python scripts/audit_ring_pinky_measures.py --threshold 0.8 2>&1 | tee docs/benchmarks/ring_pinky_measures_80pct.txt
```

- [ ] **Step 4: Commit**

```bash
git add scripts/audit_ring_pinky_measures.py
git commit -m "chore(audit): détection mesures RING/PINKY dominantes"
```

---

### Task 4 : Test unitaire — simuler un run ascendant 4 notes et vérifier les doigts attribués

**But** : Montrer concrètement sur un cas simple (4 notes, montée par demi-tons) quelle séquence de doigts l'algorithme produit vs ce qu'un humain ferait.

**Files:**
- Modify: `tests/test_finger_bias.py`

- [ ] **Step 1: Ajouter le test sur un run ascendant**

```python
from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline


def _make_run(start_fret: int, length: int, duration: float = 0.5, tempo: float = 120.0) -> list[NoteEvent]:
    """Crée une séquence de notes ascendantes sur la corde 1, demi-tons successifs."""
    open_pitch_s1 = 64  # corde 1 ouverte = E4 = MIDI 64
    notes = []
    for i in range(length):
        notes.append(NoteEvent(
            pitch=open_pitch_s1 + start_fret + i,
            onset=i * duration,
            duration=duration,
            tempo=tempo,
            articulation=Articulation.NORMAL,
            dynamic=Dynamic.MF,
            string_hint=1,
            fret_hint=start_fret + i,
        ))
    return notes


def test_ascending_run_frets_5_to_8_finger_sequence() -> None:
    """Run ascendant frets 5-6-7-8 : que donne l'algorithme ?

    Un guitariste humain typique jouerait souvent :
      Option A (position fixe) : INDEX@5, MIDDLE@6, RING@7, PINKY@8  ← correct
      Option B (shifts) :        INDEX@5, INDEX@6, MIDDLE@7, INDEX@8  ← possible aussi

    L'algorithme doit produire Option A (position fixe, aucun shift).
    C'est le comportement CORRECT. Ce test documente le comportement actuel.
    """
    notes = _make_run(start_fret=5, length=4, duration=0.5, tempo=120.0)
    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(notes, generator, optimizer, pattern_matcher=matcher)

    fingers = [str(r.state.finger).replace("Finger.", "") for r in results]
    hand_positions = [r.state.hand_position for r in results]

    print(f"\nRun 5→8: fingers={fingers}, hand_positions={hand_positions}")
    # Documenter le comportement actuel (pas d'assertion stricte — c'est une étude)
    # Un comportement sain serait : main stable, un doigt différent par fret
    unique_hp = set(hand_positions)
    assert len(results) == 4


def test_ascending_run_frets_5_to_10_finger_sequence() -> None:
    """Run ascendant 6 notes frets 5-10 : dépasse la portée d'une seule position.

    Un guitariste humain ferait un SHIFT quelque part dans la montée.
    Question : l'algorithme fait-il le shift, ou reste-t-il bloqué en PINKY ?

    Comportement pathologique : tout jouer à hp=5 → fret 8 avec RING, fret 9 avec PINKY
    mais fret 10 est impossible sans shift (PINKY@10 → hp=7, change la main).
    """
    notes = _make_run(start_fret=5, length=6, duration=0.5, tempo=120.0)
    generator = StateGenerator()
    cost_fn   = CostFunction(weights=CostWeights.performance())
    optimizer = ViterbiOptimizer(cost_fn)
    matcher   = PatternMatcher()
    results, _ = run_pipeline(notes, generator, optimizer, pattern_matcher=matcher)

    fingers = [str(r.state.finger).replace("Finger.", "") for r in results]
    hand_positions = [r.state.hand_position for r in results]
    frets = [r.state.fret for r in results]

    print(f"\nRun 5→10 (6 notes):")
    for i, r in enumerate(results):
        f = str(r.state.finger).replace("Finger.", "")
        print(f"  fret={r.state.fret}  finger={f}  hp={r.state.hand_position}")

    hp_shifts = sum(1 for i in range(1, len(hand_positions)) if hand_positions[i] != hand_positions[i-1])
    print(f"  Nombre de shifts de main : {hp_shifts}")
    assert len(results) == 6  # documenter, pas d'assertion métier stricte
```

- [ ] **Step 2: Lancer les tests**

```bash
pytest tests/test_finger_bias.py -v -s 2>&1 | grep -E "PASSED|FAILED|Run|fret=|shifts"
```

- [ ] **Step 3: Commit**

```bash
git add tests/test_finger_bias.py
git commit -m "test(scoring): documenter le comportement sur runs ascendants"
```

---

### Task 5 : Synthèse et interprétation des résultats

Cette tâche est **manuelle** — elle consiste à lire les sorties des scripts et à répondre aux questions suivantes :

- [ ] **Step 1 : Lire `docs/benchmarks/finger_distribution_audit.txt`**

Répondre à :
1. Quel est le ratio RING+PINKY / INDEX+MIDDLE sur le corpus total ?
2. Y a-t-il des morceaux avec un ratio particulièrement élevé ?
3. Est-ce cohérent avec l'analyse théorique ?

Valeurs de référence attendues (à vérifier avec de la littérature ou des enregistrements vidéo) :
- Guitariste classique avancé : INDEX ~30%, MIDDLE ~25%, RING ~25%, PINKY ~15%
- Guitariste rock/blues (technique barré) : INDEX ~35%, MIDDLE ~20%, RING ~25%, PINKY ~10%

- [ ] **Step 2 : Lire `docs/benchmarks/ring_pinky_measures_60pct.txt`**

Identifier les cas les plus suspects : mesures avec ≥ 80% RING/PINKY sur des phrases mélodiques scalaires (pas des accords ou des barré). Ce sont les cas pathologiques.

- [ ] **Step 3 : Décider des axes d'amélioration potentiels**

Trois hypothèses à évaluer selon les résultats :

**Hypothèse A — Le biais est statistiquement significatif**
→ Envisager une pénalité sur l'utilisation excessive de RING/PINKY dans les runs scalaires.
→ Ou introduire un coût asymétrique `cost_position_shift` qui pénalise moins les petits shifts (1 fret).

**Hypothèse B — Le comportement actuel est correct pour la technique "4 frets / 4 doigts"**
→ Valider que les runs ascendants produits sont réellement jouables.
→ Le "biais" perçu est en fait la technique classique correcte.

**Hypothèse C — Le biais est réel mais seulement pour certains tempos**
→ Cartographier le seuil de bascule par fichier.
→ Envisager un ajustement du `tempo_factor` dans `cost_position_shift`.

- [ ] **Step 4 : Écrire un résumé dans `docs/core_notation_gap_audit.md` ou fichier dédié**

Titre : `## Finger Bias Analysis (2026-04-20)`

Sections :
- Mécanisme analytique (avec les chiffres)
- Résultats corpus (ratios mesurés)
- Cas pathologiques identifiés
- Recommandation : corriger ou accepter

---

## Références pour l'interprétation

| Source de vérité | Localisation |
|---|---|
| Fonction de coût mécanique | `src/fretwise/scoring/__init__.py:265-472` |
| Génération des états | `src/fretwise/generator/__init__.py:139-171` |
| Constantes `_FINGER_BASE_COST` | `src/fretwise/scoring/__init__.py:41-47` |
| Constante `_SEQUENTIAL_CROSS_PENALTY = 2.0` | `src/fretwise/scoring/__init__.py:368` |
| Corpus GP | `tests/fixtures/*.gp*` |
