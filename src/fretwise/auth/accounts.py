"""Local email + password accounts with email activation.

A :class:`LocalAccount` is the credential record for password login; the user's
*profile* and storage config live in the separate :class:`~fretwise.auth.users.User`
record (created on activation/first login). Accounts are JSON files keyed by a
hash of the lower-cased email, one per account, under ``<data_dir>/accounts``.

Passwords are stored only as PBKDF2 hashes (see :mod:`fretwise.auth.passwords`).
A freshly registered account is **inactive** until the activation token from the
confirmation email is presented.
"""

from __future__ import annotations

import hashlib
import json
import os
import secrets
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from fretwise.auth.passwords import hash_password, verify_password

# Activation tokens are valid for this many seconds (24h).
ACTIVATION_TTL_SECONDS = 24 * 3600


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _account_filename(email: str) -> str:
    return hashlib.sha256(normalize_email(email).encode("utf-8")).hexdigest() + ".json"


@dataclass
class LocalAccount:
    """Credential record for an email + password account."""

    email: str
    password_hash: str
    user_id: str
    is_active: bool = False
    activation_token: str | None = None
    token_created: float = 0.0
    created_at: float = field(default_factory=time.time)

    def token_is_valid(self, token: str) -> bool:
        return (
            bool(self.activation_token)
            and bool(token)
            and secrets.compare_digest(self.activation_token, token)
            and (time.time() - self.token_created) <= ACTIVATION_TTL_SECONDS
        )


class AccountError(Exception):
    """Base error for local-account operations."""


class EmailAlreadyRegistered(AccountError):
    """Raised when registering an email that already has an account."""


class LocalAccountStore:
    """Persist and look up :class:`LocalAccount` records on disk."""

    def __init__(self, data_dir: Path) -> None:
        self._dir = Path(data_dir) / "accounts"

    def _path(self, email: str) -> Path:
        return self._dir / _account_filename(email)

    def get(self, email: str) -> LocalAccount | None:
        path = self._path(email)
        if not path.is_file():
            return None
        try:
            return LocalAccount(**json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError):
            return None

    def _save(self, account: LocalAccount) -> LocalAccount:
        self._dir.mkdir(parents=True, exist_ok=True)
        path = self._path(account.email)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(asdict(account), indent=2, ensure_ascii=False), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, path)
        return account

    def register(self, email: str, password: str) -> LocalAccount:
        """Create a new inactive account and return it (with an activation token).

        Raises:
            EmailAlreadyRegistered: If an account for *email* already exists.
            ValueError: If the email or password is missing/too short.
        """
        email = normalize_email(email)
        if "@" not in email or "." not in email.split("@")[-1]:
            raise ValueError("A valid email address is required")
        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")
        if self.get(email) is not None:
            raise EmailAlreadyRegistered(email)
        account = LocalAccount(
            email=email,
            password_hash=hash_password(password),
            user_id=f"local:{email}",
            is_active=False,
            activation_token=secrets.token_urlsafe(32),
            token_created=time.time(),
        )
        return self._save(account)

    def new_activation_token(self, email: str) -> LocalAccount | None:
        """Issue a fresh activation token (e.g. resend), if the account exists."""
        account = self.get(email)
        if account is None or account.is_active:
            return account
        account.activation_token = secrets.token_urlsafe(32)
        account.token_created = time.time()
        return self._save(account)

    def activate(self, token: str) -> LocalAccount | None:
        """Activate the account whose (valid) activation token equals *token*.

        Returns the activated account, or ``None`` if no account matches a valid,
        unexpired token.
        """
        if not token:
            return None
        if not self._dir.is_dir():
            return None
        for path in self._dir.glob("*.json"):
            try:
                account = LocalAccount(**json.loads(path.read_text(encoding="utf-8")))
            except (json.JSONDecodeError, OSError, TypeError):
                continue
            if account.token_is_valid(token):
                account.is_active = True
                account.activation_token = None
                account.token_created = 0.0
                return self._save(account)
        return None

    def verify_login(self, email: str, password: str) -> LocalAccount | None:
        """Return the account iff the password matches **and** it is active.

        Returns ``None`` for unknown email or wrong password; raises nothing.
        Callers should distinguish "inactive" via :attr:`LocalAccount.is_active`
        by fetching with :meth:`get` when they need a specific message.
        """
        account = self.get(email)
        if account is None:
            return None
        if not verify_password(password, account.password_hash):
            return None
        if not account.is_active:
            return None
        return account


__all__ = [
    "ACTIVATION_TTL_SECONDS",
    "AccountError",
    "EmailAlreadyRegistered",
    "LocalAccount",
    "LocalAccountStore",
    "normalize_email",
]
