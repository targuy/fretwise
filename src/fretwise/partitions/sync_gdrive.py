"""Synchronise partitions/ (iCloud local) → Google Drive.

Stratégie :
  - Source de vérité : ``<root>/partitions/`` (local iCloud)
  - Cible : ``FRETWISE_GDRIVE_DIR`` (défaut G:\\Mon Drive\\partitions)
  - Action : copier vers G: les .gp manquants, en conservant le nom local (spaces)
  - Détection de doublon : normalisation des noms (avec et sans espaces autour du -)
  - Report : ne SUPPRIME RIEN sur G: ; signale juste les fichiers G:-only.

Usage :
    python -m fretwise.partitions.sync_gdrive [--src PATH] [--dst PATH] [--dry-run]
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output


def normalize_key(name: str) -> str:
    """Compresse pour comparaison : minuscules, sans espaces autour des '-' et autres bruits."""
    n = name.lower()
    n = re.sub(r"\s*-\s*", "-", n)            # "A - B - C" -> "a-b-c"
    n = re.sub(r"\s+", " ", n).strip()        # multispaces -> 1
    return n


def list_gp(d: Path) -> dict[str, str]:
    """{filename: normalized_key} pour les .gp d'un répertoire."""
    if not d.is_dir():
        return {}
    return {f.name: normalize_key(f.name) for f in d.iterdir()
            if f.is_file() and f.name.endswith(".gp")}


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--src", default=None,
                    help="Répertoire source des .gp (défaut <root>/partitions)")
    ap.add_argument("--dst", default=None, help="Répertoire Google Drive cible")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    src_dir = Path(args.src) if args.src else paths.gp_dir()
    dst_dir = Path(args.dst) if args.dst else paths.gdrive_dir()
    dry_run = args.dry_run

    print(f"[sync-gdrive] mode = {'DRY-RUN' if dry_run else 'LIVE'}")
    print(f"[sync-gdrive] SRC = {src_dir}")
    print(f"[sync-gdrive] DST = {dst_dir}\n")

    if not dst_dir.is_dir():
        print(f"[sync-gdrive] SKIP: Google Drive directory introuvable : {dst_dir}")
        print("[sync-gdrive] Google Drive n'est peut-etre pas monte. Pipeline continue sans sync.")
        return 0

    src = list_gp(src_dir)        # {filename: normalized_key}
    dst = list_gp(dst_dir)
    src_keys = set(src.values())
    dst_keys = set(dst.values())

    # Fichiers locaux absents de G:
    to_copy = [f for f, k in src.items() if k not in dst_keys]
    # Fichiers G: absents en local (informatif uniquement, jamais supprimés)
    gdrive_only = [f for f, k in dst.items() if k not in src_keys]
    # Fichiers présents des deux côtés (skip)
    already_in_both = len(src) - len(to_copy)

    print(f"Total source (partitions/)         : {len(src)}")
    print(f"Total destination (GDrive)         : {len(dst)}")
    print(f"  Déjà présents (sync)             : {already_in_both}")
    print(f"  A copier local -> GDrive          : {len(to_copy)}")
    print(f"  Présents UNIQUEMENT sur GDrive   : {len(gdrive_only)}\n")

    if gdrive_only:
        print("Présents UNIQUEMENT sur GDrive (non supprimés, à vérifier manuellement) :")
        for f in gdrive_only[:20]:
            print(f"  - {f}")
        if len(gdrive_only) > 20:
            print(f"  ... ({len(gdrive_only) - 20} autres)")
        print()

    copied = 0
    failed = []
    for f in to_copy:
        src_path = src_dir / f
        dst_path = dst_dir / f
        if dry_run:
            print(f"  [dry] copy -> {f}")
            continue
        try:
            shutil.copy2(src_path, dst_path)
            copied += 1
            if copied % 50 == 0:
                print(f"  ... {copied} copied")
        except OSError as e:
            failed.append((f, str(e)))
            print(f"  FAIL: {f} -> {e}")

    print()
    print(f"Copied : {copied}")
    print(f"Failed : {len(failed)}")
    if failed:
        for f, err in failed[:10]:
            print(f"  - {f}: {err}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
