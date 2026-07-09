"""Parse chord databases (CSV like UCI Guitar Chords, or JSON chord libraries)
into the unified schema as collections of chord-diagram-only records.
"""
from __future__ import annotations

import csv
import hashlib
import json
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_FINGER_INT_MAP = {0: "open", 1: "index", 2: "middle", 3: "ring", 4: "pinky", 5: "thumb"}


def _finger_from_int(v) -> str | None:
    try:
        i = int(v)
    except (ValueError, TypeError):
        return None
    return _FINGER_INT_MAP.get(i)


def _parse_csv(path: Path) -> list[dict]:
    records = []
    with open(path, encoding="utf-8", errors="replace") as f:
        reader = csv.DictReader(f)

        name_col = None
        for c in reader.fieldnames or []:
            if c.lower() in {"chord", "chord_name", "name"}:
                name_col = c
                break

        fret_cols = []
        finger_cols = []
        for c in reader.fieldnames or []:
            lc = c.lower()
            if any(k in lc for k in ("fret", "string")) and "finger" not in lc:
                fret_cols.append(c)
            elif "finger" in lc:
                finger_cols.append(c)

        f.seek(0)
        next(f)
        reader = csv.DictReader(f, fieldnames=reader.fieldnames)

        for row_idx, row in enumerate(reader):
            chord_name = row.get(name_col, "") if name_col else f"chord_{row_idx}"
            chord_name = (chord_name or "").strip()

            frets: list[int | None] = []
            for fc in fret_cols[:6]:
                raw = (row.get(fc) or "").strip().lower()
                if raw in {"x", "-", "", "mute", "muted"}:
                    frets.append(None)
                else:
                    try:
                        frets.append(int(raw))
                    except ValueError:
                        frets.append(None)
            while len(frets) < 6:
                frets.append(None)
            frets = frets[:6]

            fingers: list[str | None] = []
            for fc in finger_cols[:6]:
                raw = (row.get(fc) or "").strip()
                fingers.append(_finger_from_int(raw))
            while len(fingers) < 6:
                fingers.append(None)
            fingers = fingers[:6]

            chord_id = "csv:" + hashlib.sha1(f"{chord_name}{frets}{fingers}".encode()).hexdigest()[:16]
            records.append({
                "song_id": chord_id,
                "metadata": {
                    "title": chord_name, "artist": None, "album": None,
                    "year": None, "genre": "chord_library",
                    "source_file": str(path), "source_format": "chord_db_csv",
                    "source_url": None,
                    "license": "open" if "uci" in path.name.lower() else None,
                    "tempo_bpm": None, "time_signature": None, "key": None,
                    "ingest_timestamp": None,
                },
                "tracks": [{
                    "track_id": 0, "name": chord_name, "instrument": "guitar",
                    "midi_program": 25, "string_count": 6,
                    "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
                    "capo": 0, "is_drum": False,
                    "events": [{
                        "measure": 1, "beat_in_measure": 0.0, "abs_beat": 0.0,
                        "duration_beats": 4.0, "type": "chord",
                        "notes": [], "chord_symbol": chord_name,
                        "chord_diagram": {
                            "name": chord_name, "base_fret": 1,
                            "frets": frets, "fingers": fingers, "barres": [],
                        },
                    }],
                }],
            })
    return records


def _parse_json(path: Path) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, dict) and "chords" in data:
        items = data["chords"]
    elif isinstance(data, list):
        items = data
    else:
        log.warning("Unknown JSON chord library structure in %s", path)
        return []

    records = []
    for idx, item in enumerate(items):
        if not isinstance(item, dict):
            continue
        name = item.get("name", f"chord_{idx}")
        base_fret = int(item.get("base_fret", item.get("baseFret", 1)) or 1)
        frets_raw = item.get("frets", [None] * 6)
        frets = []
        for fv in frets_raw:
            if fv in (None, "x", "X", -1, "-"):
                frets.append(None)
            else:
                try:
                    frets.append(int(fv))
                except (ValueError, TypeError):
                    frets.append(None)

        fingers_raw = item.get("fingers", item.get("fingering", [None] * 6))
        fingers = [
            _finger_from_int(f) if isinstance(f, (int, str)) and str(f).strip().lstrip("-").isdigit() else None
            for f in fingers_raw
        ]

        barres = item.get("barres", [])
        chord_id = "json:" + hashlib.sha1(f"{name}{frets}{fingers}{base_fret}".encode()).hexdigest()[:16]

        records.append({
            "song_id": chord_id,
            "metadata": {
                "title": name, "artist": None, "album": None, "year": None,
                "genre": "chord_library", "source_file": str(path),
                "source_format": "chord_db_json", "source_url": None,
                "license": item.get("license"),
                "tempo_bpm": None, "time_signature": None, "key": None,
                "ingest_timestamp": None,
            },
            "tracks": [{
                "track_id": 0, "name": name, "instrument": "guitar",
                "midi_program": 25, "string_count": 6,
                "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
                "capo": 0, "is_drum": False,
                "events": [{
                    "measure": 1, "beat_in_measure": 0.0, "abs_beat": 0.0,
                    "duration_beats": 4.0, "type": "chord", "notes": [],
                    "chord_symbol": name,
                    "chord_diagram": {
                        "name": name, "base_fret": base_fret,
                        "frets": frets, "fingers": fingers, "barres": barres,
                    },
                }],
            }],
        })
    return records


def parse(path: Path) -> list[dict]:
    """Returns a LIST of records (chord DBs are multi-record)."""
    if path.suffix.lower() == ".csv":
        return _parse_csv(path)
    if path.suffix.lower() == ".json":
        return _parse_json(path)
    raise ValueError(f"parse_chord_db doesn't support {path.suffix}")
