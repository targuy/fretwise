"""Orchestrateur principal — tourne 1x/jour à 2:00 AM (Task Scheduler / Claude scheduled task).

Étapes (séquentielles, idempotentes) :
    1. move_downloads     : ramène les .gp de Downloads vers partitions/
    2. rebuild_indexes    : régénère liste_partitions.txt + songs_index.tsv (avec fingered)
    3. enrich_from_notion : prépare _notion_queue/ pour l'agent IA
    4. propose_songs      : génère prompt-songsterr-<today>.md + extract-<today>.txt
       (nécessite candidates_seed.txt rempli par l'agent via web_search)
    5. archive_old        : snapshot + déplace les artefacts datés vers _archive_logs/

Contrairement au script iCloud d'origine (qui lançait chaque étape en
sous-processus par chemin de fichier), cette version appelle directement les
``main()`` des modules portés — même séquence, mêmes arguments, mêmes codes
retour (0 = ok, 2 = warn/état attendu, autre = fail).

Le script écrit son log dans _archive_logs/<today>/daily_sync-<today>.log
puis pose une copie en racine pour facilité.

Codes retour :
    0  : tout OK
    1  : au moins une étape a échoué (log dans le fichier)

Conçu pour être réentrant : peut être appelé plusieurs fois par jour sans dégât.
"""

from __future__ import annotations

import argparse
import contextlib
import shutil
import sys
import traceback
from collections.abc import Callable, Sequence
from datetime import date, datetime
from pathlib import Path
from typing import TextIO

from fretwise.partitions import (
    archive_old,
    enrich_from_notion,
    move_downloads,
    paths,
    propose_songs,
    rebuild_indexes,
)
from fretwise.partitions.console import ensure_printable_output

#: (nom, main(), l'étape reçoit --target/--downloads plutôt que --root)
STEPS: list[tuple[str, Callable[[Sequence[str] | None], int], bool]] = [
    ("move_downloads", move_downloads.main, True),
    ("rebuild_indexes", rebuild_indexes.main, False),
    ("enrich_from_notion", enrich_from_notion.main, False),
    ("propose_songs", propose_songs.main, False),
    ("archive_old", archive_old.main, False),
]


def run_step(
    name: str,
    func: Callable[[Sequence[str] | None], int],
    step_argv: list[str],
    log_fh: TextIO,
) -> tuple[str, int]:
    """Exécute une étape en redirigeant stdout/stderr vers le log."""
    log_fh.write(f"\n=== {name} @ {datetime.now().isoformat(timespec='seconds')} ===\n")
    log_fh.write(f"args: {' '.join(step_argv)}\n")
    log_fh.flush()
    try:
        with contextlib.redirect_stdout(log_fh), contextlib.redirect_stderr(log_fh):
            code = func(step_argv)
            code = 0 if code is None else int(code)
    except SystemExit as exc:  # au cas où un main() ferait sys.exit
        code = exc.code if isinstance(exc.code, int) else 1
    except Exception:
        log_fh.write("!! EXCEPTION:\n")
        log_fh.write(traceback.format_exc())
        code = 1
    log_fh.write(f"exit code: {code}\n")
    log_fh.flush()
    status = "ok" if code == 0 else ("warn" if code == 2 else "fail")
    return status, code


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    ap.add_argument("--downloads", default=None,
                    help="Chemin Downloads a transmettre a move_downloads (sinon defaut)")
    ap.add_argument("--skip", action="append", default=[],
                    help="nom d'etape a skipper, ex --skip move_downloads")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    today = date.today().isoformat()
    log_dir = paths.archive_logs_dir(root) / today
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / f"daily_sync-{today}.log"

    target_path = paths.gp_dir(root)

    summary = []
    with log_path.open("a", encoding="utf-8") as log_fh:
        log_fh.write(f"\n{'='*60}\n"
                     f"daily_sync RUN @ {datetime.now().isoformat()}\n"
                     f"{'='*60}\n")
        any_fail = False
        for name, func, has_target in STEPS:
            if name in args.skip:
                summary.append((name, "skip"))
                log_fh.write(f"\n=== {name} SKIPPED ===\n")
                continue
            step_argv = []
            if has_target:
                step_argv += ["--target", str(target_path)]
                if args.downloads:
                    step_argv += ["--downloads", args.downloads]
            else:
                step_argv += ["--root", str(root)]
            status, _code = run_step(name, func, step_argv, log_fh)
            summary.append((name, status))
            if status == "fail":
                any_fail = True

    # Copie en racine pour acces rapide au dernier log
    racine_log = root / f"daily_sync-{today}.log"
    if log_path.exists() and not racine_log.exists():
        try:
            shutil.copy(log_path, racine_log)
        except OSError:
            pass

    # Resume console
    print(f"daily_sync {today} :")
    for name, status in summary:
        print(f"  {status:5} {name}")
    print(f"log : {log_path}")
    return 1 if any_fail else 0


if __name__ == "__main__":
    sys.exit(main())
