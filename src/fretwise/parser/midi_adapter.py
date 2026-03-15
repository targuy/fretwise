"""MIDI parser adapter for M1.

Reads .mid and .midi files via pretty_midi and converts them to an ordered
list of NoteEvent objects.

Notes
-----
* MIDI carries no tablature data — ``string_hint`` and ``fret_hint`` are
  always None.  The state generator will enumerate all valid positions.
* MIDI velocity is mapped to the Dynamic enum.
* Guitar-specific articulations (bends, slides, harmonics) are **not**
  available in standard MIDI and will all default to NORMAL.
* Tempo changes embedded in the MIDI file are tracked and assigned per-note.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import BaseParser, ParseError, UnsupportedFormatError

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".mid", ".midi"})

# General MIDI guitar programs (0-indexed: 24–31 = guitar family).
_GUITAR_PROGRAMS: frozenset[int] = frozenset(range(24, 32))

# Guitar-range MIDI pitches: E2 (40) to around C6 (84) — generous range.
_GUITAR_PITCH_MIN: int = 28
_GUITAR_PITCH_MAX: int = 96


def _safe_import_pretty_midi() -> object:
    """Import pretty_midi, raising ParseError if not installed."""
    try:
        import pretty_midi  # type: ignore[import-untyped]
        return pretty_midi
    except ImportError as exc:
        raise ParseError(
            "pretty_midi is required for MIDI parsing. "
            "Install it with: pip install pretty_midi"
        ) from exc


class MidiAdapter(BaseParser):
    """Parse MIDI files (.mid, .midi) into NoteEvent sequences.

    Uses pretty_midi to read standard MIDI format.  The adapter selects the
    best guitar-like instrument track and converts each note to a NoteEvent
    with velocity-based dynamics.

    After a successful call to :meth:`parse`, the :attr:`track_name`
    attribute holds the name of the selected instrument.
    """

    #: Name of the last selected instrument; set after each call to parse().
    track_name: str = ""
    #: Section markers (MIDI has no rehearsal marks — always empty).
    section_markers: dict[int, str] = {}

    def supports(self, path: Path) -> bool:
        """Return True for .mid and .midi files."""
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, path: Path) -> list[NoteEvent]:
        """Parse a MIDI file and return NoteEvents sorted by onset.

        Args:
            path: Path to a .mid or .midi file.

        Returns:
            List of NoteEvent ordered by onset time (ascending).

        Raises:
            UnsupportedFormatError: If the suffix is not supported.
            ParseError: If the file cannot be opened or decoded.
        """
        if not self.supports(path):
            raise UnsupportedFormatError(
                f"MidiAdapter does not support '{path.suffix}'. "
                f"Supported extensions: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        pm = _safe_import_pretty_midi()

        try:
            midi = pm.PrettyMIDI(str(path))  # type: ignore[union-attr]
        except Exception as exc:
            raise ParseError(f"Failed to parse '{path}': {exc}") from exc

        instrument = _find_guitar_instrument(midi)
        if instrument is None:
            logger.warning("No suitable instrument found in '%s'. Returning empty.", path)
            self.track_name = ""
            self.section_markers = {}
            return []

        self.track_name = getattr(instrument, "name", "") or ""
        self.section_markers = {}  # MIDI has no rehearsal marks
        return _extract_note_events(midi, instrument)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _find_guitar_instrument(midi: object) -> object | None:
    """Select the best guitar-sounding instrument from a PrettyMIDI object.

    Priority:
    1. Non-drum instrument with guitar MIDI program (24–31).
    2. Non-drum instrument whose name contains 'guitar' or 'guit'.
    3. First non-drum instrument with notes in guitar range.
    4. First non-drum instrument (fallback).
    """
    instruments = getattr(midi, "instruments", [])
    non_drum = [i for i in instruments if not getattr(i, "is_drum", False)]

    if not non_drum:
        return None

    # Strategy 1: MIDI program
    for inst in non_drum:
        prog = getattr(inst, "program", -1)
        if prog in _GUITAR_PROGRAMS:
            return inst

    # Strategy 2: name matching
    for inst in non_drum:
        name = (getattr(inst, "name", "") or "").lower()
        if "guitar" in name or "guit" in name:
            return inst

    # Strategy 3: pitch range heuristic
    for inst in non_drum:
        notes = getattr(inst, "notes", [])
        if notes:
            pitches = [n.pitch for n in notes]
            if min(pitches) >= _GUITAR_PITCH_MIN and max(pitches) <= _GUITAR_PITCH_MAX:
                return inst

    # Fallback: first non-drum instrument
    logger.debug(
        "No guitar instrument found by program, name, or range — "
        "falling back to first non-drum instrument '%s'.",
        getattr(non_drum[0], "name", "?"),
    )
    return non_drum[0]


def _velocity_to_dynamic(velocity: int) -> Dynamic:
    """Map MIDI velocity (0–127) to a Dynamic enum value."""
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


def _extract_note_events(midi: object, instrument: object) -> list[NoteEvent]:
    """Convert pretty_midi notes to NoteEvents with beat-based timing.

    Uses ``midi.time_to_tick`` and tempo information to convert absolute
    seconds to beat positions.
    """
    import pretty_midi  # type: ignore[import-untyped]

    events: list[NoteEvent] = []
    tempo_changes = midi.get_tempo_changes()  # type: ignore[union-attr]
    tempo_times: list[float] = list(tempo_changes[0])
    tempo_values: list[float] = list(tempo_changes[1])

    # Default tempo if none found
    if not tempo_values:
        tempo_values = [120.0]
        tempo_times = [0.0]

    for note in instrument.notes:  # type: ignore[union-attr]
        # Convert seconds → beats
        onset_beats = _seconds_to_beats(note.start, tempo_times, tempo_values)
        end_beats = _seconds_to_beats(note.end, tempo_times, tempo_values)
        duration_beats = max(end_beats - onset_beats, 0.0625)  # min 1/64 note

        # Current tempo at note onset
        tempo = _tempo_at_time(note.start, tempo_times, tempo_values)

        events.append(
            NoteEvent(
                pitch=note.pitch,
                onset=round(onset_beats, 6),
                duration=round(duration_beats, 6),
                tempo=tempo,
                articulation=Articulation.NORMAL,
                dynamic=_velocity_to_dynamic(note.velocity),
            )
        )

    return sorted(events, key=lambda e: e.onset)


def _tempo_at_time(
    time_sec: float,
    tempo_times: list[float],
    tempo_values: list[float],
) -> float:
    """Return the tempo (BPM) active at a given time in seconds."""
    result = tempo_values[0]
    for t, v in zip(tempo_times, tempo_values):
        if t <= time_sec:
            result = v
        else:
            break
    return result


def _seconds_to_beats(
    time_sec: float,
    tempo_times: list[float],
    tempo_values: list[float],
) -> float:
    """Convert an absolute time in seconds to beat position.

    Integrates through tempo changes to compute the cumulative beat offset.
    """
    if time_sec <= 0.0:
        return 0.0

    beats = 0.0
    prev_time = 0.0
    prev_bpm = tempo_values[0]

    for t, bpm in zip(tempo_times[1:], tempo_values[1:]):
        if t >= time_sec:
            break
        segment_sec = t - prev_time
        beats += segment_sec * prev_bpm / 60.0
        prev_time = t
        prev_bpm = bpm

    # Remaining segment
    remaining_sec = time_sec - prev_time
    beats += remaining_sec * prev_bpm / 60.0
    return beats
