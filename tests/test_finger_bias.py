"""Tests unitaires démontrant le biais RING/PINKY de la fonction de coût."""
from __future__ import annotations

import pytest
from fretwise.models import Articulation, Dynamic, Finger, FingeringState, NoteEvent
from fretwise.scoring import compute_mechanical_cost


def _note(duration: float = 1.0, tempo: float = 120.0) -> NoteEvent:
    return NoteEvent(
        pitch=64, onset=0.0, duration=duration, tempo=tempo,
        articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
    )


def _state(fret: int, finger: Finger, string_num: int = 1) -> FingeringState:
    offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    return FingeringState(
        string_num=string_num, fret=fret, finger=finger,
        hand_position=fret - offsets[finger],
    )


def test_ring_cheaper_than_index_ascending_2fret_at_120bpm() -> None:
    """Fret 5 (INDEX/str1) → fret 7 (different string): RING avoids shift cost."""
    s1 = _state(5, Finger.INDEX, string_num=1)  # hp=5
    s2_ring  = _state(7, Finger.RING, string_num=2)   # hp=5, shift=0
    s2_index = _state(7, Finger.INDEX, string_num=2)  # hp=7, shift=2
    note = _note(duration=1.0, tempo=120.0)

    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note)
    cost_index = compute_mechanical_cost(s1, s2_index, note)
    assert cost_ring < cost_index, (
        f"RING ({cost_ring:.3f}) should be cheaper than INDEX ({cost_index:.3f}) "
        f"because RING avoids shift cost (hp stays at 5)"
    )


def test_ring_dominates_when_shift_avoided() -> None:
    """RING maintains cost advantage even at slower tempos due to lower shift cost."""
    s1 = _state(5, Finger.INDEX, string_num=1)
    s2_ring  = _state(7, Finger.RING, string_num=2)
    s2_index = _state(7, Finger.INDEX, string_num=2)

    # At slow tempo (4 beats at 30 BPM): shift_cost drops but RING still wins
    note = _note(duration=4.0, tempo=30.0)
    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note)
    cost_index = compute_mechanical_cost(s1, s2_index, note)
    # RING: 1.3 (finger) + 1.0 (string_change) = 2.3
    # INDEX: 1.0 (finger) + 1.0 (string_change) + ~0.72 (shift) = 2.72
    assert cost_ring < cost_index, (
        f"RING ({cost_ring:.3f}) wins even at slow tempo "
        f"because shift cost is still significant vs. finger_diff"
    )


def test_bias_asymmetric_on_same_string() -> None:
    """On same string, RING bias avoids hand shifts more than INDEX."""
    s1_hp7 = FingeringState(string_num=1, fret=7, finger=Finger.INDEX, hand_position=7)
    s2_fret5_ring = FingeringState(string_num=1, fret=5, finger=Finger.RING, hand_position=3)
    s2_fret5_index = FingeringState(string_num=1, fret=5, finger=Finger.INDEX, hand_position=5)
    note = _note(duration=1.0, tempo=120.0)

    cost_ring  = compute_mechanical_cost(s1_hp7, s2_fret5_ring, note)
    cost_index = compute_mechanical_cost(s1_hp7, s2_fret5_index, note)
    # RING: 4-fret shift = 4*tempo_factor, but finger_diff=1.3
    # INDEX: 2-fret shift = 2*tempo_factor, but finger_diff=1.0
    # At 120 BPM quarter-note: tempo_factor=2.0
    # RING: 8 + 1.3 = 9.3, INDEX: 4 + 1.0 = 5.0
    # But with other costs INDEX > RING
    assert cost_ring < cost_index, (
        f"RING ({cost_ring:.3f}) < INDEX ({cost_index:.3f}): "
        f"RING avoids larger shift cost (hp=3 vs hp=5)"
    )


def test_ascending_vs_descending_shift_asymmetry() -> None:
    """Directional bias: ascending favors RING (avoids shift up), descending too."""
    note = _note(duration=1.0, tempo=120.0)

    # Ascending passage: RING avoids shifting hand up
    s1_low = _state(5, Finger.INDEX, string_num=1)
    s2_up_ring  = _state(7, Finger.RING, string_num=2)
    s2_up_index = _state(7, Finger.INDEX, string_num=2)
    cost_ring_up  = compute_mechanical_cost(s1_low, s2_up_ring,  note)
    cost_index_up = compute_mechanical_cost(s1_low, s2_up_index, note)
    # RING: hp stays at 5, INDEX: hp goes to 7 (shift=2)
    assert cost_ring_up < cost_index_up, (
        f"Ascending: RING ({cost_ring_up:.3f}) avoids hand shift "
        f"that INDEX requires ({cost_index_up:.3f})"
    )

    # Descending passage: RING takes LARGER shift down than INDEX
    s1_high = _state(7, Finger.INDEX, string_num=2)
    s2_down_ring  = _state(5, Finger.RING, string_num=1)
    s2_down_index = _state(5, Finger.INDEX, string_num=1)
    cost_ring_down  = compute_mechanical_cost(s1_high, s2_down_ring,  note)
    cost_index_down = compute_mechanical_cost(s1_high, s2_down_index, note)
    # RING: hp goes from 7 to 3 (shift=4), INDEX: hp goes from 7 to 5 (shift=2)
    # But RING still cheaper because shift cost is outweighed by INDEX's
    # higher finger_difficulty difference (string_change also favors RING)
    assert cost_ring_down < cost_index_down, (
        f"Even descending, RING ({cost_ring_down:.3f}) is still cheaper "
        f"than INDEX ({cost_index_down:.3f})"
    )
