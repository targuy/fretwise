"""Tests for the LLM song-metadata catalog workflow (web API).

Covers the three endpoints the frontend calls to enrich the per-user
``songs.tsv`` catalog with the help of the user's own LLM:

* ``GET  /api/songs/export-list`` — the JSON list pasted into the LLM
* ``GET  /api/songs/prompt``      — the Markdown prompt for the LLM
* ``POST /api/songs/import``      — merge the LLM's JSON back into ``songs.tsv``

Plus: the catalog is persisted to (and re-read from) the user's storage
backend, and ``/api/files`` sources its metadata from that stored catalog.
"""

from __future__ import annotations

from pathlib import Path

from types import SimpleNamespace

from fastapi.testclient import TestClient

from fretwise.storage import CATALOG_NAME
from fretwise.storage.base import StorageNotFoundError
from fretwise.web.app import _load_catalog
from fretwise.web.app import create_app
from fretwise.web.songs_index import load_index_from_text


def _make_library(tmp_path: Path) -> Path:
    """Create a fixtures dir with two score files and return it."""
    (tmp_path / "Aerosmith - Back In The Saddle - 10-16-2024.gp").write_bytes(b"x")
    (tmp_path / "Pink Floyd - Time.gp").write_bytes(b"y")
    return tmp_path


def _client(tmp_path: Path) -> TestClient:
    app = create_app(fixtures_dir=tmp_path)
    return TestClient(app)


# ── export-list ─────────────────────────────────────────────────────


def test_export_list_shape(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.get("/api/songs/export-list")
    assert resp.status_code == 200
    body = resp.json()
    assert body["count"] == 2
    names = {s["filename"] for s in body["songs"]}
    assert "Pink Floyd - Time.gp" in names
    for song in body["songs"]:
        assert set(song) == {"filename", "title", "artist"}
    # Title/artist are derived from the filename.
    saddle = next(s for s in body["songs"] if s["filename"].startswith("Aerosmith"))
    assert saddle["title"] == "Back In The Saddle"
    assert saddle["artist"] == "Aerosmith"


def test_export_list_download_sets_attachment(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        resp = client.get("/api/songs/export-list?download=1")
    assert resp.status_code == 200
    assert "fretwise-songs.json" in resp.headers["content-disposition"]


# ── prompt ──────────────────────────────────────────────────────────


def test_prompt_is_markdown_attachment(tmp_path):
    with _client(tmp_path) as client:
        resp = client.get("/api/songs/prompt")
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/markdown")
    assert "fretwise-metadata-prompt.md" in resp.headers["content-disposition"]
    body = resp.text
    # Self-contained: states the task, the exact output keys, and JSON-only rule.
    for key in ("filename", "title", "artist", "album", "genre", "year", "notes"):
        assert key in body
    assert "ONLY" in body or "only" in body


# ── import ──────────────────────────────────────────────────────────


def test_import_array_writes_catalog_to_storage(tmp_path):
    _make_library(tmp_path)
    payload = [
        {"filename": "Pink Floyd - Time.gp", "title": "Time",
         "artist": "Pink Floyd", "album": "The Dark Side of the Moon",
         "genre": "Prog Rock", "year": "1973", "notes": ""},
    ]
    with _client(tmp_path) as client:
        resp = client.post("/api/songs/import", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"updated": 0, "added": 1, "total": 1}
    # Persisted to the user's storage as songs.tsv.
    saved = (tmp_path / CATALOG_NAME).read_text(encoding="utf-8")
    idx = load_index_from_text(saved)
    assert idx["Pink Floyd - Time.gp"]["album"] == "The Dark Side of the Moon"


def test_import_accepts_songs_wrapper_object(tmp_path):
    _make_library(tmp_path)
    payload = {"songs": [{"filename": "A.gp", "title": "T"}]}
    with _client(tmp_path) as client:
        resp = client.post("/api/songs/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["added"] == 1


def test_import_merges_and_reports_updated_and_added(tmp_path):
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        first = client.post(
            "/api/songs/import",
            json=[{"filename": "A.gp", "title": "Old", "genre": "Rock"}],
        )
        assert first.json() == {"updated": 0, "added": 1, "total": 1}
        second = client.post(
            "/api/songs/import",
            json=[
                {"filename": "A.gp", "title": "New"},   # update
                {"filename": "B.gp", "title": "Fresh"},  # add
            ],
        )
    assert second.json() == {"updated": 1, "added": 1, "total": 2}
    saved = (tmp_path / CATALOG_NAME).read_text(encoding="utf-8")
    idx = load_index_from_text(saved)
    assert idx["A.gp"]["title"] == "New"
    assert idx["A.gp"]["genre"] == "Rock"  # untouched field preserved
    assert idx["B.gp"]["title"] == "Fresh"


def test_import_rejects_non_json_body(tmp_path):
    with _client(tmp_path) as client:
        resp = client.post(
            "/api/songs/import",
            content=b"not json at all",
            headers={"content-type": "application/json"},
        )
    assert resp.status_code == 400


def test_import_rejects_non_list_payload(tmp_path):
    with _client(tmp_path) as client:
        resp = client.post("/api/songs/import", json={"not": "a list"})
    assert resp.status_code == 400


def test_import_round_trips_through_storage_read(tmp_path):
    """A second import reads back the catalog it just wrote (storage round-trip)."""
    _make_library(tmp_path)
    with _client(tmp_path) as client:
        client.post("/api/songs/import", json=[{"filename": "A.gp", "genre": "Rock"}])
        # Second import must see A.gp already present (read_bytes round-trip),
        # so updating it counts as an update, not an add.
        resp = client.post(
            "/api/songs/import", json=[{"filename": "A.gp", "genre": "Metal"}]
        )
    assert resp.json() == {"updated": 1, "added": 0, "total": 1}


# ── /api/files sources the catalog from the user's storage (multi-user) ──


class _FakeStorage:
    """Minimal storage stub exposing only read_bytes for catalog loading."""

    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = files

    def read_bytes(self, name: str) -> bytes:
        if name not in self._files:
            raise StorageNotFoundError(name)
        return self._files[name]


def test_load_catalog_reads_songs_tsv_from_user_storage(monkeypatch):
    """In multi-user mode the catalog comes from storage's songs.tsv."""
    import fretwise.web.app as app_module

    tsv = b"filename\tgenre\nSong.gp\tProg Rock\n"
    fake = _FakeStorage({CATALOG_NAME: tsv})
    monkeypatch.setattr(app_module, "_current_storage", lambda app: fake)

    app = SimpleNamespace(state=SimpleNamespace(multiuser=True))
    catalog = _load_catalog(app)  # type: ignore[arg-type]
    assert catalog["Song.gp"]["genre"] == "Prog Rock"


def test_load_catalog_falls_back_when_storage_has_no_catalog(monkeypatch):
    """No songs.tsv in storage -> fall back to the configured index_path."""
    import fretwise.web.app as app_module

    fake = _FakeStorage({})  # read_bytes raises StorageNotFoundError
    monkeypatch.setattr(app_module, "_current_storage", lambda app: fake)
    # index_path unset -> empty catalog, no crash.
    monkeypatch.setattr(app_module._settings, "load", lambda: {"index_path": ""})

    app = SimpleNamespace(state=SimpleNamespace(multiuser=True))
    assert _load_catalog(app) == {}  # type: ignore[arg-type]
