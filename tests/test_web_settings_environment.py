"""Deployment-owned web settings tests."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from fretwise.web import settings as web_settings
from fretwise.web.app import create_app


def _isolated_settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    config_dir = tmp_path / "config"
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", config_dir)
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", config_dir / "config.json")


def test_environment_paths_override_stale_persisted_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated_settings(tmp_path, monkeypatch)
    web_settings._CONFIG_DIR.mkdir()
    web_settings._CONFIG_FILE.write_text(
        json.dumps(
            {
                "partitions_dir": "D:/old/partitions",
                "soundfonts_dir": "D:/old/sounds",
                "gears_dir": "D:/old/gears",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("FRETWISE_PARTITIONS_DIR", "/data/partitions")
    monkeypatch.setenv("FRETWISE_SOUNDFONTS_DIR", "/data/sounds")
    monkeypatch.setenv("FRETWISE_GEARS_DIR", "/data/gears")

    loaded = web_settings.load()

    assert loaded["partitions_dir"] == "/data/partitions"
    assert loaded["soundfonts_dir"] == "/data/sounds"
    assert loaded["gears_dir"] == "/data/gears"


def test_save_cannot_replace_environment_owned_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated_settings(tmp_path, monkeypatch)
    monkeypatch.setenv("FRETWISE_PARTITIONS_DIR", "/data/partitions")

    saved = web_settings.save({"partitions_dir": "D:/escape", "index_path": "index.tsv"})

    assert saved["partitions_dir"] == "/data/partitions"
    assert saved["index_path"] == "index.tsv"


def test_settings_api_rejects_environment_owned_path(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _isolated_settings(tmp_path, monkeypatch)
    monkeypatch.delenv("FRETWISE_REQUIRE_ML_MODELS", raising=False)
    monkeypatch.setenv("FRETWISE_PARTITIONS_DIR", str(tmp_path))
    (tmp_path / "rigs").mkdir()
    client = TestClient(create_app(fixtures_dir=tmp_path, runtime_profile="server"))

    response = client.post("/api/settings", json={"partitions_dir": str(tmp_path / "other")})

    assert response.status_code == 409
    assert response.json()["detail"] == {
        "code": "setting_managed_by_environment",
        "settings": ["partitions_dir"],
    }
