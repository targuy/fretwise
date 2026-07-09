"""Train the phrase-window fingering bundle (5 slot heads + anchor head).

Thin wrapper around ``fretwise.dataset.pipeline.train_phrase_window_v1``.
Ported from GuitarDataSet; data roots come from FRETWISE_DATASET_ROOT /
FRETWISE_HANDOFF_DIR (see fretwise.dataset.config).
"""
import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:  # running from a checkout without an installed package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.dataset.pipeline.train_phrase_window_v1 import main

if __name__ == "__main__":
    main()
