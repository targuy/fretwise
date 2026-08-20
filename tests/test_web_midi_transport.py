"""Browser-local MIDI transport contract."""

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.runtime import resolve_runtime_capabilities
from fretwise.web import settings as web_settings
from fretwise.web.app import create_app


def _server_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    (tmp_path / "rigs").mkdir()
    return TestClient(create_app(fixtures_dir=tmp_path, runtime_profile="server"))


def test_runtime_profiles_disable_server_side_midi_on_nas() -> None:
    """Server profile exposes browser-safe MIDI preview only."""
    assert resolve_runtime_capabilities("desktop").midi_output is True
    assert resolve_runtime_capabilities("server").midi_output is False
    with pytest.raises(ValueError, match="desktop.*server"):
        resolve_runtime_capabilities("unknown")


def test_server_runtime_blocks_hardware_send_but_keeps_midi_preview(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NAS returns raw bytes but never attempts to open its own MIDI backend."""
    client = _server_client(tmp_path, monkeypatch)
    profile = {"id": "browser-midi", "name": "Browser MIDI", "program": 19}
    assert client.post("/api/rig-bank/profile", json=profile).status_code == 200

    runtime = client.get("/api/runtime")
    preview = client.post(
        "/api/rig-bank/activate",
        json={"profile_id": "browser-midi", "dry_run": True},
    )
    send = client.post(
        "/api/rig-bank/activate",
        json={"profile_id": "browser-midi", "dry_run": False},
    )

    assert runtime.status_code == 200
    assert runtime.json()["profile"] == "server"
    assert runtime.json()["midi_output"] is False
    assert preview.status_code == 200
    assert preview.json()["midi"] == [[176, 0, 0], [192, 19]]
    assert send.status_code == 503
    assert send.json()["detail"]["capability"] == "midi_output"


def test_server_frontend_sends_preview_bytes_through_browser_web_midi() -> None:
    """Server UI drives USB MIDI attached to device running browser."""
    main_js = Path("src/fretwise/web/static/js/main.js").read_text(encoding="utf-8")

    assert "activateRigProfile({ profile_id: select.value, dry_run: true })" in main_js
    assert "await sendMidiMessages(output, messages)" in main_js

    web_midi_js = Path("src/fretwise/web/static/js/web-midi.js").read_text(encoding="utf-8")
    assert "requestMIDIAccess({ sysex: false })" in web_midi_js
    assert "MIDI_MESSAGE_DELAY_MS = 200" in web_midi_js
    assert "output.send(message, startTimeMs + index * delayMs)" in web_midi_js
