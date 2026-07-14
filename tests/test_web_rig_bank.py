"""HTTP tests for the GP-180 rig-bank endpoints."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from fretwise.web import settings as web_settings
from fretwise.web.app import create_app


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    (tmp_path / "rigs").mkdir()
    app = create_app(fixtures_dir=tmp_path)
    return TestClient(app)


def test_rig_bank_profile_binding_resolve_and_dry_run(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    profile = {
        "id": "vh-right-now",
        "name": "Right Now Lead",
        "program": 199,
        "artist": "Van Halen",
    }
    profile_res = client.post("/api/rig-bank/profile", json=profile)
    assert profile_res.status_code == 200

    binding_res = client.post(
        "/api/rig-bank/binding",
        json={"scope": "song", "key": "Right Now", "profile_id": "vh-right-now"},
    )
    assert binding_res.status_code == 200

    resolve_res = client.post(
        "/api/rig-bank/resolve",
        json={"filename": "Van Halen - Right Now - 04-25-2026.gp"},
    )
    assert resolve_res.status_code == 200
    resolved = resolve_res.json()
    assert resolved["source"] == "song_binding"
    assert resolved["profile"]["id"] == "vh-right-now"
    assert resolved["midi"] == [[176, 0, 1], [192, 71]]

    activate_res = client.post(
        "/api/rig-bank/activate",
        json={"filename": "Van Halen - Right Now - 04-25-2026.gp"},
    )
    assert activate_res.status_code == 200
    assert activate_res.json()["dry_run"] is True
    assert activate_res.json()["sent"] is False


def test_gp180_control_surface_catalog_and_dry_run_action(
    tmp_path: Path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    client.post(
        "/api/rig-bank/profile",
        json={
            "id": "acdc",
            "name": "046 Back in DC",
            "program": 45,
            "genre": "hard rock",
        },
    )

    catalog_res = client.get("/api/control-surface/gp180")

    assert catalog_res.status_code == 200
    catalog = catalog_res.json()
    assert catalog["schema_version"] == "fretwise_gp180_control_surface_v1"
    profile_action = next(
        action for action in catalog["actions"] if action["id"] == "gp180.profile.acdc"
    )
    assert profile_action["status"] == "ready"
    assert profile_action["midi"] == [[176, 0, 0], [192, 45]]

    action_res = client.post(
        "/api/control-surface/gp180/action",
        json={"action_id": "gp180.profile.acdc", "dry_run": True},
    )

    assert action_res.status_code == 200
    payload = action_res.json()
    assert payload["sent"] is False
    assert payload["profile"]["id"] == "acdc"
    assert payload["midi"] == [[176, 0, 0], [192, 45]]


def test_rig_bank_resolve_uses_catalog_genre(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "songs.tsv"
    catalog.write_text(
        "filename\ttitle\tartist\tgenre\n"
        "Unknown - Quiet Track.gp\tQuiet Track\tUnknown\tAmbient\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    web_settings.save({"index_path": str(catalog)})
    (tmp_path / "rigs").mkdir()
    client = TestClient(create_app(fixtures_dir=tmp_path))

    client.post(
        "/api/rig-bank/profile",
        json={"id": "ambient-pad", "name": "Ambient Pad", "program": 15},
    )
    client.post(
        "/api/rig-bank/binding",
        json={"scope": "genre", "key": "Ambient", "profile_id": "ambient-pad"},
    )

    res = client.post("/api/rig-bank/resolve", json={"filename": "Unknown - Quiet Track.gp"})

    assert res.status_code == 200
    assert res.json()["source"] == "genre_binding"
    assert res.json()["profile"]["id"] == "ambient-pad"


def test_rig_bank_recommend_uses_catalog_genre(tmp_path: Path, monkeypatch) -> None:
    catalog = tmp_path / "songs.tsv"
    catalog.write_text(
        "filename\ttitle\tartist\tgenre\n"
        "Unknown - Long Crescendo.gp\tLong Crescendo\tUnknown\tAmbient Post-Rock\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    web_settings.save({"index_path": str(catalog)})
    (tmp_path / "rigs").mkdir()
    client = TestClient(create_app(fixtures_dir=tmp_path))

    client.post(
        "/api/rig-bank/profile",
        json={
            "id": "post-rock",
            "name": "POST ROCK",
            "program": 40,
            "genre": "post-rock",
            "tags": ["ambient"],
        },
    )

    res = client.post(
        "/api/rig-bank/recommend",
        json={"filename": "Unknown - Long Crescendo.gp"},
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["source"] == "genre_match"
    assert payload["profile"]["id"] == "post-rock"
    assert payload["context"]["genre"] == "Ambient Post-Rock"
    assert payload["reasons"]


def test_rig_bank_recommend_uses_active_ai_rig_modules(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    for profile in (
        {
            "id": "one-match",
            "name": "One Match",
            "program": 3,
            "modules": [{"module": "AMP", "model": "UK 50", "active": True}],
        },
        {
            "id": "two-matches",
            "name": "Two Matches",
            "program": 4,
            "modules": [
                {"module": "AMP", "model": "UK 50", "active": True},
                {"module": "DLY", "model": "Tape", "active": True},
            ],
        },
    ):
        assert client.post("/api/rig-bank/profile", json=profile).status_code == 200

    res = client.post(
        "/api/rig-bank/recommend",
        json={
            "artist": "Unknown",
            "rig_modules": [
                {"module": "AMP", "model": "UK 50", "active": True},
                {"module": "DLY", "model": "Tape", "active": True},
            ],
        },
    )

    assert res.status_code == 200
    payload = res.json()
    assert payload["source"] == "module_match"
    assert payload["profile"]["id"] == "two-matches"
    assert payload["module_match"]["positive_matches"] == 1
    assert payload["module_match"]["amp_match_module"] == "AMP"
    assert payload["context"]["active_module_count"] == 2


def test_rig_bank_resolve_returns_404_when_no_profile_matches(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    res = client.post("/api/rig-bank/resolve", json={"artist": "Nobody"})

    assert res.status_code == 404
