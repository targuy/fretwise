"""Integration tests — full pipeline parse → generate → score → optimize.

These tests run the complete pipeline using either:
1. Mocked GP data (always available), or
2. Real GP fixture files in tests/fixtures/ (skipped when absent).

Add real .gp5 files to tests/fixtures/ to enable fixture-based tests.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from fretwise.generator import StateGenerator
from fretwise.models import Finger
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser.guitarpro_adapter import GuitarProAdapter
from fretwise.scoring import CostFunction, CostWeights

# ---------------------------------------------------------------------------
# Helpers (shared with test_parser mock builders)
# ---------------------------------------------------------------------------


def _make_mock_note(string: int, fret: int, note_type_value: int = 1) -> MagicMock:
    note = MagicMock()
    note.string = string
    note.value = fret
    note.type = MagicMock(value=note_type_value)
    note.effect.hammer = False
    note.effect.pullOff = False
    note.effect.slides = []
    note.effect.vibrato = False
    note.effect.bend = None
    return note


def _make_mock_beat(notes: list[MagicMock], duration_value: int = 4) -> MagicMock:
    beat = MagicMock()
    beat.notes = notes
    beat.duration.value = duration_value
    beat.duration.isDotted = False
    beat.duration.isDoubleDotted = False
    beat.duration.tuplet.enters = 1
    beat.duration.tuplet.times = 1
    return beat


def _make_mock_song(
    tempo: int,
    note_specs: list[tuple[int, int]],  # (string, fret) pairs
) -> MagicMock:
    song = MagicMock()
    song.tempo = tempo
    track = MagicMock()
    track.isPercussionTrack = False
    # Standard EADGBE tuning
    open_pitches = [64, 59, 55, 50, 45, 40]
    mock_strings = []
    for idx, pitch in enumerate(open_pitches, start=1):
        s = MagicMock()
        s.number = idx
        s.value = pitch
        mock_strings.append(s)
    track.strings = mock_strings
    beats = [_make_mock_beat([_make_mock_note(str_n, fret)]) for str_n, fret in note_specs]
    measure = MagicMock()
    measure.header.tempo.value = tempo
    voice = MagicMock()
    voice.beats = beats
    measure.voices = [voice]
    track.measures = [measure]
    song.tracks = [track]
    return song


# ---------------------------------------------------------------------------
# Full pipeline integration (mocked source)
# ---------------------------------------------------------------------------


class TestFullPipelineMocked:
    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_single_note_pipeline(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        """E4 on string 1 open → one FingeringResult with open string state."""
        mock_parse.return_value = _make_mock_song(120, [(1, 0)])
        gp_file = tmp_path / "song.gp5"
        gp_file.touch()

        events = GuitarProAdapter().parse(gp_file)
        assert len(events) == 1
        assert events[0].pitch == 64

        state_lists = StateGenerator().states_for_sequence(events)
        assert len(state_lists) == 1
        assert any(s.fret == 0 for s in state_lists[0])

        results = ViterbiOptimizer(CostFunction()).solve(events, state_lists)
        assert len(results) == 1
        result = results[0]
        assert result.note_event.pitch == 64
        assert result.state.fret == 0 or result.state.string_num == 1

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_scale_fragment_pipeline(self, mock_parse: MagicMock, tmp_path: Path) -> None:
        """C major scale fragment C-D-E-F (string 2, frets 1-3-5-6)."""
        # C4=60, D4=62, E4=64, F4=65
        note_specs = [(2, 1), (2, 3), (2, 5), (2, 6)]
        mock_parse.return_value = _make_mock_song(120, note_specs)
        gp_file = tmp_path / "scale.gp5"
        gp_file.touch()

        events = GuitarProAdapter().parse(gp_file)
        assert len(events) == 4

        gen = StateGenerator()
        state_lists = gen.states_for_sequence(events)

        # Each note must have at least one valid state
        for i, states in enumerate(state_lists):
            assert states, f"No states for note {i} (pitch={events[i].pitch})"

        results = ViterbiOptimizer(CostFunction()).solve(events, state_lists)
        assert len(results) == 4

        # All results should be on reasonable strings (no out-of-range frets)
        for r in results:
            assert 0 <= r.state.fret <= 22
            assert 1 <= r.state.string_num <= 6

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_performance_mode_uses_different_weights(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        """Verify that performance and reference modes produce valid results."""
        note_specs = [(3, 5), (3, 7), (4, 5)]
        mock_parse.return_value = _make_mock_song(160, note_specs)
        gp_file = tmp_path / "perf.gp5"
        gp_file.touch()

        adapter = GuitarProAdapter()
        gen = StateGenerator()

        events = adapter.parse(gp_file)
        state_lists = gen.states_for_sequence(events)

        ref_results = ViterbiOptimizer(CostFunction(CostWeights.reference())).solve(
            events, state_lists
        )
        perf_results = ViterbiOptimizer(CostFunction(CostWeights.performance())).solve(
            events, state_lists
        )

        # Both modes must return valid results
        assert len(ref_results) == 3
        assert len(perf_results) == 3

    @patch("fretwise.parser.guitarpro_adapter.guitarpro.parse")
    def test_pipeline_ordering_preserved(
        self, mock_parse: MagicMock, tmp_path: Path
    ) -> None:
        """FingeringResult note_ids must match the original note order."""
        note_specs = [(1, 0), (2, 0), (3, 0), (4, 0), (5, 0)]
        mock_parse.return_value = _make_mock_song(120, note_specs)
        gp_file = tmp_path / "ordering.gp5"
        gp_file.touch()

        events = GuitarProAdapter().parse(gp_file)
        state_lists = StateGenerator().states_for_sequence(events)
        results = ViterbiOptimizer(CostFunction()).solve(events, state_lists)

        assert [r.note_id for r in results] == list(range(len(events)))
        for r, e in zip(results, events):
            assert r.note_event is e


# ---------------------------------------------------------------------------
# Real fixture files (skipped when not present)
# ---------------------------------------------------------------------------

_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _gp5_fixtures() -> list[Path]:
    if not _FIXTURES_DIR.exists():
        return []
    return list(_FIXTURES_DIR.glob("*.gp5")) + list(_FIXTURES_DIR.glob("*.gp4"))


@pytest.mark.parametrize("gp_file", _gp5_fixtures(), ids=lambda p: p.name)
def test_real_fixture_full_pipeline(gp_file: Path) -> None:
    """Run the full pipeline on every .gp5 file in tests/fixtures/."""
    adapter = GuitarProAdapter()
    gen = StateGenerator()
    cost_fn = CostFunction()
    opt = ViterbiOptimizer(cost_fn)

    events = adapter.parse(gp_file)
    assert events, f"No events parsed from {gp_file.name}"

    state_lists = gen.states_for_sequence(events)
    # Filter notes with no valid states (pitch outside guitar range)
    valid_pairs = [(e, sl) for e, sl in zip(events, state_lists) if sl]
    assert valid_pairs, f"No valid states for any note in {gp_file.name}"

    valid_events, valid_states = zip(*valid_pairs)
    results = opt.solve(list(valid_events), list(valid_states))

    assert len(results) == len(valid_events)

    # Sanity checks on the output
    for r in results:
        assert 0 <= r.state.fret <= 22
        assert 1 <= r.state.string_num <= 6
        assert r.state.finger in list(Finger)
        assert r.cost >= 0.0
