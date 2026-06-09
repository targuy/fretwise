"""Parity tests for the phrase_window_v1 fingering bundle (shadow model).

Two layers:

  1. Feature parity (no ONNX runtime) — ``build_window_feature_vector`` must
     reproduce every ``expected_features`` value in the calibration JSON to
     1e-6. This is the binding contract from GuitarDataSet (FW-015).
  2. Inference parity (skipped when onnxruntime or the bundle is absent) —
     the loaded six-head bundle reproduces the recorded ``model_output`` of
     the two fully-pinned calibration cases, and selects the ground-truth
     anchor among the real candidates.

The two ``expected_features_partial`` cases pin only a subset of features;
GuitarDataSet's recorded ``model_output`` for them was produced by the raw
XGBoost fallback over the *full* (unpinned) vector, so only argmax agreement
(not bit-exact probabilities) is asserted for those.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from fretwise.ml import (
    PhraseNote,
    build_window_feature_vector,
    candidate_anchors,
    note_from_fretwise,
    phrase_window_feature_names,
)
from fretwise.ml.phrase_window import _PER_NOTE_KEYS, PAD_VALUE, WINDOW_SIZE

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS = REPO_ROOT / "data" / "models"
CALIB_PATH = MODELS / "phrase_window_fingering_v1_calibration.json"
SPEC_PATH = MODELS / "phrase_window_fingering_v1_spec.json"
MANIFEST_PATH = MODELS / "phrase_window_fingering_v1_manifest.json"

ATOL_FEATURE = 1e-6
ATOL_ONNX = 1e-4


@pytest.fixture(scope="module")
def calibration() -> dict:
    if not CALIB_PATH.exists():
        pytest.skip(f"Calibration file missing: {CALIB_PATH}")
    return json.loads(CALIB_PATH.read_text(encoding="utf-8"))


def _to_notes(raw: list[dict]) -> list[PhraseNote]:
    """Build PhraseNotes from a calibration ``input_notes`` block.

    Calibration strings are already in the internal 0-based convention.
    """
    return [
        PhraseNote(
            string=n["string"],
            fret=n["fret"],
            pitch=n["midi"],
            onset=n["onset"],
            duration=n["duration"],
            is_chord_member=bool(n.get("is_chord_member")),
        )
        for n in raw
    ]


# ---------------------------------------------------------------------------
# Feature ordering / layout
# ---------------------------------------------------------------------------


def test_feature_names_count_is_74() -> None:
    names = phrase_window_feature_names()
    assert len(names) == 74
    assert len(names) == WINDOW_SIZE * len(_PER_NOTE_KEYS) + 14


def test_feature_names_match_spec_layout() -> None:
    if not SPEC_PATH.exists():
        pytest.skip(f"Spec missing: {SPEC_PATH}")
    spec = json.loads(SPEC_PATH.read_text(encoding="utf-8"))
    layout = spec["feature_layout"]
    expected: list[str] = []
    for slot in range(spec["window_size"]):
        for key in layout["per_note_slot_features"]:
            expected.append(key.replace("{slot}", str(slot)))
    expected.extend(layout["window_level_features"])
    assert tuple(expected) == phrase_window_feature_names()
    assert layout["total_feature_count"] == 74


# ---------------------------------------------------------------------------
# Feature extraction parity vs calibration (binding contract)
# ---------------------------------------------------------------------------


def test_all_calibration_features_match(calibration: dict) -> None:
    names = phrase_window_feature_names()
    for ex in calibration["examples"]:
        notes = _to_notes(ex["input_notes"])
        fv = build_window_feature_vector(notes, ex["candidate_anchor"])
        # every feature name must be present, no extras
        assert set(fv.keys()) == set(names), ex["case_id"]
        expected = ex.get("expected_features") or ex.get("expected_features_partial")
        for key, value in expected.items():
            assert abs(fv[key] - value) <= ATOL_FEATURE, (
                f"{ex['case_id']}::{key} got {fv[key]} expected {value}"
            )


# ---------------------------------------------------------------------------
# Candidate-anchor generation
# ---------------------------------------------------------------------------


def test_candidate_anchors_union_then_median_reduction() -> None:
    # GDS-024 worked example: Django 7-7-5-7-5 → fretted {5,7} →
    # union {2,3,4,5,6,7} (6 > 4) → reduced to {lowest, highest, median=sorted[3]}.
    notes = [PhraseNote(1, f, 60, i, 1.0) for i, f in enumerate([7, 7, 5, 7, 5])]
    assert candidate_anchors(notes) == [2, 5, 7]


def test_candidate_anchors_union_no_reduction_at_four() -> None:
    # GDS-024 worked example: Apache {2,2,2,4,2} → union {1,2,3,4} (exactly 4,
    # no reduction). This is why anchor 4 is a valid candidate.
    notes = [PhraseNote(2, f, 50, i, 0.5) for i, f in enumerate([2, 2, 2, 4, 2])]
    assert candidate_anchors(notes) == [1, 2, 3, 4]


def test_candidate_anchors_clip_to_valid_range() -> None:
    # Single low fretted note 2 → {2,1} (0 and -1 clipped out), ≤4 so no reduction.
    notes = [PhraseNote(2, 2, 50, 0, 0.5), PhraseNote(2, 2, 50, 1, 0.5)]
    assert candidate_anchors(notes) == [1, 2]


def test_candidate_anchors_all_open_defaults_to_one() -> None:
    notes = [PhraseNote(0, 0, 64, 0, 1.0), PhraseNote(1, 0, 59, 1, 1.0)]
    assert candidate_anchors(notes) == [1]


# ---------------------------------------------------------------------------
# Padding
# ---------------------------------------------------------------------------


def test_short_window_pads_empty_slots() -> None:
    notes = [PhraseNote(1, 5, 64, 0, 1.0), PhraseNote(1, 7, 66, 1, 1.0)]
    fv = build_window_feature_vector(notes, candidate_anchor=5)
    # Slots 0,1 are real; 2,3,4 must be PAD in every per-note feature.
    for slot in (2, 3, 4):
        for key in _PER_NOTE_KEYS:
            assert fv[f"n{slot}_{key}"] == PAD_VALUE
    assert fv["win_num_notes"] == 2.0


def test_open_string_fret_rel_is_negative() -> None:
    # An open string in a fretted window has negative fret_rel_min/anchor.
    notes = [
        PhraseNote(0, 0, 64, 0, 1.0),   # open
        PhraseNote(2, 5, 60, 1, 1.0),   # fretted, min fret 5
    ]
    fv = build_window_feature_vector(notes, candidate_anchor=5)
    assert fv["n0_is_open"] == 1.0
    assert fv["n0_fret_rel_min"] == -5.0
    assert fv["n0_fret_rel_anchor"] == -5.0


def test_note_from_fretwise_subtracts_one() -> None:
    # FretWise string_num 1 (high e) → internal string 0.
    note = note_from_fretwise(string_num=1, fret=7, pitch=66, onset=0.0, duration=1.0)
    assert note.string == 0


# ---------------------------------------------------------------------------
# ONNX inference parity (gated on onnxruntime + bundle present)
# ---------------------------------------------------------------------------


def _load_model():
    pytest.importorskip("onnxruntime")
    if not MANIFEST_PATH.exists():
        pytest.skip(f"Bundle manifest missing: {MANIFEST_PATH}")
    from fretwise.ml import LearnedPhraseWindowFingerer

    return LearnedPhraseWindowFingerer.from_model_dir(MODELS)


def test_bundle_reproduces_recorded_outputs(calibration: dict) -> None:
    """Cases with a recorded model_output must match it bit-for-bit.

    Witness cases (synthetic, ``model_output: null``) exist only to pin
    features and are skipped here.
    """
    model = _load_model()
    scored = [ex for ex in calibration["examples"] if ex.get("model_output") is not None]
    assert scored, "expected at least one case with a recorded model_output"
    for ex in scored:
        notes = _to_notes(ex["input_notes"])
        fv = build_window_feature_vector(notes, ex["candidate_anchor"])
        slot_probs, anchor_probs = model._run_bundle([fv])
        mo = ex["model_output"]
        assert abs(anchor_probs[0] - mo["anchor_probability"]) <= ATOL_ONNX, ex["case_id"]
        for slot, expected_slot in enumerate(mo["slot_finger_probs"]):
            for got, exp in zip(slot_probs[0][slot], expected_slot["probabilities"]):
                assert abs(got - exp) <= ATOL_ONNX, f"{ex['case_id']} slot{slot}"


def test_anchor_selection_picks_ground_truth(calibration: dict) -> None:
    """predict_window selects the correct anchor for the GT-anchor cases.

    Restricted to cases whose pinned anchor is the correct one
    (``expected_targets.anchor_correct``) and that carry a model_output —
    i.e. django/apache_2, not the deliberately-wrong or witness cases.
    """
    model = _load_model()
    gt_cases = [
        ex for ex in calibration["examples"]
        if ex.get("model_output") is not None
        and ex.get("expected_targets", {}).get("anchor_correct") is True
    ]
    assert gt_cases, "expected at least one correct-anchor case"
    for ex in gt_cases:
        notes = _to_notes(ex["input_notes"])
        prediction = model.predict_window(notes)
        assert ex["candidate_anchor"] in [a for a, _ in prediction.candidate_scores], ex["case_id"]
        assert prediction.anchor == ex["candidate_anchor"], ex["case_id"]
        assert len(prediction.slots) == len(notes)


def test_predict_sequence_covers_every_note_and_is_pure(calibration: dict) -> None:
    model = _load_model()
    notes = _to_notes(calibration["examples"][0]["input_notes"]) * 2  # 10 notes
    before = copy.deepcopy(notes)
    predictions = model.predict_sequence(notes, stride=1)
    assert len(predictions) == len(notes)
    assert all(p.n_windows >= 1 for p in predictions)
    assert all(p.finger in {"open", "index", "middle", "ring", "pinky"} for p in predictions)
    assert notes == before  # input not mutated (shadow model is read-only)


def test_open_chord_slots_decode_open_strings(calibration: dict) -> None:
    """The open-E case decodes its two open strings as 'open'."""
    model = _load_model()
    ex = next(e for e in calibration["examples"] if e["case_id"] == "open_chord_E_anchor_1")
    notes = _to_notes(ex["input_notes"])
    fv = build_window_feature_vector(notes, ex["candidate_anchor"])
    slot_probs, _ = model._run_bundle([fv])
    # slots 0,1 are the open high-e and B strings.
    for slot in (0, 1):
        best = max(range(5), key=lambda c: slot_probs[0][slot][c])
        assert best == 0  # index 0 == "open"
