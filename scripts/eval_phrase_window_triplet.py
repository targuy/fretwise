"""Rule-only vs phrase_window_v1 triplet on golden_set_v1 (GDS-024 #58 / FW-015 §2).

Answers "does the ML model beat the rules?" by scoring three fingering sources
against the human-validated golden fingers, all under the CANONICAL eval
protocol (GDS-025):

  - ``rule_only``      : FretWise's deterministic pipeline (gamma=0, no ML),
                         with each note pinned to its golden string+fret.
  - ``v1_raw``         : phrase_window_v1 argmax via predict_sequence
                         (sliding window + overlap-averaging).
  - ``v1_pinky_demotion``: v1_raw with the documented pinky->ring fallback
                         (golden_set_v1_raw_vs_pinky_demotion_report.json).

Reports per-note accuracy and pinky false-positive rate for each.

Usage:
    pixi run python scripts/eval_phrase_window_triplet.py

Discipline: golden_set_v1 is ``training_allowed: false`` — eval only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fretwise.generator import StateGenerator
from fretwise.ml import LearnedPhraseWindowFingerer, PhraseNote
from fretwise.models import NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.patterns import PatternMatcher
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS = REPO_ROOT / "data" / "models"
GOLDEN = MODELS / "golden_set_v1.jsonl"

_RING, _PINKY = 3, 4  # indices in [open, index, middle, ring, pinky]


def _phrase_notes(case: dict[str, Any]) -> list[PhraseNote]:
    tuning = case["tuning"]
    return [
        PhraseNote(
            string=e["string_num"] - 1,
            fret=e["fret"],
            pitch=tuning[e["string_num"] - 1] + e["fret"],
            onset=float(e["order"]),
            duration=1.0,
        )
        for e in sorted(case["expected"], key=lambda e: e["order"])
    ]


def _rule_only_fingers(case: dict[str, Any]) -> list[str]:
    """FretWise rule-only fingers, each note pinned to its golden position."""
    tuning = case["tuning"]
    events = [
        NoteEvent(
            pitch=tuning[e["string_num"] - 1] + e["fret"],
            onset=float(e["order"]),
            duration=1.0,
            tempo=120.0,
            string_hint=e["string_num"],
            fret_hint=e["fret"],
            voice_hint=0,
        )
        for e in sorted(case["expected"], key=lambda e: e["order"])
    ]
    cost_fn = CostFunction(weights=CostWeights.reference())  # gamma=0 -> no ML
    optimizer = ViterbiOptimizer(cost_fn)
    results, _ = run_pipeline(events, StateGenerator(), optimizer, PatternMatcher())
    results.sort(key=lambda r: r.note_event.onset)
    return [r.state.finger.value for r in results]


def _demote(
    raw_fingers: list[str],
    probabilities: list[tuple[float, ...]],
    anchors: list[int],
    frets: list[int],
    has_legato: bool,
) -> list[str]:
    """Apply the documented pinky->ring fallback under canonical decoding.

    Rule (golden_set_v1_raw_vs_pinky_demotion_report.json): predict ring when
    raw==pinky, ring is in the top-2 of the averaged softmax, the note sits on
    anchor+2 (ring's natural fret -> win_ring_natural holds), there is no legato
    in the window, ring_prob >= 0.5*pinky_prob, and it is not an open-string
    root at slot 0.
    """
    out = list(raw_fingers)
    for i, (raw, probs, anchor, fret) in enumerate(
        zip(raw_fingers, probabilities, anchors, frets)
    ):
        if raw != "pinky" or has_legato:
            continue
        top2 = sorted(range(5), key=lambda c: probs[c], reverse=True)[:2]
        ring_p, pinky_p = probs[_RING], probs[_PINKY]
        if (
            _RING in top2
            and fret == anchor + 2
            and ring_p >= 0.5 * pinky_p
            and not (i == 0 and fret == 0)
        ):
            out[i] = "ring"
    return out


def _metrics(pred: list[str], truth: list[str]) -> tuple[int, int, int, int]:
    """Return (n_correct, n_total, pinky_false_pos, n_non_pinky_truth)."""
    correct = sum(1 for p, t in zip(pred, truth) if p == t)
    non_pinky = sum(1 for t in truth if t != "pinky")
    pinky_fp = sum(1 for p, t in zip(pred, truth) if p == "pinky" and t != "pinky")
    return correct, len(truth), pinky_fp, non_pinky


def main() -> None:
    if not GOLDEN.exists():
        raise SystemExit(f"Golden set missing: {GOLDEN}")
    model = LearnedPhraseWindowFingerer.from_model_dir(MODELS)

    agg = {
        k: [0, 0, 0, 0] for k in ("rule_only", "v1_raw", "v1_pinky_demotion")
    }  # [correct, total, pinky_fp, non_pinky]

    for line in GOLDEN.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        case = json.loads(line)
        expected = sorted(case["expected"], key=lambda e: e["order"])
        truth = [e["finger"] for e in expected]
        frets = [e["fret"] for e in expected]

        rule = _rule_only_fingers(case)
        preds = model.predict_sequence(_phrase_notes(case))
        v1_raw = [p.finger for p in preds]
        has_legato = "legato" in case["case_id"]
        v1_dem = _demote(
            v1_raw,
            [p.probabilities for p in preds],
            [p.anchor for p in preds],
            frets,
            has_legato,
        )

        for key, pred in (
            ("rule_only", rule), ("v1_raw", v1_raw), ("v1_pinky_demotion", v1_dem),
        ):
            # rule_only may differ in length only if the pipeline dropped a note
            # (shouldn't happen for pinned positions); guard by truncating.
            n = min(len(pred), len(truth))
            c, t, fp, npk = _metrics(pred[:n], truth[:n])
            agg[key][0] += c
            agg[key][1] += t
            agg[key][2] += fp
            agg[key][3] += npk

    print("phrase_window_v1 triplet on golden_set_v1 (canonical protocol, 13 cases)")
    print(f"  {'source':20s} {'per_note_acc':>14s}  {'pinky_FPR':>12s}")
    for key in ("rule_only", "v1_raw", "v1_pinky_demotion"):
        c, t, fp, npk = agg[key]
        acc = c / t if t else 0.0
        fpr = fp / npk if npk else 0.0
        print(f"  {key:20s} {acc:>10.4f} ({c}/{t})  {fpr:>7.4f} ({fp}/{npk})")


if __name__ == "__main__":
    main()
