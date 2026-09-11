"""Tests for the device routes: unit selection and the copy-paste LLM workflow.

These run against the catalog artifact committed under
``data/devices/headrush-core/catalog/``, which is the same file the container
ships — so a passing test here means the deployed image can serve the prompt
without ever reaching the instrument.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.web.app import create_app
from fretwise.web.device_routes import catalog_is_available

pytestmark = pytest.mark.skipif(
    not catalog_is_available(),
    reason="no HeadRush catalog artifact — run scripts/device_catalog_dump.py",
)


@pytest.fixture(scope="module")
def client() -> TestClient:
    return TestClient(create_app())


def _binding_json(**over: object) -> str:
    doc: dict[str, object] = {
        "schemaVersion": "fretwise.device.binding.v1",
        "device": {"deviceId": "headrush-core", "appVersion": "5.1.0.2a63755"},
        "rig": {"name": "AC/DC - Highway"},
        "song": {"artist": "AC/DC", "title": "Highway To Hell"},
        "blocks": [
            {"module": "Amp", "params": {"Type": "82 Lead 800 100W", "GainA": 62}},
            {"module": "Cab", "params": {"CabType": "4x12 Green 25W", "MicType": "Dyn 57"}},
        ],
    }
    doc.update(over)
    return "```json\n" + json.dumps(doc) + "\n```"


# --- device selection ---------------------------------------------------------


def test_devices_endpoint_lists_both_units_with_their_transport(client: TestClient):
    """The two are not interchangeable, so the UI must be able to tell them apart."""
    payload = client.get("/api/devices").json()
    by_id = {d["id"]: d for d in payload["devices"]}
    assert by_id["valeton_gp180"]["transport"] == "midi"
    assert by_id["headrush_core"]["transport"] == "http"


def test_active_device_is_one_of_the_declared_units(client: TestClient):
    """Asserts the shape, not the value.

    The value is a user setting living in ~/.fretwise/config.json, so pinning it
    here makes the suite fail for anyone who selected the other unit — as it did
    the first time the UI was exercised against a real settings file.
    """
    active = client.get("/api/devices").json()["active"]
    assert active in {"valeton_gp180", "headrush_core"}


def test_gp180_stays_the_default_for_a_fresh_install():
    """The default itself is a constant and can be asserted safely."""
    from fretwise.web.settings import _DEFAULTS

    assert _DEFAULTS["gear_device"] == "valeton_gp180"


def test_devices_endpoint_reports_catalog_availability(client: TestClient):
    by_id = {d["id"]: d for d in client.get("/api/devices").json()["devices"]}
    assert by_id["headrush_core"]["catalogAvailable"] is True


# --- catalog summary ----------------------------------------------------------


def test_catalog_summary_reports_the_real_device_vocabulary(client: TestClient):
    payload = client.get("/api/devices/headrush/catalog").json()
    assert payload["appVersion"] == "5.1.0.2a63755"
    assert payload["moduleTypes"] == 278
    assert payload["ampModels"] == 53


# --- prompt -------------------------------------------------------------------


def test_prompt_is_markdown_and_pins_the_firmware(client: TestClient):
    r = client.get(
        "/api/devices/headrush/prompt", params={"artist": "AC/DC", "title": "Highway To Hell"}
    )
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert r.headers["X-FretWise-App-Version"] == "5.1.0.2a63755"
    assert "5.1.0.2a63755" in r.text


def test_prompt_never_offers_blocks_this_device_lacks(client: TestClient):
    """The GP-180 prompt lists these; none exist on a Core."""
    text = client.get(
        "/api/devices/headrush/prompt", params={"artist": "A", "title": "B"}
    ).text
    for invented in ("Klone", "Tube Scream", "Cry Baby Wah", "Blue Comp", "4x12 Greenback"):
        assert invented not in text


def test_prompt_carries_the_real_amp_and_cab_names(client: TestClient):
    text = client.get(
        "/api/devices/headrush/prompt", params={"artist": "A", "title": "B"}
    ).text
    assert "82 Lead 800 100W" in text
    assert "4x12 Green 25W" in text
    assert "Dyn 57" in text


def test_prompt_requires_a_song(client: TestClient):
    assert client.get(
        "/api/devices/headrush/prompt", params={"artist": " ", "title": " "}
    ).status_code == 400


# --- ingest -------------------------------------------------------------------


def test_ingest_accepts_a_fenced_reply_and_returns_a_binding(client: TestClient):
    r = client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "AC/DC", "title": "Highway To Hell", "response": _binding_json()},
    )
    assert r.status_code == 200
    payload = r.json()
    assert payload["blocks"] == 2
    assert payload["suggestedFilename"] == "ac-dc__highway-to-hell.json"


def test_ingest_repairs_a_missing_guard_prefix(client: TestClient):
    """Without the prefix the applier would refuse it; better to fix it here."""
    r = client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "AC/DC", "title": "Highway", "response": _binding_json()},
    )
    assert r.json()["rig"].startswith("#FW - ")


def test_ingest_refuses_an_invented_block_with_422(client: TestClient):
    r = client.post(
        "/api/devices/headrush/ingest",
        json={
            "artist": "A",
            "title": "B",
            "response": _binding_json().replace('"Amp"', '"Klone"'),
        },
    )
    assert r.status_code == 422
    assert "Klone" in r.json()["detail"]


def test_ingest_refuses_an_out_of_range_value(client: TestClient):
    r = client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "A", "title": "B", "response": _binding_json().replace("62", "620")},
    )
    assert r.status_code == 422


def test_ingest_requires_a_response_field(client: TestClient):
    r = client.post("/api/devices/headrush/ingest", json={"artist": "A", "title": "B"})
    assert r.status_code == 400


def test_ingest_never_touches_the_instrument(client: TestClient):
    """The route has no device host configured and must still succeed offline."""
    r = client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "A", "title": "B", "response": _binding_json()},
    )
    assert r.status_code == 200


# --- storing and showing a rig ------------------------------------------------


@pytest.fixture
def rig_store(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Point the rig store at a temporary gears directory.

    Without this the save tests would write into the repository (or, on the NAS,
    into the real persistent volume).
    """
    from fretwise.web import settings as _settings

    original = _settings.get

    def fake_get(key: str, default: object = None) -> object:
        return str(tmp_path) if key == "gears_dir" else original(key, default)

    monkeypatch.setattr(_settings, "get", fake_get)
    return tmp_path / "_devices" / "headrush-core" / "rigs"


def test_ingest_without_save_writes_nothing(client: TestClient, rig_store: Path):
    r = client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "Muse", "title": "Knights Of Cydonia", "response": _binding_json()},
    )
    assert r.status_code == 200
    assert r.json()["saved"] is None
    assert not rig_store.exists()


def test_ingest_with_save_stores_under_the_open_songs_key(client: TestClient, rig_store: Path):
    """Keyed by the song open in the UI, not by what the model wrote in `song`."""
    r = client.post(
        "/api/devices/headrush/ingest",
        json={
            "artist": "Muse",
            "title": "Knights Of Cydonia",
            "response": _binding_json(),
            "save": True,
        },
    )
    assert r.status_code == 200
    assert r.json()["saved"] == "muse__knights-of-cydonia.json"
    stored = json.loads((rig_store / "muse__knights-of-cydonia.json").read_text(encoding="utf-8"))
    assert stored["rig"]["name"].startswith("#FW - ")


def test_refused_rig_is_never_stored(client: TestClient, rig_store: Path):
    r = client.post(
        "/api/devices/headrush/ingest",
        json={
            "artist": "A",
            "title": "B",
            "response": _binding_json().replace('"Amp"', '"Klone"'),
            "save": True,
        },
    )
    assert r.status_code == 422
    assert not rig_store.exists()


def test_rig_route_is_empty_for_a_song_without_a_rig(client: TestClient, rig_store: Path):
    payload = client.get(
        "/api/devices/headrush/rig", params={"artist": "Nobody", "title": "Nothing"}
    ).json()
    assert payload["binding"] is None
    assert payload["view"] is None
    assert payload["provisioned"] is None


def test_rig_route_returns_the_saved_rig_slot_by_slot(client: TestClient, rig_store: Path):
    client.post(
        "/api/devices/headrush/ingest",
        json={"artist": "Muse", "title": "Knights Of Cydonia", "response": _binding_json(),
              "save": True},
    )
    payload = client.get(
        "/api/devices/headrush/rig", params={"artist": "Muse", "title": "Knights Of Cydonia"}
    ).json()
    assert payload["source"] == "store"
    blocks = {b["module"]: b for b in payload["view"]["blocks"]}
    # Frozen head: Amp in slot 6, Cab in slot 7; bypass CC = 74 + slot.
    assert (blocks["Amp"]["slot"], blocks["Amp"]["cc"]) == (6, 80)
    assert (blocks["Cab"]["slot"], blocks["Cab"]["cc"]) == (7, 81)
    assert blocks["Amp"]["params"]["Type"] == "82 Lead 800 100W"
    assert payload["view"]["applicable"] is True


def test_rig_route_falls_back_to_the_rig_shipped_in_the_image(
    client: TestClient, rig_store: Path
):
    """AC/DC was authored and pushed from the CLI: it lives in the repo, not the store."""
    payload = client.get(
        "/api/devices/headrush/rig", params={"artist": "AC/DC", "title": "Highway To Hell"}
    ).json()
    assert payload["source"] == "image"
    assert payload["provisioned"]["programChange"] == 32


def test_rig_route_requires_a_song(client: TestClient):
    assert client.get("/api/devices/headrush/rig").status_code == 400


def test_stored_rigs_stay_out_of_git_and_the_image():
    """The UI store sits inside the gears volume; neither git nor the build may take it."""
    for name in (".gitignore", ".dockerignore"):
        lines = Path(name).read_text(encoding="utf-8").splitlines()
        assert "data/gears/_devices/" in [line.strip() for line in lines], name


# --- the artifact must actually reach the image -------------------------------


def test_dockerignore_lets_the_device_catalog_into_the_build_context():
    """The prompt routes read a file from `data/`, which `.dockerignore` blanket-excludes.

    `data/*` drops everything and each runtime directory is re-included by hand.
    `data/devices/` was missing from that list, so the deployed container answered
    `catalogAvailable: false` and the prompt route returned 503 — the routes worked,
    the file simply never shipped. This asserts the re-include stays.
    """
    lines = [
        line.strip()
        for line in Path(".dockerignore").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.strip().startswith("#")
    ]
    assert "data/*" in lines, "the blanket exclusion this test guards against is gone"
    assert "!data/devices/" in lines
    assert "!data/devices/**" in lines
    # Backups are dated captures, not runtime data: they must stay out.
    assert "data/devices/*/backups/" in lines


def test_catalog_directory_holds_a_committed_artifact():
    """A catalog must be tracked, or the image ships the route without its data."""
    committed = subprocess.run(
        ["git", "ls-files", "data/devices/headrush-core/catalog"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout.split()
    assert any(f.endswith(".json") for f in committed), committed
