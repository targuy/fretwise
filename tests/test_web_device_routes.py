"""Tests for the device routes: unit selection and the copy-paste LLM workflow.

These run against the catalog artifact committed under
``data/devices/headrush-core/catalog/``, which is the same file the container
ships — so a passing test here means the deployed image can serve the prompt
without ever reaching the instrument.
"""

from __future__ import annotations

import json

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


def test_active_device_defaults_to_the_gp180(client: TestClient):
    assert client.get("/api/devices").json()["active"] == "valeton_gp180"


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
