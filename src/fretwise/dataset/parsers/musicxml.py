"""Parse MusicXML files (.musicxml, .mxl, .xml) into the unified schema.

Uses music21. Captures fingering (left hand), pluck (right hand PIMA),
string, fret, and standard guitar techniques.
"""
from __future__ import annotations

import hashlib
import logging
from pathlib import Path

log = logging.getLogger(__name__)

_MX_FINGER_NUMBER_MAP = {
    "0": "thumb", "1": "index", "2": "middle", "3": "ring", "4": "pinky",
    "5": "thumb", "T": "thumb", "t": "thumb", "p": "thumb",
}

_PLUCK_MAP = {
    "p": "p", "P": "p", "i": "i", "I": "i",
    "m": "m", "M": "m", "a": "a", "A": "a",
    "c": "c", "C": "c", "x": "pick",
}


def _midi_to_spn(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _extract_finger(art_value) -> str | None:
    if art_value is None:
        return None
    s = str(art_value).strip()
    if not s:
        return None
    s_first = s.split("-")[0]
    return _MX_FINGER_NUMBER_MAP.get(s_first)


def _extract_pluck(art_value) -> str | None:
    if art_value is None:
        return None
    return _PLUCK_MAP.get(str(art_value).strip())


def parse(path: Path) -> dict:
    """Parse a MusicXML file into unified schema."""
    try:
        from music21 import articulations, converter, harmony, stream
    except ImportError as exc:
        raise RuntimeError("music21 is not installed. Run: pip install music21") from exc

    score = converter.parse(str(path))

    src_bytes = path.read_bytes()
    song_id = "sha1:" + hashlib.sha1(src_bytes).hexdigest()

    md = score.metadata
    metadata = {
        "title": (md.title if md and md.title else path.stem) or path.stem,
        "artist": (md.composer if md and md.composer else None),
        "album": None,
        "year": None,
        "genre": None,
        "source_file": str(path),
        "source_format": path.suffix.lower().lstrip("."),
        "source_url": None,
        "license": None,
        "tempo_bpm": None,
        "time_signature": None,
        "key": None,
        "ingest_timestamp": None,
    }

    try:
        mm = score.flatten().getElementsByClass("MetronomeMark").first()
        if mm is not None and mm.number is not None:
            metadata["tempo_bpm"] = float(mm.number)
    except Exception:
        pass
    try:
        ts = score.flatten().getTimeSignatures()
        if ts:
            metadata["time_signature"] = f"{ts[0].numerator}/{ts[0].denominator}"
    except Exception:
        pass
    try:
        ks = score.flatten().getElementsByClass("KeySignature")
        if ks:
            metadata["key"] = str(ks[0])
    except Exception:
        pass

    tracks_out: list[dict] = []

    for track_idx, part in enumerate(score.parts):
        instr = part.getInstrument(returnDefault=True)
        instr_name = (getattr(instr, "instrumentName", "") or "").lower()
        if not any(k in instr_name for k in ["guitar", "bass", "ukulele", "banjo", "mandolin"]):
            continue

        tuning_midi = [40, 45, 50, 55, 59, 64]
        tuning_spn = [_midi_to_spn(v) for v in tuning_midi]
        string_count = 6
        if "bass" in instr_name:
            tuning_midi = [28, 33, 38, 43]
            tuning_spn = [_midi_to_spn(v) for v in tuning_midi]
            string_count = 4

        events_out: list[dict] = []
        abs_beat = 0.0

        measures = list(part.getElementsByClass(stream.Measure))
        for measure_idx, measure in enumerate(measures, start=1):
            for elem in measure.notesAndRests:
                duration_beats = float(elem.quarterLength)
                beat_in_measure = float(elem.offset)

                if elem.isRest:
                    events_out.append({
                        "measure": measure_idx,
                        "beat_in_measure": beat_in_measure,
                        "abs_beat": abs_beat + beat_in_measure,
                        "duration_beats": duration_beats,
                        "type": "rest",
                        "notes": [],
                        "chord_symbol": None,
                        "chord_diagram": None,
                    })
                    continue

                pitches = elem.notes if hasattr(elem, "notes") else [elem]
                notes_out: list[dict] = []

                arts = list(getattr(elem, "articulations", []))
                fingerings = [a for a in arts if isinstance(a, articulations.Fingering)]
                plucks = [a for a in arts if isinstance(a, articulations.FrettedPluck)]
                string_indications = [a for a in arts if isinstance(a, articulations.StringIndication)]
                fret_indications = [a for a in arts if isinstance(a, articulations.FretIndication)]

                for n_idx, n in enumerate(pitches):
                    string_num = None
                    fret_num = None
                    try:
                        string_num = int(string_indications[n_idx].number) if n_idx < len(string_indications) else None
                    except (ValueError, AttributeError):
                        string_num = None
                    try:
                        fret_num = int(fret_indications[n_idx].number) if n_idx < len(fret_indications) else None
                    except (ValueError, AttributeError):
                        fret_num = None

                    lh = _extract_finger(fingerings[n_idx].fingerNumber) if n_idx < len(fingerings) else None
                    rh = _extract_pluck(plucks[n_idx].fingerNumber) if n_idx < len(plucks) else None

                    techs = []
                    for a in arts:
                        cls = a.__class__.__name__.lower()
                        if "hammer" in cls:
                            techs.append("hammer")
                        if "pull" in cls:
                            techs.append("pull")
                        if "slide" in cls:
                            techs.append("slide")
                        if "harmonic" in cls:
                            techs.append("harmonic")
                        if "fretbend" in cls or cls == "bend":
                            techs.append("bend")
                        if "tap" in cls:
                            techs.append("tap")
                        if "snappizzicato" in cls:
                            techs.append("snap_pluck")
                    techs = sorted(set(techs))

                    notes_out.append({
                        "pitch_midi": int(n.pitch.midi) if hasattr(n, "pitch") else None,
                        "string": string_num,
                        "fret": fret_num,
                        "left_hand_finger": lh,
                        "right_hand_finger": rh,
                        "techniques": techs,
                        "velocity": int(getattr(n.volume, "velocity", None) or 95),
                        "tied_to_previous": (n.tie is not None and n.tie.type in ("continue", "stop")),
                    })

                chord_symbol = None
                chord_diagram = None
                harmonies = measure.getElementsByOffset(
                    beat_in_measure, beat_in_measure + 0.0001
                ).getElementsByClass(harmony.ChordSymbol)
                if harmonies:
                    h = harmonies[0]
                    chord_symbol = h.figure if h.figure else None
                    if hasattr(h, "frames") and h.frames:
                        frame = h.frames[0]
                        cd_frets = [None] * string_count
                        cd_fingers = [None] * string_count
                        for frame_note in getattr(frame, "frameNotes", []):
                            try:
                                s_idx = int(frame_note.string) - 1
                                cd_frets[s_idx] = int(frame_note.fret)
                                cd_fingers[s_idx] = _extract_finger(getattr(frame_note, "fingering", None))
                            except (ValueError, AttributeError, IndexError):
                                pass
                        chord_diagram = {
                            "name": chord_symbol or "",
                            "base_fret": int(getattr(frame, "firstFret", 1) or 1),
                            "frets": cd_frets,
                            "fingers": cd_fingers,
                            "barres": [],
                        }

                event_type = "chord" if len(notes_out) > 1 else "note"
                events_out.append({
                    "measure": measure_idx,
                    "beat_in_measure": beat_in_measure,
                    "abs_beat": abs_beat + beat_in_measure,
                    "duration_beats": duration_beats,
                    "type": event_type,
                    "notes": notes_out,
                    "chord_symbol": chord_symbol,
                    "chord_diagram": chord_diagram,
                })

            try:
                num = measure.timeSignature.numerator if measure.timeSignature else 4
                den = measure.timeSignature.denominator if measure.timeSignature else 4
                measure_length = num * 4.0 / den
            except Exception:
                measure_length = 4.0
            abs_beat += measure_length

        tracks_out.append({
            "track_id": track_idx,
            "name": part.partName or f"Part {track_idx}",
            "instrument": "bass" if "bass" in instr_name else "guitar",
            "midi_program": None,
            "string_count": string_count,
            "tuning": tuning_spn,
            "capo": 0,
            "is_drum": False,
            "events": events_out,
        })

    return {
        "song_id": song_id,
        "metadata": metadata,
        "tracks": tracks_out,
    }
