"""Data models for multi-user accounts.

A :class:`User` is created automatically on first OIDC login (self-service
signup). The server stores **no partition files** — each user points FretWise
at *their own* cloud storage (S3 / WebDAV / Google Drive). Only the non-secret
storage configuration lives on the user record; credentials are held
separately and encrypted (see :mod:`fretwise.auth.secrets`).
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Backends a user is allowed to choose. The on-server "local" backend is
# intentionally excluded: the server must not host a shared library of
# partitions (copyright — users are responsible for their own files).
USER_STORAGE_BACKENDS: frozenset[str] = frozenset({"s3", "webdav", "gdrive"})


@dataclass
class User:
    """A registered user and their (non-secret) storage configuration.

    Attributes:
        id: Stable identity, ``"<provider>:<subject>"`` (e.g. ``"google:117…"``).
        email: Email from the identity provider.
        name: Display name from the identity provider.
        created_at: Epoch seconds of first login.
        storage_backend: One of :data:`USER_STORAGE_BACKENDS`, or ``""`` when the
            user has not configured storage yet.
        storage_config: Non-secret backend config (bucket/prefix/endpoint_url,
            base_url, folder_id …). Never contains credentials.
    """

    id: str
    email: str = ""
    name: str = ""
    created_at: float = field(default_factory=time.time)
    storage_backend: str = ""
    storage_config: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        """Serialize to a JSON-safe dict."""
        return {
            "id": self.id,
            "email": self.email,
            "name": self.name,
            "created_at": self.created_at,
            "storage_backend": self.storage_backend,
            "storage_config": self.storage_config,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> User:
        """Rebuild a user from its serialized form (tolerant of missing keys)."""
        return cls(
            id=str(data["id"]),
            email=str(data.get("email", "")),
            name=str(data.get("name", "")),
            created_at=float(data.get("created_at", time.time())),
            storage_backend=str(data.get("storage_backend", "")),
            storage_config=dict(data.get("storage_config", {}) or {}),
        )

    @property
    def has_storage(self) -> bool:
        """Whether the user has a usable storage backend configured."""
        return self.storage_backend in USER_STORAGE_BACKENDS


__all__ = ["USER_STORAGE_BACKENDS", "User"]
