"""Build the transition-cost spec JSON(s) for FretWise integration.

Thin wrapper around ``fretwise.dataset.pipeline.build_spec_json`` (feature
ranges/dependencies spec) and
``fretwise.dataset.pipeline.build_transition_spec_json`` (descriptions +
model test case). NOTE: historically both scripts write the SAME output file
(``transition_cost_v2_spec.json`` in the handoff dir) — the last one run
wins. Default here is ``testcase`` (the richer spec).
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
        "--spec", choices=["ranges", "testcase"], default="testcase",
        help="ranges = build_spec_json; testcase = build_transition_spec_json",
    )
    args = parser.parse_args()
    if args.spec == "ranges":
        from fretwise.dataset.pipeline.build_spec_json import main as run
    else:
        from fretwise.dataset.pipeline.build_transition_spec_json import main as run
    run()


if __name__ == "__main__":
    main()
