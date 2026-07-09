"""Build transition-pair features (X/y .npy) for transition-cost training.

Thin wrapper around ``fretwise.dataset.pipeline.build_transition_features``.
Ported from GuitarDataSet; data roots come from FRETWISE_DATASET_ROOT /
FRETWISE_HANDOFF_DIR (see fretwise.dataset.config).
"""
import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:  # running from a checkout without an installed package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fretwise.dataset.pipeline.build_transition_features import main

if __name__ == "__main__":
    main()
