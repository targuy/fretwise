#!/usr/bin/env python3
"""Wrapper CLI pour fretwise.partitions.daily_sync (voir ce module pour l'aide)."""

import sys
from pathlib import Path

try:
    from fretwise.partitions.daily_sync import main
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from fretwise.partitions.daily_sync import main

if __name__ == "__main__":
    raise SystemExit(main())
