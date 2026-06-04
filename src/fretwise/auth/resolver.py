"""Resolve a per-user storage backend from their config + decrypted credentials.

Every partition request is served from the *logged-in user's own* cloud storage.
The server keeps no shared library: the on-server ``local`` backend is rejected
here, and downloads land only in a transient, per-user cache directory.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fretwise.auth.models import User, allowed_backends
from fretwise.storage.base import (
    StorageBackend,
    StorageError,
    StorageValidationError,
)

# A constructor builds a backend from (non-secret config, credentials, cache_dir).
Constructor = Callable[[dict[str, Any], dict[str, Any], Path], StorageBackend]


class StorageNotConfigured(StorageError):
    """Raised when a user has not yet configured their storage backend."""


def user_cache_dir(cache_root: Path, user_id: str) -> Path:
    """Return the transient per-user download cache directory.

    Isolated per user (hashed id) so cached downloads are never shared across
    users. This is a processing cache only — not a persistent library.
    """
    digest = hashlib.sha256(user_id.encode("utf-8")).hexdigest()[:32]
    return Path(cache_root) / digest


def _build_s3(config: dict[str, Any], creds: dict[str, Any], cache_dir: Path) -> StorageBackend:
    from fretwise.storage.s3 import S3StorageBackend, _build_client

    s3_creds: dict[str, str] = {}
    if creds.get("access_key_id"):
        s3_creds["aws_access_key_id"] = str(creds["access_key_id"])
    if creds.get("secret_access_key"):
        s3_creds["aws_secret_access_key"] = str(creds["secret_access_key"])
    if creds.get("session_token"):
        s3_creds["aws_session_token"] = str(creds["session_token"])
    client = _build_client(
        config.get("endpoint_url") or None,
        config.get("region") or None,
        credentials=s3_creds or None,
    )
    return S3StorageBackend(
        bucket=str(config.get("bucket", "")),
        prefix=str(config.get("prefix", "")),
        cache_dir=cache_dir,
        client=client,
    )


def _build_webdav(config: dict[str, Any], creds: dict[str, Any], cache_dir: Path) -> StorageBackend:
    from fretwise.storage.webdav import WebDavStorageBackend, _build_client

    base_url = str(config.get("base_url", ""))
    auth = None
    if creds.get("username"):
        auth = (str(creds["username"]), str(creds.get("password", "")))
    client = _build_client(base_url if base_url.endswith("/") else base_url + "/", auth)
    return WebDavStorageBackend(base_url=base_url, cache_dir=cache_dir, client=client)


def _build_gdrive(config: dict[str, Any], creds: dict[str, Any], cache_dir: Path) -> StorageBackend:
    from fretwise.storage.gdrive import GoogleDriveStorageBackend, service_from_oauth

    # The OAuth grant is stored under "google_oauth" (login + connect both write
    # that shape); fall back to a flat dict for older records / direct callers.
    token = creds.get("google_oauth") or creds
    service = service_from_oauth(token)
    return GoogleDriveStorageBackend(
        folder_id=str(config.get("folder_id", "")),
        cache_dir=cache_dir,
        service=service,
    )


DEFAULT_CONSTRUCTORS: dict[str, Constructor] = {
    "s3": _build_s3,
    "webdav": _build_webdav,
    "gdrive": _build_gdrive,
}


def resolve_user_storage(
    user: User,
    credentials: dict[str, Any] | None,
    *,
    cache_root: Path,
    local_root: Path | None = None,
    constructors: dict[str, Constructor] | None = None,
) -> StorageBackend:
    """Build the storage backend for *user* from their config + credentials.

    Args:
        user: The authenticated user.
        credentials: Decrypted credential dict (from the secrets store).
        cache_root: Base directory for transient per-user download caches.
        local_root: Server partitions directory. Only used to back the
            ``local`` backend for **admin** users; ignored otherwise.
        constructors: Cloud backend constructor map (injectable for tests).

    Raises:
        StorageNotConfigured: The user has not configured a backend yet.
        StorageValidationError: The configured backend is not available to this
            user (e.g. a non-admin selecting the on-server ``local`` backend).
    """
    ctors = constructors if constructors is not None else DEFAULT_CONSTRUCTORS
    backend = user.storage_backend
    if not backend and user.is_admin and local_root is not None:
        # Admins default to the server-local partitions library, so the local
        # admin sees the on-disk catalogue immediately after logging in without
        # first connecting a cloud backend. (They can still connect cloud
        # storage later, which sets storage_backend and takes precedence.)
        backend = "local"
    if not backend:
        raise StorageNotConfigured(
            "No storage configured. Connect your cloud storage in settings — "
            "FretWise does not host partitions on the server."
        )
    if backend not in allowed_backends(user.is_admin):
        raise StorageValidationError(
            f"Storage backend {backend!r} is not available to this user "
            "(the on-server library is admin-only)."
        )
    if backend == "local":
        # Admin-only access to the server-hosted partitions library.
        if local_root is None:
            raise StorageValidationError("Server-local storage is not available.")
        from fretwise.storage.local import LocalStorageBackend

        return LocalStorageBackend(local_root)
    ctor = ctors.get(backend)
    if ctor is None:
        raise StorageValidationError(f"Unsupported storage backend: {backend!r}")
    return ctor(user.storage_config, credentials or {}, user_cache_dir(cache_root, user.id))


__all__ = [
    "DEFAULT_CONSTRUCTORS",
    "StorageNotConfigured",
    "resolve_user_storage",
    "user_cache_dir",
]
