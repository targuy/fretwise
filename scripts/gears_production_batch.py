#!/usr/bin/env python3
"""Wrapper: economic production batch (Ollama draft -> OpenAI judge -> Claude fallback).

Outputs default to ``<repo>/exports/gears_production/`` (Songs/, Logs/,
summary.json, checkpoint.json).
"""

from __future__ import annotations

import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.gears.production.tools.run_economic_production_batch import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
