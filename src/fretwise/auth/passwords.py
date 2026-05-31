"""Password hashing for local (email + password) accounts.

Uses PBKDF2-HMAC-SHA256 from the standard library (no extra dependency). The
encoded form is self-describing so the iteration count can be raised later
without breaking existing hashes::

    pbkdf2_sha256$<iterations>$<salt_b64>$<hash_b64>
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

_ALGO = "pbkdf2_sha256"
_ITERATIONS = 600_000
_SALT_BYTES = 16


def _b64e(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _b64d(text: str) -> bytes:
    pad = "=" * (-len(text) % 4)
    return base64.urlsafe_b64decode(text + pad)


def hash_password(password: str, *, iterations: int = _ITERATIONS) -> str:
    """Return an encoded PBKDF2 hash of *password*."""
    if not password:
        raise ValueError("password must not be empty")
    salt = secrets.token_bytes(_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{_ALGO}${iterations}${_b64e(salt)}${_b64e(digest)}"


def verify_password(password: str, encoded: str) -> bool:
    """Return whether *password* matches the encoded hash (constant-time)."""
    try:
        algo, iter_str, salt_b64, hash_b64 = encoded.split("$")
        if algo != _ALGO:
            return False
        iterations = int(iter_str)
        salt = _b64d(salt_b64)
        expected = _b64d(hash_b64)
    except (ValueError, TypeError):
        return False
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(digest, expected)


__all__ = ["hash_password", "verify_password"]
