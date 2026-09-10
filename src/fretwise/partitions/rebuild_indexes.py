"""Régénère liste_partitions.txt et songs_index.tsv depuis le contenu réel de partitions/.

Usage :
    python -m fretwise.partitions.rebuild_indexes [--root PATH]

Comportement :
    - Scanne <root>/partitions/ pour les .gp
    - Régénère liste_partitions.txt (Artist - Title, sans doublon, casefold-sorted)
    - Régénère songs_index.tsv avec les colonnes :
        file, artist, title, date_added, year, genre, guitar, rig, notion_id, fingered
    - Préserve year/genre/guitar/rig/notion_id de l'ancien TSV
    - Ajoute la colonne `fingered` (1 si le nom contient _fingered, vide sinon)

Sortie console :
    [done] regen <N_entries> entries from <N_files> files
    [done] tsv rebuilt: <N> rows, metadata preserved on <K>, new <X>
"""

from __future__ import annotations

import argparse
import csv
import sys
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.lib import (
    PRESERVED_COLUMNS,
    TSV_COLUMNS,
    is_partition_file,
    parse_filename,
    to_display_entry,
)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    part_dir = paths.gp_dir(root)
    list_file = paths.liste_partitions_path(root)
    tsv_file = paths.songs_index_path(root)

    if not part_dir.is_dir():
        print(f"ERREUR : {part_dir} introuvable", file=sys.stderr)
        return 1

    files = sorted(
        f.name for f in part_dir.iterdir()
        if f.is_file() and is_partition_file(f.name)
    )

    # ─── liste_partitions.txt ────────────────────────────────────────
    entries = sorted({to_display_entry(f) for f in files}, key=str.casefold)
    list_file.write_text(
        f"# Liste des partitions ({len(entries)} fichiers)\n"
        f"# Format : Artiste - Titre\n\n"
        + "\n".join(entries) + "\n",
        encoding="utf-8",
    )
    print(f"[done] regen {len(entries)} entries from {len(files)} files")

    # ─── songs_index.tsv ─────────────────────────────────────────────
    # Charge l'ancien TSV en mémoire pour préserver les métadonnées
    old: dict[str, dict[str, str]] = {}
    old_by_identity: dict[tuple[str, str], dict[str, str]] = {}
    if tsv_file.exists():
        # Lit en ignorant les éventuels nulls (bug iCloud)
        raw = tsv_file.read_bytes().replace(b"\x00", b"").decode("utf-8", errors="replace")
        for row in csv.DictReader(raw.splitlines(), delimiter="\t"):
            old[row["file"]] = row
            key = (row.get("artist", "").lower(), row.get("title", "").lower())
            old_by_identity[key] = row

    new_rows = []
    preserved = 0
    new_count = 0

    for f in files:
        p = parse_filename(f)
        row = {c: "" for c in TSV_COLUMNS}
        row["file"] = f
        row["artist"] = p.artist
        row["title"] = p.title
        row["date_added"] = p.date or ""
        row["fingered"] = "1" if p.fingered else ""

        src = None
        if f in old:
            src = old[f]
        else:
            key = (p.artist.lower(), p.title.lower())
            if key in old_by_identity:
                src = old_by_identity[key]

        if src:
            for c in PRESERVED_COLUMNS:
                row[c] = src.get(c, "") or ""
            preserved += 1
        else:
            new_count += 1
        new_rows.append(row)

    with tsv_file.open("w", encoding="utf-8", newline="") as out:
        w = csv.DictWriter(out, fieldnames=TSV_COLUMNS, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        w.writerows(new_rows)

    print(f"[done] tsv rebuilt: {len(new_rows)} rows, "
          f"metadata preserved on {preserved}, new {new_count}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
