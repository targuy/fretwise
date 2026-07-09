"""Parse ASCII tablature files into the unified schema.

Best-effort: ASCII tabs are noisy. Output records have left_hand_finger=null
(ASCII never encodes finger info). Detects tuning from header (Drop D,
DADGAD, Open G, half step down).
"""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

_STANDARD_TUNING_MIDI = [40, 45, 50, 55, 59, 64]
_STANDARD_TUNING_SPN = ["E2", "A2", "D3", "G3", "B3", "E4"]

_LINE_TO_STRING = {
    "e": 1, "E": 6, "B": 2, "b": 2,
    "G": 3, "g": 3, "D": 4, "d": 4, "A": 5, "a": 5,
}

_FRET_NUM_RE = re.compile(r"(\d{1,2})")
_TECHNIQUE_CHARS = {
    "h": "hammer", "p": "pull", "/": "slide_up", "\\": "slide_down",
    "b": "bend", "~": "vibrato", "x": "mute", "t": "tap", "*": "harmonic",
}


def _detect_tuning_from_header(lines: list[str]) -> tuple[list[int], list[str]]:
    text = " ".join(lines[:20]).lower()
    if "drop d" in text or "dadgbe" in text:
        return [38, 45, 50, 55, 59, 64], ["D2", "A2", "D3", "G3", "B3", "E4"]
    if "dadgad" in text:
        return [38, 45, 50, 55, 57, 62], ["D2", "A2", "D3", "G3", "A3", "D4"]
    if "open g" in text:
        return [38, 43, 50, 55, 59, 62], ["D2", "G2", "D3", "G3", "B3", "D4"]
    if "half step down" in text or "eb tuning" in text:
        return [m - 1 for m in _STANDARD_TUNING_MIDI], ["Eb2", "Ab2", "Db3", "Gb3", "Bb3", "Eb4"]
    return list(_STANDARD_TUNING_MIDI), list(_STANDARD_TUNING_SPN)


def _midi_to_spn(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _is_tab_line(line: str) -> tuple[bool, int]:
    line_s = line.lstrip()
    if len(line_s) < 2:
        return False, -1
    first_char = line_s[0]
    if first_char not in "eEBbGgDdAa":
        return False, -1
    if len(line_s) > 1 and line_s[1] not in "|-:":
        return False, -1
    if first_char == "e":
        return True, 1
    if first_char == "E":
        return True, 6
    return True, _LINE_TO_STRING[first_char]


def _detect_tab_blocks(lines: list[str]) -> list[list[tuple[int, str]]]:
    blocks: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    for line in lines:
        ok, sn = _is_tab_line(line)
        if ok:
            current.append((sn, line))
        else:
            if len(current) >= 4:
                blocks.append(current)
            current = []
    if len(current) >= 4:
        blocks.append(current)
    return blocks


def _parse_block(block: list[tuple[int, str]], tuning_midi: list[int]) -> list[dict]:
    aligned: list[tuple[int, str]] = []
    for sn, line in block:
        idx_pipe = max(line.find("|"), line.find(":"))
        if idx_pipe < 0:
            idx_pipe = 1
        aligned.append((sn, line[idx_pipe + 1:]))

    if not aligned:
        return []

    max_len = max(len(b) for _, b in aligned)
    events: list[dict] = []

    col = 0
    last_event_col = -2
    while col < max_len:
        notes_at_col: list[dict] = []
        for sn, body in aligned:
            if col >= len(body):
                continue
            ch = body[col]
            if ch.isdigit():
                if col + 1 < len(body) and body[col + 1].isdigit():
                    fret_str = body[col: col + 2]
                else:
                    if col > 0 and body[col - 1].isdigit():
                        continue
                    fret_str = ch
                try:
                    fret = int(fret_str)
                except ValueError:
                    continue
                low_to_high_idx = 6 - sn
                if 0 <= low_to_high_idx < len(tuning_midi):
                    pitch_midi = tuning_midi[low_to_high_idx] + fret
                else:
                    pitch_midi = None
                techs = []
                for adj in (col - 1, col + len(fret_str)):
                    if 0 <= adj < len(body) and body[adj] in _TECHNIQUE_CHARS:
                        techs.append(_TECHNIQUE_CHARS[body[adj]])
                notes_at_col.append({
                    "pitch_midi": pitch_midi, "string": sn, "fret": fret,
                    "left_hand_finger": None, "right_hand_finger": None,
                    "techniques": techs, "velocity": 95, "tied_to_previous": False,
                })
        if notes_at_col and col - last_event_col >= 1:
            events.append({
                "measure": 1, "beat_in_measure": float(col) * 0.25,
                "abs_beat": float(col) * 0.25, "duration_beats": 0.25,
                "type": "chord" if len(notes_at_col) > 1 else "note",
                "notes": notes_at_col, "chord_symbol": None, "chord_diagram": None,
            })
            last_event_col = col
        col += 1
    return events


def parse(path: Path) -> dict:
    """Parse an ASCII tab file."""
    src_bytes = path.read_bytes()
    song_id = "sha1:" + hashlib.sha1(src_bytes).hexdigest()

    try:
        text = src_bytes.decode("utf-8")
    except UnicodeDecodeError:
        text = src_bytes.decode("latin-1", errors="replace")
    lines = text.splitlines()

    header_lines = [ln for ln in lines[:15] if ln.strip()]
    title = header_lines[0].strip() if header_lines else path.stem
    artist = header_lines[1].strip() if len(header_lines) > 1 else None

    tuning_midi, tuning_spn = _detect_tuning_from_header(lines)

    blocks = _detect_tab_blocks(lines)
    all_events: list[dict] = []
    abs_beat_offset = 0.0
    for block in blocks:
        evs = _parse_block(block, tuning_midi)
        for e in evs:
            e["abs_beat"] += abs_beat_offset
        if evs:
            all_events.extend(evs)
            abs_beat_offset = evs[-1]["abs_beat"] + evs[-1]["duration_beats"] + 0.5

    metadata = {
        "title": title, "artist": artist, "album": None, "year": None,
        "genre": None, "source_file": str(path), "source_format": "ascii_tab",
        "source_url": None, "license": None, "tempo_bpm": None,
        "time_signature": None, "key": None, "ingest_timestamp": None,
    }

    return {
        "song_id": song_id, "metadata": metadata,
        "tracks": [{
            "track_id": 0, "name": "ASCII Tab", "instrument": "guitar",
            "midi_program": 25, "string_count": 6, "tuning": tuning_spn,
            "capo": 0, "is_drum": False, "events": all_events,
        }],
    }
