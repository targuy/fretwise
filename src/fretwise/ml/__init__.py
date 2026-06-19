"""Pluggable ML cost interfaces (Phase 3 prep).

Defines the contract between FretWise scoring and a learned model produced
by GuitarDataSet's Phase 3 (neural cost) and Phase 2 (finger classifier).

Two distinct interfaces — reflects the two distinct integration points in
the pipeline:

  - ``PlayerCostModel``: injected into the Viterbi scoring as a replacement
    for the stub ``C_joueur`` (γ in the composite cost). Operates on
    transitions and emissions in melodic sequences.

  - ``ChordFingerClassifier``: called by a post-Viterbi resolver to assign
    fingers to chord notes. Replaces or augments the rule-based
    ``_natural_finger_assignment`` and related resolvers.

Both are abstract. Implementations may be:

  - ``Fixed*``: deterministic wrappers around current FretWise logic
    (baseline; useful for A/B testing).
  - ``Learned*``: ONNX-backed predictors (lazy onnxruntime import).

This module has **no production effect** until callers in
``fretwise.scoring`` and ``fretwise.pipeline`` opt in. See
``docs/handoff/MODEL_SPEC.md`` §4 for the integration plan.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from fretwise.ml.phrase_window import (
    LearnedPhraseWindowFingerer,
    NotePrediction,
    PhraseNote,
    SlotPrediction,
    WindowPrediction,
    apply_pinky_demotion,
    build_window_feature_vector,
    candidate_anchors,
    note_from_fretwise,
    phrase_window_feature_names,
    resolve_phrase_window_fingers,
)

__all__ = [
    "PlayerContext",
    "ChordNote",
    "PlayerCostModel",
    "ChordFingerClassifier",
    "FixedPlayerCost",
    "FixedChordFingerClassifier",
    "LearnedChordFingerClassifier",
    "LearnedPlayerCost",
    "extract_chord_features",
    "extract_transition_features",
    "validate_assignment",
    # Phrase-window fingering (GuitarDataSet phrase_window v2, production)
    "LearnedPhraseWindowFingerer",
    "PhraseNote",
    "SlotPrediction",
    "WindowPrediction",
    "NotePrediction",
    "phrase_window_feature_names",
    "candidate_anchors",
    "build_window_feature_vector",
    "note_from_fretwise",
    "apply_pinky_demotion",
    "resolve_phrase_window_fingers",
]


@dataclass(frozen=True)
class PlayerContext:
    """Local context passed alongside a note to ML cost models.

    Frozen so it can be hashed / cached. Optional fields default to None or
    sensible empty values so callers can construct partial contexts.

    Attributes:
        onset: Note onset in beats.
        duration: Note duration in beats.
        tempo: Local tempo BPM.
        articulation: Articulation name (e.g. "normal", "legato", "slide").
        techniques: All techniques flags as a list of strings (palm_muted,
            accent, vibrato, etc.). Empty list when none.
        voice_hint: Voice index (GP polyphony) or None.
        measure_index: 1-based measure number from source, or None.
        is_chord_member: True when this note shares its onset with at least
            one other note. False for monophonic notes.
        chord_size: Number of simultaneously sounding fretted notes
            including this one (1 if monophonic, ≥2 if member of chord).
        time_to_next_note: Beats until the next NoteEvent in the same
            voice, or None if last. Helps the model estimate transition
            urgency.
        previous_finger: Finger name played immediately before on the same
            string (or in the same voice), or None.
    """

    onset: float
    duration: float
    tempo: float
    articulation: str = "normal"
    techniques: tuple[str, ...] = ()
    voice_hint: int | None = None
    measure_index: int | None = None
    is_chord_member: bool = False
    chord_size: int = 1
    time_to_next_note: float | None = None
    previous_finger: str | None = None


@dataclass(frozen=True)
class ChordNote:
    """One note of a simultaneously sounding chord.

    Used by ``ChordFingerClassifier.predict_fingers`` as input.

    Attributes:
        string: Guitar string number 1–6 (1 = high e, 6 = low E).
        fret: Fret number 0–24 (0 = open, but open strings are typically
            excluded from chord-finger classification).
        pitch: MIDI pitch (redundant with string + fret in standard tuning,
            but kept for cross-validation).
        is_barre_candidate: True if this note shares its fret with at least
            one other chord note on an adjacent or near-adjacent string.
            The classifier uses this to decide between barre and distinct-
            finger assignments. Computed by the caller (typically the
            chord resolver) before invocation.
    """

    string: int
    fret: int
    pitch: int
    is_barre_candidate: bool = False


class PlayerCostModel(ABC):
    """Pluggable transition/emission cost for FretWise Viterbi scoring.

    Replaces the stub ``C_joueur`` (γ weight) in the composite cost. An
    implementation is responsible for both transition cost (s1 → s2) and
    emission cost (just s_i). Most learned models will produce non-zero
    transition cost and zero emission cost (matching the current Viterbi
    contract), but the interface supports both for flexibility.

    All cost values must be **non-negative**. Higher = worse (penalty).
    The injected ``γ`` weight scales the contribution into the composite.
    """

    @abstractmethod
    def transition_cost(
        self,
        prev_string: int,
        prev_fret: int,
        prev_finger: str,
        curr_string: int,
        curr_fret: int,
        curr_finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        """Cost of moving from previous state to the current state."""

    @abstractmethod
    def emission_cost(
        self,
        string: int,
        fret: int,
        finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        """Cost of producing the current state in isolation."""


class ChordFingerClassifier(ABC):
    """Pluggable finger assignment for resolved chords.

    Called by a post-Viterbi chord-finger resolver. Receives the chord's
    notes (already with string + fret + pitch + barre hint) and returns a
    list of finger names in the same order.

    The returned list MUST match the input length. Allowed finger names:
    ``"index"``, ``"middle"``, ``"ring"``, ``"pinky"`` (lowercase, matching
    ``Finger`` StrEnum values). Use ``"index"`` for barre notes — the
    resolver downstream handles barre collapse.
    """

    @abstractmethod
    def predict_fingers(
        self,
        chord_notes: Sequence[ChordNote],
        hand_position: int,
        context: PlayerContext,
    ) -> list[str]:
        """Predict finger names for chord_notes (same order as input)."""


class FixedPlayerCost(PlayerCostModel):
    """Zero-cost PlayerCostModel — neutral baseline.

    Returns 0.0 for both transition and emission. Used when no learned
    model is available so the composite cost reduces to α·C_méca + β·C_music
    (current default behaviour). Replace with ``LearnedPlayerCost`` once
    the trained ONNX model from GuitarDataSet Phase 3 is available.
    """

    def transition_cost(self, *args: Any, **kwargs: Any) -> float:
        return 0.0

    def emission_cost(self, *args: Any, **kwargs: Any) -> float:
        return 0.0


# ---------------------------------------------------------------------------
# Feature extraction for the learned chord finger classifier
# ---------------------------------------------------------------------------

# Feature ordering — must match GuitarDataSet's training pipeline exactly.
# See finger_classifier_spec.json (24 features).
_FEATURE_NAMES: tuple[str, ...] = (
    "string_num", "fret", "relative_fret", "position_in_chord",
    "gap_below", "gap_above", "notes_below", "num_played",
    "num_fretted", "num_open", "fret_span", "min_fret",
    "max_fret", "is_barre", "notes_above",
    "string_gap_below", "string_gap_above", "fret_below_val",
    "ctx_fret_0", "ctx_fret_1", "ctx_fret_2",
    "ctx_fret_3", "ctx_fret_4", "ctx_fret_5",
)
_FINGER_FROM_INDEX: tuple[str, ...] = ("index", "middle", "ring", "pinky")


def extract_chord_features(
    chord_notes: Sequence[ChordNote],
    n_open: int = 0,
) -> list[list[float]]:
    """Build the 24-feature vector for each fretted chord note.

    Aligns with the feature spec shipped by GuitarDataSet (Phase 2 classifier)
    and verified against ``GuitarDataset-feature-calibration.json``.

    Convention:
      - Fretted notes are sorted by ``string_idx`` ascending = ``string_num``
        descending = **low E (string 6) first, high e (string 1) last**.
      - ``position_in_chord``: 0.0 at the first (bassiest) fretted note,
        1.0 at the last (treble).
      - ``gap_below`` / ``gap_above``: signed fret delta to the preceding /
        following note in the sort order. -1 also marks "no neighbour".
      - ``string_gap_below`` / ``string_gap_above``: **absolute** string_num
        delta to the preceding / following note in the sort order.
      - ``ctx_fret_N``: relative_fret of the Nth fretted note in sort order
        (0-indexed), padded with -1 when fewer than 6 fretted notes.

    Args:
        chord_notes: Fretted notes of the chord (fret > 0).
        n_open: Number of open strings sounding in the same chord.

    Returns:
        list of 24-element feature vectors, one per input note, in the same
        order as ``chord_notes``.
    """
    if not chord_notes:
        return []

    sorted_by_string = sorted(
        enumerate(chord_notes), key=lambda p: p[1].string, reverse=True,
    )
    sorted_chord = [n for _, n in sorted_by_string]

    frets = [n.fret for n in sorted_chord]
    min_fret = min(frets)
    max_fret = max(frets)
    fret_span = max_fret - min_fret
    n_fretted = len(sorted_chord)
    n_played = n_fretted + n_open
    barre_active = (
        sum(1 for n in sorted_chord if n.fret == min_fret) >= 2
        and any(n.is_barre_candidate for n in sorted_chord if n.fret == min_fret)
    )
    is_barre = 1.0 if barre_active else 0.0

    # ctx_fret_N: relative_fret of the Nth fretted note in sort order.
    ctx_relative = [-1.0] * 6
    for i, n in enumerate(sorted_chord[:6]):
        ctx_relative[i] = float(n.fret - min_fret)

    feature_vectors: list[list[float]] = [[0.0] * 24 for _ in chord_notes]

    for sorted_idx, note in enumerate(sorted_chord):
        orig_idx = sorted_by_string[sorted_idx][0]
        prev_note = sorted_chord[sorted_idx - 1] if sorted_idx > 0 else None
        next_note = sorted_chord[sorted_idx + 1] if sorted_idx < n_fretted - 1 else None

        gap_below = float(note.fret - prev_note.fret) if prev_note is not None else -1.0
        gap_above = float(next_note.fret - note.fret) if next_note is not None else -1.0
        # string_gap is absolute (sort order across-strings step magnitude).
        string_gap_below = (
            float(abs(note.string - prev_note.string)) if prev_note is not None else 0.0
        )
        string_gap_above = (
            float(abs(next_note.string - note.string)) if next_note is not None else 0.0
        )
        fret_below_val = float(prev_note.fret) if prev_note is not None else 0.0

        position_in_chord = (
            sorted_idx / (n_fretted - 1) if n_fretted > 1 else 0.0
        )

        feature_vectors[orig_idx] = [
            float(note.string),
            float(note.fret),
            float(note.fret - min_fret),
            float(position_in_chord),
            gap_below,
            gap_above,
            float(sorted_idx),
            float(n_played),
            float(n_fretted),
            float(n_open),
            float(fret_span),
            float(min_fret),
            float(max_fret),
            is_barre,
            float(n_fretted - 1 - sorted_idx),
            string_gap_below,
            string_gap_above,
            fret_below_val,
            *ctx_relative,
        ]

    return feature_vectors


def validate_assignment(
    strings: list[int | None],
    fingers: list[int | None],
) -> dict:
    """Physical playability sanity check on a per-string finger assignment.

    Mirrored from GuitarDataSet's ``validate_assignment.py`` (delivered in
    GuitarDataset-008-handoff.md). Identical semantics — kept in sync. Used
    as a post-Phase 2 sanity gate in ``resolve_chord_learned_fingers``: when
    the learned classifier emits an assignment that fails validation, the
    resolver falls back to the rule-based output.

    Args:
        strings: 6-element list (index 0 = low E = FretWise string_num 6).
            ``None`` = muted, ``0`` = open, ``>0`` = fretted.
        fingers: 6-element list. ``1`` = INDEX, ``2`` = MIDDLE, ``3`` = RING,
            ``4`` = PINKY. ``None`` for non-fretted positions.

    Returns:
        ``{"valid": bool, "violations": list[str]}``.
    """
    violations: list[str] = []
    finger_names = ["INDEX", "MIDDLE", "RING", "PINKY"]

    fretted: list[tuple[int, int, int]] = []
    for i in range(6):
        if strings[i] is not None and strings[i] > 0 and fingers[i] is not None:
            fretted.append((i, strings[i], fingers[i]))

    if not fretted:
        return {"valid": True, "violations": []}

    # Check 1: a finger can only press multiple frets if INDEX with span <= 1
    # (partial barre tolerance).
    finger_frets: dict[int, set[int]] = {}
    for _, fret, finger in fretted:
        finger_frets.setdefault(finger, set()).add(fret)
    for finger, frets in finger_frets.items():
        if len(frets) <= 1:
            continue
        sorted_frets = sorted(frets)
        if finger == 1 and sorted_frets[-1] - sorted_frets[0] <= 1:
            continue
        violations.append(
            f"{finger_names[finger-1]} assigned to multiple frets: {sorted_frets}"
        )

    # Check 2: ordering — fingers should be monotone with fret position,
    # allowing 1-fret inversions (common in barre + extension shapes).
    sorted_by_fret = sorted(fretted, key=lambda x: (x[1], x[0]))
    for i in range(len(sorted_by_fret) - 1):
        _, fret_a, finger_a = sorted_by_fret[i]
        _, fret_b, finger_b = sorted_by_fret[i + 1]
        if fret_a < fret_b and finger_a > finger_b:
            fret_gap = fret_b - fret_a
            if fret_gap <= 1:
                continue
            violations.append(
                f"Ordering violation: {finger_names[finger_a-1]} at fret {fret_a} "
                f"> {finger_names[finger_b-1]} at fret {fret_b}"
            )

    # Check 3: INDEX-PINKY stretch <= 5 frets.
    finger_min_max: dict[int, tuple[int, int]] = {}
    for _, fret, finger in fretted:
        existing = finger_min_max.get(finger)
        if existing is None:
            finger_min_max[finger] = (fret, fret)
        else:
            finger_min_max[finger] = (min(existing[0], fret), max(existing[1], fret))

    if 1 in finger_min_max and 4 in finger_min_max:
        index_max = finger_min_max[1][1]
        pinky_min = finger_min_max[4][0]
        span = pinky_min - index_max
        if span > 5:
            violations.append(f"Extreme stretch: {span} frets between INDEX and PINKY")

    return {"valid": len(violations) == 0, "violations": violations}


class LearnedChordFingerClassifier(ChordFingerClassifier):
    """ONNX-backed chord finger classifier (GuitarDataSet Phase 2).

    Loads the ONNX model and the feature spec at construction. ``onnxruntime``
    is imported lazily so callers that don't activate the learned classifier
    don't pay the dependency cost.

    Args:
        model_path: Path to the .onnx file.
        spec_path: Path to the spec JSON (verified at load time).

    Raises:
        ImportError: If ``onnxruntime`` is not installed.
        FileNotFoundError: If model_path does not exist.
    """

    def __init__(self, model_path: str, spec_path: str | None = None) -> None:
        try:
            import onnxruntime as ort  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "onnxruntime is required for LearnedChordFingerClassifier. "
                "Install it via 'pip install onnxruntime'."
            ) from exc

        import json
        from pathlib import Path as _P

        model_p = _P(model_path)
        if not model_p.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")

        if spec_path:
            spec = json.loads(_P(spec_path).read_text(encoding="utf-8"))
            assert tuple(spec["feature_names"]) == _FEATURE_NAMES, (
                "Feature spec drift between FretWise and the trained model. "
                "Compare src/fretwise/ml/__init__.py _FEATURE_NAMES with "
                f"{spec_path}::feature_names."
            )

        import onnxruntime as ort
        self._session = ort.InferenceSession(str(model_p))
        self._input_name = self._session.get_inputs()[0].name

    def predict_fingers(
        self,
        chord_notes: Sequence[ChordNote],
        hand_position: int,
        context: PlayerContext,
    ) -> list[str]:
        if not chord_notes:
            return []
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ImportError("numpy required for ONNX inference") from exc

        features = extract_chord_features(chord_notes)
        x = np.asarray(features, dtype=np.float32)
        outputs = self._session.run(None, {self._input_name: x})
        # XGBoost ONNX exports usually return (labels, probabilities). Take labels.
        labels_raw = outputs[0]
        labels = labels_raw.tolist() if hasattr(labels_raw, "tolist") else list(labels_raw)
        # Handle (N,) or (N, 1) shapes
        result: list[str] = []
        for raw in labels:
            idx = int(raw[0]) if isinstance(raw, (list, tuple)) else int(raw)
            result.append(_FINGER_FROM_INDEX[idx])
        return result


class FixedChordFingerClassifier(ChordFingerClassifier):
    """Rule-based ChordFingerClassifier — current FretWise behaviour.

    Wraps ``fretwise.scoring._natural_finger_assignment`` to expose the
    current rule-based assignment through the classifier interface. Used
    as a baseline for A/B testing against learned models, or as a fallback
    when the learned classifier has low confidence.

    Note: this wrapper accepts ``ChordNote`` objects but only uses
    ``fret`` and the relative ordering. Open strings (``fret == 0``) must
    be excluded by the caller — this wrapper assumes only fretted notes.
    """

    def predict_fingers(
        self,
        chord_notes: Sequence[ChordNote],
        hand_position: int,
        context: PlayerContext,
    ) -> list[str]:
        # Import here to avoid circular dependency at module load.
        from fretwise.models import Finger
        from fretwise.scoring import _natural_finger_assignment

        if not chord_notes:
            return []

        sorted_with_idx = sorted(
            enumerate(chord_notes), key=lambda p: (p[1].fret, p[1].string),
        )
        sorted_frets = [n.fret for _, n in sorted_with_idx]
        fingers_sorted = _natural_finger_assignment(sorted_frets)

        if fingers_sorted is None:
            return [Finger.INDEX.value] * len(chord_notes)

        result: list[str] = [""] * len(chord_notes)
        for (orig_idx, _note), finger in zip(sorted_with_idx, fingers_sorted):
            result[orig_idx] = finger.value
        return result


# ---------------------------------------------------------------------------
# Phase 3 — Learned transition cost (GuitarDataSet v3 ONNX)
# ---------------------------------------------------------------------------

# Feature order matches GuitarDataSet's training set exactly.
# See data/models/transition_cost_v3_spec.json (26 features). v3 unifies the
# string convention to 0 = high E (v2's mixed ClassClef/GAPS convention was a
# bug; v2 is retired — GuitarDataSet-023).
# Convention note: model uses 0-indexed strings (0 = high E, 5 = low E),
# FW uses 1-indexed (1 = high E, 6 = low E). Conversion happens at the
# PlayerCostModel boundary; extract_transition_features expects model-side
# (0-indexed) string values to match the calibration JSON.
_PHASE3_FEATURE_NAMES: tuple[str, ...] = (
    "curr_fret", "curr_is_high_fret", "curr_is_open", "curr_midi",
    "curr_string", "curr_string_group",
    "fret_distance", "fret_distance_abs",
    "interval_abs", "interval_direction", "interval_semitones",
    "position_shift",
    "prev_finger", "prev_finger_is_index", "prev_finger_is_open",
    "prev_finger_is_pinky",
    "prev_fret", "prev_is_high_fret", "prev_is_open", "prev_midi",
    "prev_string", "prev_string_group",
    "same_fret", "same_string",
    "string_distance", "string_distance_abs",
)

# Model class index → finger name (output softmax has 5 classes).
_PHASE3_FINGER_FROM_INDEX: tuple[str, ...] = (
    "open", "index", "middle", "ring", "pinky",
)
_PHASE3_FINGER_TO_INDEX: dict[str, int] = {
    name: i for i, name in enumerate(_PHASE3_FINGER_FROM_INDEX)
}

# Standard tuning open-string MIDI pitches indexed by model string number
# (0 = high E, 5 = low E). Used to derive prev_midi / curr_midi when the
# caller passes only (string, fret) — matches FW's STANDARD_TUNING values.
_PHASE3_OPEN_STRING_MIDI: tuple[int, ...] = (64, 59, 55, 50, 45, 40)


def extract_transition_features(
    prev_string_model: int,
    prev_fret: int,
    prev_finger_model: int,
    curr_string_model: int,
    curr_fret: int,
    prev_midi: int | None = None,
    curr_midi: int | None = None,
) -> dict[str, float]:
    """Build the 26-feature dict for a single transition (prev → curr).

    Aligned with ``data/models/transition_cost_v3_spec.json`` and verified
    bit-for-bit against ``transition_cost_v3_calibration.json`` (3 cases).

    All inputs use the **model's 0-indexed string convention**:
    ``string=0`` is high E, ``string=5`` is low E. Callers operating in
    FretWise's 1-indexed convention (``string_num`` 1-6, with 1=high E)
    must subtract 1 before calling.

    MIDI is an explicit model input (not always derivable from string+fret
    when the source piece uses a non-standard tuning — calibration
    example 3 demonstrates this). When ``prev_midi`` / ``curr_midi`` are
    omitted, they default to ``STANDARD_TUNING[string] + fret``.

    Args:
        prev_string_model: 0-indexed string of the previous note (0..5).
        prev_fret: Fret of the previous note (0..24).
        prev_finger_model: Previous finger as model class index
            (0=open, 1=index, 2=middle, 3=ring, 4=pinky).
        curr_string_model: 0-indexed string of the current note (0..5).
        curr_fret: Fret of the current note (0..24).
        prev_midi: MIDI pitch of the previous note. Defaults to
            ``STANDARD_TUNING[prev_string_model] + prev_fret``.
        curr_midi: MIDI pitch of the current note. Defaults to
            ``STANDARD_TUNING[curr_string_model] + curr_fret``.

    Returns:
        Dict keyed by feature name, ordered by ``_PHASE3_FEATURE_NAMES``
        when iterated. Values are all ``float``.
    """
    if prev_midi is None:
        prev_midi = _PHASE3_OPEN_STRING_MIDI[prev_string_model] + prev_fret
    if curr_midi is None:
        curr_midi = _PHASE3_OPEN_STRING_MIDI[curr_string_model] + curr_fret

    fret_distance = curr_fret - prev_fret
    interval_semitones = curr_midi - prev_midi
    interval_abs = abs(interval_semitones)
    if interval_semitones > 0:
        interval_direction = 1.0
    elif interval_semitones < 0:
        interval_direction = -1.0
    else:
        interval_direction = 0.0

    # string_group: 0 if model_string <= 2 (treble: high E, B, G),
    # 1 if model_string >= 3 (bass: D, A, low E). Per spec v3.
    curr_string_group = 0.0 if curr_string_model <= 2 else 1.0
    prev_string_group = 0.0 if prev_string_model <= 2 else 1.0

    return {
        "curr_fret": float(curr_fret),
        "curr_is_high_fret": 1.0 if curr_fret >= 7 else 0.0,
        "curr_is_open": 1.0 if curr_fret == 0 else 0.0,
        "curr_midi": float(curr_midi),
        "curr_string": float(curr_string_model),
        "curr_string_group": curr_string_group,
        "fret_distance": float(fret_distance),
        "fret_distance_abs": float(abs(fret_distance)),
        "interval_abs": float(interval_abs),
        "interval_direction": interval_direction,
        "interval_semitones": float(interval_semitones),
        "position_shift": 1.0 if abs(fret_distance) > 4 else 0.0,
        "prev_finger": float(prev_finger_model),
        "prev_finger_is_index": 1.0 if prev_finger_model == 1 else 0.0,
        "prev_finger_is_open": 1.0 if prev_finger_model == 0 else 0.0,
        "prev_finger_is_pinky": 1.0 if prev_finger_model == 4 else 0.0,
        "prev_fret": float(prev_fret),
        "prev_is_high_fret": 1.0 if prev_fret >= 7 else 0.0,
        "prev_is_open": 1.0 if prev_fret == 0 else 0.0,
        "prev_midi": float(prev_midi),
        "prev_string": float(prev_string_model),
        "prev_string_group": prev_string_group,
        "same_fret": 1.0 if prev_fret == curr_fret else 0.0,
        "same_string": 1.0 if prev_string_model == curr_string_model else 0.0,
        "string_distance": float(curr_string_model - prev_string_model),
        "string_distance_abs": float(abs(curr_string_model - prev_string_model)),
    }


class LearnedPlayerCost(PlayerCostModel):
    """ONNX-backed transition cost (GuitarDataSet Phase 3 v3).

    Loads the XGBoost-derived ONNX model and returns Viterbi-compatible
    additive cost ``-log(p[curr_finger])`` for each transition. Emission
    cost is 0.0 — the v3 model is transition-only (no per-note emission).

    The 26 model features do not depend on tempo, articulation, techniques,
    chord membership, or any other ``PlayerContext`` field (spec v3
    ``context_fields_not_used``). The ``context`` argument is therefore
    accepted but ignored.

    Args:
        model_path: Path to the .onnx file (data/models/transition_cost_v3.onnx).
        spec_path: Optional path to the spec JSON; validated at load time
            for feature-name drift.

    Raises:
        ImportError: If ``onnxruntime`` is not installed.
        FileNotFoundError: If model_path does not exist.
    """

    def __init__(self, model_path: str, spec_path: str | None = None) -> None:
        try:
            import onnxruntime  # noqa: F401
        except ImportError as exc:  # pragma: no cover
            raise ImportError(
                "onnxruntime is required for LearnedPlayerCost. "
                "Install it via 'pip install onnxruntime' or "
                "'pip install fretwise[ml]'."
            ) from exc

        import json
        from pathlib import Path as _P

        model_p = _P(model_path)
        if not model_p.exists():
            raise FileNotFoundError(f"ONNX model not found: {model_path}")

        if spec_path:
            spec = json.loads(_P(spec_path).read_text(encoding="utf-8"))
            assert tuple(spec["feature_names"]) == _PHASE3_FEATURE_NAMES, (
                "Phase 3 feature spec drift between FretWise and the trained "
                "model. Compare src/fretwise/ml/__init__.py "
                f"_PHASE3_FEATURE_NAMES with {spec_path}::feature_names."
            )

        import onnxruntime as ort
        self._session = ort.InferenceSession(str(model_p))
        self._input_name = self._session.get_inputs()[0].name
        # Output 0 = labels (int64), output 1 = probabilities (float32[N, 5]).
        # We always want probabilities for cost computation.
        self._prob_output_name = self._session.get_outputs()[1].name

    def _predict_probs(
        self,
        prev_string_model: int,
        prev_fret: int,
        prev_finger_model: int,
        curr_string_model: int,
        curr_fret: int,
        prev_midi: int | None = None,
        curr_midi: int | None = None,
    ) -> list[float]:
        """Run ONNX inference for a single transition; return 5 probabilities.

        MIDI overrides are forwarded to ``extract_transition_features`` — use
        them when a non-standard tuning means the standard-tuning derivation
        would yield wrong pitches.
        """
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ImportError("numpy required for ONNX inference") from exc

        features = extract_transition_features(
            prev_string_model=prev_string_model,
            prev_fret=prev_fret,
            prev_finger_model=prev_finger_model,
            curr_string_model=curr_string_model,
            curr_fret=curr_fret,
            prev_midi=prev_midi,
            curr_midi=curr_midi,
        )
        row = np.asarray(
            [[features[name] for name in _PHASE3_FEATURE_NAMES]],
            dtype=np.float32,
        )
        outputs = self._session.run(
            [self._prob_output_name], {self._input_name: row},
        )
        probs = outputs[0][0]
        return [float(p) for p in probs]

    def _predict_probs_batch(
        self,
        transitions: Sequence[tuple[int, int, int, int, int]],
    ) -> list[list[float]]:
        """Batch inference: one ONNX call for N transitions.

        Each entry in ``transitions`` is the 5-tuple
        ``(prev_string_model, prev_fret, prev_finger_model,
          curr_string_model, curr_fret)``. Standard-tuning MIDI is derived
        internally; callers that need non-standard tuning should use the
        single-row ``_predict_probs`` path.

        Returns one ``[p_open, p_index, p_middle, p_ring, p_pinky]`` row per
        input, in the same order. Empty input → empty list (no ONNX call).
        """
        if not transitions:
            return []
        try:
            import numpy as np
        except ImportError as exc:  # pragma: no cover
            raise ImportError("numpy required for ONNX inference") from exc

        rows: list[list[float]] = []
        for ps, pf, pfin, cs, cf in transitions:
            features = extract_transition_features(
                prev_string_model=ps, prev_fret=pf, prev_finger_model=pfin,
                curr_string_model=cs, curr_fret=cf,
            )
            rows.append([features[name] for name in _PHASE3_FEATURE_NAMES])
        x = np.asarray(rows, dtype=np.float32)
        outputs = self._session.run(
            [self._prob_output_name], {self._input_name: x},
        )
        probs_matrix = outputs[0]
        return [[float(p) for p in row] for row in probs_matrix]

    def transition_cost(
        self,
        prev_string: int,
        prev_fret: int,
        prev_finger: str,
        curr_string: int,
        curr_fret: int,
        curr_finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        """Viterbi-additive cost: ``-log(p[curr_finger])``.

        FW conventions (1-indexed strings, finger string enum) are
        converted to model conventions (0-indexed strings, integer
        finger class) at the boundary.
        """
        import math

        prev_finger_idx = _PHASE3_FINGER_TO_INDEX.get(prev_finger, 0)
        curr_finger_idx = _PHASE3_FINGER_TO_INDEX.get(curr_finger, 0)
        probs = self._predict_probs(
            prev_string_model=prev_string - 1,
            prev_fret=prev_fret,
            prev_finger_model=prev_finger_idx,
            curr_string_model=curr_string - 1,
            curr_fret=curr_fret,
        )
        p = probs[curr_finger_idx]
        return -math.log(max(p, 1e-9))

    def emission_cost(
        self,
        string: int,
        fret: int,
        finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        return 0.0
