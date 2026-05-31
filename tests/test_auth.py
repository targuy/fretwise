"""Tests for multi-user accounts, encrypted secrets and per-user storage.

These cover everything that does not need the optional web deps (authlib /
itsdangerous): the user store, credential encryption (via ``cryptography``),
and the per-user storage resolver policy (with injected constructors).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from fretwise.auth.crypto import CipherUnavailable, get_cipher
from fretwise.auth.models import User, allowed_backends
from fretwise.auth.resolver import (
    StorageNotConfigured,
    resolve_user_storage,
    user_cache_dir,
)
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore
from fretwise.storage.base import StorageValidationError
from fretwise.storage.local import LocalStorageBackend

# --- User model -------------------------------------------------------------

def test_user_json_roundtrip() -> None:
    u = User(id="google:42", email="a@b.c", name="Ann", storage_backend="s3",
             storage_config={"bucket": "x"})
    again = User.from_json(u.to_json())
    assert again == u
    assert again.has_storage is True


def test_user_has_storage_false_for_unconfigured() -> None:
    assert User(id="google:1").has_storage is False
    assert User(id="google:1", storage_backend="local").has_storage is False  # local not allowed


# --- UserStore --------------------------------------------------------------

def test_user_store_get_or_create_and_refresh(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    assert store.get("google:1") is None
    u = store.get_or_create("google:1", email="a@b.c", name="Ann")
    assert u.email == "a@b.c"
    # Second login refreshes profile fields.
    u2 = store.get_or_create("google:1", email="new@b.c", name="Ann B")
    assert u2.email == "new@b.c" and u2.name == "Ann B"
    assert store.get("google:1") is not None


def test_user_store_set_storage(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    store.get_or_create("u1")
    store.set_storage("u1", "s3", {"bucket": "mine"})
    u = store.get("u1")
    assert u is not None and u.storage_backend == "s3"
    assert u.storage_config == {"bucket": "mine"}


def test_user_store_isolates_users_in_separate_files(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    store.get_or_create("google:1", email="one@x")
    store.get_or_create("google:2", email="two@x")
    files = list((tmp_path / "users").glob("*.json"))
    assert len(files) == 2  # one file per user, no shared store


# --- crypto + secrets -------------------------------------------------------

def test_cipher_requires_key() -> None:
    with pytest.raises(CipherUnavailable):
        get_cipher("")


def test_secrets_store_roundtrip_and_isolation(tmp_path: Path) -> None:
    cipher = get_cipher("unit-test-key")
    store = UserSecretsStore(tmp_path, cipher=cipher)
    store.set("u1", {"access_key_id": "AKIA", "secret_access_key": "s3cr3t"})
    store.set("u2", {"username": "bob", "password": "pw"})
    assert store.get("u1") == {"access_key_id": "AKIA", "secret_access_key": "s3cr3t"}
    assert store.get("u2") == {"username": "bob", "password": "pw"}
    assert store.get("u3") is None


def test_secrets_are_encrypted_at_rest(tmp_path: Path) -> None:
    cipher = get_cipher("unit-test-key")
    store = UserSecretsStore(tmp_path, cipher=cipher)
    store.set("u1", {"secret_access_key": "TOP-SECRET-VALUE"})
    blob = next((tmp_path / "secrets").glob("*.enc")).read_bytes()
    assert b"TOP-SECRET-VALUE" not in blob  # ciphertext, not plaintext


def test_secrets_delete(tmp_path: Path) -> None:
    store = UserSecretsStore(tmp_path, cipher=get_cipher("k"))
    store.set("u1", {"x": "y"})
    store.delete("u1")
    assert store.get("u1") is None
    store.delete("u1")  # idempotent


# --- per-user storage resolver ----------------------------------------------

def _fake_constructors(record: dict[str, Any]) -> dict[str, Any]:
    def make(kind: str) -> Any:
        def ctor(config: dict[str, Any], creds: dict[str, Any], cache_dir: Path) -> Any:
            record.update(kind=kind, config=config, creds=creds, cache_dir=cache_dir)
            return f"backend:{kind}"
        return ctor
    return {"s3": make("s3"), "webdav": make("webdav"), "gdrive": make("gdrive")}


def test_resolver_unconfigured_raises(tmp_path: Path) -> None:
    with pytest.raises(StorageNotConfigured):
        resolve_user_storage(User(id="u1"), None, cache_root=tmp_path)


def test_resolver_rejects_local_backend(tmp_path: Path) -> None:
    user = User(id="u1", storage_backend="local")
    with pytest.raises(StorageValidationError):
        resolve_user_storage(user, None, cache_root=tmp_path)


def test_resolver_builds_per_user_backend(tmp_path: Path) -> None:
    record: dict[str, Any] = {}
    user = User(id="u1", storage_backend="s3", storage_config={"bucket": "mine"})
    creds = {"access_key_id": "AKIA"}
    backend = resolve_user_storage(
        user, creds, cache_root=tmp_path,
        constructors=_fake_constructors(record),
    )
    assert backend == "backend:s3"
    assert record["config"] == {"bucket": "mine"}
    assert record["creds"] == {"access_key_id": "AKIA"}
    # Cache dir is isolated per user, under the cache root.
    assert record["cache_dir"] == user_cache_dir(tmp_path, "u1")
    assert tmp_path in record["cache_dir"].parents


def test_user_cache_dirs_are_distinct() -> None:
    a = user_cache_dir(Path("/cache"), "google:1")
    b = user_cache_dir(Path("/cache"), "google:2")
    assert a != b


# --- admin-only local storage (Option B) ------------------------------------

def test_allowed_backends_widen_for_admin() -> None:
    assert "local" not in allowed_backends(is_admin=False)
    assert "local" in allowed_backends(is_admin=True)
    # cloud backends available to everyone
    assert {"s3", "webdav", "gdrive"} <= allowed_backends(is_admin=False)


def test_admin_can_use_server_local_library(tmp_path: Path) -> None:
    server_lib = tmp_path / "partitions"
    server_lib.mkdir()
    user = User(id="g:admin", is_admin=True, storage_backend="local")
    backend = resolve_user_storage(
        user, None, cache_root=tmp_path / "cache", local_root=server_lib,
    )
    assert isinstance(backend, LocalStorageBackend)
    assert backend.local_root == server_lib


def test_non_admin_local_is_rejected(tmp_path: Path) -> None:
    user = User(id="g:user", is_admin=False, storage_backend="local")
    with pytest.raises(StorageValidationError):
        resolve_user_storage(
            user, None, cache_root=tmp_path, local_root=tmp_path / "partitions",
        )


def test_admin_local_without_local_root_is_unavailable(tmp_path: Path) -> None:
    user = User(id="g:admin", is_admin=True, storage_backend="local")
    with pytest.raises(StorageValidationError):
        resolve_user_storage(user, None, cache_root=tmp_path, local_root=None)


def test_user_store_refreshes_admin_flag(tmp_path: Path) -> None:
    store = UserStore(tmp_path)
    store.get_or_create("g:1", email="a@b.c", is_admin=False)
    promoted = store.get_or_create("g:1", email="a@b.c", is_admin=True)
    assert promoted.is_admin is True
    assert store.get("g:1").is_admin is True
