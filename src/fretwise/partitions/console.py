"""Aide console : sortie tolérante aux caractères non encodables (Windows cp1252).

Les scripts de ce package impriment des flèches, coches et émojis. Sur une
console Windows héritée (cp1252), ``print`` lèverait ``UnicodeEncodeError`` —
bug présent dans les scripts iCloud d'origine. On bascule stdout/stderr en
``errors="replace"`` (l'encodage lui-même est conservé pour ne pas casser les
accents sur les consoles non-UTF-8).
"""

from __future__ import annotations

import sys


def ensure_printable_output() -> None:
    """Rend stdout/stderr tolérants aux caractères non encodables."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(errors="replace")
        except (ValueError, OSError):
            pass
