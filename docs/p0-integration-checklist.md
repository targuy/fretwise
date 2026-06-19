# P0 Integration Checklist

Branch: `refactor/p0-notation-fixes`
Date: 2026-05-04

---

## Baseline pytest state (captured 2026-05-04)

```
1 failed, 794 passed, 7 skipped  (3.02s)

FAILED tests/test_core_scene_svg.py::test_canonical_to_render_scene_tablature_rhythm_anchors_time_signature_on_tab_plane
```

This pre-existing failure is a known P0 issue and is the primary target of the
current refactor branch. The merge of P0 worktrees is expected to bring it to
**0 failures**.

---

## Avant merge de chaque worktree

### Dev P0-B (pitch_to_staff_y)

- [ ] `pitch_to_staff_y()` existe dans `src/fretwise/core/layout/rules.py`
- [ ] La fonction a des type hints corrects (mypy strict)
- [ ] `_measure_event_layouts()` utilise `pitch_to_staff_y` pour le mode standard
- [ ] `pytest tests/test_p0b_pitch_to_staff.py` — tous GREEN
- [ ] `mypy src/fretwise/core/layout/rules.py --ignore-missing-imports` — 0 errors
- [ ] `ruff check src/fretwise/core/layout/rules.py --select E,W,F` — 0 errors
- [ ] Les tests de layout existants passent toujours :
  - [ ] `pytest tests/test_core_layout.py -v --tb=short` — GREEN
  - [ ] `pytest tests/test_core_layout_rules.py -v --tb=short` — GREEN

### Dev P0-C (per-measure time sig)

- [ ] `CompletedScore.measure_time_signatures` existe avec défaut `{}`
- [ ] `gpif_adapter.py` peuple ce dict depuis les MasterBars GPIF
- [ ] `mappers.py` utilise `note.measure_index` pour le groupement
- [ ] `mappers.py` utilise les time sigs per-mesure pour les frontières de mesure
- [ ] `pytest tests/test_p0c_per_measure_timesig.py` — tous GREEN
- [ ] `mypy src/fretwise/core/canonical/mappers.py --ignore-missing-imports` — 0 errors
- [ ] `ruff check src/fretwise/core/canonical/mappers.py src/fretwise/core/ingest/models.py --select E,W,F` — 0 errors
- [ ] Les tests existants de mappers/canonical passent toujours :
  - [ ] `pytest tests/test_core_canonical.py -v --tb=short` — GREEN

### Architecte P0-A (bridge contract)

- [ ] `docs/p0-bridge-contract.md` existe
- [ ] Le document couvre les 3 options de bridge (inline, adapter, protocol)
- [ ] Une recommandation claire est formulée avec justification
- [ ] Les interfaces publiques concernées sont documentées (signatures + types)

---

## Après merge de tous les worktrees

### Suite complète

- [ ] `pytest -q --tb=short` — **0 failures** (régression vs baseline = 0)
- [ ] `ruff check src/ tests/` — 0 errors
- [ ] `mypy src/fretwise --ignore-missing-imports` — 0 errors

### Tests P0 spécifiques

- [ ] `pytest tests/test_p0b_pitch_to_staff.py -v` — tous GREEN
- [ ] `pytest tests/test_p0c_per_measure_timesig.py -v` — tous GREEN
- [ ] `pytest tests/test_core_scene_svg.py -v` — **le test FAILED du baseline est maintenant GREEN**

### Validation fonctionnelle

- [ ] La vue standard de FretWise affiche des notes sur la portée correctement
- [ ] La vue standard d'Aigle Noir n'a plus de silences fantômes à partir de la mesure 77
- [ ] `bash scripts/validate_p0.sh` — exit code 0, résumé ALL CHECKS PASSED

---

## Script de validation rapide

```bash
# Depuis la racine du projet (git-bash Windows ou bash Linux)
bash scripts/validate_p0.sh

# Mode rapide (sans la full suite)
bash scripts/validate_p0.sh --fast
```

---

## Workflow de merge recommandé

```bash
# 1. Rebaser chaque worktree sur la branche principale P0
git checkout refactor/p0-notation-fixes
git merge --no-ff worktree/p0-b-pitch-to-staff   # ou rebase
git merge --no-ff worktree/p0-c-per-measure-timesig

# 2. Valider
bash scripts/validate_p0.sh

# 3. PR vers master uniquement si exit code = 0
gh pr create --base master --title "fix(notation): P0 — pitch_to_staff_y + per-measure time sigs"
```

---

## Contacts / responsabilités

| Worktree | Développeur | Fichiers cibles |
|---|---|---|
| P0-A | Architecte | `docs/p0-bridge-contract.md` |
| P0-B | Dev B | `core/layout/rules.py`, `tests/test_p0b_pitch_to_staff.py` |
| P0-C | Dev C | `core/canonical/mappers.py`, `core/ingest/models.py`, `tests/test_p0c_per_measure_timesig.py` |
