"""Evaluate the phrase-window fingering bundle on the golden set.

Thin wrapper around ``fretwise.dataset.pipeline.eval_phrase_window_v1``
(calibration + golden-set metrics). Pass ``--pinky-demotion`` to run
``fretwise.dataset.pipeline.eval_pinky_demotion`` instead (raw vs
pinky-demotion fallback comparison).
"""
import argparse
import sys
from pathlib import Path

try:
    import fretwise  # noqa: F401
except ImportError:  # running from a checkout without an installed package
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pinky-demotion", action="store_true",
        help="run the raw-vs-pinky-demotion golden set comparison instead",
    )
    args = parser.parse_args()
    if args.pinky_demotion:
        from fretwise.dataset.pipeline.eval_pinky_demotion import main as run
    else:
        from fretwise.dataset.pipeline.eval_phrase_window_v1 import main as run
    run()


if __name__ == "__main__":
    main()
