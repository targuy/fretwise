import argparse
import json
from pathlib import Path

from fretwise.gears.production.fretwise_export import attach_fretwise_export
from fretwise.gears.production.paths import default_production_root


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Attach stable Fretwise export objects to SongsGear JSON files."
    )
    parser.add_argument(
        "--input-dir",
        default=str(default_production_root() / "Songs"),
        help="Verbose batch output dir (default: <repo>/exports/gears_production/Songs).",
    )
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--indent", type=int, default=2)
    args = parser.parse_args(argv)

    input_dir = Path(args.input_dir)
    paths = sorted(input_dir.glob(args.pattern))
    counts = {"seen": 0, "updated": 0, "failed": 0}
    failures = []

    for path in paths:
        counts["seen"] += 1
        try:
            original = json.loads(path.read_text(encoding="utf-8"))
            updated = attach_fretwise_export(original)
            if updated != original:
                counts["updated"] += 1
                if not args.dry_run:
                    path.write_text(
                        json.dumps(updated, ensure_ascii=False, indent=args.indent) + "\n",
                        encoding="utf-8",
                    )
        except Exception as exc:
            counts["failed"] += 1
            failures.append({"path": str(path), "error": str(exc)})

    print(json.dumps({"counts": counts, "failures": failures}, ensure_ascii=False, indent=2))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
