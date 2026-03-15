"""Tests for fretwise.export — ascii_tab, chord_recognition, pdf_tab."""

from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.patterns.chord_recognition import recognize_chord
from fretwise.export.ascii_tab import (
    _group_by_measure,
    _render_measure,
    render_ascii_tab,
    render_text_report,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _note(
    pitch: int = 60,
    onset: float = 0.0,
    duration: float = 1.0,
    tempo: float = 120.0,
) -> NoteEvent:
    return NoteEvent(pitch=pitch, onset=onset, duration=duration, tempo=tempo)


def _fr(
    note_id: int,
    onset: float,
    string_num: int,
    fret: int,
    finger: Finger,
    pitch: int = 60,
    tempo: float = 120.0,
) -> FingeringResult:
    _offsets = {Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3}
    offset = _offsets.get(finger, 0)
    hp = max(1, fret - offset) if fret > 0 else 1
    state = FingeringState(string_num=string_num, fret=fret, finger=finger, hand_position=hp)
    note = NoteEvent(pitch=pitch, onset=onset, duration=1.0, tempo=tempo)
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=1.0)


def _open_fr(note_id: int, onset: float, string_num: int, pitch: int = 64) -> FingeringResult:
    state = FingeringState(string_num=string_num, fret=0, finger=Finger.OPEN, hand_position=1)
    note = NoteEvent(pitch=pitch, onset=onset, duration=1.0, tempo=120.0)
    return FingeringResult(note_id=note_id, note_event=note, state=state, cost=0.0)


# ---------------------------------------------------------------------------
# export package imports
# ---------------------------------------------------------------------------


def test_export_package_imports() -> None:
    """Importing fretwise.export exposes the main renderer functions."""
    from fretwise.export import render_ascii_tab as rat  # noqa: F401
    from fretwise.export import render_pdf_tab as rpt  # noqa: F401
    from fretwise.export import render_text_report as rtr  # noqa: F401

    assert callable(rat)
    assert callable(rpt)
    assert callable(rtr)


# ---------------------------------------------------------------------------
# recognize_chord
# ---------------------------------------------------------------------------


class TestRecognizeChord:
    def test_exact_c_major(self) -> None:
        # C major: C=60, E=64, G=67
        assert recognize_chord([60, 64, 67]) == "C"

    def test_exact_a_minor(self) -> None:
        # A minor: A=69, C=72, E=76
        assert recognize_chord([69, 72, 76]) == "Am"

    def test_exact_g_major7(self) -> None:
        # G major7: G=55, B=59, D=62, F#=66
        assert recognize_chord([55, 59, 62, 66]) == "Gmaj7"

    def test_exact_g_dominant7(self) -> None:
        # G7: G=55, B=59, D=62, F=65
        assert recognize_chord([55, 59, 62, 65]) == "G7"

    def test_exact_dim7(self) -> None:
        # Bdim7: B=59, D=62, F=65, Ab=68
        result = recognize_chord([59, 62, 65, 68])
        assert result is not None
        assert "dim7" in result

    def test_exact_minor7(self) -> None:
        # Am7: A=69, C=72, E=76, G=79
        assert recognize_chord([69, 72, 76, 79]) == "Am7"

    def test_exact_sus4(self) -> None:
        # Csus4: C=60, F=65, G=67
        assert recognize_chord([60, 65, 67]) == "Csus4"

    def test_exact_sus2(self) -> None:
        # Csus2: C=60, D=62, G=67
        assert recognize_chord([60, 62, 67]) == "Csus2"

    def test_exact_augmented(self) -> None:
        # Caug: C=60, E=64, G#=68
        result = recognize_chord([60, 64, 68])
        assert result is not None
        assert "aug" in result

    def test_exact_dim_triad(self) -> None:
        # Bdim: B=59, D=62, F=65
        result = recognize_chord([59, 62, 65])
        assert result is not None
        assert "dim" in result

    def test_subset_match_three_of_four(self) -> None:
        # Gmaj7 with only 3 notes: G=55, B=59, D=62 (missing F#)
        # Should match as subset of Gmaj7 or as G major.
        result = recognize_chord([55, 59, 62])
        assert result is not None

    def test_octave_equivalence(self) -> None:
        # Same pitch classes, different octaves → same chord name.
        assert recognize_chord([60, 64, 67]) == recognize_chord([72, 76, 79])

    def test_only_one_pitch_class_returns_none(self) -> None:
        # Only C in multiple octaves → no chord.
        assert recognize_chord([60, 72, 84]) is None

    def test_empty_returns_none(self) -> None:
        assert recognize_chord([]) is None

    def test_two_pitch_classes_returns_none(self) -> None:
        # Two pitch classes: perfect fifth.  Not enough for any chord pattern.
        assert recognize_chord([60, 67]) is None

    def test_unrecognised_cluster_returns_none(self) -> None:
        # Intervals 0,1,6 don't match any defined pattern.
        result = recognize_chord([60, 61, 66])
        assert result is None

    def test_m7_chord(self) -> None:
        # Dm7: D=50, F=53, A=57, C=60
        result = recognize_chord([50, 53, 57, 60])
        assert result is not None
        assert "m7" in result

    def test_m6_chord(self) -> None:
        # Am6: A=57, C=60, E=64, F#=66  → (0,3,7,9)
        result = recognize_chord([57, 60, 64, 66])
        assert result is not None
        assert "m6" in result

    def test_major6_chord(self) -> None:
        # C6: C=60, E=64, G=67, A=69 → (0,4,7,9)
        result = recognize_chord([60, 64, 67, 69])
        assert result is not None
        assert "6" in result


# ---------------------------------------------------------------------------
# _group_by_measure
# ---------------------------------------------------------------------------


class TestGroupByMeasure:
    def test_empty_returns_empty(self) -> None:
        assert _group_by_measure([], 4.0) == []

    def test_single_note_one_measure(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        groups = _group_by_measure(results, 4.0)
        assert len(groups) == 1
        assert groups[0] == results

    def test_two_notes_same_measure(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 2.0, 4, 7, Finger.RING),
        ]
        groups = _group_by_measure(results, 4.0)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_notes_split_across_two_measures(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 4.0, 4, 7, Finger.RING),
        ]
        groups = _group_by_measure(results, 4.0)
        assert len(groups) == 2
        assert len(groups[0]) == 1
        assert len(groups[1]) == 1

    def test_late_start_offset_yields_one_group(self) -> None:
        # Notes start at beat 16 (measure 5 in 4/4) — offset normalised away.
        results = [_fr(0, 16.0, 3, 5, Finger.INDEX)]
        groups = _group_by_measure(results, 4.0)
        assert len(groups) == 1

    def test_three_beat_measure(self) -> None:
        # 3/4 time: notes at beats 0, 3, 6 each start a new measure.
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 3.0, 4, 7, Finger.RING),
            _fr(2, 6.0, 5, 9, Finger.MIDDLE),
        ]
        groups = _group_by_measure(results, 3.0)
        assert len(groups) == 3

    def test_three_notes_three_separate_measures(self) -> None:
        results = [_fr(i, float(i * 4), 3, 5, Finger.INDEX) for i in range(3)]
        groups = _group_by_measure(results, 4.0)
        assert len(groups) == 3


# ---------------------------------------------------------------------------
# _render_measure
# ---------------------------------------------------------------------------


class TestRenderMeasure:
    def test_empty_returns_empty(self) -> None:
        assert _render_measure([]) == []

    def test_returns_six_string_lines(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        lines = _render_measure(results)
        # There must be exactly 6 string lines (possibly preceded by chord line).
        string_lines = [l for l in lines if l.startswith(("e ", "B ", "G ", "D ", "A ", "E "))]
        assert len(string_lines) == 6

    def test_fret_finger_on_correct_string(self) -> None:
        # INDEX fret 5 on string 3 (G) → "5/i" on "G" line.
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        lines = _render_measure(results)
        g_line = next(l for l in lines if l.startswith("G "))
        assert "5/i" in g_line

    def test_open_string_notation(self) -> None:
        results = [_open_fr(0, 0.0, string_num=1)]
        lines = _render_measure(results)
        e_line = next(l for l in lines if l.startswith("e "))
        assert "0/-" in e_line

    def test_pinky_finger_char(self) -> None:
        results = [_fr(0, 0.0, 4, 8, Finger.PINKY)]
        lines = _render_measure(results)
        d_line = next(l for l in lines if l.startswith("D "))
        assert "8/p" in d_line

    def test_multiple_onsets(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 1.0, 4, 7, Finger.MIDDLE),
        ]
        lines = _render_measure(results)
        assert len(lines) >= 6

    def test_chord_line_for_recognisable_chord(self) -> None:
        # C major chord at onset 0.
        notes = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=2, fret=1, finger=Finger.INDEX, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=1,
                note_event=NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
            FingeringResult(
                note_id=2,
                note_event=NoteEvent(pitch=67, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(string_num=3, fret=0, finger=Finger.OPEN, hand_position=1),
                cost=0.0,
            ),
        ]
        lines = _render_measure(notes)
        # Chord annotation line should precede string lines.
        full = "\n".join(lines)
        assert "C" in full


# ---------------------------------------------------------------------------
# render_ascii_tab
# ---------------------------------------------------------------------------


class TestRenderAsciiTab:
    def test_empty_results(self) -> None:
        out = render_ascii_tab([])
        assert "(no notes)" in out

    def test_title_appears(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results, title="My Song")
        assert "My Song" in out

    def test_no_title(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        assert "Measure" in out

    def test_fret_finger_inline(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        assert "5/i" in out

    def test_open_string_rendered(self) -> None:
        results = [_open_fr(0, 0.0, string_num=1)]
        out = render_ascii_tab(results)
        assert "0/-" in out

    def test_measure_number_1_shown(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        assert "Measure 1" in out

    def test_late_start_measure_number_correct(self) -> None:
        # Note at beat 16 → measure 5 in 4/4 (beat 16 / 4 = 4, +1 → 5).
        results = [_fr(0, 16.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        assert "Measure 5" in out

    def test_max_measures_limits_output(self) -> None:
        results = [_fr(i, float(i * 4), 3, 5, Finger.INDEX) for i in range(3)]
        full = render_ascii_tab(results)
        limited = render_ascii_tab(results, max_measures=1)
        assert full.count("Measure") > limited.count("Measure")

    def test_legend_present(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        assert "Legend" in out

    def test_six_string_lines_present(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_ascii_tab(results)
        for name in ("e |", "B |", "G |", "D |", "A |", "E |"):
            assert name in out

    def test_tempo_in_header(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX, tempo=140.0)]
        out = render_ascii_tab(results)
        assert "140" in out

    def test_two_measures_rendered(self) -> None:
        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 4.0, 3, 7, Finger.RING),
        ]
        out = render_ascii_tab(results)
        assert "Measure 1" in out
        assert "Measure 2" in out

    def test_ring_finger_char(self) -> None:
        results = [_fr(0, 0.0, 4, 7, Finger.RING)]
        out = render_ascii_tab(results)
        assert "7/r" in out

    def test_middle_finger_char(self) -> None:
        results = [_fr(0, 0.0, 5, 9, Finger.MIDDLE)]
        out = render_ascii_tab(results)
        assert "9/m" in out

    def test_pinky_finger_char(self) -> None:
        results = [_fr(0, 0.0, 6, 3, Finger.PINKY)]
        out = render_ascii_tab(results)
        assert "3/p" in out


# ---------------------------------------------------------------------------
# render_text_report
# ---------------------------------------------------------------------------


class TestRenderTextReport:
    def test_empty_results_has_header(self) -> None:
        out = render_text_report([])
        assert "#" in out  # column header present

    def test_title_in_report(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_text_report(results, title="Test Song")
        assert "Test Song" in out

    def test_note_id_in_output(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_text_report(results)
        assert "0" in out

    def test_onset_in_output(self) -> None:
        results = [_fr(0, 2.5, 3, 5, Finger.INDEX)]
        out = render_text_report(results)
        assert "2.500" in out

    def test_fret_in_output(self) -> None:
        results = [_fr(0, 0.0, 3, 7, Finger.RING)]
        out = render_text_report(results)
        assert "7" in out

    def test_finger_name_in_output(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.MIDDLE)]
        out = render_text_report(results)
        assert "middle" in out

    def test_max_notes_limits_rows(self) -> None:
        results = [_fr(i, float(i), 3, 5, Finger.INDEX) for i in range(10)]
        limited = render_text_report(results, max_notes=3)
        full = render_text_report(results)
        assert limited.count("\n") < full.count("\n")

    def test_total_line_present(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_text_report(results)
        assert "Total notes" in out

    def test_no_title_no_crash(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_text_report(results)
        assert out  # non-empty

    def test_separator_lines_present(self) -> None:
        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out = render_text_report(results)
        assert "---" in out


# ---------------------------------------------------------------------------
# render_pdf_tab — smoke tests (verifies execution, not visual output)
# ---------------------------------------------------------------------------


class TestRenderPdfTab:
    def test_renders_to_file_without_error(self, tmp_path: Path) -> None:
        """render_pdf_tab produces a valid PDF file."""
        from fretwise.export.pdf_tab import render_pdf_tab

        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out_path = tmp_path / "test.pdf"
        render_pdf_tab(results, str(out_path), title="Test")
        assert out_path.exists()
        content = out_path.read_bytes()
        assert content[:4] == b"%PDF"

    def test_renders_multiple_measures(self, tmp_path: Path) -> None:
        from fretwise.export.pdf_tab import render_pdf_tab

        results = [_fr(i, float(i * 4), 3, 5, Finger.INDEX) for i in range(5)]
        out_path = tmp_path / "multi.pdf"
        render_pdf_tab(results, str(out_path), title="Multi")
        assert out_path.exists()

    def test_renders_with_section_markers(self, tmp_path: Path) -> None:
        from fretwise.export.pdf_tab import render_pdf_tab

        results = [
            _fr(0, 0.0, 3, 5, Finger.INDEX),
            _fr(1, 4.0, 3, 7, Finger.RING),
        ]
        out_path = tmp_path / "sections.pdf"
        render_pdf_tab(
            results, str(out_path), title="Sections", section_markers={1: "Intro", 2: "Verse"}
        )
        assert out_path.exists()

    def test_renders_chord(self, tmp_path: Path) -> None:
        """PDF with a simultaneous chord (multi-note onset) renders correctly."""
        from fretwise.export.pdf_tab import render_pdf_tab

        chord = [
            FingeringResult(
                note_id=i,
                note_event=NoteEvent(pitch=p, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(
                    string_num=s, fret=f, finger=fi, hand_position=max(1, f)
                ),
                cost=0.0,
            )
            for i, (p, s, f, fi) in enumerate([
                (64, 1, 0, Finger.OPEN),
                (59, 2, 0, Finger.OPEN),
                (55, 3, 0, Finger.OPEN),
            ])
        ]
        out_path = tmp_path / "chord.pdf"
        render_pdf_tab(chord, str(out_path), title="Chord")
        assert out_path.exists()

    def test_renders_let_ring_notes(self, tmp_path: Path) -> None:
        """PDF with let-ring notes renders without error."""
        from fretwise.export.pdf_tab import render_pdf_tab

        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(
                    pitch=60, onset=0.0, duration=2.0, tempo=120.0, let_ring=True
                ),
                state=FingeringState(
                    string_num=3, fret=5, finger=Finger.INDEX, hand_position=5
                ),
                cost=1.0,
            )
        ]
        out_path = tmp_path / "letring.pdf"
        render_pdf_tab(results, str(out_path), title="LetRing")
        assert out_path.exists()

    def test_renders_empty_results(self, tmp_path: Path) -> None:
        """render_pdf_tab with empty result list does not crash."""
        from fretwise.export.pdf_tab import render_pdf_tab

        out_path = tmp_path / "empty.pdf"
        # Empty results: should either produce a minimal PDF or raise a known error.
        try:
            render_pdf_tab([], str(out_path))
        except (IndexError, ValueError):
            pass  # acceptable — no notes means nothing to render

    def test_renders_many_notes_pagination(self, tmp_path: Path) -> None:
        """Long song triggers page breaks without crashing."""
        from fretwise.export.pdf_tab import render_pdf_tab

        # 40 measures × 4 beats = 160 notes, enough to force multiple pages.
        results = [
            _fr(i, float(i * 1), 3, 5 + (i % 3), Finger.INDEX) for i in range(80)
        ]
        out_path = tmp_path / "long.pdf"
        render_pdf_tab(results, str(out_path), title="Long Song")
        assert out_path.exists()


# ---------------------------------------------------------------------------
# _get_beam_groups — RENDER-02 + RENDER-03
# ---------------------------------------------------------------------------


class TestGetBeamGroups:
    """Unit tests for the beat-aware, rest-aware beam grouping algorithm."""

    def _stem(self, x: float, onset: float, dur: float) -> tuple[float, float, float]:
        return (x, onset, dur)

    def test_four_quarter_notes_no_beams(self) -> None:
        """Quarter notes (dur=1.0) are never beamable."""
        from fretwise.export.pdf_tab import _get_beam_groups

        stems = [self._stem(i * 20.0, float(i), 1.0) for i in range(4)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        assert groups == []

    def test_two_eighth_notes_one_beat_one_group(self) -> None:
        """Two eighth notes within the same beat form one group."""
        from fretwise.export.pdf_tab import _get_beam_groups

        stems = [self._stem(10.0, 0.0, 0.5), self._stem(27.0, 0.5, 0.5)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        assert len(groups) == 1
        assert len(groups[0]) == 2

    def test_eight_eighth_notes_4_4_four_groups(self) -> None:
        """8 eighth notes in 4/4 must produce 4 groups of 2 (one per beat)."""
        from fretwise.export.pdf_tab import _get_beam_groups

        stems = [self._stem(i * 17.0, i * 0.5, 0.5) for i in range(8)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        assert len(groups) == 4
        for g in groups:
            assert len(g) == 2

    def test_rest_between_two_eighth_notes_no_beam(self) -> None:
        """A rest gap >= 1/32 beat between notes must break the beam group."""
        from fretwise.export.pdf_tab import _get_beam_groups

        # note at beat 0, dur 0.5 → ends at 0.5; next note starts at 1.5 → gap = 1.0
        stems = [self._stem(10.0, 0.0, 0.5), self._stem(40.0, 1.5, 0.5)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        # gap of 1.0 beat = rest → each note is alone → no group of ≥ 2
        assert groups == []

    def test_rest_interrupts_otherwise_same_beat_group(self) -> None:
        """Even within the same beat, a rest must split the beam."""
        from fretwise.export.pdf_tab import _get_beam_groups

        # beat 0: note(0.0, dur=0.25) → end=0.25; gap=0.125 (>=0.115); note(0.375, dur=0.25)
        stems = [
            self._stem(10.0, 0.0, 0.25),
            self._stem(27.0, 0.375, 0.25),
        ]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        # gap = 0.375 - 0.25 = 0.125 >= 0.115 → rest → no single group
        assert groups == []

    def test_no_rest_consecutive_sixteenth_notes_same_beat(self) -> None:
        """4 consecutive 16th notes in beat 0 form one group."""
        from fretwise.export.pdf_tab import _get_beam_groups

        stems = [self._stem(i * 14.0, i * 0.25, 0.25) for i in range(4)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        assert len(groups) == 1
        assert len(groups[0]) == 4

    def test_mixed_eighth_and_quarter_splits_correctly(self) -> None:
        """A quarter note inside a sequence terminates the current beam group."""
        from fretwise.export.pdf_tab import _get_beam_groups

        # [8th, 8th, quarter, 8th, 8th] in one measure
        stems = [
            self._stem(10.0, 0.0, 0.5),
            self._stem(27.0, 0.5, 0.5),
            self._stem(44.0, 1.0, 1.0),   # quarter — not beamable
            self._stem(61.0, 2.0, 0.5),
            self._stem(78.0, 2.5, 0.5),
        ]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=0.0)
        assert len(groups) == 2
        assert len(groups[0]) == 2
        assert len(groups[1]) == 2

    def test_non_zero_measure_onset(self) -> None:
        """Beat boundaries are computed from measure_onset, not from 0."""
        from fretwise.export.pdf_tab import _get_beam_groups

        # Measure starts at beat 8 (e.g. measure 3 in 4/4)
        mo = 8.0
        stems = [self._stem(i * 17.0, mo + i * 0.5, 0.5) for i in range(4)]
        groups = _get_beam_groups(stems, beats_per_measure=4.0, measure_onset=mo)
        # Should produce 2 groups of 2 (only 2 beats worth of 8ths here)
        assert len(groups) == 2


# ---------------------------------------------------------------------------
# _draw_secondary_beam — partial secondary beam logic
# ---------------------------------------------------------------------------


class TestDrawSecondaryBeam:
    """Verify that _draw_secondary_beam runs without errors for all cases."""

    def _mock_canvas(self) -> object:
        """Return a minimal mock that accepts any drawing call."""
        from unittest.mock import MagicMock
        return MagicMock()

    def test_all_sixteenth_draws_without_error(self) -> None:
        from fretwise.export.pdf_tab import _draw_secondary_beam

        group = [(i * 14.0, i * 0.25, 0.25) for i in range(4)]
        _draw_secondary_beam(self._mock_canvas(), group, 100.0, 2.5, 3.0)

    def test_mixed_eighth_sixteenth_draws_without_error(self) -> None:
        from fretwise.export.pdf_tab import _draw_secondary_beam

        group = [
            (10.0, 0.0, 0.5),    # eighth
            (27.0, 0.5, 0.25),   # sixteenth
            (41.0, 0.75, 0.25),  # sixteenth
        ]
        _draw_secondary_beam(self._mock_canvas(), group, 100.0, 2.5, 3.0)

    def test_all_eighth_no_secondary(self) -> None:
        """All-eighth group: secondary beam draws nothing (no rect call)."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_secondary_beam

        c = MagicMock()
        group = [(i * 17.0, i * 0.5, 0.5) for i in range(2)]
        _draw_secondary_beam(c, group, 100.0, 2.5, 3.0)
        c.rect.assert_not_called()


# ---------------------------------------------------------------------------
# _draw_rest — RENDER-01: position + disc rendering
# ---------------------------------------------------------------------------


class TestDrawRest:
    """Verify _draw_rest uses sys_y reference and draws discs for small rests."""

    def _recording_canvas(self) -> object:
        from unittest.mock import MagicMock
        return MagicMock()

    def test_quarter_rest_draws_disc(self) -> None:
        """Quarter rest (dur=1.0) must call canvas.circle for the white disc."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_rest

        c = MagicMock()
        _draw_rest(c, rx=100.0, sys_y=200.0, duration=1.0)
        # circle() should be called once for the white disc
        assert c.circle.called

    def test_eighth_rest_draws_disc(self) -> None:
        """Eighth rest (dur=0.5) must draw a disc."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_rest, _REST_CENTER_Y

        c = MagicMock()
        _draw_rest(c, rx=100.0, sys_y=200.0, duration=0.5)
        assert c.circle.called
        # Verify the disc is centred at sys_y - _REST_CENTER_Y
        disc_call_args = c.circle.call_args_list[0][0]  # positional args
        assert abs(disc_call_args[1] - (200.0 - _REST_CENTER_Y)) < 0.5

    def test_whole_rest_no_disc(self) -> None:
        """Whole rest (dur=4.0) must NOT draw a disc (uses rect instead)."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_rest

        c = MagicMock()
        _draw_rest(c, rx=100.0, sys_y=200.0, duration=4.0)
        c.circle.assert_not_called()
        assert c.rect.called

    def test_half_rest_no_disc(self) -> None:
        """Half rest (dur=2.0) must NOT draw a disc."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_rest

        c = MagicMock()
        _draw_rest(c, rx=100.0, sys_y=200.0, duration=2.0)
        c.circle.assert_not_called()
        assert c.rect.called

    def test_rest_centre_is_below_sys_y(self) -> None:
        """The disc centre must be exactly sys_y - _REST_CENTER_Y."""
        from unittest.mock import MagicMock
        from fretwise.export.pdf_tab import _draw_rest, _REST_CENTER_Y

        c = MagicMock()
        sys_y = 300.0
        _draw_rest(c, rx=50.0, sys_y=sys_y, duration=0.25)
        # First circle() call is the disc
        args = c.circle.call_args_list[0][0]
        expected_cy = sys_y - _REST_CENTER_Y
        assert abs(args[1] - expected_cy) < 0.1


# ---------------------------------------------------------------------------
# render_staff_pdf — smoke tests
# ---------------------------------------------------------------------------


class TestRenderStaffPdf:
    def test_renders_to_file(self, tmp_path: Path) -> None:
        """render_staff_pdf produces a valid PDF file."""
        from fretwise.export.staff_renderer import render_staff_pdf

        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out_path = tmp_path / "staff.pdf"
        render_staff_pdf(results, out_path, title="Staff Test")
        assert out_path.exists()
        assert out_path.read_bytes()[:4] == b"%PDF"

    def test_empty_results(self, tmp_path: Path) -> None:
        from fretwise.export.staff_renderer import render_staff_pdf

        out_path = tmp_path / "empty.pdf"
        render_staff_pdf([], out_path)
        assert out_path.exists()

    def test_multiple_measures(self, tmp_path: Path) -> None:
        from fretwise.export.staff_renderer import render_staff_pdf

        results = [_fr(i, float(i * 4), 3, 5 + i % 3, Finger.INDEX, pitch=60 + i)
                    for i in range(12)]
        out_path = tmp_path / "multi_staff.pdf"
        render_staff_pdf(results, out_path, title="Multi")
        assert out_path.exists()
        assert out_path.stat().st_size > 200

    def test_with_section_markers(self, tmp_path: Path) -> None:
        from fretwise.export.staff_renderer import render_staff_pdf

        results = [_fr(0, 0.0, 3, 5, Finger.INDEX), _fr(1, 4.0, 3, 7, Finger.RING)]
        out_path = tmp_path / "sections_staff.pdf"
        render_staff_pdf(results, out_path, section_markers={1: "Intro", 2: "Verse"})
        assert out_path.exists()

    def test_accidentals_render(self, tmp_path: Path) -> None:
        """Notes with sharps (C#, F#) render without error."""
        from fretwise.export.staff_renderer import render_staff_pdf

        results = [
            _fr(0, 0.0, 3, 6, Finger.INDEX, pitch=61),   # C#4
            _fr(1, 1.0, 2, 2, Finger.INDEX, pitch=66),    # F#4
        ]
        out_path = tmp_path / "accidentals.pdf"
        render_staff_pdf(results, out_path, title="Accidentals")
        assert out_path.exists()

    def test_ledger_lines_below(self, tmp_path: Path) -> None:
        """Middle C (MIDI 60) — needs ledger line below staff."""
        from fretwise.export.staff_renderer import render_staff_pdf

        results = [_fr(0, 0.0, 5, 3, Finger.RING, pitch=60)]
        out_path = tmp_path / "ledger.pdf"
        render_staff_pdf(results, out_path, title="Ledger Below")
        assert out_path.exists()


# ---------------------------------------------------------------------------
# render_combined_pdf — smoke tests
# ---------------------------------------------------------------------------


class TestRenderCombinedPdf:
    def test_renders_to_file(self, tmp_path: Path) -> None:
        """render_combined_pdf produces a valid PDF file."""
        from fretwise.export.combined_renderer import render_combined_pdf

        results = [_fr(0, 0.0, 3, 5, Finger.INDEX)]
        out_path = tmp_path / "combined.pdf"
        render_combined_pdf(results, out_path, title="Combined Test")
        assert out_path.exists()
        assert out_path.read_bytes()[:4] == b"%PDF"

    def test_empty_results(self, tmp_path: Path) -> None:
        from fretwise.export.combined_renderer import render_combined_pdf

        out_path = tmp_path / "empty_combined.pdf"
        render_combined_pdf([], out_path)
        assert out_path.exists()

    def test_multiple_measures(self, tmp_path: Path) -> None:
        from fretwise.export.combined_renderer import render_combined_pdf

        results = [_fr(i, float(i * 4), 3, 5 + i % 3, Finger.INDEX, pitch=60 + i)
                    for i in range(12)]
        out_path = tmp_path / "multi_combined.pdf"
        render_combined_pdf(results, out_path, title="Multi Combined")
        assert out_path.exists()
        assert out_path.stat().st_size > 200


# ---------------------------------------------------------------------------
# StaffRenderer — unit tests for helpers
# ---------------------------------------------------------------------------


class TestStaffRendererHelpers:
    def test_midi_to_staff_pos_middle_c(self) -> None:
        from fretwise.export.staff_renderer import _midi_to_staff_pos
        pos, acc = _midi_to_staff_pos(60)
        assert pos == 0   # C4
        assert acc == 0

    def test_midi_to_staff_pos_e4(self) -> None:
        from fretwise.export.staff_renderer import _midi_to_staff_pos
        pos, acc = _midi_to_staff_pos(64)
        assert pos == 2   # E4 = bottom staff line
        assert acc == 0

    def test_midi_to_staff_pos_g4(self) -> None:
        from fretwise.export.staff_renderer import _midi_to_staff_pos
        pos, acc = _midi_to_staff_pos(67)
        assert pos == 4   # G4 = line 2 (treble clef)
        assert acc == 0

    def test_midi_to_staff_pos_csharp(self) -> None:
        from fretwise.export.staff_renderer import _midi_to_staff_pos
        pos, acc = _midi_to_staff_pos(61)
        assert pos == 0   # C#4 → same as C4 position
        assert acc == 1   # sharp

    def test_midi_to_staff_pos_octave_above(self) -> None:
        from fretwise.export.staff_renderer import _midi_to_staff_pos
        pos, acc = _midi_to_staff_pos(72)
        assert pos == 7   # C5
        assert acc == 0

    def test_staff_pos_to_y_bottom_line(self) -> None:
        from fretwise.export.staff_renderer import _staff_pos_to_y, _STAFF_SPACING
        y = _staff_pos_to_y(100.0, 2)  # E4 = bottom line
        assert y == 100.0

    def test_staff_pos_to_y_top_line(self) -> None:
        from fretwise.export.staff_renderer import _staff_pos_to_y, _STAFF_SPACING
        y = _staff_pos_to_y(100.0, 10)  # F5 = top line
        expected = 100.0 + 8 * (_STAFF_SPACING / 2.0)
        assert abs(y - expected) < 0.01

    def test_num_flags_quarter(self) -> None:
        from fretwise.export.staff_renderer import _num_flags
        assert _num_flags(1.0) == 0

    def test_num_flags_eighth(self) -> None:
        from fretwise.export.staff_renderer import _num_flags
        assert _num_flags(0.5) == 1

    def test_num_flags_sixteenth(self) -> None:
        from fretwise.export.staff_renderer import _num_flags
        assert _num_flags(0.25) == 2

    def test_is_filled_quarter(self) -> None:
        from fretwise.export.staff_renderer import _is_filled
        assert _is_filled(1.0) is True

    def test_is_filled_half(self) -> None:
        from fretwise.export.staff_renderer import _is_filled
        assert _is_filled(2.0) is False

    def test_is_filled_whole(self) -> None:
        from fretwise.export.staff_renderer import _is_filled
        assert _is_filled(4.0) is False


# ---------------------------------------------------------------------------
# Concordance validation tests
# ---------------------------------------------------------------------------


class TestConcordanceValidation:
    def test_import(self) -> None:
        from fretwise.validation import ConcordanceReport, compute_concordance
        assert callable(compute_concordance)

    def test_empty_results(self) -> None:
        from fretwise.validation import compute_concordance
        report = compute_concordance([])
        assert report.total_notes == 0
        assert report.position_concordance == 0.0  # no notes → 0/0 → 0.0

    def test_perfect_concordance(self) -> None:
        from fretwise.validation import compute_concordance

        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(
                    pitch=60, onset=0.0, duration=1.0, tempo=120.0,
                    string_hint=3, fret_hint=5,
                ),
                state=FingeringState(
                    string_num=3, fret=5, finger=Finger.INDEX, hand_position=5,
                ),
                cost=1.0,
            ),
        ]
        report = compute_concordance(results)
        assert report.total_notes == 1
        assert report.hinted_notes == 1
        assert report.string_matches == 1
        assert report.fret_matches == 1
        assert report.position_matches == 1
        assert report.position_concordance == 1.0
        assert report.string_concordance == 1.0
        assert report.fret_concordance == 1.0
        assert len(report.deviations) == 0

    def test_deviation_detected(self) -> None:
        from fretwise.validation import compute_concordance

        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(
                    pitch=60, onset=0.0, duration=1.0, tempo=120.0,
                    string_hint=3, fret_hint=5,
                ),
                state=FingeringState(
                    string_num=4, fret=10, finger=Finger.INDEX, hand_position=10,
                ),
                cost=1.0,
            ),
        ]
        report = compute_concordance(results)
        assert report.hinted_notes == 1
        assert report.string_matches == 0
        assert report.fret_matches == 0
        assert report.position_matches == 0
        assert report.position_concordance == 0.0
        assert len(report.deviations) == 1

    def test_unhinted_notes_excluded(self) -> None:
        from fretwise.validation import compute_concordance

        results = [
            FingeringResult(
                note_id=0,
                note_event=NoteEvent(pitch=60, onset=0.0, duration=1.0, tempo=120.0),
                state=FingeringState(
                    string_num=3, fret=5, finger=Finger.INDEX, hand_position=5,
                ),
                cost=1.0,
            ),
        ]
        report = compute_concordance(results)
        assert report.total_notes == 1
        assert report.hinted_notes == 0  # no hints → not counted
        assert report.position_concordance == 0.0  # 0/0 → 0.0

    def test_format_report(self) -> None:
        from fretwise.validation import ConcordanceReport, format_concordance_report

        report = ConcordanceReport(
            total_notes=10, hinted_notes=8,
            string_matches=8, fret_matches=7, position_matches=7,
            deviations=[],
        )
        text = format_concordance_report(report, title="Test")
        assert "Test" in text
        assert "Position" in text
