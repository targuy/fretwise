"""Local, offline song-metadata catalog reader (E2.2).

FretWise enriches the library view with metadata coming from **two** sources,
merged with a clear precedence:

1. **Filename parsing** — titles/artists/years inferred from filenames shaped
   like ``Artist - Title - MM-DD-YYYY.gp``. Always available, never invented
   beyond what the filename actually contains.
2. **Local catalog** — a user-editable, tab-separated ``songs.tsv`` file. This
   is fully offline: no network lookup is ever performed. The operator owns and
   edits this file by hand (or with a spreadsheet that exports TSV).

Catalog (non-empty) values **override** the filename-derived fields. Anything
the catalog omits is filled in from the filename. ``album``/``genre``/``notes``
are *never* invented — they appear only when the catalog supplies them.

Catalog file format (``songs.tsv``)
-----------------------------------
* Tab-separated values, UTF-8 (a leading BOM is tolerated).
* The **first row is a header** naming the columns.
* Recognised columns (all optional except a key column):

  ====================  =====================================================
  Column                Meaning
  ====================  =====================================================
  ``filename``          Key: the score filename. ``file`` / ``name`` /
                        ``stem`` are accepted as aliases. Matching is done on
                        the full filename *and* on the extension-less stem, so
                        either form works as the key.
  ``title``             Song title.
  ``artist``            Performing artist / composer.
  ``album``             Album the track belongs to.
  ``genre``             Musical genre (also drives the library Genre filter).
  ``year``              Release / recording year.
  ``notes``             Free-form notes (tuning, capo, difficulty, …).
  ====================  =====================================================

* Extra columns are kept and surfaced too; missing columns are tolerated.
* Empty cells are ignored (they never clobber filename-derived values).

File location
-------------
The catalog path is configured via the ``index_path`` web setting. There is no
default on-disk catalog shipped with FretWise; a commented header-only template
lives at ``data/songs.tsv.example`` to document the expected layout. A missing
or unreadable file simply yields no catalog metadata (filename parsing still
applies).
"""
from __future__ import annotations

import csv
import io
import re
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# Ordered set of catalog columns FretWise understands. Used for documentation
# and to keep UI ordering stable; unknown columns are still preserved.
CATALOG_FIELDS: tuple[str, ...] = (
    "title",
    "artist",
    "album",
    "genre",
    "year",
    "notes",
)

# Canonical, full column order written back to ``songs.tsv``. The key column
# (``filename``) comes first, followed by the documented metadata fields.
CATALOG_COLUMNS: tuple[str, ...] = ("filename", *CATALOG_FIELDS)

# Header aliases that all identify the "which file is this row about?" key.
_KEY_ALIASES: tuple[str, ...] = ("filename", "file", "name", "stem")

# Trailing date stamp embedded in filenames: "MM-DD-YYYY" (e.g. "10-16-2024").
# Optionally preceded by a " - " / "-" separator that we also consume so the
# remaining stem is clean ("Artist - Title").
_DATE_RE = re.compile(r"\s*-\s*(?P<m>\d{1,2})-(?P<d>\d{1,2})-(?P<y>\d{4})\s*$")


def parse_filename_metadata(name: str) -> dict[str, str]:
    """Parse ``Artist - Title - MM-DD-YYYY.ext`` style filenames.

    Splits the stem into a clean ``title``, ``artist`` and ``year`` (taken from
    the trailing ``MM-DD-YYYY`` date when present). Handles both spaced
    (``Artist - Title``) and tight (``Artist-Title``) separators. Falls back to
    using the whole stem as the title when no artist separator is found.

    Returns a dict with non-empty ``title``/``artist``/``year`` keys only.

    Examples:
        "Aerosmith - Back In The Saddle - 10-16-2024.gp"
            -> {"title": "Back In The Saddle", "artist": "Aerosmith", "year": "2024"}
        "Artist-Title-01-02-2020"
            -> {"title": "Title", "artist": "Artist", "year": "2020"}
    """
    stem = Path(name).stem

    year = ""
    date_match = _DATE_RE.search(stem)
    if date_match:
        year = date_match.group("y")
        stem = stem[: date_match.start()].strip()

    # Strip any leftover trailing separator left by an odd filename.
    stem = re.sub(r"\s*-\s*$", "", stem).strip()

    artist = ""
    title = stem
    # Prefer a spaced " - " separator (artist/title); fall back to a tight "-".
    if " - " in stem:
        artist, _, title = stem.partition(" - ")
    elif "-" in stem:
        artist, _, title = stem.partition("-")

    artist = artist.strip()
    title = title.strip() or stem.strip()

    out: dict[str, str] = {}
    if title:
        out["title"] = title
    if artist:
        out["artist"] = artist
    if year:
        out["year"] = year
    return out


def load_index(tsv_path: str | Path) -> dict[str, dict[str, Any]]:
    """Read the ``songs.tsv`` catalog and index rows by filename and by stem.

    The catalog is a tab-separated file with a header row (see the module
    docstring for the schema). Reading is deliberately forgiving:

    * a missing/empty/unreadable file yields an empty dict;
    * a BOM and UTF-8 encoding are handled transparently;
    * extra or missing columns are tolerated;
    * each row is indexed both by its full ``filename`` and by the
      extension-less stem, so callers can match either form;
    * cell values are whitespace-stripped.

    Returns:
        Mapping of ``filename`` / ``stem`` -> the cleaned catalog row. Returns an
        empty dict on any read error rather than raising.
    """
    path = Path(tsv_path) if tsv_path else None
    if not path or not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8-sig")
    except OSError:
        return {}
    return load_index_from_text(text)


def load_index_from_text(text: str) -> dict[str, dict[str, Any]]:
    """Parse a ``songs.tsv`` catalog given as in-memory text.

    Same forgiving semantics as :func:`load_index` (BOM-tolerant, extra/missing
    columns tolerated, values stripped, indexed by both filename and stem), but
    sourced from a string rather than a file. This is used when the catalog is
    read from the user's storage backend (multi-user mode).

    Args:
        text: The raw TSV content (a leading BOM is tolerated).

    Returns:
        Mapping of ``filename`` / ``stem`` -> the cleaned catalog row. Returns an
        empty dict on any parse error rather than raising.
    """
    if not text:
        return {}
    # Tolerate a leading BOM even when the caller decoded as plain UTF-8.
    text = text.lstrip("﻿")

    result: dict[str, dict[str, Any]] = {}
    try:
        reader = csv.DictReader(io.StringIO(text), delimiter="\t")
        for row in reader:
            # Normalize: strip whitespace from keys/values, drop unnamed cols.
            clean = {
                k.strip(): (v.strip() if isinstance(v, str) else v)
                for k, v in row.items()
                if k and k.strip()
            }
            # Locate the key column under any of its accepted aliases.
            name = ""
            for alias in _KEY_ALIASES:
                candidate = clean.get(alias)
                if candidate:
                    name = candidate
                    break
            if not name:
                continue
            result[name] = clean
            # Also index by stem (no extension) so either form matches.
            stem = Path(name).stem
            if stem and stem != name:
                result.setdefault(stem, clean)
    except csv.Error:
        return {}

    return result


def serialize_index(rows: Iterable[Mapping[str, Any]]) -> str:
    """Serialize catalog rows back to TSV text (header + tab-separated values).

    Columns are written in the canonical :data:`CATALOG_COLUMNS` order
    (``filename`` first, then the documented metadata fields). Any extra columns
    present on the rows are appended after the canonical ones, in first-seen
    order, so unknown data survives a round-trip. Missing cells are written as
    empty strings.

    Args:
        rows: An iterable of catalog rows (mappings keyed by column name). Rows
            without a non-empty ``filename`` are skipped.

    Returns:
        The TSV document as a single UTF-8 string (``\\n`` line endings, with a
        trailing newline).
    """
    rows = list(rows)
    extra: list[str] = []
    for row in rows:
        for key in row:
            if key not in CATALOG_COLUMNS and key not in extra:
                extra.append(key)
    columns = [*CATALOG_COLUMNS, *extra]

    buffer = io.StringIO()
    writer = csv.DictWriter(
        buffer, fieldnames=columns, delimiter="\t",
        lineterminator="\n", extrasaction="ignore",
    )
    writer.writeheader()
    for row in rows:
        filename = str(row.get("filename") or "").strip()
        if not filename:
            continue
        out = {col: ("" if row.get(col) is None else str(row.get(col))) for col in columns}
        out["filename"] = filename
        writer.writerow(out)
    return buffer.getvalue()


def merge_catalog(
    existing_text: str, incoming: Iterable[Mapping[str, Any]]
) -> tuple[str, int, int]:
    """Upsert *incoming* metadata rows into an existing ``songs.tsv`` document.

    Rows are matched by their ``filename`` key. For an existing filename, each
    non-empty incoming value overrides the stored one (empty incoming values are
    ignored, so the LLM omitting a field never wipes existing data); unknown
    filenames are appended as new rows. Incoming rows without a ``filename`` are
    skipped.

    Args:
        existing_text: The current TSV content (may be empty).
        incoming: Parsed objects from the LLM, each a mapping with at least a
            ``filename`` and any of the documented metadata fields.

    Returns:
        ``(tsv_text, updated, added)`` where ``updated`` counts existing rows
        changed and ``added`` counts brand-new filenames.
    """
    # Build an ordered, de-duplicated view of the existing catalog keyed by
    # filename (ignore the stem aliases the loader also emits).
    order: list[str] = []
    catalog: dict[str, dict[str, Any]] = {}
    if existing_text:
        for row in load_index_from_text(existing_text).values():
            filename = str(row.get("filename") or row.get("file") or "").strip()
            if not filename or filename in catalog:
                continue
            normalized = {k: v for k, v in row.items() if k not in _KEY_ALIASES}
            normalized["filename"] = filename
            catalog[filename] = normalized
            order.append(filename)

    updated = 0
    added = 0
    for item in incoming:
        filename = str(item.get("filename") or "").strip()
        if not filename:
            continue
        values = {
            field: str(item[field]).strip()
            for field in CATALOG_FIELDS
            if field in item and str(item[field]).strip()
        }
        if filename in catalog:
            row = catalog[filename]
            changed = any(row.get(field, "") != value for field, value in values.items())
            row.update(values)
            if changed:
                updated += 1
        else:
            new_row: dict[str, Any] = {"filename": filename, **values}
            catalog[filename] = new_row
            order.append(filename)
            added += 1

    text = serialize_index(catalog[name] for name in order)
    return text, updated, added


# Self-contained prompt the user pastes (along with the exported song list) into
# their own LLM to enrich the catalog. Kept here as the single source of truth;
# the same text is also shipped as a downloadable ``.md`` asset and served by the
# ``/api/songs/prompt`` endpoint.
METADATA_PROMPT: str = """\
# FretWise — Guitar Song Metadata Enrichment

You are a music-metadata assistant. Your task is to enrich metadata for a list
of guitar songs.

## Input

You will be given a JSON array of songs. Each entry has at least these fields:

```json
[
  {"filename": "Aerosmith - Back In The Saddle - 10-16-2024.gp",
   "title": "Back In The Saddle", "artist": "Aerosmith"}
]
```

The `filename` is the unique match key — copy it back **verbatim**. `title` and
`artist` are best-effort guesses parsed from the filename; correct them if you
are confident they are wrong.

## Task

For each song, fill in as much accurate metadata as you can: corrected title and
artist, plus the album, genre, release year, and any short useful notes
(e.g. tuning, capo, alternate version).

## Output

Return **only** a single valid JSON array — no prose, no explanation, no
Markdown code fences. Each object must have **exactly** these keys:

- `filename` — copied verbatim from the input (the match key)
- `title`
- `artist`
- `album`
- `genre`
- `year`
- `notes`

Rules:

- Output ONLY the JSON array. Nothing before or after it.
- Use an empty string `""` for any field you do not know.
- Do **not** invent facts. If unsure, leave the field `""`.
- Keep `filename` identical to the input, character for character.

### Example output

```json
[
  {"filename": "Aerosmith - Back In The Saddle - 10-16-2024.gp",
   "title": "Back in the Saddle", "artist": "Aerosmith",
   "album": "Rocks", "genre": "Hard Rock", "year": "1976",
   "notes": "Tuned down a half step"}
]
```
"""


def enrich_file_info(
    file_info: dict[str, Any], index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Attach merged metadata to a ``file_info`` dict under ``"meta"``.

    Precedence (lowest to highest): metadata parsed from the filename
    (``title``/``artist``/``year``), then any non-empty value from the local
    catalog, which always wins. ``album``/``genre``/``notes`` are present only
    when the catalog supplies them — they are never derived from the filename.

    The catalog's own key columns (``filename``/``file``/``name``/``stem``) are
    not copied into ``meta``; they are bookkeeping, not displayable metadata.
    """
    name = file_info.get("name", "")
    stem = file_info.get("stem", "")

    parsed = parse_filename_metadata(name or stem)
    indexed = index.get(name) or index.get(stem) or {}

    # Start from the filename parse, then let real catalog values override.
    meta: dict[str, Any] = dict(parsed)
    for key, value in indexed.items():
        if key in _KEY_ALIASES:
            continue
        if value not in (None, ""):
            meta[key] = value

    file_info = dict(file_info)
    if meta:
        file_info["meta"] = meta
    return file_info
