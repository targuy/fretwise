"""Tests for fretwise.generator — StateGenerator."""

from __future__ import annotations

from fretwise.generator import GeneratorConfig, StateGenerator
from fretwise.models import Finger, NoteEvent

# Standard EADGBE open string MIDI pitches: string 1–6
# E4=64, B3=59, G3=55, D3=50, A2=45, E2=40
_STANDARD_TUNING = [64, 59, 55, 50, 45, 40]


def _note(pitch: int, tempo: float = 120.0) -> NoteEvent:
    return NoteEvent(pitch=pitch, onset=0.0, duration=1.0, tempo=tempo)


class TestStateGeneratorStandardTuning:
    """Tests using standard EADGBE tuning."""

    def setup_method(self) -> None:
        self.gen = StateGenerator()

    def test_open_high_e_string(self) -> None:
        """E4 (MIDI 64) = string 1 open."""
        states = self.gen.states_for(_note(64))
        open_states = [s for s in states if s.string_num == 1 and s.fret == 0]
        assert len(open_states) == 12
        assert all(s.finger == Finger.OPEN for s in open_states)
        assert open_states[0].hand_position == 1
        assert open_states[-1].hand_position == 12

    def test_open_low_e_string(self) -> None:
        """E2 (MIDI 40) = string 6 open."""
        states = self.gen.states_for(_note(40))
        open_states = [s for s in states if s.string_num == 6 and s.fret == 0]
        assert len(open_states) == 12
        assert all(s.finger == Finger.OPEN for s in open_states)

    def test_middle_c_string_coverage(self) -> None:
        """MIDI 60 (C4) is playable on strings 2–6."""
        states = self.gen.states_for(_note(60))
        covered_strings = {s.string_num for s in states}
        # String 2 (B3=59): fret 1
        # String 3 (G3=55): fret 5
        # String 4 (D3=50): fret 10
        # String 5 (A2=45): fret 15
        # String 6 (E2=40): fret 20
        assert 2 in covered_strings
        assert 3 in covered_strings
        assert 4 in covered_strings
        assert 5 in covered_strings
        assert 6 in covered_strings
        # Not on string 1 (E4=64 > 60)
        assert 1 not in covered_strings

    def test_middle_c_frets(self) -> None:
        """Check specific (string, fret) pairs for MIDI 60."""
        states = self.gen.states_for(_note(60))
        string_fret = {(s.string_num, s.fret) for s in states}
        assert (2, 1) in string_fret
        assert (3, 5) in string_fret
        assert (4, 10) in string_fret
        assert (5, 15) in string_fret
        assert (6, 20) in string_fret

    def test_fretted_note_generates_four_fingers(self) -> None:
        """A fretted note on a single string has up to 4 finger options."""
        # G#3 on string 3 (G3=55): fret 4 (index, middle, ring, pinky all possible)
        states = self.gen.states_for(_note(59))  # B3 = string 2 open; fret 0 = 1 state
        # fret 4 on string 3: hand positions 4, 3, 2, 1
        fret4_string3 = [s for s in states if s.string_num == 3 and s.fret == 4]
        assert len(fret4_string3) == 4
        fingers_used = {s.finger for s in fret4_string3}
        assert Finger.INDEX in fingers_used
        assert Finger.MIDDLE in fingers_used
        assert Finger.RING in fingers_used
        assert Finger.PINKY in fingers_used

    def test_fret_1_only_index_possible(self) -> None:
        """Fret 1 can only be played with index (hand_pos=1); other fingers invalid."""
        # A#2/Bb2 on string 5 (A2=45): fret 1 → hand_pos = 1 for index only
        # middle: hand_pos = 0 (invalid), ring: -1 (invalid), pinky: -2 (invalid)
        states = self.gen.states_for(_note(46))  # A#2
        fret1_string5 = [s for s in states if s.string_num == 5 and s.fret == 1]
        assert len(fret1_string5) == 1
        assert fret1_string5[0].finger == Finger.INDEX
        assert fret1_string5[0].hand_position == 1

    def test_hand_position_derived_from_finger(self) -> None:
        """hand_position = fret - finger_offset."""
        # Use fret 5 on string 3 (G3=55 + 5 = 60 = C4)
        fret5_str3 = [
            s for s in self.gen.states_for(_note(60)) if s.string_num == 3 and s.fret == 5
        ]
        # index: hand_pos=5, middle: 4, ring: 3, pinky: 2
        hp_map = {s.finger: s.hand_position for s in fret5_str3}
        assert hp_map[Finger.INDEX] == 5
        assert hp_map[Finger.MIDDLE] == 4
        assert hp_map[Finger.RING] == 3
        assert hp_map[Finger.PINKY] == 2

    def test_pitch_above_range_returns_empty(self) -> None:
        """A pitch above E4 + 22 frets = MIDI 86 has no states on string 1."""
        states = self.gen.states_for(_note(120))  # way above guitar range
        assert states == []

    def test_pitch_below_range_returns_empty(self) -> None:
        """A pitch below E2 (MIDI 40) has no valid states."""
        states = self.gen.states_for(_note(30))
        assert states == []

    def test_max_fret_boundary(self) -> None:
        """Fret 22 is included; fret 23 is excluded."""
        # fret 22 on string 6 (E2=40): MIDI 62
        states = self.gen.states_for(_note(62))
        fret22_str6 = [s for s in states if s.string_num == 6 and s.fret == 22]
        assert len(fret22_str6) > 0

        # fret 23 on string 6: MIDI 63 — only on string 6 which is out of range
        states_63 = self.gen.states_for(_note(63))
        # string 6: fret 23 > MAX_FRET=22 → excluded
        fret23_str6 = [s for s in states_63 if s.string_num == 6]
        assert fret23_str6 == []


class TestStateGeneratorSequence:
    def test_states_for_sequence_length(self) -> None:
        gen = StateGenerator()
        notes = [_note(60), _note(62), _note(64)]
        result = gen.states_for_sequence(notes)
        assert len(result) == 3

    def test_states_for_sequence_empty(self) -> None:
        gen = StateGenerator()
        assert gen.states_for_sequence([]) == []

    def test_states_for_sequence_parallel(self) -> None:
        gen = StateGenerator()
        notes = [_note(64), _note(59)]
        results = gen.states_for_sequence(notes)
        # E4 (string 1 open) should appear in first note's states
        assert any(s.string_num == 1 and s.fret == 0 for s in results[0])
        # B3 (string 2 open) should appear in second note's states
        assert any(s.string_num == 2 and s.fret == 0 for s in results[1])


class TestStateGeneratorHintFallback:
    """Tests for hint-based fallback when string_hint/fret_hint don't match tuning."""

    def test_hint_open_string_fallback_added(self) -> None:
        """fret_hint=0 with a non-standard position triggers an OPEN fallback state."""
        gen = StateGenerator()
        # Use a pitch that won't produce a state at string 3 fret 0 in standard tuning.
        # string 3 (G3=55): fret 0 → pitch 55. Use pitch 64 which won't be on str3 fret 0.
        note = NoteEvent(
            pitch=64, onset=0.0, duration=1.0, tempo=120.0,
            string_hint=3, fret_hint=0,
        )
        states = gen.states_for(note)
        # Should add fallback: string 3 open.
        fallback = [s for s in states if s.string_num == 3 and s.fret == 0]
        assert len(fallback) >= 1
        assert fallback[0].finger == Finger.OPEN

    def test_hint_fretted_fallback_added(self) -> None:
        """fret_hint>0 with a hint that standard tuning wouldn't produce adds states."""
        gen = StateGenerator()
        # string 6 (E2=40), fret 3 → pitch 43 (G2).  Use pitch 44 with hint str6 fret 3.
        # The standard generator would produce string 6 fret 4 for pitch 44, NOT fret 3.
        note = NoteEvent(
            pitch=44, onset=0.0, duration=1.0, tempo=120.0,
            string_hint=6, fret_hint=3,
        )
        states = gen.states_for(note)
        hint_states = [s for s in states if s.string_num == 6 and s.fret == 3]
        assert len(hint_states) >= 1

    def test_hint_already_present_not_duplicated(self) -> None:
        """If the hint position is already in the standard states, no duplicate is added."""
        gen = StateGenerator()
        # E4 string 1 open — standard tuning already generates this.
        note = NoteEvent(
            pitch=64, onset=0.0, duration=1.0, tempo=120.0,
            string_hint=1, fret_hint=0,
        )
        states = gen.states_for(note)
        str1_open = [s for s in states if s.string_num == 1 and s.fret == 0]
        assert len(str1_open) == 12  # full open-state set, not duplicated beyond config


class TestStateGeneratorCustomTuning:
    def test_drop_d_tuning(self) -> None:
        """With drop-D tuning, string 6 is D2 (38) instead of E2 (40)."""
        drop_d = [64, 59, 55, 50, 45, 38]  # string 6: D2
        config = GeneratorConfig(open_string_pitches=drop_d)
        gen = StateGenerator(config)

        # E2 (MIDI 40) on standard string 6 (open E) should be fret 2 in drop-D
        states = gen.states_for(_note(40))
        str6_states = [s for s in states if s.string_num == 6]
        assert all(s.fret == 2 for s in str6_states)

    def test_custom_max_fret(self) -> None:
        """A 24-fret guitar allows frets 23 and 24."""
        config = GeneratorConfig(max_fret=24)
        gen = StateGenerator(config)

        # MIDI 64 (E4) on string 6 (E2=40): fret 24
        states = gen.states_for(_note(64))
        fret24_str6 = [s for s in states if s.string_num == 6 and s.fret == 24]
        assert len(fret24_str6) > 0
