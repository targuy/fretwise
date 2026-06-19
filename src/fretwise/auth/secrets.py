"""Per-user encrypted credential store.

Each user's cloud credentials live in their own file, encrypted at rest with a
server-held key (see :mod:`fretwise.auth.crypto`). Credentials are keyed by user
id and never shared between users, never logged, and never written to the plain
config / user record.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Any

from fretwise.auth.crypto import Cipher, get_cipher


def _secret_filename(user_id: str) -> str:
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest() + ".enc"


class UserSecretsStore:
    """Store/retrieve a per-user credential dict, encrypted on disk."""

    def __init__(self, data_dir: Path, *, cipher: Cipher | None = None) -> None:
        """Create the store.

        Args:
            data_dir: Base directory; secrets live under ``data_dir/secrets``.
            cipher: Cipher to use. Defaults to the Fernet cipher derived from
                ``FRETWISE_SECRET_KEY`` (built lazily so the store can be
                constructed even before a key is configured).
        """
        self._dir = Path(data_dir) / "secrets"
        self._cipher = cipher

    def _get_cipher(self) -> Cipher:
        if self._cipher is None:
            self._cipher = get_cipher()
        return self._cipher

    def _path(self, user_id: str) -> Path:
        return self._dir / _secret_filename(user_id)

    def get(self, user_id: str) -> dict[str, Any] | None:
        """Return the decrypted credential dict for *user_id*, or ``None``."""
        path = self._path(user_id)
        if not path.is_file():
            return None
        try:
            token = path.read_bytes()
            plaintext = self._get_cipher().decrypt(token)
            data = json.loads(plaintext.decode("utf-8"))
        except Exception:  # noqa: BLE001 - corrupt/unreadable secrets must not crash
            return None
        return data if isinstance(data, dict) else None

    def set(self, user_id: str, credentials: dict[str, Any]) -> None:
        """Encrypt and persist *credentials* for *user_id* (0600 perms)."""
        self._dir.mkdir(parents=True, exist_ok=True)
        token = self._get_cipher().encrypt(
            json.dumps(credentials, ensure_ascii=False).encode("utf-8")
        )
        path = self._path(user_id)
        tmp = path.with_suffix(".enc.tmp")
        tmp.write_bytes(token)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)

    def delete(self, user_id: str) -> None:
        """Remove stored credentials for *user_id* (no error if absent)."""
        try:
            self._path(user_id).unlink()
        except FileNotFoundError:
            pass


__all__ = ["UserSecretsStore"]
