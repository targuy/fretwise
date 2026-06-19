"""Tests for local email+password accounts, hashing, and the mailer fallback."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from fretwise.auth.accounts import (
    ACTIVATION_TTL_SECONDS,
    EmailAlreadyRegistered,
    LocalAccountStore,
    normalize_email,
)
from fretwise.auth.mailer import SmtpConfig, send_activation_email
from fretwise.auth.passwords import hash_password, verify_password

# --- password hashing -------------------------------------------------------

def test_hash_and_verify_roundtrip() -> None:
    enc = hash_password("correct horse battery staple")
    assert enc.startswith("pbkdf2_sha256$")
    assert verify_password("correct horse battery staple", enc)
    assert not verify_password("wrong password", enc)


def test_verify_rejects_garbage_and_empty_raises() -> None:
    assert verify_password("x", "not-a-valid-hash") is False
    with pytest.raises(ValueError):
        hash_password("")


def test_hashes_are_salted_unique() -> None:
    assert hash_password("same") != hash_password("same")


# --- account registration / activation --------------------------------------

def test_register_creates_inactive_account_with_token(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    acc = store.register("Alice@Example.com", "supersecret")
    assert acc.email == "alice@example.com"  # normalized
    assert acc.user_id == "local:alice@example.com"
    assert acc.is_active is False
    assert acc.activation_token
    # password is stored hashed, never in plaintext on disk
    blob = next((tmp_path / "accounts").glob("*.json")).read_text()
    assert "supersecret" not in blob


def test_register_duplicate_and_validation(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    store.register("bob@example.com", "supersecret")
    with pytest.raises(EmailAlreadyRegistered):
        store.register("bob@example.com", "anotherpass")
    with pytest.raises(ValueError):
        store.register("not-an-email", "supersecret")
    with pytest.raises(ValueError):
        store.register("c@example.com", "short")


def test_activation_flow(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    acc = store.register("dora@example.com", "supersecret")
    token = acc.activation_token
    assert store.activate("wrong-token") is None
    activated = store.activate(token)
    assert activated is not None and activated.is_active
    assert activated.activation_token is None
    # token is single-use
    assert store.activate(token) is None


def test_expired_token_cannot_activate(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    acc = store.register("eve@example.com", "supersecret")
    token = acc.activation_token
    acc.token_created = time.time() - (ACTIVATION_TTL_SECONDS + 60)
    store._save(acc)  # noqa: SLF001 - test pokes the persisted record
    assert store.activate(token) is None


def test_verify_login_requires_active_and_correct_password(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    acc = store.register("fred@example.com", "supersecret")
    # inactive -> no login even with right password
    assert store.verify_login("fred@example.com", "supersecret") is None
    store.activate(acc.activation_token)
    assert store.verify_login("fred@example.com", "wrong") is None
    ok = store.verify_login("Fred@Example.com", "supersecret")  # email case-insensitive
    assert ok is not None and ok.is_active


def test_resend_issues_new_token_for_inactive(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    acc = store.register("gwen@example.com", "supersecret")
    first = acc.activation_token
    again = store.new_activation_token("gwen@example.com")
    assert again is not None and again.activation_token not in (None, first)
    # once active, resend is a no-op (stays active, no token)
    store.activate(again.activation_token)
    after = store.new_activation_token("gwen@example.com")
    assert after is not None and after.is_active


# --- env-configured local admin seeding -------------------------------------

def test_ensure_admin_seeds_preactivated_account(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    pw_hash = hash_password("admin-secret-pw")
    admin = store.ensure_admin("Admin@Example.com", pw_hash)
    assert admin.email == "admin@example.com"  # normalized
    assert admin.user_id == "local:admin@example.com"
    assert admin.is_active is True
    assert admin.activation_token is None
    # logs in immediately (pre-activated) with the matching password…
    assert store.verify_login("admin@example.com", "admin-secret-pw") is not None
    # …and not with a wrong one.
    assert store.verify_login("admin@example.com", "wrong-pw") is None
    # password is never persisted in plaintext.
    blob = next((tmp_path / "accounts").glob("*.json")).read_text()
    assert "admin-secret-pw" not in blob


def test_ensure_admin_is_idempotent_and_rotates_hash(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    first_hash = hash_password("first-password")
    a1 = store.ensure_admin("admin@example.com", first_hash)
    # Re-seed with the same hash: no change, still works.
    a2 = store.ensure_admin("admin@example.com", first_hash)
    assert a2.password_hash == a1.password_hash
    assert store.verify_login("admin@example.com", "first-password") is not None
    # Re-seed with a new hash: rotates the stored credential.
    second_hash = hash_password("second-password")
    store.ensure_admin("admin@example.com", second_hash)
    assert store.verify_login("admin@example.com", "second-password") is not None
    assert store.verify_login("admin@example.com", "first-password") is None


def test_ensure_admin_reactivates_existing_inactive_account(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    # A normal (inactive) registration for the same email.
    store.register("admin@example.com", "registered-pw")
    assert store.verify_login("admin@example.com", "registered-pw") is None  # inactive
    # Seeding as admin activates it and sets the env hash.
    store.ensure_admin("admin@example.com", hash_password("env-admin-pw"))
    assert store.verify_login("admin@example.com", "env-admin-pw") is not None
    assert store.verify_login("admin@example.com", "registered-pw") is None


def test_ensure_admin_rejects_empty(tmp_path: Path) -> None:
    store = LocalAccountStore(tmp_path)
    with pytest.raises(ValueError):
        store.ensure_admin("", hash_password("x-password"))
    with pytest.raises(ValueError):
        store.ensure_admin("admin@example.com", "")


def test_normalize_email() -> None:
    assert normalize_email("  Foo@BAR.com ") == "foo@bar.com"


# --- mailer -----------------------------------------------------------------

def test_send_activation_email_console_fallback_when_unconfigured() -> None:
    # No SMTP host configured -> returns False, logs the link, never raises.
    sent = send_activation_email(
        "user@example.com",
        "https://app.example/auth/activate?token=abc",
        config=SmtpConfig(),
    )
    assert sent is False
