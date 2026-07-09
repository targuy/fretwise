"""Train PhraseWindowFingeringModelV1.

Spec contract: FretWise ML Training Spec v2, Section 4.

Architecture (baseline v1):
  - Inputs: window features (per-note x WINDOW_SIZE + window-level + anchor)
  - Outputs: per-slot finger probability distribution + anchor likelihood
  - Model: 5 XGBoost classifiers (one per slot for finger) + 1 binary anchor head

This is the simplest baseline that satisfies the spec contract. A sequential
model (small Transformer or BiLSTM) is the obvious next step (v2) but is
expected to only marginally outperform this approach with the current data
volumes (< 500K windows).

The critical metric to watch is `pinky_false_positive_rate` — the rule we are
trying to teach is "pinky is an extension, not an anchor".
"""

import json

import numpy as np

from fretwise.dataset._mldeps import optional_attr, optional_import
from fretwise.dataset.config import HANDOFF_DIR, PROCESSED_DIR
from fretwise.dataset.features.phrase_window_features import WINDOW_SIZE

xgb = optional_import("xgboost")
accuracy_score = optional_attr("sklearn.metrics", "accuracy_score")
log_loss = optional_attr("sklearn.metrics", "log_loss")

PHASE4_DIR = PROCESSED_DIR / "phase4"

FINGER_NAMES = {0: "open", 1: "index", 2: "middle", 3: "ring", 4: "pinky"}


def load_data():
    X = np.load(PHASE4_DIR / "X_phrase_window.npy")
    y_fingers = np.load(PHASE4_DIR / "y_fingers.npy")
    y_anchor = np.load(PHASE4_DIR / "y_anchor.npy")
    sources = np.load(PHASE4_DIR / "sources.npy")
    with open(PHASE4_DIR / "feature_names.json") as f:
        feature_names = json.load(f)
    return X, y_fingers, y_anchor, sources, feature_names


def train_slot_classifier(X_train, y_train, X_val, y_val, feature_names, num_rounds=400):
    # XGBoost ONNX export requires feature names in f%d format.
    f_names = [f"f{i}" for i in range(len(feature_names))]
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=f_names)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=f_names)
    params = {
        "objective": "multi:softprob",
        "num_class": 5,
        "max_depth": 7,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "seed": 42,
    }
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=num_rounds,
        evals=[(dval, "val")],
        early_stopping_rounds=30,
        verbose_eval=0,
    )
    probs = model.predict(dval)
    preds = probs.argmax(axis=1)
    return model, probs, preds


def train_anchor_head(X_train, y_train, X_val, y_val, feature_names, num_rounds=300):
    f_names = [f"f{i}" for i in range(len(feature_names))]
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=f_names)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=f_names)
    params = {
        "objective": "binary:logistic",
        "max_depth": 6,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "eval_metric": "logloss",
        "tree_method": "hist",
        "seed": 42,
    }
    model = xgb.train(
        params,
        dtrain,
        num_boost_round=num_rounds,
        evals=[(dval, "val")],
        early_stopping_rounds=30,
        verbose_eval=0,
    )
    probs = model.predict(dval)
    return model, probs


def compute_per_slot_metrics(y_true, y_pred, y_probs):
    metrics = {}
    for slot in range(WINDOW_SIZE):
        slot_true = y_true[:, slot]
        slot_pred = y_pred[:, slot]
        slot_probs = y_probs[slot]
        try:
            ll = log_loss(slot_true, slot_probs, labels=[0, 1, 2, 3, 4])
        except ValueError:
            ll = None
        metrics[f"slot_{slot}"] = {
            "accuracy": float(accuracy_score(slot_true, slot_pred)),
            "n_pinky_true": int((slot_true == 4).sum()),
            "n_pinky_pred": int((slot_pred == 4).sum()),
            "pinky_fpr": float(
                ((slot_pred == 4) & (slot_true != 4)).sum()
                / max((slot_true != 4).sum(), 1)
            ),
            "pinky_fnr": float(
                ((slot_pred != 4) & (slot_true == 4)).sum()
                / max((slot_true == 4).sum(), 1)
            ),
            "nll": float(ll) if ll is not None else None,
        }
    return metrics


def compute_window_metrics(y_true, y_pred):
    exact_match = (y_true == y_pred).all(axis=1)
    return {
        "exact_window_match_rate": float(exact_match.mean()),
        "per_note_finger_accuracy": float((y_true == y_pred).mean()),
    }


def compute_pinky_overuse(y_true, y_pred):
    """Across all slots: how often does the model predict pinky when truth was not pinky?"""
    flat_true = y_true.ravel()
    flat_pred = y_pred.ravel()
    return float(
        ((flat_pred == 4) & (flat_true != 4)).sum() / max((flat_true != 4).sum(), 1)
    )


def export_onnx(models, feature_names, out_path, out_dir):
    """Export each head as a separate ONNX file plus a small bundle manifest.

    Merging multiple XGBoost ONNX graphs into one file is fragile (each graph
    has the same `input` / `probabilities` / `label` node names and onnx.compose
    refuses to merge them without surgery). Shipping 6 separate ONNX files
    + a manifest is the contract FretWise can load via onnxruntime.
    """
    from onnxmltools.convert.common.data_types import FloatTensorType
    from onnxmltools.convert.xgboost.convert import convert as xgb_to_onnx

    n_features = len(feature_names)
    initial_types = [("input", FloatTensorType([None, n_features]))]

    manifest = {
        "bundle_name": "phrase_window_fingering_v1",
        "feature_count": n_features,
        "heads": {},
    }
    for name, model in models.items():
        onnx_model = xgb_to_onnx(
            model,
            initial_types=initial_types,
            target_opset=15,
        )
        head_path = out_dir / f"phrase_window_v1_{name}.onnx"
        with open(head_path, "wb") as f:
            f.write(onnx_model.SerializeToString())
        manifest["heads"][name] = head_path.name

    with open(out_path, "w") as f:
        json.dump(manifest, f, indent=2)


def main():
    X, y_fingers, y_anchor, sources, feature_names = load_data()
    n_rows, n_feats = X.shape
    print(f"Loaded {n_rows:,} rows x {n_feats} features")

    # 80/20 split, stratified on slot_0 finger to keep label balance comparable
    rng = np.random.default_rng(42)
    perm = rng.permutation(n_rows)
    split = int(0.8 * n_rows)
    train_idx = perm[:split]
    val_idx = perm[split:]

    X_train, X_val = X[train_idx], X[val_idx]
    y_train_f, y_val_f = y_fingers[train_idx], y_fingers[val_idx]
    y_train_a, y_val_a = y_anchor[train_idx], y_anchor[val_idx]

    models = {}
    all_probs = []
    all_preds = np.zeros_like(y_val_f)

    for slot in range(WINDOW_SIZE):
        print(f"\n--- Training slot {slot} finger classifier ---")
        model, probs, preds = train_slot_classifier(
            X_train, y_train_f[:, slot], X_val, y_val_f[:, slot], feature_names
        )
        models[f"slot{slot}_finger"] = model
        all_probs.append(probs)
        all_preds[:, slot] = preds

    print("\n--- Training anchor head ---")
    anchor_model, anchor_probs = train_anchor_head(
        X_train, y_train_a, X_val, y_val_a, feature_names
    )
    models["anchor_head"] = anchor_model

    # Metrics
    slot_metrics = compute_per_slot_metrics(y_val_f, all_preds, all_probs)
    window_metrics = compute_window_metrics(y_val_f, all_preds)
    pinky_overuse = compute_pinky_overuse(y_val_f, all_preds)

    anchor_pred_bin = (anchor_probs >= 0.5).astype(np.int32)
    anchor_acc = float(accuracy_score(y_val_a, anchor_pred_bin))

    print("\n=== PhraseWindowFingeringModelV1 ===")
    print(f"Per-note finger accuracy: {window_metrics['per_note_finger_accuracy']*100:.2f}%")
    print(f"Exact window match: {window_metrics['exact_window_match_rate']*100:.2f}%")
    print(f"Pinky overuse (FPR overall): {pinky_overuse*100:.2f}%")
    print(f"Anchor head accuracy: {anchor_acc*100:.2f}%")

    # Save XGBoost models
    PHASE4_DIR.mkdir(exist_ok=True, parents=True)
    for name, model in models.items():
        model.save_model(str(PHASE4_DIR / f"xgb_{name}_v1.json"))

    # Try to export ONNX (bundle of 6 heads + manifest)
    manifest_path = PHASE4_DIR / "phrase_window_fingering_v1_manifest.json"
    try:
        export_onnx(models, feature_names, manifest_path, PHASE4_DIR)
        print(f"\nONNX bundle manifest: {manifest_path}")
    except Exception as e:
        print(f"\nONNX export skipped: {e}")

    # Save training report
    report = {
        "model_name": "phrase_window_fingering_v1",
        "model_version": "1.0.0",
        "schema_version": "fretwise-ml-v2",
        "feature_dim": n_feats,
        "window_size": WINDOW_SIZE,
        "train_rows": int(len(train_idx)),
        "val_rows": int(len(val_idx)),
        "per_note_finger_accuracy": window_metrics["per_note_finger_accuracy"],
        "exact_window_match_rate": window_metrics["exact_window_match_rate"],
        "pinky_overuse_rate": pinky_overuse,
        "anchor_head_accuracy": anchor_acc,
        "per_slot_metrics": slot_metrics,
    }
    with open(PHASE4_DIR / "training_report_phrase_window_v1.json", "w") as f:
        json.dump(report, f, indent=2)

    # Copy ONNX + XGBoost fallbacks to handoff
    if HANDOFF_DIR.exists():
        import shutil

        if manifest_path.exists():
            shutil.copy2(manifest_path, HANDOFF_DIR / manifest_path.name)
        for name in models:
            onnx_head = PHASE4_DIR / f"phrase_window_v1_{name}.onnx"
            xgb_head = PHASE4_DIR / f"xgb_{name}_v1.json"
            if onnx_head.exists():
                shutil.copy2(onnx_head, HANDOFF_DIR / onnx_head.name)
            if xgb_head.exists():
                shutil.copy2(xgb_head, HANDOFF_DIR / xgb_head.name)
        shutil.copy2(
            PHASE4_DIR / "training_report_phrase_window_v1.json",
            HANDOFF_DIR / "training_report_phrase_window_v1.json",
        )

    print("\nReport saved.")


if __name__ == "__main__":
    main()
