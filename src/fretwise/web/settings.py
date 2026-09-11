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
#: Address of the HeadRush Core on the home LAN; editable in the settings.
DEFAULT_HEADRUSH_HOST = "192.168.1.34"

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
    "gears_dir": "",              # "" = <repo>/data/gears (per-model rig sheets)
    # --- Multi-effects unit driven by FretWise -------------------------------
    # Which pedalboard the rig UI targets. The two are not interchangeable: the
    # GP-180 is addressed by MIDI Program Change from the PC and its sheets are
    # `songsgear.fretwise.gear.v2`; the HeadRush Core has no MIDI input from the
    # PC at all (verified: no USB-MIDI endpoint) and is driven over HTTP with
    # `fretwise.device.binding.v1` documents. Showing both at once would offer
    # controls that cannot work for the selected hardware.
    "gear_device": "valeton_gp180",   # valeton_gp180 | headrush_core
    # IP literal rather than headrushcore.local: mDNS does not cross into a Docker
    # bridge network, so the NAS container can only reach the Core by address.
    "headrush_host": DEFAULT_HEADRUSH_HOST,
    # Lock 1 of the device applier, as an installation setting (the environment
    # variable FRETWISE_HEADRUSH_ALLOW_WRITE also opens it). Off by default: the
    # Core's API has no authentication, so writing to it is an explicit opt-in.
    "headrush_allow_write": False,
}

#: Devices the rig UI knows how to drive, and how each is reached.
GEAR_DEVICES: dict[str, dict[str, str]] = {
    "valeton_gp180": {
        "label": "Valeton GP-180",
        "transport": "midi",
        "sheet_schema": "songsgear.fretwise.gear.v2",
    },
    "headrush_core": {
        "label": "HeadRush Core",
        "transport": "http",
        "sheet_schema": "fretwise.device.binding.v1",
    },
}

_ENVIRONMENT_SETTINGS = {
    "partitions_dir": "FRETWISE_PARTITIONS_DIR",
    "soundfonts_dir": "FRETWISE_SOUNDFONTS_DIR",
    "gears_dir": "FRETWISE_GEARS_DIR",
    "gear_device": "FRETWISE_GEAR_DEVICE",
    "headrush_host": "FRETWISE_CORE_HOST",
}


def environment_overrides() -> dict[str, str]:
    """Return deployment-owned settings supplied through environment variables."""
    return {
        key: value
        for key, env_name in _ENVIRONMENT_SETTINGS.items()
        if (value := os.environ.get(env_name, "").strip())
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
    # Deployment paths win over a persisted desktop config. This prevents a
    # copied Windows config.json from redirecting a NAS container to stale paths.
    settings.update(environment_overrides())
    return settings


def save(updates: dict[str, Any]) -> dict[str, Any]:
    """Save settings to disk. Returns merged settings."""
    current = load()
    valid_keys = set(_DEFAULTS)
    locked_keys = set(environment_overrides())
    for k, v in updates.items():
        if k in valid_keys and k not in locked_keys:
            current[k] = v
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(current, indent=2, ensure_ascii=False), encoding="utf-8")
    return current


def get(key: str, default: Any = None) -> Any:
    """Get a single setting value."""
    return load().get(key, default)
