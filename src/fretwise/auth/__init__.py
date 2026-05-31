"""Multi-user accounts, OIDC auth and per-user storage resolution.

Auth is opt-in: with no OIDC provider configured the app stays single-user and
unchanged. When enabled, each user authenticates via OIDC (e.g. Google), is
auto-provisioned on first login, and connects *their own* cloud storage — the
server never hosts a shared partition library.
"""

from fretwise.auth.accounts import (
    EmailAlreadyRegistered,
    LocalAccount,
    LocalAccountStore,
)
from fretwise.auth.config import AuthConfig, OIDCProvider, load_auth_config
from fretwise.auth.models import USER_STORAGE_BACKENDS, User
from fretwise.auth.passwords import hash_password, verify_password
from fretwise.auth.resolver import (
    StorageNotConfigured,
    resolve_user_storage,
    user_cache_dir,
)
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore

__all__ = [
    "USER_STORAGE_BACKENDS",
    "AuthConfig",
    "EmailAlreadyRegistered",
    "LocalAccount",
    "LocalAccountStore",
    "OIDCProvider",
    "StorageNotConfigured",
    "User",
    "UserSecretsStore",
    "UserStore",
    "hash_password",
    "load_auth_config",
    "resolve_user_storage",
    "user_cache_dir",
    "verify_password",
]
