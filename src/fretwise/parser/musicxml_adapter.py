"""MusicXML parser adapter for M1.

Reads .xml and .mxl (compressed) MusicXML files via music21 and converts
them to an ordered list of NoteEvent objects.

Notes
-----
* MusicXML does **not** carry tablature data (string/fret) — ``string_hint``
  and ``fret_hint`` will always be None.  The state generator will enumerate
  all valid fretboard positions for each pitch.
* Articulations and effects are mapped where music21 provides them; many
  guitar-specific notations (bends, slides, harmonics) may not be present
  in generic MusicXML exports.
"""

from __future__ import annotations

import logging
from pathlib import Path

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import BaseParser, ParseError, UnsupportedFormatError

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".xml", ".mxl", ".musicxml"})


def _safe_import_music21() -> object:
    """Import music21, raising ParseError if not installed."""
    try:
        import music21  # type: ignore[import-untyped]
        return music21
    except ImportError as exc:
        raise ParseError(
            "music21 is required for MusicXML parsing. "
            "Install it with: pip install music21"
        ) from exc


class MusicXmlAdapter(BaseParser):
    """Parse MusicXML files (.xml, .mxl, .musicxml) into NoteEvent sequences.

    Uses music21 to read the MusicXML format.  The adapter processes all
    parts by default, selecting the first guitar-like part when multiple
    instruments are present.

    After a successful call to :meth:`parse`, the :attr:`track_name` attribute
    holds the name of the selected part (e.g. ``"Classical Guitar"``).
    """

    #: Name of the last selected part; set after each call to parse().
    track_name: str = ""
    #: Section/rehearsal markers: {1-based measure number → section title}.
    section_markers: dict[int, str] = {}

    def supports(self, path: Path) -> bool:
        """Return True for .xml, .mxl, and .musicxml files."""
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, path: Path) -> list[NoteEvent]:
        """Parse a MusicXML file and return NoteEvents sorted by onset.

        Args:
            path: Path to a .xml, .mxl, or .musicxml file.

        Returns:
            List of NoteEvent ordered by onset time (ascending).

        Raises:
            UnsupportedFormatError: If the suffix is not supported.
            ParseError: If the file cannot be opened or decoded.
        """
        if not self.supports(path):
            raise UnsupportedFormatError(
                f"MusicXmlAdapter does not support '{path.suffix}'. "
                f"Supported extensions: {sorted(_SUPPORTED_EXTENSIONS)}"
            )
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        m21 = _safe_import_music21()

        try:
            score = m21.converter.parse(str(path))  # type: ignore[union-attr]
        except Exception as exc:
            raise ParseError(f"Failed to parse '{path}': {exc}") from exc

        part = _find_guitar_part(score)
        if part is None:
            logger.warning("No suitable part found in '%s'. Returning empty.", path)
            self.track_name = ""
            self.section_markers = {}
            return []

        self.track_name = _part_name(part)
        self.section_markers = _extract_rehearsal_marks(part)
        return _extract_note_events(part)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_GUITAR_MIDI_PROGRAMS: frozenset[int] = frozenset(range(24, 32))


def _part_name(part: object) -> str:
    """Extract a human-readable name from a music21 Part."""
    name = getattr(part, "partName", None) or ""
    if not name:
        name = getattr(part, "id", "") or ""
    return str(name).strip()


def _find_guitar_part(score: object) -> object | None:
    """Select the best guitar-sounding part from a music21 Score.

    Priority:
    1. Part whose MIDI program is 24–31 (guitar family).
    2. Part whose name contains 'guitar' or 'guit' (case-insensitive).
    3. First Part (fallback).
    """
    import music21  # type: ignore[import-untyped]

    parts = list(score.parts)  # type: ignore[union-attr]
    if not parts:
        return None

    # Strategy 1: MIDI program
    for part in parts:
        instruments = part.getInstruments(returnDefault=False)
        for inst in instruments:
            prog = getattr(inst, "midiProgram", None)
            if prog is not None and prog in _GUITAR_MIDI_PROGRAMS:
                return part

    # Strategy 2: name matching
    for part in parts:
        name = _part_name(part).lower()
        if "guitar" in name or "guit" in name:
            return part

    # Fallback: first part
    logger.debug(
        "No guitar part found by program or name — falling back to first part '%s'.",
        _part_name(parts[0]),
    )
    return parts[0]


def _extract_rehearsal_marks(part: object) -> dict[int, str]:
    """Extract rehearsal marks as {1-based measure number → label}."""
    import music21  # type: ignore[import-untyped]

    markers: dict[int, str] = {}
    for el in part.recurse():  # type: ignore[union-attr]
        if isinstance(el, music21.expressions.RehearsalMark):
            measure = el.getContextByClass(music21.stream.Measure)
            if measure is not None:
                label = str(getattr(el, "content", "") or "").strip()
                if label:
                    markers[int(measure.number)] = label
    return markers


def _m21_dynamic_to_dynamic(m21_velocity: int | None) -> Dynamic:
    """Map a MIDI velocity (0–127) to a Dynamic enum value."""
    if m21_velocity is None:
        return Dynamic.MF
    if m21_velocity < 32:
        return Dynamic.PP
    if m21_velocity < 54:
        return Dynamic.P
    if m21_velocity < 75:
        return Dynamic.MP
    if m21_velocity < 96:
        return Dynamic.MF
    if m21_velocity < 112:
        return Dynamic.F
    return Dynamic.FF


def _m21_articulation_to_articulation(note: object) -> Articulation:
    """Map music21 articulations to a single Articulation value."""
    import music21  # type: ignore[import-untyped]

    arts = getattr(note, "articulations", [])
    for art in arts:
        if isinstance(art, music21.articulations.Staccato):
            return Articulation.STACCATO
        if isinstance(art, music21.articulations.Accent):
            return Articulation.NORMAL  # accent stored as flag, not Articulation
    # Check for expressions
    exprs = getattr(note, "expressions", [])
    for expr in exprs:
        if isinstance(expr, music21.expressions.Trill):
            return Articulation.LEGATO
        if isinstance(expr, music21.expressions.Mordent):
            return Articulation.LEGATO
    return Articulation.NORMAL


def _extract_note_events(part: object) -> list[NoteEvent]:
    """Walk a music21 Part and collect NoteEvents.

    Processes both single notes and chords.  Tied notes (continuation)
    are skipped to avoid duplicating sustained notes.
    """
    import music21  # type: ignore[import-untyped]

    events: list[NoteEvent] = []
    current_tempo: float = 120.0  # default

    for el in part.flatten().notesAndRests:  # type: ignore[union-attr]
        # Track tempo changes
        tempos = el.getContextByClass(music21.tempo.MetronomeMark)
        if tempos is not None:
            current_tempo = float(tempos.number)

        if isinstance(el, music21.note.Rest):
            continue

        if isinstance(el, music21.chord.Chord):
            for n in el:
                _append_note(events, n, el.offset, el.quarterLength, current_tempo)
        elif isinstance(el, music21.note.Note):
            _append_note(events, el, el.offset, el.quarterLength, current_tempo)

    return sorted(events, key=lambda e: e.onset)


def _append_note(
    events: list[NoteEvent],
    note: object,
    offset: float,
    duration: float,
    tempo: float,
) -> None:
    """Create a NoteEvent from a music21 Note and append to events.

    Skips tied continuation notes (tie type 'stop' without 'start').
    """
    import music21  # type: ignore[import-untyped]

    # Skip tied continuation notes
    tie = getattr(note, "tie", None)
    if tie is not None and tie.type == "stop":
        return

    pitch_midi: int = int(note.pitch.midi)  # type: ignore[union-attr]
    art = _m21_articulation_to_articulation(note)
    vel: int | None = getattr(getattr(note, "volume", None), "velocity", None)
    dynamic = _m21_dynamic_to_dynamic(vel)

    # Accent detection
    accent = False
    accent_strong = False
    for a in getattr(note, "articulations", []):
        if isinstance(a, music21.articulations.Accent):
            accent = True
        if isinstance(a, music21.articulations.StrongAccent):
            accent_strong = True

    events.append(
        NoteEvent(
            pitch=pitch_midi,
            onset=float(offset),
            duration=float(duration),
            tempo=tempo,
            articulation=art,
            dynamic=dynamic,
            accent=accent,
            accent_strong=accent_strong,
        )
    )
