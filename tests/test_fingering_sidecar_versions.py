"""A one-track recompute must not certify other tracks from an older pipeline."""
from __future__ import annotations

import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from fretwise.export.gp_writer import GPIF_CONTENT_NAME
from fretwise.models import (
    Articulation,
    Dynamic,
    Finger,
    FingeringResult,
    FingeringState,
    NoteEvent,
)
from fretwise.web.app import (
    FINGERING_ALGO_VERSION,
    _current_sidecar_fingering_mapping,
    _fingering_data_path,
    _fingering_meta_path,
    _fingering_sidecar_tracks_are_current,
    _read_fingering_meta,
    _serialize_result,
    _solve_cache_clear,
    _write_fingering_sidecar,
    create_app,
)


def _result(source_id: str = "0", finger: Finger = Finger.INDEX) -> FingeringResult:
    return FingeringResult(
        note_id=1,
        note_event=NoteEvent(
            pitch=69, onset=0.0, duration=1.0, tempo=120.0,
            articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
            string_hint=1, fret_hint=5, source_note_id=source_id,
        ),
        state=FingeringState(string_num=1, fret=5, finger=finger, hand_position=5),
        cost=0.0,
    )


@pytest.fixture
def score(tmp_path: Path) -> Path:
    path = tmp_path / "song.gp"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr(
            GPIF_CONTENT_NAME,
            '<GPIF><Notes><Note id="0"><LeftFingering>A</LeftFingering></Note>'
            '<Note id="1"><LeftFingering>C</LeftFingering></Note></Notes></GPIF>',
        )
    return path


def _legacy_sidecar(
    score: Path, *, version: str = "2.1", tracks: bool = True,
) -> dict[str, object]:
    old = {"results": [_serialize_result(_result("1", Finger.PINKY))],
           "audit": {"available": True, "overall": "old-audit"}}
    _fingering_meta_path(score).write_text(json.dumps({
        "algo_version": version, "source_mtime": score.stat().st_mtime, "track_id": 1,
    }), encoding="utf-8")
    _fingering_data_path(score).write_text(json.dumps({
        **old, "tracks": {"1": old} if tracks else {},
    }), encoding="utf-8")
    return old


@pytest.mark.parametrize("with_tracks", [True, False])
def test_recompute_preserves_old_track_payload_and_version(score: Path, with_tracks: bool) -> None:
    old = _legacy_sidecar(score, tracks=with_tracks)

    assert _write_fingering_sidecar(score, [_result()], track_id=3)
    data = json.loads(_fingering_data_path(score).read_text(encoding="utf-8"))

    assert data["tracks"]["1"] == {**old, "algo_version": "2.1"}
    assert data["tracks"]["3"]["algo_version"] == FINGERING_ALGO_VERSION
    assert data["results"] == data["tracks"]["3"]["results"]
    assert _read_fingering_meta(score)["algo_version"] == FINGERING_ALGO_VERSION
    # A second save must preserve the explicit old version, despite the new header.
    assert _write_fingering_sidecar(score, [_result()], track_id=3)
    again = json.loads(_fingering_data_path(score).read_text(encoding="utf-8"))
    assert again["tracks"]["1"] == data["tracks"]["1"]


def test_missing_old_header_keeps_unknown_track_version(score: Path) -> None:
    _legacy_sidecar(score)
    _fingering_meta_path(score).unlink()
    assert _write_fingering_sidecar(score, [_result()], track_id=3)
    data = json.loads(_fingering_data_path(score).read_text(encoding="utf-8"))
    assert data["tracks"]["1"]["algo_version"] is None


def test_stale_track_is_not_merged_as_current_or_skipped_by_batch(score: Path) -> None:
    _legacy_sidecar(score)
    assert _write_fingering_sidecar(score, [_result()], track_id=3)
    meta = _read_fingering_meta(score)
    assert meta is not None
    assert _current_sidecar_fingering_mapping(score) == {"0": "I"}
    assert not _fingering_sidecar_tracks_are_current(meta, score)
    assert _write_fingering_sidecar(score, [_result("1")], track_id=1)
    assert _fingering_sidecar_tracks_are_current(_read_fingering_meta(score), score)


def test_failed_data_write_does_not_publish_new_version(
    score: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    _legacy_sidecar(score)
    previous_header = _fingering_meta_path(score).read_bytes()
    original = Path.write_text

    def fail_data(path: Path, *args: Any, **kwargs: Any) -> int:
        # Any preserves the stdlib method's call signature in this I/O failure probe.
        if path == _fingering_data_path(score):
            raise OSError("simulated full disk")
        return original(path, *args, **kwargs)

    monkeypatch.setattr(Path, "write_text", fail_data)
    assert not _write_fingering_sidecar(score, [_result()], track_id=3)
    assert _fingering_meta_path(score).read_bytes() == previous_header


@pytest.mark.parametrize("legacy_current", [False, True])
def test_solve_checks_selected_track_and_reads_data_only_once(
    score: Path, monkeypatch: pytest.MonkeyPatch, legacy_current: bool,
) -> None:
    _legacy_sidecar(score, version=FINGERING_ALGO_VERSION if legacy_current else "2.1")
    if not legacy_current:
        assert _write_fingering_sidecar(score, [_result()], track_id=3)
    _solve_cache_clear()
    app = create_app(score.parent)
    adapter = SimpleNamespace(
        track_name="Guitar", midi_program=24, section_markers={}, chord_diagrams=[],
        chord_markers={}, beats_per_measure=4.0, measure_time_signatures={}, time_denominator=4,
    )
    monkeypatch.setattr(
        "fretwise.web.app._load_adapter_and_events",
        lambda *_args, **_kwargs: (adapter, [_result().note_event]),
    )
    monkeypatch.setattr(
        "fretwise.web.app._run_core_pipeline_for_events",
        lambda *_args, **_kwargs: SimpleNamespace(
            svg="<svg/>", conformance_issues=[], render_scene=None, canonical_score=None,
        ),
    )
    data_reads: list[Path] = []
    original_read = Path.read_text

    def counted_read(path: Path, *args: Any, **kwargs: Any) -> str:
        # Any preserves the stdlib call signature while counting only the large sidecar.
        if path == _fingering_data_path(score):
            data_reads.append(path)
        return original_read(path, *args, **kwargs)

    monkeypatch.setattr(Path, "read_text", counted_read)
    endpoint = next(
        r.endpoint for r in app.routes if getattr(r, "path", "") == "/api/solve/{filename}"
    )
    old = endpoint(filename=score.name, track_id=1, representation_mode="standard_tablature")
    assert len(data_reads) == 1
    assert old["fingering_is_current"] is legacy_current
    if legacy_current:
        assert old["stats"]["from_sidecar"] is True
    else:
        assert old["fingering_algo_version"] == "2.1"
        assert old["stats"]["from_embedded"] is True
        assert old["results"][0]["finger"] == "ring"
        assert old["audit"] == {}
        new = endpoint(filename=score.name, track_id=3, representation_mode="standard_tablature")
        assert len(data_reads) == 2
        assert new["fingering_is_current"] is True
        assert new["stats"]["from_sidecar"] is True
        missing = endpoint(
            filename=score.name, track_id=9, representation_mode="standard_tablature",
        )
        assert missing["fingering_is_current"] is False


def test_batch_does_not_skip_missing_or_malformed_data(score: Path) -> None:
    _legacy_sidecar(score, version=FINGERING_ALGO_VERSION)
    meta = _read_fingering_meta(score)
    assert meta is not None
    assert _fingering_sidecar_tracks_are_current(meta, score)
    _fingering_data_path(score).write_text("[]", encoding="utf-8")
    assert not _fingering_sidecar_tracks_are_current(meta, score)
    _fingering_data_path(score).unlink()
    assert not _fingering_sidecar_tracks_are_current(meta, score)
