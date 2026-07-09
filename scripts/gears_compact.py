#!/usr/bin/env python3
"""Wrapper: compact verbose v1 gears sheets into songsgear.fretwise.gear.v2.

Reads ``<repo>/data/gears`` by default (env ``FRETWISE_GEARS_DIR`` or
``--input-dir`` to override) and writes ``<input>_compact_v2`` next to it.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.gears.production.tools.compact_fretwise_gears import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
