"""Export unified records to Parquet (flattened per-note, denormalized).

One row = one note. Song/track metadata duplicated on each row.
Optimal for big-scale ML loading via polars / pyarrow / HF datasets.
"""
from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path


def _flatten(records: Iterable[dict]) -> Iterator[dict]:
    for rec in records:
        md = rec.get("metadata", {}) or {}
        sid = rec.get("song_id")
        for track in rec.get("tracks", []):
            t_id = track.get("track_id")
            t_name = track.get("name")
            t_instr = track.get("instrument")
            t_tuning = track.get("tuning")
            t_capo = track.get("capo")
            t_string_count = track.get("string_count")
            for evt in track.get("events", []):
                base = {
                    "song_id": sid,
                    "title": md.get("title"),
                    "artist": md.get("artist"),
                    "source_format": md.get("source_format"),
                    "license": md.get("license"),
                    "tempo_bpm": md.get("tempo_bpm"),
                    "key": md.get("key"),
                    "track_id": t_id,
                    "track_name": t_name,
                    "instrument": t_instr,
                    "tuning": t_tuning,
                    "capo": t_capo,
                    "string_count": t_string_count,
                    "measure": evt.get("measure"),
                    "abs_beat": evt.get("abs_beat"),
                    "duration_beats": evt.get("duration_beats"),
                    "event_type": evt.get("type"),
                    "chord_symbol": evt.get("chord_symbol"),
                }
                if not evt.get("notes"):
                    yield {**base, "pitch_midi": None, "string": None,
                           "fret": None, "left_hand_finger": None,
                           "right_hand_finger": None, "techniques": [],
                           "velocity": None}
                    continue
                for note in evt["notes"]:
                    yield {**base,
                           "pitch_midi": note.get("pitch_midi"),
                           "string": note.get("string"),
                           "fret": note.get("fret"),
                           "left_hand_finger": note.get("left_hand_finger"),
                           "right_hand_finger": note.get("right_hand_finger"),
                           "techniques": note.get("techniques") or [],
                           "velocity": note.get("velocity")}


def export(records: Iterable[dict], output_path: Path) -> int:
    """Write records to Parquet. Returns number of rows written."""
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:
        raise RuntimeError("pyarrow not installed. Run: pip install pyarrow") from exc

    rows = list(_flatten(records))
    if not rows:
        return 0

    table = pa.Table.from_pylist(rows)
    pq.write_table(table, output_path, compression="zstd")
    return len(rows)
