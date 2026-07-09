"""Unification, validation and post-processing for unified records.

After raw parsing, every record must pass through unify() which fills
defaults, validates finger values, adds ingest_timestamp, sorts events.
"""
from __future__ import annotations

import datetime as dt
import logging
from collections.abc import Iterable, Iterator

log = logging.getLogger(__name__)

VALID_LH_FINGERS = {"open", "thumb", "index", "middle", "ring", "pinky", "barre", None}
VALID_RH_FINGERS = {"p", "i", "m", "a", "c", "pick", None}


def _ensure_metadata(record: dict, *, ingest_ts: str) -> None:
    md = record.setdefault("metadata", {})
    md.setdefault("title", record.get("metadata", {}).get("title") or "untitled")
    md.setdefault("artist", None)
    md.setdefault("album", None)
    md.setdefault("year", None)
    md.setdefault("genre", None)
    md.setdefault("source_file", None)
    md.setdefault("source_format", "unknown")
    md.setdefault("source_url", None)
    md.setdefault("license", None)
    md.setdefault("tempo_bpm", None)
    md.setdefault("time_signature", None)
    md.setdefault("key", None)
    md["ingest_timestamp"] = ingest_ts


def _validate_note(note: dict) -> None:
    if note.get("left_hand_finger") not in VALID_LH_FINGERS:
        note["left_hand_finger"] = None
    if note.get("right_hand_finger") not in VALID_RH_FINGERS:
        note["right_hand_finger"] = None
    if not isinstance(note.get("techniques"), list):
        note["techniques"] = []


def _validate_track(track: dict) -> None:
    track.setdefault("name", f"Track {track.get('track_id', 0)}")
    track.setdefault("instrument", "guitar")
    track.setdefault("midi_program", None)
    track.setdefault("string_count", len(track.get("tuning", []) or []) or 6)
    track.setdefault("tuning", ["E2", "A2", "D3", "G3", "B3", "E4"])
    track.setdefault("capo", 0)
    track.setdefault("is_drum", False)
    track.setdefault("events", [])

    for event in track["events"]:
        event.setdefault("measure", 1)
        event.setdefault("beat_in_measure", 0.0)
        event.setdefault("abs_beat", 0.0)
        event.setdefault("duration_beats", 0.25)
        event.setdefault("type", "rest")
        event.setdefault("notes", [])
        event.setdefault("chord_symbol", None)
        event.setdefault("chord_diagram", None)
        for note in event["notes"]:
            _validate_note(note)

    track["events"].sort(key=lambda e: e.get("abs_beat", 0.0))


def unify(record: dict, *, ingest_ts: str | None = None) -> dict:
    """Apply defaults, validate, sort. Mutates and returns the record."""
    ts = ingest_ts or dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    _ensure_metadata(record, ingest_ts=ts)
    for track in record.get("tracks", []):
        _validate_track(track)
    return record


def unify_many(records: Iterable[dict], *, ingest_ts: str | None = None) -> Iterator[dict]:
    ts = ingest_ts or dt.datetime.utcnow().isoformat(timespec="seconds") + "Z"
    for rec in records:
        if rec is None:
            continue
        if isinstance(rec, list):
            for r in rec:
                yield unify(r, ingest_ts=ts)
        else:
            yield unify(rec, ingest_ts=ts)


def stats(records: Iterable[dict]) -> dict:
    """Quick summary of a collection of unified records."""
    n_songs = 0
    n_tracks = 0
    n_events = 0
    n_notes = 0
    n_notes_with_lh = 0
    n_notes_with_rh = 0
    by_format: dict[str, int] = {}
    by_instrument: dict[str, int] = {}
    for rec in records:
        n_songs += 1
        fmt = rec.get("metadata", {}).get("source_format", "unknown")
        by_format[fmt] = by_format.get(fmt, 0) + 1
        for track in rec.get("tracks", []):
            n_tracks += 1
            ins = track.get("instrument", "guitar")
            by_instrument[ins] = by_instrument.get(ins, 0) + 1
            for evt in track.get("events", []):
                n_events += 1
                for note in evt.get("notes", []):
                    n_notes += 1
                    if note.get("left_hand_finger") is not None:
                        n_notes_with_lh += 1
                    if note.get("right_hand_finger") is not None:
                        n_notes_with_rh += 1
    return {
        "n_songs": n_songs, "n_tracks": n_tracks,
        "n_events": n_events, "n_notes": n_notes,
        "n_notes_with_lh_finger": n_notes_with_lh,
        "n_notes_with_rh_finger": n_notes_with_rh,
        "pct_lh_annotated": round(100 * n_notes_with_lh / max(1, n_notes), 2),
        "pct_rh_annotated": round(100 * n_notes_with_rh / max(1, n_notes), 2),
        "by_source_format": by_format,
        "by_instrument": by_instrument,
    }
