"""Repo-relative default paths for the gears production tools.

The original SongsGears tools hard-coded producer-machine paths (for example
an absolute ``.../fretwise/data/gears`` and ``Output/Final/...``). Here every
default is derived from the fretwise repo root, with environment overrides so
batches can target another checkout without editing code.
"""

from __future__ import annotations

import os
from pathlib import Path


def repo_root() -> Path:
    """Return the fretwise repository root (four levels above this file)."""
    return Path(__file__).resolve().parents[4]


def default_gears_dir() -> Path:
    """Return the target gears sheet directory.

    ``FRETWISE_GEARS_DIR`` overrides; defaults to ``<repo>/data/gears``.
    """
    env = os.environ.get("FRETWISE_GEARS_DIR", "").strip()
    if env:
        return Path(env)
    return repo_root() / "data" / "gears"


def default_production_root() -> Path:
    """Return the root for batch outputs (Songs/, Logs/, checkpoint.json …).

    ``FRETWISE_GEARS_PRODUCTION_ROOT`` overrides; defaults to
    ``<repo>/exports/gears_production``.
    """
    env = os.environ.get("FRETWISE_GEARS_PRODUCTION_ROOT", "").strip()
    if env:
        return Path(env)
    return repo_root() / "exports" / "gears_production"


def default_config_path() -> Path:
    """Return the packaged example config (mock provider, dry-run Notion)."""
    return Path(__file__).resolve().parent / "data" / "config.example.json"
