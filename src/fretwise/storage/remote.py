"""Shared base for remote (cloud) storage backends.

Implements the local-cache half of :meth:`StorageBackend.ensure_local` once, so
each provider backend only has to implement the remote primitives
(:meth:`list_scores`, :meth:`stat`, :meth:`read_bytes`, …).
"""

from __future__ import annotations

import os
from pathlib import Path

from fretwise.storage.base import (
    StorageBackend,
    StorageNotFoundError,
    StorageObject,
    safe_score_name,
)


class RemoteStorageBackend(StorageBackend):
    """A :class:`StorageBackend` that caches downloaded objects on local disk."""

    def __init__(self, cache_dir: Path) -> None:
        """Create the backend.

        Args:
            cache_dir: Directory used to cache downloaded objects so parsers
                (which need a real file path) can open them.
        """
        self._cache_dir = Path(cache_dir)

    @property
    def supports_batch_refresh(self) -> bool:
        # The in-place multiprocessing batch only works on a local directory.
        return False

    def _safe(self, name: str) -> str:
        """Validate and reduce *name* to a safe basename."""
        return safe_score_name(name)

    def ensure_local(self, name: str) -> Path:
        safe = self._safe(name)
        remote = self.stat(safe)
        if remote is None:
            raise StorageNotFoundError(f"File not found: {safe}")
        cache_path = self._cache_dir / safe
        # Reuse the cached copy when it is non-empty and at least as new as the
        # remote object; otherwise (re)download.
        try:
            if cache_path.is_file():
                st = cache_path.stat()
                if st.st_size > 0 and st.st_mtime >= (remote.modified or 0.0):
                    return cache_path
        except OSError:
            pass
        data = self.read_bytes(safe)
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        tmp_path = cache_path.with_suffix(cache_path.suffix + ".part")
        tmp_path.write_bytes(data)
        os.replace(tmp_path, cache_path)
        if remote.modified:
            try:
                os.utime(cache_path, (remote.modified, remote.modified))
            except OSError:
                pass
        return cache_path

    # Subclasses must still implement the remote primitives.
    def list_scores(self) -> list[StorageObject]:  # pragma: no cover - abstract
        raise NotImplementedError

    def exists(self, name: str) -> bool:
        return self.stat(self._safe(name)) is not None

    def stat(self, name: str) -> StorageObject | None:  # pragma: no cover - abstract
        raise NotImplementedError

    def read_bytes(self, name: str) -> bytes:  # pragma: no cover - abstract
        raise NotImplementedError

    def write_bytes(self, name: str, data: bytes) -> None:  # pragma: no cover - abstract
        raise NotImplementedError

    def delete(self, name: str) -> None:  # pragma: no cover - abstract
        raise NotImplementedError


__all__ = ["RemoteStorageBackend"]
