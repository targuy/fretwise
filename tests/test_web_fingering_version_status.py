"""HTTP contract for selected-track fingering provenance and explicit recompute."""

from __future__ import annotations

import asyncio
import json
import os
import threading
import zipfile
from collections.abc import AsyncGenerator
from contextvars import ContextVar
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient

from fretwise.export.gp_writer import GPIF_CONTENT_NAME, write_gp_with_fingerings
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.storage.base import StorageError, StorageObject
from fretwise.storage.remote import RemoteStorageBackend
from fretwise.web.app import (
    FINGERING_ALGO_VERSION,
    _fingering_data_path,
    _fingering_meta_path,
    _read_embedded_gp_fingerings,
    _serialize_result,
    _solve_cache_clear,
    _stream_fingering_save,
    create_app,
)


@dataclass
class _Case:
    app: FastAPI
    source: Path
    results: dict[int, FingeringResult]


@pytest.fixture
def case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Case:
    """Exercise HTTP, sidecars, GP annotation and storage; stub parsing/engraving."""
    _solve_cache_clear()
    monkeypatch.setattr("fretwise.web.app._settings.load", lambda: {})
    source = tmp_path / "song.gp"
    with zipfile.ZipFile(source, "w") as archive:
        notes = "".join(
            f'<Note id="{track}"><Properties><Property name="Fret"><Fret>5</Fret>'
            '</Property></Properties></Note>' for track in (1, 3, 9)
        )
        archive.writestr(GPIF_CONTENT_NAME, f"<GPIF><Notes>{notes}</Notes></GPIF>")
    results = {}
    for track in (1, 3, 9):
        note = NoteEvent(
            pitch=69, onset=0, duration=1, tempo=120, string_hint=1, fret_hint=5,
            source_note_id=str(track), voice_hint=0, measure_index=1,
        )
        results[track] = FingeringResult(
            0, note, FingeringState(1, 5, Finger.INDEX, 5), 0,
        )
    adapter = SimpleNamespace(
        track_name="Guitar", midi_program=24, beats_per_measure=4,
        measure_time_signatures={1: (4, 4)},
    )

    def parse(path: Path, *, track_id: int | None = None) -> tuple[object, list[NoteEvent]]:
        assert path == source
        return adapter, [results[track_id or 1].note_event]

    def forbid_compute(*args: object, **kwargs: object) -> None:
        raise AssertionError("Opening a track must not compute or save new fingerings")

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", parse)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", forbid_compute)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", lambda *args, **kwargs:
                        SimpleNamespace(svg="<svg/>", conformance_issues=[],
                                        render_scene=None, canonical_score=None))
    app = create_app(tmp_path, allowed_hosts=["testserver"])
    return _Case(app, source, results)


def _sidecar(
    case: _Case, *, header: str | None,
    tracks: dict[int, str | None], inherit_header: bool = False,
) -> None:
    first = next(iter(tracks))
    entries = {}
    for track, version in tracks.items():
        entry: dict[str, object] = {"results": [_serialize_result(case.results[track])]}
        if not inherit_header:
            entry["algo_version"] = version
        entries[str(track)] = entry
    _fingering_data_path(case.source).write_text(json.dumps({
        "results": entries[str(first)]["results"], "tracks": entries,
    }), encoding="utf-8")
    _fingering_meta_path(case.source).write_text(json.dumps({
        "algo_version": header, "track_id": first,
        "source_mtime": case.source.stat().st_mtime,
    }), encoding="utf-8")


def _solve(client: TestClient, track: int = 1) -> dict[str, object]:
    response = client.get("/api/solve/song.gp", params={"track_id": track})
    assert response.status_code == 200, response.text
    payload: dict[str, object] = response.json()
    assert payload["fingering_current_algo_version"] == FINGERING_ALGO_VERSION
    return payload


@pytest.mark.parametrize(
    ("version", "outdated", "current"),
    [("2.1", True, False), ("2.2", True, False), ("2.3", False, True),
     ("2.4", False, False), ("2.10", False, False), ("2.3.0", False, False), (None, False, False),
     ("embedded", False, False), ("unknown", False, False)],
)
def test_numeric_versions_distinguish_older_current_future_and_unknown(
    case: _Case, version: str | None, outdated: bool, current: bool,
) -> None:
    _sidecar(case, header=version, tracks={1: version})
    before = {path.name: path.read_bytes() for path in case.source.parent.glob("*")}
    result = _solve(TestClient(case.app))
    assert result["has_saved_fingering"] is True
    assert result["fingering_algo_version"] == version
    assert result["fingering_is_outdated"] is outdated
    assert result["fingering_is_current"] is current
    assert {path.name: path.read_bytes() for path in case.source.parent.glob("*")} == before


@pytest.mark.parametrize("header", ["2.1", "2.2", "3.0"])
def test_selected_track_version_overrides_header_in_both_directions(
    case: _Case, header: str,
) -> None:
    _sidecar(case, header=header, tracks={1: "2.1", 3: FINGERING_ALGO_VERSION})
    client = TestClient(case.app)
    old = _solve(client, 1)
    current = _solve(client, 3)
    missing = _solve(client, 9)
    assert (old["fingering_algo_version"], old["fingering_is_outdated"]) == ("2.1", True)
    assert (current["fingering_algo_version"], current["fingering_is_current"]) == (
        FINGERING_ALGO_VERSION, True,
    )
    assert current["fingering_is_outdated"] is False
    assert missing["fingering_algo_version"] is None
    assert missing["has_saved_fingering"] is False
    assert missing["fingering_is_outdated"] is False


def test_legacy_entry_inherits_header_but_explicit_unknown_does_not(case: _Case) -> None:
    _sidecar(case, header="2.1", tracks={1: None}, inherit_header=True)
    client = TestClient(case.app)
    assert _solve(client)["fingering_is_outdated"] is True
    _sidecar(case, header="2.1", tracks={1: None})
    result = _solve(client)
    assert result["fingering_algo_version"] is None
    assert result["fingering_is_outdated"] is False


@pytest.mark.parametrize("version", ["2.1", FINGERING_ALGO_VERSION])
def test_changed_source_never_becomes_current_from_track_version(
    case: _Case, version: str,
) -> None:
    _sidecar(case, header=FINGERING_ALGO_VERSION, tracks={1: version})
    client = TestClient(case.app)
    _solve(client)
    changed = case.source.stat().st_mtime + 10
    os.utime(case.source, (changed, changed))
    result = _solve(client)
    assert result["fingering_is_current"] is False
    assert result["fingering_is_outdated"] is (version == "2.1")
    assert result["results"] == []


def test_no_saved_or_other_track_embedded_is_not_an_old_algorithm(case: _Case) -> None:
    client = TestClient(case.app)
    absent = _solve(client, 1)
    assert absent["fingering_algo_version"] is None
    assert absent["has_saved_fingering"] is False
    assert absent["fingering_is_outdated"] is False
    case.source.write_bytes(write_gp_with_fingerings(case.source, {"1": "M"}))
    embedded = _solve(client, 1)
    other_track = _solve(client, 3)
    assert embedded["fingering_algo_version"] == "embedded"
    assert embedded["has_saved_fingering"] is True
    assert embedded["fingering_is_outdated"] is False
    assert embedded["fingering_is_current"] is False
    assert other_track["has_saved_fingering"] is False
    assert other_track["fingering_algo_version"] is None


@pytest.mark.parametrize("sidecar_succeeds", [True, False])
@pytest.mark.parametrize("stream", [False, True])
def test_existing_save_route_recomputes_and_updates_status_only_after_persistence(
    case: _Case, monkeypatch: pytest.MonkeyPatch, sidecar_succeeds: bool, stream: bool,
) -> None:
    _sidecar(case, header="2.1", tracks={1: "2.1", 3: "2.1"})
    calls: list[list[NoteEvent]] = []

    def compute(events: list[NoteEvent]) -> SimpleNamespace:
        calls.append(events)
        return SimpleNamespace(
            results=[case.results[3]],
            biomechanical_report=SimpleNamespace(
                fatal_count=0, high_count=0, violations=[], by_measure=lambda: {},
            ),
        )

    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", compute)
    monkeypatch.setattr("fretwise.web.app._safe_audit", lambda *args, **kwargs: {})
    if not sidecar_succeeds:
        monkeypatch.setattr("fretwise.web.app._write_fingering_sidecar", lambda *args, **kw: False)
    client = TestClient(case.app)
    assert _solve(client, 3)["fingering_is_outdated"] is True
    saved = client.post("/api/save/gp/song.gp", params={"track_id": 3, "stream": stream})
    assert saved.status_code == 200, saved.text
    assert len(calls) == 1
    if stream:
        assert saved.headers["content-type"].startswith("application/x-ndjson")
        assert saved.headers["x-accel-buffering"] == "no"
        assert saved.headers["cache-control"] == "no-cache"
        messages = [json.loads(line) for line in saved.text.splitlines()]
        assert messages[0]["type"] == "started"
        assert messages[-1]["type"] == "result"
        data = messages[-1]["result"]
    else:
        data = saved.json()
    assert data["sidecar_saved"] is sidecar_succeeds
    assert data["algo_version"] == FINGERING_ALGO_VERSION
    assert _read_embedded_gp_fingerings(case.source)["3"] == "I"
    after = _solve(client, 3)
    assert after["fingering_is_current"] is sidecar_succeeds
    assert after["fingering_is_outdated"] is (not sidecar_succeeds)
    assert _solve(client, 1)["fingering_is_outdated"] is True


class _Remote(RemoteStorageBackend):
    """Real remote-cache behavior over an in-memory cloud object."""

    name = "remote-test"

    def __init__(self, source: Path, *, fail_refresh: bool = False) -> None:
        super().__init__(source.parent)
        self.data = source.read_bytes()
        self.modified = 1000.0
        self.writes = 0
        self.fail_refresh = fail_refresh
        os.utime(source, (self.modified, self.modified))

    def stat(self, name: str) -> StorageObject:
        return StorageObject(name, len(self.data), self.modified)

    def list_scores(self) -> list[StorageObject]:
        return [self.stat("song.gp")]

    def read_bytes(self, name: str) -> bytes:
        if self.fail_refresh and self.writes:
            raise StorageError("private-provider-error")
        return self.data

    def write_bytes(self, name: str, data: bytes) -> None:
        self.data = data
        self.modified += 10
        self.writes += 1


@pytest.mark.parametrize("fail_refresh", [False, True])
def test_cloud_save_refreshes_parse_cache_before_publishing_sidecar(
    case: _Case, monkeypatch: pytest.MonkeyPatch, fail_refresh: bool,
) -> None:
    remote = _Remote(case.source, fail_refresh=fail_refresh)
    case.app.state.storage = remote
    _sidecar(case, header="2.1", tracks={1: "2.1"})
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", lambda events:
                        SimpleNamespace(results=[case.results[1]], biomechanical_report=
                                        SimpleNamespace(fatal_count=0, high_count=0,
                                                        violations=[], by_measure=lambda: {})))
    monkeypatch.setattr("fretwise.web.app._safe_audit", lambda *args, **kwargs: {})
    client = TestClient(case.app)
    response = client.post("/api/save/gp/song.gp", params={"track_id": 1})
    assert remote.writes == 1
    meta = json.loads(_fingering_meta_path(case.source).read_text(encoding="utf-8"))
    if fail_refresh:
        assert response.status_code == 502
        assert "private-provider-error" not in response.text
        assert meta["algo_version"] == "2.1"
    else:
        assert response.status_code == 200, response.text
        assert response.json()["sidecar_saved"] is True
        assert meta["source_mtime"] == remote.modified == case.source.stat().st_mtime
        assert _solve(client)["fingering_is_current"] is True


def test_stream_heartbeats_preserve_context_and_finish_once_after_disconnect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fretwise.web.app import _SAVE_TASKS

    monkeypatch.setattr("fretwise.web.app._SAVE_HEARTBEAT_SECONDS", .005)
    user = ContextVar("save_test_user", default="other")
    finished: list[str] = []
    release = threading.Event()

    def operation() -> dict[str, object]:
        assert release.wait(2), "test must release worker"
        finished.append(user.get())
        return {"sidecar_saved": True}

    async def scenario() -> None:
        token = user.set("request-user")
        response = _stream_fingering_save(operation)
        user.reset(token)
        iterator = cast(AsyncGenerator[str, None], response.body_iterator)
        try:
            assert json.loads(await anext(iterator))["type"] == "started"
            assert json.loads(await anext(iterator))["type"] == "heartbeat"
            await iterator.aclose()
            assert len(_SAVE_TASKS) == 1
            assert not finished
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(*tuple(_SAVE_TASKS)), timeout=2)
        await asyncio.sleep(0)
        assert not _SAVE_TASKS

    asyncio.run(scenario())
    assert finished == ["request-user"]


@pytest.mark.parametrize("error", [HTTPException(404, "Missing score"),
                                  HTTPException(502, "private-provider-error"),
                                  RuntimeError("private-internal-error")])
def test_stream_reports_terminal_failure_without_retry_or_private_details(error: Exception) -> None:
    calls: list[int] = []

    def fail() -> dict[str, object]:
        calls.append(1)
        raise error

    async def scenario() -> list[dict[str, object]]:
        response = _stream_fingering_save(fail)
        iterator = cast(AsyncGenerator[str, None], response.body_iterator)
        return [json.loads(line) async for line in iterator]

    messages = asyncio.run(scenario())
    assert [message["type"] for message in messages] == ["started", "error"]
    expected_status = error.status_code if isinstance(error, HTTPException) else 500
    assert messages[-1]["status"] == expected_status
    assert "private-" not in str(messages)
    assert calls == [1]


def test_disconnected_save_keeps_file_lock_until_completion(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    from fretwise.web.app import _SAVE_FILES, _SAVE_TASKS

    monkeypatch.setattr("fretwise.web.app._SAVE_HEARTBEAT_SECONDS", .005)
    release = threading.Event()
    entered = threading.Event()
    calls: list[int] = []

    def compute(events: list[NoteEvent]) -> SimpleNamespace:
        calls.append(1)
        entered.set()
        assert release.wait(2), "test must release worker"
        return SimpleNamespace(results=[case.results[1]], biomechanical_report=
                               SimpleNamespace(fatal_count=0, high_count=0,
                                               violations=[], by_measure=lambda: {}))

    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", compute)
    monkeypatch.setattr("fretwise.web.app._safe_audit", lambda *args, **kwargs: {})
    endpoint = next(route.endpoint for route in case.app.routes
                    if isinstance(route, APIRoute) and route.path == "/api/save/gp/{filename}")

    async def scenario() -> None:
        response = endpoint("song.gp", track_id=1, stream=True)
        assert isinstance(response, StreamingResponse)
        iterator = cast(AsyncGenerator[str, None], response.body_iterator)
        try:
            assert json.loads(await anext(iterator))["type"] == "started"
            while not entered.is_set():
                await anext(iterator)
            await iterator.aclose()
            with pytest.raises(HTTPException) as concurrent:
                endpoint("song.gp", track_id=3, stream=False)
            assert concurrent.value.status_code == 409
            assert calls == [1]
            assert _SAVE_FILES
        finally:
            release.set()
        await asyncio.wait_for(asyncio.gather(*tuple(_SAVE_TASKS)), timeout=2)
        await asyncio.sleep(0)
        assert not _SAVE_FILES
        assert not _SAVE_TASKS
        subsequent = endpoint("song.gp", track_id=1, stream=False)
        assert subsequent["sidecar_saved"] is True

    asyncio.run(scenario())
    assert calls == [1, 1]
