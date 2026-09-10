"""Outillage de gestion de la bibliothèque de partitions Guitar Pro.

Portage du workspace iCloud ``C:/Users/benoit/iCloudDrive/partitions`` (les
sources originales y restent intactes). Tous les chemins sont centralisés dans
:mod:`fretwise.partitions.paths` et surchargables par variables d'environnement
(``FRETWISE_PARTITIONS_ROOT``, ``FRETWISE_DOWNLOADS_DIR``, ``FRETWISE_GDRIVE_DIR``).

Workflow quotidien (orchestré par :mod:`fretwise.partitions.daily_sync`) :

1. **watcher / move** — :mod:`move_downloads` ramène les ``.gp`` téléchargés
   depuis ``Downloads/`` vers ``<root>/partitions/`` avec dédup (les doublons
   partent dans ``<root>/_doublons_archive/``).
2. **rebuild** — :mod:`rebuild_indexes` régénère ``liste_partitions.txt`` et
   ``songs_index.tsv`` (métadonnées year/genre/guitar/rig/notion_id préservées).
3. **enrich** — :mod:`enrich_from_notion` prépare ``<root>/_notion_queue/``
   (plan JSON) pour qu'un agent IA complète le TSV depuis Notion, sans aucun
   appel réseau côté local.
4. **propose** — :mod:`propose_songs` filtre un fichier de candidats contre la
   bibliothèque (anti-doublon + équilibrage artiste) et génère le prompt
   Songsterr du jour ; :mod:`check_before_download` fait la vérification seule.
5. **archive** — :mod:`archive_old` snapshotte les index et range les artefacts
   datés dans ``<root>/_archive_logs/YYYY-MM-DD/``.

Téléchargement effectif : le prompt généré (:mod:`songsterr_prompt`,
:mod:`propose_songs`, :mod:`curate_beginners`) est exécuté par Claude-in-Chrome
sur songsterr.com (sélecteurs DOM stables ``#control-export``,
``#control-export-gp``, ``form#export_modal``).

Synchronisations annexes : :mod:`sync_gdrive` (copie vers Google Drive),
:mod:`notion_sync` (API Notion directe, nécessite ``requests``),
:mod:`sync_songs` (diff local ↔ export Notion + plans de writes minimaux),
:mod:`tag_genres` (auto-tag genre par artiste).
"""
