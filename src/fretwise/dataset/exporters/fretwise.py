"""Bridge from unified harvester records to FretWise NoteEvent objects.

Converts unified records into one NoteEvent list per guitar track, ready
for the FretWise Viterbi-based fingering optimizer.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fretwise.models import Articulation, Dynamic, NoteEvent

logger = logging.getLogger(__name__)


_TECHNIQUE_PRIORITY: list[tuple[str, Any]] = [
    ("hammer_on", Articulation.HAMMER_ON),
    ("pull_off", Articulation.PULL_OFF),
    ("slide", Articulation.SLIDE),
    ("bend", Articulation.BEND),
    ("vibrato", Articulation.VIBRATO),
    ("harmonic", Articulation.HARMONIC),
]


def _pick_articulation(techniques: list[str]) -> Any:
    for tag, art in _TECHNIQUE_PRIORITY:
        if tag in techniques:
            return art
    return Articulation.NORMAL


def _velocity_to_dynamic(velocity: int | None) -> Any:
    if velocity is None:
        return Dynamic.MF
    if velocity < 32:
        return Dynamic.PP
    if velocity < 54:
        return Dynamic.P
    if velocity < 75:
        return Dynamic.MP
    if velocity < 96:
        return Dynamic.MF
    if velocity < 112:
        return Dynamic.F
    return Dynamic.FF


_LH_FINGER_TO_INT: dict[str, int] = {
    "open": -1, "thumb": 0, "index": 1, "middle": 2, "ring": 3, "pinky": 4,
}


def _build_noteevent(
    pitch_midi: int, onset: float, duration: float, tempo: float,
    techniques: list[str], velocity: int | None,
    string: int | None, fret: int | None,
    left_hand_finger: str | None, voice: int, measure: int, let_ring: bool,
) -> Any:
    articulation = _pick_articulation(techniques)
    dynamic = _velocity_to_dynamic(velocity)
    lh_hint = _LH_FINGER_TO_INT.get((left_hand_finger or "").lower())

    fields: dict[str, Any] = {
        "pitch": pitch_midi,
        "onset": round(float(onset), 6),
        "duration": round(float(duration), 6),
        "tempo": float(tempo) if tempo is not None else 120.0,
        "articulation": articulation,
        "dynamic": dynamic,
        "string_hint": string,
        "fret_hint": fret,
        "left_hand_finger_hint": lh_hint,
        "voice_hint": voice,
        "measure_index": measure,
        "let_ring": bool(let_ring),
    }

    import inspect

    sig = inspect.signature(NoteEvent)
    accepted = {k: v for k, v in fields.items() if k in sig.parameters}
    return NoteEvent(**accepted)


def unified_to_noteevents(record: dict[str, Any]) -> dict[int, list[Any]]:
    """Convert one unified record to {track_id -> list[NoteEvent]}."""
    out: dict[int, list[Any]] = {}
    for track in record.get("tracks", []):
        track_id = int(track.get("track_id", 0))
        events_out: list[Any] = []
        for ev in track.get("events", []):
            if ev.get("type") == "rest":
                continue
            measure = int(ev.get("measure", 1))
            onset = float(ev.get("abs_beat", 0.0))
            duration = float(ev.get("duration_beats", 1.0))
            voice = int(ev.get("voice", 0))
            tempo = float(ev.get("tempo_bpm", 120.0) or 120.0)
            for note in ev.get("notes", []):
                pitch = note.get("pitch_midi")
                if pitch is None:
                    continue
                techniques = list(note.get("techniques", []))
                let_ring = "let_ring" in techniques
                events_out.append(_build_noteevent(
                    pitch_midi=int(pitch), onset=onset, duration=duration,
                    tempo=tempo, techniques=techniques,
                    velocity=note.get("velocity"),
                    string=note.get("string"), fret=note.get("fret"),
                    left_hand_finger=note.get("left_hand_finger"),
                    voice=voice, measure=measure, let_ring=let_ring,
                ))
        events_out.sort(key=lambda e: (
            getattr(e, "onset", e.get("onset", 0.0) if isinstance(e, dict) else 0.0),
            getattr(e, "voice_hint", e.get("voice_hint", 0) if isinstance(e, dict) else 0) or 0,
        ))
        out[track_id] = events_out
    return out


def _serialize_noteevent(ev: Any) -> dict[str, Any]:
    if isinstance(ev, dict):
        return ev
    try:
        from dataclasses import asdict, is_dataclass
        if is_dataclass(ev):
            return _enums_to_strings(asdict(ev))
    except Exception:
        pass
    return _enums_to_strings({
        k: getattr(ev, k)
        for k in dir(ev)
        if not k.startswith("_") and not callable(getattr(ev, k))
    })


def _enums_to_strings(d: Any) -> Any:
    if isinstance(d, dict):
        return {k: _enums_to_strings(v) for k, v in d.items()}
    if isinstance(d, list):
        return [_enums_to_strings(x) for x in d]
    name = getattr(d, "name", None)
    if name is not None and not isinstance(d, str):
        return name
    return d


def process_jsonl(input_path: Path, output_dir: Path) -> int:
    """Process a JSONL of unified records -> per-song JSON of NoteEvents."""
    output_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    with input_path.open("r", encoding="utf-8") as f:
        for line_idx, line in enumerate(f, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError as exc:
                logger.warning("Skipping malformed line %d: %s", line_idx, exc)
                continue
            song_id = (record.get("song_id") or f"song_{line_idx}").replace(":", "_")
            tracks = unified_to_noteevents(record)
            for track_id, events in tracks.items():
                out_path = output_dir / f"{song_id}_track{track_id}.json"
                payload = {
                    "song_id": record.get("song_id"),
                    "track_id": track_id,
                    "metadata": record.get("metadata", {}),
                    "events": [_serialize_noteevent(e) for e in events],
                }
                out_path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False),
                    encoding="utf-8",
                )
            count += 1
    return count
