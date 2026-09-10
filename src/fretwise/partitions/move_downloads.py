"""Watcher local : déplace les .gp depuis Downloads vers partitions/ avec dédup.

Usage :
    python -m fretwise.partitions.move_downloads [--downloads PATH] [--target PATH] [--dry-run]

Comportement :
    1. Scanne DOWNLOADS pour les fichiers .gp/.gpx/.gp5/.gp4/.gp3
    2. Pour chaque fichier :
        - Si identité (artist|title) existe déjà dans TARGET : garde la plus grosse
          version (ou la plus récente si tailles égales), archive l'autre dans
          _doublons_archive/
        - Sinon : déplace vers TARGET
    3. Dédoublonne aussi dans TARGET (au cas où des doublons traîneraient)

Conçu pour tourner toutes les 2 heures via Windows Task Scheduler.
Exit codes : 0 = OK, 1 = erreur, 2 = aucun fichier à traiter (dry-run).
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections import defaultdict
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.lib import is_partition_file, normalize_identity, parse_filename


def log(msg: str) -> None:
    """Trace horodatée sur stdout."""
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def safe_rename(src: Path, dst: Path) -> Path:
    """
    Rename robuste sur iCloud : passe par un nom temporaire pour eviter
    les bugs FUSE quand src/dst different juste par le dossier.
    Utilise shutil.move pour le deplacement final, qui gere les
    cross-device links (cas Downloads -> partitions sur mounts differents).
    """
    if dst.exists():
        # Genere un suffixe _dupN
        i = 1
        while True:
            candidate = dst.with_name(f"{dst.stem}_dup{i}{dst.suffix}")
            if not candidate.exists():
                dst = candidate
                break
            i += 1
    tmp = src.with_name(src.name + ".MOVING_TMP")
    os.rename(src, tmp)
    shutil.move(str(tmp), str(dst))
    return dst


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--downloads", default=None, help="Répertoire de téléchargements")
    ap.add_argument("--target", default=None, help="Répertoire cible des .gp")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    downloads = Path(args.downloads) if args.downloads else paths.downloads_dir()
    target = Path(args.target) if args.target else paths.gp_dir()
    archive = target.parent / paths.DOUBLONS_ARCHIVE_SUBDIR

    if not target.exists():
        log(f"ERREUR : target {target} introuvable")
        return 1
    archive.mkdir(parents=True, exist_ok=True)

    # 1) Index l'existant dans TARGET par identite
    existing: dict[str, list[tuple[Path, int, float]]] = defaultdict(list)
    for f in target.iterdir():
        if f.is_file() and is_partition_file(f.name):
            p = parse_filename(f.name)
            ident = normalize_identity(p.artist, p.title)
            st = f.stat()
            existing[ident].append((f, st.st_size, st.st_mtime))

    log(f"target {target} : {sum(len(v) for v in existing.values())} fichiers, "
        f"{len(existing)} identites uniques")

    # 2) Traite les telechargements
    if not downloads.exists():
        log(f"AVERTISSEMENT : downloads {downloads} introuvable, skip")
        return 0
    incoming = [f for f in downloads.iterdir()
                if f.is_file() and is_partition_file(f.name)]
    log(f"downloads {downloads} : {len(incoming)} fichiers .gp a traiter")

    moved = 0
    skipped = 0
    archived_existing = 0

    for src in incoming:
        p = parse_filename(src.name)
        ident = normalize_identity(p.artist, p.title)
        st = src.stat()
        log(f"  {src.name}  [{p.artist} | {p.title} | {p.date} | fingered={p.fingered}]")

        if ident in existing:
            # Comparer avec le meilleur existant
            best_existing = max(existing[ident], key=lambda x: (x[1], x[2]))
            best_file, best_size, _ = best_existing
            if st.st_size > best_size:
                # Le nouveau est meilleur -> archive l'existant, deplace le nouveau
                if args.dry_run:
                    log(f"    [DRY] archiverait {best_file.name}, deplacerait {src.name}")
                else:
                    safe_rename(best_file, archive / best_file.name)
                    safe_rename(src, target / src.name)
                    archived_existing += 1
                    moved += 1
            else:
                # L'existant est meilleur ou egal -> archive le telechargement
                if args.dry_run:
                    log(f"    [DRY] archiverait telechargement {src.name} (existant gagne)")
                else:
                    safe_rename(src, archive / src.name)
                    skipped += 1
        else:
            # Nouveau morceau -> deplace simplement
            if args.dry_run:
                log(f"    [DRY] deplacerait {src.name} -> {target.name}/")
            else:
                final_path = safe_rename(src, target / src.name)
                existing[ident].append((final_path, st.st_size, st.st_mtime))
                moved += 1

    log(f"[done] moved={moved} skipped={skipped} archived_existing={archived_existing}")
    return 0 if (moved or skipped) else 2


if __name__ == "__main__":
    sys.exit(main())
