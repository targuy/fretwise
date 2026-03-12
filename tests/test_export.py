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
