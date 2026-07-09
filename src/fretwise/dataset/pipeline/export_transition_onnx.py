"""Export XGBoost v3 transition-cost model to ONNX format.

Loads the Phase 3 v3 model, exports to ONNX via onnxmltools,
validates output against native XGBoost predictions.
"""

import json
from pathlib import Path

import numpy as np

from fretwise.dataset._mldeps import optional_import
from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR

xgb = optional_import("xgboost")

PHASE3_DIR = PROCESSED_DIR / "phase3"

MODEL_VERSION = "v3"
MODEL_JSON = PHASE3_DIR / f"xgb_transition_cost_{MODEL_VERSION}.json"
REPORT_JSON = PHASE3_DIR / f"training_report_{MODEL_VERSION}.json"
ONNX_PATH = HANDOFF_DIR / f"transition_cost_{MODEL_VERSION}.onnx"

FEATURES: list[str] = []
N_FEATURES = 0


def _load_features() -> None:
    """Load the trained feature order from the v3 training report (lazy)."""
    global FEATURES, N_FEATURES
    with open(REPORT_JSON) as f:
        FEATURES = json.load(f)["feature_names"]
    N_FEATURES = len(FEATURES)
    assert N_FEATURES == 26, f"Expected 26 features, got {N_FEATURES}"


def load_model():
    model = xgb.Booster()
    model.load_model(str(MODEL_JSON))
    return model


def get_test_row():
    """Load a valid test row from the training data (after filtering/dropping)."""
    X_raw = np.load(PHASE3_DIR / "X_transitions.npy")
    y_raw = np.load(PHASE3_DIR / "y_transitions.npy")
    with open(PHASE3_DIR / "feature_names.json") as f:
        raw_names = json.load(f)

    position_cols = ["prev_string", "curr_string", "prev_fret", "curr_fret"]
    col_indices = [raw_names.index(c) for c in position_cols]
    valid_mask = np.ones(X_raw.shape[0], dtype=bool)
    for idx in col_indices:
        col = X_raw[:, idx]
        valid_mask &= col >= 0
        if np.issubdtype(col.dtype, np.floating):
            valid_mask &= ~np.isnan(col)
    X_filt = X_raw[valid_mask]
    y_filt = y_raw[valid_mask]

    drop_features = {"curr_finger", "position_inferred"}
    keep_cols = [i for i, name in enumerate(raw_names) if name not in drop_features]
    X_clean = X_filt[:, keep_cols]

    return X_clean[0:1].astype(np.float32), int(y_filt[0])


def export_onnx(model):
    """Export to ONNX via onnxmltools."""
    import tempfile

    from onnxmltools.convert import convert_xgboost
    from onnxmltools.convert.common.data_types import FloatTensorType

    tmp_path = Path(tempfile.mktemp(suffix=".json"))
    model.save_model(str(tmp_path))
    with open(tmp_path) as f:
        model_text = f.read()

    for i, name in enumerate(FEATURES):
        model_text = model_text.replace(f'"{name}"', f'"f{i}"')

    with open(tmp_path, "w") as f:
        f.write(model_text)

    generic_model = xgb.Booster()
    generic_model.load_model(str(tmp_path))
    tmp_path.unlink()

    initial_types = [("input", FloatTensorType([None, N_FEATURES]))]
    onnx_model = convert_xgboost(generic_model, initial_types=initial_types)

    import onnx
    onnx.save_model(onnx_model, str(ONNX_PATH))
    print(f"ONNX model saved: {ONNX_PATH}")
    print(f"  Size: {ONNX_PATH.stat().st_size / 1024:.0f} KB")
    return onnx_model


def validate_onnx(model, test_row, test_label):
    """Compare ONNX output to native XGBoost output."""
    import onnxruntime as ort

    dmat = xgb.DMatrix(test_row, feature_names=FEATURES)
    xgb_probs = model.predict(dmat)
    xgb_pred = int(np.argmax(xgb_probs[0]))

    sess = ort.InferenceSession(str(ONNX_PATH))
    input_name = sess.get_inputs()[0].name
    outputs = sess.run(None, {input_name: test_row})

    print(f"\nONNX outputs: {len(outputs)} tensor(s)")
    for i, out in enumerate(outputs):
        arr = np.array(out)
        print(f"  output[{i}]: shape={arr.shape}, dtype={arr.dtype}")

    if len(outputs) == 2:
        onnx_pred = int(outputs[0][0])
        onnx_probs = np.array(outputs[1][0])
        if hasattr(onnx_probs, 'dtype') and onnx_probs.dtype == np.object_:
            prob_list = []
            for d in outputs[1]:
                prob_list.append([d.get(i, 0.0) for i in range(5)])
            onnx_probs = np.array(prob_list[0])
    elif len(outputs) == 1:
        arr = np.array(outputs[0])
        if arr.ndim == 2 and arr.shape[1] == 5:
            onnx_probs = arr[0]
            onnx_pred = int(np.argmax(onnx_probs))
        else:
            onnx_pred = int(arr[0])
            onnx_probs = None
    else:
        print("WARNING: unexpected output count")
        return False

    max_diff = float(np.max(np.abs(xgb_probs[0] - onnx_probs))) if onnx_probs is not None else -1
    print("\nValidation:")
    print(f"  Ground truth label: {test_label}")
    print(f"  XGBoost pred: {xgb_pred}, probs: {np.round(xgb_probs[0], 6)}")
    if onnx_probs is not None:
        print(f"  ONNX pred:    {onnx_pred}, probs: {np.round(onnx_probs, 6)}")
        print(f"  Max prob diff: {max_diff:.2e}")
    else:
        print(f"  ONNX pred: {onnx_pred} (no probabilities)")

    ok = max_diff < 1e-4 if max_diff >= 0 else (xgb_pred == onnx_pred)
    print(f"  Status: {'PASS' if ok else 'FAIL'}")
    return ok


def write_fallback_shim(model, test_row):
    """If ONNX fails, write a Python inference shim instead."""
    shim_path = HANDOFF_DIR / f"transition_cost_{MODEL_VERSION}_inference.py"

    content = f'''"""Standalone transition-cost inference (fallback if ONNX unavailable).

Usage:
    model = TransitionCostModel("{MODEL_JSON}")
    probs = model.predict(feature_dict)  # returns 5 probabilities
    finger = model.predict_finger(feature_dict)  # returns best finger (0-4)
"""

import numpy as np
import xgboost as xgb

FEATURE_NAMES = {json.dumps(FEATURES)}


class TransitionCostModel:
    def __init__(self, model_path: str):
        self.booster = xgb.Booster()
        self.booster.load_model(model_path)

    def predict(self, feature_dict: dict) -> np.ndarray:
        """Return 5-class probability vector [open/thumb, index, middle, ring, pinky]."""
        row = np.array([[feature_dict[f] for f in FEATURE_NAMES]], dtype=np.float32)
        dmat = xgb.DMatrix(row, feature_names=FEATURE_NAMES)
        return self.booster.predict(dmat)[0]

    def predict_finger(self, feature_dict: dict) -> int:
        """Return best finger index (0=open/thumb, 1=index, 2=middle, 3=ring, 4=pinky)."""
        probs = self.predict(feature_dict)
        return int(np.argmax(probs))
'''
    with open(shim_path, "w") as f:
        f.write(content)
    print(f"\nFallback Python shim saved: {shim_path}")


def main():
    print(f"=== Export Transition Cost {MODEL_VERSION} to ONNX ===\n")
    _load_features()
    model = load_model()
    test_row, test_label = get_test_row()
    print(f"Model loaded: {N_FEATURES} features, test label={test_label}")

    try:
        export_onnx(model)
        ok = validate_onnx(model, test_row, test_label)
        if not ok:
            print("\nONNX validation FAILED — writing fallback shim")
            write_fallback_shim(model, test_row)
    except Exception as e:
        print(f"\nONNX export FAILED: {e}")
        print("Writing fallback Python inference shim...")
        write_fallback_shim(model, test_row)


if __name__ == "__main__":
    main()
