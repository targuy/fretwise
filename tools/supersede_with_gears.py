#!/usr/bin/env python3
"""Remove legacy rig data that a new-format gears sheet has superseded.

For every ``data/gears/<artist__title>.json`` sheet, delete the matching legacy
data so the JSON is the single source of truth for that song:

  * its entry in ``data/curated_facts*.json`` (matched by canonical gears key), and
  * its generated ``partitions/rigs/<file>.md`` sheet (so ``gen_fiche.py`` won't
    recreate it).

Idempotent: songs with no gears sheet are untouched; already-cleaned songs are
no-ops. Run after dropping new sheets into ``data/gears/``.

Usage:
    pixi run python tools/supersede_with_gears.py
    pixi run python tools/supersede_with_gears.py --dry-run
    pixi run python tools/supersede_with_gears.py --gears-dir <path>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fretwise.gears.naming import gears_key  # noqa: E402

DEFAULT_GEARS = ROOT / "data" / "gears"
RIGS = ROOT / "partitions" / "rigs"
CURATED_GLOB = "curated_facts*.json"


def _canonical_key(stem: str) -> str:
    """Canonicalize a gears filename stem to the shared ``artist__title`` key.

    Mirrors the web resolver: tolerates kebab (``ac-dc__highway-to-hell``) and
    the SongsGear export's underscored Title Case (``AC_DC__Highway_To_Hell``).
    """
    if "__" in stem:
        artist, title = stem.split("__", 1)
        return gears_key(artist, title)
    return gears_key("", stem)


def _gears_keys(gears_dir: Path) -> set[str]:
    return {_canonical_key(p.stem) for p in gears_dir.glob("*.json")}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gears-dir", default=str(DEFAULT_GEARS))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)

    gears_dir = Path(args.gears_dir)
    keys = _gears_keys(gears_dir)
    if not keys:
        print(f"No gears sheets in {gears_dir} — nothing to supersede.")
        return 0

    removed_entries = 0
    removed_md = 0
    touched_files = 0
    superseded: set[str] = set()

    for facts_path in sorted((ROOT / "data").glob(CURATED_GLOB)):
        try:
            raw = json.loads(facts_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        # curated_facts files wrap the list as {"songs": [...]}; tolerate a bare list.
        wrapped = isinstance(raw, dict) and isinstance(raw.get("songs"), list)
        entries = raw["songs"] if wrapped else raw
        if not isinstance(entries, list):
            continue
        kept: list[dict] = []
        changed = False
        for entry in entries:
            if not isinstance(entry, dict):
                kept.append(entry)
                continue
            artist = str(entry.get("artist") or "")
            title = str(entry.get("title") or "")
            key = gears_key(artist, title)
            if key in keys:
                superseded.add(key)
                removed_entries += 1
                changed = True
                md_name = str(entry.get("file") or "").strip()
                md_path = RIGS / md_name if md_name else None
                if md_path and md_path.is_file():
                    if not args.dry_run:
                        md_path.unlink()
                    removed_md += 1
                continue
            kept.append(entry)
        if changed:
            touched_files += 1
            if not args.dry_run:
                if wrapped:
                    raw["songs"] = kept
                    out = raw
                else:
                    out = kept
                facts_path.write_text(
                    json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8"
                )

    unmatched = sorted(keys - superseded)
    print(
        f"{'(dry-run) ' if args.dry_run else ''}superseded {removed_entries} curated entries "
        f"in {touched_files} file(s); removed {removed_md} .md sheet(s)."
    )
    if unmatched:
        print(f"{len(unmatched)} gears sheet(s) had no legacy entry (new songs): "
              + ", ".join(unmatched[:10]) + (" …" if len(unmatched) > 10 else ""))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
