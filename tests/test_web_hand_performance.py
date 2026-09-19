"""HTTP regressions for the read-only, revisioned hand-performance endpoint."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fretwise.auth.models import User
from fretwise.auth.users import UserStore
from fretwise.auth.web import UserContextMiddleware
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.storage.local import LocalStorageBackend
from fretwise.web.app import (
    _fingering_data_path,
    _solve_cache_clear,
    _write_fingering_sidecar,
    create_app,
)


@dataclass
class _Fixture:
    app: FastAPI
    source: Path
    events: list[NoteEvent]
    parsed_paths: list[Path]


@pytest.fixture
def hand_case(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> _Fixture:
    """Use real HTTP/storage/sidecars and stub only score parsing/engraving."""
    _solve_cache_clear()
    monkeypatch.setattr("fretwise.web.app._settings.load", lambda: {})
    source = tmp_path / "source.gp"
    source.write_bytes(b"synthetic score fixture")
    events = [
        NoteEvent(60, 0.0, 1.0, 120.0, string_hint=2, fret_hint=1,
                  voice_hint=0, source_note_id="source-a", source_finger=Finger.INDEX),
        NoteEvent(62, 1.0, 0.5, 120.0, string_hint=2, fret_hint=3,
                  voice_hint=0, source_note_id="source-b", source_finger=Finger.RING),
    ]
    results = [
        FingeringResult(0, events[0], FingeringState(2, 1, Finger.INDEX, 1), 0.0),
        FingeringResult(1, events[1], FingeringState(2, 3, Finger.RING, 1), 0.0),
    ]
    assert _write_fingering_sidecar(source, results, track_id=0)
    adapter = SimpleNamespace(
        track_name="Guitar", midi_program=24, beats_per_measure=4.0,
        measure_time_signatures={1: (4, 4)},
    )
    parsed_paths: list[Path] = []

    def parse(path: Path, *, track_id: int | None = None) -> tuple[object, list[NoteEvent]]:
        del track_id
        parsed_paths.append(path)
        return adapter, events

    def forbid_optimization(*args: object, **kwargs: object) -> None:
        raise AssertionError("Hand-performance retrieval must not recompute fingerings")

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", parse)
    monkeypatch.setattr("fretwise.optimizer.ViterbiOptimizer.solve", forbid_optimization)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", forbid_optimization)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", lambda *args, **kwargs:
                        SimpleNamespace(svg="<svg/>", conformance_issues=[],
                                        render_scene=None, canonical_score=None))
    app = create_app(tmp_path, allowed_hosts=["testserver"])
    return _Fixture(app, source, events, parsed_paths)


def _body(client: TestClient, filename: str = "source.gp") -> dict[str, str]:
    response = client.get(f"/api/solve/{filename}", params={
        "track_id": 0, "representation_mode": "tablature",
    })
    assert response.status_code == 200, response.text
    payload = response.json()
    return {
        "scoreId": filename, "trackId": "0", "scoreRevision": payload["score_revision"],
        "fingeringRevision": payload["fingering_revision"],
    }


def test_delivered_profiles_are_versioned_and_unknown_revision_is_rejected(
    hand_case: _Fixture,
) -> None:
    client = TestClient(hand_case.app)
    hand = client.get('/api/v2/hand-profiles/adult-reference-left/revisions/1')
    assert hand.status_code == 200
    assert hand.json()['asset']['status'] == 'illustrative'
    assert len(hand.json()['asset']['glbSha256']) == 64
    guitar = client.get('/api/v2/instrument-profiles/six-string-648/revisions/1')
    assert guitar.status_code == 200
    assert guitar.json()['scaleLengthM'] == 0.648
    assert client.get('/api/v2/hand-profiles/adult-reference-left/revisions/99').status_code == 404


def test_hand_performance_uses_saved_decisions_and_exact_source_ids(hand_case: _Fixture) -> None:
    before = {path.name: path.read_bytes() for path in hand_case.source.parent.glob("*")}
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json=_body(client))
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["schemaVersion"] == "1.1"
    assert [note["sourceNoteId"] for note in payload["notes"]] == ["source-a", "source-b"]
    assert [note["fingering"]["finger"] for note in payload["notes"]] == ["index", "ring"]
    assert len({note["occurrenceId"] for note in payload["notes"]}) == 2
    assert {path.name: path.read_bytes() for path in hand_case.source.parent.glob("*")} == before


@pytest.mark.parametrize("revision", ["scoreRevision", "fingeringRevision"])
def test_stale_requested_revision_returns_409(hand_case: _Fixture, revision: str) -> None:
    with TestClient(hand_case.app) as client:
        body = _body(client)
        body[revision] = "outdated"
        response = client.post("/api/v2/hand-performance", json=body)
    assert response.status_code == 409


def test_changed_saved_decisions_invalidate_cached_revision(hand_case: _Fixture) -> None:
    with TestClient(hand_case.app) as client:
        body = _body(client)
        assert client.post("/api/v2/hand-performance", json=body).status_code == 200
        sidecar = _fingering_data_path(hand_case.source)
        data = json.loads(sidecar.read_text(encoding="utf-8"))
        data["results"][1]["finger"] = "pinky"
        data["tracks"]["0"]["results"][1]["finger"] = "pinky"
        sidecar.write_text(json.dumps(data), encoding="utf-8")
        response = client.post("/api/v2/hand-performance", json=body)
    assert response.status_code == 409


def test_incomplete_saved_fingering_returns_422_instead_of_reoptimizing(
    hand_case: _Fixture,
) -> None:
    sidecar = _fingering_data_path(hand_case.source)
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    data["results"] = data["results"][:1]
    data["tracks"]["0"]["results"] = data["tracks"]["0"]["results"][:1]
    sidecar.write_text(json.dumps(data), encoding="utf-8")
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json=_body(client))
    assert response.status_code == 422
    assert "missing or ambiguous" in response.json()["detail"]


def test_source_occurrence_matching_rejects_wrong_voice(hand_case: _Fixture) -> None:
    hand_case.events[1] = replace(hand_case.events[1], voice_hint=1)
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json=_body(client))
    assert response.status_code == 422


@pytest.mark.parametrize("filename,status", [
    ("../outside.gp", 404), ("C:\\outside.gp", 404), ("secret.txt", 400),
])
def test_score_access_is_confined_to_active_storage(
    hand_case: _Fixture, filename: str, status: int,
) -> None:
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json={
            "scoreId": filename, "trackId": "0",
            "scoreRevision": "x", "fingeringRevision": "x",
        })
    assert response.status_code == status
    assert hand_case.parsed_paths == []


def test_authentication_middleware_protects_hand_performance(hand_case: _Fixture) -> None:
    hand_case.app.add_middleware(
        UserContextMiddleware, user_store=UserStore(hand_case.source.parent / "users"),
    )
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json={
            "scoreId": "source.gp", "trackId": "0",
            "scoreRevision": "x", "fingeringRevision": "x",
        })
    assert response.status_code == 401
    assert hand_case.parsed_paths == []


def test_authenticated_user_cannot_read_shared_library(
    hand_case: _Fixture, monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_library = hand_case.source.parent / "own-library"
    user_library.mkdir()
    hand_case.app.state.multiuser = True
    hand_case.app.state.secrets_store = SimpleNamespace(get=lambda _user_id: {})
    hand_case.app.state.cache_root = hand_case.source.parent / "cache"
    monkeypatch.setattr("fretwise.web.app.current_request_user", lambda: User(id="user-a"))
    monkeypatch.setattr("fretwise.web.app.resolve_user_storage", lambda *args, **kwargs:
                        LocalStorageBackend(user_library))
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json={
            "scoreId": "source.gp", "trackId": "0",
            "scoreRevision": "x", "fingeringRevision": "x",
        })
    assert response.status_code == 404
    assert hand_case.parsed_paths == []


def test_cross_origin_post_is_rejected_before_score_access(hand_case: _Fixture) -> None:
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json={},
                               headers={"Origin": "https://unrelated.invalid"})
    assert response.status_code == 403
    assert hand_case.parsed_paths == []


@pytest.mark.parametrize("extra", [{"range": {"startTick": 0, "endTick": 1}},
                                    {"handProfileRevision": "unknown"},
                                    {"trackId": "not-a-track"}])
def test_unavailable_request_capabilities_are_explicit(
    hand_case: _Fixture, extra: dict[str, object],
) -> None:
    with TestClient(hand_case.app) as client:
        response = client.post("/api/v2/hand-performance", json={**_body(client), **extra})
    assert response.status_code in {404, 422}
