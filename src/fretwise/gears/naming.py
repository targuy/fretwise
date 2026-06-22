"""Canonical filename scheme shared between FretWise and SongsGears.

A per-song gear sheet is keyed by ``<artist-slug>__<title-slug>`` so the same
file resolves from a score filename (FretWise side) and from song metadata
(SongsGears side). ``slugify`` is the single normalization both projects must
use; keep the two in lockstep when either changes.

Why a neutral ``artist__title`` key (not FretWise's legacy ``rig_{song}_{artist}``):
artist-first ordering groups a catalog by performer, ``__`` cleanly separates the
two free-text fields (each internally kebab-cased), and there is no ``rig_``
prefix to strip — SongsGears emits the same name without knowing FretWise's
legacy conventions.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

GEARS_KEY_SEP = "__"

# Splits a "Artist - Title" score stem. Mirrors the parser used by rig.py and the
# web front office so the gears key derived here matches what the user sees.
_SPLIT_SEP = re.compile(r"\s*-\s*")
_DATE_TAIL = re.compile(r"[\s-]+\d{2}[.\-]\d{2}[.\-]\d{4}(?:\s+\d+)?$")
_FINGERED_SUFFIX = re.compile(r"_fingered$", re.IGNORECASE)


def slugify(text: str) -> str:
    """Return the canonical kebab-case slug for one free-text field.

    Accent-stripped, lowercased, ``&``→``and``, ``/``→``-``; every other run of
    non-alphanumerics collapses to a single ``-`` with no leading/trailing dash.
    Empty input (or input with no alphanumerics) returns ``""``.
    """
    text = unicodedata.normalize("NFD", text or "")
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    text = text.encode("ascii", "ignore").decode("ascii").lower()
    text = text.replace("&", " and ").replace("/", "-")
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")


def gears_key(artist: str, title: str) -> str:
    """Return the canonical ``<artist-slug>__<title-slug>`` key.

    A missing artist still yields a valid key (``__title-slug``) so single-field
    songs resolve, but callers should pass both whenever available to avoid
    cross-artist collisions on shared titles.
    """
    return f"{slugify(artist)}{GEARS_KEY_SEP}{slugify(title)}"


def gears_filename(artist: str, title: str) -> str:
    """Return the canonical gears JSON filename for a song."""
    return f"{gears_key(artist, title)}.json"


def gears_key_from_filename(filename: str) -> str:
    """Derive the canonical gears key from a score/partition filename.

    Strips the extension, a trailing ``_fingered`` marker and a trailing date,
    then splits on the first `` - `` into (artist, title) exactly like the rig
    parser. A stem with no separator is treated as a title-only song.
    """
    stem = Path(filename).stem
    stem = _FINGERED_SUFFIX.sub("", stem)
    stem = _DATE_TAIL.sub("", stem)
    parts = _SPLIT_SEP.split(stem, maxsplit=1)
    if len(parts) == 2:
        return gears_key(parts[0], parts[1])
    return gears_key("", parts[0])
