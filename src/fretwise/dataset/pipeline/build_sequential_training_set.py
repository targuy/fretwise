"""Build a unified sequential fingering training set from GAPS + ClassClef.

Merges sequential note data from both sources into a single training format.
Each piece becomes a sequence of (pitch, string, fret, finger, timing) tuples.
"""

import json
from collections import Counter

from fretwise.dataset.config import PROCESSED_DIR

STANDARD_TUNING = [40, 45, 50, 55, 59, 64]  # E2 A2 D3 G3 B3 E4 (MIDI)


def midi_to_string_fret(midi: int, max_fret: int = 19) -> list[tuple[int, int]]:
    """Map MIDI pitch to possible (string, fret) positions on standard tuning.

    Returns list of (string_idx_0based, fret) sorted by preference.
    String index 0 = high E (string 1), 5 = low E (string 6).
    """
    positions = []
    for s_idx, open_midi in enumerate(STANDARD_TUNING):
        fret = midi - open_midi
        if 0 <= fret <= max_fret:
            # Invert so 0=high_E, 5=low_E (matches GPIF/FretWise convention)
            positions.append((5 - s_idx, fret))
    return positions


def process_gaps_piece(piece: dict) -> dict:
    """Convert a GAPS piece to unified training format."""
    notes = []
    for note in piece["sequence"]:
        midi = note["midi"]
        finger = note["finger"]

        # Map MIDI to best string/fret position
        positions = midi_to_string_fret(midi)
        if not positions:
            continue

        # Use lowest position (most common in classical guitar)
        string_idx, fret = positions[0]

        notes.append({
            "midi": midi,
            "string": string_idx,
            "fret": fret,
            "finger": finger,
            "measure": note["measure"],
            "is_chord": note["is_chord"],
            "source": "gaps",
        })

    return {
        "file": piece["file"],
        "source": "gaps",
        "notes_total": piece["notes_total"],
        "notes_fingered": len(notes),
        "sequence": notes,
    }


def process_classclef_piece(piece: dict) -> dict:
    """Convert a ClassClef piece to unified training format."""
    notes = []
    for note in piece["sequence"]:
        lf = note.get("left_finger")
        if lf is None:
            continue

        string = note.get("string")
        fret = note.get("fret")
        midi = note.get("midi")

        # ClassClef has explicit string/fret from GPIF
        if string is not None and fret is not None:
            # Upstream GPIF data uses 0 = low E, 5 = high E in this dataset.
            # Invert to our convention: 0 = high E, 5 = low E.
            string_idx = max(0, min(5, 5 - string))
        elif midi is not None:
            positions = midi_to_string_fret(midi)
            if not positions:
                continue
            string_idx, fret = positions[0]
        else:
            continue

        notes.append({
            "midi": midi,
            "string": string_idx,
            "fret": fret,
            "finger": lf,
            "measure": note.get("measure", 0),
            "is_chord": note.get("is_chord", False),
            "source": "classclef",
        })

    return {
        "file": piece["file"],
        "title": piece.get("title", ""),
        "source": "classclef",
        "notes_total": piece.get("total_sequence_notes", len(piece["sequence"])),
        "notes_fingered": len(notes),
        "sequence": notes,
    }


def compute_stats(pieces: list[dict]) -> dict:
    """Compute aggregate statistics."""
    total_notes = sum(p["notes_fingered"] for p in pieces)
    finger_dist = Counter()
    string_dist = Counter()
    fret_dist = Counter()
    transitions = Counter()

    for piece in pieces:
        seq = piece["sequence"]
        for note in seq:
            finger_dist[note["finger"]] += 1
            string_dist[note["string"]] += 1
            fret_dist[note["fret"]] += 1

        # Count finger transitions (non-chord notes only)
        prev_finger = None
        for note in seq:
            if note["is_chord"]:
                prev_finger = None
                continue
            if prev_finger is not None:
                transitions[(prev_finger, note["finger"])] += 1
            prev_finger = note["finger"]

    return {
        "total_pieces": len(pieces),
        "total_fingered_notes": total_notes,
        "finger_distribution": dict(sorted(finger_dist.items())),
        "string_distribution": dict(sorted(string_dist.items())),
        "fret_range": {"min": min(fret_dist.keys()), "max": max(fret_dist.keys())} if fret_dist else {},
        "top_transitions": {
            f"{k[0]}->{k[1]}": v for k, v in transitions.most_common(20)
        },
    }


def main():
    all_pieces = []

    # Load GAPS
    gaps_path = PROCESSED_DIR / "gaps_sequential_fingering.json"
    if gaps_path.exists():
        print("Loading GAPS data...")
        with open(gaps_path, encoding="utf-8") as f:
            gaps = json.load(f)
        for piece in gaps["pieces"]:
            converted = process_gaps_piece(piece)
            if converted["notes_fingered"] > 0:
                all_pieces.append(converted)
        print(f"  GAPS: {len(all_pieces)} pieces with fingering")

    # Load ClassClef
    cc_path = PROCESSED_DIR / "classclef_sequential_fingering.json"
    if cc_path.exists():
        print("Loading ClassClef data...")
        with open(cc_path, encoding="utf-8") as f:
            cc = json.load(f)
        cc_count = 0
        for piece in cc["pieces"]:
            converted = process_classclef_piece(piece)
            if converted["notes_fingered"] > 0:
                all_pieces.append(converted)
                cc_count += 1
        print(f"  ClassClef: {cc_count} pieces with fingering")

    print(f"\nTotal pieces with fingering: {len(all_pieces)}")

    # Filter to pieces with meaningful coverage
    min_notes = 10
    good_pieces = [p for p in all_pieces if p["notes_fingered"] >= min_notes]
    print(f"Pieces with >= {min_notes} fingered notes: {len(good_pieces)}")

    # Stats
    stats = compute_stats(good_pieces)
    print(f"\n{'='*60}")
    print("UNIFIED SEQUENTIAL TRAINING SET")
    print(f"{'='*60}")
    print(f"  Pieces: {stats['total_pieces']}")
    print(f"  Total fingered notes: {stats['total_fingered_notes']:,}")
    print("\n  Finger distribution:")
    finger_names = {0: "THUMB/OPEN", 1: "INDEX", 2: "MIDDLE", 3: "RING", 4: "PINKY"}
    for finger, count in stats["finger_distribution"].items():
        name = finger_names.get(finger, f"?{finger}")
        print(f"    {name}: {count:,} ({count/stats['total_fingered_notes']*100:.1f}%)")

    print(f"\n  Fret range: {stats['fret_range']}")
    print("\n  Top transitions:")
    for trans, count in list(stats["top_transitions"].items())[:10]:
        print(f"    {trans}: {count:,}")

    # By source
    gaps_pieces = [p for p in good_pieces if p["source"] == "gaps"]
    cc_pieces = [p for p in good_pieces if p["source"] == "classclef"]
    print("\n  By source:")
    print(f"    GAPS: {len(gaps_pieces)} pieces, "
          f"{sum(p['notes_fingered'] for p in gaps_pieces):,} notes")
    print(f"    ClassClef: {len(cc_pieces)} pieces, "
          f"{sum(p['notes_fingered'] for p in cc_pieces):,} notes")

    # Save
    output = {
        "description": "Unified sequential fingering training set (GAPS + ClassClef)",
        "stats": stats,
        "pieces": good_pieces,
    }
    out_path = PROCESSED_DIR / "sequential_fingering_training.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False)

    print(f"\n  Saved to: {out_path}")
    print(f"  File size: {out_path.stat().st_size / 1024 / 1024:.1f} MB")


if __name__ == "__main__":
    main()
