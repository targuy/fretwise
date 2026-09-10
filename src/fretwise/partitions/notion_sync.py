"""Synchronise les fichiers Guitar Pro avec la base Notion "Songs Library".

Pour chaque fichier .gp :
  - Si la page existe dans Songs Library  → insère un callout "Partition" dans la page
  - Si la page n'existe pas               → crée une nouvelle entrée dans la base

Usage :
    python -m fretwise.partitions.notion_sync --token <NOTION_TOKEN> \\
        [--dir <PARTITIONS_DIR>] [--dry-run]

Pré-requis :
    pip install requests   (import paresseux : message clair si absent)

Obtenir un token Notion :
    1. Aller sur https://www.notion.so/my-integrations
    2. Créer une nouvelle intégration (type "Internal")
    3. Copier le "Internal Integration Secret"
    4. Dans Notion, ouvrir la base Songs Library → "..." → "Connections" → ajouter l'intégration

NB : ce script interroge l'ID historique LEGACY_SONGS_LIBRARY_DATABASE_ID
(cf. fretwise.partitions.notion_ids pour l'explication du conflit d'IDs).
"""

from __future__ import annotations

import argparse
import re
import sys
import time
from collections.abc import Sequence
from pathlib import Path

from fretwise.partitions import paths
from fretwise.partitions.console import ensure_printable_output
from fretwise.partitions.notion_ids import LEGACY_SONGS_LIBRARY_DATABASE_ID

try:  # import paresseux/gardé — requests n'est requis que pour ce module
    import requests
except ImportError:  # pragma: no cover - dépend de l'environnement
    requests = None  # type: ignore[assignment]

# ─── CONFIGURATION ────────────────────────────────────────────────────────────

DATABASE_ID = LEGACY_SONGS_LIBRARY_DATABASE_ID  # Songs Library (ID historique)
NOTION_VERSION = "2022-06-28"
API_BASE = "https://api.notion.com/v1"

# Artistes dont le nom de fichier diffère du nom Notion
ARTIST_ALIASES = {
    "AC_DC": "AC/DC",
    "Carlos Santana": "Santana",
    "The Rolling Stones": "Rolling Stones",
    "The Eagles": "Eagles",
    "The White Stripes": "White Stripes",
    "The Beatles": "Beatles",
    "The Cranberries": "Cranberries",
    "The Animals": "Animals",
    "The Police": "Police",
    "The Police (Akuvestin)": "Police",
    "The Offspring": "Offspring",
    "The Connels": "Connels",
    "The Doors": "Doors",
    "The Kinks": "Kinks",
    "Rage Against The Machine": "Rage Against the Machine",
}

# ─── HELPERS ──────────────────────────────────────────────────────────────────


def notion_headers(token: str) -> dict:
    """En-têtes HTTP pour l'API Notion."""
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }


def parse_gp_filename(filename: str):
    """
    Extrait (artist, title) depuis un nom de fichier comme :
      AC_DC-Back In Black-12-05-2025.gp
      The Police (Akuvestin)-Every Breath You Take (Fingerstyle)-06-21-2025.gp
      Bon Jovi-Wanted Dead Or Alive - Rock Band Version-12-21-2011 (1).gp
    Retourne (artist_raw, title_raw) ou (None, None) si non reconnu.
    """
    # Supprime l'extension
    name = Path(filename).stem
    # Le timestamp est de la forme -MM-DD-YYYY à la fin (optionnellement suivi de " (N)")
    pattern = r"^(.+?)-(\d{2}-\d{2}-\d{4})(?:\s*\(\d+\))?$"
    m = re.match(pattern, name)
    if not m:
        return None, None
    body = m.group(1)   # tout avant le timestamp
    # Le body est "Artiste-Titre" ; on coupe au premier "-"
    # (AC/DC est déjà encodé "AC_DC" dans les noms de fichiers)
    parts = body.split("-", 1)
    if len(parts) < 2:
        return None, None
    artist_raw = parts[0].strip()
    title_raw = parts[1].strip()
    return artist_raw, title_raw


def normalize_artist(artist_raw: str) -> str:
    """Applique les alias artiste fichier → Notion."""
    return ARTIST_ALIASES.get(artist_raw, artist_raw)


def search_song_in_db(token: str, artist: str, title: str) -> list:
    """Cherche une page dans Songs Library par titre. Retourne la liste des pages trouvées."""
    url = f"{API_BASE}/databases/{DATABASE_ID}/query"
    payload = {
        "filter": {
            "property": "Song",
            "title": {"equals": title}
        }
    }
    r = requests.post(url, headers=notion_headers(token), json=payload)
    if r.status_code != 200:
        print(f"  ⚠ Erreur API query: {r.status_code} {r.text[:200]}")
        return []
    results = r.json().get("results", [])
    # Filtre par artiste si plusieurs résultats
    if len(results) > 1:
        filtered = []
        for page in results:
            artist_prop = page.get("properties", {}).get("Artist", {})
            page_artist = ""
            if artist_prop.get("type") == "select" and artist_prop.get("select"):
                page_artist = artist_prop["select"].get("name", "")
            if page_artist.lower() == artist.lower():
                filtered.append(page)
        if filtered:
            return filtered
    return results


def has_partition_callout(token: str, page_id: str) -> bool:
    """Vérifie si la page contient déjà un callout Partition."""
    url = f"{API_BASE}/blocks/{page_id}/children"
    r = requests.get(url, headers=notion_headers(token))
    if r.status_code != 200:
        return False
    blocks = r.json().get("results", [])
    for block in blocks:
        if block.get("type") == "callout":
            rich_text = block.get("callout", {}).get("rich_text", [])
            for rt in rich_text:
                if "partition" in rt.get("plain_text", "").lower():
                    return True
    return False


def append_partition_callout(token: str, page_id: str, filenames: list, dry_run: bool) -> bool:
    """Ajoute un callout Partition à la fin de la page."""
    files_text = "\n".join(filenames)
    callout_block = {
        "object": "block",
        "type": "callout",
        "callout": {
            "rich_text": [
                {"type": "text", "text": {"content": "Partition\n" + files_text}},
            ],
            "icon": {"type": "emoji", "emoji": "🎸"},
            "color": "gray_background",
        }
    }
    if dry_run:
        print(f"    [DRY-RUN] Ajouterait callout avec : {filenames}")
        return True
    url = f"{API_BASE}/blocks/{page_id}/children"
    payload = {"children": [callout_block]}
    r = requests.patch(url, headers=notion_headers(token), json=payload)
    if r.status_code in (200, 201):
        return True
    print(f"    ⚠ Erreur lors de l'ajout du callout: {r.status_code} {r.text[:300]}")
    return False


def create_song_page(
    token: str, artist: str, title: str, filenames: list, dry_run: bool
) -> str | None:
    """Crée une nouvelle page dans Songs Library avec le callout Partition."""
    files_text = "\n".join(filenames)
    payload = {
        "parent": {"database_id": DATABASE_ID},
        "icon": {"type": "emoji", "emoji": "🎵"},
        "properties": {
            "Song": {
                "title": [{"type": "text", "text": {"content": title}}]
            },
            "Artist": {
                "select": {"name": artist}
            }
        },
        "children": [
            {
                "object": "block",
                "type": "callout",
                "callout": {
                    "rich_text": [
                        {"type": "text", "text": {"content": "Partition\n" + files_text}},
                    ],
                    "icon": {"type": "emoji", "emoji": "🎸"},
                    "color": "gray_background",
                }
            }
        ]
    }
    if dry_run:
        print(f"    [DRY-RUN] Créerait page : {artist} - {title} avec {filenames}")
        return "dry-run-id"
    r = requests.post(f"{API_BASE}/pages", headers=notion_headers(token), json=payload)
    if r.status_code in (200, 201):
        return r.json().get("id")
    print(f"    ⚠ Erreur création page: {r.status_code} {r.text[:300]}")
    return None


# ─── MAIN ─────────────────────────────────────────────────────────────────────

def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entrée CLI. Retourne le code de sortie."""
    ensure_printable_output()
    parser = argparse.ArgumentParser(
        description="Sync partitions Guitar Pro → Notion Songs Library")
    parser.add_argument("--token", required=True, help="Notion Integration Token (secret_...)")
    parser.add_argument("--dir", default=None,
                        help="Répertoire contenant les fichiers .gp (défaut: <root>/partitions)")
    parser.add_argument("--dry-run", action="store_true", help="Simulation sans modification")
    args = parser.parse_args(argv)

    if requests is None:
        print("❌ Le package 'requests' est requis pour notion_sync : pip install requests",
              file=sys.stderr)
        return 1

    gp_dir = Path(args.dir) if args.dir else paths.gp_dir()
    gp_files = sorted(gp_dir.glob("*.gp"))

    if not gp_files:
        print(f"❌ Aucun fichier .gp trouvé dans {gp_dir}")
        return 1

    print(f"\n{'='*60}")
    print("  SYNC GUITAR PRO -> NOTION SONGS LIBRARY")
    print(f"  {'[DRY-RUN] ' if args.dry_run else ''}Répertoire : {gp_dir.resolve()}")
    print(f"  {len(gp_files)} fichiers trouvés")
    print(f"{'='*60}\n")

    # Regrouper les fichiers par (artist_raw, title_raw)
    groups: dict[tuple, list] = {}
    skipped = []
    for gp in gp_files:
        artist_raw, title_raw = parse_gp_filename(gp.name)
        if not artist_raw:
            skipped.append(gp.name)
            continue
        key = (artist_raw, title_raw)
        groups.setdefault(key, []).append(gp.name)

    if skipped:
        print(f"⚠  {len(skipped)} fichier(s) ignoré(s) (format non reconnu) :")
        for s in skipped:
            print(f"   - {s}")
        print()

    # Statistiques
    stats = {"exists_updated": 0, "exists_skipped": 0, "created": 0, "errors": 0}

    for (artist_raw, title_raw), filenames in sorted(groups.items()):
        artist = normalize_artist(artist_raw)
        # Nettoie le titre (supprime le suffixe " - Rock Band Version", "(Fingerstyle)", etc.)
        # pour la recherche Notion, mais garde le nom de fichier original
        search_title = title_raw
        # Supprime certains suffixes spécifiques
        for suffix in [" - Rock Band Version", " (Fingerstyle)", " Solo", " (Shove It)"]:
            search_title = search_title.replace(suffix, "")
        search_title = search_title.strip()

        print(f"🎸 {artist} – {title_raw}")
        if len(filenames) > 1:
            print(f"   📄 Fichiers ({len(filenames)}) : {', '.join(filenames)}")
        else:
            print(f"   📄 Fichier : {filenames[0]}")

        # Recherche dans la DB
        pages = search_song_in_db(args.token, artist, search_title)
        time.sleep(0.35)  # Respecte le rate limit Notion (~3 req/s)

        if pages:
            page = pages[0]
            page_id = page["id"]
            page_url = page.get("url", "")
            print(f"   ✅ Page trouvée : {page_url}")

            # Vérifie si callout déjà présent
            if has_partition_callout(args.token, page_id):
                print("   ⏭  Callout 'Partition' déjà présent, skipping.")
                stats["exists_skipped"] += 1
            else:
                ok = append_partition_callout(args.token, page_id, filenames, args.dry_run)
                if ok:
                    print("   ✔  Callout ajouté avec succès.")
                    stats["exists_updated"] += 1
                else:
                    stats["errors"] += 1
        else:
            print("   ➕ Page non trouvée → création...")
            new_id = create_song_page(args.token, artist, search_title, filenames, args.dry_run)
            if new_id:
                print(f"   ✔  Page créée : https://www.notion.so/{new_id.replace('-', '')}")
                stats["created"] += 1
            else:
                stats["errors"] += 1

        print()

    # Résumé final
    total = stats["exists_updated"] + stats["exists_skipped"] + stats["created"] + stats["errors"]
    print(f"\n{'='*60}")
    print(f"  RÉSUMÉ FINAL ({total} chansons traitées)")
    print(f"{'='*60}")
    print(f"  ✅ Pages existantes mises à jour : {stats['exists_updated']}")
    print(f"  ⏭  Pages existantes déjà à jour  : {stats['exists_skipped']}")
    print(f"  ➕ Nouvelles pages créées         : {stats['created']}")
    print(f"  ❌ Erreurs                        : {stats['errors']}")
    print(f"{'='*60}\n")
    return 0 if stats["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
