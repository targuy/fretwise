#!/usr/bin/env python3
"""Wrapper: build a HeadRush Core write plan offline, from a binding document."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.devices.headrush_core.cli import plan_main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(plan_main(sys.argv[1:]))
