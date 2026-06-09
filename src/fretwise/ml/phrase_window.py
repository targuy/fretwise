"""Phrase-window fingering predictor (GuitarDataSet ``phrase_window_v1``).

Successor to the note-by-note ``finger_classifier`` for **melodic** (non-chord)
fingering.  Instead of predicting one finger from a single isolated note, this
model decodes a sliding window of ``WINDOW_SIZE`` notes under a *candidate
anchor* (the fret covered by the index finger), using a bundle of six ONNX
heads: one finger classifier per window slot plus one binary anchor head.

Integration status — **shadow / dry-run only** (FretWise FW-015 decision):
predictions are computed and logged for comparison against the rule-based
pipeline, but are **never** applied to user output.  Golden per-note accuracy
(~0.51) and pinky over-use (~20 % FPR) are below the rule baseline, so the
model is not eligible for default activation.  See
``data/models/phrase_window_fingering_v1_metrics.json``.

Contract source of truth:
  - ``data/models/phrase_window_fingering_v1_spec.json`` (feature layout,
    inference protocol, candidate-anchor rule).
  - ``data/models/phrase_window_fingering_v1_calibration.json`` (binding:
    ``build_window_feature_vector`` reproduces every ``expected_features`` to
    1e-6, validated in ``tests/test_ml_phrase_window.py``).

String convention: this module is **internal 0-based** (``0 = high e``,
``5 = low E``), the same convention as ``transition_cost_v3``.  Callers holding
a FretWise ``NoteEvent.string_num`` (1-based, ``1 = high e``) must subtract 1 —
see :func:`note_from_fretwise`.
"""
from __future__ import annotations

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "WINDOW_SIZE",
    "PAD_VALUE",
    "PHRASE_FINGER_FROM_INDEX",
    "PHRASE_FINGER_TO_INDEX",
    "PhraseNote",
    "SlotPrediction",
    "WindowPrediction",
    "NotePrediction",
    "phrase_window_feature_names",
    "candidate_anchors",
    "build_window_feature_vector",
    "note_from_fretwise",
    "LearnedPhraseWindowFingerer",
]

WINDOW_SIZE = 5
PAD_VALUE = -1.0

# Output class order for every slot head and the model's finger indices.
PHRASE_FINGER_FROM_INDEX: tuple[str, ...] = ("open", "index", "middle", "ring", "pinky")
PHRASE_FINGER_TO_INDEX: dict[str, int] = {
    name: i for i, name in enumerate(PHRASE_FINGER_FROM_INDEX)
}

# Per-note slot feature keys (12), in the exact order the model was trained on.
# DO NOT reorder — the ONNX input is positional. Mirrors the spec
# ``feature_layout.per_note_slot_features``.
_PER_NOTE_KEYS: tuple[str, ...] = (
    "string", "fret", "pitch", "fret_rel_min", "fret_rel_anchor", "is_open",
    "onset_delta", "duration", "is_repeated_pos", "same_string_as_prev",
    "same_fret_as_prev", "has_legato",
)

# Window-level feature keys (14), exact order. Mirrors the spec
# ``feature_layout.window_level_features``.
_WINDOW_KEYS: tuple[str, ...] = (
    "win_num_notes", "win_min_fret", "win_max_fret", "win_fret_span",
    "win_num_strings", "win_string_span", "win_contains_open",
    "win_contains_chord", "win_candidate_anchor", "win_index_anchor_required",
    "win_ring_natural_for_anchor_plus_2", "win_pinky_natural_for_anchor_plus_3",
    "win_pinky_used_without_lower_anchor", "win_would_shift_hand_if_no_pinky",
)

_MIN_ANCHOR = 1
_MAX_ANCHOR = 22


@dataclass(frozen=True)
class PhraseNote:
    """One melodic note, in the model's internal 0-based string convention.

    Attributes:
        string: 0-based string index (``0 = high e``, ``5 = low E``).
        fret: Fret number (0 = open, 1..22 fretted).
        pitch: MIDI pitch (0..127).
        onset: Note onset in beats.
        duration: Note duration in beats.
        is_chord_member: True when the note shares its onset with at least one
            other note (sets the ``win_contains_chord`` window feature).
        has_legato: True when the note carries a hammer-on / pull-off / slide
            technique (sets ``n{slot}_has_legato``).
    """

    string: int
    fret: int
    pitch: int
    onset: float
    duration: float
    is_chord_member: bool = False
    has_legato: bool = False


@dataclass(frozen=True)
class SlotPrediction:
    """Decoded finger for one window slot."""

    finger: str
    probabilities: tuple[float, ...]  # len 5, order = PHRASE_FINGER_FROM_INDEX
    entropy: float


@dataclass(frozen=True)
class WindowPrediction:
    """Result of decoding one window under its selected anchor."""

    anchor: int
    anchor_probability: float
    slots: tuple[SlotPrediction, ...]  # one per real note (≤ WINDOW_SIZE)
    candidate_scores: tuple[tuple[int, float], ...]  # (anchor, selection_score)


@dataclass(frozen=True)
class NotePrediction:
    """Per-note prediction after overlap-averaging across windows (step 6)."""

    finger: str
    probabilities: tuple[float, ...]  # averaged softmax, len 5
    anchor: int                       # anchor of the most confident covering window
    entropy: float
    n_windows: int                    # how many windows voted for this note


def phrase_window_feature_names(window_size: int = WINDOW_SIZE) -> tuple[str, ...]:
    """Return the 74 feature names in the exact ONNX input order.

    Layout: ``window_size`` blocks of the 12 per-note slot keys
    (``n{slot}_<key>``) followed by the 14 window-level keys.

    Args:
        window_size: Number of slots (5 for v1).

    Returns:
        Tuple of feature names, length ``window_size * 12 + 14``.
    """
    names: list[str] = []
    for slot in range(window_size):
        for key in _PER_NOTE_KEYS:
            names.append(f"n{slot}_{key}")
    names.extend(_WINDOW_KEYS)
    return tuple(names)


def candidate_anchors(
    notes: Sequence[PhraseNote], max_candidates: int = 4,
) -> list[int]:
    """Generate candidate anchor frets for a window (spec step 2, rev2).

    For **every** fretted note in the window, the candidate set includes
    ``{fret, fret-1, fret-2, fret-3} ∩ [1, 22]`` (the index..pinky span that
    could place that note). The union over all fretted notes is deduplicated;
    if it exceeds ``max_candidates`` entries, it is reduced to exactly
    ``{lowest, highest, median}`` where ``median = sorted[n // 2]``.

    All-open windows default to anchor 1 (``all_open_default`` in the spec).

    Per GDS-024 (#52) — this is the union over all notes, **not** the
    ``{min..min-3}`` subset of the lowest note. Example: frets ``{7, 5}`` →
    union ``{2,3,4,5,6,7}`` → reduced to ``{2, 5, 7}``; frets ``{2,2,2,4,2}`` →
    ``{1, 2, 3, 4}`` (exactly 4, no reduction).

    Args:
        notes: Real (non-padding) notes of the window.
        max_candidates: Reduction threshold (4 for v1).

    Returns:
        Distinct candidate anchor frets, ascending.
    """
    fretted = {n.fret for n in notes if n.fret > 0}
    if not fretted:
        return [_MIN_ANCHOR]
    cands: set[int] = set()
    for fret in fretted:
        for offset in range(4):
            candidate = fret - offset
            if _MIN_ANCHOR <= candidate <= _MAX_ANCHOR:
                cands.add(candidate)
    ordered = sorted(cands)
    if len(ordered) > max_candidates:
        median = ordered[len(ordered) // 2]
        ordered = sorted({ordered[0], ordered[-1], median})
    return ordered


def build_window_feature_vector(
    notes: Sequence[PhraseNote],
    candidate_anchor: int,
    window_size: int = WINDOW_SIZE,
) -> dict[str, float]:
    """Build the 74-dim feature dict for one window under one candidate anchor.

    Validated bit-for-bit against every ``expected_features`` case in
    ``phrase_window_fingering_v1_calibration.json`` (1e-6).

    Empty slots (when ``len(notes) < window_size``) are right-padded with
    ``PAD_VALUE`` in every per-note feature. Window-level features are computed
    from the real notes only.

    The five anchor/finger window features use the authoritative ``has(k)``
    definitions from the GDS reference extractor (calibration rev2 / GDS-024),
    where ``has(k)`` means a fretted note sits exactly on fret ``anchor+k``.
    Validated against all seven rev2 calibration cases (incl. three synthetic
    witnesses that pin the pinky/index features at non-zero values).

    Args:
        notes: Real notes of the window, already ordered (melodic: by onset;
            chord: treble→bass), in the internal 0-based string convention.
        candidate_anchor: The anchor fret being scored.
        window_size: Number of slots (5 for v1).

    Returns:
        Dict keyed by :func:`phrase_window_feature_names`; values are floats.
    """
    fretted = [n.fret for n in notes if n.fret > 0]
    win_min = float(min(fretted)) if fretted else 0.0
    win_max = float(max(fretted)) if fretted else 0.0
    contains_chord = any(n.is_chord_member for n in notes)
    frets_present = {n.fret for n in notes}
    strings = [n.string for n in notes]
    first_onset = notes[0].onset if notes else 0.0

    features: dict[str, float] = {}
    seen_positions: set[tuple[int, int]] = set()
    for slot in range(window_size):
        prefix = f"n{slot}_"
        if slot < len(notes):
            note = notes[slot]
            position = (note.string, note.fret)
            repeated = position in seen_positions
            seen_positions.add(position)
            prev = notes[slot - 1] if slot > 0 else None
            features[prefix + "string"] = float(note.string)
            features[prefix + "fret"] = float(note.fret)
            features[prefix + "pitch"] = float(note.pitch)
            features[prefix + "fret_rel_min"] = float(note.fret) - win_min
            features[prefix + "fret_rel_anchor"] = float(note.fret - candidate_anchor)
            features[prefix + "is_open"] = 1.0 if note.fret == 0 else 0.0
            features[prefix + "onset_delta"] = float(note.onset - first_onset)
            features[prefix + "duration"] = float(note.duration)
            features[prefix + "is_repeated_pos"] = 1.0 if repeated else 0.0
            features[prefix + "same_string_as_prev"] = (
                1.0 if prev is not None and prev.string == note.string else 0.0
            )
            features[prefix + "same_fret_as_prev"] = (
                1.0 if prev is not None and prev.fret == note.fret else 0.0
            )
            features[prefix + "has_legato"] = 1.0 if note.has_legato else 0.0
        else:
            for key in _PER_NOTE_KEYS:
                features[prefix + key] = PAD_VALUE

    anchor = float(candidate_anchor)
    # has(k): a fretted note sits exactly on fret anchor+k. anchor+k is always
    # >= 1 (anchor >= 1, k >= 0), so open strings (fret 0) never satisfy it and
    # ``frets_present`` is safe to query directly. These are the authoritative
    # definitions from the GDS reference extractor (calibration rev2 / GDS-024).
    has0 = candidate_anchor in frets_present
    has1 = (candidate_anchor + 1) in frets_present
    has2 = (candidate_anchor + 2) in frets_present
    has3 = (candidate_anchor + 3) in frets_present

    features["win_num_notes"] = float(len(notes))
    features["win_min_fret"] = win_min
    features["win_max_fret"] = win_max
    features["win_fret_span"] = win_max - win_min
    features["win_num_strings"] = float(len(set(strings)))
    features["win_string_span"] = float(max(strings) - min(strings)) if strings else 0.0
    features["win_contains_open"] = 1.0 if any(n.fret == 0 for n in notes) else 0.0
    features["win_contains_chord"] = 1.0 if contains_chord else 0.0
    features["win_candidate_anchor"] = anchor
    # Index's natural fret (anchor+0) carries a note.
    features["win_index_anchor_required"] = 1.0 if has0 else 0.0
    # Ring's natural fret (anchor+2) carries a note.
    features["win_ring_natural_for_anchor_plus_2"] = 1.0 if has2 else 0.0
    # Pinky's natural fret (anchor+3) carries a note.
    features["win_pinky_natural_for_anchor_plus_3"] = 1.0 if has3 else 0.0
    # Pinky fret used while neither the anchor nor anchor+1 carry a note.
    features["win_pinky_used_without_lower_anchor"] = (
        1.0 if (has3 and not has0 and not has1) else 0.0
    )
    # Pinky note present with no lower fret (anchor, +1, +2) to anchor the hand,
    # so dropping the pinky note would force a position shift.
    features["win_would_shift_hand_if_no_pinky"] = (
        1.0 if (has3 and not has2 and not has1 and not has0) else 0.0
    )
    return features


def note_from_fretwise(
    string_num: int,
    fret: int,
    pitch: int,
    onset: float,
    duration: float,
    *,
    is_chord_member: bool = False,
    has_legato: bool = False,
) -> PhraseNote:
    """Build a :class:`PhraseNote` from FretWise-facing values.

    Converts the 1-based ``string_num`` (``1 = high e``) to the model's
    internal 0-based convention by subtracting 1.
    """
    return PhraseNote(
        string=string_num - 1,
        fret=fret,
        pitch=pitch,
        onset=onset,
        duration=duration,
        is_chord_member=is_chord_member,
        has_legato=has_legato,
    )


def _entropy(probs: Sequence[float]) -> float:
    """Shannon entropy (nats) of a probability distribution."""
    return -sum(p * math.log(p) for p in probs if p > 0.0)


class LearnedPhraseWindowFingerer:
    """ONNX-backed phrase-window fingerer (GuitarDataSet ``phrase_window_v1``).

    Loads the six-head bundle named in the manifest and runs the spec
    inference protocol. ``onnxruntime`` and ``numpy`` are imported lazily so
    callers that never activate the shadow predictor pay no dependency cost.

    Args:
        manifest_path: Path to ``phrase_window_fingering_v1_manifest.json``.
            The six head filenames are resolved relative to its directory.
        spec_path: Optional path to the spec JSON; when given, the feature
            layout is validated against :func:`phrase_window_feature_names`
            at load time (guards against silent feature drift).

    Raises:
        ImportError: If ``onnxruntime`` is not installed.
        FileNotFoundError: If the manifest or any head file is missing.
        AssertionError: If the spec feature layout drifts from this module.
    """

    def __init__(self, manifest_path: str, spec_path: str | None = None) -> None:
        try:
            import onnxruntime as ort  # noqa: F401
        except ImportError as exc:  # pragma: no cover - exercised only without ort
            raise ImportError(
                "onnxruntime is required for LearnedPhraseWindowFingerer. "
                "Install it via 'pip install onnxruntime' or "
                "'pip install fretwise[ml]'."
            ) from exc

        manifest_p = Path(manifest_path)
        if not manifest_p.exists():
            raise FileNotFoundError(f"Manifest not found: {manifest_path}")
        manifest = json.loads(manifest_p.read_text(encoding="utf-8"))
        self._feature_names = phrase_window_feature_names(WINDOW_SIZE)

        if spec_path:
            self._validate_spec(Path(spec_path))

        import onnxruntime as ort

        heads: dict[str, str] = manifest["heads"]
        model_dir = manifest_p.parent
        self._slot_sessions = []
        for slot in range(WINDOW_SIZE):
            head_file = heads[f"slot{slot}_finger"]
            head_p = model_dir / head_file
            if not head_p.exists():
                raise FileNotFoundError(f"Slot head not found: {head_p}")
            self._slot_sessions.append(ort.InferenceSession(str(head_p)))
        anchor_p = model_dir / heads["anchor_head"]
        if not anchor_p.exists():
            raise FileNotFoundError(f"Anchor head not found: {anchor_p}")
        self._anchor_session = ort.InferenceSession(str(anchor_p))

        self._slot_inputs = [s.get_inputs()[0].name for s in self._slot_sessions]
        self._anchor_input = self._anchor_session.get_inputs()[0].name

    def _validate_spec(self, spec_p: Path) -> None:
        """Assert the spec's feature layout matches this module's ordering."""
        spec = json.loads(spec_p.read_text(encoding="utf-8"))
        layout = spec["feature_layout"]
        expected: list[str] = []
        for slot in range(spec.get("window_size", WINDOW_SIZE)):
            for key in layout["per_note_slot_features"]:
                expected.append(key.replace("{slot}", str(slot)))
        expected.extend(layout["window_level_features"])
        assert tuple(expected) == self._feature_names, (
            "phrase_window feature layout drift between FretWise and the "
            "trained model. Compare phrase_window_feature_names() with "
            f"{spec_p}::feature_layout."
        )

    @classmethod
    def from_model_dir(cls, model_dir: str | Path) -> LearnedPhraseWindowFingerer:
        """Construct from a directory holding the manifest + spec + heads."""
        model_dir = Path(model_dir)
        manifest = model_dir / "phrase_window_fingering_v1_manifest.json"
        spec = model_dir / "phrase_window_fingering_v1_spec.json"
        return cls(str(manifest), str(spec) if spec.exists() else None)

    def _run_bundle(
        self, feature_rows: list[dict[str, float]],
    ) -> tuple[list[list[list[float]]], list[float]]:
        """Run all six heads on a batch of feature rows.

        Args:
            feature_rows: One 74-key feature dict per candidate.

        Returns:
            Tuple of:
              - slot_probs: ``slot_probs[row][slot]`` is a 5-vector softmax.
              - anchor_probs: ``anchor_probs[row]`` is P(anchor correct).
        """
        import numpy as np

        matrix = np.asarray(
            [[row[name] for name in self._feature_names] for row in feature_rows],
            dtype=np.float32,
        )
        # Per-slot finger heads: probabilities output is the [N, 5] float tensor.
        per_slot: list[list[list[float]]] = []
        for session, input_name in zip(self._slot_sessions, self._slot_inputs):
            outputs = session.run(None, {input_name: matrix})
            probs = _first_prob_tensor(outputs, width=5)
            per_slot.append([[float(p) for p in r] for r in probs])
        # Anchor head: binary classifier, column 1 = P(anchor correct).
        anchor_out = self._anchor_session.run(None, {self._anchor_input: matrix})
        anchor_probs_raw = _first_prob_tensor(anchor_out, width=2)
        anchor_probs = [float(r[1]) for r in anchor_probs_raw]

        # Re-shape from [slot][row] to [row][slot].
        n_rows = len(feature_rows)
        slot_probs: list[list[list[float]]] = [
            [per_slot[slot][row] for slot in range(WINDOW_SIZE)]
            for row in range(n_rows)
        ]
        return slot_probs, anchor_probs

    def predict_window(
        self,
        notes: Sequence[PhraseNote],
        alpha: float = 1.0,
    ) -> WindowPrediction:
        """Decode one window: select the best anchor, then its slot fingers.

        Implements spec steps 2–5. Candidate anchors are scored by
        ``anchor_prob - alpha * mean(slot NLL over real slots)`` and the
        argmax candidate's slot decoding is returned. (The spec's "uncertain
        slots" refinement degenerates to all real slots here; ``alpha`` tunes
        the confidence penalty.)

        Args:
            notes: 1..WINDOW_SIZE real notes, internal 0-based strings.
            alpha: Weight of the slot-confidence penalty in anchor selection.

        Returns:
            A :class:`WindowPrediction`. Empty ``notes`` yields an empty result.

        Raises:
            ValueError: If more than WINDOW_SIZE notes are supplied.
        """
        if not notes:
            return WindowPrediction(anchor=_MIN_ANCHOR, anchor_probability=0.0,
                                    slots=(), candidate_scores=())
        if len(notes) > WINDOW_SIZE:
            raise ValueError(
                f"predict_window expects at most {WINDOW_SIZE} notes, got {len(notes)}"
            )

        anchors = candidate_anchors(notes)
        rows = [build_window_feature_vector(notes, a) for a in anchors]
        slot_probs, anchor_probs = self._run_bundle(rows)

        n_real = len(notes)
        best_idx = 0
        best_score = -math.inf
        scores: list[tuple[int, float]] = []
        for i, anchor in enumerate(anchors):
            nlls = [
                -math.log(max(max(slot_probs[i][slot]), 1e-9))
                for slot in range(n_real)
            ]
            mean_nll = sum(nlls) / len(nlls) if nlls else 0.0
            score = anchor_probs[i] - alpha * mean_nll
            scores.append((anchor, score))
            if score > best_score:
                best_score = score
                best_idx = i

        chosen_anchor = anchors[best_idx]
        chosen_slots = slot_probs[best_idx]
        slots = tuple(
            _slot_prediction(chosen_slots[slot]) for slot in range(n_real)
        )
        return WindowPrediction(
            anchor=chosen_anchor,
            anchor_probability=anchor_probs[best_idx],
            slots=slots,
            candidate_scores=tuple(scores),
        )

    def predict_sequence(
        self,
        notes: Sequence[PhraseNote],
        stride: int = 1,
        alpha: float = 1.0,
    ) -> list[NotePrediction]:
        """Decode a melodic line, overlap-averaging per-note probabilities.

        Implements spec steps 1 & 6: slide a ``WINDOW_SIZE`` window with the
        given ``stride`` across the (non-chord) notes, decode each window, and
        average the slot softmaxes across every window that covers a note
        before taking the argmax — smoothing phrase-level decisions.

        Sequences shorter than ``WINDOW_SIZE`` are decoded as a single short
        window (the model degrades below 3 notes, per the spec).

        Args:
            notes: The melodic line, in onset order, internal 0-based strings.
            stride: Window step (1 = maximal overlap, the spec recommendation).
            alpha: Forwarded to :meth:`predict_window` anchor selection.

        Returns:
            One :class:`NotePrediction` per input note, in input order.
        """
        n = len(notes)
        if n == 0:
            return []
        if stride < 1:
            raise ValueError("stride must be >= 1")

        # Accumulators per note: summed softmax, vote count, best covering window.
        prob_sums: list[list[float]] = [[0.0] * 5 for _ in range(n)]
        counts: list[int] = [0] * n
        best_anchor: list[int] = [_MIN_ANCHOR] * n
        best_anchor_conf: list[float] = [-math.inf] * n

        starts = list(range(0, max(1, n - WINDOW_SIZE + 1), stride))
        # Ensure the tail is covered when (n - WINDOW_SIZE) isn't a stride multiple.
        last_start = max(0, n - WINDOW_SIZE)
        if starts[-1] != last_start:
            starts.append(last_start)

        for start in starts:
            window = notes[start:start + WINDOW_SIZE]
            prediction = self.predict_window(window, alpha=alpha)
            for slot, slot_pred in enumerate(prediction.slots):
                note_idx = start + slot
                for cls in range(5):
                    prob_sums[note_idx][cls] += slot_pred.probabilities[cls]
                counts[note_idx] += 1
                if prediction.anchor_probability > best_anchor_conf[note_idx]:
                    best_anchor_conf[note_idx] = prediction.anchor_probability
                    best_anchor[note_idx] = prediction.anchor

        result: list[NotePrediction] = []
        for idx in range(n):
            votes = counts[idx]
            if votes == 0:  # pragma: no cover - every note is covered by ≥1 window
                avg = [0.2] * 5
            else:
                avg = [s / votes for s in prob_sums[idx]]
            best_cls = max(range(5), key=lambda c: avg[c])
            result.append(NotePrediction(
                finger=PHRASE_FINGER_FROM_INDEX[best_cls],
                probabilities=tuple(avg),
                anchor=best_anchor[idx],
                entropy=_entropy(avg),
                n_windows=votes,
            ))
        return result


def _slot_prediction(probs: Sequence[float]) -> SlotPrediction:
    """Build a SlotPrediction (argmax finger + entropy) from a 5-vector."""
    best_cls = max(range(len(probs)), key=lambda c: probs[c])
    return SlotPrediction(
        finger=PHRASE_FINGER_FROM_INDEX[best_cls],
        probabilities=tuple(float(p) for p in probs),
        entropy=_entropy(probs),
    )


def _first_prob_tensor(outputs: list[Any], width: int) -> Any:
    """Return the float probability tensor of the given class width.

    XGBoost→ONNX exports emit ``(label[int64], probabilities[float, width])``.
    Some exporters wrap probabilities as a ZipMap (list of dicts); handle both
    by selecting the first 2-D float tensor with the expected column count.
    """
    import numpy as np

    for out in outputs:
        arr = np.asarray(out)
        if arr.ndim == 2 and arr.shape[1] == width and arr.dtype.kind == "f":
            return arr
    # ZipMap fallback: list[dict[int|str, float]] → dense rows ordered by key.
    for out in outputs:
        if isinstance(out, list) and out and isinstance(out[0], dict):
            rows = []
            for row in out:
                ordered = [row[k] for k in sorted(row.keys(), key=lambda x: int(x))]
                rows.append(ordered)
            arr = np.asarray(rows, dtype=np.float32)
            if arr.shape[1] == width:
                return arr
    raise ValueError(
        f"No [N, {width}] float probability tensor found in ONNX outputs."
    )
