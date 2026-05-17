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
from dataclasses import dataclass, field
from typing import Any, Sequence

__all__ = [
    "PlayerContext",
    "ChordNote",
    "PlayerCostModel",
    "ChordFingerClassifier",
    "FixedPlayerCost",
    "FixedChordFingerClassifier",
    "LearnedChordFingerClassifier",
    "extract_chord_features",
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

    Aligns with the feature spec shipped by GuitarDataSet (Phase 2 classifier).
    "below" / "above" refer to the **string-ascending** ordering of fretted
    notes (string 1 = high e first → string 6 = low E last). Open strings are
    counted via ``n_open`` but not present as ChordNote.

    Args:
        chord_notes: Fretted notes of the chord (fret > 0).
        n_open: Number of open strings sounding in the same chord.

    Returns:
        list of 24-element feature vectors, one per input note, in the same
        order as ``chord_notes``.
    """
    if not chord_notes:
        return []

    sorted_by_string = sorted(enumerate(chord_notes), key=lambda p: p[1].string)
    sorted_chord = [n for _, n in sorted_by_string]

    frets = [n.fret for n in sorted_chord]
    min_fret = min(frets)
    max_fret = max(frets)
    fret_span = max_fret - min_fret
    n_fretted = len(sorted_chord)
    n_played = n_fretted + n_open
    # is_barre: true at the chord level if any two notes share min_fret AND
    # at least one ChordNote has is_barre_candidate True.
    barre_active = (
        sum(1 for n in sorted_chord if n.fret == min_fret) >= 2
        and any(n.is_barre_candidate for n in sorted_chord if n.fret == min_fret)
    )
    is_barre = 1.0 if barre_active else 0.0

    # ctx_fret_0..5: relative_fret per string slot 1..6, padded with -1.
    ctx_relative = [-1.0] * 6
    for n in sorted_chord:
        if 1 <= n.string <= 6:
            ctx_relative[n.string - 1] = float(n.fret - min_fret)

    feature_vectors: list[list[float]] = [[0.0] * 24 for _ in chord_notes]

    for sorted_idx, note in enumerate(sorted_chord):
        orig_idx = sorted_by_string[sorted_idx][0]
        prev_note = sorted_chord[sorted_idx - 1] if sorted_idx > 0 else None
        next_note = sorted_chord[sorted_idx + 1] if sorted_idx < n_fretted - 1 else None

        gap_below = float(note.fret - prev_note.fret) if prev_note is not None else -1.0
        gap_above = float(next_note.fret - note.fret) if next_note is not None else -1.0
        string_gap_below = (
            float(note.string - prev_note.string) if prev_note is not None else -1.0
        )
        string_gap_above = (
            float(next_note.string - note.string) if next_note is not None else -1.0
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
