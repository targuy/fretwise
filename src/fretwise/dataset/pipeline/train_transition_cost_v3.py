"""Train XGBoost v3 transition-cost model for Phase 3.

Changes from v2:
- REBUILT training data with consistent string convention (0=high_E, 5=low_E)
- v2 had mixed conventions: GAPS used 0=low_E, ClassClef used 0=high_E
- String-derived features now carry correct signal across both sources
- Same hyperparameters as v2 to isolate the data quality impact
"""

import json

import numpy as np

from fretwise.dataset._mldeps import optional_attr, optional_import
from fretwise.dataset.config import PROCESSED_DIR

xgb = optional_import("xgboost")
accuracy_score = optional_attr("sklearn.metrics", "accuracy_score")
classification_report = optional_attr("sklearn.metrics", "classification_report")
StratifiedKFold = optional_attr("sklearn.model_selection", "StratifiedKFold")

PHASE3_DIR = PROCESSED_DIR / "phase3"
FINGER_NAMES = {0: "open/thumb", 1: "index", 2: "middle", 3: "ring", 4: "pinky"}
DROP_FEATURES = {"curr_finger", "position_inferred"}


def load_data():
    X = np.load(PHASE3_DIR / "X_transitions.npy")
    y = np.load(PHASE3_DIR / "y_transitions.npy")
    sources = np.load(PHASE3_DIR / "sources.npy")
    with open(PHASE3_DIR / "feature_names.json") as f:
        feature_names = json.load(f)
    return X, y, sources, feature_names


def filter_invalid_rows(X, y, sources, feature_names):
    """Remove rows where any string or fret column is negative or NaN."""
    position_cols = ["prev_string", "curr_string", "prev_fret", "curr_fret"]
    col_indices = [feature_names.index(c) for c in position_cols]

    valid_mask = np.ones(X.shape[0], dtype=bool)
    for idx in col_indices:
        col = X[:, idx]
        valid_mask &= col >= 0
        if np.issubdtype(col.dtype, np.floating):
            valid_mask &= ~np.isnan(col)

    n_filtered = int((~valid_mask).sum())
    return X[valid_mask], y[valid_mask], sources[valid_mask], n_filtered


def drop_features(X, feature_names):
    """Remove position_inferred and curr_finger from features."""
    keep_cols = [i for i, name in enumerate(feature_names)
                 if name not in DROP_FEATURES]
    X_clean = X[:, keep_cols]
    clean_names = [feature_names[i] for i in keep_cols]
    return X_clean, clean_names


def make_params(objective="multi:softmax"):
    return {
        "objective": objective,
        "num_class": 5,
        "max_depth": 8,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "min_child_weight": 5,
        "eval_metric": "mlogloss",
        "tree_method": "hist",
        "device": "cuda",
        "seed": 42,
    }


def train_model(X_train, y_train, X_val, y_val, feature_names,
                num_boost_round=500, early_stopping_rounds=30):
    """Train XGBoost with early stopping, return (model, val_accuracy)."""
    dtrain = xgb.DMatrix(X_train, label=y_train, feature_names=feature_names)
    dval = xgb.DMatrix(X_val, label=y_val, feature_names=feature_names)

    model = xgb.train(
        make_params("multi:softmax"), dtrain,
        num_boost_round=num_boost_round,
        evals=[(dtrain, "train"), (dval, "val")],
        early_stopping_rounds=early_stopping_rounds,
        verbose_eval=0,
    )

    y_pred = model.predict(dval).astype(int)
    acc = accuracy_score(y_val, y_pred)
    return model, acc


def evaluate_holdout(model, X_test, y_test, feature_names):
    """Evaluate model on a holdout set, return (accuracy, classification_report_str)."""
    dtest = xgb.DMatrix(X_test, label=y_test, feature_names=feature_names)
    y_pred = model.predict(dtest).astype(int)
    acc = float(accuracy_score(y_test, y_pred))
    report = classification_report(
        y_test, y_pred,
        target_names=[FINGER_NAMES[i] for i in range(5)],
        zero_division=0,
    )
    return acc, report


def main():
    # ── Load ────────────────────────────────────────────────────────
    X_raw, y_raw, sources_raw, feature_names_raw = load_data()
    n_raw = X_raw.shape[0]

    # ── Filter invalid rows ─────────────────────────────────────────
    X_filt, y_filt, sources_filt, n_filtered = filter_invalid_rows(
        X_raw, y_raw, sources_raw, feature_names_raw
    )

    # ── Drop bad features ───────────────────────────────────────────
    X, feature_names = drop_features(X_filt, feature_names_raw)
    y = y_filt
    sources = sources_filt

    # ── Split by source ─────────────────────────────────────────────
    cc_mask = sources == 1
    gaps_mask = sources == 0

    X_cc, y_cc = X[cc_mask], y[cc_mask]
    X_gaps, y_gaps = X[gaps_mask], y[gaps_mask]

    # ── Experiment 1: ClassClef 80/20 split ─────────────────────────
    np.random.seed(42)
    indices = np.random.permutation(len(y_cc))
    split = int(0.8 * len(indices))
    train_idx, val_idx = indices[:split], indices[split:]

    X_train, y_train = X_cc[train_idx], y_cc[train_idx]
    X_val, y_val = X_cc[val_idx], y_cc[val_idx]

    model_cc, acc_cc = train_model(
        X_train, y_train, X_val, y_val, feature_names
    )

    # ── GAPS holdout ────────────────────────────────────────────────
    acc_gaps, gaps_report = evaluate_holdout(model_cc, X_gaps, y_gaps, feature_names)

    # ── Experiment 2: 5-fold CV on all data ─────────────────────────
    skf = StratifiedKFold(n_splits=5, shuffle=True, random_state=42)
    fold_accs = []
    for train_idx, val_idx in skf.split(X, y):
        _, acc = train_model(
            X[train_idx], y[train_idx],
            X[val_idx], y[val_idx],
            feature_names,
        )
        fold_accs.append(acc)

    cv_mean = float(np.mean(fold_accs))
    cv_std = float(np.std(fold_accs))

    # ── Final model: softprob on all data ───────────────────────────
    best_rounds = int(model_cc.best_iteration * 1.1)
    best_rounds = max(best_rounds, 100)

    dtrain_all = xgb.DMatrix(X, label=y, feature_names=feature_names)
    final_model = xgb.train(
        make_params("multi:softprob"), dtrain_all,
        num_boost_round=best_rounds,
        evals=[(dtrain_all, "train")],
        verbose_eval=0,
    )

    # ── Feature importance ──────────────────────────────────────────
    importance = final_model.get_score(importance_type="gain")
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)

    # ── Save model ──────────────────────────────────────────────────
    model_path = PHASE3_DIR / "xgb_transition_cost_v3.json"
    final_model.save_model(str(model_path))

    # ── v2 comparison ───────────────────────────────────────────────
    v2_report_path = PHASE3_DIR / "training_report_v2.json"
    v2_report = None
    if v2_report_path.exists():
        with open(v2_report_path) as f:
            v2_report = json.load(f)

    # ── Save training report ────────────────────────────────────────
    report = {
        "model_version": "v3",
        "changes_from_v2": [
            "rebuilt data with consistent string convention (0=high_E, 5=low_E)",
            "v2 had mixed conventions: GAPS=0-low_E, ClassClef=0-high_E",
            "same hyperparameters as v2 to isolate data quality impact",
        ],
        "raw_samples": int(n_raw),
        "filtered_rows": int(n_filtered),
        "training_samples": int(X.shape[0]),
        "n_features": len(feature_names),
        "feature_names": feature_names,
        "classclef_samples": int(X_cc.shape[0]),
        "gaps_samples": int(X_gaps.shape[0]),
        "classclef_accuracy": float(acc_cc),
        "gaps_holdout_accuracy": float(acc_gaps),
        "cv_5fold_mean": cv_mean,
        "cv_5fold_std": cv_std,
        "cv_fold_accs": [float(a) for a in fold_accs],
        "best_rounds": best_rounds,
        "feature_importance_top10": {
            name: float(score) for name, score in sorted_imp[:10]
        },
        "target_distribution": {
            str(i): int((y == i).sum()) for i in range(5)
        },
    }

    if v2_report:
        report["v2_comparison"] = {
            "classclef_accuracy": {"v2": v2_report["classclef_accuracy"], "v3": float(acc_cc)},
            "gaps_holdout_accuracy": {"v2": v2_report["gaps_holdout_accuracy"], "v3": float(acc_gaps)},
            "cv_5fold_mean": {"v2": v2_report["cv_5fold_mean"], "v3": cv_mean},
        }

    report_path = PHASE3_DIR / "training_report_v3.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2)

    # ── Summary ─────────────────────────────────────────────────────
    print("=== Transition Cost v3 ===")
    print(f"Samples: {n_raw} raw -> {n_filtered} filtered -> {X.shape[0]} used  |  Features: {len(feature_names)}")
    print(f"ClassClef: {X_cc.shape[0]}  |  GAPS: {X_gaps.shape[0]}")
    print(f"ClassClef val acc:  {acc_cc*100:.1f}%")
    print(f"GAPS holdout acc:   {acc_gaps*100:.1f}%")
    print(f"5-fold CV acc:      {cv_mean*100:.1f}% +/- {cv_std*100:.1f}%")
    print(f"Final model rounds: {best_rounds}")
    print(f"Top features: {', '.join(n for n, _ in sorted_imp[:5])}")
    print(f"Model saved: {model_path}")
    print(f"Report saved: {report_path}")

    if v2_report:
        print("\n--- v2 vs v3 ---")
        print(f"ClassClef val:   {v2_report['classclef_accuracy']*100:.1f}% -> {acc_cc*100:.1f}%")
        print(f"GAPS holdout:    {v2_report['gaps_holdout_accuracy']*100:.1f}% -> {acc_gaps*100:.1f}%")
        print(f"5-fold CV mean:  {v2_report['cv_5fold_mean']*100:.1f}% -> {cv_mean*100:.1f}%")

    print(f"\nGAPS holdout per-class:\n{gaps_report}")


if __name__ == "__main__":
    main()
