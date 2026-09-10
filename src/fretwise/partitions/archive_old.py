"""Archive les artefacts datés (prompts, extracts, logs, snapshots txt/tsv).

Ils sont rangés dans _archive_logs/YYYY-MM-DD/ pour ne garder à la racine que
les versions courantes.

Règles :
    - Garde à la racine le PLUS RÉCENT prompt-songsterr-*.md (si daté d'aujourd'hui)
    - Idem pour extract-*.txt
    - Idem pour daily_sync-*.log
    - Conserve TOUJOURS liste_partitions.txt et songs_index.tsv à la racine
    - Snapshot avant archive : copie liste_partitions.txt → _archive_logs/YYYY-MM-DD/
      sous le nom liste_partitions-YYYY-MM-DD.txt (idem TSV)
    - Tout fichier daté >= 7 jours est archivé sans condition

Usage :
    python -m fretwise.partitions.archive_old [--root PATH] [--keep-days 7]
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output

DATED_PATTERNS = [
    re.compile(r"^prompt-songsterr-(\d{4}-\d{2}-\d{2})[a-z]?\.md$"),
    re.compile(r"^extract-(\d{4}-\d{2}-\d{2})[a-z]?\.txt$"),
    re.compile(r"^daily_sync-(\d{4}-\d{2}-\d{2})\.log$"),
    re.compile(r"^liste_partitions-(\d{4}-\d{2}-\d{2})\.txt$"),
    re.compile(r"^songs_index-(\d{4}-\d{2}-\d{2})\.tsv$"),
]


def safe_move(src: Path, dst: Path) -> None:
    """Move robust on iCloud (rename via temp)."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        i = 1
        while True:
            candidate = dst.with_name(f"{dst.stem}_{i}{dst.suffix}")
            if not candidate.exists():
                dst = candidate
                break
            i += 1
    tmp = src.with_name(src.name + ".MOVING_TMP")
    os.rename(src, tmp)
    os.rename(tmp, dst)


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    ap.add_argument("--keep-days", type=int, default=7)
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    archive_root = paths.archive_logs_dir(root)
    archive_root.mkdir(exist_ok=True)
    today = date.today()
    keep_threshold = today - timedelta(days=args.keep_days)

    # 1) Snapshot des indexes courants
    snap_dir = archive_root / today.isoformat()
    snap_dir.mkdir(exist_ok=True)
    for src_name, dst_name in [
        (paths.LISTE_PARTITIONS_NAME, f"liste_partitions-{today.isoformat()}.txt"),
        (paths.SONGS_INDEX_NAME, f"songs_index-{today.isoformat()}.tsv"),
    ]:
        src = root / src_name
        dst = snap_dir / dst_name
        if src.exists() and not dst.exists():
            shutil.copy(src, dst)
            print(f"[snap] {src_name} -> _archive_logs/{today.isoformat()}/{dst_name}")

    # 2) Archive les fichiers datés trop anciens (et toute version d'un autre jour
    #    que today pour les prompts/extracts/logs)
    moved = 0
    for f in root.iterdir():
        if not f.is_file():
            continue
        for pattern in DATED_PATTERNS:
            m = pattern.match(f.name)
            if not m:
                continue
            file_date = m.group(1)
            try:
                d = date.fromisoformat(file_date)
            except ValueError:
                continue
            if d == today:
                # Garde le fichier du jour à la racine
                continue
            if d > keep_threshold:
                # Récent mais pas d'aujourd'hui — on archive quand même
                # pour garder la racine propre
                pass
            dest = archive_root / file_date / f.name
            safe_move(f, dest)
            moved += 1
            print(f"[move] {f.name} -> _archive_logs/{file_date}/")
            break

    print(f"[done] archive : {moved} fichier(s) déplacé(s), snapshot du jour OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
