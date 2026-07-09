"""Build the PhraseWindowFingeringModelV1 training dataset.

Spec contract: FretWise ML Training Spec v2, Section 4.

Reads unified sequential fingering data and emits per-note feature vectors
that include their window context + a candidate anchor. The training target
is the ground-truth finger.

Each piece contributes (num_notes - WINDOW_SIZE + 1) windows; for each window
we expand into multiple training rows by enumerating candidate anchors.
For each anchor, we evaluate per-note targets and a per-window "anchor cost"
proxy (= 1 if the anchor matches the ground-truth `position_anchor`, else 0).
"""

import json

import numpy as np

from fretwise.dataset.config import PROCESSED_DIR
from fretwise.dataset.features.phrase_window_features import (
    WINDOW_SIZE,
    build_window_feature_vector,
    candidate_anchors,
    feature_names,
    iter_windows,
)

PHASE4_DIR = PROCESSED_DIR / "phase4"

FINGER_TO_INT = {
    None: 0,
    0: 0,
    "open": 0,
    "thumb": 0,
    1: 1,
    "index": 1,
    2: 2,
    "middle": 2,
    3: 3,
    "ring": 3,
    4: 4,
    "pinky": 4,
}


def to_finger_int(value) -> int | None:
    if value is None:
        return None
    return FINGER_TO_INT.get(value, None)


def infer_window_anchor(window: list[dict]) -> int:
    """Heuristic ground-truth anchor: fret of the lowest INDEX note in the window.

    Falls back to (min_fret) when there is no index. Pinky never anchors.
    """
    index_frets = [
        n.get("fret", 0)
        for n in window
        if to_finger_int(n.get("finger")) == 1 and (n.get("fret") or 0) > 0
    ]
    if index_frets:
        return min(index_frets)
    fretted = [n.get("fret", 0) for n in window if (n.get("fret") or 0) > 0]
    return min(fretted) if fretted else 1


def main():
    PHASE4_DIR.mkdir(exist_ok=True, parents=True)

    input_path = PROCESSED_DIR / "sequential_fingering_training.json"
    print(f"Loading {input_path}...")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    pieces = data["pieces"]
    print(f"Loaded {len(pieces)} pieces")

    feat_names = feature_names(WINDOW_SIZE)
    n_feats = len(feat_names)

    rows_X: list[list[float]] = []
    rows_y: list[list[int]] = []  # per-note finger targets (length WINDOW_SIZE)
    rows_y_anchor: list[int] = []  # 1 if candidate_anchor == gt_anchor
    rows_source: list[int] = []  # 1=classclef, 0=gaps

    windows_total = 0
    skipped_no_finger = 0

    for piece in pieces:
        seq = piece["sequence"]
        source = piece.get("source", "unknown")
        source_int = 1 if source == "classclef" else 0

        for window in iter_windows(seq, WINDOW_SIZE, stride=1):
            fingers = [to_finger_int(n.get("finger")) for n in window]
            if any(f is None for f in fingers):
                skipped_no_finger += 1
                continue

            gt_anchor = infer_window_anchor(window)
            cands = candidate_anchors(window)
            if gt_anchor not in cands:
                cands = sorted(set(cands + [gt_anchor]))

            for cand in cands:
                feats = build_window_feature_vector(window, cand, WINDOW_SIZE)
                rows_X.append([feats[k] for k in feat_names])
                rows_y.append(fingers)
                rows_y_anchor.append(int(cand == gt_anchor))
                rows_source.append(source_int)
                windows_total += 1

    if not rows_X:
        print("ERROR: no rows produced.")
        return

    X = np.array(rows_X, dtype=np.float32)
    y_fingers = np.array(rows_y, dtype=np.int32)
    y_anchor = np.array(rows_y_anchor, dtype=np.int32)
    sources = np.array(rows_source, dtype=np.int32)

    print(f"\nTotal rows: {windows_total:,}")
    print(f"  Skipped (no finger): {skipped_no_finger:,}")
    print(f"  Feature dim: {n_feats}")
    print(f"  ClassClef rows: {(sources == 1).sum():,}")
    print(f"  GAPS rows: {(sources == 0).sum():,}")
    print(f"  Positive anchor rows (anchor matches gt): {y_anchor.sum():,}")
    print(f"  Negative anchor rows: {(y_anchor == 0).sum():,}")

    np.save(PHASE4_DIR / "X_phrase_window.npy", X)
    np.save(PHASE4_DIR / "y_fingers.npy", y_fingers)
    np.save(PHASE4_DIR / "y_anchor.npy", y_anchor)
    np.save(PHASE4_DIR / "sources.npy", sources)
    with open(PHASE4_DIR / "feature_names.json", "w") as f:
        json.dump(feat_names, f, indent=2)

    meta = {
        "schema_version": "fretwise-ml-v2",
        "window_size": WINDOW_SIZE,
        "total_rows": int(windows_total),
        "classclef_rows": int((sources == 1).sum()),
        "gaps_rows": int((sources == 0).sum()),
        "positive_anchor_rows": int(y_anchor.sum()),
        "negative_anchor_rows": int((y_anchor == 0).sum()),
        "feature_dim": n_feats,
        "feature_names": feat_names,
        "finger_distribution_per_slot": {
            f"slot_{i}": {str(f): int((y_fingers[:, i] == f).sum()) for f in range(5)}
            for i in range(WINDOW_SIZE)
        },
        "string_convention": "0=high_e (internal); FretWise spec exposes 1-based",
        "anchor_strategy": "ground-truth anchor = fret of lowest index-fingered note; falls back to min fret if no index in window",
    }
    with open(PHASE4_DIR / "phrase_window_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved to {PHASE4_DIR}/")


if __name__ == "__main__":
    main()
