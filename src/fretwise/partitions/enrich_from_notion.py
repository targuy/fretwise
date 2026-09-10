"""Enrichit songs_index.tsv avec year/genre/guitar/rig depuis Notion.

Architecture token-éco :
    - Le PC local fait le boulot lourd (lecture TSV, comparaison).
    - Le script GÉNÈRE des artefacts JSON listant ce qu'il faut faire côté Notion.
    - Un agent IA (Claude ou autre) lit ces artefacts et exécute les appels Notion.
    - À l'itération suivante, le script relit Notion et complète le TSV.

Sortie (toujours dans <root>/_notion_queue/) :
    pending_lookups.json   : songs avec metadata manquante → l'agent les cherche dans Notion
    pending_todos.json     : songs introuvables côté Notion → à ajouter dans la Todo DB
    completed.json         : songs déjà enrichies dans cette run (info)

Usage :
    python -m fretwise.partitions.enrich_from_notion [--root PATH]

L'agent doit ensuite :
    1. Lire pending_lookups.json
    2. Pour chaque entrée : notion-search sur Songs Library
       (id=SONGS_LIBRARY_DATA_SOURCE_ID, cf. fretwise.partitions.notion_ids)
    3. Si trouvé : extraire year, genre, guitar, rig ; écrire dans songs_index.tsv
    4. Si pas trouvé : créer entrée dans Todo DB (id=TODO_DATABASE_ID)
       avec un lien vers le prompt Notion "create_song" ou "update_song"

Le script lui-même ne fait AUCUN appel réseau — il prépare uniquement le plan.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.notion_ids import (
    PARTITIONS_DATA_SOURCE_ID,
    SONGS_LIBRARY_DATA_SOURCE_ID,
    TODO_DATABASE_ID,
)

# Champs considérés "enrichis" — si TOUS sont vides, on cherche dans Notion
ENRICH_FIELDS = ["year", "genre"]  # guitar et rig sont optionnels


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--root", default=None, help="Racine du workspace partitions")
    ap.add_argument("--max-lookups", type=int, default=200,
                    help="Limite le nombre de lookups par run pour éviter de spammer l'agent")
    args = ap.parse_args(argv)

    root = Path(args.root) if args.root else paths.partitions_root()
    tsv_file = paths.songs_index_path(root)
    queue_dir = paths.notion_queue_dir(root)
    queue_dir.mkdir(exist_ok=True)

    if not tsv_file.exists():
        print(f"ERREUR : {tsv_file} introuvable", file=sys.stderr)
        return 1

    raw = tsv_file.read_bytes().replace(b"\x00", b"").decode("utf-8", errors="replace")
    rows = list(csv.DictReader(raw.splitlines(), delimiter="\t"))

    # Charge la liste des lookups déjà demandés (todos in flight)
    in_flight_path = queue_dir / "in_flight_todos.json"
    in_flight = {}
    if in_flight_path.exists():
        in_flight = json.loads(in_flight_path.read_text(encoding="utf-8"))

    pending_lookups = []   # songs à chercher dans Notion Songs Library
    pending_todos: list[dict[str, str]] = []  # songs absentes de Notion → todo
    completed = []         # songs déjà enrichies, info uniquement

    for row in rows:
        artist = row.get("artist", "").strip()
        title = row.get("title", "").strip()
        if not artist or not title:
            continue
        key = f"{artist.lower()}|{title.lower()}"
        has_meta = any((row.get(f) or "").strip() for f in ENRICH_FIELDS)

        if has_meta:
            completed.append({"artist": artist, "title": title,
                              "year": row.get("year", ""),
                              "genre": row.get("genre", "")})
            # Si elle est devenue enrichie, retirer de in_flight
            if key in in_flight:
                in_flight.pop(key, None)
            continue

        # Pas enrichie : décider si on relance le lookup ou si la todo est déjà en cours
        if key in in_flight:
            # Todo en cours côté Notion — on ne re-demande pas tant qu'elle n'est pas terminée
            continue

        if len(pending_lookups) < args.max_lookups:
            pending_lookups.append({
                "file": row["file"],
                "artist": artist,
                "title": title,
                "date_added": row.get("date_added", ""),
            })

    # Crée la liste des todos pour les chansons jamais trouvées
    # (l'agent décidera lesquelles deviennent des todos après ses searches)
    summary = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "tsv_total": len(rows),
        "tsv_enriched": len(completed),
        "tsv_missing_meta": sum(1 for r in rows
                                if not any((r.get(f) or "").strip()
                                           for f in ENRICH_FIELDS)),
        "pending_lookups_count": len(pending_lookups),
        "pending_todos_count": len(pending_todos),
        "in_flight_count": len(in_flight),
        "notion_ids": {
            "songs_library_data_source": SONGS_LIBRARY_DATA_SOURCE_ID,
            "partitions_data_source": PARTITIONS_DATA_SOURCE_ID,
            "todo_database_page": TODO_DATABASE_ID,
        },
        "agent_instructions": (
            "1. Pour chaque entrée de pending_lookups.json, faire notion-search "
            "sur le data_source 'songs_library_data_source' avec query='<artist> <title>'. "
            "2. Si match exact (titre identique, artiste contient) : extraire les "
            "properties 'Year' (ou 'Sortie'), 'Genre' (ou 'Style'), 'Guitar' (ou 'Guitare'), "
            "'Rig'. Mettre à jour la ligne dans songs_index.tsv. "
            "3. Si introuvable : appeler notion-create-pages sur 'todo_database_page' "
            "avec une todo 'Créer fiche Songs Library pour <artist> - <title>' et stocker "
            "la clé dans in_flight_todos.json (clé = '<artist>|<title>' lowercase). "
            "4. À la prochaine run, in_flight évite de re-créer la même todo."
        ),
    }

    (queue_dir / "pending_lookups.json").write_text(
        json.dumps(pending_lookups, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (queue_dir / "pending_todos.json").write_text(
        json.dumps(pending_todos, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (queue_dir / "in_flight_todos.json").write_text(
        json.dumps(in_flight, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (queue_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"[done] enrich plan: lookups={summary['pending_lookups_count']} "
          f"in_flight={summary['in_flight_count']} "
          f"enriched={summary['tsv_enriched']}/{summary['tsv_total']}")
    print(f"       artefacts dans {queue_dir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
