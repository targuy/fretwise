"""Regression tests for the Part A cost feature-vector refactor.

These lock in the load-bearing invariant of the refactor: the scalar costs
``compute_mechanical_cost`` / ``compute_musical_cost`` are exactly the sum of
their feature vectors under identity weights (byte-for-byte the historical
behaviour), and the explicit identity-weight path agrees with the default path.
If a future change to a ``cost_*`` term forgets to update its feature slot,
these tests fail.
"""

from __future__ import annotations

import itertools

import pytest

from fretwise.models import Articulation, Finger, FingeringState, NoteEvent
from fretwise.scoring import (
    MECHANICAL_FEATURE_COUNT,
    MECHANICAL_FEATURE_NAMES,
    MUSICAL_FEATURE_COUNT,
    MUSICAL_FEATURE_NAMES,
    compute_mechanical_cost,
    compute_mechanical_cost_features,
    compute_musical_cost,
    compute_musical_cost_features,
)


def _note(articulation: Articulation = Articulation.NORMAL) -> NoteEvent:
    return NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0, articulation=articulation)


# A spread of states covering open/fretted, every finger, low/high frets, and
# a range of hand positions so the special-case branches are all exercised.
_STATES = [
    FingeringState(string_num=s, fret=f, finger=fg, hand_position=hp)
    for s, f, fg, hp in [
        (3, 0, Finger.OPEN, 1),
        (1, 5, Finger.INDEX, 5),
        (2, 5, Finger.MIDDLE, 5),
        (4, 8, Finger.RING, 6),
        (6, 12, Finger.PINKY, 9),
        (3, 5, Finger.INDEX, 5),  # duplicate position w/ varied finger for same-fret cases
        (3, 5, Finger.RING, 5),
        (5, 3, Finger.INDEX, 2),
    ]
]

_ARTICULATIONS = [
    Articulation.NORMAL,
    Articulation.HAMMER_ON,
    Articulation.PULL_OFF,
    Articulation.LEGATO,
    Articulation.VIBRATO,
    Articulation.WIDE_VIBRATO,
]


class TestFeatureVectorShape:
    def test_mechanical_count_matches_names_and_arity(self) -> None:
        assert MECHANICAL_FEATURE_COUNT == len(MECHANICAL_FEATURE_NAMES) == 6
        vec = compute_mechanical_cost_features(_STATES[1], _STATES[3], _note())
        assert len(vec) == MECHANICAL_FEATURE_COUNT

    def test_musical_count_matches_names_and_arity(self) -> None:
        assert MUSICAL_FEATURE_COUNT == len(MUSICAL_FEATURE_NAMES) == 7
        vec = compute_musical_cost_features(_STATES[1], _STATES[3], _note())
        assert len(vec) == MUSICAL_FEATURE_COUNT

    def test_features_are_non_negative(self) -> None:
        for s1, s2 in itertools.product(_STATES, _STATES):
            for art in _ARTICULATIONS:
                note = _note(art)
                assert all(c >= 0.0 for c in compute_mechanical_cost_features(s1, s2, note))
                assert all(c >= 0.0 for c in compute_musical_cost_features(s1, s2, note))


class TestScalarEqualsFeatureSum:
    """sum(features) == scalar (default identity path) for every transition."""

    def test_mechanical_sum_equals_scalar(self) -> None:
        for s1, s2 in itertools.product(_STATES, _STATES):
            note = _note()
            vec = compute_mechanical_cost_features(s1, s2, note)
            assert sum(vec) == pytest.approx(compute_mechanical_cost(s1, s2, note))

    def test_musical_sum_equals_scalar(self) -> None:
        for s1, s2 in itertools.product(_STATES, _STATES):
            for art in _ARTICULATIONS:
                note = _note(art)
                vec = compute_musical_cost_features(s1, s2, note)
                assert sum(vec) == pytest.approx(compute_musical_cost(s1, s2, note))

    def test_mechanical_sum_equals_scalar_segment_aware(self) -> None:
        # Exercise the segment-aware shift branch on both producer and scalar.
        for s1, s2 in itertools.product(_STATES, _STATES):
            note = _note()
            kw = {"segment_anchor_prev": 1, "segment_anchor_curr": 7}
            vec = compute_mechanical_cost_features(s1, s2, note, **kw)
            assert sum(vec) == pytest.approx(compute_mechanical_cost(s1, s2, note, **kw))


class TestIdentityWeightsEqualDefault:
    """Explicit all-ones weights reproduce the default (no-weights) scalar."""

    def test_mechanical_identity_weights(self) -> None:
        ones = [1.0] * MECHANICAL_FEATURE_COUNT
        for s1, s2 in itertools.product(_STATES, _STATES):
            note = _note()
            assert compute_mechanical_cost(s1, s2, note, feature_weights=ones) == pytest.approx(
                compute_mechanical_cost(s1, s2, note)
            )

    def test_musical_identity_weights(self) -> None:
        ones = [1.0] * MUSICAL_FEATURE_COUNT
        for s1, s2 in itertools.product(_STATES, _STATES):
            for art in _ARTICULATIONS:
                note = _note(art)
                assert compute_musical_cost(s1, s2, note, feature_weights=ones) == pytest.approx(
                    compute_musical_cost(s1, s2, note)
                )


class TestWeightedPathBehaviour:
    def test_zero_weights_zero_cost(self) -> None:
        zeros_m = [0.0] * MECHANICAL_FEATURE_COUNT
        zeros_u = [0.0] * MUSICAL_FEATURE_COUNT
        s1, s2 = _STATES[1], _STATES[4]
        note = _note(Articulation.HAMMER_ON)
        assert compute_mechanical_cost(s1, s2, note, feature_weights=zeros_m) == pytest.approx(0.0)
        assert compute_musical_cost(s1, s2, note, feature_weights=zeros_u) == pytest.approx(0.0)

    def test_doubling_weights_doubles_cost(self) -> None:
        # With a uniform 2x weight vector the weighted cost is exactly 2x the sum.
        twos = [2.0] * MECHANICAL_FEATURE_COUNT
        for s1, s2 in itertools.product(_STATES, _STATES):
            note = _note()
            base = compute_mechanical_cost(s1, s2, note)
            assert compute_mechanical_cost(s1, s2, note, feature_weights=twos) == pytest.approx(
                2.0 * base
            )
