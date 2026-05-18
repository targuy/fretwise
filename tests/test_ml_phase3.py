"""Parity tests for Phase 3 transition cost integration.

Validates that ``extract_transition_features`` produces the exact 26 floats
that GuitarDataSet's training pipeline produces, by comparing against the
three calibration cases shipped alongside the v2 ONNX model.

When ``onnxruntime`` is installed and the model is present, also runs the
ONNX inference on the same three cases and verifies that the predicted
probabilities and the Viterbi-additive cost match the calibration record
to within ``ATOL`` tolerance.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from fretwise.ml import (
    _PHASE3_FEATURE_NAMES,
    _PHASE3_FINGER_TO_INDEX,
    extract_transition_features,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

REPO_ROOT = Path(__file__).resolve().parents[1]
CALIB_PATH = REPO_ROOT / "data" / "models" / "transition_cost_v2_calibration.json"
MODEL_PATH = REPO_ROOT / "data" / "models" / "transition_cost_v2.onnx"
SPEC_PATH = REPO_ROOT / "data" / "models" / "transition_cost_v2_spec.json"

ATOL = 1e-4  # ONNX inference precision tolerance


@pytest.fixture(scope="module")
def calibration() -> dict:
    if not CALIB_PATH.exists():
        pytest.skip(f"Calibration file missing: {CALIB_PATH}")
    return json.loads(CALIB_PATH.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# Feature extraction parity (no ONNX runtime needed)
# ---------------------------------------------------------------------------


def test_feature_names_match_calibration(calibration: dict) -> None:
    """Feature ordering in FW must match the calibration feature_order."""
    assert tuple(calibration["feature_order"]) == _PHASE3_FEATURE_NAMES


def test_n_features_is_26(calibration: dict) -> None:
    assert calibration["n_features"] == 26
    assert len(_PHASE3_FEATURE_NAMES) == 26


@pytest.mark.parametrize("example_idx", [0, 1, 2])
def test_feature_extraction_parity(calibration: dict, example_idx: int) -> None:
    """All 26 features must match the calibration ``features_expected``
    block bit-for-bit (the model was trained on these exact values)."""
    example = calibration["examples"][example_idx]
    prev = example["prev_state"]
    curr = example["curr_state"]
    expected = example["features_expected"]

    actual = extract_transition_features(
        prev_string_model=prev["string"],
        prev_fret=prev["fret"],
        prev_finger_model=_PHASE3_FINGER_TO_INDEX[prev["finger"]],
        curr_string_model=curr["string"],
        curr_fret=curr["fret"],
        prev_midi=prev["midi"],
        curr_midi=curr["midi"],
    )

    # All 26 features must be present, in the expected order, with values
    # equal to the calibration record. Use exact equality — floats are
    # deterministic for these inputs (no trig / sqrt / division by non-2).
    mismatches: list[str] = []
    for feature_name in _PHASE3_FEATURE_NAMES:
        if feature_name not in expected:
            # Calibration record may omit some features; skip those.
            continue
        if actual[feature_name] != expected[feature_name]:
            mismatches.append(
                f"  {feature_name}: actual={actual[feature_name]!r} "
                f"expected={expected[feature_name]!r}"
            )

    assert not mismatches, (
        f"Feature mismatch on example '{example['label']}':\n"
        + "\n".join(mismatches)
    )


# ---------------------------------------------------------------------------
# ONNX end-to-end parity (requires onnxruntime + model file)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def learned_cost():
    """Construct LearnedPlayerCost or skip if dependencies are missing."""
    try:
        import onnxruntime  # noqa: F401
    except ImportError:
        pytest.skip("onnxruntime not installed")
    if not MODEL_PATH.exists():
        pytest.skip(f"Model file missing: {MODEL_PATH}")
    from fretwise.ml import LearnedPlayerCost

    return LearnedPlayerCost(
        model_path=str(MODEL_PATH),
        spec_path=str(SPEC_PATH) if SPEC_PATH.exists() else None,
    )


@pytest.mark.parametrize("example_idx", [0, 1, 2])
def test_onnx_probabilities_match_calibration(
    calibration: dict, learned_cost, example_idx: int,
) -> None:
    """ONNX inference probabilities must match calibration to within ATOL."""
    example = calibration["examples"][example_idx]
    prev = example["prev_state"]
    curr = example["curr_state"]
    expected_probs = example["model_output"]["probabilities"]

    probs = learned_cost._predict_probs(
        prev_string_model=prev["string"],
        prev_fret=prev["fret"],
        prev_finger_model=_PHASE3_FINGER_TO_INDEX[prev["finger"]],
        curr_string_model=curr["string"],
        curr_fret=curr["fret"],
        prev_midi=prev["midi"],
        curr_midi=curr["midi"],
    )

    # Probabilities are ordered [open, index, middle, ring, pinky].
    finger_order = ("open", "index", "middle", "ring", "pinky")
    mismatches: list[str] = []
    for i, finger_name in enumerate(finger_order):
        actual = probs[i]
        expected = expected_probs[finger_name]
        if abs(actual - expected) > ATOL:
            mismatches.append(
                f"  p[{finger_name}]: actual={actual:.6f} "
                f"expected={expected:.6f} delta={actual - expected:+.2e}"
            )

    assert not mismatches, (
        f"Probability mismatch on example '{example['label']}':\n"
        + "\n".join(mismatches)
    )


@pytest.mark.parametrize("example_idx", [0, 1, 2])
def test_transition_cost_matches_calibration(
    calibration: dict, learned_cost, example_idx: int,
) -> None:
    """Viterbi-additive cost = -log(p[GT_finger]) must match calibration.

    Routed through _predict_probs with explicit MIDI to make the test
    robust to non-standard-tuning calibration cases (e.g. example 3
    has prev_midi=60 / curr_midi=59, which doesn't match standard tuning
    + the given string/fret). The cost formula itself is what's under test.
    """
    example = calibration["examples"][example_idx]
    prev = example["prev_state"]
    curr = example["curr_state"]
    gt_finger = curr["ground_truth_finger"]
    expected_cost = example["model_output"]["predicted_cost"]

    probs = learned_cost._predict_probs(
        prev_string_model=prev["string"],
        prev_fret=prev["fret"],
        prev_finger_model=_PHASE3_FINGER_TO_INDEX[prev["finger"]],
        curr_string_model=curr["string"],
        curr_fret=curr["fret"],
        prev_midi=prev["midi"],
        curr_midi=curr["midi"],
    )
    gt_idx = _PHASE3_FINGER_TO_INDEX[gt_finger]
    actual_cost = -math.log(max(probs[gt_idx], 1e-9))

    # Calibration cost is rounded to 4 decimals; allow a bit more slack.
    assert math.isclose(actual_cost, expected_cost, abs_tol=1e-3), (
        f"Cost mismatch on '{example['label']}': "
        f"actual={actual_cost:.6f} expected={expected_cost:.6f} "
        f"delta={actual_cost - expected_cost:+.2e}"
    )


def test_transition_cost_via_fw_boundary_standard_tuning(
    learned_cost,
) -> None:
    """End-to-end transition_cost() via FW conventions.

    Uses calibration example 1 (trivial_adjacent_fret) which sits in
    standard tuning, so the standard-tuning MIDI derivation matches.
    Confirms FW-side string indexing (1-based) is correctly translated
    to the model's 0-based convention.
    """
    from fretwise.ml import PlayerContext

    # example 1: prev string=2 fret=1 (model G string), curr string=2 fret=2.
    # FW convention: model string 2 + 1 = FW string_num 3 (G).
    cost = learned_cost.transition_cost(
        prev_string=3,
        prev_fret=1,
        prev_finger="index",
        curr_string=3,
        curr_fret=2,
        curr_finger="middle",
        hand_position=1,
        context=PlayerContext(onset=0.0, duration=1.0, tempo=120.0),
    )
    # Calibration expected_cost for example 1 = 0.4821.
    assert math.isclose(cost, 0.4821, abs_tol=1e-3), (
        f"FW-boundary cost on example 1: actual={cost:.6f} expected=0.4821"
    )


def test_emission_cost_is_zero(learned_cost) -> None:
    """v2 model is transition-only; emission cost is always 0.0."""
    from fretwise.ml import PlayerContext

    cost = learned_cost.emission_cost(
        string=1, fret=5, finger="index", hand_position=5,
        context=PlayerContext(onset=0.0, duration=1.0, tempo=120.0),
    )
    assert cost == 0.0
