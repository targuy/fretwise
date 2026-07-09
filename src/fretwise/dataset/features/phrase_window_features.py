"""Phrase-window feature extraction for PhraseWindowFingeringModelV1.

Spec contract: FretWise ML Training Spec v2, Section 4.

Convention used internally (matches transition_cost_v3):
  - string_num: 0-based, 0=high_E, 5=low_E
  - finger: int (0=open, 1=index, 2=middle, 3=ring, 4=pinky)
  - hand_position / anchor: int fret number of the virtual index finger

The exporter is responsible for converting to the FretWise-facing 1-based
string convention when writing the _spec.json file.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence

STANDARD_TUNING_HIGH_TO_LOW = [64, 59, 55, 50, 45, 40]  # E4, B3, G3, D3, A2, E2

FINGER_OPEN = 0
FINGER_INDEX = 1
FINGER_MIDDLE = 2
FINGER_RING = 3
FINGER_PINKY = 4

FINGER_OFFSET = {
    FINGER_INDEX: 0,
    FINGER_MIDDLE: 1,
    FINGER_RING: 2,
    FINGER_PINKY: 3,
}


def candidate_anchors(notes: Sequence[dict], max_candidates: int = 4) -> list[int]:
    """Generate candidate anchor frets for a window.

    Strategy: every fretted note's fret minus an offset in {0, 1, 2, 3}
    yields a candidate anchor. Filter to {>=1, <=22} and dedupe.
    """
    fretted = [n.get("fret", 0) for n in notes if (n.get("fret") or 0) > 0]
    if not fretted:
        return [1]  # default for all-open windows
    cands = set()
    for f in fretted:
        for offset in range(4):
            cand = f - offset
            if 1 <= cand <= 22:
                cands.add(cand)
    sorted_cands = sorted(cands)
    if len(sorted_cands) > max_candidates:
        # keep the lowest, highest, and median
        n = len(sorted_cands)
        picks = {sorted_cands[0], sorted_cands[-1], sorted_cands[n // 2]}
        sorted_cands = sorted(picks)
    return sorted_cands or [1]


def is_repeated_position(notes: Sequence[dict], idx: int) -> int:
    """Whether note at idx repeats an earlier (string, fret) position in the window."""
    s = notes[idx].get("string")
    f = notes[idx].get("fret")
    for j in range(idx):
        if notes[j].get("string") == s and notes[j].get("fret") == f:
            return 1
    return 0


def per_note_features(
    notes: Sequence[dict],
    idx: int,
    candidate_anchor: int,
    window_min_fret: int,
) -> dict[str, float]:
    note = notes[idx]
    string = note.get("string") or 0
    fret = note.get("fret") or 0
    pitch = note.get("midi") or note.get("pitch") or 0
    duration = note.get("duration", 1.0)
    onset = note.get("onset", float(idx))
    window_start_onset = notes[0].get("onset", 0.0)

    same_string_prev = 0
    same_fret_prev = 0
    if idx > 0:
        prev = notes[idx - 1]
        same_string_prev = int(prev.get("string") == string)
        same_fret_prev = int((prev.get("fret") or 0) == fret)

    techniques = note.get("techniques") or []
    has_legato = int(any(t in ("hammer_on", "pull_off", "slide") for t in techniques))

    return {
        f"n{idx}_string": float(string),
        f"n{idx}_fret": float(fret),
        f"n{idx}_pitch": float(pitch),
        f"n{idx}_fret_rel_min": float(fret - window_min_fret),
        f"n{idx}_fret_rel_anchor": float(fret - candidate_anchor),
        f"n{idx}_is_open": float(fret == 0),
        f"n{idx}_onset_delta": float(onset - window_start_onset),
        f"n{idx}_duration": float(duration),
        f"n{idx}_is_repeated_pos": float(is_repeated_position(notes, idx)),
        f"n{idx}_same_string_as_prev": float(same_string_prev),
        f"n{idx}_same_fret_as_prev": float(same_fret_prev),
        f"n{idx}_has_legato": float(has_legato),
    }


def window_level_features(
    notes: Sequence[dict],
    candidate_anchor: int,
) -> dict[str, float]:
    fretted_frets = [n.get("fret", 0) for n in notes if (n.get("fret") or 0) > 0]
    min_fret = min(fretted_frets) if fretted_frets else 0
    max_fret = max(fretted_frets) if fretted_frets else 0
    fret_span = max_fret - min_fret
    strings = {n.get("string") for n in notes if n.get("string") is not None}
    string_span = (max(strings) - min(strings)) if strings else 0
    contains_open = int(any((n.get("fret") or 0) == 0 for n in notes))
    contains_chord = int(any(n.get("is_chord_member", False) for n in notes))

    # Anchor-role heuristics (these are PRIORS the model can override).
    natural_index_fret = candidate_anchor + FINGER_OFFSET[FINGER_INDEX]
    natural_middle_fret = candidate_anchor + FINGER_OFFSET[FINGER_MIDDLE]
    natural_ring_fret = candidate_anchor + FINGER_OFFSET[FINGER_RING]
    natural_pinky_fret = candidate_anchor + FINGER_OFFSET[FINGER_PINKY]

    has_index_fret = int(any((n.get("fret") or 0) == natural_index_fret for n in notes))
    has_middle_fret = int(any((n.get("fret") or 0) == natural_middle_fret for n in notes))
    has_ring_fret = int(any((n.get("fret") or 0) == natural_ring_fret for n in notes))
    has_pinky_fret = int(any((n.get("fret") or 0) == natural_pinky_fret for n in notes))

    pinky_without_lower = int(has_pinky_fret and not has_index_fret and not has_middle_fret)
    would_shift_if_no_pinky = int(
        has_pinky_fret and not (has_ring_fret or has_middle_fret or has_index_fret)
    )

    return {
        "win_num_notes": float(len(notes)),
        "win_min_fret": float(min_fret),
        "win_max_fret": float(max_fret),
        "win_fret_span": float(fret_span),
        "win_num_strings": float(len(strings)),
        "win_string_span": float(string_span),
        "win_contains_open": float(contains_open),
        "win_contains_chord": float(contains_chord),
        "win_candidate_anchor": float(candidate_anchor),
        "win_index_anchor_required": float(has_index_fret),
        "win_ring_natural_for_anchor_plus_2": float(has_ring_fret),
        "win_pinky_natural_for_anchor_plus_3": float(has_pinky_fret),
        "win_pinky_used_without_lower_anchor": float(pinky_without_lower),
        "win_would_shift_hand_if_no_pinky": float(would_shift_if_no_pinky),
    }


WINDOW_SIZE = 5
PAD_VALUE = -1.0

PER_NOTE_KEYS = (
    "string",
    "fret",
    "pitch",
    "fret_rel_min",
    "fret_rel_anchor",
    "is_open",
    "onset_delta",
    "duration",
    "is_repeated_pos",
    "same_string_as_prev",
    "same_fret_as_prev",
    "has_legato",
)


def per_note_pad_features(slot: int) -> dict[str, float]:
    """Pad features for missing slot in a short window."""
    return {f"n{slot}_{key}": PAD_VALUE for key in PER_NOTE_KEYS}


def build_window_feature_vector(
    notes: Sequence[dict],
    candidate_anchor: int,
    window_size: int = WINDOW_SIZE,
) -> dict[str, float]:
    """Build a flat dict of features for a (window, anchor) pair.

    Notes longer than `window_size` are truncated.
    Notes shorter than `window_size` are right-padded with PAD_VALUE.
    """
    notes = list(notes)[:window_size]
    fretted_frets = [n.get("fret", 0) for n in notes if (n.get("fret") or 0) > 0]
    window_min_fret = min(fretted_frets) if fretted_frets else 0

    feats: dict[str, float] = {}
    for slot in range(window_size):
        if slot < len(notes):
            feats.update(per_note_features(notes, slot, candidate_anchor, window_min_fret))
        else:
            feats.update(per_note_pad_features(slot))

    feats.update(window_level_features(notes, candidate_anchor))
    return feats


def feature_names(window_size: int = WINDOW_SIZE) -> list[str]:
    """Stable ordering of feature names for the given window size."""
    feats: list[str] = []
    for slot in range(window_size):
        for key in PER_NOTE_KEYS:
            feats.append(f"n{slot}_{key}")
    feats.extend(
        [
            "win_num_notes",
            "win_min_fret",
            "win_max_fret",
            "win_fret_span",
            "win_num_strings",
            "win_string_span",
            "win_contains_open",
            "win_contains_chord",
            "win_candidate_anchor",
            "win_index_anchor_required",
            "win_ring_natural_for_anchor_plus_2",
            "win_pinky_natural_for_anchor_plus_3",
            "win_pinky_used_without_lower_anchor",
            "win_would_shift_hand_if_no_pinky",
        ]
    )
    return feats


def iter_windows(
    sequence: Iterable[dict],
    window_size: int = WINDOW_SIZE,
    stride: int = 1,
) -> Iterable[list[dict]]:
    """Slide a window of `window_size` notes across the sequence."""
    notes = [n for n in sequence if not n.get("is_chord", False)]
    if len(notes) < window_size:
        return
    for start in range(0, len(notes) - window_size + 1, stride):
        yield notes[start : start + window_size]


__all__ = [
    "FINGER_OPEN",
    "FINGER_INDEX",
    "FINGER_MIDDLE",
    "FINGER_RING",
    "FINGER_PINKY",
    "FINGER_OFFSET",
    "WINDOW_SIZE",
    "PER_NOTE_KEYS",
    "build_window_feature_vector",
    "candidate_anchors",
    "feature_names",
    "iter_windows",
    "per_note_features",
    "window_level_features",
]
