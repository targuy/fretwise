"""New-format GP-180 rig "gears" — per-song tone sheets in the shared SongsGears
JSON schema, the single source that supersedes the legacy ``.md`` sheets.

Sheets live flat under ``data/gears/<key>.json`` where ``key`` is the canonical
:func:`fretwise.gears.naming.gears_key` (``artist__title``) shared with the
SongsGears project. :func:`fretwise.gears.adapter.song_output_to_view` converts
one such document into the same view dict the web renderer already consumes for
``.md`` rig sheets, so the front office renders either source unchanged.
"""

from fretwise.gears.adapter import song_output_to_view
from fretwise.gears.naming import (
    GEARS_KEY_SEP,
    gears_filename,
    gears_key,
    gears_key_from_filename,
    slugify,
)

__all__ = [
    "GEARS_KEY_SEP",
    "gears_filename",
    "gears_key",
    "gears_key_from_filename",
    "slugify",
    "song_output_to_view",
]
