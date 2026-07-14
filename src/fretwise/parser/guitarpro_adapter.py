"""GuitarPro file parser adapter for M1.

Reads .gp3, .gp4, .gp5 files via PyGuitarPro and converts them to an
ordered list of NoteEvent objects.

Notes on format support
-----------------------
* GP6/GP7/GP8 (.gpx, .gp without version suffix) are **not** supported by
  PyGuitarPro.  Convert via MuseScore (File → Export → Guitar Pro 5) or via
  Guitar Pro itself (File → Export → Guitar Pro 5) before parsing.
* All voices (0–3) of the selected non-percussion track are processed.
"""

from __future__ import annotations

import logging
from pathlib import Path

import guitarpro  # type: ignore[import-untyped]

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import BaseParser, ParseError, UnsupportedFormatError

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".gp3", ".gp4", ".gp5"})

# Extensions known to be unsupported GP7/GP8 formats — used for a clearer error message.
_GP7_EXTENSIONS: frozenset[str] = frozenset({".gp", ".gpx"})

# MIDI note values for open strings in standard EADGBE tuning (index = string - 1).
# These are used as a fallback when a track does not carry its own tuning data.
_STANDARD_TUNING: list[int] = [64, 59, 55, 50, 45, 40]

# Maximum fret number on a standard guitar neck (22 frets).
MAX_FRET: int = 22

# guitarpro.NoteType.normal has integer value 1.
_NOTE_TYPE_NORMAL: int = 1


class GuitarProAdapter(BaseParser):
    """Parse GuitarPro files (.gp3, .gp4, .gp5) into NoteEvent sequences.

    Uses PyGuitarPro to read the proprietary GP binary format.  The adapter
    processes the first non-percussion guitar track and converts each normal
    note (pitch, rhythm, articulation) into a NoteEvent.

    After a successful call to :meth:`parse`, the :attr:`track_name` attribute
    holds the name of the selected guitar track (e.g. ``"E. Guitar"``).

    Example:
        >>> adapter = GuitarProAdapter()
        >>> events = adapter.parse(Path("song.gp5"))
        >>> events[0].pitch
        64
    """

    #: Name of the last selected guitar track; set after each call to parse().
    track_name: str = ""
    #: MIDI program number (0-127) of the selected track; -1 if unknown.
    midi_program: int = -1
    #: Section/rehearsal markers: {1-based measure number → section title}.
    #: Set after each call to parse().
    section_markers: dict[int, str] = {}
    #: Beat-level chord name annotations: {onset_str → chord_name}.
    #: Set after each call to parse().
    chord_markers: dict[str, str] = {}
    #: Per-measure time signatures: {1-based measure number → (numerator, denominator)}.
    #: Set after each call to parse().
    measure_time_signatures: dict[int, tuple[int, int]] = {}

    def supports(self, path: Path) -> bool:
        """Return True for .gp3, .gp4, and .gp5 files."""
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, path: Path) -> list[NoteEvent]:
        """Parse a GuitarPro file and return NoteEvents sorted by onset.

        Args:
            path: Path to a .gp3, .gp4, or .gp5 file.

        Returns:
            List of NoteEvent ordered by onset time (ascending).

        Raises:
            UnsupportedFormatError: If the suffix is not .gp3/.gp4/.gp5.
            ParseError: If the file is missing or PyGuitarPro cannot read it.
        """
        if not self.supports(path):
            suffix = path.suffix.lower()
            if suffix in _GP7_EXTENSIONS:
                raise UnsupportedFormatError(
                    f"'{path.name}' appears to be a Guitar Pro 7/8 file (.gp/.gpx), "
                    "which is not supported by PyGuitarPro.  "
                    "Convert it to GP5 first: open in MuseScore or Guitar Pro, "
                    "then File > Export > Guitar Pro 5 (.gp5)."
                )
            raise UnsupportedFormatError(
                f"GuitarProAdapter does not support '{path.suffix}'. "
                f"Supported extensions: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        try:
            song = guitarpro.parse(str(path))
        except Exception as exc:
            raise ParseError(f"Failed to parse '{path}': {exc}") from exc

        track = _find_guitar_track(song)
        if track is None:
            logger.warning("No guitar track found in '%s'. Returning empty sequence.", path)
            self.track_name = ""
            return []

        self.track_name = getattr(track, "name", "") or ""
        self.midi_program = getattr(getattr(track, "channel", None), "instrument", -1)
        self.section_markers = _extract_section_markers(track)
        self.chord_markers = _extract_beat_chord_markers(song, track)
        self.measure_time_signatures = _extract_measure_time_signatures(track)
        return _extract_note_events(song, track)


# ---------------------------------------------------------------------------
# Module-level helpers (pure functions — easier to test in isolation)
# ---------------------------------------------------------------------------


def _find_guitar_track(song: guitarpro.Song) -> guitarpro.Track | None:  # type: ignore[name-defined]
    """Return the best guitar track, preferring guitar MIDI programs (24-31).

    Selection order:
    1. Non-percussion track with guitar MIDI program (24–31) — standard or electric guitar.
    2. Non-percussion track with exactly 6 strings (standard guitar neck).
    3. First non-percussion track (fallback with a warning).
    """
    _GUITAR_PROGRAMS: frozenset[int] = frozenset(range(24, 32))

    for track in song.tracks:
        if track.isPercussionTrack:
            continue
        program = getattr(getattr(track, "channel", None), "instrument", -1)
        if program in _GUITAR_PROGRAMS:
            return track

    for track in song.tracks:
        if not track.isPercussionTrack and track.strings and len(track.strings) == 6:
            return track

    for track in song.tracks:
        if not track.isPercussionTrack:
            logger.warning(
                "No guitar track found (MIDI programs 24–31 / 6-string). "
                "Falling back to first non-percussion track '%s'.",
                getattr(track, "name", "?"),
            )
            return track

    return None


def _extract_note_events(
    song: guitarpro.Song,  # type: ignore[name-defined]
    track: guitarpro.Track,  # type: ignore[name-defined]
) -> list[NoteEvent]:
    """Walk the track measure-by-measure and collect NoteEvents from all voices.

    All GP voices (0–3) are processed; each NoteEvent carries its voice index in
    ``voice_hint`` so the pipeline can run Viterbi independently per voice.
    Tempo changes are tracked via MeasureHeader.
    """
    open_pitches = _open_string_pitches(track)
    current_tempo = float(song.tempo)
    onset = 0.0
    events: list[NoteEvent] = []

    for measure_number, measure in enumerate(track.measures, start=1):
        current_tempo = _measure_tempo(measure, current_tempo)
        measure_onset = onset
        measure_duration = _measure_nominal_duration_in_beats(measure)

        for voice_idx, voice in enumerate(measure.voices):
            beat_onset = measure_onset

            for beat in voice.beats:
                beat_duration = _duration_in_beats(beat.duration)
                _gp_tup = beat.duration.tuplet
                _beat_tuplet_actual: int | None = (
                    _gp_tup.enters if _gp_tup.enters != _gp_tup.times else None
                )
                _beat_tuplet_normal: int | None = (
                    _gp_tup.times if _gp_tup.enters != _gp_tup.times else None
                )
                strum_direction = _beat_strum_direction(beat)

                for note in beat.notes:
                    # Skip rests (0) and tied notes (2); process only normal notes (1).
                    if getattr(note.type, "value", int(note.type)) != _NOTE_TYPE_NORMAL:
                        continue

                    string_num: int = note.string
                    fret: int = note.value
                    pitch = open_pitches[string_num - 1] + fret

                    events.append(
                        NoteEvent(
                            pitch=pitch,
                            onset=beat_onset,
                            duration=beat_duration,
                            tempo=current_tempo,
                            articulation=_get_articulation(note),
                            dynamic=Dynamic.MF,  # GP velocity → Phase 2
                            string_hint=string_num,
                            fret_hint=fret,
                            voice_hint=voice_idx,
                            let_ring=bool(getattr(getattr(note, "effect", None), "letRing", False)),
                            strum_direction=strum_direction,
                            tuplet_actual=_beat_tuplet_actual,
                            tuplet_normal=_beat_tuplet_normal,
                            measure_index=measure_number,
                        )
                    )

                beat_onset += beat_duration

        # The measure grid is defined by the (global) time signature headers.
        # Never stretch a measure to fit an overfull voice: every track of the
        # song must advance by the same amount per measure, or the tracks
        # desync from one another (playback, cursor, navigation).
        onset = measure_onset + measure_duration

    return sorted(events, key=lambda e: (e.onset, e.voice_hint or 0))


def _open_string_pitches(track: guitarpro.Track) -> list[int]:  # type: ignore[name-defined]
    """Return open-string MIDI pitches ordered by string number (index 0 = string 1).

    Falls back to standard EADGBE tuning when the track carries no string data.
    """
    if track.strings:
        return [s.value for s in sorted(track.strings, key=lambda s: s.number)]
    logger.debug("Track has no string data; falling back to standard EADGBE tuning.")
    return _STANDARD_TUNING


def _measure_tempo(
    measure: guitarpro.Measure,  # type: ignore[name-defined]
    current_tempo: float,
) -> float:
    """Extract the tempo from a measure header, falling back to the current tempo."""
    try:
        return float(measure.header.tempo.value)
    except AttributeError:
        return current_tempo


def _duration_in_beats(duration: guitarpro.Duration) -> float:  # type: ignore[name-defined]
    """Convert a PyGuitarPro Duration to a float number of quarter-note beats.

    Handles dotted notes and tuplets.

    Args:
        duration: A guitarpro.Duration with .value (1=whole, 2=half, 4=quarter…),
            .isDotted, .isDoubleDotted, and .tuplet (.enters / .times).

    Returns:
        Duration expressed in quarter-note beats (e.g. 1.0 for a quarter note).
    """
    beats = 4.0 / duration.value
    if duration.isDotted:
        beats *= 1.5
    elif duration.isDoubleDotted:
        beats *= 1.75
    tuplet = duration.tuplet
    if tuplet.enters != tuplet.times:
        beats = beats * tuplet.times / tuplet.enters
    return beats


def _extract_beat_chord_markers(
    song: guitarpro.Song,  # type: ignore[name-defined]
    track: guitarpro.Track,  # type: ignore[name-defined]
) -> dict[str, str]:
    """Return {onset_str → chord_name} from beat-level chord annotations (voice 0 only)."""
    markers: dict[str, str] = {}
    current_tempo = float(song.tempo)
    onset = 0.0
    for measure in track.measures:
        current_tempo = _measure_tempo(measure, current_tempo)
        measure_onset = onset
        measure_duration = _measure_nominal_duration_in_beats(measure)
        voice = measure.voices[0] if measure.voices else None
        beat_onset = measure_onset
        if voice:
            for beat in voice.beats:
                beat_duration = _duration_in_beats(beat.duration)
                chord = getattr(getattr(beat, "effect", None), "chord", None)
                if chord is not None:
                    name = getattr(chord, "name", None) or ""
                    if name.strip():
                        markers[f"{beat_onset:.6f}"] = name.strip()
                beat_onset += beat_duration
        # Same global-grid rule as _extract_note_events: advance strictly by the
        # header time signature so chord markers stay aligned across tracks.
        onset = measure_onset + measure_duration
    return markers


def _measure_nominal_duration_in_beats(
    measure: guitarpro.Measure,  # type: ignore[name-defined]
) -> float:
    """Return nominal measure duration from the time signature (quarter-note beats)."""
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


def _beat_strum_direction(
    beat: guitarpro.Beat,  # type: ignore[name-defined]
) -> str | None:
    """Extract strum direction from beat-level stroke metadata when present."""
    effect = getattr(beat, "effect", None)
    stroke = getattr(effect, "stroke", None)
    if stroke is not None:
        try:
            down = int(getattr(stroke, "down", 0) or 0)
        except (TypeError, ValueError):
            down = 0
        try:
            up = int(getattr(stroke, "up", 0) or 0)
        except (TypeError, ValueError):
            up = 0
        if down > 0:
            return "down"
        if up > 0:
            return "up"

    pick_stroke = str(getattr(effect, "pickStroke", "") or "").lower()
    if "down" in pick_stroke:
        return "down"
    if "up" in pick_stroke:
        return "up"
    return None


def _extract_section_markers(
    track: guitarpro.Track,  # type: ignore[name-defined]
) -> dict[int, str]:
    """Return {1-based measure number → section title} from rehearsal markers.

    PyGuitarPro exposes markers via ``measure.header.marker``.  The attribute
    is ``None`` when no marker is set for that measure.
    """
    markers: dict[int, str] = {}
    for m_idx, measure in enumerate(track.measures):
        try:
            marker = measure.header.marker
        except AttributeError:
            continue
        if marker is None:
            continue
        title: str = getattr(marker, "title", "") or ""
        title = title.strip()
        # PyGuitarPro uses "Section" as the default placeholder title — skip it.
        if title and title.lower() != "section":
            markers[m_idx + 1] = title
    return markers


def _extract_measure_time_signatures(
    track: guitarpro.Track,  # type: ignore[name-defined]
) -> dict[int, tuple[int, int]]:
    """Return {1-based measure number → (numerator, denominator)} for every measure.

    Reads ``measure.header.timeSignature`` from each measure in the track.
    """
    result: dict[int, tuple[int, int]] = {}
    for m_idx, measure in enumerate(track.measures):
        try:
            ts = measure.header.timeSignature
            numerator = int(getattr(ts, "numerator", 4) or 4)
            denominator_obj = getattr(ts, "denominator", 4)
            denominator = int(getattr(denominator_obj, "value", denominator_obj) or 4)
            if numerator > 0 and denominator > 0:
                result[m_idx + 1] = (numerator, denominator)
        except Exception:
            continue
    return result


def _get_articulation(note: guitarpro.Note) -> Articulation:  # type: ignore[name-defined]
    """Map PyGuitarPro note effects to a single Articulation value.

    Priority order (highest to lowest): hammer-on, pull-off, slide,
    vibrato, bend.  Returns NORMAL when no effect is detected.
    """
    effect = note.effect
    if effect.hammer:
        return Articulation.HAMMER_ON
    if effect.pullOff:
        return Articulation.PULL_OFF
    if effect.slides:
        return Articulation.SLIDE
    if effect.vibrato:
        return Articulation.VIBRATO
    if effect.bend is not None:
        return Articulation.BEND
    return Articulation.NORMAL
