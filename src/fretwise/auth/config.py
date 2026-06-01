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

    def provider(self, name: str) -> OIDCProvider | None:
        for p in self.providers:
            if p.name == name:
                return p
        return None

    def is_admin_email(self, email: str) -> bool:
        return bool(email) and email.strip().lower() in self.admin_emails


def load_auth_config() -> AuthConfig:
    """Build the :class:`AuthConfig` from the environment."""
    providers = _load_providers()
    enabled = _env_bool("FRETWISE_AUTH_ENABLED") or bool(providers)
    data_dir = Path(os.environ.get("FRETWISE_DATA_DIR", str(Path.home() / ".fretwise" / "data")))
    default_cache = str(Path(tempfile.gettempdir()) / "fretwise-cache")
    cache_root = Path(os.environ.get("FRETWISE_STORAGE_CACHE_ROOT", default_cache))
    admin_emails = frozenset(
        e.strip().lower()
        for e in os.environ.get("FRETWISE_ADMIN_EMAILS", "").split(",")
        if e.strip()
    )
    return AuthConfig(
        enabled=enabled,
        secret_key=os.environ.get("FRETWISE_SECRET_KEY", ""),
        base_url=os.environ.get("FRETWISE_BASE_URL", "").rstrip("/"),
        data_dir=data_dir,
        cache_root=cache_root,
        providers=providers,
        admin_emails=admin_emails,
    )


__all__ = ["AuthConfig", "OIDCProvider", "load_auth_config"]
