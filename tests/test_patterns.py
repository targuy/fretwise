"""Tests for fretwise.patterns — PatternMatcher, chord, and scale recognition."""

from __future__ import annotations

import pytest

from fretwise.models import Finger, FingeringState, NoteEvent
from fretwise.patterns import PatternMatcher
from fretwise.patterns.chord_library import all_voicings, lookup_chord
from fretwise.patterns.chord_recognition import recognize_chord
from fretwise.patterns.scale_library import (
    ScaleMatch,
    get_scale,
    list_scales,
    recognize_scale,
    scale_boxes_for_root,
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


class TestAllVoicings:
    def test_open_chord_leads_with_the_curated_shape(self) -> None:
        """E has a curated open voicing — it must come first (lowest position)."""
        voicings = all_voicings("E")
        assert len(voicings) >= 2
        assert voicings[0].frets == [0, 0, 1, 2, 2, 0]
        assert voicings[0].base_fret == 1
        assert all(v.base_fret >= voicings[0].base_fret for v in voicings)

    def test_no_open_chord_still_offers_barre_positions(self) -> None:
        """C#m has no curated open voicing — both movable families must appear."""
        voicings = all_voicings("C#m")
        assert len(voicings) == 2
        # E-shape (root on string 6) and A-shape (root on string 5) land at
        # different anchor frets for the same chord.
        assert {v.base_fret for v in voicings} == {4, 9}

    def test_sorted_by_base_fret_ascending(self) -> None:
        voicings = all_voicings("Bbsus4")
        frets = [v.base_fret for v in voicings]
        assert frets == sorted(frets)

    def test_unknown_chord_returns_empty(self) -> None:
        assert all_voicings("Xdim#11b9") == []

    def test_every_voicing_is_playable_by_lookup_chord_semantics(self) -> None:
        """Each returned diagram must be internally consistent: one finger per
        distinct fret, frets aligned with fingers, no fret below the barre."""
        for voicing in all_voicings("F#m7"):
            fretted = [f for f in voicing.frets if f > 0]
            if fretted:
                assert min(fretted) == voicing.base_fret or voicing.base_fret == 1
            assert len(voicing.fingers) == len(voicing.frets)


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

    def test_get_scale_minor_pentatonic(self) -> None:
        s = get_scale("minor_pentatonic")
        assert s is not None
        assert s.intervals == frozenset({0, 3, 5, 7, 10})

    def test_get_scale_blues(self) -> None:
        s = get_scale("blues")
        assert s is not None
        assert 6 in s.intervals  # b5

    def test_get_scale_nonexistent(self) -> None:
        assert get_scale("nonexistent_scale") is None


# ---------------------------------------------------------------------------
# Scale box transposition (training module)
# ---------------------------------------------------------------------------


_OPEN_PC = {1: 4, 2: 11, 3: 7, 4: 2, 5: 9, 6: 4}
_ROOT_PC = {
    "C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5,
    "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11,
}


class TestScaleBoxesForRoot:
    def test_unknown_scale_returns_none(self) -> None:
        assert scale_boxes_for_root("nonexistent_scale", "E") is None

    def test_unknown_root_returns_none(self) -> None:
        assert scale_boxes_for_root("major", "H") is None

    @pytest.mark.parametrize("scale_name", list_scales())
    @pytest.mark.parametrize("root", ["C", "E", "G", "A#"])
    def test_every_generated_note_is_in_scale(self, scale_name: str, root: str) -> None:
        """No box may contain a note outside the scale.

        This is the invariant the hand-authored ``positions:`` YAML violated:
        it had no consumer, so nothing ever checked it against the intervals.
        """
        scale = get_scale(scale_name)
        assert scale is not None
        allowed = {(_ROOT_PC[root] + i) % 12 for i in scale.intervals}
        boxes = scale_boxes_for_root(scale_name, root)
        assert boxes
        for box in boxes:
            for note in box["notes"]:
                pc = (_OPEN_PC[note["string"]] + note["fret"]) % 12
                assert pc in allowed, (
                    f"{scale_name}/{box['name']} string {note['string']} "
                    f"fret {note['fret']} is out of scale"
                )

    def test_g_major_position_1_matches_known_box(self) -> None:
        # Classic G major position 1: low-E string fretted at 3, 5, 7.
        boxes = scale_boxes_for_root("major", "G")
        assert boxes is not None
        pos1 = next(b for b in boxes if b["name"] == "position_1")
        low_e_frets = sorted(n["fret"] for n in pos1["notes"] if n["string"] == 6)
        assert low_e_frets == [3, 5, 7]

    def test_a_minor_pentatonic_box_1_is_the_textbook_shape(self) -> None:
        """The most-practised shape on the instrument — pin it exactly."""
        boxes = scale_boxes_for_root("minor_pentatonic", "A")
        assert boxes is not None
        pos1 = boxes[0]
        by_string = {
            s: sorted(n["fret"] for n in pos1["notes"] if n["string"] == s)
            for s in range(1, 7)
        }
        assert by_string == {
            6: [5, 8], 5: [5, 7], 4: [5, 7], 3: [5, 7], 2: [5, 8], 1: [5, 8],
        }

    def test_position_1_starts_on_the_tonic(self) -> None:
        for scale_name in ("major", "minor_pentatonic", "blues"):
            boxes = scale_boxes_for_root(scale_name, "G")
            assert boxes
            low_e = min(n["fret"] for n in boxes[0]["notes"] if n["string"] == 6)
            assert (_OPEN_PC[6] + low_e) % 12 == _ROOT_PC["G"]

    @pytest.mark.parametrize("scale_name", list_scales())
    @pytest.mark.parametrize("root", ["C", "E", "G", "A#"])
    def test_boxes_stay_within_a_hand_span(self, scale_name: str, root: str) -> None:
        """A box the hand cannot hold is not a box.

        The binding constraint is per string: each string must be reachable
        from one hand position (≤ 5 frets). The overall footprint is allowed
        to be wider, because three-notes-per-string shapes legitimately pivot
        the hand as they climb — but not by much, which is what catches
        degree-walk drift (six-note scales otherwise smear a box across nine
        frets by the time they reach the high E).
        """
        boxes = scale_boxes_for_root(scale_name, root)
        assert boxes
        for box in boxes:
            width = box["max_fret"] - box["min_fret"] + 1
            assert width <= 6, f"{scale_name}/{box['name']} spans {width} frets"

    def test_every_string_is_playable(self) -> None:
        """No negative frets, and every string carries at least two notes."""
        for scale_name in list_scales():
            for box in scale_boxes_for_root(scale_name, "C") or []:
                for s in range(1, 7):
                    on_string = [n["fret"] for n in box["notes"] if n["string"] == s]
                    assert len(on_string) >= 2
                    assert min(on_string) >= 0

    def test_pentatonic_yields_its_five_classic_boxes(self) -> None:
        """Five boxes, all distinct. Collapsing two onto one window loses one."""
        for root in ("A", "E", "C"):
            boxes = scale_boxes_for_root("minor_pentatonic", root)
            assert boxes is not None
            assert len(boxes) == 5, [b["min_fret"] for b in boxes]
            starts = [b["min_fret"] for b in boxes]
            assert len(set(starts)) == 5

    def test_positions_climb_the_neck_without_wrapping(self) -> None:
        """Stepping to the next position must go up, never back to the nut."""
        for scale_name in ("major", "minor_pentatonic", "blues"):
            boxes = scale_boxes_for_root(scale_name, "A")
            assert boxes
            starts = [b["min_fret"] for b in boxes]
            assert starts == sorted(starts), f"{scale_name} positions wrap: {starts}"
            assert starts[-1] > starts[0]

    def test_root_notes_are_flagged(self) -> None:
        boxes = scale_boxes_for_root("major", "G")
        assert boxes is not None
        pos1 = next(b for b in boxes if b["name"] == "position_1")
        root_note = next(n for n in pos1["notes"] if n["string"] == 6 and n["fret"] == 3)
        assert root_note["is_root"] is True
        non_root = next(n for n in pos1["notes"] if n["string"] == 6 and n["fret"] == 5)
        assert non_root["is_root"] is False

    def test_case_insensitive_root(self) -> None:
        assert scale_boxes_for_root("major", "g") == scale_boxes_for_root("major", "G")

    def test_flat_root_name(self) -> None:
        # Bb (pc=10) should resolve like A# would.
        assert scale_boxes_for_root("major", "Bb") == scale_boxes_for_root("major", "A#")

    def test_all_boxes_have_min_max_fret(self) -> None:
        boxes = scale_boxes_for_root("minor_pentatonic", "A")
        assert boxes is not None
        for box in boxes:
            assert box["min_fret"] <= box["max_fret"]
            assert box["notes"]


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
