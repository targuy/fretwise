#!/usr/bin/env python3
"""Wrapper: print or save the exact LLM prompt for one rig request.

Runs the ``prompt`` subcommand; pass ``--stage`` arguments through
``gears_assemble_stages.py``'s sibling ``prompt-stage`` via
``python -m fretwise.gears.production.cli prompt-stage ...`` if needed.
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.gears.production.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["prompt", *sys.argv[1:]]))
