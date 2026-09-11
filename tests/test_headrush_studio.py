"""Tests for HeadRush Studio, the standalone HeadRush Core rig designer.

The Studio has no login, so most of what is tested here is how it guards itself
instead: loopback-only ``Host``, refusal of cross-site posts, and a settings
route limited to the two device keys. The device itself is an in-memory fake.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fretwise.devices.headrush_core.studio import create_studio_app
from fretwise.devices.headrush_core.studio.server import _hostname
from fretwise.web.device_routes import catalog_is_available

pytestmark = pytest.mark.skipif(
    not catalog_is_available(),
    reason="no HeadRush catalog artifact — run scripts/device_catalog_dump.py",
)

#: GUID of the AC/DC rig recorded in the shipped song table.
ACDC_GUID = "06afd1ac-a508-41f5-ba73-ee4ce6b889ea"


@pytest.fixture
def config(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Keep settings writes away from the real ~/.fretwise/config.json."""
    from fretwise.web import settings as _settings

    monkeypatch.setattr(_settings, "_CONFIG_DIR", tmp_path)
    monkeypatch.setattr(_settings, "_CONFIG_FILE", tmp_path / "config.json")
    for name in ("FRETWISE_CORE_HOST", "FRETWISE_HEADRUSH_ALLOW_WRITE", "FRETWISE_GEARS_DIR"):
        monkeypatch.delenv(name, raising=False)
    return tmp_path / "config.json"


@pytest.fixture
def client(config: Path) -> TestClient:
    return TestClient(create_studio_app(allowed_hosts={"testserver"}))


class _FakeCore:
    """In-memory Core holding a hand-made rig, the AC/DC rig and the sandbox."""

    def __init__(self) -> None:
        self.props: dict[str, dict[str, Any]] = {
            "/Evil/Gui": {"AppVersion": "5.1.0.2a63755", "DeviceName": "HeadRush Core_3570"},
            "/Evil/API/Rigs": {
                "AllRigIds": ["id-hand", ACDC_GUID, "id-scratch"],
                "AllRigNames": [
                    "Lorenzo solo 1", "#FW - AC/DC - Highway To Hell", "#FW - SCRATCH",
                ],
                "loadedID": "id-hand",
                "loadedName": "Lorenzo solo 1",
                "dirty": False,
                "availableProgMIDICC": list(range(128)),
            },
            "/Evil/API/RigSaveDialog": {"displayDialog": False},
        }
        self.invocations: list[tuple[str, str, list[Any]]] = []

    def subtree(self, path: str) -> dict[str, Any]:
        return {}

    def meta(self, path: str) -> dict[str, Any]:
        return {}

    def query(self, path: str, method: str, arguments: list[Any]) -> Any:
        return None

    def properties(self, path: str) -> dict[str, Any]:
        return dict(self.props.get(path, {}))

    def set_properties(self, path: str, values: dict[str, Any]) -> None:
        self.props.setdefault(path, {}).update(values)

    def invoke(self, path: str, method: str, arguments: list[Any]) -> Any:
        self.invocations.append((path, method, arguments))
        if method == "loadRigConfirm":
            rigs = self.props["/Evil/API/Rigs"]
            index = rigs["AllRigIds"].index(arguments[0])
            rigs["loadedID"] = arguments[0]
            rigs["loadedName"] = rigs["AllRigNames"][index]
        return True


@pytest.fixture
def core(monkeypatch: pytest.MonkeyPatch) -> _FakeCore:
    import time

    from fretwise.web import device_routes

    fake = _FakeCore()
    monkeypatch.setattr(device_routes, "make_read_client", lambda host: fake)
    monkeypatch.setattr(device_routes, "make_write_client", lambda host: fake)
    monkeypatch.setattr(time, "sleep", lambda _seconds: None)
    return fake


# --- the page and its assets --------------------------------------------------


def test_index_is_the_studio_page(client: TestClient):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>HeadRush Studio</title>" in r.text


def test_the_rig_view_module_is_shared_with_fretwise(client: TestClient):
    """One rig view for both apps: fixes to the push flow land in both."""
    r = client.get("/shared/headrush.js")
    assert r.status_code == 200
    assert "export function renderRigView" in r.text
    assert "export function setSettingsLabel" in r.text


def test_studio_assets_are_served(client: TestClient):
    assert client.get("/static/studio.js").status_code == 200
    assert client.get("/static/studio.css").status_code == 200


# --- how an unauthenticated local app guards itself ---------------------------


def test_a_foreign_host_header_is_refused(config: Path):
    """DNS rebinding: a hostile name resolving to 127.0.0.1 must not get through."""
    app = create_studio_app()
    assert TestClient(app, base_url="http://evil.example:8765").get("/").status_code == 403
    assert TestClient(app, base_url="http://127.0.0.1:8765").get("/").status_code == 200
    assert TestClient(app, base_url="http://localhost:8765").get("/").status_code == 200


def test_a_cross_site_post_is_refused(client: TestClient, config: Path):
    r = client.post(
        "/api/studio/settings",
        json={"headrush_allow_write": True},
        headers={"Origin": "https://evil.example"},
    )
    assert r.status_code == 403
    assert not config.exists()


def test_a_same_origin_post_passes_the_guard(client: TestClient):
    r = client.post("/api/studio/settings", json={}, headers={"Origin": "http://testserver"})
    assert r.status_code == 400  # reached the route: nothing to save


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("127.0.0.1:8765", "127.0.0.1"),
        ("LOCALHOST:8765", "localhost"),
        ("[::1]:8765", "::1"),
        ("::1", "::1"),
        ("http://127.0.0.1:8765", "127.0.0.1"),
        ("null", "null"),
    ],
)
def test_hostname_parsing(raw: str, expected: str):
    assert _hostname(raw) == expected


# --- songs --------------------------------------------------------------------


def test_song_list_includes_the_shipped_rig_and_its_program_change(client: TestClient):
    rigs = client.get("/api/devices/headrush/rigs").json()["rigs"]
    acdc = next(r for r in rigs if r["key"] == "ac-dc__highway-to-hell")
    assert acdc["title"] == "Highway To Hell"
    assert acdc["provisioned"]["programChange"] == 32
    assert all(not r["key"].startswith("_") for r in rigs)  # _exemple.json is documentation


# --- settings -----------------------------------------------------------------


def test_settings_round_trip_to_the_shared_config_file(client: TestClient, config: Path):
    r = client.post(
        "/api/studio/settings", json={"headrush_host": "10.0.0.5", "headrush_allow_write": True}
    )
    assert r.status_code == 200
    assert r.json()["host"] == "10.0.0.5" and r.json()["writeEnabled"] is True
    assert client.get("/api/studio/settings").json()["host"] == "10.0.0.5"
    saved = json.loads(config.read_text(encoding="utf-8"))
    assert saved["headrush_host"] == "10.0.0.5"


def test_settings_refuse_a_host_that_is_not_bare(client: TestClient, config: Path):
    r = client.post("/api/studio/settings", json={"headrush_host": "evil.example/x?y="})
    assert r.status_code == 400
    assert not config.exists()


def test_settings_refuse_a_non_boolean_write_flag(client: TestClient):
    r = client.post("/api/studio/settings", json={"headrush_allow_write": "yes"})
    assert r.status_code == 400


def test_settings_only_touch_the_two_device_keys(client: TestClient, config: Path):
    """The Studio has no business changing FretWise's other settings."""
    r = client.post("/api/studio/settings", json={"gear_device": "headrush_core"})
    assert r.status_code == 400
    assert not config.exists()


def test_writes_are_off_until_enabled(client: TestClient):
    assert client.get("/api/studio/settings").json()["writeEnabled"] is False


# --- device view and audition load --------------------------------------------


def test_device_view_marks_the_rigs_fretwise_made(client: TestClient, core: _FakeCore):
    payload = client.get("/api/devices/headrush/device").json()
    assert payload["reachable"] is True
    by_id = {r["id"]: r for r in payload["rigs"]}
    assert by_id["id-hand"]["loaded"] is True and by_id["id-hand"]["song"] is None
    acdc = by_id[ACDC_GUID]
    assert acdc["generated"] is True
    assert acdc["song"]["title"] == "Highway To Hell" and acdc["song"]["programChange"] == 32


def test_load_is_refused_while_writes_are_disabled(client: TestClient, core: _FakeCore):
    r = client.post("/api/devices/headrush/load", json={"rigId": ACDC_GUID})
    assert r.status_code == 409
    assert r.json()["detail"]["code"] == "write_disabled"
    assert core.invocations == []


def test_load_is_refused_over_unsaved_changes(
    client: TestClient, core: _FakeCore, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("FRETWISE_HEADRUSH_ALLOW_WRITE", "1")
    core.props["/Evil/API/Rigs"]["dirty"] = True
    r = client.post("/api/devices/headrush/load", json={"rigId": ACDC_GUID})
    assert r.status_code == 409
    assert "non sauvegard" in r.json()["detail"]["detail"]
    assert core.invocations == []


def test_load_refuses_a_rig_the_device_does_not_have(
    client: TestClient, core: _FakeCore, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("FRETWISE_HEADRUSH_ALLOW_WRITE", "1")
    r = client.post("/api/devices/headrush/load", json={"rigId": "nope"})
    assert r.status_code == 409
    assert core.invocations == []


def test_load_switches_the_rig(
    client: TestClient, core: _FakeCore, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.setenv("FRETWISE_HEADRUSH_ALLOW_WRITE", "1")
    r = client.post("/api/devices/headrush/load", json={"rigId": ACDC_GUID})
    assert r.status_code == 200, r.text
    assert r.json()["loadedName"] == "#FW - AC/DC - Highway To Hell"
    assert [m for _, m, _ in core.invocations] == ["loadRigConfirm"]
