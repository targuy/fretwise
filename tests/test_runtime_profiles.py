"""Runtime profile contract for desktop and NAS/server deployments."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.runtime import resolve_runtime_capabilities
from fretwise.web import settings as web_settings
from fretwise.web.app import create_app


def _server_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.delenv("FRETWISE_REQUIRE_ML_MODELS", raising=False)
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    (tmp_path / "rigs").mkdir()
    return TestClient(create_app(fixtures_dir=tmp_path, runtime_profile="server"))


def test_runtime_profiles_are_explicit_and_unknown_profile_fails_closed() -> None:
    desktop = resolve_runtime_capabilities("desktop")
    server = resolve_runtime_capabilities("server")

    assert desktop.midi_output is True
    assert server.midi_output is False
    with pytest.raises(ValueError, match="desktop.*server"):
        resolve_runtime_capabilities("typo")


def test_server_profile_reports_disabled_pc_capabilities(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)

    response = client.get("/api/runtime")

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile"] == "server"
    assert payload["midi_output"] is False
    assert payload["fingering_ml"] == {
        "available": True,
        "version": "fingering-production-2026-08-20",
        "engine": "onnxruntime-cpu",
    }


def test_server_profile_rejects_midi_endpoint_with_stable_503(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)

    response = client.get("/api/rig-bank/midi-outputs")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "code": "feature_disabled",
        "capability": "midi_output",
        "runtime_profile": "server",
    }


def test_automated_rig_generation_is_not_a_web_runtime_route(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)

    response = client.post("/api/rig/generate", json={"artist": "A", "title": "B"})

    assert response.status_code == 405
    assert "/api/rig/generate" not in client.get("/openapi.json").json()["paths"]


def test_server_profile_keeps_midi_dry_run_but_blocks_hardware_send(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)
    profile = {
        "id": "server-preview",
        "name": "Server Preview",
        "program": 12,
    }
    assert client.post("/api/rig-bank/profile", json=profile).status_code == 200

    preview = client.post(
        "/api/rig-bank/activate",
        json={"profile_id": "server-preview", "dry_run": True},
    )
    send = client.post(
        "/api/rig-bank/activate",
        json={"profile_id": "server-preview", "dry_run": False},
    )

    assert preview.status_code == 200
    assert preview.json()["sent"] is False
    assert send.status_code == 503
    assert send.json()["detail"]["capability"] == "midi_output"


def test_control_surface_defaults_to_safe_dry_run_in_server_profile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)
    profile = {"id": "surface-preview", "name": "Surface Preview", "program": 8}
    assert client.post("/api/rig-bank/profile", json=profile).status_code == 200

    preview = client.post(
        "/api/control-surface/gp180/action",
        json={"action_id": "gp180.profile.surface-preview"},
    )
    send = client.post(
        "/api/control-surface/gp180/action",
        json={"action_id": "gp180.profile.surface-preview", "dry_run": False},
    )

    assert preview.status_code == 200
    assert preview.json()["dry_run"] is True
    assert preview.json()["sent"] is False
    assert send.status_code == 503
    assert send.json()["detail"]["capability"] == "midi_output"


def test_health_endpoints_report_live_and_cpu_model_readiness(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _server_client(tmp_path, monkeypatch)

    live = client.get("/health/live")
    ready = client.get("/health/ready")

    assert live.status_code == 200
    assert live.json() == {"status": "live"}
    assert ready.status_code == 200
    assert ready.json()["status"] == "ready"
    assert ready.json()["fingering_ml"]["engine"] == "onnxruntime-cpu"
