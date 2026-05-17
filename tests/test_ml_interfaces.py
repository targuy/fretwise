"""Tests for the ML interface stubs (Phase 3 prep).

These tests verify the contracts (signatures, types, default values) and
the baseline implementations (FixedPlayerCost, FixedChordFingerClassifier).
They do NOT exercise any learned model.
"""
from __future__ import annotations

import pytest

from fretwise.ml import (
    ChordFingerClassifier,
    ChordNote,
    FixedChordFingerClassifier,
    FixedPlayerCost,
    PlayerContext,
    PlayerCostModel,
)


# ---------------------------------------------------------------------------
# Dataclasses
# ---------------------------------------------------------------------------


def test_player_context_defaults() -> None:
    ctx = PlayerContext(onset=0.0, duration=1.0, tempo=120.0)
    assert ctx.articulation == "normal"
    assert ctx.techniques == ()
    assert ctx.voice_hint is None
    assert ctx.measure_index is None
    assert ctx.is_chord_member is False
    assert ctx.chord_size == 1
    assert ctx.time_to_next_note is None
    assert ctx.previous_finger is None


def test_player_context_is_frozen() -> None:
    ctx = PlayerContext(onset=0.0, duration=1.0, tempo=120.0)
    with pytest.raises(AttributeError):
        ctx.onset = 1.0  # type: ignore[misc]


def test_chord_note_defaults() -> None:
    note = ChordNote(string=3, fret=5, pitch=60)
    assert note.is_barre_candidate is False


def test_chord_note_is_frozen() -> None:
    note = ChordNote(string=3, fret=5, pitch=60)
    with pytest.raises(AttributeError):
        note.fret = 7  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Abstract base classes
# ---------------------------------------------------------------------------


def test_player_cost_model_is_abstract() -> None:
    with pytest.raises(TypeError):
        PlayerCostModel()  # type: ignore[abstract]


def test_chord_finger_classifier_is_abstract() -> None:
    with pytest.raises(TypeError):
        ChordFingerClassifier()  # type: ignore[abstract]


# ---------------------------------------------------------------------------
# FixedPlayerCost
# ---------------------------------------------------------------------------


def test_fixed_player_cost_returns_zero() -> None:
    model = FixedPlayerCost()
    ctx = PlayerContext(onset=0.0, duration=0.5, tempo=120.0)
    assert model.transition_cost(1, 3, "index", 1, 5, "ring", 3, ctx) == 0.0
    assert model.emission_cost(1, 5, "ring", 3, ctx) == 0.0


def test_fixed_player_cost_is_player_cost_model() -> None:
    model = FixedPlayerCost()
    assert isinstance(model, PlayerCostModel)


# ---------------------------------------------------------------------------
# FixedChordFingerClassifier
# ---------------------------------------------------------------------------


def test_fixed_classifier_empty_chord_returns_empty() -> None:
    cls = FixedChordFingerClassifier()
    ctx = PlayerContext(onset=0.0, duration=1.0, tempo=120.0)
    assert cls.predict_fingers([], hand_position=1, context=ctx) == []


def test_fixed_classifier_three_note_consecutive() -> None:
    cls = FixedChordFingerClassifier()
    ctx = PlayerContext(onset=0.0, duration=1.0, tempo=120.0)
    notes = [
        ChordNote(string=3, fret=5, pitch=60),
        ChordNote(string=2, fret=6, pitch=66),
        ChordNote(string=1, fret=7, pitch=71),
    ]
    fingers = cls.predict_fingers(notes, hand_position=5, context=ctx)
    assert fingers == ["index", "middle", "ring"]


def test_fixed_classifier_preserves_input_order() -> None:
    """If chord_notes is unsorted, return must align with input order."""
    cls = FixedChordFingerClassifier()
    ctx = PlayerContext(onset=0.0, duration=1.0, tempo=120.0)
    # Input order: highest fret first, then lower, then middle
    notes = [
        ChordNote(string=1, fret=7, pitch=71),  # input idx 0 → expected RING
        ChordNote(string=3, fret=5, pitch=60),  # input idx 1 → expected INDEX
        ChordNote(string=2, fret=6, pitch=66),  # input idx 2 → expected MIDDLE
    ]
    fingers = cls.predict_fingers(notes, hand_position=5, context=ctx)
    assert fingers == ["ring", "index", "middle"]


def test_fixed_classifier_is_chord_finger_classifier() -> None:
    cls = FixedChordFingerClassifier()
    assert isinstance(cls, ChordFingerClassifier)
