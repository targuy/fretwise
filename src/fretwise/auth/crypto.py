"""Symmetric encryption for credentials at rest.

User cloud credentials must be stored server-side (the server uses them to reach
each user's own storage) but never in plaintext. We encrypt them with Fernet
(AES-128-CBC + HMAC) using a key derived from the ``FRETWISE_SECRET_KEY``
environment variable.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Protocol


class Cipher(Protocol):
    """Minimal reversible-cipher interface (Fernet-compatible)."""

    def encrypt(self, data: bytes) -> bytes: ...

    def decrypt(self, token: bytes) -> bytes: ...


class CipherUnavailable(RuntimeError):
    """Raised when encryption is requested but no key/backend is available."""


def _fernet_key_from_passphrase(passphrase: str) -> bytes:
    """Derive a valid 32-byte url-safe Fernet key from an arbitrary string."""
    digest = hashlib.sha256(passphrase.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest)


def get_cipher(secret_key: str | None = None) -> Cipher:
    """Return a Fernet cipher derived from *secret_key* / ``FRETWISE_SECRET_KEY``.

    Args:
        secret_key: Override for the env var (mainly for tests).

    Raises:
        CipherUnavailable: If no key is configured or ``cryptography`` is not
            installed. Callers should treat this as "cannot store cloud
            credentials" and surface a clear setup error.
    """
    key_material = (
        secret_key if secret_key is not None else os.environ.get("FRETWISE_SECRET_KEY", "")
    )
    if not key_material:
        raise CipherUnavailable(
            "FRETWISE_SECRET_KEY is not set — cannot encrypt user credentials."
        )
    try:
        from cryptography.fernet import Fernet  # type: ignore[import-untyped]
    except ImportError as exc:  # pragma: no cover - depends on optional dep
        raise CipherUnavailable(
            "The 'cryptography' package is required to store user credentials."
        ) from exc
    return Fernet(_fernet_key_from_passphrase(key_material))


__all__ = ["Cipher", "CipherUnavailable", "get_cipher"]
