"""JSON-backed user store (one file per user).

MVP persistence per the project plan (JSON now, SQLite in a later phase). Each
user is stored at ``<data_dir>/users/<sha256(id)>.json`` so arbitrary provider
subjects map to safe filenames and users never collide or leak across files.
"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from fretwise.auth.models import User


def _user_filename(user_id: str) -> str:
    """Map an arbitrary user id to a safe, collision-resistant filename."""
    return hashlib.sha256(user_id.encode("utf-8")).hexdigest() + ".json"


class UserStore:
    """Persist and look up :class:`User` records on disk."""

    def __init__(self, data_dir: Path) -> None:
        """Create the store.

        Args:
            data_dir: Base directory; users live under ``data_dir/users``.
        """
        self._dir = Path(data_dir) / "users"

    def _path(self, user_id: str) -> Path:
        return self._dir / _user_filename(user_id)

    def get(self, user_id: str) -> User | None:
        """Return the user with *user_id*, or ``None`` if unknown."""
        path = self._path(user_id)
        if not path.is_file():
            return None
        try:
            return User.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, KeyError):
            return None

    def save(self, user: User) -> User:
        """Create or overwrite *user* atomically."""
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(user.id)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(user.to_json(), indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, path)
        return user

    def get_or_create(
        self, user_id: str, *, email: str = "", name: str = "", is_admin: bool = False,
    ) -> User:
        """Return the existing user or create one (self-service signup).

        Profile fields — including admin status, derived from the configured
        admin-email allowlist — are refreshed from the identity provider on
        each login.
        """
        existing = self.get(user_id)
        if existing is not None:
            changed = False
            if email and existing.email != email:
                existing.email, changed = email, True
            if name and existing.name != name:
                existing.name, changed = name, True
            if existing.is_admin != is_admin:
                existing.is_admin, changed = is_admin, True
            if changed:
                self.save(existing)
            return existing
        return self.save(User(id=user_id, email=email, name=name, is_admin=is_admin))

    def set_storage(self, user_id: str, backend: str, config: dict[str, object]) -> User:
        """Update a user's (non-secret) storage configuration."""
        user = self.get(user_id)
        if user is None:
            raise KeyError(user_id)
        user.storage_backend = backend
        user.storage_config = dict(config)
        return self.save(user)


__all__ = ["UserStore"]
