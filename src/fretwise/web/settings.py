"""Persistent user settings for FretWise, stored in ~/.fretwise/config.json."""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from fretwise.config import config as _fw_config

_CONFIG_DIR = Path(os.environ.get("FRETWISE_CONFIG_DIR", str(Path.home() / ".fretwise")))
_CONFIG_FILE = _CONFIG_DIR / "config.json"

_SETTINGS_DEFAULTS = _fw_config().web.settings_defaults

DEFAULT_PARTITIONS_DIR = str(Path(__file__).resolve().parents[3] / "partitions")
DEFAULT_INDEX_PATH = ""
DEFAULT_SOUNDFONTS_DIR = str(_SETTINGS_DEFAULTS.soundfonts_dir)

_DEFAULTS: dict[str, Any] = {
    "partitions_dir": DEFAULT_PARTITIONS_DIR,
    "index_path": DEFAULT_INDEX_PATH,
    "soundfonts_dir": DEFAULT_SOUNDFONTS_DIR,
    "active_soundfont": "",
    "soundfont_assignments": {},  # filename -> sf2 name
    # --- Partitions storage backend (see fretwise.storage) ---
    # Credentials are NEVER stored here; they come from the environment /
    # secrets file (see fretwise.storage.credentials).
    "storage_backend": str(_SETTINGS_DEFAULTS.storage_backend),   # local | s3 | webdav | gdrive
    "storage_cache_dir": "",      # optional cache dir override for cloud backends
    "storage_s3": {},             # {bucket, prefix, endpoint_url, region}
    "storage_webdav": {},         # {base_url}
    "storage_gdrive": {},         # {folder_id}
}


def load() -> dict[str, Any]:
    """Load settings from disk, merging with defaults."""
    settings = dict(_DEFAULTS)
    if _CONFIG_FILE.exists():
        try:
            data = json.loads(_CONFIG_FILE.read_text(encoding="utf-8"))
            settings.update({k: v for k, v in data.items() if k in _DEFAULTS})
        except (json.JSONDecodeError, OSError):
            pass
    return settings


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Save settings to disk. Returns merged settings."""
    current = load()
    valid_keys = set(_DEFAULTS)
    for k, v in updates.items():
        if k in valid_keys:
            current[k] = v
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def get(key: str, default: Any = None) -> Any:
    """Get a single setting value."""
    return load().get(key, default)
