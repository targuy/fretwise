"""Tests for fretwise.export.hand_viz — JSON export for hand visualization."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fretwise.export.hand_viz import export_hand_viz_json
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent


def _make_result(
    note_id: int,
    pitch: int,
    onset: float,
    duration: float,
    *,
    tempo: float = 120.0,
    string_num: int = 1,
    fret: int = 5,
    finger: Finger = Finger.INDEX,
    hand_position: int = 5,
    voice_hint: int | None = None,
    planted: dict[str, tuple[int, int]] | None = None,
) -> FingeringResult:
    ne = NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=duration,
        tempo=tempo,
        voice_hint=voice_hint,
    )
    st = FingeringState(
        string_num=string_num,
        fret=fret,
        finger=finger,
        hand_position=hand_position,
    )
    return FingeringResult(
        note_id=note_id,
        note_event=ne,
        state=st,
        cost=0.0,
        planted_fingers=planted or {},
    )


class TestExportHandVizJson:
    def test_empty_results_writes_skeleton(self, tmp_path: Path) -> None:
        out = tmp_path / "viz.json"
        data = export_hand_viz_json([], out, title="t", artist="a")
        assert out.exists()
        assert data["frames"] == []
        assert data["meta"]["title"] == "t"
        assert data["meta"]["artist"] == "a"
        assert data["meta"]["tempo"] == 120.0  # default when results empty

    def test_default_tuning_is_standard(self, tmp_path: Path) -> None:
        out = tmp_path / "viz.json"
        data = export_hand_viz_json([], out)
        assert data["fretboard"]["tuning"] == ["E2", "A2", "D3", "G3", "B3", "E4"]
        assert data["fretboard"]["num_frets"] == 15
        assert data["fretboard"]["scale_length_mm"] == pytest.approx(648.0)

    def test_custom_tuning_is_preserved(self, tmp_path: Path) -> None:
        out = tmp_path / "viz.json"
        custom = ["D2", "A2", "D3", "G3", "B3", "E4"]
        data = export_hand_viz_json([], out, tuning=custom)
        assert data["fretboard"]["tuning"] == custom

    def test_single_note_serialization(self, tmp_path: Path) -> None:
        out = tmp_path / "viz.json"
        r = _make_result(
            note_id=0, pitch=64, onset=0.0, duration=1.0,
            string_num=1, fret=0, finger=Finger.OPEN, hand_position=1,
        )
        data = export_hand_viz_json([r], out)
        assert len(data["frames"]) == 1
        f = data["frames"][0]
        assert f["note_id"] == 0
        assert f["pitch"] == 64
        assert f["string"] == 1
        assert f["fret"] == 0
        assert f["finger"] == "open"
        assert f["hand_position"] == 1
        assert f["voice"] == 0  # None → 0
        assert f["planted"] == {}

    def test_first_onset_is_normalized_to_zero(self, tmp_path: Path) -> None:
        # The first onset becomes t=0 — subsequent onsets are deltas.
        r0 = _make_result(0, 64, onset=4.0, duration=1.0, tempo=120.0)
        r1 = _make_result(1, 65, onset=6.0, duration=1.0, tempo=120.0)
        data = export_hand_viz_json([r0, r1], tmp_path / "viz.json", max_seconds=10.0)
        assert data["frames"][0]["onset_sec"] == pytest.approx(0.0)
        # 2 beats at 120bpm = 1 second
        assert data["frames"][1]["onset_sec"] == pytest.approx(1.0)
        assert data["frames"][0]["onset_beat"] == pytest.approx(0.0)
        assert data["frames"][1]["onset_beat"] == pytest.approx(2.0)

    def test_max_seconds_truncates(self, tmp_path: Path) -> None:
        # At 120 bpm, 1 beat = 0.5 s. With max_seconds=1.0, only the first 2 beats fit.
        results = [
            _make_result(i, 60 + i, onset=float(i), duration=0.5, tempo=120.0)
            for i in range(5)
        ]
        data = export_hand_viz_json(results, tmp_path / "viz.json", max_seconds=1.0)
        # onsets 0.0s, 0.5s, 1.0s, 1.5s, 2.0s — onsets >= 1.0s are excluded.
        assert len(data["frames"]) == 2

    def test_planted_fingers_serialized_as_dict_of_lists(self, tmp_path: Path) -> None:
        r = _make_result(
            0, 64, 0.0, 1.0,
            planted={"index": (1, 5), "middle": (2, 6)},
        )
        data = export_hand_viz_json([r], tmp_path / "viz.json")
        planted = data["frames"][0]["planted"]
        assert planted == {"index": [1, 5], "middle": [2, 6]}
        # Tuples must round-trip as lists for valid JSON.
        assert isinstance(planted["index"], list)

    def test_duration_floor_for_very_short_notes(self, tmp_path: Path) -> None:
        # The export clamps duration_sec to at least 0.08.
        r = _make_result(0, 64, 0.0, duration=0.001, tempo=120.0)
        data = export_hand_viz_json([r], tmp_path / "viz.json")
        assert data["frames"][0]["duration_sec"] == pytest.approx(0.08)

    def test_voice_hint_preserved(self, tmp_path: Path) -> None:
        r = _make_result(0, 64, 0.0, 1.0, voice_hint=2)
        data = export_hand_viz_json([r], tmp_path / "viz.json")
        assert data["frames"][0]["voice"] == 2

    def test_tempo_taken_from_first_note(self, tmp_path: Path) -> None:
        r = _make_result(0, 64, 0.0, 1.0, tempo=90.0)
        data = export_hand_viz_json([r], tmp_path / "viz.json")
        assert data["meta"]["tempo"] == pytest.approx(90.0)

    def test_output_is_valid_json(self, tmp_path: Path) -> None:
        r = _make_result(0, 64, 0.0, 1.0)
        out = tmp_path / "viz.json"
        export_hand_viz_json([r], out, title="X", artist="Y", track_name="Z")
        # Round-trip via json.loads to confirm valid serialization.
        parsed = json.loads(out.read_text(encoding="utf-8"))
        assert parsed["meta"]["title"] == "X"
        assert parsed["meta"]["artist"] == "Y"
        assert parsed["meta"]["track"] == "Z"

    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        out = tmp_path / "nested" / "deeper" / "viz.json"
        export_hand_viz_json([], out)
        assert out.exists()

    def test_string_and_fret_are_ints(self, tmp_path: Path) -> None:
        r = _make_result(0, 64, 0.0, 1.0, string_num=3, fret=7)
        data = export_hand_viz_json([r], tmp_path / "viz.json")
        assert data["frames"][0]["string"] == 3
        assert data["frames"][0]["fret"] == 7
        assert isinstance(data["frames"][0]["string"], int)
        assert isinstance(data["frames"][0]["fret"], int)
