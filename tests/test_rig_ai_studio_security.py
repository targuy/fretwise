"""Other local browser origins must not mutate provider keys or spend credits."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from fretwise.devices.headrush_core.studio.server import create_studio_app
from fretwise.web import rig_ai_routes


@pytest.mark.parametrize("endpoint", ["/api/rig-ai/settings", "/api/devices/headrush/generate"])
@pytest.mark.parametrize(
    "origin",
    [
        "http://127.0.0.1:8000",
        "https://127.0.0.1:8765",
        "http://localhost:8765",
        "https://evil.example",
        "null",
        "http://127.0.0.1:bad",
        "http://[::1]:8765",
    ],
)
def test_studio_rejects_foreign_origin_before_keys_or_provider(
    endpoint: str,
    origin: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rig_ai_routes, "save_settings", lambda body: pytest.fail("Key write"))
    monkeypatch.setattr(rig_ai_routes, "generate", lambda prompt: pytest.fail("Provider called"))
    client = TestClient(create_studio_app(), base_url="http://127.0.0.1:8765")
    response = client.post(
        endpoint,
        content='{"title":"test"}',
        headers={"Origin": origin, "Content-Type": "text/plain"},
    )
    assert response.status_code == 403


@pytest.mark.parametrize("fetch_site", ["cross-site", "same-site"])
def test_studio_fetch_metadata_rejects_cross_origin_without_origin_header(
    fetch_site: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(rig_ai_routes, "save_settings", lambda body: pytest.fail("Key write"))
    client = TestClient(create_studio_app(), base_url="http://127.0.0.1:8765")
    response = client.post(
        "/api/rig-ai/settings",
        json={"mode": "manual"},
        headers={"Sec-Fetch-Site": fetch_site},
    )
    assert response.status_code == 403


@pytest.mark.parametrize(
    "base_url,headers",
    [
        (
            "http://127.0.0.1:8765",
            {"Origin": "http://127.0.0.1:8765", "Sec-Fetch-Site": "same-origin"},
        ),
        ("http://127.0.0.1:8765", {}),
        ("http://127.0.0.1:8765", {"Sec-Fetch-Site": "none"}),
        ("http://localhost", {"Origin": "http://localhost:80"}),
        # The bundled Starlette TestClient cannot parse an IPv6 transport URL;
        # the Host header still exercises the actual ASGI request origin handling.
        ("http://localhost:8765", {"Host": "[::1]:8765", "Origin": "http://[::1]:8765"}),
    ],
)
def test_studio_allows_same_origin_and_native_clients(
    base_url: str,
    headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []
    monkeypatch.setattr(rig_ai_routes, "save_settings", lambda body: calls.append(body))
    monkeypatch.setattr(rig_ai_routes, "get_settings", lambda: {"mode": "manual"})
    client = TestClient(create_studio_app(), base_url=base_url)
    response = client.post("/api/rig-ai/settings", json={"mode": "manual"}, headers=headers)
    assert response.status_code == 200
    assert calls == [{"mode": "manual"}]
