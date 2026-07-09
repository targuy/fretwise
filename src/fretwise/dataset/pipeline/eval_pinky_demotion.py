"""Compare raw v1 predictions vs pinky_demotion fallback on the golden set.

Implements the fallback rule FretWise accepted in Fretwise-015 §5:

    if predicted == pinky
       and ring is top-2
       and candidate_anchor + 2 == fret
       and win_ring_natural_for_anchor_plus_2 == 1
       and no musical/biomechanical reason requires pinky:
        prefer ring

"No musical/biomechanical reason requires pinky" is conservatively interpreted as:
    - the window does NOT contain a hammer_on / pull_off / slide technique
      (legato chains may legitimately want pinky)
    - the window does NOT contain an open string acting as a power-chord root
    - the ring probability is at least 0.5 * pinky probability (close enough to be
      a defensible swap).

Output: golden_set_v1_raw_vs_pinky_demotion_report.json in the handoff dir.
"""

import json

import numpy as np

from fretwise.dataset._mldeps import optional_import
from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR
from fretwise.dataset.features.phrase_window_features import (
    WINDOW_SIZE,
    build_window_feature_vector,
    candidate_anchors,
    feature_names,
)

xgb = optional_import("xgboost")

PHASE4_DIR = PROCESSED_DIR / "phase4"

FINGER_NAMES = ["open", "index", "middle", "ring", "pinky"]
PINKY_IDX = 4
RING_IDX = 3


def load_models():
    models = {}
    for slot in range(WINDOW_SIZE):
        m = xgb.Booster()
        m.load_model(str(PHASE4_DIR / f"xgb_slot{slot}_finger_v1.json"))
        models[f"slot{slot}"] = m
    anchor = xgb.Booster()
    anchor.load_model(str(PHASE4_DIR / "xgb_anchor_head_v1.json"))
    models["anchor"] = anchor
    return models


def predict_window(models, feat_names, f_names, feats_dict):
    x = np.array([[feats_dict[n] for n in feat_names]], dtype=np.float32)
    dm = xgb.DMatrix(x, feature_names=f_names)
    anchor_p = float(models["anchor"].predict(dm)[0])
    slot_probs = []
    for slot in range(WINDOW_SIZE):
        probs = models[f"slot{slot}"].predict(dm)[0]
        slot_probs.append(probs)
    return anchor_p, slot_probs


def apply_pinky_demotion(slot_probs, window_notes, candidate_anchor, feats_dict):
    """Apply the demotion rule slot-by-slot."""
    raw_preds = [int(np.argmax(p)) for p in slot_probs]
    final_preds = list(raw_preds)
    demoted_slots = []

    has_legato_in_window = any(
        any(t in ("hammer_on", "pull_off", "slide") for t in (n.get("techniques") or []))
        for n in window_notes
    )
    win_ring_natural = feats_dict.get("win_ring_natural_for_anchor_plus_2", 0)
    win_contains_open = feats_dict.get("win_contains_open", 0)

    for slot_idx, probs in enumerate(slot_probs):
        if slot_idx >= len(window_notes):
            break
        if raw_preds[slot_idx] != PINKY_IDX:
            continue

        # Is ring in top-2?
        top2 = np.argsort(probs)[-2:][::-1]
        if RING_IDX not in top2:
            continue

        note = window_notes[slot_idx]
        note_fret = note.get("fret", 0)
        if note_fret != candidate_anchor + 2:
            continue

        if not win_ring_natural:
            continue

        if has_legato_in_window:
            continue

        # Conservative: ring prob must be >= 50% of pinky prob
        if probs[RING_IDX] < 0.5 * probs[PINKY_IDX]:
            continue

        # Special case: open-string-root power chord — keep pinky if window has open root
        if win_contains_open and note_fret == candidate_anchor + 2 and slot_idx == 0:
            # likely E5-open style, do nothing
            continue

        final_preds[slot_idx] = RING_IDX
        demoted_slots.append(slot_idx)

    return raw_preds, final_preds, demoted_slots


def fretwise_string_to_internal(s):
    return s - 1


def load_golden_set():
    cases = []
    with open(HANDOFF_DIR / "golden_set_v1.jsonl", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))
    return cases


def select_best_candidate(models, feat_names, f_names, window_notes):
    """Pick best candidate anchor per anchor-head probability."""
    cands = candidate_anchors(window_notes)
    best = None
    for cand in cands:
        feats = build_window_feature_vector(window_notes, cand, WINDOW_SIZE)
        anchor_p, slot_probs = predict_window(models, feat_names, f_names, feats)
        if best is None or anchor_p > best["anchor_p"]:
            best = {
                "cand": cand,
                "anchor_p": anchor_p,
                "slot_probs": slot_probs,
                "feats": feats,
            }
    return best


def main():
    feat_names = feature_names(WINDOW_SIZE)
    f_names = [f"f{i}" for i in range(len(feat_names))]
    models = load_models()
    cases = load_golden_set()

    report_cases = []
    raw_pinky_fp = 0
    raw_pinky_tn = 0
    demoted_pinky_fp = 0
    demoted_pinky_tn = 0
    raw_correct = 0
    demoted_correct = 0
    total_eval = 0
    cases_changed = 0
    cases_legitimate_pinky_preserved = 0
    cases_legitimate_pinky_destroyed = 0

    for case in cases:
        gt_notes = case["expected"]
        if len(gt_notes) < 3:
            report_cases.append({
                "case_id": case["case_id"],
                "status": "skipped (window too short)",
            })
            continue

        window_notes = gt_notes[:WINDOW_SIZE]
        notes_internal = []
        for n in window_notes:
            notes_internal.append({
                "string": fretwise_string_to_internal(n["string_num"]),
                "fret": n["fret"],
                "midi": n.get("pitch", 0),
                "onset": n.get("order", len(notes_internal)) * 1.0,
                "duration": n.get("duration", 1.0),
                "is_chord_member": n.get("is_chord_member", False),
                "techniques": n.get("techniques", []),
            })

        best = select_best_candidate(models, feat_names, f_names, notes_internal)
        raw_preds, demoted_preds, demoted_slots = apply_pinky_demotion(
            best["slot_probs"], notes_internal, best["cand"], best["feats"]
        )

        gt_fingers = [n.get("finger") for n in window_notes[:WINDOW_SIZE]]
        gt_finger_idx = [FINGER_NAMES.index(f) if f in FINGER_NAMES else 0 for f in gt_fingers]

        for slot, (raw, dem, gt) in enumerate(zip(raw_preds, demoted_preds, gt_finger_idx)):
            if slot >= len(window_notes):
                break
            total_eval += 1
            if raw == gt:
                raw_correct += 1
            if dem == gt:
                demoted_correct += 1
            # pinky stats — ground truth NOT pinky
            if gt != PINKY_IDX:
                if raw == PINKY_IDX:
                    raw_pinky_fp += 1
                else:
                    raw_pinky_tn += 1
                if dem == PINKY_IDX:
                    demoted_pinky_fp += 1
                else:
                    demoted_pinky_tn += 1

            # Track legitimate pinky preservation/destruction
            if gt == PINKY_IDX:
                if raw == PINKY_IDX and dem == PINKY_IDX:
                    cases_legitimate_pinky_preserved += 1
                elif raw == PINKY_IDX and dem != PINKY_IDX:
                    cases_legitimate_pinky_destroyed += 1

        if raw_preds != demoted_preds:
            cases_changed += 1

        report_cases.append({
            "case_id": case["case_id"],
            "expected_anchor": next(
                (n.get("anchor") for n in window_notes if n.get("anchor") is not None),
                None,
            ),
            "predicted_anchor": best["cand"],
            "ground_truth_fingers": gt_fingers[:WINDOW_SIZE],
            "raw_predictions": [FINGER_NAMES[p] for p in raw_preds],
            "demoted_predictions": [FINGER_NAMES[p] for p in demoted_preds],
            "demoted_slots": demoted_slots,
            "raw_per_note_accuracy": round(
                sum(1 for r, g in zip(raw_preds[:len(gt_finger_idx)], gt_finger_idx) if r == g)
                / max(len(gt_finger_idx), 1),
                3,
            ),
            "demoted_per_note_accuracy": round(
                sum(1 for d, g in zip(demoted_preds[:len(gt_finger_idx)], gt_finger_idx) if d == g)
                / max(len(gt_finger_idx), 1),
                3,
            ),
        })

    pinky_fpr_raw = raw_pinky_fp / max(raw_pinky_fp + raw_pinky_tn, 1)
    pinky_fpr_demoted = demoted_pinky_fp / max(demoted_pinky_fp + demoted_pinky_tn, 1)

    report = {
        "schema_version": "fretwise-ml-v2",
        "model_name": "phrase_window_fingering_v1",
        "comparison": "raw vs pinky_demotion fallback",
        "fallback_rule": (
            "predict ring when: raw==pinky AND ring in top2 AND fret == anchor+2 "
            "AND win_ring_natural_for_anchor_plus_2 AND no legato in window "
            "AND ring_prob >= 0.5 * pinky_prob AND not (slot0 with open-string root)"
        ),
        "n_cases": len(cases),
        "n_notes_evaluated": total_eval,
        "cases_changed_by_fallback": cases_changed,
        "raw_metrics": {
            "per_note_accuracy": round(raw_correct / max(total_eval, 1), 4),
            "pinky_false_positive_rate": round(pinky_fpr_raw, 4),
        },
        "pinky_demotion_metrics": {
            "per_note_accuracy": round(demoted_correct / max(total_eval, 1), 4),
            "pinky_false_positive_rate": round(pinky_fpr_demoted, 4),
        },
        "pinky_fpr_delta_pp": round((pinky_fpr_raw - pinky_fpr_demoted) * 100, 2),
        "per_note_accuracy_delta_pp": round(
            (demoted_correct - raw_correct) / max(total_eval, 1) * 100, 2
        ),
        "legitimate_pinky_preserved": cases_legitimate_pinky_preserved,
        "legitimate_pinky_destroyed_by_fallback": cases_legitimate_pinky_destroyed,
        "verdict": (
            "GO" if pinky_fpr_demoted <= 0.05 and cases_legitimate_pinky_destroyed == 0
            else "PARTIAL" if pinky_fpr_demoted < pinky_fpr_raw
            else "NO-GO"
        ),
        "cases": report_cases,
    }

    out_path = HANDOFF_DIR / "golden_set_v1_raw_vs_pinky_demotion_report.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2)

    print(f"Report written: {out_path}")
    print(json.dumps({k: v for k, v in report.items() if k != "cases"}, indent=2))


if __name__ == "__main__":
    main()
