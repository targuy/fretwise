"""Regression tests on known fingering pathologies.

Each test corresponds to a case in ``tests/fixtures/golden_set/cases.yaml``.
The cases describe passages where the current algorithm produces a fingering
a guitarist would never choose, and they assert an aggregate rule (per-measure
or per-piece finger share) that a sane fingering must satisfy.

These tests are tracking tests for the B integration roadmap. They are
declared ``xfail(strict=False)`` so that:
  - they don't fail the CI suite while B is still pending;
  - when B (or any other improvement) makes them pass, pytest reports
    ``XPASS`` and signals progress;
  - if a previously-passing case starts failing again, it's a regression.

If the source corpus (``partitions/``) is not on the machine running the
tests, all cases are skipped.
"""
from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest
import yaml

from fretwise.generator import StateGenerator
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

GOLDEN_DIR = Path(__file__).parent / "fixtures" / "golden_set"
PARTITIONS_DIR = Path(__file__).parents[1] / "partitions"


def _load_cases() -> list[dict]:
    with (GOLDEN_DIR / "cases.yaml").open(encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data["cases"]


def _solve(path: Path) -> list:
    adapter = get_adapter(path)
    events = adapter.parse(path)
    if not events:
        return []
    gen = StateGenerator()
    cost = CostFunction(weights=CostWeights.performance())
    opt = ViterbiOptimizer(cost)
    matcher = PatternMatcher()
    results, _ = run_pipeline(events, gen, opt, pattern_matcher=matcher)
    return results


def _filter_by_measure(results: list, measure: int, beats_per_measure: float = 4.0) -> list:
    """Keep only notes belonging to a 1-based measure index.

    Uses ``measure_index`` from the NoteEvent when populated; falls back to
    onset // beats_per_measure when not.
    """
    out = []
    for r in results:
        mi = r.note_event.measure_index
        if mi is not None:
            note_measure = mi
        else:
            note_measure = int(r.note_event.onset // beats_per_measure) + 1
        if note_measure == measure:
            out.append(r)
    return out


def _finger_share(results: list, finger_name: str) -> float:
    if not results:
        return 0.0
    counter = Counter(r.state.finger.name for r in results)
    return counter.get(finger_name, 0) / len(results)


_CASES = _load_cases()


@pytest.mark.xfail(
    strict=False,
    reason="Pathology tracked by the B roadmap — see plan in ~/.claude/plans/.",
)
@pytest.mark.parametrize("case", _CASES, ids=lambda c: c["id"])
def test_golden_pathology(case: dict) -> None:
    source_path = PARTITIONS_DIR / case["source"]
    if not source_path.exists():
        pytest.skip(f"Source corpus not available: {source_path}")

    results = _solve(source_path)
    if not results:
        pytest.skip(f"Pipeline produced no results for {source_path.name}")

    measure = case.get("measure")
    scope = case["rule"].get("scope", "measure" if measure else "whole_piece")

    if scope == "measure":
        if measure is None:
            pytest.fail(f"Case {case['id']} has scope=measure but no measure field")
        filtered = _filter_by_measure(results, measure)
        if not filtered:
            pytest.skip(f"No notes found in measure {measure} of {source_path.name}")
    else:
        filtered = results

    rule = case["rule"]
    rule_type = rule["type"]

    if rule_type == "max_finger_share":
        finger = rule["finger"]
        max_share = float(rule["max_share"])
        actual = _finger_share(filtered, finger)
        assert actual <= max_share, (
            f"{case['id']}: {finger} share is {actual:.1%}, "
            f"max allowed {max_share:.1%} ({len(filtered)} notes)"
        )
    elif rule_type == "min_finger_share":
        finger = rule["finger"]
        min_share = float(rule["min_share"])
        actual = _finger_share(filtered, finger)
        assert actual >= min_share, (
            f"{case['id']}: {finger} share is {actual:.1%}, "
            f"min required {min_share:.1%} ({len(filtered)} notes)"
        )
    else:
        pytest.skip(f"Rule type {rule_type!r} not implemented yet")
