#!/usr/bin/env python3
"""Wrapper CLI pour fretwise.partitions.sync_songs (voir ce module pour l'aide)."""

import sys
from pathlib import Path

try:
    from fretwise.partitions.sync_songs import main
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
    from fretwise.partitions.sync_songs import main

if __name__ == "__main__":
    raise SystemExit(main())
