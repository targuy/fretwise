"""Security-hardening regression tests for the web app."""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from fretwise.auth.models import User
from fretwise.auth.web import _REQUEST_USER
from fretwise.web.app import (
    _MAX_SCORE_UPLOAD_BYTES,
    _read_upload_limited,
    _require_admin,
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


# --- _require_admin: server-global routes gated in multi-user ---------------

def test_require_admin_is_noop_in_single_user(tmp_path: Path) -> None:
    app = create_app(tmp_path)  # no auth configured -> single-user
    assert app.state.multiuser is False
    _require_admin(app)  # must not raise


def test_require_admin_blocks_anonymous_and_non_admin(tmp_path: Path) -> None:
    app = create_app(tmp_path)
    app.state.multiuser = True  # simulate multi-user without standing up OIDC

    # Anonymous (no request user) -> 401
    with pytest.raises(HTTPException) as exc:
        _require_admin(app)
    assert exc.value.status_code == 401

    # Authenticated non-admin -> 403
    token = _REQUEST_USER.set(User(id="google:u", is_admin=False))
    try:
        with pytest.raises(HTTPException) as exc:
            _require_admin(app)
        assert exc.value.status_code == 403
    finally:
        _REQUEST_USER.reset(token)

    # Admin -> allowed
    token = _REQUEST_USER.set(User(id="google:a", is_admin=True))
    try:
        _require_admin(app)  # must not raise
    finally:
        _REQUEST_USER.reset(token)


def test_multiuser_setup_fails_closed_without_secret_key(monkeypatch: Any) -> None:
    """Configuring OIDC but no FRETWISE_SECRET_KEY must refuse to boot, never
    silently degrade to unauthenticated single-user."""
    pytest.importorskip("authlib")
    monkeypatch.setenv("FRETWISE_GOOGLE_CLIENT_ID", "x")
    monkeypatch.setenv("FRETWISE_GOOGLE_CLIENT_SECRET", "y")
    monkeypatch.delenv("FRETWISE_SECRET_KEY", raising=False)
    monkeypatch.delenv("FRETWISE_AUTH_ENABLED", raising=False)
    with pytest.raises(RuntimeError):
        create_app()


# --- env-configured local admin (password login, no OIDC) -------------------

def _clear_auth_env(monkeypatch: Any) -> None:
    for var in (
        "FRETWISE_AUTH_ENABLED", "FRETWISE_GOOGLE_CLIENT_ID", "FRETWISE_GOOGLE_CLIENT_SECRET",
        "FRETWISE_OIDC_ISSUER", "FRETWISE_OIDC_CLIENT_ID", "FRETWISE_OIDC_CLIENT_SECRET",
        "FRETWISE_ADMIN_EMAILS", "FRETWISE_ADMIN_EMAIL", "FRETWISE_ADMIN_PASSWORD_HASH",
        "FRETWISE_SECRET_KEY", "FRETWISE_BASE_URL",
    ):
        monkeypatch.delenv(var, raising=False)


def test_local_admin_no_oidc_seeds_admin_and_logs_in(monkeypatch: Any, tmp_path: Path) -> None:
    """Local admin (email + password hash, no OIDC) boots into multi-user mode,
    seeds a pre-activated admin, and serves password login + admin-only routes."""
    pytest.importorskip("itsdangerous")
    from starlette.testclient import TestClient

    from fretwise.auth.passwords import hash_password

    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("FRETWISE_SECRET_KEY", "test-secret-key-not-a-password")
    monkeypatch.setenv("FRETWISE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRETWISE_ADMIN_EMAIL", "admin@example.com")
    # NOTE: the password is hashed here at test time; only the hash hits the env.
    monkeypatch.setenv("FRETWISE_ADMIN_PASSWORD_HASH", hash_password("test-admin-password"))

    app = create_app(tmp_path / "partitions")
    assert app.state.multiuser is True

    # The admin account was seeded, pre-activated, from the env hash.
    seeded = app.state.account_store.get("admin@example.com")
    assert seeded is not None and seeded.is_active

    with TestClient(app) as client:
        # No OIDC providers, password method available.
        methods = client.get("/api/auth/methods").json()
        assert methods["password"] is True
        assert methods["providers"] == []

        # Wrong password -> 401.
        bad = client.post(
            "/api/auth/login", json={"email": "admin@example.com", "password": "wrong"},
        )
        assert bad.status_code == 401

        # Correct password -> session established, recognised as admin.
        ok = client.post(
            "/api/auth/login",
            json={"email": "admin@example.com", "password": "test-admin-password"},
        )
        assert ok.status_code == 200
        me = client.get("/api/me").json()
        assert me["authenticated"] is True and me["is_admin"] is True
        # Admin gets the server-local library as a storage option.
        assert "local" in me["available_backends"]


def test_local_admin_reseed_is_idempotent_across_app_creates(
    monkeypatch: Any, tmp_path: Path,
) -> None:
    pytest.importorskip("itsdangerous")
    from fretwise.auth.passwords import hash_password

    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("FRETWISE_SECRET_KEY", "test-secret-key")
    monkeypatch.setenv("FRETWISE_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("FRETWISE_ADMIN_EMAIL", "admin@example.com")
    monkeypatch.setenv("FRETWISE_ADMIN_PASSWORD_HASH", hash_password("first-pw"))

    app1 = create_app(tmp_path / "partitions")
    assert app1.state.account_store.verify_login("admin@example.com", "first-pw") is not None

    # Recreate the app with a rotated hash -> the stored credential updates.
    monkeypatch.setenv("FRETWISE_ADMIN_PASSWORD_HASH", hash_password("second-pw"))
    app2 = create_app(tmp_path / "partitions")
    store = app2.state.account_store
    assert store.verify_login("admin@example.com", "second-pw") is not None
    assert store.verify_login("admin@example.com", "first-pw") is None
    # Still exactly one account file (idempotent, no duplicates).
    assert len(list((tmp_path / "data" / "accounts").glob("*.json"))) == 1


def test_single_user_mode_unchanged_when_no_auth(monkeypatch: Any, tmp_path: Path) -> None:
    _clear_auth_env(monkeypatch)
    app = create_app(tmp_path)
    assert app.state.multiuser is False
    assert app.state.__dict__.get("account_store") is None  # no auth wiring in single-user
