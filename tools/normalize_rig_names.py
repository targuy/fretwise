#!/usr/bin/env python3
"""Normalize artist/title on every rig sheet against the canonical inventory.

Source of truth: ``E:/partitions/songs_index.tsv`` (the original Claude-cowork
inventory; already cleaner than the rig fields, e.g. AC/DC vs AC_DC). On top of
it we apply a small curated CORRECTIONS map for the structural breaks the index
also carries (swaps, concatenated band+title), then strip junk title suffixes.

Dry-run by default — prints the diff. ``--apply`` rewrites the Artiste/Chanson
lines in place (backing up each sheet once to ``.namebak``) and emits a clean
``data/songs_index_clean.tsv``.
"""
from __future__ import annotations

import argparse
import csv
import re
import sys
import unicodedata
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from fretwise.rig import find_rigs_dir, parse_rig  # noqa: E402

CLEAN_TSV = REPO / "data" / "songs_index_clean.tsv"


def _nfc(s: str) -> str:
    return unicodedata.normalize("NFC", s)

# Curated fixes for structural breaks (keyed by current lowercased artist||title).
# Each value is the corrected (artist, title).
CORRECTIONS: dict[tuple[str, str], tuple[str, str]] = {
    ("whats up", "4 non blondes"): ("4 Non Blondes", "What's Up"),
    ("the b", "52s-rock lobster (simple drum)"): ("The B-52's", "Rock Lobster"),
    ("the connels-'74", "'75"): ("The Connells", "'74-'75"),
    ("_chitlins con carne_", "kenny burrell"): ("Kenny Burrell", "Chitlins Con Carne"),
    ("fall out boy-sugar, we're going down", "band arrangement"):
        ("Fall Out Boy", "Sugar, We're Goin' Down"),
    ("earth wind and fire-september", "by guitarlogic"): ("Earth, Wind & Fire", "September"),
    ("yuyayu24-waves", "guthrie govan"): ("Guthrie Govan", "Waves"),
    ("monos-aznavour", "la bohème"): ("Charles Aznavour", "La Bohème"),
    ("dream theater-metropolis", "part i_ _the miracle and the sleeper_"):
        ("Dream Theater", "Metropolis, Pt. 1: The Miracle and the Sleeper"),
    ("bon jovi-wanted dead or alive", "rock band version"): ("Bon Jovi", "Wanted Dead or Alive"),
    ("taylor swift cover-anti-hero", "rock version"): ("Taylor Swift", "Anti-Hero"),
    ("misc covers-pressure and time by rival sons", "standard"): ("Rival Sons", "Pressure and Time"),
    ("weezer-undone", "the sweater song"): ("Weezer", "Undone (The Sweater Song)"),
    ("rory gallagher-tattoo'd lady (live)", "irish tour '74"): ("Rory Gallagher", "Tattoo'd Lady"),
    ("the cure _ ortopilot cover", "close to me"): ("The Cure", "Close to Me"),
}

# Junk suffixes stripped from titles (keep legitimate (Live)/(Acoustic) markers).
_JUNK = re.compile(r"\s*(\((tab|ai|band arrangement|simple drum|guitar ?logic|"
                   r"rock ?(band|version)|standard)\)|by guitarlogic)\s*$", re.IGNORECASE)


def clean_title(title: str) -> str:
    prev = None
    out = title.strip()
    while prev != out:
        prev = out
        out = _JUNK.sub("", out).strip()
    return out


# NFC-normalized correction lookup so accented keys match regardless of source form.
_CORR = {(_nfc(k0).casefold().strip(), _nfc(k1).casefold().strip()): v
         for (k0, k1), v in CORRECTIONS.items()}


def canonical(current: tuple[str, str]) -> tuple[str, str]:
    """Return the corrected (artist, title): curated structural fix, else just a
    junk-suffix strip on the title. The canonical inventory is deliberately NOT
    blanket-adopted — it is sometimes worse (``&``->``And``, lost apostrophes)."""
    key = (_nfc(current[0]).casefold().strip(), _nfc(current[1]).casefold().strip())
    if key in _CORR:
        a, t = _CORR[key]
    else:
        a, t = current[0], clean_title(current[1])
    return a.strip(), t.strip()


def rewrite(content: str, artist: str, title: str) -> str:
    content = re.sub(r"(?m)^(Artiste\s*:\s*).*$", lambda m: m.group(1) + artist, content, count=1)
    content = re.sub(r"(?m)^(Chanson\s*:\s*).*$", lambda m: m.group(1) + title, content, count=1)
    return content


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Normalize rig artist/title names.")
    p.add_argument("--apply", action="store_true", help="Write changes (default: dry-run).")
    p.add_argument("--show", type=int, default=25, help="How many diffs to print.")
    args = p.parse_args(argv)

    rigs_dir = find_rigs_dir(REPO / "partitions")
    changed: list[tuple[str, tuple[str, str], tuple[str, str]]] = []

    for rig in sorted(rigs_dir.glob("*.md")):
        content = rig.read_text(encoding="utf-8")
        d = parse_rig(content)
        cur = ((d.get("artist") or "").strip(), (d.get("song") or "").strip())
        new = canonical(cur)
        # Compare in NFC so invisible unicode-form-only differences never count.
        if (_nfc(new[0]), _nfc(new[1])) != (_nfc(cur[0]), _nfc(cur[1])) and new[0] and new[1]:
            changed.append((rig.name, cur, new))
            if args.apply:
                bak = rig.with_suffix(".md.namebak")
                if not bak.exists():
                    bak.write_text(content, encoding="utf-8")
                rig.write_text(rewrite(content, new[0], new[1]), encoding="utf-8")

    print(f"Fiches: {sum(1 for _ in rigs_dir.glob('*.md'))}")
    print(f"{'APPLIQUÉ' if args.apply else 'DRY-RUN'} — fiches à corriger: {len(changed)}")
    print(f"  dont corrections curées (cassures structurelles): "
          f"{sum(1 for _, c, _ in changed if (c[0].lower().strip(), c[1].lower().strip()) in CORRECTIONS)}")
    print("\nExemples (actuel -> normalisé):")
    for name, cur, new in changed[: args.show]:
        print(f"  [{cur[0]} | {cur[1]}]")
        print(f"    -> [{new[0]} | {new[1]}]   ({name})")

    if args.apply:
        with CLEAN_TSV.open("w", encoding="utf-8", newline="") as fh:
            w = csv.writer(fh, delimiter="\t")
            w.writerow(["rig_file", "artist", "title"])
            for rig in sorted(rigs_dir.glob("*.md")):
                d = parse_rig(rig.read_text(encoding="utf-8"))
                w.writerow([rig.name, d.get("artist") or "", d.get("song") or ""])
        print(f"\nIndex propre écrit -> {CLEAN_TSV}")
        print("Backups: <fiche>.md.namebak (créés une fois).")
    else:
        print("\n(dry-run — relance avec --apply pour écrire ; backups .namebak créés)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
