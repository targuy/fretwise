"""Build transition-pair features for Phase 3 XGBoost training.

Extracts (note_prev, note_curr) pairs from sequential fingering data
and engineers features suitable for transition-cost prediction.

Target: predict finger_curr given (note_prev, note_curr, finger_prev, context).
"""

import json

import numpy as np

from fretwise.dataset.config import PROCESSED_DIR

STANDARD_TUNING = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4 (low to high)


def note_features(note: dict, prefix: str) -> dict:
    """Extract features for a single note."""
    midi = note.get("midi") or 0
    string = note.get("string") or 0
    fret = note.get("fret") or 0
    finger = note.get("finger") or 0

    return {
        f"{prefix}_midi": midi,
        f"{prefix}_string": string,
        f"{prefix}_fret": fret,
        f"{prefix}_finger": finger,
        f"{prefix}_is_open": int(fret == 0),
        f"{prefix}_is_high_fret": int(fret >= 7),
        f"{prefix}_string_group": 0 if string <= 2 else 1,  # 0=treble (str 0-2: E4,B,G), 1=bass (str 3-5: D,A,E2)
    }


def transition_features(prev: dict, curr: dict) -> dict:
    """Compute features for a (prev, curr) note transition."""
    pf = note_features(prev, "prev")
    cf = note_features(curr, "curr")

    features = {**pf, **cf}

    # Interval features
    prev_midi = prev.get("midi") or 0
    curr_midi = curr.get("midi") or 0
    features["interval_semitones"] = curr_midi - prev_midi
    features["interval_abs"] = abs(curr_midi - prev_midi)
    features["interval_direction"] = int(np.sign(curr_midi - prev_midi))

    # Fret distance
    prev_fret = prev.get("fret") or 0
    curr_fret = curr.get("fret") or 0
    features["fret_distance"] = curr_fret - prev_fret
    features["fret_distance_abs"] = abs(curr_fret - prev_fret)

    # String distance
    prev_string = prev.get("string") or 0
    curr_string = curr.get("string") or 0
    features["string_distance"] = curr_string - prev_string
    features["string_distance_abs"] = abs(curr_string - prev_string)

    # Same string / same fret
    features["same_string"] = int(prev_string == curr_string)
    features["same_fret"] = int(prev_fret == curr_fret)

    # Position shift needed
    features["position_shift"] = int(abs(curr_fret - prev_fret) > 4)

    # Finger mechanics from prev
    prev_finger = prev.get("finger") or 0
    features["prev_finger_is_index"] = int(prev_finger == 1)
    features["prev_finger_is_pinky"] = int(prev_finger == 4)
    features["prev_finger_is_open"] = int(prev_finger == 0)

    # Source reliability flag
    features["position_inferred"] = int(prev.get("source") == "gaps" or curr.get("source") == "gaps")

    return features


def extract_transitions(pieces: list[dict]) -> list[dict]:
    """Extract all valid transition pairs from sequential data."""
    transitions = []

    for piece in pieces:
        seq = piece["sequence"]
        prev_note = None

        for note in seq:
            if note.get("is_chord", False):
                prev_note = None
                continue

            finger = note.get("finger")
            if finger is None:
                prev_note = None
                continue

            if prev_note is not None:
                feat = transition_features(prev_note, note)
                feat["target_finger"] = finger
                feat["piece_source"] = piece.get("source", "unknown")
                transitions.append(feat)

            prev_note = note

    return transitions


def main():
    input_path = PROCESSED_DIR / "sequential_fingering_training.json"
    print(f"Loading {input_path}...")
    with open(input_path, encoding="utf-8") as f:
        data = json.load(f)

    pieces = data["pieces"]
    print(f"Loaded {len(pieces)} pieces")

    # Split by source for analysis
    gaps_pieces = [p for p in pieces if p.get("source") == "gaps"]
    cc_pieces = [p for p in pieces if p.get("source") == "classclef"]
    print(f"  GAPS: {len(gaps_pieces)} pieces")
    print(f"  ClassClef: {len(cc_pieces)} pieces")

    # Extract transitions
    print("\nExtracting transition pairs...")
    all_trans = extract_transitions(pieces)
    print(f"Total transition pairs: {len(all_trans):,}")

    cc_trans = [t for t in all_trans if t["piece_source"] == "classclef"]
    gaps_trans = [t for t in all_trans if t["piece_source"] == "gaps"]
    print(f"  ClassClef transitions: {len(cc_trans):,}")
    print(f"  GAPS transitions: {len(gaps_trans):,}")

    # Convert to arrays
    feature_cols = [k for k in all_trans[0].keys()
                    if k not in ("target_finger", "piece_source")]
    feature_cols.sort()

    X = np.array([[t[c] for c in feature_cols] for t in all_trans], dtype=np.float32)
    y = np.array([t["target_finger"] for t in all_trans], dtype=np.int32)
    sources = np.array([1 if t["piece_source"] == "classclef" else 0 for t in all_trans])

    print(f"\nFeature matrix: {X.shape}")
    print("Target distribution:")
    for finger in range(5):
        count = (y == finger).sum()
        print(f"  Finger {finger}: {count:,} ({count/len(y)*100:.1f}%)")

    # Save
    out_dir = PROCESSED_DIR / "phase3"
    out_dir.mkdir(exist_ok=True)

    np.save(out_dir / "X_transitions.npy", X)
    np.save(out_dir / "y_transitions.npy", y)
    np.save(out_dir / "sources.npy", sources)

    # Save feature names
    with open(out_dir / "feature_names.json", "w") as f:
        json.dump(feature_cols, f, indent=2)

    # Save metadata
    meta = {
        "total_transitions": len(all_trans),
        "classclef_transitions": len(cc_trans),
        "gaps_transitions": len(gaps_trans),
        "n_features": len(feature_cols),
        "feature_names": feature_cols,
        "target_distribution": {str(finger): int((y == finger).sum()) for finger in range(5)},
    }
    with open(out_dir / "transition_meta.json", "w") as f:
        json.dump(meta, f, indent=2)

    print(f"\nSaved to {out_dir}/")
    print(f"  X_transitions.npy: {X.shape}")
    print(f"  y_transitions.npy: {y.shape}")
    print(f"  feature_names.json: {len(feature_cols)} features")

    # Feature summary
    print(f"\nFeatures ({len(feature_cols)}):")
    for i, name in enumerate(feature_cols):
        vals = X[:, i]
        print(f"  {name}: min={vals.min():.1f}, max={vals.max():.1f}, "
              f"mean={vals.mean():.2f}, std={vals.std():.2f}")


if __name__ == "__main__":
    main()
