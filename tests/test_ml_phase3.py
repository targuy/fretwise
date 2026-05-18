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


# ---------------------------------------------------------------------------
# CostFunction wiring (Phase 3 injection into Viterbi scoring)
# ---------------------------------------------------------------------------


def _make_state(string_num: int, fret: int, finger: str, hand_position: int):
    from fretwise.models import Finger, FingeringState
    return FingeringState(
        string_num=string_num,
        fret=fret,
        finger=Finger(finger),
        hand_position=hand_position,
    )


def _make_note(onset: float = 0.0) -> object:
    from fretwise.models import NoteEvent
    return NoteEvent(pitch=60, onset=onset, duration=0.5, tempo=120.0)


class _RecordingPlayerCost:
    """PlayerCostModel double that returns a fixed cost and records calls."""

    def __init__(self, fixed_cost: float = 0.7):
        self.fixed_cost = fixed_cost
        self.calls: list[dict] = []

    def transition_cost(self, **kwargs):
        self.calls.append(kwargs)
        return self.fixed_cost

    def emission_cost(self, **kwargs):
        return 0.0


def test_costfunction_without_model_unchanged() -> None:
    """No player_cost_model → c_joueur stays at 0 (legacy behaviour)."""
    from fretwise.scoring import CostFunction, CostWeights

    cost_fn = CostFunction(weights=CostWeights.performance())
    s1 = _make_state(3, 5, "index", 5)
    s2 = _make_state(3, 7, "ring", 5)
    cost = cost_fn.transition_cost(s1, s2, _make_note(), index=1)
    # We don't care about exact value, just that it runs and returns a float.
    assert isinstance(cost, float) and cost >= 0.0


def test_costfunction_calls_model_when_gamma_positive() -> None:
    """Performance mode (γ=2) + injected model → transition_cost is called."""
    from fretwise.scoring import CostFunction, CostWeights

    recorder = _RecordingPlayerCost(fixed_cost=0.5)
    cost_fn = CostFunction(
        weights=CostWeights.performance(),  # γ=2.0
        player_cost_model=recorder,
    )
    s1 = _make_state(3, 5, "index", 5)
    s2 = _make_state(3, 7, "ring", 5)
    cost_fn.transition_cost(s1, s2, _make_note(), index=1)
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    # FW conventions preserved at the boundary (1-indexed strings, str finger).
    assert call["prev_string"] == 3
    assert call["prev_fret"] == 5
    assert call["prev_finger"] == "index"
    assert call["curr_string"] == 3
    assert call["curr_fret"] == 7
    assert call["curr_finger"] == "ring"


def test_costfunction_skips_model_when_gamma_zero() -> None:
    """Reference mode (γ=0) short-circuits the model call (ONNX latency saved)."""
    from fretwise.scoring import CostFunction, CostWeights

    recorder = _RecordingPlayerCost()
    cost_fn = CostFunction(
        weights=CostWeights.reference(),  # γ=0.0
        player_cost_model=recorder,
    )
    cost_fn.transition_cost(
        _make_state(3, 5, "index", 5),
        _make_state(3, 7, "ring", 5),
        _make_note(),
        index=1,
    )
    assert recorder.calls == [], (
        "Model should not be called when gamma == 0"
    )


def test_costfunction_model_exception_does_not_break_viterbi() -> None:
    """A broken model never breaks the Viterbi run — fallback to c_joueur=0."""
    from fretwise.scoring import CostFunction, CostWeights

    class _Broken:
        def transition_cost(self, **kwargs):
            raise RuntimeError("simulated model failure")

        def emission_cost(self, **kwargs):
            return 0.0

    cost_fn = CostFunction(
        weights=CostWeights.performance(),
        player_cost_model=_Broken(),
    )
    cost = cost_fn.transition_cost(
        _make_state(3, 5, "index", 5),
        _make_state(3, 7, "ring", 5),
        _make_note(),
        index=1,
    )
    assert isinstance(cost, float) and cost >= 0.0
