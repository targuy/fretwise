"""Generation keeps provider billing, validation and persistent saves behind guards."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.web import device_routes, rig_ai_routes


@pytest.fixture
def rig_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("FRETWISE_CONFIG_DIR", str(tmp_path / "config"))
    monkeypatch.setenv("FRETWISE_RIG_AI_SECRETS_FILE", str(tmp_path / "keys.json"))
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setattr(device_routes, "_store_dir", lambda: tmp_path / "rigs")
    # A failed candidate remains failed unless this test explicitly provides a repair.
    monkeypatch.setattr(rig_ai_routes, "repair", lambda prompt, previous: previous)
    app = FastAPI()
    app.state.admin = True

    def require_admin(app: FastAPI) -> None:
        if not app.state.admin:
            raise HTTPException(403, "Admin privileges required")

    device_routes.register_device_routes(app, require_admin)
    return TestClient(app)


def binding() -> dict[str, object]:
    return {
        "schemaVersion": "fretwise.device.binding.v1",
        "device": {"deviceId": "headrush-core", "appVersion": "5.1.0.2a63755"},
        "rig": {"name": "#FW - Unexpected title", "programChange": None},
        "song": {"artist": "Wrong artist", "title": "Wrong title"},
        "confidence": "unknown",
        "blocks": [
            {"module": "Amp", "params": {"Type": "82 Lead 800 100W", "GainA": 42}},
            {"module": "Cab", "params": {"CabType": "4x12 Green 25W"}},
        ],
    }


def provider_result(document: object) -> SimpleNamespace:
    return SimpleNamespace(
        text=json.dumps(document), sources=[],
        metadata=lambda: {"provider": "openai", "model": "test"},
    )


def test_generate_validates_and_saves_for_requested_song_without_device_access(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    def generate(prompt: str) -> SimpleNamespace:
        calls.append(prompt)
        return provider_result(binding())

    monkeypatch.setattr(rig_ai_routes, "generate", generate)

    def forbidden_device(*args: object, **kwargs: object) -> None:
        raise AssertionError("Generation must not access the instrument")

    monkeypatch.setattr(device_routes, "make_read_client", forbidden_device)
    monkeypatch.setattr(device_routes, "make_write_client", forbidden_device)
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium", "guidance": "Partie saturée studio",
    })
    assert response.status_code == 200, response.text
    assert len(calls) == 1 and "Partie saturée studio" in calls[0]
    data = response.json()
    assert data["saved"] == "nirvana__lithium.json"
    assert data["binding"]["song"] == {"artist": "Nirvana", "title": "Lithium"}
    assert len(data["view"]["blocks"]) == 2
    assert data["generation"]["provider"] == "openai"
    assert device_routes._rig_file("Nirvana", "Lithium").is_file()
    assert data["generation"]["validationRepair"] is False


def test_one_technical_repair_is_validated_before_saving(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    bad = {"blocks": [{"module": "Imaginary Tube", "params": {}}]}
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: provider_result(bad))

    def repair(prompt: str, previous: SimpleNamespace) -> SimpleNamespace:
        calls.append(prompt)
        assert not device_routes._rig_file("Nirvana", "Lithium").exists()
        assert "ERREURS_VALIDATION" in prompt and "Imaginary Tube" in prompt
        return provider_result(binding())

    monkeypatch.setattr(rig_ai_routes, "repair", repair)
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert response.status_code == 200
    assert len(calls) == 1
    assert response.json()["generation"]["validationRepair"] is True


def test_second_invalid_candidate_stops_without_saving_or_more_calls(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    bad = provider_result({"blocks": []})
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: bad)

    def repair(prompt: str, previous: SimpleNamespace) -> SimpleNamespace:
        calls.append(prompt)
        return bad

    monkeypatch.setattr(rig_ai_routes, "repair", repair)
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert response.status_code == 422
    assert len(calls) == 1
    assert not device_routes._rig_file("Nirvana", "Lithium").exists()


@pytest.mark.parametrize("bad", [
    {"blocks": [{"module": "Imaginary Tube", "params": {}}]},
    {"rig": [], "blocks": []},
    {"blocks": [{"module": "Amp", "params": {"GainA": 100000}}]},
])
def test_invalid_generation_does_not_overwrite_existing_rig(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch, bad: object,
) -> None:
    target = device_routes._rig_file("Nirvana", "Lithium")
    target.parent.mkdir(parents=True)
    original = json.dumps(binding())
    target.write_text(original, encoding="utf-8")
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: provider_result(bad))
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert response.status_code == 422
    assert target.read_text(encoding="utf-8") == original


def test_generation_detects_rig_changed_while_provider_runs(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = device_routes._rig_file("Nirvana", "Lithium")

    def generate(prompt: str) -> SimpleNamespace:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text('{"newer":"user edit"}', encoding="utf-8")
        return provider_result(binding())

    monkeypatch.setattr(rig_ai_routes, "generate", generate)
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert response.status_code == 409
    assert json.loads(target.read_text()) == {"newer": "user edit"}


def test_generation_checks_concurrent_edit_after_view_preparation(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = device_routes._rig_file("Nirvana", "Lithium")
    original_view = device_routes._rig_view
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: provider_result(binding()))

    def view(document: dict[str, object], catalog: Catalog) -> dict[str, object]:
        target.parent.mkdir(parents=True, exist_ok=True)
        with device_routes._rig_store_lock:
            rig_ai_routes._atomic_json(target, {"newer": "manual"})
        return original_view(document, catalog)

    monkeypatch.setattr(device_routes, "_rig_view", view)
    response = rig_client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert response.status_code == 409
    assert json.loads(target.read_text()) == {"newer": "manual"}


def test_manual_ingestion_and_generation_use_shared_commit_lock(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[Path] = []
    original_write = rig_ai_routes._atomic_json

    def write(path: Path, document: object) -> None:
        assert device_routes._rig_store_lock.locked()
        writes.append(path)
        original_write(path, document)

    monkeypatch.setattr(rig_ai_routes, "_atomic_json", write)
    # Registration captures the atomic writer used by the manual route.
    second = FastAPI()
    device_routes.register_device_routes(second, lambda app: None)
    client = TestClient(second)
    manual = client.post("/api/devices/headrush/ingest", json={
        "response": binding(), "artist": "Nirvana", "title": "Lithium", "save": True,
    })
    assert manual.status_code == 200
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: provider_result(binding()))
    automatic = client.post("/api/devices/headrush/generate", json={
        "artist": "Nirvana", "title": "Lithium",
    })
    assert automatic.status_code == 200
    assert len(writes) == 2


def test_non_admin_cannot_spend_or_change_provider_keys(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    cast(FastAPI, rig_client.app).state.admin = False
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: pytest.fail("Provider called"))
    monkeypatch.setattr(rig_ai_routes, "save_settings", lambda body: pytest.fail("Keys changed"))
    assert rig_client.post("/api/devices/headrush/generate", json={"title": "x"}).status_code == 403
    assert rig_client.post("/api/rig-ai/settings", json={"mode": "openai"}).status_code == 403
    data = rig_client.get("/api/rig-ai/settings").json()
    assert data["canEdit"] is False and data["canGenerate"] is False


def test_concurrent_generation_is_rejected_without_provider_call(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: pytest.fail("Provider called"))
    assert rig_ai_routes._generation_lock.acquire(blocking=False)
    try:
        response = rig_client.post("/api/devices/headrush/generate", json={"title": "x"})
    finally:
        rig_ai_routes._generation_lock.release()
    assert response.status_code == 409


@pytest.mark.parametrize("body", [[], {"title": 42}, {"title": "x", "guidance": "x" * 8001}])
def test_invalid_request_never_calls_provider(
    rig_client: TestClient, monkeypatch: pytest.MonkeyPatch, body: object,
) -> None:
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: pytest.fail("Provider called"))
    assert rig_client.post("/api/devices/headrush/generate", json=body).status_code == 400


def test_oversized_key_update_is_rejected_before_parsing(rig_client: TestClient) -> None:
    response = rig_client.post("/api/rig-ai/settings", content=b" " * 32769)
    assert response.status_code == 413
