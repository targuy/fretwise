"""Tests for the pluggable partitions storage layer."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fretwise.storage import (
    LocalStorageBackend,
    StorageObject,
    StorageValidationError,
    build_backend,
    safe_score_name,
)
from fretwise.storage.base import StorageBackendUnavailable, StorageNotFoundError
from fretwise.storage.remote import RemoteStorageBackend

# --- name safety ------------------------------------------------------------

def test_safe_score_name_strips_traversal() -> None:
    assert safe_score_name("a/b/../song.gp") == "song.gp"
    assert safe_score_name("/etc/Song.GP") == "Song.GP"


def test_safe_score_name_rejects_bad_inputs() -> None:
    for bad in ("id_rsa", "passwd", "..", "", "evil.sh"):
        with pytest.raises(StorageValidationError):
            safe_score_name(bad)


# --- local backend ----------------------------------------------------------

def test_local_backend_lists_only_supported_files(tmp_path: Path) -> None:
    (tmp_path / "song.gp").write_bytes(b"PK\x03\x04")
    (tmp_path / "tune.mid").write_bytes(b"MThd")
    (tmp_path / "notes.txt").write_text("ignore me")
    backend = LocalStorageBackend(tmp_path)
    names = sorted(o.name for o in backend.list_scores())
    assert names == ["song.gp", "tune.mid"]


def test_local_backend_read_write_delete_roundtrip(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    backend.write_bytes("new.gp", b"hello")
    assert backend.exists("new.gp")
    assert backend.read_bytes("new.gp") == b"hello"
    assert backend.ensure_local("new.gp") == tmp_path / "new.gp"
    stat = backend.stat("new.gp")
    assert stat is not None and stat.size == 5
    backend.delete("new.gp")
    assert not backend.exists("new.gp")


def test_local_backend_missing_file_raises(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    with pytest.raises(StorageNotFoundError):
        backend.read_bytes("nope.gp")


def test_local_backend_supports_batch_refresh(tmp_path: Path) -> None:
    backend = LocalStorageBackend(tmp_path)
    assert backend.supports_batch_refresh is True
    assert backend.local_root == tmp_path


# --- factory ----------------------------------------------------------------

def test_build_backend_local(tmp_path: Path) -> None:
    backend = build_backend({"storage_backend": "local"}, local_root=tmp_path)
    assert isinstance(backend, LocalStorageBackend)


def test_build_backend_unknown_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageValidationError):
        build_backend({"storage_backend": "bogus"}, local_root=tmp_path)


def test_build_backend_s3_requires_bucket_or_sdk(tmp_path: Path) -> None:
    """Without boto3 (or without a bucket) S3 construction must fail loudly."""
    with pytest.raises(StorageBackendUnavailable):
        build_backend(
            {"storage_backend": "s3", "storage_s3": {"bucket": ""}},
            local_root=tmp_path,
        )


# --- remote cache logic (provider-agnostic) ---------------------------------

class _FakeRemote(RemoteStorageBackend):
    """In-memory remote store for exercising the cache half of ensure_local."""

    name = "fake"

    def __init__(self, cache_dir: Path) -> None:
        super().__init__(cache_dir)
        self.store: dict[str, tuple[bytes, float]] = {}
        self.downloads = 0

    def list_scores(self) -> list[StorageObject]:
        return [
            StorageObject(name=n, size=len(d), modified=m)
            for n, (d, m) in self.store.items()
        ]

    def stat(self, name: str) -> StorageObject | None:
        safe = self._safe(name)
        if safe not in self.store:
            return None
        data, mtime = self.store[safe]
        return StorageObject(name=safe, size=len(data), modified=mtime)

    def read_bytes(self, name: str) -> bytes:
        self.downloads += 1
        safe = self._safe(name)
        if safe not in self.store:
            raise StorageNotFoundError(safe)
        return self.store[safe][0]

    def write_bytes(self, name: str, data: bytes) -> None:
        self.store[self._safe(name)] = (data, time.time())

    def delete(self, name: str) -> None:
        self.store.pop(self._safe(name), None)


def test_remote_ensure_local_caches_and_refreshes(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    remote = _FakeRemote(cache)
    remote.store["song.gp"] = (b"v1", 1000.0)

    p1 = remote.ensure_local("song.gp")
    assert p1.read_bytes() == b"v1"
    assert remote.downloads == 1

    # Second call hits the cache (no new download).
    p2 = remote.ensure_local("song.gp")
    assert p2 == p1
    assert remote.downloads == 1

    # Remote gets a newer copy -> cache is refreshed.
    remote.store["song.gp"] = (b"v2-newer", 2000.0)
    p3 = remote.ensure_local("song.gp")
    assert p3.read_bytes() == b"v2-newer"
    assert remote.downloads == 2


def test_remote_ensure_local_missing_raises(tmp_path: Path) -> None:
    remote = _FakeRemote(tmp_path / "cache")
    with pytest.raises(StorageNotFoundError):
        remote.ensure_local("ghost.gp")


# --- S3 mapping via an injected fake client ---------------------------------

class _FakePaginator:
    def __init__(self, pages: list[dict]) -> None:
        self._pages = pages

    def paginate(self, **_kwargs: object) -> list[dict]:
        return self._pages


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def get_paginator(self, _name: str) -> _FakePaginator:
        contents = [
            {"Key": k, "Size": len(v)} for k, v in self.objects.items()
        ]
        return _FakePaginator([{"Contents": contents}])

    def head_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
        if Key not in self.objects:
            raise RuntimeError("404")
        return {"ContentLength": len(self.objects[Key])}

    def get_object(self, *, Bucket: str, Key: str) -> dict:  # noqa: N803
        class _Body:
            def __init__(self, data: bytes) -> None:
                self._data = data

            def read(self) -> bytes:
                return self._data

        return {"Body": _Body(self.objects[Key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:  # noqa: N803
        self.objects[Key] = Body

    def delete_object(self, *, Bucket: str, Key: str) -> None:  # noqa: N803
        self.objects.pop(Key, None)


def test_s3_backend_with_injected_client_prefix(tmp_path: Path) -> None:
    from fretwise.storage.s3 import S3StorageBackend

    client = _FakeS3Client()
    backend = S3StorageBackend(
        bucket="b", prefix="scores", cache_dir=tmp_path, client=client,
    )
    backend.write_bytes("song.gp", b"abc")
    # Stored under the prefix.
    assert "scores/song.gp" in client.objects
    assert [o.name for o in backend.list_scores()] == ["song.gp"]
    assert backend.exists("song.gp")
    assert backend.read_bytes("song.gp") == b"abc"
    local = backend.ensure_local("song.gp")
    assert local.read_bytes() == b"abc"
    backend.delete("song.gp")
    assert not backend.exists("song.gp")


# --- WebDAV PROPFIND parsing ------------------------------------------------

def test_webdav_parse_multistatus_filters_collections() -> None:
    pytest.importorskip("defusedxml")
    from fretwise.storage.webdav import WebDavStorageBackend

    xml = """<?xml version="1.0"?>
    <d:multistatus xmlns:d="DAV:">
      <d:response>
        <d:href>/dav/Partitions/</d:href>
        <d:propstat><d:prop><d:resourcetype><d:collection/></d:resourcetype>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/dav/Partitions/Song%20One.gp</d:href>
        <d:propstat><d:prop>
          <d:getcontentlength>123</d:getcontentlength>
          <d:getlastmodified>Wed, 15 Mar 2026 09:49:27 GMT</d:getlastmodified>
          <d:resourcetype/>
        </d:prop></d:propstat>
      </d:response>
      <d:response>
        <d:href>/dav/Partitions/notes.txt</d:href>
        <d:propstat><d:prop><d:getcontentlength>9</d:getcontentlength>
        <d:resourcetype/></d:prop></d:propstat>
      </d:response>
    </d:multistatus>"""
    objects = WebDavStorageBackend._parse_multistatus(xml)
    names = [o.name for o in objects]
    assert names == ["Song One.gp"]  # folder + .txt filtered out
    assert objects[0].size == 123
    assert objects[0].modified > 0
