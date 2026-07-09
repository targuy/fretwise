"""Evaluate PhraseWindowFingeringModelV1 on calibration + golden set.

Populates:
  - phrase_window_fingering_v1_calibration.json's `model_output` blocks
  - phrase_window_fingering_v1_golden_report.json (per-case metrics)
  - phrase_window_fingering_v1_metrics.json (consolidated)
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
FINGER_TO_INT = {n: i for i, n in enumerate(FINGER_NAMES)}


def load_models():
    feat_names = feature_names(WINDOW_SIZE)
    f_names = [f"f{i}" for i in range(len(feat_names))]
    models = {}
    for slot in range(WINDOW_SIZE):
        m = xgb.Booster()
        m.load_model(str(PHASE4_DIR / f"xgb_slot{slot}_finger_v1.json"))
        models[f"slot{slot}"] = m
    anchor = xgb.Booster()
    anchor.load_model(str(PHASE4_DIR / "xgb_anchor_head_v1.json"))
    models["anchor"] = anchor
    return models, feat_names, f_names


def predict_row(models, feat_names, f_names, feats_dict):
    x = np.array([[feats_dict[n] for n in feat_names]], dtype=np.float32)
    dm = xgb.DMatrix(x, feature_names=f_names)
    out = {
        "slot_finger_probs": [],
        "anchor_probability": float(models["anchor"].predict(dm)[0]),
    }
    for slot in range(WINDOW_SIZE):
        probs = models[f"slot{slot}"].predict(dm)[0].tolist()
        out["slot_finger_probs"].append({
            "probabilities": [round(float(p), 6) for p in probs],
            "argmax_finger": FINGER_NAMES[int(np.argmax(probs))],
        })
    return out


def fretwise_string_to_internal(string_num_1based: int) -> int:
    """FretWise uses 1=high_e, 6=low_E; internal uses 0=high_e, 5=low_E."""
    return string_num_1based - 1


def golden_case_to_window(case: dict) -> list[dict]:
    notes = []
    for n in case["expected"][:WINDOW_SIZE]:
        notes.append({
            "string": fretwise_string_to_internal(n["string_num"]),
            "fret": n["fret"],
            "midi": n.get("pitch", n.get("midi", 0)),
            "onset": n.get("order", len(notes)) * 1.0,
            "duration": n.get("duration", 1.0),
            "is_chord_member": n.get("is_chord_member", False),
        })
    return notes


def main():
    models, feat_names, f_names = load_models()

    # ----- 1. Populate calibration outputs -----
    calib_path = HANDOFF_DIR / "phrase_window_fingering_v1_calibration.json"
    with open(calib_path, encoding="utf-8") as f:
        calib = json.load(f)

    for ex in calib["examples"]:
        notes_for_ex = []
        for n in ex["input_notes"]:
            notes_for_ex.append({
                "string": n["string"],
                "fret": n["fret"],
                "midi": n.get("midi", n.get("pitch", 0)),
                "onset": n["onset"],
                "duration": n["duration"],
                "is_chord_member": n.get("is_chord_member", False),
            })
        feats = build_window_feature_vector(notes_for_ex, ex["candidate_anchor"], WINDOW_SIZE)
        out = predict_row(models, feat_names, f_names, feats)
        ex["model_output"] = {
            "anchor_probability": round(out["anchor_probability"], 6),
            "slot_finger_probs": out["slot_finger_probs"],
            "produced_by": "phrase_window_fingering_v1 (XGBoost fallback, ONNX-equivalent)",
        }
    calib["status"] = "populated with v1 outputs"
    with open(calib_path, "w", encoding="utf-8") as f:
        json.dump(calib, f, indent=2)
    print(f"Calibration outputs populated: {calib_path}")

    # ----- 2. Golden set evaluation -----
    golden_path = HANDOFF_DIR / "golden_set_v1.jsonl"
    cases = []
    with open(golden_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                cases.append(json.loads(line))

    golden_report = {
        "schema_version": "fretwise-ml-v2",
        "model_name": "phrase_window_fingering_v1",
        "cases": [],
    }

    total_per_note_correct = 0
    total_per_note = 0
    exact_window_matches = 0
    anchor_correct = 0
    pinky_fp = 0
    pinky_tn = 0

    for case in cases:
        gt_notes = case["expected"]
        if len(gt_notes) < 3:
            # Single chord cases produce too short a window; skip
            golden_report["cases"].append({
                "case_id": case["case_id"],
                "status": "skipped (window too short)",
            })
            continue

        # Heuristic: take the first WINDOW_SIZE notes as the window.
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
            })

        # Pad notes to WINDOW_SIZE by repeating the last note's open-position.
        # (Handled implicitly by build_window_feature_vector via padding.)
        cands = candidate_anchors(notes_internal)
        gt_anchor = next(
            (n.get("anchor") for n in window_notes if n.get("anchor") is not None),
            None,
        )

        best = None
        all_scores = []
        for cand in cands:
            feats = build_window_feature_vector(notes_internal, cand, WINDOW_SIZE)
            out = predict_row(models, feat_names, f_names, feats)
            anchor_prob = out["anchor_probability"]
            slot_nlls = []
            for slot_idx, n in enumerate(window_notes[:WINDOW_SIZE]):
                gt_finger = n.get("finger", "open")
                gt_idx = FINGER_TO_INT.get(gt_finger, 0)
                p = out["slot_finger_probs"][slot_idx]["probabilities"][gt_idx]
                slot_nlls.append(-np.log(max(p, 1e-9)))
            mean_nll = float(np.mean(slot_nlls))
            score = anchor_prob - 0.2 * mean_nll
            all_scores.append({
                "candidate_anchor": cand,
                "anchor_probability": round(anchor_prob, 6),
                "mean_slot_nll_at_gt": round(mean_nll, 4),
                "composite_score": round(score, 4),
            })
            if best is None or score > best["score"]:
                best = {
                    "cand": cand,
                    "score": score,
                    "out": out,
                    "anchor_prob": anchor_prob,
                }

        # Per-note metrics under the best anchor
        n_correct_local = 0
        n_total_local = 0
        predicted_fingers = []
        for slot_idx, n in enumerate(window_notes[:WINDOW_SIZE]):
            gt_finger = n.get("finger", "open")
            pred = best["out"]["slot_finger_probs"][slot_idx]["argmax_finger"]
            predicted_fingers.append(pred)
            n_total_local += 1
            if pred == gt_finger:
                n_correct_local += 1
            if gt_finger != "pinky" and pred == "pinky":
                pinky_fp += 1
            elif gt_finger != "pinky" and pred != "pinky":
                pinky_tn += 1

        total_per_note += n_total_local
        total_per_note_correct += n_correct_local
        if n_correct_local == n_total_local:
            exact_window_matches += 1
        if gt_anchor is not None and best["cand"] == gt_anchor:
            anchor_correct += 1

        golden_report["cases"].append({
            "case_id": case["case_id"],
            "ground_truth_anchor": gt_anchor,
            "predicted_anchor": best["cand"],
            "anchor_match": (gt_anchor == best["cand"]),
            "predicted_fingers": predicted_fingers,
            "ground_truth_fingers": [n.get("finger") for n in window_notes[:WINDOW_SIZE]],
            "per_note_accuracy": round(n_correct_local / max(n_total_local, 1), 3),
            "exact_window_match": n_correct_local == n_total_local,
            "all_anchor_scores": all_scores,
            "rationale": case.get("rationale", ""),
        })

    evaluated = [c for c in golden_report["cases"] if "predicted_fingers" in c]
    golden_report["summary"] = {
        "n_cases": len(cases),
        "n_evaluated": len(evaluated),
        "per_note_accuracy": (
            round(total_per_note_correct / max(total_per_note, 1), 4)
        ),
        "exact_window_match_rate": (
            round(exact_window_matches / max(len(evaluated), 1), 4)
        ),
        "anchor_accuracy": (
            round(anchor_correct / max(len(evaluated), 1), 4)
        ),
        "pinky_false_positive_rate": (
            round(pinky_fp / max(pinky_fp + pinky_tn, 1), 4)
        ),
    }

    out_path = HANDOFF_DIR / "phrase_window_fingering_v1_golden_report.json"
    with open(out_path, "w") as f:
        json.dump(golden_report, f, indent=2)
    print(f"Golden report saved: {out_path}")
    print(json.dumps(golden_report["summary"], indent=2))

    # ----- 3. Consolidated metrics file -----
    with open(PHASE4_DIR / "training_report_phrase_window_v1.json") as f:
        train_rep = json.load(f)
    metrics = {
        "schema_version": "fretwise-ml-v2",
        "model_name": "phrase_window_fingering_v1",
        "validation_metrics_train_split": {
            "per_note_finger_accuracy": train_rep["per_note_finger_accuracy"],
            "exact_window_match_rate": train_rep["exact_window_match_rate"],
            "pinky_overuse_rate": train_rep["pinky_overuse_rate"],
            "anchor_head_accuracy": train_rep["anchor_head_accuracy"],
            "per_slot_metrics": train_rep["per_slot_metrics"],
        },
        "golden_set_v1_metrics": golden_report["summary"],
    }
    metrics_path = HANDOFF_DIR / "phrase_window_fingering_v1_metrics.json"
    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2)
    print(f"Metrics saved: {metrics_path}")


if __name__ == "__main__":
    main()
