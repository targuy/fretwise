"""Tests for the favorite-partitions web API.

Favorites are stored as a small JSON companion file (``favorites.json``) in
the active storage backend, mirroring the ``songs.tsv`` catalog pattern
(see ``test_web_song_catalog.py``). This means the same code path serves
single-user local runs and each multi-user's own cloud storage.
"""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from fretwise.storage import FAVORITES_NAME
from fretwise.web.app import create_app


def _make_library(tmp_path: Path) -> Path:
    (tmp_path / "Aerosmith - Back In The Saddle - 10-16-2024.gp").write_bytes(b"x")
    (tmp_path / "Pink Floyd - Time.gp").write_bytes(b"y")
    return tmp_path


def _client(tmp_path: Path) -> TestClient:
    app = create_app(fixtures_dir=tmp_path)
    return TestClient(app)


def test_favorites_empty_by_default(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.get("/api/favorites")
    assert resp.status_code == 200
    assert resp.json() == {"favorites": []}


def test_add_favorite_persists_to_storage(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.post("/api/favorites/Pink Floyd - Time.gp")
        assert resp.status_code == 200
        assert resp.json() == {"favorites": ["Pink Floyd - Time.gp"]}

        get_resp = client.get("/api/favorites")
        assert get_resp.json() == {"favorites": ["Pink Floyd - Time.gp"]}

    saved = json.loads((tmp_path / FAVORITES_NAME).read_text(encoding="utf-8"))
    assert saved == ["Pink Floyd - Time.gp"]


def test_add_favorite_round_trips_through_a_fresh_client(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        client.post("/api/favorites/Pink Floyd - Time.gp")
    # A brand-new TestClient/app instance must read the same favorites.json.
    with _client(tmp_path) as client2:
        resp = client2.get("/api/favorites")
    assert resp.json() == {"favorites": ["Pink Floyd - Time.gp"]}


def test_remove_favorite(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        client.post("/api/favorites/Pink Floyd - Time.gp")
        resp = client.delete("/api/favorites/Pink Floyd - Time.gp")
    assert resp.status_code == 200
    assert resp.json() == {"favorites": []}


def test_remove_non_favorite_is_a_noop(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.delete("/api/favorites/Pink Floyd - Time.gp")
    assert resp.status_code == 200
    assert resp.json() == {"favorites": []}


def test_add_favorite_rejects_invalid_filename(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.post("/api/favorites/not-a-score.txt")
    assert resp.status_code == 400


def test_files_endpoint_reports_favorite_flag(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        client.post("/api/favorites/Pink Floyd - Time.gp")
        resp = client.get("/api/files")
    files = {f["name"]: f for f in resp.json()}
    assert files["Pink Floyd - Time.gp"]["favorite"] is True
    assert files["Aerosmith - Back In The Saddle - 10-16-2024.gp"]["favorite"] is False
