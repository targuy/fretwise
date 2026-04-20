"""Tests unitaires démontrant le biais RING/PINKY de la fonction de coût.

Ces tests isolent le trade-off cost_position_shift vs cost_finger_difficulty
en désactivant cost_same_finger_motion (qui pénaliserait doublement INDEX
sur les transitions INDEX→INDEX et masquerait le phénomène étudié).
"""
from __future__ import annotations

from fretwise.models import Articulation, Dynamic, Finger, FingeringState, NoteEvent
from fretwise.scoring import RulePreferences, compute_mechanical_cost

_NO_SAME_FINGER = RulePreferences(same_finger_motion_penalty=False)


def _note(duration: float = 1.0, tempo: float = 120.0) -> NoteEvent:
    return NoteEvent(
        pitch=64, onset=0.0, duration=duration, tempo=tempo,
        articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
    )


def _state(fret: int, finger: Finger) -> FingeringState:
    offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    return FingeringState(
        string_num=1, fret=fret, finger=finger,
        hand_position=fret - offsets[finger],
    )


def test_ring_cheaper_than_index_ascending_2fret_at_120bpm() -> None:
    """Fret 5 (INDEX, hp=5) → fret 7 : RING coûte moins que INDEX à 120 BPM.

    RING@7 → hp=5, shift=0 → coût = 0 + 1.3 = 1.3
    INDEX@7 → hp=7, shift=2 → coût = 2×2.0 + 1.0 = 5.0
    """
    s1 = _state(5, Finger.INDEX)
    s2_ring  = _state(7, Finger.RING)
    s2_index = _state(7, Finger.INDEX)
    note = _note(duration=1.0, tempo=120.0)

    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note, rule_preferences=_NO_SAME_FINGER)
    cost_index = compute_mechanical_cost(s1, s2_index, note, rule_preferences=_NO_SAME_FINGER)
    assert cost_ring < cost_index, (
        f"RING ({cost_ring:.3f}) should be cheaper than INDEX ({cost_index:.3f}) "
        f"for an ascending 2-fret interval at 120 BPM"
    )


def test_index_wins_for_very_slow_notes() -> None:
    """À très basse vitesse (whole note à 30 BPM), le shift est peu coûteux → INDEX préféré.

    seconds = 4.0 × 60 / 30 = 8.0 s, tf = 0.125
    RING@7 → coût = 0 + 1.3 = 1.3
    INDEX@7 → coût = 2×0.125 + 1.0 = 1.25  → INDEX gagne
    """
    s1 = _state(5, Finger.INDEX)
    s2_ring  = _state(7, Finger.RING)
    s2_index = _state(7, Finger.INDEX)
    note = _note(duration=4.0, tempo=30.0)

    cost_ring  = compute_mechanical_cost(s1, s2_ring,  note, rule_preferences=_NO_SAME_FINGER)
    cost_index = compute_mechanical_cost(s1, s2_index, note, rule_preferences=_NO_SAME_FINGER)
    assert cost_index < cost_ring, (
        f"INDEX ({cost_index:.3f}) should be cheaper than RING ({cost_ring:.3f}) "
        f"for very slow notes (4 beats at 30 BPM)"
    )


def test_bias_breakeven_duration() -> None:
    """Le seuil de bascule INDEX↔RING se situe à ~13 beats à 120 BPM (irréaliste).

    Sans same_finger_motion :
      RING cost = 1.3 (constant)
      INDEX cost = 2×tf + 1.0  où tf = 1/max(d×0.5, 0.1)
      INDEX < RING quand : 2×tf < 0.3 → tf < 0.15 → seconds > 6.67 → d > 13.3 beats
    """
    s1 = _state(5, Finger.INDEX)
    s2_ring  = _state(7, Finger.RING)
    s2_index = _state(7, Finger.INDEX)

    # À 10 beats : seconds=5.0, tf=0.2 → INDEX=2×0.2+1.0=1.4 > RING=1.3 → RING gagne encore
    note_10b = _note(duration=10.0, tempo=120.0)
    cost_ring_10  = compute_mechanical_cost(s1, s2_ring,  note_10b, rule_preferences=_NO_SAME_FINGER)
    cost_index_10 = compute_mechanical_cost(s1, s2_index, note_10b, rule_preferences=_NO_SAME_FINGER)
    assert cost_ring_10 < cost_index_10 or abs(cost_ring_10 - cost_index_10) < 0.5, (
        f"At 10 beats, RING ({cost_ring_10:.3f}) should be cheaper or very close to INDEX ({cost_index_10:.3f})"
    )

    # À 14 beats : seconds=7.0, tf≈0.143 → INDEX=2×0.143+1.0≈1.286 < RING=1.3 → INDEX gagne
    note_14b = _note(duration=14.0, tempo=120.0)
    cost_ring_14  = compute_mechanical_cost(s1, s2_ring,  note_14b, rule_preferences=_NO_SAME_FINGER)
    cost_index_14 = compute_mechanical_cost(s1, s2_index, note_14b, rule_preferences=_NO_SAME_FINGER)
    assert cost_index_14 < cost_ring_14, (
        f"At 14 beats, INDEX ({cost_index_14:.3f}) should beat RING ({cost_ring_14:.3f})"
    )


def test_ascending_favors_ring_descending_favors_index() -> None:
    """Le biais est asymétrique : RING favorisé en montée, INDEX en descente.

    Montée (fret5→7) : RING évite le shift montant (hp reste à 5)
    Descente (fret7→5) : INDEX (shift=2) bat RING (shift=4)
      RING: 4×2.0+1.3=9.3   INDEX: 2×2.0+1.0=5.0 → INDEX gagne
    """
    note = _note(duration=1.0, tempo=120.0)

    # MONTÉE
    s1_low = _state(5, Finger.INDEX)
    c_ring_up  = compute_mechanical_cost(s1_low, _state(7, Finger.RING),  note, rule_preferences=_NO_SAME_FINGER)
    c_index_up = compute_mechanical_cost(s1_low, _state(7, Finger.INDEX), note, rule_preferences=_NO_SAME_FINGER)
    assert c_ring_up < c_index_up, f"Ascending: RING ({c_ring_up:.3f}) should beat INDEX ({c_index_up:.3f})"

    # DESCENTE
    s1_high = _state(7, Finger.INDEX)
    c_ring_down  = compute_mechanical_cost(s1_high, _state(5, Finger.RING),  note, rule_preferences=_NO_SAME_FINGER)
    c_index_down = compute_mechanical_cost(s1_high, _state(5, Finger.INDEX), note, rule_preferences=_NO_SAME_FINGER)
    assert c_index_down < c_ring_down, f"Descending: INDEX ({c_index_down:.3f}) should beat RING ({c_ring_down:.3f})"
