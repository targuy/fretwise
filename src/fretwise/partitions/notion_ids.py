"""Constantes nommées pour les IDs Notion utilisés par les scripts partitions.

⚠️ CONFLIT D'IDs DÉTECTÉ lors du portage (2026-07) — deux paires d'identifiants
coexistent dans le code source original :

- **Songs Library** : l'ID canonique ``199b…0ae5`` (data source, utilisé par les
  skills Claude et par ``enrich_from_notion``) diffère de ``a108…dd36`` que
  ``notion_sync_partitions.py`` (→ :mod:`fretwise.partitions.notion_sync`)
  interroge via l'API databases. Il s'agit vraisemblablement du couple
  database-id (API v1 ``/databases/{id}/query``) vs data-source-id (API MCP).
  Le code porté conserve le comportement d'origine : ``notion_sync`` continue
  d'utiliser ``LEGACY_SONGS_LIBRARY_DATABASE_ID``.
- **Partitions** : l'ID canonique ``ea10…a71a`` diffère de ``6d96…25ba``
  qu'utilisait ``notion_finish_path_updates.py`` (migration one-shot, non
  portée). Conservé ici en LEGACY_* pour référence.
"""

# ── IDs canoniques (utilisés par les skills et enrich_from_notion) ────────────

#: Data source Notion "Songs Library" (canonique).
SONGS_LIBRARY_DATA_SOURCE_ID = "199b2b85-3d8d-4895-a101-3e1f1ac30ae5"

#: Data source Notion "Partitions" (canonique).
PARTITIONS_DATA_SOURCE_ID = "ea104966-2390-4f65-86c2-81cdb8d6a71a"

#: Page/database Notion "Todo".
TODO_DATABASE_ID = "b4fc5ae26331488d9b721e8a22ca3a17"

#: Page Notion "Chansons".
CHANSONS_PAGE_ID = "2dcd399a325b80048e75da261033b6ee"

# ── Variantes legacy (comportement historique préservé) ───────────────────────

#: Songs Library tel qu'interrogé par notion_sync (API /databases/{id}/query).
#: Diffère de SONGS_LIBRARY_DATA_SOURCE_ID — voir le commentaire de module.
LEGACY_SONGS_LIBRARY_DATABASE_ID = "a108b2da-3565-4272-a70a-d68e528bdd36"

#: Partitions tel qu'utilisé par notion_finish_path_updates.py (non porté).
LEGACY_PARTITIONS_DATABASE_ID = "6d96feb6-bfef-4532-89ff-62dfb5925aba"

# ── URLs référencées par les plans de writes (sync_songs) ─────────────────────

TODO_DATABASE_URL = f"https://www.notion.so/{TODO_DATABASE_ID}"

#: Prompts Notion référencés PAR LIEN uniquement (jamais lus côté local).
PROMPT_URLS = {
    "create_song": "https://www.notion.so/Create-Song-Prompt-2fed399a325b8033a01bc58cfa5c0d41",
    "update_song": "https://www.notion.so/Update-Song-prompt-d34fbba1f1a64a1d9fd8c3532285d4ce",
    "update_from_gp": (
        "https://www.notion.so/"
        "Update-Songs-from-Guitar-Pro-Partitions-Prompt-b3a98d04de2946c4bfeb1dbce9001527"
    ),
    "update_links": (
        "https://www.notion.so/"
        "Update-Songs-Library-Partition-Links-Prompt-01b7bd277c68425b91a1643d985b2ba9"
    ),
    "create_from_gp": (
        "https://www.notion.so/"
        "Create-from-Guitar-Pro-Partitions-Prompt-0f27f4ce193345498b362cf46e31806d"
    ),
}
