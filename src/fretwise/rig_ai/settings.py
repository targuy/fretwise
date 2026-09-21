"""Server-wide rig AI preferences, with credentials in a separate private file.

No value from the secrets file is returned by the public settings functions.
The normal web config and cloud credentials stores remain independent.
"""

from __future__ import annotations

import csv
import io
import json
import os
import re
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Any

from fretwise.rig_ai.errors import RigAIError

# Any is restricted to JSON boundaries: these documents contain heterogeneous values.
_DEFAULTS: dict[str, Any] = {
    "mode": "manual",
    "openai_model": "gpt-5.6-terra",
    "anthropic_model": "claude-sonnet-4-6",
    "web_search": True,
}
_PROVIDERS = ("openai", "anthropic")
_MODEL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}\Z")
_KEY = re.compile(r"[\x21-\x7e]{16,512}\Z")
_LOCK = threading.RLock()
_MAX_SETTINGS_BYTES = 64 * 1024


def _paths() -> tuple[Path, Path]:
    directory = Path(os.environ.get("FRETWISE_CONFIG_DIR", str(Path.home() / ".fretwise")))
    secrets = Path(
        os.environ.get("FRETWISE_RIG_AI_SECRETS_FILE", directory / "rig-ai-secrets.json")
    )
    return directory / "rig-ai.json", secrets


def _safe_path(path: Path) -> None:
    for component in (path, *path.parents):
        if component.is_symlink():
            raise RigAIError("storage_unsafe", "Stockage IA : lien symbolique refusé.", 503)
        try:
            attributes = getattr(component.stat(), "st_file_attributes", 0)
        except FileNotFoundError:
            continue
        if attributes & 0x400:  # Windows reparse points include junctions.
            raise RigAIError("storage_unsafe", "Stockage IA : lien symbolique refusé.", 503)


def _read(path: Path) -> dict[str, Any]:
    try:
        _safe_path(path)
        if not path.exists():
            return {}
        with path.open("rb") as stream:
            content = stream.read(_MAX_SETTINGS_BYTES + 1)
        if len(content) > _MAX_SETTINGS_BYTES:
            raise ValueError
        result = json.loads(content)
        if not isinstance(result, dict):
            raise ValueError
        return result
    except (OSError, ValueError, RecursionError):
        raise RigAIError("storage_unavailable", "Stockage IA illisible.", 503) from None


def _private_file(path: Path) -> None:
    """Restrict the temporary file before writing any credential bytes."""
    os.chmod(path, 0o600)
    if os.name != "nt":
        return
    # chmod on Windows only toggles the read-only flag; establish a real DACL.
    options: dict[str, Any] = {
        "stderr": subprocess.DEVNULL,
        "check": True,
        "timeout": 10,
        "creationflags": subprocess.CREATE_NO_WINDOW,
    }
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        stdout=subprocess.PIPE,
        text=True,
        **options,
    )
    rows = list(csv.reader(io.StringIO(identity.stdout)))
    sid = rows[0][-1] if rows else ""
    if not re.fullmatch(r"S-1-[0-9-]+", sid):
        raise OSError("Cannot establish owner permissions")
    subprocess.run(
        ["icacls", str(path), "/inheritance:r", "/grant:r", f"*{sid}:F", "*S-1-5-18:F"],
        stdout=subprocess.DEVNULL,
        **options,
    )


def _write(path: Path, data: dict[str, Any]) -> None:
    temporary: Path | None = None
    try:
        _safe_path(path)
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        _safe_path(path)
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        os.close(descriptor)
        _private_file(temporary)
        with temporary.open("w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _safe_path(path)
        os.replace(temporary, path)
    except (OSError, subprocess.SubprocessError):
        raise RigAIError("storage_unavailable", "Enregistrement IA impossible.", 503) from None
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass  # No secret data is ever copied into the exception or logs.


def _preferences() -> dict[str, Any]:
    stored = _read(_paths()[0])
    result = {**_DEFAULTS, **{key: value for key, value in stored.items() if key in _DEFAULTS}}
    if result["mode"] not in ("manual", *_PROVIDERS):
        raise RigAIError("settings_invalid", "Mode IA enregistré invalide.", 503)
    for provider in _PROVIDERS:
        value = result[f"{provider}_model"]
        if not isinstance(value, str) or not _MODEL.fullmatch(value):
            raise RigAIError("settings_invalid", "Modèle IA enregistré invalide.", 503)
    if not isinstance(result["web_search"], bool):
        raise RigAIError("settings_invalid", "Préférence de recherche invalide.", 503)
    return result


def _credential(provider: str, secrets: dict[str, Any]) -> tuple[str, str]:
    name = f"{provider.upper()}_API_KEY"
    if os.environ.get(name, "").strip():
        return os.environ[name].strip(), "environment"
    value = secrets.get(name, "")
    if isinstance(value, str) and value.strip():
        return value.strip(), "file"
    return "", "none"


def get_settings() -> dict[str, Any]:
    """Return public preferences and credential availability; never call a provider."""
    with _LOCK:
        preferences = _preferences()
        secrets = _read(_paths()[1])
        result: dict[str, Any] = {
            "mode": preferences["mode"],
            "webSearch": preferences["web_search"],
        }
        for provider in _PROVIDERS:
            key, source = _credential(provider, secrets)
            result[provider] = {
                "model": preferences[f"{provider}_model"],
                "configured": bool(key),
                "keySource": source,
                "editable": source != "environment",
            }
        return result


def save_settings(updates: dict[str, Any]) -> dict[str, Any]:
    """Validate updates and atomically save separate preference/credential files.

    Empty password inputs preserve the existing key. Explicit clear flags remove
    a stored key. Environment-owned keys reject replacements and deletion.
    """
    allowed = (
        set(_DEFAULTS)
        | {f"{provider}_api_key" for provider in _PROVIDERS}
        | {f"clear_{provider}_key" for provider in _PROVIDERS}
    )
    if not isinstance(updates, dict) or set(updates) - allowed:
        raise RigAIError("settings_invalid", "Paramètres IA inconnus.")
    with _LOCK:
        preferences = _preferences()
        secrets = _read(_paths()[1])
        dirty_secrets = False
        dirty_preferences = False
        for key in _DEFAULTS:
            if key not in updates:
                continue
            value = updates[key]
            if key == "mode" and value not in ("manual", *_PROVIDERS):
                raise RigAIError("settings_invalid", "Mode IA invalide.")
            if key == "web_search" and not isinstance(value, bool):
                raise RigAIError("settings_invalid", "Recherche web : booléen attendu.")
            if key.endswith("_model"):
                if not isinstance(value, str) or not _MODEL.fullmatch(value.strip()):
                    raise RigAIError("settings_invalid", "Identifiant de modèle invalide.")
                value = value.strip()
            preferences[key] = value
            dirty_preferences = True
        for provider in _PROVIDERS:
            value = updates.get(f"{provider}_api_key", "")
            clear = updates.get(f"clear_{provider}_key", False)
            if not isinstance(value, str) or not isinstance(clear, bool):
                raise RigAIError("settings_invalid", "Format de clé IA invalide.")
            value = value.strip()
            if clear and value:
                raise RigAIError("settings_invalid", "Suppression et remplacement incompatibles.")
            if not value and not clear:
                continue
            if _credential(provider, secrets)[1] == "environment":
                raise RigAIError("key_locked", "Clé gérée par l'environnement du serveur.", 409)
            if value and not _KEY.fullmatch(value):
                raise RigAIError("settings_invalid", "Format de clé IA invalide.")
            name = f"{provider.upper()}_API_KEY"
            if clear:
                secrets.pop(name, None)
            else:
                secrets[name] = value
            dirty_secrets = True
        preferences_path, secrets_path = _paths()
        if dirty_secrets:
            _write(secrets_path, secrets)
        if dirty_preferences:
            _write(preferences_path, preferences)
        return get_settings()


def generation_settings() -> tuple[str, str, str, bool]:
    """Return private provider configuration for internal generation only."""
    with _LOCK:
        preferences = _preferences()
        provider = preferences["mode"]
        if provider == "manual":
            raise RigAIError("manual_mode", "Mode manuel : collez la réponse de votre IA.", 409)
        key, _ = _credential(provider, _read(_paths()[1]))
        if not key:
            raise RigAIError("key_missing", "Configurez la clé du fournisseur sélectionné.", 409)
        if not _KEY.fullmatch(key):
            raise RigAIError("key_invalid", "Format de clé fournisseur invalide.", 409)
        return provider, preferences[f"{provider}_model"], key, preferences["web_search"]
