"""Local ``songs_metadata.json`` catalog reader + reconciliation.

FretWise's partitions library carries a companion metadata file,
``songs_metadata.json``, sitting next to the ``.gp`` score files in the
partitions directory. Each entry documents one song:

.. code-block:: json

    {"nom": "Highway To Hell", "artiste": "AC/DC", "genre": "Hard Rock",
     "type_guitare": "Gibson SG", "type_guitare_incertain": false,
     "difficulte": "Intermédiaire", "difficulte_source": "gp_analysis"}

The file carries no explicit filename key, so entries are matched to actual
``.gp`` files by normalizing ``artiste``/``nom`` into a comparable token set
and comparing it against each filename's token set (accents/case/punctuation
folded away, a trailing ``-MM-DD-YYYY`` date suffix stripped). This is
deliberately re-derived on every read rather than trusted from a persisted
key, because the library evolves (files renamed, added, removed) and a stale
key would silently drift from reality.

Reconciliation semantics (checked on every read, per the library's rule):

* A ``songs_metadata.json`` entry with no matching file on disk is **never
  displayed** — it describes a song FretWise no longer has.
* A ``.gp`` file with no matching entry is **still displayed**, with empty
  ``genre``/``type_guitare``/``difficulte`` — it just isn't documented yet.
"""
from __future__ import annotations

import json
import logging
import re
import unicodedata
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Filename of the catalog, expected alongside the score files.
CATALOG_FILENAME = "songs_metadata.json"

# songs_metadata.json fields copied into a file's "meta" dict. "nom"/"artiste"
# map onto the existing "title"/"artist" meta keys (shared with filename
# parsing) since they name the same thing; the others have no prior English
# equivalent in this codebase and are kept as-is.
_FIELD_MAP: tuple[tuple[str, str], ...] = (
    ("nom", "title"),
    ("artiste", "artist"),
    ("genre", "genre"),
    ("type_guitare", "type_guitare"),
    ("difficulte", "difficulte"),
)

# Trailing date stamp some filenames carry: "MM-DD-YYYY", optionally preceded
# by a "-" separator (mirrors songs_index._DATE_RE).
_DATE_SUFFIX_RE = re.compile(r"\s*-?\s*\d{1,2}-\d{1,2}-\d{4}\s*$")

# A song is matched to a file candidate only above this token-overlap ratio
# (fraction of the catalog entry's tokens found in the filename).
_FUZZY_MATCH_THRESHOLD = 0.7


def _tokens(text: str) -> frozenset[str]:
    """Fold accents/case/punctuation and split into a comparable token set."""
    folded = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii")
    return frozenset(re.findall(r"[a-z0-9]+", folded.lower()))


def _filename_tokens(filename: str) -> frozenset[str]:
    stem = _DATE_SUFFIX_RE.sub("", Path(filename).stem)
    return _tokens(stem)


def load_songs_metadata(json_path: str | Path) -> list[dict[str, Any]]:
    """Read ``songs_metadata.json`` from disk.

    Returns an empty list if the path is unset, missing, unreadable, or not a
    JSON array — never raises.
    """
    path = Path(json_path) if json_path else None
    if not path or not path.exists():
        return []
    try:
        return load_songs_metadata_from_text(path.read_text(encoding="utf-8-sig"))
    except OSError:
        return []


def load_songs_metadata_from_text(text: str) -> list[dict[str, Any]]:
    """Parse ``songs_metadata.json`` content given as in-memory text.

    Same forgiving semantics as :func:`load_songs_metadata`: any parse error
    or a top-level value that isn't a JSON array yields an empty list.
    """
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return []
    return data if isinstance(data, list) else []


def reconcile_songs_metadata(
    entries: list[dict[str, Any]], filenames: list[str]
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Match ``songs_metadata.json`` entries against the actual score filenames.

    Args:
        entries: Parsed ``songs_metadata.json`` rows (``nom``/``artiste``/
            ``genre``/``type_guitare``/``difficulte``).
        filenames: Names of the score files currently on disk.

    Returns:
        ``(index, missing, new_files)``:

        * ``index`` maps ``filename -> meta`` (the ``title``/``artist``/
          ``genre``/``type_guitare``/``difficulte`` fields to overlay onto
          that file's ``meta`` dict).
        * ``missing`` lists entries with no matching file (never displayed).
        * ``new_files`` lists filenames with no matching entry (displayed with
          empty catalog metadata).

        Each filename is claimed by at most one entry, so duplicate entries
        (the catalog can carry more than one row for the same song, e.g. two
        different recordings) never double-claim a single file.
    """
    file_tokens = {name: _filename_tokens(name) for name in filenames}
    unused = set(file_tokens)

    # Pass 1: exact token-set match, resolved only when a single unused file
    # carries that exact token set (handles the vast majority of entries).
    by_tokens: dict[frozenset[str], list[str]] = {}
    for name, tokens in file_tokens.items():
        by_tokens.setdefault(tokens, []).append(name)

    index: dict[str, dict[str, Any]] = {}
    missing: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []

    for entry in entries:
        key = _tokens(f"{entry.get('artiste', '')} {entry.get('nom', '')}")
        candidates = [n for n in by_tokens.get(key, ()) if n in unused]
        if len(candidates) == 1:
            name = candidates[0]
            index[name] = {dst: entry[src] for src, dst in _FIELD_MAP if src in entry}
            unused.discard(name)
        else:
            unresolved.append(entry)

    # Pass 2: fuzzy fallback for the residual — best token-overlap among the
    # files still unused, so a file already claimed exactly is never re-taken.
    for entry in unresolved:
        key = _tokens(f"{entry.get('artiste', '')} {entry.get('nom', '')}")
        if not key:
            missing.append(entry)
            continue
        best_name: str | None = None
        best_score = 0.0
        for name in unused:
            tokens = file_tokens[name]
            if not tokens:
                continue
            score = len(key & tokens) / len(key)
            if score > best_score:
                best_score, best_name = score, name
        if best_name is not None and best_score >= _FUZZY_MATCH_THRESHOLD:
            index[best_name] = {dst: entry[src] for src, dst in _FIELD_MAP if src in entry}
            unused.discard(best_name)
        else:
            missing.append(entry)

    new_files = sorted(unused)
    return index, missing, new_files


def log_reconciliation(
    missing: list[dict[str, Any]], new_files: list[str], matched: int
) -> None:
    """Emit a startup-time summary of the songs_metadata.json <-> disk check."""
    logger.info(
        "songs_metadata.json reconciliation: %d matched, %d entries with no file "
        "(hidden), %d files with no entry (shown, undocumented)",
        matched, len(missing), len(new_files),
    )
    if missing:
        sample = ", ".join(f"{e.get('artiste', '?')} - {e.get('nom', '?')}" for e in missing[:10])
        logger.warning("songs_metadata.json entries with no matching file: %s%s",
                        sample, ", ..." if len(missing) > 10 else "")
    if new_files:
        sample = ", ".join(new_files[:10])
        logger.info("Score files not yet in songs_metadata.json: %s%s",
                     sample, ", ..." if len(new_files) > 10 else "")
