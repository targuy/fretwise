"""Export tests/fixtures/golden_set/cases.yaml → cases.jsonl.

One JSON record per golden-set case. Each record contains:
  - case metadata (id, scope, measure, description, annotation_status)
  - source identification (file, sha1 hash, fretwise commit)
  - data_quality verdict (from fretwise.quality.assess_source_quality)
  - the validation rule and its current evaluation result
  - notes in scope, with FretWise's current output (annotator = "fretwise_viterbi")

The format follows GuitarDataSet's accepted schema (sha1 hashes,
techniques-as-list, optional null hand_position, annotator field) with
extensions specific to the golden-set use case (case_id, rule,
rule_result, current_state).

Usage:
    python scripts/export_golden_to_jsonl.py
    # writes tests/fixtures/golden_set/cases.jsonl
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import yaml

from fretwise.generator import StateGenerator
from fretwise.models import Finger
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.quality import assess_source_quality
from fretwise.scoring import CostFunction, CostWeights

REPO_ROOT = Path(__file__).parents[1]
GOLDEN_DIR = REPO_ROOT / "tests" / "fixtures" / "golden_set"
PARTITIONS_DIR = REPO_ROOT / "partitions"
YAML_PATH = GOLDEN_DIR / "cases.yaml"
JSONL_PATH = GOLDEN_DIR / "cases.jsonl"


def _sha1(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return f"sha1:{h.hexdigest()}"


def _git_commit() -> str:
    try:
        out = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=REPO_ROOT, text=True,
        )
        return out.strip()
    except Exception:
        return "unknown"


def _techniques_from_event(e) -> list[str]:
    """Extract a techniques list from a NoteEvent matching the ML schema."""
    techs = []
    art = getattr(e, "articulation", None)
    if art is not None and art.value != "normal":
        techs.append(art.value)
    for flag in ("muted", "palm_muted", "tapping", "accent", "accent_strong",
                 "tremolo_picking", "ghost", "staccato", "slap", "pop",
                 "rasgueado", "golpe", "vibrato_wide", "let_ring"):
        if getattr(e, flag, False):
            techs.append(flag)
    return techs


def _filter_by_scope(results, case: dict) -> list:
    measure = case.get("measure")
    scope = case["rule"].get("scope", "measure" if measure else "whole_piece")
    if scope == "whole_piece":
        return list(results)
    if measure is None:
        return []
    out = []
    for r in results:
        mi = r.note_event.measure_index
        note_measure = mi if mi is not None else int(r.note_event.onset // 4.0) + 1
        if note_measure == measure:
            out.append(r)
    return out


def _evaluate_rule(filtered: list, rule: dict) -> dict:
    if not filtered:
        return {"passed": None, "reason": "no notes in scope"}
    n = len(filtered)
    counts = Counter(r.state.finger.name for r in filtered)
    if rule["type"] == "max_finger_share":
        finger = rule["finger"]
        max_share = float(rule["max_share"])
        actual = counts.get(finger, 0) / n
        return {
            "passed": actual <= max_share,
            "actual_share": round(actual, 4),
            "threshold": max_share,
            "finger": finger,
            "note_count": n,
            "finger_distribution": dict(counts),
        }
    if rule["type"] == "min_finger_share":
        finger = rule["finger"]
        min_share = float(rule["min_share"])
        actual = counts.get(finger, 0) / n
        return {
            "passed": actual >= min_share,
            "actual_share": round(actual, 4),
            "threshold": min_share,
            "finger": finger,
            "note_count": n,
            "finger_distribution": dict(counts),
        }
    return {"passed": None, "reason": f"unsupported rule type {rule['type']!r}"}


def _solve(source_path: Path) -> list:
    adapter = get_adapter(source_path)
    events = adapter.parse(source_path)
    if not events:
        return []
    gen = StateGenerator()
    cost = CostFunction(weights=CostWeights.performance())
    opt = ViterbiOptimizer(cost)
    matcher = PatternMatcher()
    results, _ = run_pipeline(events, gen, opt, pattern_matcher=matcher)
    return results


def _note_record(r) -> dict:
    e = r.note_event
    s = r.state
    return {
        "note_id": r.note_id,
        "onset": round(float(e.onset), 6),
        "duration": round(float(e.duration), 6),
        "pitch": int(e.pitch),
        "string_num": int(s.string_num),
        "fret": int(s.fret),
        "finger": s.finger.value,
        "hand_position": int(s.hand_position),
        "confidence": None,
        "techniques": _techniques_from_event(e),
        "annotator": "fretwise_viterbi",
    }


def export(yaml_path: Path = YAML_PATH, jsonl_path: Path = JSONL_PATH) -> int:
    with yaml_path.open(encoding="utf-8") as f:
        data = yaml.safe_load(f)

    commit = _git_commit()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    written = 0

    with jsonl_path.open("w", encoding="utf-8") as out:
        for case in data["cases"]:
            source_path = PARTITIONS_DIR / case["source"]
            if not source_path.exists():
                record = {
                    "case_id": case["id"],
                    "source_file": case["source"],
                    "source_hash": None,
                    "fretwise_commit": commit,
                    "exported_at": now,
                    "status": "source_missing",
                    "rule": case["rule"],
                    "description": case.get("description", "").strip(),
                    "annotation_status": case.get("annotation_status"),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1
                continue

            results = _solve(source_path)
            filtered = _filter_by_scope(results, case)
            rule_result = _evaluate_rule(filtered, case["rule"])

            adapter = get_adapter(source_path)
            events = adapter.parse(source_path)
            quality = assess_source_quality(events)

            record = {
                "case_id": case["id"],
                "source_file": case["source"],
                "source_hash": _sha1(source_path),
                "fretwise_commit": commit,
                "exported_at": now,
                "dataset_version": data.get("version", "0.1"),
                "scope": case["rule"].get("scope", "measure" if case.get("measure") else "whole_piece"),
                "measure": case.get("measure"),
                "annotation_status": case.get("annotation_status"),
                "description": case.get("description", "").strip(),
                "rule": case["rule"],
                "rule_result": rule_result,
                "current_state": "XPASS" if rule_result.get("passed") else "XFAIL",
                "data_quality": {
                    "verdict": quality.verdict,
                    "rationale": quality.rationale,
                    "note_count": quality.note_count,
                    "pitch_hint_conflicts": quality.pitch_hint_conflicts,
                    "max_chord_span": quality.max_chord_span,
                },
                "notes_in_scope_count": len(filtered),
                "notes": [_note_record(r) for r in filtered],
            }
            out.write(json.dumps(record, ensure_ascii=False) + "\n")
            written += 1

    return written


if __name__ == "__main__":
    n = export()
    print(f"Wrote {n} records to {JSONL_PATH}")
