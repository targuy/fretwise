"""Build a :class:`StorageBackend` from app configuration.

Configuration lives in the regular settings (``config.json``); **credentials do
not** — those are read from the environment / secrets file by each backend.

Relevant config keys::

    storage_backend: "local" | "s3" | "webdav" | "gdrive"   (default "local")
    partitions_dir:  local directory (local backend root / cache base)
    storage_cache_dir: optional cache dir override for cloud backends
    storage_s3:     {bucket, prefix, endpoint_url, region}
    storage_webdav: {base_url}
    storage_gdrive: {folder_id}
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fretwise.storage.base import StorageBackend, StorageValidationError
from fretwise.storage.local import LocalStorageBackend

_VALID_BACKENDS = frozenset({"local", "s3", "webdav", "gdrive"})


def _default_cache_dir(kind: str) -> Path:
    return Path.home() / ".fretwise" / "cache" / kind


def build_backend(cfg: dict[str, Any], *, local_root: Path) -> StorageBackend:
    """Construct the configured storage backend.

    Args:
        cfg: Settings dict (see module docstring for the relevant keys).
        local_root: Directory used as the local backend root and as the default
            cache base for cloud backends.

    Returns:
        A ready-to-use :class:`StorageBackend`.

    Raises:
        StorageValidationError: If ``storage_backend`` is unknown.
        StorageBackendUnavailable: If a cloud backend is missing its SDK or
            required configuration.
    """
    kind = str(cfg.get("storage_backend", "local") or "local").lower()
    if kind not in _VALID_BACKENDS:
        raise StorageValidationError(f"Unknown storage_backend: {kind!r}")

    if kind == "local":
        return LocalStorageBackend(Path(local_root))

    cache_dir = Path(cfg.get("storage_cache_dir") or _default_cache_dir(kind))

    if kind == "s3":
        from fretwise.storage.s3 import S3StorageBackend

        c = cfg.get("storage_s3", {}) or {}
        return S3StorageBackend(
            bucket=str(c.get("bucket", "")),
            prefix=str(c.get("prefix", "")),
            endpoint_url=(c.get("endpoint_url") or None),
            region=(c.get("region") or None),
            cache_dir=cache_dir,
        )

    if kind == "webdav":
        from fretwise.storage.webdav import WebDavStorageBackend

        c = cfg.get("storage_webdav", {}) or {}
        return WebDavStorageBackend(
            base_url=str(c.get("base_url", "")),
            cache_dir=cache_dir,
        )

    # kind == "gdrive"
    from fretwise.storage.gdrive import GoogleDriveStorageBackend

    c = cfg.get("storage_gdrive", {}) or {}
    return GoogleDriveStorageBackend(
        folder_id=str(c.get("folder_id", "")),
        cache_dir=cache_dir,
    )


__all__ = ["build_backend"]
