#!/usr/bin/env python3
"""Wrapper: run the existing tools/supersede_with_gears.py without moving it.

Removes legacy curated-facts entries and generated .md rig sheets for every
song that now has a ``data/gears/<artist__title>.json`` sheet.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


def _load_main():
    path = _ROOT / "tools" / "supersede_with_gears.py"
    spec = importlib.util.spec_from_file_location("supersede_with_gears", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.main


if __name__ == "__main__":
    raise SystemExit(_load_main()(sys.argv[1:]))
