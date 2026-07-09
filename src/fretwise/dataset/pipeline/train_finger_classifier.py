"""Train a chord finger classifier using gradient boosting and neural nets.

Per-note classification: for each fretted note in a chord, predict which
finger (INDEX=1, MIDDLE=2, RING=3, PINKY=4) should be used.

Uses the 4090 GPU for the neural net variant.

Usage:
    python scripts/train_finger_classifier.py
    python scripts/train_finger_classifier.py --model xgboost
    python scripts/train_finger_classifier.py --model neural
    python scripts/train_finger_classifier.py --model both
"""
import argparse
import json
import logging
import time

import numpy as np

from fretwise.dataset.config import PROCESSED_DIR

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def load_dataset():
    """Load chord dataset and splits."""
    with open(PROCESSED_DIR / "chord_dataset.json", encoding="utf-8") as f:
        chords = json.load(f)
    with open(PROCESSED_DIR / "splits.json", encoding="utf-8") as f:
        splits = json.load(f)
    return chords, splits


def chord_to_samples(chord, chord_idx):
    """Convert a chord to per-note training samples.

    Each fretted note becomes one sample with:
    - Features: note context + chord context
    - Label: finger (1=INDEX, 2=MIDDLE, 3=RING, 4=PINKY)
    """
    strings = chord["strings"]
    fingers = chord["fingers"]

    fretted_notes = []
    for i in range(6):
        if strings[i] is not None and strings[i] > 0 and fingers[i] is not None and fingers[i] > 0:
            fretted_notes.append((i, strings[i], fingers[i]))

    if len(fretted_notes) < 1:
        return [], []

    fretted_frets = [f for _, f, _ in fretted_notes]
    min_fret = min(fretted_frets)
    max_fret = max(fretted_frets)
    fret_span = max_fret - min_fret

    num_played = sum(1 for s in strings if s is not None)
    num_fretted = len(fretted_notes)
    num_open = sum(1 for s in strings if s == 0)
    has_barre = chord.get("is_barre", False)

    samples = []
    labels = []

    for note_idx, (string_idx, fret, finger) in enumerate(fretted_notes):
        # Note-specific features
        relative_fret = fret - min_fret
        string_num = 6 - string_idx  # 6=low E, 1=high E
        position_in_chord = note_idx / max(num_fretted - 1, 1)  # 0..1

        # Neighboring notes context
        fret_below = fretted_notes[note_idx - 1][1] if note_idx > 0 else -1
        fret_above = fretted_notes[note_idx + 1][1] if note_idx < len(fretted_notes) - 1 else -1
        gap_below = fret - fret_below if fret_below >= 0 else -1
        gap_above = fret_above - fret if fret_above >= 0 else -1

        # How many fretted notes below/above this one (on lower/higher strings)
        notes_below = note_idx
        notes_above = num_fretted - note_idx - 1

        # String gaps (how many strings between this and neighbors)
        string_gap_below = (string_idx - fretted_notes[note_idx - 1][0]) if note_idx > 0 else 0
        string_gap_above = (fretted_notes[note_idx + 1][0] - string_idx) if note_idx < len(fretted_notes) - 1 else 0

        # All fretted positions as context (padded to 6)
        all_frets_padded = [-1] * 6
        for j, (si, sf, _) in enumerate(fretted_notes[:6]):
            all_frets_padded[j] = sf - min_fret  # relative

        features = [
            # Note-level (7 features)
            string_num,
            fret,
            relative_fret,
            position_in_chord,
            gap_below,
            gap_above,
            notes_below,
            # Chord-level (7 features)
            num_played,
            num_fretted,
            num_open,
            fret_span,
            min_fret,
            max_fret,
            int(has_barre),
            # Neighbor context (4 features)
            notes_above,
            string_gap_below,
            string_gap_above,
            fret_below if fret_below >= 0 else 0,
            # All positions context (6 features)
            *all_frets_padded,
        ]

        samples.append(features)
        labels.append(finger)

    return samples, labels


FEATURE_NAMES = [
    "string_num", "fret", "relative_fret", "position_in_chord",
    "gap_below", "gap_above", "notes_below",
    "num_played", "num_fretted", "num_open", "fret_span",
    "min_fret", "max_fret", "is_barre",
    "notes_above", "string_gap_below", "string_gap_above", "fret_below_val",
    "ctx_fret_0", "ctx_fret_1", "ctx_fret_2", "ctx_fret_3", "ctx_fret_4", "ctx_fret_5",
]


def build_arrays(chords, indices):
    """Build feature/label arrays from chord indices."""
    all_X = []
    all_y = []
    for idx in indices:
        chord = chords[idx]
        samples, labels = chord_to_samples(chord, idx)
        all_X.extend(samples)
        all_y.extend(labels)
    return np.array(all_X, dtype=np.float32), np.array(all_y, dtype=np.int64)


def train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test):
    """Train XGBoost classifier."""
    try:
        import xgboost as xgb
    except ImportError:
        logger.error("XGBoost not installed. Run: pip install xgboost")
        return None

    logger.info("Training XGBoost classifier...")
    logger.info(f"  Train: {len(X_train)} samples, Val: {len(X_val)}, Test: {len(X_test)}")

    # Labels are 1-4, XGBoost needs 0-based
    y_train_0 = y_train - 1
    y_val_0 = y_val - 1
    y_test_0 = y_test - 1

    dtrain = xgb.DMatrix(X_train, label=y_train_0, feature_names=FEATURE_NAMES)
    dval = xgb.DMatrix(X_val, label=y_val_0, feature_names=FEATURE_NAMES)
    dtest = xgb.DMatrix(X_test, label=y_test_0, feature_names=FEATURE_NAMES)

    params = {
        "objective": "multi:softmax",
        "num_class": 4,
        "max_depth": 8,
        "learning_rate": 0.1,
        "subsample": 0.8,
        "colsample_bytree": 0.8,
        "tree_method": "gpu_hist",
        "device": "cuda",
        "eval_metric": "mlogloss",
        "seed": 42,
    }

    t0 = time.time()
    try:
        model = xgb.train(
            params, dtrain,
            num_boost_round=500,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=30,
            verbose_eval=50,
        )
    except xgb.core.XGBoostError:
        # Fall back to CPU if GPU fails
        logger.warning("GPU training failed, falling back to CPU...")
        params["tree_method"] = "hist"
        params.pop("device", None)
        model = xgb.train(
            params, dtrain,
            num_boost_round=500,
            evals=[(dtrain, "train"), (dval, "val")],
            early_stopping_rounds=30,
            verbose_eval=50,
        )

    train_time = time.time() - t0

    # Evaluate
    pred_val = model.predict(dval).astype(int) + 1
    pred_test = model.predict(dtest).astype(int) + 1

    val_acc = (pred_val == y_val).mean()
    test_acc = (pred_test == y_test).mean()

    # Per-finger accuracy
    print(f"\n{'='*60}")
    print(f"XGBoost Results (trained in {train_time:.1f}s)")
    print(f"{'='*60}")
    print(f"Validation accuracy: {val_acc:.4f} ({(pred_val == y_val).sum()}/{len(y_val)})")
    print(f"Test accuracy:       {test_acc:.4f} ({(pred_test == y_test).sum()}/{len(y_test)})")

    finger_names = {1: "INDEX", 2: "MIDDLE", 3: "RING", 4: "PINKY"}
    print("\nPer-finger test accuracy:")
    for f in [1, 2, 3, 4]:
        mask = y_test == f
        if mask.sum() > 0:
            acc = (pred_test[mask] == f).mean()
            print(f"  {finger_names[f]:8s}: {acc:.4f} ({(pred_test[mask] == f).sum()}/{mask.sum()})")

    # Confusion matrix
    print("\nConfusion matrix (test set):")
    header = "GT\\Pred"
    print(f"  {header:10s} {'INDEX':>8s} {'MIDDLE':>8s} {'RING':>8s} {'PINKY':>8s}")
    for gt in [1, 2, 3, 4]:
        row = []
        for pred in [1, 2, 3, 4]:
            count = ((y_test == gt) & (pred_test == pred)).sum()
            row.append(count)
        print(f"  {finger_names[gt]:10s} {row[0]:8d} {row[1]:8d} {row[2]:8d} {row[3]:8d}")

    # Feature importance
    importance = model.get_score(importance_type="gain")
    sorted_imp = sorted(importance.items(), key=lambda x: x[1], reverse=True)
    print("\nTop 10 features by gain:")
    for fname, gain in sorted_imp[:10]:
        print(f"  {fname:25s} {gain:.1f}")

    # Save model
    model_path = PROCESSED_DIR / "xgboost_finger_classifier.json"
    model.save_model(str(model_path))
    logger.info(f"Model saved to {model_path}")

    return {
        "model": "xgboost",
        "val_accuracy": float(val_acc),
        "test_accuracy": float(test_acc),
        "train_time_s": train_time,
        "best_iteration": model.best_iteration,
        "n_features": len(FEATURE_NAMES),
    }


def train_neural(X_train, y_train, X_val, y_val, X_test, y_test):
    """Train a small neural net classifier with PyTorch."""
    try:
        import torch
        import torch.nn as nn
        from torch.utils.data import DataLoader, TensorDataset
    except ImportError:
        logger.error("PyTorch not installed. Run: pip install torch")
        return None

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    logger.info(f"Training Neural Net on {device}...")
    logger.info(f"  Train: {len(X_train)} samples, Val: {len(X_val)}, Test: {len(X_test)}")

    # Prepare data
    X_tr = torch.tensor(X_train, dtype=torch.float32)
    y_tr = torch.tensor(y_train - 1, dtype=torch.long)  # 0-based
    X_v = torch.tensor(X_val, dtype=torch.float32)
    y_v = torch.tensor(y_val - 1, dtype=torch.long)
    X_te = torch.tensor(X_test, dtype=torch.float32)

    train_ds = TensorDataset(X_tr, y_tr)
    train_loader = DataLoader(train_ds, batch_size=512, shuffle=True, pin_memory=True)

    # Model
    n_features = X_train.shape[1]

    class FingerNet(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(
                nn.Linear(n_features, 128),
                nn.ReLU(),
                nn.BatchNorm1d(128),
                nn.Dropout(0.2),
                nn.Linear(128, 64),
                nn.ReLU(),
                nn.BatchNorm1d(64),
                nn.Dropout(0.2),
                nn.Linear(64, 32),
                nn.ReLU(),
                nn.Linear(32, 4),
            )

        def forward(self, x):
            return self.net(x)

    model = FingerNet().to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-3, weight_decay=1e-4)
    scheduler = torch.optim.lr_scheduler.ReduceLROnPlateau(optimizer, patience=10, factor=0.5)
    criterion = nn.CrossEntropyLoss()

    best_val_acc = 0
    best_state = None
    patience = 20
    no_improve = 0

    t0 = time.time()
    for epoch in range(200):
        model.train()
        total_loss = 0
        for batch_X, batch_y in train_loader:
            batch_X, batch_y = batch_X.to(device), batch_y.to(device)
            optimizer.zero_grad()
            out = model(batch_X)
            loss = criterion(out, batch_y)
            loss.backward()
            optimizer.step()
            total_loss += loss.item()

        # Validate
        model.eval()
        with torch.no_grad():
            val_out = model(X_v.to(device))
            val_pred = val_out.argmax(dim=1).cpu()
            val_acc = (val_pred == y_v).float().mean().item()
            val_loss = criterion(val_out, y_v.to(device)).item()

        scheduler.step(val_loss)

        if val_acc > best_val_acc:
            best_val_acc = val_acc
            best_state = model.state_dict().copy()
            no_improve = 0
        else:
            no_improve += 1

        if (epoch + 1) % 20 == 0:
            print(f"  Epoch {epoch+1:3d}: loss={total_loss/len(train_loader):.4f}, val_acc={val_acc:.4f}")

        if no_improve >= patience:
            logger.info(f"Early stopping at epoch {epoch+1}")
            break

    train_time = time.time() - t0

    # Load best model and evaluate on test
    model.load_state_dict(best_state)
    model.eval()
    with torch.no_grad():
        test_out = model(X_te.to(device))
        test_pred = (test_out.argmax(dim=1).cpu() + 1).numpy()  # back to 1-based
        val_out = model(X_v.to(device))
        val_pred_final = (val_out.argmax(dim=1).cpu() + 1).numpy()

    val_acc_final = (val_pred_final == y_val).mean()
    test_acc = (test_pred == y_test).mean()

    finger_names = {1: "INDEX", 2: "MIDDLE", 3: "RING", 4: "PINKY"}
    print(f"\n{'='*60}")
    print(f"Neural Net Results (trained in {train_time:.1f}s on {device})")
    print(f"{'='*60}")
    print(f"Validation accuracy: {val_acc_final:.4f}")
    print(f"Test accuracy:       {test_acc:.4f} ({(test_pred == y_test).sum()}/{len(y_test)})")

    print("\nPer-finger test accuracy:")
    for f in [1, 2, 3, 4]:
        mask = y_test == f
        if mask.sum() > 0:
            acc = (test_pred[mask] == f).mean()
            print(f"  {finger_names[f]:8s}: {acc:.4f} ({(test_pred[mask] == f).sum()}/{mask.sum()})")

    # Confusion matrix
    header2 = "GT\\Pred"
    print("\nConfusion matrix (test set):")
    print(f"  {header2:10s} {'INDEX':>8s} {'MIDDLE':>8s} {'RING':>8s} {'PINKY':>8s}")
    for gt in [1, 2, 3, 4]:
        row = []
        for pred in [1, 2, 3, 4]:
            count = ((y_test == gt) & (test_pred == pred)).sum()
            row.append(count)
        print(f"  {finger_names[gt]:10s} {row[0]:8d} {row[1]:8d} {row[2]:8d} {row[3]:8d}")

    # Save model
    model_path = PROCESSED_DIR / "neural_finger_classifier.pt"
    torch.save(best_state, model_path)
    logger.info(f"Model saved to {model_path}")

    return {
        "model": "neural_net",
        "val_accuracy": float(val_acc_final),
        "test_accuracy": float(test_acc),
        "train_time_s": train_time,
        "device": str(device),
        "n_features": n_features,
        "architecture": "128-64-32-4 (BN+Dropout)",
    }


def main():
    parser = argparse.ArgumentParser(description="Train chord finger classifier")
    parser.add_argument("--model", choices=["xgboost", "neural", "both"], default="both")
    args = parser.parse_args()

    chords, splits = load_dataset()
    logger.info(f"Loaded {len(chords)} chords with splits: "
                f"train={len(splits['train'])}, val={len(splits['val'])}, test={len(splits['test'])}")

    # Build arrays
    logger.info("Building feature arrays...")
    X_train, y_train = build_arrays(chords, splits["train"])
    X_val, y_val = build_arrays(chords, splits["val"])
    X_test, y_test = build_arrays(chords, splits["test"])

    logger.info(f"Samples: train={len(X_train)}, val={len(X_val)}, test={len(X_test)}")
    logger.info(f"Features per sample: {X_train.shape[1]}")
    logger.info(f"Label distribution (train): "
                f"INDEX={sum(y_train==1)}, MIDDLE={sum(y_train==2)}, "
                f"RING={sum(y_train==3)}, PINKY={sum(y_train==4)}")

    results = []

    if args.model in ("xgboost", "both"):
        r = train_xgboost(X_train, y_train, X_val, y_val, X_test, y_test)
        if r:
            results.append(r)

    if args.model in ("neural", "both"):
        r = train_neural(X_train, y_train, X_val, y_val, X_test, y_test)
        if r:
            results.append(r)

    # Compare with FretWise baseline
    print(f"\n{'='*60}")
    print("Comparison with FretWise baseline")
    print(f"{'='*60}")
    print("FretWise Viterbi (finger-only): 80.9%")
    for r in results:
        print(f"{r['model']:15s} test accuracy:  {r['test_accuracy']:.1%}")

    # Save results
    results_path = PROCESSED_DIR / "ml_training_results.json"
    with open(results_path, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)
    logger.info(f"Results saved to {results_path}")


if __name__ == "__main__":
    main()
