"""Pluggable storage backends for FretWise partitions (score files).

Public surface:
    StorageBackend        — abstract backend interface
    StorageObject         — metadata for one stored score file
    LocalStorageBackend   — default local-directory backend
    build_backend         — construct the configured backend from settings
    SUPPORTED_SCORE_EXTS  — allowlisted score extensions
    safe_score_name       — sanitize a user-supplied object name
    StorageError + subclasses — domain exceptions

Cloud backends (S3-compatible, WebDAV/Nextcloud, Google Drive) live in their own
modules and pull in optional dependencies only when actually constructed via
:func:`build_backend`.
"""

from fretwise.storage.base import (
    SUPPORTED_SCORE_EXTS,
    StorageBackend,
    StorageBackendUnavailable,
    StorageError,
    StorageNotFoundError,
    StorageObject,
    StorageValidationError,
    safe_score_name,
)
from fretwise.storage.factory import build_backend
from fretwise.storage.local import LocalStorageBackend

__all__ = [
    "SUPPORTED_SCORE_EXTS",
    "LocalStorageBackend",
    "StorageBackend",
    "StorageBackendUnavailable",
    "StorageError",
    "StorageNotFoundError",
    "StorageObject",
    "StorageValidationError",
    "build_backend",
    "safe_score_name",
]
