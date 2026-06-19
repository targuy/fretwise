"""Tests for the multitrack web API: /api/tracks listing + staff-only solve.

Covers the contract that FretWise imports *all* tracks (not just guitars) and
that non-guitar tracks (vocals/bass/drums/other) are served staff-only —
no Viterbi fingering — via the ``kind`` / ``fingered`` response fields.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fretwise.core.graphics import RepresentationMode
from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.web.app import create_app


def _route_endpoint(app: Any, path: str) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def _note(pitch: int, onset: float, string: int | None = 1, fret: int | None = 0) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=string,
        fret_hint=fret,
    )


class _MultiTrackAdapter:
    """Adapter stub exposing list_all_tracks + per-track parsing/metadata."""

    track_name: str = ""
    midi_program: int = -1
    section_markers: dict[int, str] = {}
    chord_diagrams: list[Any] = []
    chord_markers: dict[str, str] = {}
    beats_per_measure: float = 4.0
    measure_time_signatures: dict[int, tuple[int, int]] = {}
    key_signature_fifths: int = 0
    time_denominator: int = 4
    has_anacrusis: bool = False

    # id -> (name, tuning, kind)
    _TRACKS = {
        0: ("Lead Guitar", [40, 45, 50, 55, 59, 64], "guitar"),
        1: ("Lead Vocals", [39, 44, 49, 54, 58, 63], "vocal"),
        2: ("Bass", [28, 33, 38, 43], "bass"),
        3: ("Drums", [0, 0, 0, 0, 0, 0], "drums"),
    }

    def list_all_tracks(self, _path: Path) -> list[tuple[int, str, list[int], str]]:
        return [(tid, name, tuning, kind) for tid, (name, tuning, kind) in self._TRACKS.items()]

    def list_guitar_tracks(self, _path: Path) -> list[tuple[int, str, list[int]]]:
        return [
            (tid, name, tuning)
            for tid, (name, tuning, kind) in self._TRACKS.items()
            if kind == "guitar"
        ]

    def parse_track(self, _path: Path, track_id: int) -> list[NoteEvent]:
        self.track_name = self._TRACKS[track_id][0]
        return [_note(60, 0.0), _note(62, 1.0)]

    def parse(self, _path: Path) -> list[NoteEvent]:
        return self.parse_track(_path, 0)


# ---------------------------------------------------------------------------
# /api/tracks — list every instrument with kind
# ---------------------------------------------------------------------------


def test_list_tracks_returns_all_kinds(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    monkeypatch.setattr("fretwise.web.app.get_adapter", lambda _p: _MultiTrackAdapter())

    endpoint = _route_endpoint(app, "/api/tracks/{filename}")
    tracks = asyncio.run(endpoint(filename="song.gp"))

    assert [(t["id"], t["kind"]) for t in tracks] == [
        (0, "guitar"), (1, "vocal"), (2, "bass"), (3, "drums"),
    ]
    # Each entry exposes the frontend contract fields.
    for t in tracks:
        assert set(t) >= {"id", "name", "tuning", "kind"}
    assert tracks[2]["tuning"] == [28, 33, 38, 43]


def test_list_tracks_guitar_only_adapter_defaults_kind_guitar(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Adapter without list_all_tracks → guitar tracks tagged kind=guitar."""
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)

    class _GuitarOnly:
        def list_guitar_tracks(self, _p: Path) -> list[tuple[int, str, list[int]]]:
            return [(0, "Gtr", [40, 45, 50, 55, 59, 64])]

    monkeypatch.setattr("fretwise.web.app.get_adapter", lambda _p: _GuitarOnly())
    endpoint = _route_endpoint(app, "/api/tracks/{filename}")
    tracks = asyncio.run(endpoint(filename="song.gp"))
    assert tracks == [
        {"id": 0, "name": "Gtr", "tuning": [40, 45, 50, 55, 59, 64], "kind": "guitar"}
    ]


def test_list_tracks_single_track_adapter_is_guitar(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """MusicXML/MIDI-style adapter (no listing methods) → one guitar track."""
    file_path = tmp_path / "song.xml"
    file_path.touch()
    app = create_app(tmp_path)

    monkeypatch.setattr("fretwise.web.app.get_adapter", lambda _p: object())
    endpoint = _route_endpoint(app, "/api/tracks/{filename}")
    tracks = asyncio.run(endpoint(filename="song.xml"))
    assert len(tracks) == 1
    assert tracks[0]["kind"] == "guitar"
    assert tracks[0]["id"] == 0


# ---------------------------------------------------------------------------
# /api/solve — staff-only for non-guitar tracks (no Viterbi)
# ---------------------------------------------------------------------------


def _install_solve_stubs(monkeypatch: Any, adapter: Any, call_log: dict[str, int]) -> None:
    from fretwise.web.app import _solve_cache_clear

    _solve_cache_clear()

    def _fake_load(
        _fp: Path, *, track_id: int | None = None
    ) -> tuple[Any, list[NoteEvent]]:
        if track_id is not None:
            events = adapter.parse_track(_fp, track_id)
        else:
            events = adapter.parse(_fp)
        return adapter, events

    def _fake_legacy(
        events: list[NoteEvent], *, rule_preferences: Any = None
    ) -> tuple[list[Any], dict[str, int]]:
        del rule_preferences
        call_log["legacy"] = call_log.get("legacy", 0) + 1
        results = [
            SimpleNamespace(
                note_id=i + 1,
                note_event=ev,
                state=SimpleNamespace(string_num=1, fret=0, finger="1", hand_position=0),
                cost=0.0,
                planted_fingers={},
            )
            for i, ev in enumerate(events)
        ]
        return results, {"parsed": len(events)}

    def _fake_core(*_a: Any, **kwargs: Any) -> Any:
        call_log["core_mode"] = kwargs["representation_mode"]
        return SimpleNamespace(
            svg="<svg/>", conformance_issues=[],
            render_scene=None, canonical_score=None,
        )

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline", _fake_legacy)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _fake_core)


def test_solve_guitar_track_is_fingered(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _MultiTrackAdapter()
    call_log: dict[str, int] = {}
    _install_solve_stubs(monkeypatch, adapter, call_log)

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    payload = endpoint(filename="song.gp", track_id=0, representation_mode="standard_tablature")

    assert payload["kind"] == "guitar"
    assert payload["fingered"] is True
    # /api/solve no longer runs Viterbi — fingerings come from the sidecar (or
    # embedded GP data). With neither present, the guitar track renders as
    # tablature with no finger annotations and flags has_saved_fingering=False.
    assert call_log.get("legacy", 0) == 0
    assert call_log["core_mode"] == RepresentationMode.STANDARD_TAB
    assert payload["has_saved_fingering"] is False
    assert payload["results"] == []


def test_solve_vocal_track_is_staff_only(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _MultiTrackAdapter()
    call_log: dict[str, int] = {}
    _install_solve_stubs(monkeypatch, adapter, call_log)

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    payload = endpoint(filename="song.gp", track_id=1, representation_mode="standard_tablature")

    assert payload["kind"] == "vocal"
    assert payload["fingered"] is False
    # Viterbi must NOT run for non-guitar tracks.
    assert call_log.get("legacy", 0) == 0
    # Tab is meaningless → forced to standard (staff-only) render.
    assert payload["representation_mode"] == "standard"
    assert call_log["core_mode"] == RepresentationMode.STANDARD
    # Every result is un-fingered (null string/fret/finger) but keeps pitch.
    assert len(payload["results"]) == 2
    for r in payload["results"]:
        assert r["string"] is None and r["fret"] is None and r["finger"] is None
        assert r["pitch"] in (60, 62)


def test_solve_drums_track_does_not_error(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _MultiTrackAdapter()
    call_log: dict[str, int] = {}
    _install_solve_stubs(monkeypatch, adapter, call_log)

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    payload = endpoint(filename="song.gp", track_id=3, representation_mode="tablature")
    assert payload["kind"] == "drums"
    assert payload["fingered"] is False
    assert call_log.get("legacy", 0) == 0
    assert payload["stats"]["fingered"] == 0


# ---------------------------------------------------------------------------
# /api/notes — staff-only for non-guitar tracks
# ---------------------------------------------------------------------------


def test_notes_vocal_track_is_staff_only(monkeypatch: Any, tmp_path: Path) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _MultiTrackAdapter()
    call_log: dict[str, int] = {}
    _install_solve_stubs(monkeypatch, adapter, call_log)

    endpoint = _route_endpoint(app, "/api/notes/{filename}")
    payload = asyncio.run(endpoint(filename="song.gp", track_id=2))  # bass
    assert payload["kind"] == "bass"
    assert payload["fingered"] is False
    assert call_log.get("legacy", 0) == 0
    for r in payload["results"]:
        assert r["finger"] is None and r["string"] is None
