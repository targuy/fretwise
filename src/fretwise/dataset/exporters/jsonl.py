"""Export unified records to JSON Lines (one song per line)."""
from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path


def export(records: Iterable[dict], output_path: Path) -> int:
    """Write records to a JSONL file. Returns number of records written."""
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False))
            f.write("\n")
            count += 1
    return count
