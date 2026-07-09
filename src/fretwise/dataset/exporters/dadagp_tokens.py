"""Tokenize unified records into DadaGP-style event sequences.

Token format: note:s<N>:f<F>:lh:<finger>:nfx:<technique>
"""
from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

TICKS_PER_BEAT = 480


def _tokenize_event(event: dict, prev_abs_beat: float) -> tuple[list[str], float]:
    tokens: list[str] = []
    gap_ticks = int(round((event["abs_beat"] - prev_abs_beat) * TICKS_PER_BEAT))
    if gap_ticks > 0:
        tokens.append(f"wait:{gap_ticks}")

    if event.get("chord_symbol"):
        tokens.append(f"chord:{event['chord_symbol']}")

    if event.get("type") == "rest" or not event.get("notes"):
        tokens.append("rest")
        new_prev = event["abs_beat"] + event.get("duration_beats", 0.25)
        return tokens, new_prev

    for note in event["notes"]:
        s = note.get("string")
        f = note.get("fret")
        if s is None or f is None:
            p = note.get("pitch_midi")
            if p is not None:
                tokens.append(f"note:p{p}")
        else:
            tok = f"note:s{s}:f{f}"
            lh = note.get("left_hand_finger")
            if lh and lh != "open":
                tok += f":lh:{lh}"
            techs = note.get("techniques") or []
            for t in techs[:1]:
                tok += f":nfx:{t}"
            tokens.append(tok)

    new_prev = event["abs_beat"] + event.get("duration_beats", 0.25)
    return tokens, new_prev


def tokenize(record: dict) -> list[str]:
    """Tokenize one unified record into a flat list of tokens."""
    tokens: list[str] = ["song_start"]
    md = record.get("metadata", {}) or {}
    if md.get("artist"):
        tokens.append(f"artist:{md['artist']}")
    if md.get("tempo_bpm"):
        tokens.append(f"tempo:{int(md['tempo_bpm'])}")
    if md.get("time_signature"):
        n, d = md["time_signature"].split("/", 1)
        tokens.append(f"ts:{n}:{d}")
    if md.get("source_format"):
        tokens.append(f"src:{md['source_format']}")

    for track in record.get("tracks", []):
        if track.get("is_drum"):
            continue
        instr = track.get("instrument", "guitar")
        tokens.append(f"track:{instr}:strings:{track.get('string_count', 6)}")
        tuning = track.get("tuning") or []
        if tuning:
            tokens.append("tuning:" + ":".join(tuning))
        if track.get("capo"):
            tokens.append(f"capo:{track['capo']}")

        prev_measure = 0
        prev_abs = 0.0
        for event in track.get("events", []):
            if event.get("measure", 0) != prev_measure:
                tokens.append("new_measure")
                prev_measure = event["measure"]
            evt_toks, prev_abs = _tokenize_event(event, prev_abs)
            tokens.extend(evt_toks)
        tokens.append("track_end")

    tokens.append("song_end")
    return tokens


def export(records: Iterable[dict], output_path: Path) -> int:
    """Write tokenized records to a text file. Returns number of songs."""
    count = 0
    with open(output_path, "w", encoding="utf-8") as f:
        for rec in records:
            toks = tokenize(rec)
            for t in toks:
                f.write(t)
                f.write("\n")
            f.write("\n")
            count += 1
    return count


def build_vocab(token_files: list[Path]) -> dict[str, int]:
    """Build vocabulary from token files (token -> id)."""
    vocab: dict[str, int] = {}
    for fp in token_files:
        with open(fp, encoding="utf-8") as f:
            for line in f:
                tok = line.strip()
                if not tok:
                    continue
                if tok not in vocab:
                    vocab[tok] = len(vocab)
    return vocab
