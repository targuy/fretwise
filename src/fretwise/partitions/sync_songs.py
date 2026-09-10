"""Index local des partitions .gp + génération de plans d'écriture Notion minimaux.

Index : songs_index.tsv (greppable, colonnes : file, artist, title, date_added,
year, genre, guitar, rig, notion_id).

Commandes :
    rebuild           (re)construit l'index depuis les .gp locaux
                      (préserve year/genre/guitar/rig/notion_id existants).
    diff              affiche les écarts local vs export Notion JSON.
    fetch-missing     liste URLs Songsterr pour les .gp absents en local.
    propose-writes    génère le plan minimal de writes Notion (Partitions DB + Todo DB) — JSON.
    sync              rebuild + instructions pour l'agent.

PÉRIMÈTRE NOTION CÔTÉ LOCAL — ne pas dépasser :
    - Partitions DB : ajout/retrait d'une ligne (artiste, titre, fichier, date)
    - Todo DB       : création d'entrée qui RÉFÉRENCE un prompt Notion existant par URL
                      (jamais le contenu du prompt — l'agent Notion l'exécute en autonomie)

Le local NE rédige JAMAIS de fiche Song, NE met JAMAIS à jour Songs Library.
Toute mise à jour de fiche = todo Notion référençant le prompt approprié (économie tokens).
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
import urllib.parse
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.notion_ids import PROMPT_URLS, TODO_DATABASE_URL

HEADER = ["file", "artist", "title", "date_added", "year", "genre", "guitar", "rig", "notion_id"]
COMPOUND_ARTISTS = ["Blink-182", "Eagle-Eye Cherry", "Jean-Jacques Goldman", "T-Rex"]


def parse_filename(name: str) -> tuple[str, str, str]:
    """Extrait (artist, title, date) depuis un stem de fichier .gp (variante historique)."""
    m = re.search(r"\s*-\s*(\d{2}-\d{2}-\d{4})$", name)
    date = m.group(1) if m else ""
    body = (name[:m.start()] if m else name).strip()
    for ca in COMPOUND_ARTISTS:
        if body.startswith(ca + "-") or body.startswith(ca + " - "):
            rest = body[len(ca):].lstrip(" -")
            return ca, rest.strip(), date
    sep = " - " if " - " in body else "-"
    artist, _, title = body.partition(sep)
    return artist.strip(), title.strip(), date


def load_index(index_path: Path) -> dict[str, dict[str, str]]:
    """Charge songs_index.tsv en dict {file: row}."""
    if not index_path.exists():
        return {}
    with open(index_path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    return {r["file"]: r for r in rows}


def write_index(index_path: Path, rows: list[dict[str, str]]) -> None:
    """Écrit songs_index.tsv trié artiste/titre."""
    with open(index_path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, delimiter="\t", extrasaction="ignore")
        w.writeheader()
        for r in sorted(rows, key=lambda x: (x["artist"].casefold(), x["title"].casefold())):
            w.writerow(r)


def scan_local(gp_dir: Path) -> dict[str, dict[str, str]]:
    """Scanne les .gp locaux -> {file: base_row}."""
    out = {}
    if not gp_dir.is_dir():
        return out
    for p in gp_dir.iterdir():
        f = p.name
        if f.endswith(".gp") and p.is_file():
            artist, title, date = parse_filename(f[:-3])
            out[f] = {"file": f, "artist": artist, "title": title, "date_added": date}
    return out


def rebuild(root: Path) -> tuple[list[dict[str, str]], list[str]]:
    """Reconstruit l'index : fusionne scan local avec métadonnées existantes."""
    index_path = paths.songs_index_path(root)
    existing = load_index(index_path)
    local = scan_local(paths.gp_dir(root))
    merged = []
    for f, base in local.items():
        prev = existing.get(f, {})
        row = {k: "" for k in HEADER}
        row.update(base)
        for k in ("year", "genre", "guitar", "rig", "notion_id"):
            row[k] = prev.get(k, "")
        merged.append(row)
    removed = [f for f in existing if f not in local]
    write_index(index_path, merged)
    print(f"[rebuild] {len(merged)} fichiers indexés ; {len(removed)} supprimés.")
    if removed:
        print("  Removed:", *removed[:10], "..." if len(removed) > 10 else "")
    return merged, removed


def diff_local_notion(root: Path, notion_rows: list[dict]) -> tuple[list[dict], list[dict]]:
    """notion_rows : list of dicts with at minimum {file, artist, title, notion_id}.
       Retourne (local_only, notion_only)."""
    local = scan_local(paths.gp_dir(root))
    local_keys = {(r["artist"].casefold(), r["title"].casefold()) for r in local.values()}
    notion_keys = {(r.get("artist", "").casefold(), r.get("title", "").casefold()): r
                   for r in notion_rows}
    local_only = [r for r in local.values()
                  if (r["artist"].casefold(), r["title"].casefold()) not in notion_keys]
    notion_only = [r for (k, r) in notion_keys.items() if k not in local_keys]
    return local_only, notion_only


def songsterr_search(artist: str, title: str) -> str:
    """URL de recherche Songsterr (pas d'API publique de download .gp)."""
    q = urllib.parse.quote(f"{artist} {title}")
    return f"https://www.songsterr.com/?pattern={q}"


def fetch_missing(notion_only: list[dict]) -> list[dict]:
    """Pour chaque entrée Notion sans .gp local, génère l'URL Songsterr à télécharger.
       L'agent doit utiliser browser automation pour le téléchargement effectif."""
    todos = []
    for r in notion_only:
        url = songsterr_search(r.get("artist", ""), r.get("title", ""))
        todos.append({"artist": r.get("artist"), "title": r.get("title"),
                      "songsterr_search": url, "notion_id": r.get("notion_id")})
    print(json.dumps(todos, indent=2, ensure_ascii=False))
    return todos


def make_todo_payload(action, artist, title, prompt_key,
                      partition_file=None, notion_song_id=None) -> dict:
    """Crée le payload minimal pour une entrée Todo Notion.
       Référence le prompt par URL — N'inclut PAS son contenu (économie tokens)."""
    return {
        "name": f"[{action}] {artist} - {title}",
        "action": action,
        "artist": artist,
        "title": title,
        "partition_file": partition_file,
        "song_notion_id": notion_song_id,
        "prompt_ref": PROMPT_URLS.get(prompt_key, prompt_key),
        "todo_db": TODO_DATABASE_URL,
    }


def make_partitions_row(artist, title, file, date_added, notion_song_id=None) -> dict:
    """Payload minimal pour création de ligne dans la base Partitions Notion."""
    return {
        "artist": artist,
        "title": title,
        "file": file,
        "date_added": date_added,
        "song_link": notion_song_id,
    }


def cmd_propose_writes(root: Path, notion_export: str | None = None) -> dict | None:
    """Génère le plan de writes Notion (Partitions DB + Todo DB) à partir du diff.
       N'EXÉCUTE PAS — sort un JSON consommé par l'agent qui appellera notion-create-pages."""
    if not notion_export or not Path(notion_export).exists():
        print("Usage: sync_songs propose-writes <notion_songs.json>")
        return None
    with open(notion_export, encoding="utf-8") as f:
        notion_rows = json.load(f)
    local_only, notion_only = diff_local_notion(root, notion_rows)

    plan: dict = {"partitions_to_add": [], "partitions_to_remove": [], "todos_to_create": []}

    # .gp local sans entrée Notion → ajouter à Partitions DB + Todo "créer fiche Song"
    for r in local_only:
        plan["partitions_to_add"].append(
            make_partitions_row(r["artist"], r["title"], r["file"], r.get("date_added", "")))
        plan["todos_to_create"].append(
            make_todo_payload("create_song_fiche", r["artist"], r["title"],
                              "create_from_gp", partition_file=r["file"]))

    # Entrée Notion sans .gp local → après download Songsterr, ajouter Partitions + Todo "link"
    for r in notion_only:
        plan["todos_to_create"].append(
            make_todo_payload("download_and_link", r.get("artist", ""), r.get("title", ""),
                              "update_links", notion_song_id=r.get("notion_id")))

    print(json.dumps(plan, indent=2, ensure_ascii=False))
    return plan


def cmd_diff(root: Path, notion_export: str | None = None) -> None:
    """Lit un export Notion JSON (passé en arg) et affiche le diff."""
    if not notion_export:
        print("Usage: sync_songs diff <chemin/vers/notion_songs.json>")
        return
    with open(notion_export, encoding="utf-8") as f:
        notion_rows = json.load(f)
    local_only, notion_only = diff_local_notion(root, notion_rows)
    print(f"Local sans Notion ({len(local_only)}):")
    for r in local_only[:20]:
        print(" ", r["artist"], "-", r["title"])
    print(f"Notion sans local ({len(notion_only)}):")
    for r in notion_only[:20]:
        print(" ", r.get("artist"), "-", r.get("title"))


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("command", nargs="?",
                    choices=["rebuild", "diff", "fetch-missing", "propose-writes",
                             "sync", "pull", "push"],
                    help="Commande à exécuter")
    ap.add_argument("notion_export", nargs="?", default=None,
                    help="Export Notion JSON (pour diff / fetch-missing / propose-writes)")
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()

    if not args.command:
        print(__doc__)
        return 0
    cmd = args.command
    if cmd == "rebuild":
        rebuild(root)
    elif cmd == "diff":
        cmd_diff(root, args.notion_export)
    elif cmd == "fetch-missing":
        if not args.notion_export:
            print("Usage: sync_songs fetch-missing <chemin/vers/notion_songs.json>")
            return 1
        with open(args.notion_export, encoding="utf-8") as f:
            notion_rows = json.load(f)
        _, notion_only = diff_local_notion(root, notion_rows)
        fetch_missing(notion_only)
    elif cmd == "propose-writes":
        cmd_propose_writes(root, args.notion_export)
    elif cmd == "sync":
        rebuild(root)
        print("[sync] rebuild OK. Étapes suivantes (à exécuter par l'agent) :")
        print("  1. Export Notion Songs : notion-search → notion_songs.json")
        print("  2. python -m fretwise.partitions.sync_songs propose-writes "
              "notion_songs.json → plan JSON")
        print("  3. Download Songsterr pour notion_only (browser MCP)")
        print("  4. python -m fretwise.partitions.sync_songs rebuild "
              "(intègre les .gp téléchargés)")
        print("  5. Agent applique le plan : seulement Partitions DB + Todo DB "
              "(pas Songs Library)")
    elif cmd in ("pull", "push"):
        print(f"[{cmd}] délégué à l'agent : voir skill notion-partitions-sync.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
