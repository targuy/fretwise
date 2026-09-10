"""Chemins centralisés de la bibliothèque de partitions.

Tous les scripts du package passent par ce module : aucun chemin absolu ne doit
être codé en dur ailleurs. Chaque chemin est surchargable par variable
d'environnement (lue à chaque appel, pas à l'import, pour rester testable) :

- ``FRETWISE_PARTITIONS_ROOT`` — racine du workspace partitions
  (défaut : ``C:\\Users\\benoit\\iCloudDrive\\partitions``)
- ``FRETWISE_DOWNLOADS_DIR`` — répertoire de téléchargements du navigateur
  (défaut : ``~/Downloads``)
- ``FRETWISE_GDRIVE_DIR`` — miroir Google Drive
  (défaut : ``G:\\Mon Drive\\partitions``)

Conventions de sous-répertoires (relatifs à la racine) :

- ``partitions/`` — les fichiers ``.gp`` eux-mêmes
- ``_doublons_archive/`` — doublons archivés par ``move_downloads``
- ``_notion_queue/`` — artefacts JSON pour l'agent Notion
- ``_archive_logs/`` — snapshots et artefacts datés
"""

from __future__ import annotations

import os
from pathlib import Path

DEFAULT_PARTITIONS_ROOT = r"C:\Users\benoit\iCloudDrive\partitions"
DEFAULT_GDRIVE_DIR = r"G:\Mon Drive\partitions"

GP_SUBDIR = "partitions"
DOUBLONS_ARCHIVE_SUBDIR = "_doublons_archive"
NOTION_QUEUE_SUBDIR = "_notion_queue"
ARCHIVE_LOGS_SUBDIR = "_archive_logs"

LISTE_PARTITIONS_NAME = "liste_partitions.txt"
SONGS_INDEX_NAME = "songs_index.tsv"


def partitions_root() -> Path:
    """Racine du workspace partitions (env ``FRETWISE_PARTITIONS_ROOT``)."""
    return Path(os.environ.get("FRETWISE_PARTITIONS_ROOT", DEFAULT_PARTITIONS_ROOT))


def downloads_dir() -> Path:
    """Répertoire de téléchargements (env ``FRETWISE_DOWNLOADS_DIR``)."""
    return Path(os.environ.get("FRETWISE_DOWNLOADS_DIR", str(Path.home() / "Downloads")))


def gdrive_dir() -> Path:
    """Miroir Google Drive (env ``FRETWISE_GDRIVE_DIR``)."""
    return Path(os.environ.get("FRETWISE_GDRIVE_DIR", DEFAULT_GDRIVE_DIR))


def gp_dir(root: Path | None = None) -> Path:
    """Sous-répertoire contenant les fichiers ``.gp``."""
    return (root or partitions_root()) / GP_SUBDIR


def doublons_archive_dir(root: Path | None = None) -> Path:
    """Archive des doublons détectés par ``move_downloads``."""
    return (root or partitions_root()) / DOUBLONS_ARCHIVE_SUBDIR


def notion_queue_dir(root: Path | None = None) -> Path:
    """File d'attente d'artefacts JSON pour l'agent Notion."""
    return (root or partitions_root()) / NOTION_QUEUE_SUBDIR


def archive_logs_dir(root: Path | None = None) -> Path:
    """Répertoire des snapshots et artefacts datés."""
    return (root or partitions_root()) / ARCHIVE_LOGS_SUBDIR


def liste_partitions_path(root: Path | None = None) -> Path:
    """Fichier index humain ``liste_partitions.txt``."""
    return (root or partitions_root()) / LISTE_PARTITIONS_NAME


def songs_index_path(root: Path | None = None) -> Path:
    """Fichier index machine ``songs_index.tsv``."""
    return (root or partitions_root()) / SONGS_INDEX_NAME
