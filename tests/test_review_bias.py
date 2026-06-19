"""Tests for ``fretwise.review.bias`` — constrained generator + biased cost."""
from __future__ import annotations

from fretwise.generator import StateGenerator
from fretwise.ml import PlayerContext, PlayerCostModel
from fretwise.models import Finger, FingeringState, NoteEvent
from fretwise.review.bias import ConstrainedStateGenerator, FeedbackBiasedPlayerCost
from fretwise.review.feedback import FeedbackRecord, SongFeedback


class _ConstInner(PlayerCostModel):
    """Inner model returning a constant so bias deltas are observable."""

    def transition_cost(self, *args: object, **kwargs: object) -> float:
        return 10.0

    def emission_cost(self, *args: object, **kwargs: object) -> float:
        return 10.0


def _ctx() -> PlayerContext:
    return PlayerContext(onset=0.0, duration=0.5, tempo=120.0)


def _feedback() -> SongFeedback:
    rec = FeedbackRecord(
        song_stem="s", measure_index=1, onset=0.0, severity="suspect",
        chosen=[{"string": 2, "fret": 7, "finger": "ring", "hand_position": 5}],
        rejected=[{"string": 2, "fret": 7, "finger": "pinky", "hand_position": 4}],
    )
    return SongFeedback(stem="s", records=[rec])


def test_constrained_generator_locks_matching_note() -> None:
    note = NoteEvent(pitch=64, onset=6.0, duration=0.5, tempo=120.0, voice_hint=0)
    locked = FingeringState(string_num=2, fret=7, finger=Finger.RING, hand_position=5)
    gen = ConstrainedStateGenerator(StateGenerator(), {(6.0, 64, 0): locked})
    states = gen.states_for(note)
    assert states == [locked]


def test_constrained_generator_defers_when_unlocked() -> None:
    note = NoteEvent(pitch=64, onset=1.0, duration=0.5, tempo=120.0, voice_hint=0)
    base = StateGenerator()
    gen = ConstrainedStateGenerator(base, {(6.0, 64, 0): FingeringState(2, 7, Finger.RING, 5)})
    assert gen.states_for(note) == base.states_for(note)


def test_biased_cost_orders_preferred_below_rejected() -> None:
    cost = FeedbackBiasedPlayerCost(_ConstInner(), _feedback())
    preferred = cost.emission_cost(2, 7, "ring", 5, _ctx())
    neutral = cost.emission_cost(1, 3, "index", 3, _ctx())
    rejected = cost.emission_cost(2, 7, "pinky", 4, _ctx())
    assert preferred < neutral < rejected


def test_biased_cost_never_negative() -> None:
    cost = FeedbackBiasedPlayerCost(None, _feedback())  # no inner → zero base
    val = cost.emission_cost(2, 7, "ring", 5, _ctx())
    assert val >= 0.0


def test_biased_transition_applies_curr_state_delta() -> None:
    cost = FeedbackBiasedPlayerCost(_ConstInner(), _feedback())
    rejected = cost.transition_cost(1, 0, "open", 2, 7, "pinky", 4, _ctx())
    preferred = cost.transition_cost(1, 0, "open", 2, 7, "ring", 5, _ctx())
    assert preferred < rejected
