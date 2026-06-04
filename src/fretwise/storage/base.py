"""Pluggable storage backends for FretWise score files (partitions).

The web app no longer assumes a single local directory. A
:class:`StorageBackend` abstracts *where* score files live so the same routes
can serve files from the local disk, an S3-compatible object store, a WebDAV /
Nextcloud share, or Google Drive.

Parsers (PyGuitarPro / music21 / pretty_midi) all require a real local file
path, so every backend exposes :meth:`StorageBackend.ensure_local`, which
returns a readable local path — a no-op for the local backend, a cached
download for cloud backends.

Security note: credentials are **never** stored here or in the app config.
They are read from the environment / a separate secrets file by
:mod:`fretwise.storage.credentials`.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path

# Single source of truth for the score formats the app accepts. Imported by the
# web layer so the upload/download/list/parse allowlist stays consistent.
SUPPORTED_SCORE_EXTS: frozenset[str] = frozenset({
    ".gp3", ".gp4", ".gp5", ".gp",
    ".xml", ".mxl", ".musicxml",
    ".mid", ".midi",
})

# Per-user song-metadata catalog (TSV). It is *not* a score, so it is not part
# of SUPPORTED_SCORE_EXTS (it never appears in ``list_scores``), but the storage
# layer must still allow reading/writing this single, fixed name so the LLM
# metadata-enrichment workflow can persist it next to the user's scores.
CATALOG_NAME: str = "songs.tsv"


class StorageError(Exception):
    """Base error for the storage layer."""


class StorageValidationError(StorageError):
    """Raised for an unsafe or unsupported object name (maps to HTTP 400)."""


class StorageNotFoundError(StorageError):
    """Raised when an object does not exist (maps to HTTP 404)."""


class StorageBackendUnavailable(StorageError):
    """Raised when a backend is selected but its SDK/config is missing."""


@dataclass(frozen=True)
class StorageObject:
    """Metadata for a single stored score file.

    Attributes:
        name: Object name (basename, e.g. ``"Song.gp"``). Never a path.
        size: Size in bytes (``0`` if the backend cannot report it cheaply).
        modified: Last-modified time as epoch seconds (``0.0`` if unknown).
    """

    name: str
    size: int = 0
    modified: float = 0.0

    @property
    def stem(self) -> str:
        """Filename without its extension."""
        return Path(self.name).stem

    @property
    def format(self) -> str:
        """Uppercased extension without the dot (e.g. ``"GP"``)."""
        return Path(self.name).suffix.lstrip(".").upper()


def safe_score_name(name: str) -> str:
    """Validate and reduce *name* to a safe basename with a supported extension.

    Guards every backend against path traversal and arbitrary file types:
    the result can only ever be a single score file in the storage root.

    Args:
        name: User-supplied object name (possibly a path).

    Returns:
        The sanitized basename.

    Raises:
        StorageValidationError: If the name is empty or not a supported score
            format.
    """
    base = Path(name).name
    if not base or base in {".", ".."}:
        raise StorageValidationError(f"Invalid filename: {name!r}")
    # The metadata catalog is a fixed, non-score companion file; allow it through
    # so the song-catalog workflow can persist it alongside the user's scores.
    if base == CATALOG_NAME:
        return base
    if Path(base).suffix.lower() not in SUPPORTED_SCORE_EXTS:
        raise StorageValidationError(f"Unsupported file type: {base}")
    return base


class StorageBackend(ABC):
    """Abstract backend for listing, reading and writing score files."""

    #: Short identifier (``"local"``, ``"s3"``, ``"webdav"``, ``"gdrive"``).
    name: str = "abstract"

    @property
    def supports_batch_refresh(self) -> bool:
        """Whether the in-place multiprocessing refresh batch is supported.

        Only the local backend can be glob-walked and written back in place by
        worker processes. Cloud backends return ``False`` (the route reports a
        clear error instead of silently doing nothing).
        """
        return False

    @property
    def local_root(self) -> Path | None:
        """Local directory backing this storage, or ``None`` for remote stores."""
        return None

    @abstractmethod
    def list_scores(self) -> list[StorageObject]:
        """Return metadata for every supported score file in the store."""

    @abstractmethod
    def exists(self, name: str) -> bool:
        """Return whether *name* exists in the store."""

    @abstractmethod
    def stat(self, name: str) -> StorageObject | None:
        """Return metadata for *name*, or ``None`` if it does not exist."""

    @abstractmethod
    def read_bytes(self, name: str) -> bytes:
        """Return the raw bytes of *name*."""

    @abstractmethod
    def write_bytes(self, name: str, data: bytes) -> None:
        """Create or overwrite *name* with *data*."""

    @abstractmethod
    def delete(self, name: str) -> None:
        """Delete *name* from the store."""

    @abstractmethod
    def ensure_local(self, name: str) -> Path:
        """Return a readable local path for *name*.

        Local backends return the real file path. Cloud backends download the
        object into a local cache (refreshing it when the remote copy is newer)
        and return the cached path so parsers can open it.
        """


__all__ = [
    "CATALOG_NAME",
    "SUPPORTED_SCORE_EXTS",
    "StorageBackend",
    "StorageBackendUnavailable",
    "StorageError",
    "StorageNotFoundError",
    "StorageObject",
    "StorageValidationError",
    "safe_score_name",
]
