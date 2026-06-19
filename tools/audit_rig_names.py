#!/usr/bin/env python3
"""Read-only audit of artist/title quality across all rig sheets.

Classifies every rig ``.md`` by name-quality signal so we know the scope of the
cleanup before changing anything. Writes a review list of the structurally broken
ones (swaps, internal-hyphen band names) that cannot be auto-fixed safely.
"""
from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fretwise.rig import find_rigs_dir, parse_rig  # noqa: E402

OUT = REPO / "exports" / "name_audit"
_MISSING_APOS = {"whats", "dont", "cant", "im", "aint", "wont", "didnt", "isnt",
                 "youre", "thats", "hes", "shes", "couldnt", "wouldnt", "shouldnt",
                 "wasnt", "werent", "havent", "hasnt", "lets", "gonna"}


def signals(artist: str, title: str) -> list[str]:
    out: list[str] = []
    a, t = artist.strip(), title.strip()
    al = a.lower()
    if re.match(r"^\d", a):
        out.append("artist_starts_digit")          # likely swapped (songs lead with digits)
    if "-" in a:
        out.append("hyphen_in_artist")              # split band name (The B-52's, Connels-'74)
    if "_" in a:
        out.append("underscore_in_artist")          # AC_DC -> AC/DC
    if len(a) <= 4 or al in {"the b", "the"}:
        out.append("short_artist")
    words = set(re.findall(r"[a-z]+", f"{al} {t.lower()}"))
    if words & _MISSING_APOS:
        out.append("missing_apostrophe")
    if "(" in t or "[" in t:
        out.append("parenthetical_title")
    if a and a == al and a.isascii() and re.search(r"[a-z]", a):
        out.append("all_lowercase_artist")
    if re.search(r"_finger|\.gp\b|\.md\b", f"{a} {t}", re.IGNORECASE):
        out.append("filename_junk")
    return out


def main() -> int:
    rigs_dir = find_rigs_dir(REPO / "partitions")
    if not rigs_dir:
        print("no rigs dir", file=sys.stderr)
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    cat = Counter()
    flagged: list[dict] = []
    total = 0
    no_fields = 0
    for rig in sorted(rigs_dir.glob("*.md")):
        try:
            d = parse_rig(rig.read_text(encoding="utf-8"))
        except OSError:
            continue
        total += 1
        artist = (d.get("artist") or "").strip()
        title = (d.get("song") or "").strip()
        if not artist or not title:
            no_fields += 1
            cat["missing_artist_or_title"] += 1
            flagged.append({"file": rig.name, "artist": artist, "title": title,
                            "signals": ["missing_artist_or_title"]})
            continue
        sig = signals(artist, title)
        for s in sig:
            cat[s] += 1
        if sig:
            flagged.append({"file": rig.name, "artist": artist, "title": title, "signals": sig})

    clean = total - len({f["file"] for f in flagged})
    (OUT / "flagged.json").write_text(
        json.dumps(flagged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Total fiches: {total}")
    print(f"Propres (aucun signal): {clean} ({100*clean//total}%)")
    print(f"Avec au moins un signal: {total - clean} ({100*(total-clean)//total}%)")
    print("\nPar catégorie de signal:")
    for s, n in cat.most_common():
        print(f"  {s:<26} {n}")
    print("\nExemples par catégorie:")
    for s in [c for c, _ in cat.most_common()]:
        ex = [f for f in flagged if s in f["signals"]][:3]
        print(f"  {s}:")
        for f in ex:
            print(f"     {f['artist']!r}  /  {f['title']!r}   [{f['file']}]")
    print(f"\nListe complète des signalés -> {OUT / 'flagged.json'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
