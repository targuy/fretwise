"""Parse MIDI files for guitar parts into the unified schema.

Supports hexaphonic channel-per-string detection, track-name string tags,
and fallback lowest-fret heuristic for string assignment.
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_STANDARD_TUNING_MIDI = [40, 45, 50, 55, 59, 64]
_STANDARD_TUNING_SPN = ["E2", "A2", "D3", "G3", "B3", "E4"]


def _midi_to_spn(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _try_hex_channel_assignment(note_events: list[dict]) -> tuple[bool, dict[int, int]]:
    channels_used = sorted({n["channel"] for n in note_events})
    if not (4 <= len(channels_used) <= 6):
        return False, {}
    by_chan: dict[int, list[int]] = {}
    for n in note_events:
        by_chan.setdefault(n["channel"], []).append(n["pitch"])
    medians = {c: sorted(v)[len(v) // 2] for c, v in by_chan.items()}
    sorted_chans = sorted(channels_used, key=lambda c: -medians[c])
    return True, {chan: i + 1 for i, chan in enumerate(sorted_chans)}


def _track_name_string(track_name: str) -> int | None:
    if not track_name:
        return None
    m = re.search(r"string\s*(\d)", track_name, re.IGNORECASE)
    if m:
        n = int(m.group(1))
        if 1 <= n <= 8:
            return n
    return None


def _assign_string_fret(pitch: int, tuning_midi: list[int]) -> tuple[int | None, int | None]:
    candidates = []
    for low_to_high_idx, open_pitch in enumerate(tuning_midi):
        fret = pitch - open_pitch
        if 0 <= fret <= 24:
            string_num = len(tuning_midi) - low_to_high_idx
            candidates.append((fret, string_num))
    if not candidates:
        return None, None
    fret, string_num = min(candidates, key=lambda t: t[0])
    return string_num, fret


def parse(path: Path) -> dict:
    """Parse a MIDI file."""
    try:
        import mido
    except ImportError as exc:
        raise RuntimeError("mido not installed. Run: pip install mido") from exc

    src_bytes = path.read_bytes()
    song_id = "sha1:" + hashlib.sha1(src_bytes).hexdigest()

    mid = mido.MidiFile(str(path))
    ticks_per_beat = mid.ticks_per_beat or 480

    tempo_bpm = 120.0
    tracks_out: list[dict] = []

    for track_idx, track in enumerate(mid.tracks):
        track_name = ""
        instrument_program = None
        for msg in track:
            if msg.type == "track_name":
                track_name = msg.name
                break
        for msg in track:
            if msg.type == "program_change":
                instrument_program = msg.program
                break
            if msg.type == "set_tempo":
                import mido as _mido
                tempo_bpm = _mido.tempo2bpm(msg.tempo)

        is_guitar = (
            (instrument_program is None and ("guitar" in track_name.lower() or "bass" in track_name.lower()))
            or (instrument_program is not None and (24 <= instrument_program <= 39))
        )
        if not is_guitar:
            continue

        is_bass = (instrument_program is not None and 32 <= instrument_program <= 39) or "bass" in track_name.lower()
        if is_bass:
            tuning_midi = [28, 33, 38, 43]
            tuning_spn = [_midi_to_spn(v) for v in tuning_midi]
        else:
            tuning_midi = list(_STANDARD_TUNING_MIDI)
            tuning_spn = list(_STANDARD_TUNING_SPN)

        abs_tick = 0
        active_notes: dict[tuple[int, int], dict] = {}
        note_events: list[dict] = []
        for msg in track:
            abs_tick += msg.time
            if msg.type == "note_on" and msg.velocity > 0:
                key = (msg.channel, msg.note)
                active_notes[key] = {
                    "start_tick": abs_tick, "channel": msg.channel,
                    "pitch": msg.note, "velocity": msg.velocity,
                }
            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.channel, msg.note)
                start = active_notes.pop(key, None)
                if start is None:
                    continue
                duration_ticks = abs_tick - start["start_tick"]
                note_events.append({
                    "start_tick": start["start_tick"],
                    "duration_ticks": duration_ticks,
                    "channel": start["channel"],
                    "pitch": start["pitch"],
                    "velocity": start["velocity"],
                })

        if not note_events:
            continue

        is_hex, chan_to_string = _try_hex_channel_assignment(note_events)
        track_name_str = _track_name_string(track_name)

        note_events.sort(key=lambda n: (n["start_tick"], n["pitch"]))

        events_out: list[dict] = []
        i = 0
        SIMULTANEOUS_TOLERANCE = ticks_per_beat // 16
        while i < len(note_events):
            anchor = note_events[i]
            group = [anchor]
            j = i + 1
            while j < len(note_events) and note_events[j]["start_tick"] - anchor["start_tick"] <= SIMULTANEOUS_TOLERANCE:
                group.append(note_events[j])
                j += 1
            i = j

            notes_out: list[dict] = []
            for n in group:
                if is_hex:
                    string_num = chan_to_string.get(n["channel"])
                    fret = None
                    if string_num is not None:
                        low_to_high_idx = len(tuning_midi) - string_num
                        if 0 <= low_to_high_idx < len(tuning_midi):
                            fret = n["pitch"] - tuning_midi[low_to_high_idx]
                            if fret < 0 or fret > 24:
                                fret = None
                                string_num = None
                elif track_name_str is not None:
                    string_num = track_name_str
                    low_to_high_idx = len(tuning_midi) - string_num
                    fret = n["pitch"] - tuning_midi[low_to_high_idx] if 0 <= low_to_high_idx < len(tuning_midi) else None
                else:
                    string_num, fret = _assign_string_fret(n["pitch"], tuning_midi)

                notes_out.append({
                    "pitch_midi": n["pitch"],
                    "string": string_num,
                    "fret": fret,
                    "left_hand_finger": None,
                    "right_hand_finger": None,
                    "techniques": [],
                    "velocity": n["velocity"],
                    "tied_to_previous": False,
                    "string_inferred": not is_hex and track_name_str is None,
                })

            abs_beat_val = anchor["start_tick"] / ticks_per_beat
            duration_beats = max(0.0625, max(n["duration_ticks"] for n in group) / ticks_per_beat)

            events_out.append({
                "measure": 1,
                "beat_in_measure": abs_beat_val % 4.0,
                "abs_beat": abs_beat_val,
                "duration_beats": duration_beats,
                "type": "chord" if len(notes_out) > 1 else "note",
                "notes": notes_out,
                "chord_symbol": None,
                "chord_diagram": None,
            })

        tracks_out.append({
            "track_id": track_idx,
            "name": track_name or f"Track {track_idx}",
            "instrument": "bass" if is_bass else "guitar",
            "midi_program": instrument_program,
            "string_count": len(tuning_midi),
            "tuning": tuning_spn,
            "capo": 0,
            "is_drum": False,
            "events": events_out,
        })

    metadata = {
        "title": path.stem,
        "artist": None, "album": None, "year": None, "genre": None,
        "source_file": str(path),
        "source_format": "midi",
        "source_url": None, "license": None,
        "tempo_bpm": tempo_bpm,
        "time_signature": None, "key": None, "ingest_timestamp": None,
    }

    return {"song_id": song_id, "metadata": metadata, "tracks": tracks_out}
