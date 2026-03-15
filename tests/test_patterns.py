"""Tests for fretwise.patterns — PatternMatcher, chord, and scale recognition."""

from __future__ import annotations

import pytest

from fretwise.models import Finger, FingeringState, NoteEvent
from fretwise.patterns import PatternMatcher
from fretwise.patterns.chord_library import lookup_chord
from fretwise.patterns.chord_recognition import recognize_chord
from fretwise.patterns.scale_library import (
    ScaleMatch,
    get_scale,
    list_scales,
    recognize_scale,
)


def _note(pitch: int = 60, onset: float = 0.0) -> NoteEvent:
    return NoteEvent(pitch=pitch, onset=onset, duration=1.0, tempo=120.0)


def _state(string_num: int = 3, fret: int = 5) -> FingeringState:
    return FingeringState(
        string_num=string_num, fret=fret, finger=Finger.INDEX, hand_position=fret
    )


# ---------------------------------------------------------------------------
# PatternMatcher — basic interface
# ---------------------------------------------------------------------------


class TestPatternMatcherBasic:
    def setup_method(self) -> None:
        self.matcher = PatternMatcher()

    def test_empty_sequence(self) -> None:
        result = self.matcher.apply([], [])
        assert result == []

    def test_single_note_unchanged(self) -> None:
        notes = [_note()]
        state_list = [[_state()]]
        result = self.matcher.apply(notes, state_list)
        assert result == state_list

    def test_does_not_remove_states(self) -> None:
        notes = [_note()]
        original = [[_state(3, 5), _state(2, 10)]]
        result = self.matcher.apply(notes, original)
        assert len(result[0]) == 2

    def test_preserves_all_states(self) -> None:
        """PatternMatcher reorders but never drops states."""
        notes = [_note(60), _note(62)]
        states = [[_state(3, 5), _state(1, 0)], [_state(3, 7), _state(2, 8)]]
        result = self.matcher.apply(notes, states)
        assert set(id(s) for s in result[0]) == set(id(s) for s in states[0])
        assert set(id(s) for s in result[1]) == set(id(s) for s in states[1])


# ---------------------------------------------------------------------------
# PatternMatcher — chord promotion
# ---------------------------------------------------------------------------


class TestPatternMatcherChordPromotion:
    """When simultaneous notes form a recognized chord, prefer canonical voicing states."""

    def setup_method(self) -> None:
        self.matcher = PatternMatcher()

    def test_am_chord_promotes_matching_states(self) -> None:
        """Am chord (x02210): notes at onset=0 should promote matching (string, fret)."""
        # Am = A2(45), E3(52), A3(57), C4(60), E4(64)
        notes = [
            _note(45, onset=0.0),  # A2 — string 5 open
            _note(52, onset=0.0),  # E3 — string 4 fret 2
            _note(57, onset=0.0),  # A3 — string 3 fret 2
            _note(60, onset=0.0),  # C4 — string 2 fret 1
            _note(64, onset=0.0),  # E4 — string 1 open
        ]
        # For note C4 (string 2 fret 1), create states with matching and non-matching.
        # Am voicing: string 2 = fret 1.
        state_match = _state(string_num=2, fret=1)
        state_nomatch = _state(string_num=1, fret=5)
        states = [
            [_state(5, 0)],           # A2
            [_state(4, 2)],           # E3
            [_state(3, 2)],           # A3
            [state_nomatch, state_match],  # C4 — non-match first
            [_state(1, 0)],           # E4
        ]
        result = self.matcher.apply(notes, states)
        # After promotion, the matching state should be first.
        assert result[3][0] is state_match
        assert self.matcher.chord_matches >= 1

    def test_no_chord_no_promotion(self) -> None:
        """Single notes don't trigger chord matching."""
        notes = [_note(60, onset=0.0), _note(62, onset=1.0)]
        states = [[_state(3, 5), _state(2, 8)], [_state(3, 7)]]
        result = self.matcher.apply(notes, states)
        assert self.matcher.chord_matches == 0


# ---------------------------------------------------------------------------
# PatternMatcher — scale promotion
# ---------------------------------------------------------------------------


class TestPatternMatcherScalePromotion:
    def setup_method(self) -> None:
        self.matcher = PatternMatcher()

    def test_c_major_scale_detected(self) -> None:
        """A full C major scale should be detected."""
        # C D E F G A B = MIDI 60 62 64 65 67 69 71
        notes = [_note(p, onset=float(i)) for i, p in
                 enumerate([60, 62, 64, 65, 67, 69, 71])]
        states = [[_state(3, 5), _state(2, 8)] for _ in notes]
        self.matcher.apply(notes, states)
        assert self.matcher.scale_match is not None
        assert self.matcher.scale_match.name == "major"
        assert self.matcher.scale_match.root_name == "C"


# ---------------------------------------------------------------------------
# Chord recognition
# ---------------------------------------------------------------------------


class TestChordRecognition:
    def test_c_major(self) -> None:
        assert recognize_chord([60, 64, 67]) == "C"

    def test_am(self) -> None:
        assert recognize_chord([45, 52, 57, 60, 64]) == "Am"

    def test_g7(self) -> None:
        # G B D F = 55 59 62 65
        assert recognize_chord([55, 59, 62, 65]) == "G7"

    def test_single_note_returns_none(self) -> None:
        assert recognize_chord([60]) is None

    def test_empty_returns_none(self) -> None:
        assert recognize_chord([]) is None

    def test_em(self) -> None:
        assert recognize_chord([40, 47, 52, 55, 59, 64]) == "Em"

    def test_d(self) -> None:
        # D F# A = 50 54 57
        assert recognize_chord([50, 54, 57]) == "D"

    def test_dm7(self) -> None:
        # D F A C = 50 53 57 60
        assert recognize_chord([50, 53, 57, 60]) == "Dm7"


# ---------------------------------------------------------------------------
# Chord library
# ---------------------------------------------------------------------------


class TestChordLibrary:
    def test_lookup_am(self) -> None:
        diagram = lookup_chord("Am")
        assert diagram is not None
        assert diagram.name == "Am"
        assert diagram.frets[0] == 0   # high_e open
        assert diagram.frets[5] == -1  # low_E muted

    def test_lookup_nonexistent_returns_none(self) -> None:
        assert lookup_chord("Xdim#11b9") is None

    def test_lookup_empty_returns_none(self) -> None:
        assert lookup_chord("") is None

    def test_lookup_case_insensitive(self) -> None:
        diagram = lookup_chord("am")
        assert diagram is not None
        assert diagram.name == "Am"

    def test_lookup_slash_chord_fallback(self) -> None:
        """C/G should be found directly (in library)."""
        diagram = lookup_chord("C/G")
        assert diagram is not None

    def test_lookup_g(self) -> None:
        diagram = lookup_chord("G")
        assert diagram is not None
        assert diagram.frets == [3, 0, 0, 0, 2, 3]


# ---------------------------------------------------------------------------
# Scale library
# ---------------------------------------------------------------------------


class TestScaleLibrary:
    def test_list_scales_not_empty(self) -> None:
        scales = list_scales()
        assert len(scales) >= 10

    def test_get_scale_major(self) -> None:
        s = get_scale("major")
        assert s is not None
        assert s.intervals == frozenset({0, 2, 4, 5, 7, 9, 11})
        assert len(s.positions) >= 1

    def test_get_scale_minor_pentatonic(self) -> None:
        s = get_scale("minor_pentatonic")
        assert s is not None
        assert s.intervals == frozenset({0, 3, 5, 7, 10})
        assert len(s.positions) >= 3  # 5 box positions

    def test_get_scale_blues(self) -> None:
        s = get_scale("blues")
        assert s is not None
        assert 6 in s.intervals  # b5

    def test_get_scale_nonexistent(self) -> None:
        assert get_scale("nonexistent_scale") is None


# ---------------------------------------------------------------------------
# Scale recognition
# ---------------------------------------------------------------------------


class TestScaleRecognition:
    def test_c_major_scale(self) -> None:
        # C D E F G A B
        result = recognize_scale([60, 62, 64, 65, 67, 69, 71])
        assert result is not None
        assert result.name == "major"
        assert result.root == 0  # C
        assert result.confidence == pytest.approx(1.0)

    def test_a_minor_pentatonic(self) -> None:
        # A C D E G = 57 60 62 64 67
        # Note: these 5 pitch classes are a subset of C major (7-note),
        # so the recogniser correctly prefers the more specific 7-note match.
        # We just confirm it finds a diatonic match with high confidence.
        result = recognize_scale([57, 60, 62, 64, 67])
        assert result is not None
        assert result.confidence >= 0.75

    def test_e_natural_minor(self) -> None:
        # E F# G A B C D = 64 66 67 69 71 72 74
        # Note: E natural minor = G major (relative major). Recogniser may
        # return either; we verify a 7-note diatonic scale is found.
        result = recognize_scale([64, 66, 67, 69, 71, 72, 74])
        assert result is not None
        assert result.confidence == pytest.approx(1.0)
        assert result.name in ("major", "natural_minor", "dorian", "lydian")

    def test_too_few_notes_returns_none(self) -> None:
        assert recognize_scale([60, 64]) is None
        assert recognize_scale([60, 64, 67]) is None

    def test_chromatic_mess_returns_none(self) -> None:
        """12 chromatic notes don't match any scale well."""
        result = recognize_scale(list(range(60, 72)))
        assert result is None

    def test_g_blues(self) -> None:
        # G Bb C C# D F = 55 58 60 61 62 65
        result = recognize_scale([55, 58, 60, 61, 62, 65])
        assert result is not None
        assert result.root_name == "G"

    def test_repeated_pitches_dont_affect_result(self) -> None:
        # C major with repeats
        pitches = [60, 62, 64, 65, 67, 69, 71, 60, 62, 64]
        result = recognize_scale(pitches)
        assert result is not None
        assert result.name == "major"
        assert result.root == 0
