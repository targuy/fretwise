"""Credential loading for cloud storage backends.

Secrets are read from the process environment first, then from an optional
JSON secrets file (``~/.fretwise/secrets.json`` by default, overridable with
``FRETWISE_SECRETS_FILE``). They are deliberately kept **out** of the regular
``config.json`` so that synced/committed settings never carry access keys.

The secrets file, when present, is a flat JSON object, e.g.::

    {
      "AWS_ACCESS_KEY_ID": "...",
      "AWS_SECRET_ACCESS_KEY": "...",
      "WEBDAV_PASSWORD": "...",
      "GOOGLE_APPLICATION_CREDENTIALS": "/path/to/service-account.json"
    }
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

_SECRETS_FILE = Path(
    os.environ.get("FRETWISE_SECRETS_FILE", str(Path.home() / ".fretwise" / "secrets.json"))
)


def _load_secrets_file() -> dict[str, Any]:
    """Return the parsed secrets file, or an empty dict if absent/invalid."""
    if not _SECRETS_FILE.exists():
        return {}
    try:
        data = json.loads(_SECRETS_FILE.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def get_secret(key: str, default: str | None = None) -> str | None:
    """Return a secret by key, preferring the environment over the secrets file.

    Args:
        key: Secret name (e.g. ``"AWS_ACCESS_KEY_ID"``).
        default: Value returned when the key is set nowhere.
    """
    env = os.environ.get(key)
    if env:
        return env
    val = _load_secrets_file().get(key, default)
    return str(val) if val is not None else default


def load_s3_credentials() -> dict[str, str]:
    """Return non-empty S3 credentials suitable for ``boto3.client`` kwargs.

    Honours the standard ``AWS_*`` names. Missing keys are omitted so boto3 can
    fall back to its own credential chain (instance role, shared config, …).
    """
    out: dict[str, str] = {}
    access = get_secret("AWS_ACCESS_KEY_ID")
    secret = get_secret("AWS_SECRET_ACCESS_KEY")
    token = get_secret("AWS_SESSION_TOKEN")
    if access:
        out["aws_access_key_id"] = access
    if secret:
        out["aws_secret_access_key"] = secret
    if token:
        out["aws_session_token"] = token
    return out


def load_webdav_credentials() -> dict[str, str]:
    """Return ``{"username", "password"}`` for WebDAV (omitting empties)."""
    out: dict[str, str] = {}
    user = get_secret("WEBDAV_USERNAME")
    password = get_secret("WEBDAV_PASSWORD")
    if user:
        out["username"] = user
    if password:
        out["password"] = password
    return out


def load_gdrive_service_account() -> str | None:
    """Return the path to a Google service-account JSON, if configured.

    Uses ``GOOGLE_APPLICATION_CREDENTIALS`` (the Google-standard variable).
    """
    return get_secret("GOOGLE_APPLICATION_CREDENTIALS")


__all__ = [
    "get_secret",
    "load_gdrive_service_account",
    "load_s3_credentials",
    "load_webdav_credentials",
]
