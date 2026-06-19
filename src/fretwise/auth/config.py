"""Auth configuration, loaded from the environment.

Multi-user auth is *off by default*: with no configuration FretWise runs exactly
as the original single-user app (so existing behaviour and tests are unchanged).
It turns on when at least one OIDC provider is configured (or
``FRETWISE_AUTH_ENABLED`` is truthy).

Relevant environment variables::

    FRETWISE_AUTH_ENABLED        1 / true to force-enable
    FRETWISE_SECRET_KEY          session signing + credential encryption (required)
    FRETWISE_BASE_URL            public base URL, for OAuth redirect_uri
    FRETWISE_DATA_DIR            where users + encrypted secrets live
    FRETWISE_STORAGE_CACHE_ROOT  transient per-user download cache root

    # Local admin login (no Google/OIDC required)
    FRETWISE_ADMIN_EMAIL         email for the pre-seeded local admin account
    FRETWISE_ADMIN_PASSWORD_HASH PBKDF2 hash of the admin password (NEVER the
                                 plaintext) — generate it with `fretwise hash-password`

    # Google (preset)
    FRETWISE_GOOGLE_CLIENT_ID / FRETWISE_GOOGLE_CLIENT_SECRET
    # Generic OIDC provider
    FRETWISE_OIDC_NAME / FRETWISE_OIDC_ISSUER (…/.well-known/openid-configuration)
    FRETWISE_OIDC_CLIENT_ID / FRETWISE_OIDC_CLIENT_SECRET
"""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class OIDCProvider:
    """A single OpenID Connect provider."""

    name: str                       # short id used in the login URL (e.g. "google")
    client_id: str
    client_secret: str
    server_metadata_url: str        # OIDC discovery document URL
    scopes: str = "openid email profile"


def _env_bool(key: str) -> bool:
    return os.environ.get(key, "").strip().lower() in {"1", "true", "yes", "on"}


def _load_providers() -> list[OIDCProvider]:
    providers: list[OIDCProvider] = []
    g_id = os.environ.get("FRETWISE_GOOGLE_CLIENT_ID", "")
    g_secret = os.environ.get("FRETWISE_GOOGLE_CLIENT_SECRET", "")
    if g_id and g_secret:
        providers.append(OIDCProvider(
            name="google",
            client_id=g_id,
            client_secret=g_secret,
            server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
            # Full Drive access so FretWise can list/read files the user drops
            # into the FretWise folder manually (drive.file only sees app-created
            # files). This is a Google "restricted" scope: keep test-users set
            # or verify the app for production.
            scopes="openid email profile https://www.googleapis.com/auth/drive",
        ))
    o_issuer = os.environ.get("FRETWISE_OIDC_ISSUER", "")
    o_id = os.environ.get("FRETWISE_OIDC_CLIENT_ID", "")
    o_secret = os.environ.get("FRETWISE_OIDC_CLIENT_SECRET", "")
    if o_issuer and o_id and o_secret:
        url = o_issuer.rstrip("/")
        if not url.endswith("openid-configuration"):
            url += "/.well-known/openid-configuration"
        providers.append(OIDCProvider(
            name=os.environ.get("FRETWISE_OIDC_NAME", "oidc"),
            client_id=o_id,
            client_secret=o_secret,
            server_metadata_url=url,
        ))
    return providers


@dataclass(frozen=True)
class AuthConfig:
    """Resolved multi-user auth configuration."""

    enabled: bool
    secret_key: str
    base_url: str
    data_dir: Path
    cache_root: Path
    providers: list[OIDCProvider] = field(default_factory=list)
    # Lower-cased emails granted admin rights (access to the server-local
    # partitions library). From FRETWISE_ADMIN_EMAILS (comma-separated).
    admin_emails: frozenset[str] = field(default_factory=frozenset)
    # Pre-seeded local admin account: email + a PBKDF2 password *hash* (never a
    # plaintext password). When both are set, a pre-activated admin account is
    # ensured on startup so the app is usable without any OIDC provider.
    admin_email: str = ""
    admin_password_hash: str = ""

    def provider(self, name: str) -> OIDCProvider | None:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def is_admin_email(self, email: str) -> bool:
        return bool(email) and email.strip().lower() in self.admin_emails

    @property
    def has_local_admin(self) -> bool:
        """Whether an env-configured local admin account should be seeded."""
        return bool(self.admin_email and self.admin_password_hash)


def load_auth_config() -> AuthConfig:
    """Build the :class:`AuthConfig` from the environment."""
    providers = _load_providers()
    # Local admin account, configured in the (gitignored) .env. Primary form is a
    # plain username + password:
    #     FRETWISE_ADMIN=benoit
    #     FRETWISE_ADMIN_PASSWD=<REMOVED_SECRET>
    # The plaintext is read only from the environment (never committed) and hashed
    # here at startup, so the on-disk account store holds a hash, not the password.
    # The username is used directly as the local-login identifier (the email/
    # password login route treats it as an opaque key). The older
    # FRETWISE_ADMIN_EMAIL + FRETWISE_ADMIN_PASSWORD_HASH form is still accepted.
    admin_email = os.environ.get("FRETWISE_ADMIN_EMAIL", "").strip().lower()
    admin_password_hash = os.environ.get("FRETWISE_ADMIN_PASSWORD_HASH", "").strip()
    admin_username = os.environ.get("FRETWISE_ADMIN", "").strip().lower()
    admin_passwd = os.environ.get("FRETWISE_ADMIN_PASSWD", "")
    if admin_username and admin_passwd:
        from fretwise.auth.passwords import hash_password
        admin_email = admin_username  # used as the local login identifier/key
        admin_password_hash = hash_password(admin_passwd)
    has_local_admin = bool(admin_email and admin_password_hash)
    # A configured local admin (email + password hash) is enough to turn auth on:
    # password login then works with no OIDC provider configured.
    enabled = _env_bool("FRETWISE_AUTH_ENABLED") or bool(providers) or has_local_admin
    data_dir = Path(os.environ.get("FRETWISE_DATA_DIR", str(Path.home() / ".fretwise" / "data")))
    default_cache = str(Path(tempfile.gettempdir()) / "fretwise-cache")
    cache_root = Path(os.environ.get("FRETWISE_STORAGE_CACHE_ROOT", default_cache))
    admin_emails = set(
        e.strip().lower()
        for e in os.environ.get("FRETWISE_ADMIN_EMAILS", "").split(",")
        if e.strip()
    )
    # The local admin email is implicitly an admin (server-local library access).
    if admin_email:
        admin_emails.add(admin_email)
    return AuthConfig(
        enabled=enabled,
        secret_key=os.environ.get("FRETWISE_SECRET_KEY", ""),
        base_url=os.environ.get("FRETWISE_BASE_URL", "").rstrip("/"),
        data_dir=data_dir,
        cache_root=cache_root,
        providers=providers,
        admin_emails=frozenset(admin_emails),
        admin_email=admin_email,
        admin_password_hash=admin_password_hash,
    )


__all__ = ["AuthConfig", "OIDCProvider", "load_auth_config"]
