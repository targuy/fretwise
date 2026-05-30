"""Security-hardening regression tests for the web app."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from fretwise.web.app import (
    _MAX_SCORE_UPLOAD_BYTES,
    _read_upload_limited,
    _resolve_allowed_hosts,
    _resolve_file,
    create_app,
)

# --- _resolve_file: extension allowlist (arbitrary-read fix) ----------------

def test_resolve_file_rejects_unsupported_extension(tmp_path: Path) -> None:
    """A non-score file in fixtures_dir must not be resolvable/served."""
    secret = tmp_path / "id_rsa"
    secret.write_text("PRIVATE KEY")
    app = create_app(tmp_path)
    with pytest.raises(HTTPException) as exc:
        _resolve_file(app, "id_rsa")
    assert exc.value.status_code == 400


def test_resolve_file_accepts_supported_score_file(tmp_path: Path) -> None:
    score = tmp_path / "song.gp"
    score.write_bytes(b"PK\x03\x04")  # zip magic — existence is all that matters here
    app = create_app(tmp_path)
    assert _resolve_file(app, "song.gp") == score


def test_resolve_file_strips_path_traversal(tmp_path: Path) -> None:
    """Even a supported extension cannot escape fixtures_dir via traversal."""
    app = create_app(tmp_path)
    with pytest.raises(HTTPException) as exc:
        _resolve_file(app, "../../evil.gp")
    # Basename-stripped to 'evil.gp' which does not exist -> 404 (never escapes).
    assert exc.value.status_code == 404


# --- _read_upload_limited: streaming size cap (DoS fix) ---------------------

class _FakeUpload:
    """Minimal async stand-in for starlette's UploadFile."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._sent = False

    async def read(self, _size: int = -1) -> bytes:
        if self._sent:
            return b""
        self._sent = True
        return self._data


def test_read_upload_limited_accepts_within_limit() -> None:
    payload = b"x" * 10
    got = asyncio.run(_read_upload_limited(_FakeUpload(payload), 1024))
    assert got == payload


def test_read_upload_limited_rejects_oversized() -> None:
    payload = b"x" * 4096
    with pytest.raises(HTTPException) as exc:
        asyncio.run(_read_upload_limited(_FakeUpload(payload), 16))
    assert exc.value.status_code == 413


def test_score_upload_limit_is_bounded() -> None:
    assert 0 < _MAX_SCORE_UPLOAD_BYTES <= 256 * 1024 * 1024


# --- host allowlist (DNS-rebinding fix) -------------------------------------

def test_resolve_allowed_hosts_defaults_to_loopback(monkeypatch: Any) -> None:
    monkeypatch.delenv("FRETWISE_ALLOWED_HOSTS", raising=False)
    hosts = _resolve_allowed_hosts(None)
    assert "127.0.0.1" in hosts
    assert "localhost" in hosts
    assert "*" not in hosts


def test_resolve_allowed_hosts_env_override(monkeypatch: Any) -> None:
    monkeypatch.setenv("FRETWISE_ALLOWED_HOSTS", "example.test, *")
    assert _resolve_allowed_hosts(None) == ["example.test", "*"]


def test_resolve_allowed_hosts_explicit_arg_wins(monkeypatch: Any) -> None:
    monkeypatch.setenv("FRETWISE_ALLOWED_HOSTS", "ignored.test")
    assert _resolve_allowed_hosts(["only.test"]) == ["only.test"]
