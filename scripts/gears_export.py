#!/usr/bin/env python3
"""Wrapper: export assembled rigs (rigs.jsonl / staged-rig files) into data/gears/."""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.gears.production.tools.export_to_fretwise_gears import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
