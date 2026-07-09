"""GuitarPro file parser adapter — all versions (.gp3/.gp4/.gp5/.gpx/.gp).

Legacy (.gp3/.gp4/.gp5) via PyGuitarPro library.
Modern (.gp/.gpx) via native ZIP/XML parsing of Content/score.gpif.

String numbering: unified schema uses 1 = highest pitch (thinnest), 6 = lowest.
GPIF uses 0 = lowest; conversion via _gpif_string_to_unified().
"""

from __future__ import annotations

import hashlib
import logging
import struct
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from typing import Any

from .base import BaseParser, ParseError, UnsupportedFormatError

logger = logging.getLogger(__name__)

_GP_LEGACY_EXTENSIONS: frozenset[str] = frozenset({".gp3", ".gp4", ".gp5"})
_GP_MODERN_EXTENSIONS: frozenset[str] = frozenset({".gp", ".gpx"})
_SUPPORTED_EXTENSIONS: frozenset[str] = _GP_LEGACY_EXTENSIONS | _GP_MODERN_EXTENSIONS

_GUITAR_MIDI_PROGRAMS: frozenset[int] = frozenset(range(24, 32))
_BASS_MIDI_PROGRAMS: frozenset[int] = frozenset(range(32, 40))

_STANDARD_TUNING_LOW_TO_HIGH: list[int] = [40, 45, 50, 55, 59, 64]

_NOTE_TYPE_NORMAL: int = 1

_NOTE_VALUE_BEATS: dict[str, float] = {
    "Long": 16.0, "DoubleWhole": 8.0, "Whole": 4.0, "Half": 2.0,
    "Quarter": 1.0, "Eighth": 0.5, "16th": 0.25, "32nd": 0.125, "64th": 0.0625,
}

_GUITAR_NAME_KEYWORDS = [
    "guitar", "guit", "gtr", "chitarra", "guitare", "gitarre",
    "lead", "rhythm", "riff", "solo",
]
_BASS_NAME_KEYWORDS = ["bass", "basse", "bajo"]
_DRUM_NAME_KEYWORDS = ["drum", "perc", "batterie", "drums", "percussion"]


def _midi_to_spn(midi: int) -> str:
    names = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
    return f"{names[midi % 12]}{midi // 12 - 1}"


def _hash_song_id(path: Path) -> str:
    h = hashlib.sha1()
    try:
        with path.open("rb") as f:
            h.update(f.read(1024 * 1024))
    except OSError:
        h.update(path.name.encode("utf-8"))
    return f"sha1:{h.hexdigest()}"


class GuitarProAdapter(BaseParser):

    def supports(self, path: Path) -> bool:
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, path: Path) -> dict[str, Any]:
        if not self.supports(path):
            raise UnsupportedFormatError(
                f"GuitarProAdapter does not support '{path.suffix}'. "
                f"Supported: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        ext = path.suffix.lower()
        if ext in _GP_LEGACY_EXTENSIONS:
            return _parse_legacy_gp(path)
        if ext == ".gp":
            return _parse_gpif_native(path)
        if ext == ".gpx":
            try:
                return _parse_legacy_gp(path)
            except ParseError:
                logger.info("PyGuitarPro failed on '%s'; trying GPIF native parse.", path)
                return _parse_gpif_native(path)
        raise UnsupportedFormatError(f"unhandled extension: {ext}")


# ===========================================================================
# Legacy path: GP3 / GP4 / GP5 via PyGuitarPro
# ===========================================================================


def _safe_import_guitarpro() -> Any:
    try:
        import guitarpro
        return guitarpro
    except ImportError as exc:
        raise ParseError(
            "pyguitarpro is required for .gp3/.gp4/.gp5 parsing. "
            "Install with: pip install pyguitarpro"
        ) from exc


def _parse_legacy_gp(path: Path) -> dict[str, Any]:
    gp = _safe_import_guitarpro()
    try:
        song = gp.parse(str(path))
    except Exception as exc:
        raise ParseError(f"PyGuitarPro failed on '{path}': {exc}") from exc

    tracks_out: list[dict[str, Any]] = []
    for track_idx, track in enumerate(song.tracks):
        if track.isPercussionTrack:
            continue
        if not _is_guitar_track_legacy(track):
            continue
        record = _build_legacy_track_record(song, track, track_idx)
        if record is not None:
            tracks_out.append(record)

    return {
        "song_id": _hash_song_id(path),
        "metadata": _build_legacy_metadata(song, path),
        "tracks": tracks_out,
    }


def _is_guitar_track_legacy(track: Any) -> bool:
    """Filter legacy GP tracks to guitar only (exclude bass, drums)."""
    midi_prog = getattr(getattr(track, "channel", None), "instrument", -1)
    if isinstance(midi_prog, int):
        if midi_prog in _GUITAR_MIDI_PROGRAMS:
            return True
        if midi_prog in _BASS_MIDI_PROGRAMS:
            return False

    name = (getattr(track, "name", "") or "").lower()
    if any(kw in name for kw in _DRUM_NAME_KEYWORDS):
        return False
    if any(kw in name for kw in _BASS_NAME_KEYWORDS):
        return False
    if any(kw in name for kw in _GUITAR_NAME_KEYWORDS):
        return True

    # Fallback: 6-7 strings with standard-ish tuning (lowest > 35 = not bass)
    if hasattr(track, "strings") and 6 <= len(track.strings) <= 8:
        pitches = [s.value for s in track.strings]
        if min(pitches) >= 35:
            return True

    return False


def _build_legacy_metadata(song: Any, path: Path) -> dict[str, Any]:
    return {
        "title": (getattr(song, "title", "") or "").strip() or None,
        "artist": (getattr(song, "artist", "") or "").strip() or None,
        "album": (getattr(song, "album", "") or "").strip() or None,
        "transcriber": (getattr(song, "tab", "") or "").strip() or None,
        "source_format": path.suffix.lower().lstrip("."),
        "source_path": path.name,
        "tempo_bpm": float(song.tempo) if getattr(song, "tempo", None) else None,
        "license": None,
        "schema_version": "1.0.0",
    }


def _build_legacy_track_record(
    song: Any, track: Any, track_idx: int
) -> dict[str, Any] | None:
    if not track.strings:
        return None
    strings_sorted = sorted(track.strings, key=lambda s: s.number)
    pitches_high_to_low = [s.value for s in strings_sorted]
    pitches_low_to_high = list(reversed(pitches_high_to_low))
    tuning = [_midi_to_spn(p) for p in pitches_low_to_high]

    events = _walk_legacy_measures(song, track)
    return {
        "track_id": track_idx,
        "track_name": (getattr(track, "name", "") or "").strip() or None,
        "instrument": "guitar",
        "midi_program": getattr(getattr(track, "channel", None), "instrument", -1),
        "tuning": tuning,
        "capo": int(getattr(track, "offset", 0) or 0),
        "events": events,
    }


def _walk_legacy_measures(song: Any, track: Any) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    abs_beat = 0.0
    current_tempo = float(song.tempo)

    for measure_idx, measure in enumerate(track.measures, start=1):
        current_tempo = _legacy_measure_tempo(measure, current_tempo)
        measure_onset = abs_beat
        nominal_duration = _legacy_measure_nominal_duration(measure)

        for voice_idx, voice in enumerate(measure.voices):
            beat_onset = measure_onset
            for beat in voice.beats:
                beat_duration = _legacy_duration_in_beats(beat.duration)
                chord_symbol = _legacy_beat_chord_name(beat)
                notes_in_beat = list(beat.notes)

                if not notes_in_beat:
                    events.append(_make_rest_event(
                        measure_idx, beat_onset, beat_duration,
                        voice_idx, current_tempo, chord_symbol,
                    ))
                    beat_onset += beat_duration
                    continue

                normal_notes = [
                    n for n in notes_in_beat
                    if getattr(n.type, "value", int(n.type)) == _NOTE_TYPE_NORMAL
                ]
                if not normal_notes:
                    beat_onset += beat_duration
                    continue

                unified_notes = [_legacy_note_to_unified(n, track) for n in normal_notes]
                event_type = "chord" if len(unified_notes) > 1 else "note"
                events.append({
                    "measure": measure_idx,
                    "abs_beat": round(beat_onset, 6),
                    "duration_beats": round(beat_duration, 6),
                    "type": event_type,
                    "voice": voice_idx,
                    "tempo_bpm": current_tempo,
                    "chord_symbol": chord_symbol,
                    "chord_diagram": None,
                    "notes": unified_notes,
                })
                beat_onset += beat_duration

            voice_duration = beat_onset - measure_onset
            if voice_duration > 0.0:
                nominal_duration = max(nominal_duration, voice_duration)

        abs_beat = measure_onset + nominal_duration

    events.sort(key=lambda e: (e["abs_beat"], e["voice"]))
    return events


def _make_rest_event(
    measure_idx: int, abs_beat: float, duration: float,
    voice: int, tempo: float, chord_symbol: str | None,
) -> dict[str, Any]:
    return {
        "measure": measure_idx,
        "abs_beat": round(abs_beat, 6),
        "duration_beats": round(duration, 6),
        "type": "rest",
        "voice": voice,
        "tempo_bpm": tempo,
        "chord_symbol": chord_symbol,
        "chord_diagram": None,
        "notes": [],
    }


def _legacy_note_to_unified(note: Any, track: Any) -> dict[str, Any]:
    open_pitch = _legacy_open_pitch_for_string(track, note.string)
    pitch_midi = open_pitch + int(note.value) if open_pitch is not None else None

    return {
        "pitch_midi": pitch_midi,
        "string": int(note.string),
        "fret": int(note.value),
        "left_hand_finger": _legacy_left_hand_finger(note),
        "right_hand_finger": None,
        "techniques": _legacy_techniques(note),
        "velocity": int(getattr(note, "velocity", 95) or 95),
        "tied_to_previous": False,
    }


def _legacy_open_pitch_for_string(track: Any, string_number: int) -> int | None:
    for s in track.strings:
        if s.number == string_number:
            return int(s.value)
    return None


def _legacy_left_hand_finger(note: Any) -> str | None:
    fingering = getattr(getattr(note, "effect", None), "leftHandFinger", None)
    if fingering is None:
        return None
    value = getattr(fingering, "value", None)
    if value is None:
        return None
    mapping = {-1: "open", 0: "thumb", 1: "index", 2: "middle", 3: "ring", 4: "pinky"}
    return mapping.get(int(value))


def _legacy_techniques(note: Any) -> list[str]:
    effect = getattr(note, "effect", None)
    if effect is None:
        return []
    tags: list[str] = []
    if getattr(effect, "hammer", False):
        tags.append("hammer_on")
    if getattr(effect, "pullOff", False):
        tags.append("pull_off")
    if getattr(effect, "slides", None):
        tags.append("slide")
    if getattr(effect, "vibrato", False):
        tags.append("vibrato")
    if getattr(effect, "bend", None) is not None:
        tags.append("bend")
    if getattr(effect, "harmonic", None) is not None:
        tags.append("harmonic")
    if getattr(effect, "palmMute", False):
        tags.append("palm_mute")
    if getattr(effect, "letRing", False):
        tags.append("let_ring")
    if getattr(effect, "ghostNote", False):
        tags.append("ghost")
    return tags


def _legacy_beat_chord_name(beat: Any) -> str | None:
    chord = getattr(getattr(beat, "effect", None), "chord", None)
    if chord is None:
        return None
    return (getattr(chord, "name", "") or "").strip() or None


def _legacy_duration_in_beats(duration: Any) -> float:
    beats = 4.0 / duration.value
    if getattr(duration, "isDotted", False):
        beats *= 1.5
    elif getattr(duration, "isDoubleDotted", False):
        beats *= 1.75
    tuplet = getattr(duration, "tuplet", None)
    if tuplet is not None and tuplet.enters != tuplet.times:
        beats = beats * tuplet.times / tuplet.enters
    return beats


def _legacy_measure_tempo(measure: Any, fallback: float) -> float:
    try:
        return float(measure.header.tempo.value)
    except AttributeError:
        return fallback


def _legacy_measure_nominal_duration(measure: Any) -> float:
    try:
        ts = measure.header.timeSignature
        numerator = int(getattr(ts, "numerator", 4) or 4)
        denominator_obj = getattr(ts, "denominator", 4)
        denominator = int(getattr(denominator_obj, "value", denominator_obj) or 4)
        if numerator > 0 and denominator > 0:
            return float(numerator) * (4.0 / float(denominator))
    except Exception:
        pass
    return 4.0


# ===========================================================================
# Modern path: GP7/GP8 native GPIF parsing
# ===========================================================================


def _parse_gpif_native(path: Path) -> dict[str, Any]:
    try:
        root = _load_gpif(path)
    except (zipfile.BadZipFile, KeyError, ET.ParseError, OSError) as exc:
        raise ParseError(f"Failed to read GPIF from '{path}': {exc}") from exc

    metadata = _gpif_extract_metadata(root, path)
    tempo_map = _gpif_build_tempo_map(root)
    rhythm_map = _gpif_build_rhythm_map(root)
    note_map = _gpif_build_note_map(root)
    beat_map = _gpif_build_beat_map(root)
    voice_map = _gpif_build_voice_map(root)
    bar_map = _gpif_build_bar_map(root)

    tracks_out: list[dict[str, Any]] = []
    track_elements = root.findall("Tracks/Track")
    for track_idx, track_el in enumerate(track_elements):
        if not _gpif_is_guitar_track(track_el):
            continue
        record = _gpif_build_track_record(
            root, track_el, track_idx,
            tempo_map, rhythm_map, note_map, beat_map, voice_map, bar_map,
        )
        if record is not None:
            tracks_out.append(record)

    return {
        "song_id": _hash_song_id(path),
        "metadata": metadata,
        "tracks": tracks_out,
    }


class _BitStream:
    """Bit-level reader for BCFZ decompression (MSB-first within each byte)."""

    def __init__(self, data: bytes):
        self.data = data
        self.pointer = 0
        self.subpointer = 0
        self.finished = False

    def get_bit(self) -> bool:
        if self.pointer >= len(self.data):
            self.finished = True
            return False
        ret_val = (self.data[self.pointer] >> (7 - self.subpointer)) & 1 == 1
        self.subpointer += 1
        if self.subpointer == 8:
            self.subpointer = 0
            self.pointer += 1
        if self.pointer >= len(self.data):
            self.finished = True
        return ret_val

    def get_bits_le(self, amount: int) -> int:
        ret_val = 0
        for x in range(amount):
            if self.get_bit():
                ret_val |= (1 << x)
        return ret_val

    def get_bits_be(self, amount: int) -> int:
        ret_val = 0
        for x in range(amount):
            if self.get_bit():
                ret_val |= (1 << (amount - x - 1))
        return ret_val

    def get_byte(self) -> int:
        ret_val = 0
        powers_rev = [128, 64, 32, 16, 8, 4, 2, 1]
        for x in range(8):
            if self.get_bit():
                ret_val |= powers_rev[x]
        return ret_val

    def skip_bytes(self, n: int):
        self.pointer += n
        if self.pointer >= len(self.data):
            self.finished = True


def _decompress_bcfz(data: bytes) -> bytes:
    """Decompress BCFZ (Guitar Pro 6 GPX) bit-packed LZ format."""
    expected_size = struct.unpack_from("<I", data, 4)[0]
    bs = _BitStream(data)
    bs.skip_bytes(8)

    output = bytearray()
    while not bs.finished and len(output) < expected_size:
        if bs.get_bit():
            word_size = bs.get_bits_be(4)
            offset = bs.get_bits_le(word_size)
            length = bs.get_bits_le(word_size)
            source_position = len(output) - offset
            if source_position < 0:
                break
            to_read = min(length, offset)
            for r in range(source_position, source_position + to_read):
                output.append(output[r])
        else:
            byte_length = bs.get_bits_le(2)
            for _ in range(byte_length):
                output.append(bs.get_byte())

    return bytes(output)


def _extract_gpif_from_bcfs(decompressed: bytes) -> bytes:
    """Extract GPIF XML from a decompressed BCFS virtual filesystem."""
    xml_start = decompressed.find(b"<?xml")
    if xml_start == -1:
        xml_start = decompressed.find(b"<GPIF")
    if xml_start == -1:
        raise ParseError("No GPIF XML found in BCFS data")

    gpif_end = decompressed.find(b"</GPIF>", xml_start)
    if gpif_end == -1:
        return decompressed[xml_start:]
    return decompressed[xml_start:gpif_end + 7]


def _load_gpif(path: Path) -> ET.Element:
    raw = path.read_bytes()

    # GP6 .gpx files use BCFZ compression
    if raw[:4] == b"BCFZ":
        decompressed = _decompress_bcfz(raw)
        gpif_xml = _extract_gpif_from_bcfs(decompressed)
        return ET.fromstring(gpif_xml)

    # GP7+ .gp files are ZIP archives
    try:
        with zipfile.ZipFile(path, "r") as zf:
            candidates = ["Content/score.gpif", "score.gpif"]
            for name in candidates:
                if name in zf.namelist():
                    return ET.fromstring(zf.read(name))
            for name in zf.namelist():
                if name.endswith(".gpif"):
                    return ET.fromstring(zf.read(name))
    except zipfile.BadZipFile:
        raise ParseError(f"Cannot open {path}: not a valid ZIP or BCFZ file")

    raise ParseError(f"No score.gpif inside {path}")


def _gpif_extract_metadata(root: ET.Element, path: Path) -> dict[str, Any]:
    score = root.find("Score")

    def _ftxt(tag: str) -> str | None:
        if score is None:
            return None
        val = (score.findtext(tag, "") or "").strip()
        return val or None

    tempo = None
    for auto in root.findall("MasterTrack/Automations/Automation"):
        if auto.findtext("Type", "") == "Tempo":
            val_text = auto.findtext("Value", "")
            try:
                tempo = float(val_text.split()[0]) if val_text else None
            except (ValueError, IndexError):
                tempo = None
            break

    return {
        "title": _ftxt("Title"),
        "subtitle": _ftxt("SubTitle"),
        "artist": _ftxt("Artist"),
        "album": _ftxt("Album"),
        "transcriber": _ftxt("Tabber"),
        "source_format": "gp7",
        "source_path": path.name,
        "tempo_bpm": tempo,
        "license": None,
        "schema_version": "1.0.0",
    }


def _gpif_is_guitar_track(track_el: ET.Element) -> bool:
    """Determine if a GPIF track is a guitar track.

    Ported from old gp7_parser._is_guitar_track_gp7() with full MIDI program
    range checks, bass exclusion, and keyword filtering. This replaces the
    harvester's _gpif_is_percussion() which only excluded drumkit/percussion
    and let bass tracks through.
    """
    # Check instrument type — exclude percussion
    instrument_type = track_el.findtext(".//InstrumentSet/Type", "") or ""
    if instrument_type.lower() in ("drumkit", "percussion"):
        return False

    # Check MIDI program (most reliable)
    midi_prog = _gpif_track_midi_program(track_el)
    if midi_prog >= 0:
        if midi_prog in _GUITAR_MIDI_PROGRAMS:
            return True
        if midi_prog in _BASS_MIDI_PROGRAMS:
            return False
        if midi_prog == 0:
            pass  # ambiguous, check further

    # Check sound name
    for sound_el in track_el.findall(".//Sounds/Sound"):
        sound_name = (sound_el.findtext("Name") or "").strip().lower()
        if any(kw in sound_name for kw in _DRUM_NAME_KEYWORDS):
            return False
        if any(kw in sound_name for kw in _BASS_NAME_KEYWORDS):
            return False
        if "guitar" in sound_name:
            return True

    # Check track name
    name = (track_el.findtext("Name") or "").lower()
    if any(kw in name for kw in _DRUM_NAME_KEYWORDS):
        return False
    if any(kw in name for kw in _BASS_NAME_KEYWORDS):
        return False
    if any(kw in name for kw in _GUITAR_NAME_KEYWORDS):
        return True

    # Fallback: 6-8 strings with lowest pitch > 35 MIDI (not bass range)
    tuning_el = track_el.find(".//Properties/Property[@name='Tuning']")
    if tuning_el is None:
        # Try Staves path
        staff = track_el.find("Staves/Staff")
        if staff is not None:
            for prop in staff.findall("Properties/Property"):
                if prop.get("name") == "Tuning":
                    tuning_el = prop
                    break

    if tuning_el is not None:
        pitches_el = tuning_el.find("Pitches")
        if pitches_el is not None and pitches_el.text:
            pitches = pitches_el.text.strip().split()
            n_strings = len(pitches)
            if 6 <= n_strings <= 8:
                try:
                    lowest = min(int(p) for p in pitches)
                    if lowest >= 35:
                        return True
                except ValueError:
                    pass

    return False


def _gpif_build_tempo_map(root: ET.Element) -> dict[int, float]:
    tempo_map: dict[int, float] = {}
    for auto in root.findall("MasterTrack/Automations/Automation"):
        if auto.findtext("Type", "") != "Tempo":
            continue
        bar_text = auto.findtext("Bar", "0")
        val_text = auto.findtext("Value", "")
        try:
            bar = int(bar_text)
            bpm = float(val_text.split()[0]) if val_text else 120.0
            tempo_map[bar] = bpm
        except (ValueError, IndexError):
            continue
    return tempo_map


def _gpif_build_rhythm_map(root: ET.Element) -> dict[str, dict[str, Any]]:
    rmap: dict[str, dict[str, Any]] = {}
    for rhythm in root.findall("Rhythms/Rhythm"):
        rid = rhythm.get("id", "")
        nv = rhythm.findtext("NoteValue", "Quarter")
        dotted = 0
        aug = rhythm.find("AugmentationDot")
        if aug is not None:
            try:
                dotted = int(aug.get("count", "0") or "0")
            except ValueError:
                dotted = 0
        tuplet = rhythm.find("PrimaryTuplet")
        enters = times = 1
        if tuplet is not None:
            try:
                enters = int(tuplet.get("num", "1") or "1")
                times = int(tuplet.get("den", "1") or "1")
            except ValueError:
                pass
        rmap[rid] = {
            "note_value": nv, "dotted": dotted,
            "tuplet_enters": enters, "tuplet_times": times,
        }
    return rmap


def _gpif_build_note_map(root: ET.Element) -> dict[str, ET.Element]:
    return {n.get("id", ""): n for n in root.findall("Notes/Note")}


def _gpif_build_beat_map(root: ET.Element) -> dict[str, ET.Element]:
    return {b.get("id", ""): b for b in root.findall("Beats/Beat")}


def _gpif_build_voice_map(root: ET.Element) -> dict[str, ET.Element]:
    return {v.get("id", ""): v for v in root.findall("Voices/Voice")}


def _gpif_build_bar_map(root: ET.Element) -> dict[str, ET.Element]:
    return {b.get("id", ""): b for b in root.findall("Bars/Bar")}


def _gpif_build_track_record(
    root: ET.Element, track_el: ET.Element, track_idx: int,
    tempo_map: dict[int, float],
    rhythm_map: dict[str, dict[str, Any]],
    note_map: dict[str, ET.Element],
    beat_map: dict[str, ET.Element],
    voice_map: dict[str, ET.Element],
    bar_map: dict[str, ET.Element],
) -> dict[str, Any] | None:
    name = (track_el.findtext("Name", "") or "").strip() or None

    open_pitches_low_to_high = _gpif_track_tuning(track_el)
    if not open_pitches_low_to_high:
        return None
    tuning = [_midi_to_spn(p) for p in open_pitches_low_to_high]
    string_count = len(open_pitches_low_to_high)

    events = _gpif_walk_masterbars(
        root, track_idx, open_pitches_low_to_high, string_count,
        tempo_map, rhythm_map, note_map, beat_map, voice_map, bar_map,
    )

    return {
        "track_id": track_idx,
        "track_name": name,
        "instrument": "guitar",
        "midi_program": _gpif_track_midi_program(track_el),
        "tuning": tuning,
        "capo": _gpif_track_capo(track_el),
        "events": events,
    }


def _gpif_track_tuning(track_el: ET.Element) -> list[int]:
    # GP7+ stores tuning under Staves/Staff/Properties; GP6 under direct Properties
    search_roots = []
    staff = track_el.find("Staves/Staff")
    if staff is not None:
        search_roots.append(staff)
    search_roots.append(track_el)

    for parent in search_roots:
        for prop in parent.findall("Properties/Property"):
            if prop.get("name") == "Tuning":
                pitches_text = prop.findtext("Pitches", "") or ""
                try:
                    return [int(x) for x in pitches_text.split() if x.strip()]
                except ValueError:
                    continue
    return []


def _gpif_track_capo(track_el: ET.Element) -> int:
    for prop in track_el.findall(".//Property"):
        if prop.get("name") == "CapoFret":
            try:
                return int(prop.findtext("Fret", "0") or "0")
            except ValueError:
                return 0
    return 0


def _gpif_track_midi_program(track_el: ET.Element) -> int:
    for tag in (".//MIDI/Program", ".//PartSounding/Program"):
        prog = track_el.findtext(tag, "")
        if prog and prog.lstrip("-").isdigit():
            return int(prog)
    return -1


def _gpif_walk_masterbars(
    root: ET.Element, track_idx: int,
    open_pitches_low_to_high: list[int], string_count: int,
    tempo_map: dict[int, float],
    rhythm_map: dict[str, dict[str, Any]],
    note_map: dict[str, ET.Element],
    beat_map: dict[str, ET.Element],
    voice_map: dict[str, ET.Element],
    bar_map: dict[str, ET.Element],
) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    abs_beat = 0.0
    current_tempo = 120.0

    master_bars = root.findall("MasterBars/MasterBar")
    for mb_idx, mb in enumerate(master_bars, start=1):
        if (mb_idx - 1) in tempo_map:
            current_tempo = tempo_map[mb_idx - 1]

        time_sig = (mb.findtext("Time", "4/4") or "4/4").strip()
        nominal_duration = _gpif_time_sig_to_beats(time_sig)
        measure_onset = abs_beat

        bars_text = (mb.findtext("Bars", "") or "").strip()
        bar_ids = bars_text.split()
        if track_idx >= len(bar_ids):
            abs_beat = measure_onset + nominal_duration
            continue
        bar = bar_map.get(bar_ids[track_idx])
        if bar is None:
            abs_beat = measure_onset + nominal_duration
            continue

        voices_text = (bar.findtext("Voices", "") or "").strip()
        voice_ids = voices_text.split()

        for voice_idx, vid in enumerate(voice_ids):
            if vid == "-1":
                continue
            voice = voice_map.get(vid)
            if voice is None:
                continue
            beats_text = (voice.findtext("Beats", "") or "").strip()
            beat_ids = beats_text.split()
            beat_onset = measure_onset

            for bid in beat_ids:
                beat_el = beat_map.get(bid)
                if beat_el is None:
                    continue
                rhythm_ref = beat_el.find("Rhythm")
                rhythm_id = rhythm_ref.get("ref", "") if rhythm_ref is not None else ""
                rhythm = rhythm_map.get(rhythm_id, {})
                beat_duration = _gpif_rhythm_to_beats(rhythm)
                chord_symbol = _gpif_beat_chord_name(beat_el)

                note_ids_text = (beat_el.findtext("Notes", "") or "").strip()
                note_ids = note_ids_text.split()

                if not note_ids:
                    events.append(_make_rest_event(
                        mb_idx, beat_onset, beat_duration,
                        voice_idx, current_tempo, chord_symbol,
                    ))
                    beat_onset += beat_duration
                    continue

                unified_notes: list[dict[str, Any]] = []
                for nid in note_ids:
                    note_el = note_map.get(nid)
                    if note_el is None:
                        continue
                    u = _gpif_note_to_unified(note_el, open_pitches_low_to_high, string_count)
                    if u is not None:
                        unified_notes.append(u)

                if unified_notes:
                    event_type = "chord" if len(unified_notes) > 1 else "note"
                    events.append({
                        "measure": mb_idx,
                        "abs_beat": round(beat_onset, 6),
                        "duration_beats": round(beat_duration, 6),
                        "type": event_type,
                        "voice": voice_idx,
                        "tempo_bpm": current_tempo,
                        "chord_symbol": chord_symbol,
                        "chord_diagram": None,
                        "notes": unified_notes,
                    })
                beat_onset += beat_duration

            voice_duration = beat_onset - measure_onset
            if voice_duration > 0.0:
                nominal_duration = max(nominal_duration, voice_duration)

        abs_beat = measure_onset + nominal_duration

    events.sort(key=lambda e: (e["abs_beat"], e["voice"]))
    return events


def _gpif_note_to_unified(
    note_el: ET.Element,
    open_pitches_low_to_high: list[int],
    string_count: int,
) -> dict[str, Any] | None:
    tie = note_el.find("Tie")
    if tie is not None and tie.get("destination", "false").lower() == "true":
        return None

    props = {p.get("name", ""): p for p in note_el.findall("Properties/Property")}

    string_prop = props.get("String")
    fret_prop = props.get("Fret")
    if string_prop is None or fret_prop is None:
        return None
    try:
        gpif_string = int(string_prop.findtext("String", "0") or "0")
        fret = int(fret_prop.findtext("Fret", "0") or "0")
    except ValueError:
        return None

    unified_string = _gpif_string_to_unified(gpif_string, string_count)
    if 0 <= gpif_string < string_count:
        open_pitch = open_pitches_low_to_high[gpif_string]
        pitch_midi: int | None = open_pitch + fret
    else:
        pitch_midi = None

    midi_prop = props.get("Midi")
    if midi_prop is not None:
        midi_text = midi_prop.findtext("Number", "")
        if midi_text and midi_text.lstrip("-").isdigit():
            pitch_midi = int(midi_text)

    return {
        "pitch_midi": pitch_midi,
        "string": unified_string,
        "fret": fret,
        "left_hand_finger": _gpif_left_hand_finger(note_el),
        "right_hand_finger": _gpif_right_hand_finger(note_el),
        "techniques": _gpif_techniques(note_el, props),
        "velocity": 95,
        "tied_to_previous": False,
    }


def _gpif_string_to_unified(gpif_string: int, string_count: int) -> int:
    return string_count - gpif_string


def _gpif_left_hand_finger(note_el: ET.Element) -> str | None:
    finger_text = (note_el.findtext("LeftFingering", "") or "").strip().upper()
    if not finger_text:
        return None
    mapping = {
        "OPEN": "open", "P": "thumb", "I": "index",
        "M": "middle", "A": "ring", "C": "pinky",
    }
    return mapping.get(finger_text)


def _gpif_right_hand_finger(note_el: ET.Element) -> str | None:
    finger_text = (note_el.findtext("RightFingering", "") or "").strip().upper()
    if not finger_text:
        return None
    mapping = {"P": "p", "I": "i", "M": "m", "A": "a", "C": "c"}
    return mapping.get(finger_text)


def _gpif_techniques(note_el: ET.Element, props: dict[str, ET.Element]) -> list[str]:
    tags: list[str] = []
    if note_el.find("HammerPullOrigin") is not None:
        tags.append("hammer_on")
    if note_el.find("HammerPullDestination") is not None:
        tags.append("pull_off")
    if "Slide" in props:
        tags.append("slide")
    if "Bended" in props:
        tags.append("bend")
    if "HarmonicType" in props or "HarmonicFret" in props:
        tags.append("harmonic")
    if note_el.findtext("Vibrato", "") or "Vibrato" in props:
        tags.append("vibrato")
    if "PalmMuted" in props:
        tags.append("palm_mute")
    if "LetRing" in props:
        tags.append("let_ring")
    if "Ghost" in props:
        tags.append("ghost")
    if "Muted" in props:
        tags.append("dead_note")
    if "Tapped" in props:
        tags.append("tap")
    return tags


def _gpif_beat_chord_name(beat_el: ET.Element) -> str | None:
    chord_ref = beat_el.find("Chord")
    if chord_ref is None:
        return None
    name = (chord_ref.text or "").strip()
    return name or None


def _gpif_rhythm_to_beats(rhythm: dict[str, Any]) -> float:
    if not rhythm:
        return 1.0
    beats = _NOTE_VALUE_BEATS.get(rhythm.get("note_value", "Quarter"), 1.0)
    dotted = int(rhythm.get("dotted", 0))
    if dotted == 1:
        beats *= 1.5
    elif dotted == 2:
        beats *= 1.75
    enters = int(rhythm.get("tuplet_enters", 1))
    times = int(rhythm.get("tuplet_times", 1))
    if enters != times and enters > 0:
        beats = beats * times / enters
    return beats


def _gpif_time_sig_to_beats(time_sig: str) -> float:
    try:
        num, den = time_sig.split("/")
        n, d = int(num), int(den)
        if n > 0 and d > 0:
            return float(n) * (4.0 / float(d))
    except (ValueError, AttributeError):
        pass
    return 4.0


# ---------------------------------------------------------------------------
# Module-level convenience
# ---------------------------------------------------------------------------


def parse(path: Path) -> dict[str, Any]:
    """Module-level entrypoint used by the harvest pipeline."""
    return GuitarProAdapter().parse(path)
