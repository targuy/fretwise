"""Local filesystem storage backend (the default)."""

from __future__ import annotations

from pathlib import Path

from fretwise.storage.base import (
    SUPPORTED_SCORE_EXTS,
    StorageBackend,
    StorageNotFoundError,
    StorageObject,
    StorageValidationError,
    safe_score_name,
)


class LocalStorageBackend(StorageBackend):
    """Serve score files from a directory on the local filesystem.

    This preserves FretWise's original behaviour: ``root`` is the partitions
    directory and every operation is confined to it.
    """

    name = "local"

    def __init__(self, root: Path) -> None:
        """Create the backend.

        Args:
            root: Directory containing the score files.
        """
        self._root = Path(root)

    @property
    def supports_batch_refresh(self) -> bool:
        return True

    @property
    def local_root(self) -> Path | None:
        return self._root

    def _resolve(self, name: str) -> Path:
        """Validate *name* and return its contained path inside ``root``."""
        safe = safe_score_name(name)
        path = self._root / safe
        # Defence in depth: reject symlink escapes out of the root.
        try:
            path.resolve().relative_to(self._root.resolve())
        except ValueError as exc:
            raise StorageValidationError(f"Access denied: {safe}") from exc
        return path

    def list_scores(self) -> list[StorageObject]:
        if not self._root.exists():
            return []
        objects: list[StorageObject] = []
        for f in sorted(self._root.iterdir()):
            if f.is_file() and f.suffix.lower() in SUPPORTED_SCORE_EXTS:
                try:
                    st = f.stat()
                    objects.append(
                        StorageObject(name=f.name, size=st.st_size, modified=st.st_mtime)
                    )
                except OSError:
                    objects.append(StorageObject(name=f.name))
        return objects

    def exists(self, name: str) -> bool:
        try:
            return self._resolve(name).is_file()
        except StorageValidationError:
            return False

    def stat(self, name: str) -> StorageObject | None:
        path = self._resolve(name)
        if not path.is_file():
            return None
        st = path.stat()
        return StorageObject(name=path.name, size=st.st_size, modified=st.st_mtime)

    def read_bytes(self, name: str) -> bytes:
        path = self._resolve(name)
        if not path.is_file():
            raise StorageNotFoundError(f"File not found: {path.name}")
        return path.read_bytes()

    def write_bytes(self, name: str, data: bytes) -> None:
        path = self._resolve(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)

    def delete(self, name: str) -> None:
        path = self._resolve(name)
        if not path.is_file():
            raise StorageNotFoundError(f"File not found: {path.name}")
        path.unlink()

    def ensure_local(self, name: str) -> Path:
        path = self._resolve(name)
        if not path.is_file():
            raise StorageNotFoundError(f"File not found: {path.name}")
        return path


__all__ = ["LocalStorageBackend"]
