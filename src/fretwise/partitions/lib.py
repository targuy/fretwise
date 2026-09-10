"""Librairie partagée pour la gestion de la bibliothèque Guitar Pro.

Fonctions pures (pas d'I/O), portables, utilisables par tout script Python
— y compris des agents IA non-Claude.

Fonctions clés :
    parse_filename(name)       -> ParsedFilename(artist, title, date, fingered)
    normalize_identity(a, t)   -> str  (clé canonique pour dédup)
    to_display_entry(file)     -> "Artist - Title"  (pour liste_partitions.txt)
    is_partition_file(name)    -> bool

Schéma TSV (songs_index.tsv) :
    file, artist, title, date_added, year, genre, guitar, rig, notion_id, fingered

La colonne `fingered` vaut "1" si le nom de fichier contient `_fingered`, sinon "".
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

COMPOUND_ARTISTS = [
    "Blink-182",
    "blink-182",
    "Eagle-Eye Cherry",
    "Jean-Jacques Goldman",
    "T-Rex",
    "T.Rex",
]

ARTIST_DECODE = {
    "AC_DC": "AC/DC",
}

TSV_COLUMNS = [
    "file",
    "artist",
    "title",
    "date_added",
    "year",
    "genre",
    "guitar",
    "rig",
    "notion_id",
    "fingered",
]

PRESERVED_COLUMNS = ["year", "genre", "guitar", "rig", "notion_id"]


@dataclass
class ParsedFilename:
    """Décomposition d'un nom de fichier .gp en (artiste, titre, date, fingered)."""

    artist: str
    title: str
    date: str | None
    fingered: bool


_RE_TRAILING_DATE = re.compile(
    r"[ \-]+(\d{2}-\d{2}-\d{4})"
    r"(?:\s*\(\d+\))?"
    r"(_[a-zA-Z]+)?"
    r"$"
)


def is_partition_file(name: str) -> bool:
    """True si le fichier est une partition Guitar Pro."""
    n = name.lower()
    return n.endswith((".gp", ".gpx", ".gp5", ".gp4", ".gp3"))


def parse_filename(name: str) -> ParsedFilename:
    """Extrait (artist, title, date MM-DD-YYYY, fingered) depuis un nom de fichier .gp."""
    stem = re.sub(r"\.(gp|gpx|gp5|gp4|gp3)$", "", name, flags=re.IGNORECASE)
    m = _RE_TRAILING_DATE.search(stem)
    fingered = False
    date: str | None = None
    if m:
        date = m.group(1)
        suffix = m.group(2) or ""
        fingered = suffix.lower() == "_fingered"
        body = stem[: m.start()].rstrip(" -")
    else:
        body = stem.rstrip(" -")

    artist = ""
    title = ""
    body_lower = body.lower()
    for compound in COMPOUND_ARTISTS:
        cl = compound.lower()
        if body_lower.startswith(cl + "-") or body_lower.startswith(cl + " - "):
            artist = compound
            title = body[len(compound):].lstrip(" -")
            break

    if not artist:
        if " - " in body:
            artist, _, title = body.partition(" - ")
        elif "-" in body:
            artist, _, title = body.partition("-")
        else:
            artist = body
            title = ""

    artist = ARTIST_DECODE.get(artist.strip(), artist.strip())
    return ParsedFilename(artist=artist, title=title.strip(), date=date, fingered=fingered)


def _norm_text(s: str) -> str:
    """Normalise un texte pour comparaison."""
    s = s.lower().replace("_", " ").replace("/", " ")
    s = re.sub(r"[.,!?'\"()&]", "", s)
    s = re.sub(r"\b(and|et)\b", "", s)
    s = re.sub(r"\bfingered\b", "", s)
    s = re.sub(r"\s+", " ", s).strip()
    s = unicodedata.normalize("NFD", s)
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s


def normalize_identity(artist: str, title: str) -> str:
    """Identité canonique d'un morceau (sans date) pour la dédup."""
    return f"{_norm_text(artist)}|{_norm_text(title)}"


def to_display_entry(filename: str) -> str:
    """Convertit un nom de fichier en entrée 'Artist - Title'."""
    p = parse_filename(filename)
    return f"{p.artist} - {p.title}" if p.title else p.artist
