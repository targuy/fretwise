#!/usr/bin/env python3
"""Export assembled SongsGears rigs into FretWise's flat ``data/gears/`` dir.

Reads assembled rig JSON — either a ``rigs.jsonl`` (one rig per line, as written
by ``songs-gears run``) or a directory/glob of ``*-staged-rig.json`` files — and
writes one ``<artist-slug>__<title-slug>.json`` per song using the canonical key
shared with FretWise. Drop the output straight into FretWise's single gears dir;
each sheet then supersedes that song's legacy ``.md`` in FretWise.

Usage (module: fretwise.gears.production.tools.export_to_fretwise_gears):
    ... --in sample_run/rigs.jsonl --out <repo>/data/gears
    ... --in "sample_run/**/*-staged-rig.json"    (defaults to <repo>/data/gears)
"""

from __future__ import annotations

import argparse
import glob
import json
import sys
from pathlib import Path

from fretwise.gears.naming import gears_filename_for_rig
from fretwise.gears.production.paths import default_gears_dir


def _load_rigs(pattern: str) -> list[dict]:
    path = Path(pattern)
    rigs: list[dict] = []
    if path.is_file() and path.suffix == ".jsonl":
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                rigs.append(json.loads(line))
        return rigs
    files = [path] if path.is_file() else [Path(p) for p in glob.glob(pattern, recursive=True)]
    for file in files:
        rigs.append(json.loads(file.read_text(encoding="utf-8")))
    return rigs


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--in", dest="inp", required=True, help="rigs.jsonl, a file, or a glob.")
    parser.add_argument(
        "--out",
        default=str(default_gears_dir()),
        help="Target gears dir (default: <repo>/data/gears, env FRETWISE_GEARS_DIR).",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    rigs = _load_rigs(args.inp)
    if not rigs:
        print(f"No rigs found in {args.inp!r}", file=sys.stderr)
        return 1
    out = Path(args.out)
    if not args.dry_run:
        out.mkdir(parents=True, exist_ok=True)

    written = skipped = 0
    for rig in rigs:
        name = gears_filename_for_rig(rig)
        if name.startswith("__") or name == "__.json":
            skipped += 1
            continue
        if not args.dry_run:
            (out / name).write_text(json.dumps(rig, ensure_ascii=False, indent=2), encoding="utf-8")
        written += 1

    print(f"{'(dry-run) ' if args.dry_run else ''}wrote {written}, skipped {skipped} -> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
