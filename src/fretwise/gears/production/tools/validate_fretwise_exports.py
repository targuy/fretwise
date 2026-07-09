import argparse
import json
from collections import Counter
from pathlib import Path

from fretwise.gears.production.fretwise_export import validate_fretwise_export
from fretwise.gears.production.paths import default_production_root


def main(argv=None):
    parser = argparse.ArgumentParser(description="Validate SongsGears Fretwise exports.")
    parser.add_argument(
        "--input-dir",
        default=str(default_production_root() / "Songs"),
        help="Verbose batch output dir (default: <repo>/exports/gears_production/Songs).",
    )
    parser.add_argument("--pattern", default="*.json")
    parser.add_argument("--source-from", type=int, default=None)
    parser.add_argument("--source-to", type=int, default=None)
    args = parser.parse_args(argv)

    paths = sorted(Path(args.input_dir).glob(args.pattern))
    checked = 0
    failures = []
    empty_genre = []
    genres = Counter()

    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        source_index = data.get("metadata", {}).get("sourceIndex")
        if args.source_from is not None and (
            not isinstance(source_index, int) or source_index < args.source_from
        ):
            continue
        if args.source_to is not None and (
            not isinstance(source_index, int) or source_index > args.source_to
        ):
            continue

        checked += 1
        genre = data.get("song", {}).get("genre") or ""
        genres[genre] += 1
        if not genre:
            empty_genre.append(path.name)

        validation = validate_fretwise_export(data.get("fretwiseExport") or {})
        if not validation.get("ok"):
            failures.append({"file": path.name, "validation": validation})

    result = {
        "checked": checked,
        "emptyGenreCount": len(empty_genre),
        "fretwiseValidationFailedCount": len(failures),
        "topGenres": genres.most_common(25),
        "emptyGenreExamples": empty_genre[:10],
        "failureExamples": failures[:10],
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 1 if failures or empty_genre or checked == 0 else 0


if __name__ == "__main__":
    raise SystemExit(main())
