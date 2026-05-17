"""Reader for the songs_index.tsv metadata file."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any


def load_index(tsv_path: str | Path) -> dict[str, dict[str, Any]]:
    """
    Read songs_index.tsv and return a dict keyed by filename stem or full name.

    Returns empty dict if the file is missing or malformed.
    """
    path = Path(tsv_path)
    if not path.exists():
        return {}

    result: dict[str, dict[str, Any]] = {}
    try:
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f, delimiter="\t")
            for row in reader:
                # Normalize: strip whitespace from values
                clean = {
                    k.strip(): (v.strip() if isinstance(v, str) else v)
                    for k, v in row.items()
                    if k
                }
                # Allow matching by filename with or without extension
                name = clean.get("filename") or clean.get("file") or clean.get("name") or ""
                if name:
                    result[name] = clean
                    # Also index by stem (no extension)
                    stem = Path(name).stem
                    if stem != name:
                        result[stem] = clean
    except (OSError, csv.Error):
        return {}

    return result


def enrich_file_info(
    file_info: dict[str, Any], index: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    """Add metadata from songs_index to a file_info dict."""
    name = file_info.get("name", "")
    stem = file_info.get("stem", "")
    meta = index.get(name) or index.get(stem) or {}
    if meta:
        file_info = dict(file_info)
        file_info["meta"] = meta
    return file_info
