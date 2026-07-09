"""Feature extraction for guitar chord ML training.

Extracts per-note, chord-level, and inter-note features from a chord dict.
Accepts raw JSON dicts (not FingeredChord dataclass instances) so callers
don't need to reconstruct dataclasses.

String ordering convention: index 0 = low E (6th string), index 5 = high E (1st string).
Fret span is computed over *fretted* notes only (open strings excluded) since
only fretted notes constrain hand reach.
"""



def extract_chord_features(chord: dict) -> dict:
    """Extract ML features from a chord dict.

    Args:
        chord: dict with keys 'name', 'strings' (list of 6 int|None),
               'fingers' (list of 6 int|None), 'position' (int),
               'is_barre' (bool), 'source' (str).

    Returns:
        dict with three groups of features:
          - per_note_features: list of dicts, one per string (6 total)
          - chord_features: single dict of chord-level aggregates
          - inter_note_features: dict with fret_gaps and finger_density
    """
    strings = chord["strings"]
    fingers = chord["fingers"]
    position = chord.get("position", 0)
    is_barre = chord.get("is_barre", False)

    # --- Per-note features (one per string, index 0 = low E / 6th string) ---
    per_note = []
    fretted_frets = []
    num_open = 0
    num_muted = 0
    num_fretted = 0

    for i in range(6):
        fret = strings[i]
        finger = fingers[i] if fingers else None

        is_muted = fret is None
        is_open = fret == 0
        is_fretted = fret is not None and fret > 0

        if is_muted:
            num_muted += 1
        elif is_open:
            num_open += 1
        else:
            num_fretted += 1
            fretted_frets.append(fret)

        per_note.append({
            "string_num": 6 - i,      # 6=low E, 1=high E (standard guitar numbering)
            "string_index": i,         # 0-based index in the array
            "fret": fret,
            "finger": finger,
            "is_muted": is_muted,
            "is_open": is_open,
            "is_fretted": is_fretted,
        })

    # Compute relative frets (only meaningful for fretted notes)
    min_fret = min(fretted_frets) if fretted_frets else 0
    max_fret = max(fretted_frets) if fretted_frets else 0
    for note in per_note:
        if note["is_fretted"]:
            note["relative_fret"] = note["fret"] - min_fret
        else:
            note["relative_fret"] = None

    # --- Chord-level features ---
    num_notes = 6 - num_muted  # open + fretted
    fret_span = max_fret - min_fret if fretted_frets else 0

    chord_feats = {
        "num_notes": num_notes,
        "num_fretted": num_fretted,
        "num_open": num_open,
        "num_muted": num_muted,
        "fret_span": fret_span,
        "min_fret": min_fret,
        "max_fret": max_fret,
        "position": position,
        "is_barre": is_barre,
        "has_open_strings": num_open > 0,
    }

    # --- Inter-note features ---
    # Fret gaps between adjacent *played* strings (muted strings are skipped).
    # This means gaps are between physically-adjacent sounding notes, not all 6
    # physical string pairs. A chord like [None, 3, None, 2, None, None] has one
    # gap (|3-2|=1) rather than five gaps with missing values.
    played_frets = []
    for i in range(6):
        f = strings[i]
        if f is not None:
            played_frets.append(f)

    fret_gaps = []
    for i in range(1, len(played_frets)):
        fret_gaps.append(abs(played_frets[i] - played_frets[i - 1]))

    # Finger density: fretted_notes / (fret_span + 1).
    # Note: uses (fret_span + 1) rather than bare fret_span to avoid division by
    # zero when all fretted notes share the same fret (e.g., barre chords).
    # A single-fret barre with 6 fretted notes → density 6.0, not infinity.
    finger_density = num_fretted / (fret_span + 1) if fret_span >= 0 else 0.0

    inter_note = {
        "fret_gaps": fret_gaps,
        "max_fret_gap": max(fret_gaps) if fret_gaps else 0,
        "mean_fret_gap": sum(fret_gaps) / len(fret_gaps) if fret_gaps else 0.0,
        "finger_density": finger_density,
    }

    return {
        "per_note_features": per_note,
        "chord_features": chord_feats,
        "inter_note_features": inter_note,
    }


def extract_flat_features(chord: dict) -> dict:
    """Extract a flat feature vector suitable for tabular ML.

    Returns a single dict with all features at the top level, with
    per-note features prefixed by string position (s6_ through s1_).
    """
    features = extract_chord_features(chord)

    flat = {}

    # Per-note (prefixed by string number)
    for note in features["per_note_features"]:
        prefix = f"s{note['string_num']}_"
        flat[prefix + "fret"] = note["fret"]
        flat[prefix + "finger"] = note["finger"]
        flat[prefix + "is_muted"] = int(note["is_muted"])
        flat[prefix + "is_open"] = int(note["is_open"])
        flat[prefix + "is_fretted"] = int(note["is_fretted"])
        flat[prefix + "relative_fret"] = note["relative_fret"]

    # Chord-level
    for k, v in features["chord_features"].items():
        if isinstance(v, bool):
            flat[k] = int(v)
        else:
            flat[k] = v

    # Inter-note
    flat["max_fret_gap"] = features["inter_note_features"]["max_fret_gap"]
    flat["mean_fret_gap"] = features["inter_note_features"]["mean_fret_gap"]
    flat["finger_density"] = features["inter_note_features"]["finger_density"]

    return flat
