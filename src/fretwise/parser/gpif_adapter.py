"""Guitar Pro 7/8 file parser adapter for M1.

Guitar Pro 7+ uses the `.gp` extension and stores the score as a ZIP archive
containing ``Content/score.gpif``, an XML dialect (Guitar Pro Internal Format).

This adapter parses that XML directly without external dependencies beyond the
standard library, extracting pitch, string/fret, onset, duration, tempo and
basic articulations for every note on the first guitar track found.

Format notes
------------
* String index in GPIF: 0 = lowest string (E2), N-1 = highest string.
  Converted to FretWise convention (1 = highest, 6 = lowest) on output.
* Pitch: taken from ``Property[@name="Midi"]``, which already applies the
  instrument transpose (guitar sounds an octave lower than written).
* Tied notes (``<Tie destination="true">``) are skipped — they extend the
  previous note's duration acoustically but are not new attacks.
* All voices present in the selected track are processed.
"""

from __future__ import annotations

import logging
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from fretwise.models import (
    Articulation, BendType, ChordDiagram, Dynamic, HarmonicType, NoteEvent, SlideType,
)
from fretwise.parser.base import BaseParser, ParseError, UnsupportedFormatError

logger = logging.getLogger(__name__)

_SUPPORTED_EXTENSIONS: frozenset[str] = frozenset({".gp"})

# Maps GPIF NoteValue strings to quarter-note beat counts.
_NOTE_VALUE_BEATS: dict[str, float] = {
    "Long": 16.0,
    "DoubleWhole": 8.0,
    "Whole": 4.0,
    "Half": 2.0,
    "Quarter": 1.0,
    "Eighth": 0.5,
    "16th": 0.25,
    "32nd": 0.125,
    "64th": 0.0625,
}

# Slide flag values that map to an outgoing slide articulation.
_SLIDE_OUT_FLAGS: frozenset[int] = frozenset({1, 2, 4, 32, 64})


def _compute_chord_fingers(frets: list[int]) -> list[int]:
    """Assign finger numbers to chord diagram dots.

    Returns a list parallel to *frets* where each element is:
    0 = unspecified, 1 = index, 2 = middle, 3 = ring, 4 = pinky.

    Algorithm:
    - Ignore muted (-1) and open (0) strings.
    - Sort fretted strings by (fret ASC, string_index ASC).
      Equal fret ⟹ same finger (barre) — the same number is reused.
    - Assign finger numbers 1, 2, 3, 4 in order of ascending fret.
    """
    fingers: list[int] = [0] * len(frets)
    fretted = [(s_idx, fv) for s_idx, fv in enumerate(frets) if fv > 0]
    if not fretted:
        return fingers
    fretted_sorted = sorted(fretted, key=lambda t: (t[1], t[0]))
    fret_to_finger: dict[int, int] = {}
    next_f = 1
    for s_idx, fv in fretted_sorted:
        if fv not in fret_to_finger:
            fret_to_finger[fv] = min(next_f, 4)
            next_f += 1
        fingers[s_idx] = fret_to_finger[fv]
    return fingers


class GpifAdapter(BaseParser):
    """Parse Guitar Pro 7/8 files (.gp) into NoteEvent sequences.

    The .gp file is a ZIP archive; this adapter reads ``Content/score.gpif``
    and extracts notes from the first guitar (non-drum, non-bass) track.

    After a successful call to :meth:`parse`, the :attr:`track_name` attribute
    holds the name of the selected guitar track (e.g. ``"E. Guitar I"``).

    Example:
        >>> adapter = GpifAdapter()
        >>> events = adapter.parse(Path("Hotel California.gp"))
        >>> events[0].string_hint
        1
    """

    #: Name of the last selected guitar track; set after each call to parse().
    track_name: str = ""
    #: MIDI program number (0-127) of the selected track; -1 if unknown.
    midi_program: int = -1
    #: Section/rehearsal markers: {1-based measure number → section title}.
    #: Set after each call to parse().
    section_markers: dict[int, str] = {}
    #: Chord diagrams from the DiagramCollection of the selected track.
    #: Set after each call to parse() or parse_track().
    chord_diagrams: list[ChordDiagram] = []
    #: Beat-level chord name annotations: {onset_str → chord_name}.
    #: Set after each call to parse() or parse_track().
    chord_markers: dict[str, str] = {}
    #: Measure duration in quarter-note beats (e.g. 3.0 for 6/8, 4.0 for 4/4).
    #: Set after each call to parse() or parse_track().
    beats_per_measure: float = 4.0
    #: Time signature denominator of the first MasterBar (e.g. 8 for 6/8, 4 for 4/4).
    #: Set after each call to parse() or parse_track().
    time_denominator: int = 4
    #: Key signature expressed as fifths: positive = sharps, negative = flats.
    #: Set after each call to parse() or parse_track().
    key_signature_fifths: int = 0
    #: True if the first MasterBar is a pickup bar (anacrusis/upbeat).
    #: Set after each call to parse() or parse_track().
    has_anacrusis: bool = False

    def supports(self, path: Path) -> bool:
        """Return True for .gp files (Guitar Pro 7/8)."""
        return path.suffix.lower() in _SUPPORTED_EXTENSIONS

    def parse(self, path: Path) -> list[NoteEvent]:
        """Parse a .gp file and return NoteEvents for the best guitar track.

        Args:
            path: Path to a .gp (Guitar Pro 7/8) file.

        Returns:
            List of NoteEvent ordered by onset time (ascending).

        Raises:
            UnsupportedFormatError: If the suffix is not .gp.
            ParseError: If the file is missing, not a valid GP archive, or
                the GPIF XML cannot be parsed.
        """
        if not self.supports(path):
            raise UnsupportedFormatError(
                f"GpifAdapter only handles .gp files; got '{path.suffix}'."
            )
        if not path.exists():
            raise ParseError(f"File not found: {path}")

        try:
            root = _load_gpif(path)
        except Exception as exc:
            raise ParseError(f"Failed to read GPIF from '{path}': {exc}") from exc

        track_id, open_pitches = _find_guitar_track(root)
        if track_id is None:
            logger.warning("No guitar track found in '%s'. Returning empty sequence.", path)
            self.track_name = ""
            return []
        track_index = _track_bar_index(root, track_id)
        if track_index is None:
            raise ParseError(f"Selected track id={track_id} not found in '{path}'.")

        # Capture track name and chord diagrams for callers
        self.track_name = ""
        self.chord_diagrams = []
        for _trk in root.findall("Tracks/Track"):
            if _trk.get("id") == str(track_id):
                self.track_name = _trk.findtext("Name", "").strip()
                self.chord_diagrams = self._parse_diagram_collection(_trk)
                break

        tempo_map = _build_tempo_map(root)
        rhythm_map = _build_rhythm_map(root)
        note_map = _build_note_map(root)
        self.section_markers = _build_section_markers(root)
        self.beats_per_measure = _get_beats_per_measure(root)
        self.time_denominator = _get_time_denominator(root)
        self.key_signature_fifths = _get_key_signature_fifths(root)
        self.has_anacrusis = root.find("MasterTrack/Anacrusis") is not None
        diag_name_map = {str(cd.source_id): cd.name for cd in self.chord_diagrams}
        self.chord_markers = _extract_gpif_beat_chord_markers(
            root, track_index, rhythm_map, diag_name_map
        )

        return _extract_events(root, track_index, open_pitches, tempo_map, rhythm_map, note_map)

    def list_guitar_tracks(self, path: Path) -> list[tuple[int, str, list[int]]]:
        """Return all guitar tracks in the file as (track_id, name, open_pitches).

        Useful for multi-track export: iterate and call parse_track() for each.

        Args:
            path: Path to a .gp file.

        Returns:
            List of (track_id, track_name, open_string_pitches), ordered by
            descending score (best track first).
        """
        if not path.exists():
            raise ParseError(f"File not found: {path}")
        try:
            root = _load_gpif(path)
        except Exception as exc:
            raise ParseError(f"Failed to read GPIF from '{path}': {exc}") from exc
        return _list_guitar_tracks(root)

    def parse_track(self, path: Path, track_id: int) -> list[NoteEvent]:
        """Parse a specific track by its numeric track_id.

        Also sets :attr:`track_name` and :attr:`section_markers`.

        Args:
            path: Path to a .gp file.
            track_id: Numeric track id as returned by :meth:`list_guitar_tracks`.

        Returns:
            List of NoteEvent ordered by onset time (ascending).
        """
        if not path.exists():
            raise ParseError(f"File not found: {path}")
        try:
            root = _load_gpif(path)
        except Exception as exc:
            raise ParseError(f"Failed to read GPIF from '{path}': {exc}") from exc

        # Find the tuning (open_pitches) for this specific track.
        open_pitches: list[int] = []
        self.track_name = ""
        self.midi_program = -1
        for track in root.findall("Tracks/Track"):
            if track.get("id") == str(track_id):
                self.track_name = track.findtext("Name", "").strip()
                prog_text = track.findtext(".//MIDI/Program") or ""
                self.midi_program = int(prog_text) if prog_text.isdigit() else -1
                staff = track.find("Staves/Staff")
                if staff is not None:
                    props = {p.get("name", ""): p for p in staff.findall("Properties/Property")}
                    pitches_text = props.get("Tuning", ET.Element("x")).findtext("Pitches") or ""
                    open_pitches = [int(x) for x in pitches_text.split() if x.strip()]
                break

        if not open_pitches:
            raise ParseError(f"Track {track_id} has no tuning data in '{path}'.")
        track_index = _track_bar_index(root, track_id)
        if track_index is None:
            raise ParseError(f"Track {track_id} not found in '{path}'.")

        tempo_map = _build_tempo_map(root)
        rhythm_map = _build_rhythm_map(root)
        note_map = _build_note_map(root)
        self.section_markers = _build_section_markers(root)
        self.beats_per_measure = _get_beats_per_measure(root)
        self.time_denominator = _get_time_denominator(root)
        self.key_signature_fifths = _get_key_signature_fifths(root)
        self.has_anacrusis = root.find("MasterTrack/Anacrusis") is not None

        # Extract chord diagrams for this track.
        for track in root.findall("Tracks/Track"):
            if track.get("id") == str(track_id):
                self.chord_diagrams = self._parse_diagram_collection(track)
                break

        diag_name_map = {str(cd.source_id): cd.name for cd in self.chord_diagrams}
        self.chord_markers = _extract_gpif_beat_chord_markers(
            root, track_index, rhythm_map, diag_name_map
        )

        return _extract_events(root, track_index, open_pitches, tempo_map, rhythm_map, note_map)

    def _parse_diagram_collection(self, track_el: ET.Element) -> list[ChordDiagram]:
        """Parse the DiagramCollection from a Track element.

        Args:
            track_el: The ``<Track>`` XML element for the selected track.

        Returns:
            List of ChordDiagram objects, one per ``<Item>`` in the collection.
            Returns an empty list if no DiagramCollection is found.
        """
        diagrams: list[ChordDiagram] = []

        staff = track_el.find("Staves/Staff")
        if staff is None:
            return diagrams

        # Find the DiagramCollection property among the Staff properties.
        diagram_prop: ET.Element | None = None
        for prop in staff.findall("Properties/Property"):
            if prop.get("name") == "DiagramCollection":
                diagram_prop = prop
                break

        if diagram_prop is None:
            return diagrams

        for item in diagram_prop.findall("Items/Item"):
            item_id_str = item.get("id", "0")
            item_name = item.get("name", "")

            diagram_el = item.find("Diagram")
            if diagram_el is None:
                continue

            try:
                base_fret = int(diagram_el.get("baseFret", "0"))
            except ValueError:
                base_fret = 0
            try:
                string_count = int(diagram_el.get("stringCount", "6"))
            except ValueError:
                string_count = 6

            # Initialize all strings as muted (-1).
            frets: list[int] = [-1] * string_count

            for fret_el in diagram_el.findall("Fret"):
                try:
                    # GPIF string index 1 = high e (index 0 in our frets list).
                    s_idx = int(fret_el.get("string", "1")) - 1
                    f_val = int(fret_el.get("fret", "-1"))
                except ValueError:
                    continue
                if 0 <= s_idx < string_count:
                    frets[s_idx] = f_val

            try:
                source_id = int(item_id_str)
            except ValueError:
                source_id = 0

            fingers = _compute_chord_fingers(frets)
            diagrams.append(
                ChordDiagram(
                    name=item_name,
                    frets=frets,
                    string_count=string_count,
                    base_fret=base_fret,
                    source_id=source_id,
                    fingers=fingers,
                )
            )

        logger.debug(
            "Parsed %d chord diagram(s) from DiagramCollection.", len(diagrams)
        )

        # Detect and repair corrupted diagram sets (all entries share identical frets).
        from fretwise.patterns.chord_library import is_corrupt_diagram_set, repair_diagrams

        if is_corrupt_diagram_set(diagrams):
            logger.warning(
                "Chord diagram data appears corrupted (all %d diagrams have identical "
                "frets). Replacing with library voicings.",
                len(diagrams),
            )
            diagrams = repair_diagrams(diagrams)

        return diagrams


# ---------------------------------------------------------------------------
# Loading
# ---------------------------------------------------------------------------


def _load_gpif(path: Path) -> ET.Element:
    """Open the .gp ZIP and return the parsed GPIF XML root element."""
    try:
        with zipfile.ZipFile(path) as zf:
            with zf.open("Content/score.gpif") as f:
                return ET.parse(f).getroot()
    except zipfile.BadZipFile as exc:
        raise ParseError(f"'{path}' is not a valid ZIP/GP archive.") from exc
    except KeyError as exc:
        raise ParseError(f"'{path}' has no Content/score.gpif inside.") from exc


# ---------------------------------------------------------------------------
# Lookup maps
# ---------------------------------------------------------------------------


def _get_beats_per_measure(root: ET.Element) -> float:
    """Return measure duration in quarter-note beats (e.g. 3.0 for 6/8, 4.0 for 4/4).

    The internal timing model uses quarter-note beats throughout.  For compound
    meters (6/8, 9/8, 12/8 …) the numerator alone is NOT a correct measure
    duration: 6/8 = 6 eighth notes = 3.0 quarter beats.  Formula:
        quarter_beats = numerator * (4 / denominator)
    """
    first_bar = root.find("MasterBars/MasterBar")
    if first_bar is None:
        return 4.0
    time_str = first_bar.findtext("Time", "4/4")
    try:
        numerator_str, denominator_str = time_str.split("/")
        numerator = int(numerator_str)
        denominator = int(denominator_str)
        if denominator <= 0:
            return 4.0
        return numerator * 4.0 / denominator
    except (ValueError, AttributeError):
        return 4.0


def _get_time_denominator(root: ET.Element) -> int:
    """Return the denominator of the first MasterBar's time signature (e.g. 8 for 6/8)."""
    first_bar = root.find("MasterBars/MasterBar")
    if first_bar is None:
        return 4
    time_str = first_bar.findtext("Time", "4/4")
    try:
        _, denominator_str = time_str.split("/")
        denominator = int(denominator_str)
        return max(1, denominator)
    except (ValueError, AttributeError):
        return 4


def _get_key_signature_fifths(root: ET.Element) -> int:
    """Return the key signature as fifths from the first MasterBar.

    Reads ``<MasterBar><Key><AccidentalCount>`` where a positive value means
    sharps and a negative value means flats, matching the SMuFL/music21 fifths
    convention (e.g. +2 = D major, -3 = Eb major).
    """
    first_bar = root.find("MasterBars/MasterBar")
    if first_bar is None:
        return 0
    acc_text = first_bar.findtext("Key/AccidentalCount", "0").strip()
    try:
        return int(acc_text)
    except (ValueError, AttributeError):
        return 0


def _build_section_markers(root: ET.Element) -> dict[int, str]:
    """Return {1-based measure number → section title} from MasterBar markers.

    Handles both ``<Section><Text>…</Text></Section>`` (GP7/8) and the older
    ``<Marker><Title>…</Title></Marker>`` style within each ``<MasterBar>``.
    """
    markers: dict[int, str] = {}
    for bar_num, masterbar in enumerate(root.findall("MasterBars/MasterBar")):
        # GP7/8: <Section><Text>Intro</Text></Section>
        title = masterbar.findtext("Section/Text", "").strip()
        # Fallback: <Marker><Title>…</Title></Marker>
        if not title:
            title = masterbar.findtext("Marker/Title", "").strip()
        if title:
            markers[bar_num + 1] = title
    return markers


def _build_tempo_map(root: ET.Element) -> list[tuple[int, float]]:
    """Return a list of (bar_index, bpm) sorted by bar_index.

    Reads tempo automations from MasterTrack.  The first entry always covers
    bar 0 (fallback to 120 BPM if absent).
    """
    entries: list[tuple[int, float]] = []
    for auto in root.findall("MasterTrack/Automations/Automation"):
        if auto.findtext("Type") == "Tempo":
            bar = int(auto.findtext("Bar") or 0)
            value_str = (auto.findtext("Value") or "120").split()[0]
            entries.append((bar, float(value_str)))
    if not entries:
        entries.append((0, 120.0))
    return sorted(entries, key=lambda t: t[0])


def _build_rhythm_map(root: ET.Element) -> dict[str, float]:
    """Return {rhythm_id: beats} mapping from the <Rhythms> section."""
    result: dict[str, float] = {}
    for r in root.findall("Rhythms/Rhythm"):
        rid = r.get("id", "")
        note_value = r.findtext("NoteValue") or "Quarter"
        beats = _NOTE_VALUE_BEATS.get(note_value, 1.0)

        # Augmentation dots (on the Rhythm element in older GPIF)
        dot = r.find("AugmentationDot")
        if dot is not None:
            count = int(dot.get("count", "1"))
            extra = beats
            for _ in range(count):
                extra /= 2.0
                beats += extra

        # Tuplet: PrimaryTuplet num="3" den="2" → × (den/num)
        tuplet = r.find("PrimaryTuplet")
        if tuplet is not None:
            num = int(tuplet.get("num", "1"))
            den = int(tuplet.get("den", "1"))
            if num != den:
                beats = beats * den / num

        result[rid] = beats
    return result


def _build_rhythm_tuplet_map(root: ET.Element) -> dict[str, tuple[int, int] | None]:
    """Return {rhythm_id: (actual, normal)} for tuplet rhythms, or None otherwise."""
    result: dict[str, tuple[int, int] | None] = {}
    for r in root.findall("Rhythms/Rhythm"):
        rid = r.get("id", "")
        tuplet = r.find("PrimaryTuplet")
        if tuplet is not None:
            num = int(tuplet.get("num", "1"))
            den = int(tuplet.get("den", "1"))
            result[rid] = (num, den) if num != den else None
        else:
            result[rid] = None
    return result


class _NoteData:
    """Lightweight parsed representation of a GPIF Note element."""

    __slots__ = (
        "gpif_string", "fret", "midi_pitch", "is_tie_dest", "articulation", "let_ring",
        "bend_value", "bend_type", "slide_type", "harmonic_type", "harmonic_fret",
        "muted", "palm_muted", "tapping", "accent", "accent_strong", "tremolo_picking",
        "vibrato_wide",
        "pitch_step", "pitch_accidental", "pitch_octave",
        "ghost", "staccato", "strum_direction", "slap", "pop", "rasgueado", "golpe",
    )

    def __init__(
        self,
        gpif_string: int,
        fret: int,
        midi_pitch: int,
        is_tie_dest: bool,
        articulation: Articulation,
        let_ring: bool = False,
        bend_value: float | None = None,
        bend_type: str | None = None,
        slide_type: str | None = None,
        harmonic_type: str | None = None,
        harmonic_fret: int | None = None,
        muted: bool = False,
        palm_muted: bool = False,
        tapping: bool = False,
        accent: bool = False,
        accent_strong: bool = False,
        tremolo_picking: bool = False,
        vibrato_wide: bool = False,
        pitch_step: str | None = None,
        pitch_accidental: str | None = None,
        pitch_octave: int | None = None,
        ghost: bool = False,
        staccato: bool = False,
        strum_direction: str | None = None,
        slap: bool = False,
        pop: bool = False,
        rasgueado: bool = False,
        golpe: bool = False,
    ) -> None:
        self.gpif_string = gpif_string
        self.fret = fret
        self.midi_pitch = midi_pitch
        self.is_tie_dest = is_tie_dest
        self.articulation = articulation
        self.let_ring = let_ring
        self.bend_value = bend_value
        self.bend_type = bend_type
        self.slide_type = slide_type
        self.harmonic_type = harmonic_type
        self.harmonic_fret = harmonic_fret
        self.muted = muted
        self.palm_muted = palm_muted
        self.tapping = tapping
        self.accent = accent
        self.accent_strong = accent_strong
        self.tremolo_picking = tremolo_picking
        self.vibrato_wide = vibrato_wide
        self.pitch_step = pitch_step
        self.pitch_accidental = pitch_accidental
        self.pitch_octave = pitch_octave
        self.ghost = ghost
        self.staccato = staccato
        self.strum_direction = strum_direction
        self.slap = slap
        self.pop = pop
        self.rasgueado = rasgueado
        self.golpe = golpe


def _build_note_map(root: ET.Element) -> dict[str, _NoteData]:
    """Return {note_id: _NoteData} for every Note element."""
    result: dict[str, _NoteData] = {}
    for note in root.findall("Notes/Note"):
        nid = note.get("id", "")

        # Tied-note detection: <Tie destination="true"/> means skip this attack.
        tie_el = note.find("Tie")
        is_tie_dest = tie_el is not None and tie_el.get("destination", "").lower() == "true"

        props: dict[str, ET.Element] = {
            p.get("name", ""): p for p in note.findall("Properties/Property")
        }

        try:
            fret = int(props["Fret"].findtext("Fret") or "0") if "Fret" in props else 0
        except ValueError:
            fret = 0
        try:
            string_text = props["String"].findtext("String") or "0" if "String" in props else "0"
            # Drum notes can have fractional string values (e.g. "5.5") — skip them.
            string_float = float(string_text)
            if string_float != int(string_float):
                result[nid] = _NoteData(0, 0, 0, is_tie_dest=True, articulation=Articulation.NORMAL)
                continue
            gpif_string = int(string_float)
        except ValueError:
            gpif_string = 0

        # Midi property gives the actual sounding MIDI pitch (transpose applied).
        midi_el = props.get("Midi")
        midi_pitch = int(midi_el.findtext("Number") or "0") if midi_el is not None else 0

        note_props = _parse_note_properties(props)
        pitch_step, pitch_accidental, pitch_octave = _parse_notated_pitch(props)

        result[nid] = _NoteData(
            gpif_string, fret, midi_pitch, is_tie_dest,
            articulation=note_props["articulation"],
            let_ring="LetRing" in props,
            bend_value=note_props["bend_value"],
            bend_type=note_props["bend_type"],
            slide_type=note_props["slide_type"],
            harmonic_type=note_props["harmonic_type"],
            harmonic_fret=note_props["harmonic_fret"],
            muted=note_props["muted"],
            palm_muted=note_props["palm_muted"],
            tapping=note_props["tapping"],
            accent=note_props["accent"],
            accent_strong=note_props["accent_strong"],
            tremolo_picking=note_props["tremolo_picking"],
            vibrato_wide=note_props["vibrato_wide"],
            pitch_step=pitch_step,
            pitch_accidental=pitch_accidental,
            pitch_octave=pitch_octave,
            ghost=note_props["ghost"],
            staccato=note_props["staccato"],
            slap=note_props["slap"],
            pop=note_props["pop"],
            golpe=note_props["golpe"],
        )
    return result


def _parse_note_articulation(props: dict[str, ET.Element]) -> Articulation:
    """Derive an Articulation from note Properties.

    Backward-compatible wrapper around :func:`_parse_note_properties`.
    """
    return _parse_note_properties(props)["articulation"]  # type: ignore[return-value]


def _parse_note_properties(props: dict[str, ET.Element]) -> dict:  # type: ignore[type-arg]
    """Extract all notation properties from note Properties dict."""
    result: dict = {  # type: ignore[type-arg]
        "articulation": Articulation.NORMAL,
        "bend_value": None,
        "bend_type": None,
        "slide_type": None,
        "harmonic_type": None,
        "harmonic_fret": None,
        "muted": False,
        "palm_muted": False,
        "tapping": False,
        "accent": False,
        "accent_strong": False,
        "tremolo_picking": False,
        "vibrato_wide": False,
        "ghost": False,
        "staccato": False,
        "slap": False,
        "pop": False,
        "golpe": False,
    }

    # Muted (x note)
    if "Muted" in props:
        result["muted"] = True
        result["articulation"] = Articulation.MUTED

    # Hammer-on / Pull-off — GP5 uses "HammerOn"/"PullOff"; GP7 uses "HopoOrigin"/"HopoDestination".
    # Only the ORIGIN note is marked: the renderer draws the arc forward to the next note on the
    # same string.  HopoDestination alone is left as NORMAL so it doesn't trigger a spurious arc.
    elif "HammerOn" in props or "HopoOrigin" in props:
        result["articulation"] = Articulation.HAMMER_ON
    elif "PullOff" in props:
        result["articulation"] = Articulation.PULL_OFF

    # Slide: parse flags for type
    if "Slide" in props:
        flags_text = props["Slide"].findtext("Flags") or "0"
        try:
            flags = int(flags_text)
        except ValueError:
            flags = 0
        slide_type, art = _parse_slide_flags(flags)
        result["slide_type"] = slide_type
        if result["articulation"] == Articulation.NORMAL:
            result["articulation"] = art

    # Vibrato — only override articulation if not already set to a more specific value
    if "Vibrato" in props:
        vib_type = props["Vibrato"].findtext("Type") or ""
        if "Wide" in vib_type or "Tremolo" in vib_type.lower():
            result["vibrato_wide"] = True
            if result["articulation"] == Articulation.NORMAL:
                result["articulation"] = Articulation.WIDE_VIBRATO
        else:
            if result["articulation"] == Articulation.NORMAL:
                result["articulation"] = Articulation.VIBRATO

    # Bend
    if "Bend" in props:
        if result["articulation"] == Articulation.NORMAL:
            result["articulation"] = Articulation.BEND
        bend_val, bend_type = _parse_bend(props["Bend"])
        result["bend_value"] = bend_val
        result["bend_type"] = bend_type

    # Harmonic
    if "Harmonic" in props:
        h_type, h_fret = _parse_harmonic(props["Harmonic"])
        result["harmonic_type"] = h_type
        result["harmonic_fret"] = h_fret
        if result["articulation"] == Articulation.NORMAL:
            result["articulation"] = Articulation.HARMONIC

    # Palm mute
    if "PalmMuted" in props:
        result["palm_muted"] = True

    # Tapping
    if "Tapping" in props:
        result["tapping"] = True
        if result["articulation"] == Articulation.NORMAL:
            result["articulation"] = Articulation.TAPPING

    # Accent (may be on beat element, but sometimes on note)
    if "Accent" in props:
        try:
            accent_val = int(props["Accent"].findtext("Flags") or "0")
        except ValueError:
            accent_val = 0
        result["accent"] = bool(accent_val & 1)
        result["accent_strong"] = bool(accent_val & 2)

    # Tremolo picking
    if "TremoloPicking" in props or "Tremolo" in props:
        result["tremolo_picking"] = True
        if result["articulation"] == Articulation.NORMAL:
            result["articulation"] = Articulation.TREMOLO

    # Ghost note — fret shown in parentheses
    if "Ghost" in props or "IsGhost" in props:
        result["ghost"] = True

    # Staccato — short detached note
    if "Staccato" in props:
        result["staccato"] = True

    # Slap / Pop
    if "Slap" in props:
        result["slap"] = True
    if "Popping" in props or "Pop" in props:
        result["pop"] = True

    # Golpe — percussive tap on guitar body
    if "Golpe" in props:
        result["golpe"] = True

    return result


def _parse_slide_flags(flags: int) -> tuple[str | None, Articulation]:
    """Parse GPIF Slide flags into (slide_type, Articulation).

    GP7/8 slide flags (may vary by version):
      1 = ShiftSlide (destination IS re-struck)
      2 = LegatoSlide (destination NOT re-struck)
      4 = SlideOutDown
      8 = SlideOutUp
      16 = SlideInFromAbove
      32 = SlideInFromBelow
    """
    if flags & 1:
        return SlideType.SHIFT, Articulation.SLIDE
    if flags & 2:
        return SlideType.LEGATO, Articulation.SLIDE
    if flags & 4:
        return SlideType.SLIDE_OUT_DOWN, Articulation.SLIDE
    if flags & 8:
        return SlideType.SLIDE_OUT_UP, Articulation.SLIDE
    if flags & 16:
        return SlideType.SLIDE_IN_ABOVE, Articulation.SLIDE
    if flags & 32:
        return SlideType.SLIDE_IN_BELOW, Articulation.SLIDE
    return None, Articulation.SLIDE


def _parse_notated_pitch(
    props: dict[str, ET.Element],
) -> tuple[str | None, str | None, int | None]:
    """Return explicit GPIF pitch spelling as (step, accidental, octave).

    Preference order:
    1. ``TransposedPitch`` (written score pitch)
    2. ``ConcertPitch`` (fallback when transposed spelling is absent)
    """
    pitch_prop = props.get("TransposedPitch") or props.get("ConcertPitch")
    if pitch_prop is None:
        return None, None, None

    pitch_el = pitch_prop.find("Pitch")
    if pitch_el is None:
        return None, None, None

    step_raw = (pitch_el.findtext("Step") or "").strip().upper()
    step = step_raw if step_raw in {"A", "B", "C", "D", "E", "F", "G"} else None

    accidental_raw = (pitch_el.findtext("Accidental") or "").strip()
    if accidental_raw in {"#", "♯"}:
        accidental = "sharp"
    elif accidental_raw in {"b", "♭"}:
        accidental = "flat"
    elif accidental_raw:
        accidental = "natural"
    else:
        accidental = None

    octave_text = (pitch_el.findtext("Octave") or "").strip()
    try:
        octave = int(octave_text)
    except ValueError:
        octave = None

    return step, accidental, octave


def _parse_bend(bend_prop: ET.Element) -> tuple[float | None, str | None]:
    """Parse a Bend Property element into (max_value_semitones, bend_type)."""
    bend_el = bend_prop.find("Bend")
    if bend_el is None:
        return None, None
    points = []
    for pt in bend_el.findall("Points/Point"):
        try:
            pos = int(pt.findtext("Position") or "0")
            val = int(pt.findtext("Value") or "0")
            points.append((pos, val))
        except ValueError:
            continue
    if not points:
        return None, None

    max_val = max(v for _, v in points)
    semitones = max_val / 100.0  # 100 = 1 semitone in GPIF

    if not semitones:
        return None, None

    # Classify bend type by point pattern
    starts_bent = points[0][1] >= max_val * 0.9 if points else False
    ends_at_zero = points[-1][1] == 0 if len(points) > 1 else False

    if starts_bent and ends_at_zero:
        bend_type: str = BendType.PRE_BEND_RELEASE
    elif starts_bent:
        bend_type = BendType.PRE_BEND
    elif ends_at_zero:
        bend_type = BendType.RELEASE
    elif semitones < 0.3:
        bend_type = BendType.GRACE
    else:
        bend_type = BendType.NORMAL

    return semitones, bend_type


def _parse_harmonic(harm_prop: ET.Element) -> tuple[str | None, int | None]:
    """Parse a Harmonic Property element into (harmonic_type, fret)."""
    harm_el = harm_prop.find("HarmonicType")
    if harm_el is None:
        # Try direct type text
        type_text = harm_prop.findtext("Type") or harm_prop.text or ""
    else:
        type_text = harm_el.text or ""
    type_text = type_text.strip()

    fret_text = harm_prop.findtext("Fret") or harm_prop.findtext("HarmonicFret") or ""
    try:
        harm_fret: int | None = int(fret_text)
    except ValueError:
        harm_fret = None

    type_map: dict[str, str] = {
        "Natural": HarmonicType.NATURAL,
        "NaturalHarmonic": HarmonicType.NATURAL,
        "Artificial": HarmonicType.ARTIFICIAL,
        "ArtificialHarmonic": HarmonicType.ARTIFICIAL,
        "Pinch": HarmonicType.PINCH,
        "PinchHarmonic": HarmonicType.PINCH,
        "Tapped": HarmonicType.HARP,
        "Harp": HarmonicType.HARP,
        "Semi": HarmonicType.NATURAL,
    }
    h_type: str | None = type_map.get(type_text, HarmonicType.NATURAL)
    return h_type, harm_fret


# ---------------------------------------------------------------------------
# Track selection
# ---------------------------------------------------------------------------


def _list_guitar_tracks(root: ET.Element) -> list[tuple[int, str, list[int]]]:
    """Return all guitar tracks as (track_id, name, open_pitches), best first."""
    _GUITAR_PROGRAMS = frozenset(range(24, 32))
    _EXCLUDED_TYPES = frozenset(
        {"drumkit", "voice", "electricbass", "acousticbass", "saxophone", "trumpet",
         "trombone", "violin", "cello", "piano", "organ", "strings"}
    )

    results: list[tuple[tuple[int, int], int, str, list[int]]] = []

    for track in root.findall("Tracks/Track"):
        tid_str = track.get("id", "")
        if not tid_str.isdigit():
            continue
        tid = int(tid_str)

        inst_type = (track.findtext("InstrumentSet/Type") or "").lower()
        if inst_type in _EXCLUDED_TYPES:
            continue

        program_text = track.findtext(".//MIDI/Program") or ""
        program = int(program_text) if program_text.isdigit() else -1
        explicit_guitar = "guitar" in inst_type
        program_guitar = program in _GUITAR_PROGRAMS

        if not explicit_guitar and not program_guitar:
            continue

        name = track.findtext("Name", "").strip()
        staff = track.find("Staves/Staff")
        if staff is None:
            continue
        props = {p.get("name", ""): p for p in staff.findall("Properties/Property")}
        if "Tuning" not in props:
            continue
        pitches_text = props["Tuning"].findtext("Pitches") or ""
        pitches = [int(x) for x in pitches_text.split() if x.strip()]
        if not pitches or all(p == 0 for p in pitches):
            continue

        type_score = 2 if explicit_guitar else 1
        string_score = 2 if len(pitches) == 6 else 1
        results.append(((type_score, string_score), tid, name, pitches))

    results.sort(key=lambda t: t[0], reverse=True)
    return [(tid, name, pitches) for _, tid, name, pitches in results]


def _find_guitar_track(root: ET.Element) -> tuple[int | None, list[int]]:
    """Return (track_index, open_string_pitches) for the best guitar track.

    Selects the highest-scoring explicit guitar track.  Scoring:
    - +2 if ``InstrumentSet/Type`` contains "guitar" (explicit guitar type).
    - +1 if the Standard MIDI program is in the guitar range 24–31.
    - +2 if the track has exactly 6 strings (standard guitar neck).
    - +1 for any other number of non-zero strings.

    Tracks whose type is ``drumKit``, ``voice``, ``electricBass`` or similar
    non-stringed instruments are excluded regardless of MIDI program.

    Returns:
        (None, []) if no suitable track is found.
    """
    _GUITAR_PROGRAMS = frozenset(range(24, 32))  # 24=Nylon, 31=Guitar Harmonics
    _EXCLUDED_TYPES = frozenset(
        {"drumkit", "voice", "electricbass", "acousticbass", "saxophone", "trumpet",
         "trombone", "violin", "cello", "piano", "organ", "strings"}
    )

    candidates: list[tuple[tuple[int, int], int, list[int]]] = []  # (score, tid, pitches)

    for track in root.findall("Tracks/Track"):
        tid_str = track.get("id", "")
        if not tid_str.isdigit():
            continue
        tid = int(tid_str)

        inst_type = (track.findtext("InstrumentSet/Type") or "").lower()
        if inst_type in _EXCLUDED_TYPES:
            continue

        program_text = track.findtext(".//MIDI/Program") or ""
        program = int(program_text) if program_text.isdigit() else -1
        explicit_guitar = "guitar" in inst_type
        program_guitar = program in _GUITAR_PROGRAMS

        if not explicit_guitar and not program_guitar:
            continue

        staff = track.find("Staves/Staff")
        if staff is None:
            continue
        props = {p.get("name", ""): p for p in staff.findall("Properties/Property")}

        if "Tuning" not in props:
            continue
        pitches_text = props["Tuning"].findtext("Pitches") or ""
        pitches = [int(x) for x in pitches_text.split() if x.strip()]
        if not pitches or all(p == 0 for p in pitches):
            continue

        # Higher score = preferred.
        type_score = 2 if explicit_guitar else 1
        string_score = 2 if len(pitches) == 6 else 1
        candidates.append(((type_score, string_score), tid, pitches))

    if not candidates:
        available = []
        for track in root.findall("Tracks/Track"):
            name = track.findtext("Name", "").strip()
            inst_type = track.findtext("InstrumentSet/Type", "") or "unknown"
            available.append(f"'{name}' (type={inst_type})")
        if available:
            logger.warning(
                "No guitar track found. Available tracks: %s", ", ".join(available)
            )
        return None, []

    candidates.sort(key=lambda t: t[0], reverse=True)
    best_score, tid, pitches = candidates[0]
    logger.debug(
        "Selected track %d (score=%s tuning=%s) from %d candidate(s).",
        tid, best_score, pitches, len(candidates),
    )
    return tid, pitches


def _track_bar_index(root: ET.Element, track_id: int) -> int | None:
    """Return the 0-based track position used by MasterBar/Bars references."""
    for idx, track in enumerate(root.findall("Tracks/Track")):
        if track.get("id") == str(track_id):
            return idx
    return None


# ---------------------------------------------------------------------------
# Event extraction
# ---------------------------------------------------------------------------


def _extract_gpif_beat_chord_markers(
    root: ET.Element,
    track_idx: int,
    rhythm_map: dict[str, float],
    diag_name_map: dict[str, str],
) -> dict[str, str]:
    """Return {onset_str → chord_name} from beat-level <Chord> annotations (voice 0 only)."""
    markers: dict[str, str] = {}
    bars_index = {b.get("id"): b for b in root.findall("Bars/Bar")}
    voices_index = {v.get("id"): v for v in root.findall("Voices/Voice")}
    beats_index = {b.get("id"): b for b in root.findall("Beats/Beat")}
    onset = 0.0

    for masterbar in root.findall("MasterBars/MasterBar"):
        measure_duration = _measure_beats(masterbar)
        bar_ids_text = masterbar.findtext("Bars") or ""
        bar_ids = bar_ids_text.split()
        if track_idx >= len(bar_ids):
            onset += measure_duration
            continue

        bar_id = bar_ids[track_idx]
        bar_el = bars_index.get(bar_id)
        if bar_el is None:
            onset += measure_duration
            continue

        voice_ids = (bar_el.findtext("Voices") or "").split()
        if not voice_ids or voice_ids[0] == "-1":
            onset += measure_duration
            continue

        voice_el = voices_index.get(voice_ids[0])  # voice 0 only
        if voice_el is None:
            onset += measure_duration
            continue

        beat_onset = onset
        for beat_id in (voice_el.findtext("Beats") or "").split():
            beat_el = beats_index.get(beat_id)
            if beat_el is None:
                continue
            rhythm_ref = beat_el.find("Rhythm")
            rid = rhythm_ref.get("ref", "") if rhythm_ref is not None else ""
            beat_duration = rhythm_map.get(rid, 1.0)
            chord_el = beat_el.find("Chord")
            if chord_el is not None:
                # GP7/8 stores the chord diagram ID as text content, not as
                # a "ref" attribute (older GP formats may use ref="N").
                ref = (chord_el.get("ref") or (chord_el.text or "")).strip()
                name = diag_name_map.get(ref, "")
                if name:
                    markers[f"{beat_onset:.6f}"] = name
            beat_onset += beat_duration

        onset += measure_duration

    return markers


def _extract_events(
    root: ET.Element,
    track_idx: int,
    open_pitches: list[int],
    tempo_map: list[tuple[int, float]],
    rhythm_map: dict[str, float],
    note_map: dict[str, _NoteData],
) -> list[NoteEvent]:
    """Walk MasterBars in order and collect NoteEvents from all voices for the given track.

    All GP voices present in each bar are processed; each NoteEvent carries its
    voice index in ``voice_hint`` so the pipeline can run Viterbi per voice.
    """
    rhythm_tuplet_map = _build_rhythm_tuplet_map(root)
    num_strings = len(open_pitches)
    bars_index = {b.get("id"): b for b in root.findall("Bars/Bar")}
    voices_index = {v.get("id"): v for v in root.findall("Voices/Voice")}
    beats_index = {b.get("id"): b for b in root.findall("Beats/Beat")}

    tempo_idx = 0
    current_tempo = tempo_map[0][1] if tempo_map else 120.0
    onset = 0.0
    events: list[NoteEvent] = []

    for bar_num, masterbar in enumerate(root.findall("MasterBars/MasterBar")):
        measure_duration = _measure_beats(masterbar)
        # Advance tempo if a new automation starts at this bar.
        while tempo_idx + 1 < len(tempo_map) and tempo_map[tempo_idx + 1][0] <= bar_num:
            tempo_idx += 1
            current_tempo = tempo_map[tempo_idx][1]

        bar_ids_text = masterbar.findtext("Bars") or ""
        bar_ids = bar_ids_text.split()
        if track_idx >= len(bar_ids):
            onset += measure_duration
            continue

        bar_id = bar_ids[track_idx]
        bar_el = bars_index.get(bar_id)
        if bar_el is None:
            onset += measure_duration
            continue

        voices_text = bar_el.findtext("Voices") or ""
        voice_ids = voices_text.split()

        if not voice_ids or all(v == "-1" for v in voice_ids):
            # Empty or rest-only measure: advance by time signature length.
            onset += measure_duration
            continue

        measure_onset = onset

        for voice_idx, vid in enumerate(voice_ids):
            if vid == "-1":
                continue

            voice_el = voices_index.get(vid)
            if voice_el is None:
                continue

            beats_text = voice_el.findtext("Beats") or ""
            beat_onset = measure_onset

            for beat_id in beats_text.split():
                beat_el = beats_index.get(beat_id)
                if beat_el is None:
                    continue

                rhythm_ref = beat_el.find("Rhythm")
                rid = rhythm_ref.get("ref", "") if rhythm_ref is not None else ""

                # Beat-level dots (some GPIF versions put dots on Beat, not Rhythm).
                beat_duration = rhythm_map.get(rid, 1.0)
                _rt = rhythm_tuplet_map.get(rid)
                beat_tuplet_actual: int | None = _rt[0] if _rt else None
                beat_tuplet_normal: int | None = _rt[1] if _rt else None
                dot_el = beat_el.find("AugmentationDot")
                if dot_el is not None:
                    count = int(dot_el.get("count", "1"))
                    extra = beat_duration
                    for _ in range(count):
                        extra /= 2.0
                        beat_duration += extra

                # Beat-level properties
                beat_props = {p.get("name", ""): p for p in beat_el.findall("Properties/Property")}
                beat_accent = False
                beat_accent_strong = False
                if "Accent" in beat_props:
                    try:
                        acc_flags = int(beat_props["Accent"].findtext("Flags") or "0")
                    except ValueError:
                        acc_flags = 0
                    beat_accent = bool(acc_flags & 1)
                    beat_accent_strong = bool(acc_flags & 2)
                beat_tremolo = "TremoloPicking" in beat_props
                beat_strum: str | None = None
                if "PickStroke" in beat_props:
                    stroke_val = (beat_props["PickStroke"].findtext("Value") or
                                  beat_props["PickStroke"].findtext("direction") or "").lower()
                    if stroke_val in ("up", "u", "1"):
                        beat_strum = "up"
                    elif stroke_val in ("down", "d", "2"):
                        beat_strum = "down"
                beat_rasgueado = "Rasgueado" in beat_props
                beat_golpe = "Golpe" in beat_props

                notes_text = beat_el.findtext("Notes") or ""
                for note_id in notes_text.split():
                    nd = note_map.get(note_id)
                    if nd is None:
                        continue
                    # Tie-destination notes are emitted as regular events so that
                    # measures containing only tied-note continuations are not treated
                    # as empty (which would otherwise trigger spurious whole-measure
                    # rests).  The renderer detects same-pitch consecutive notes and
                    # draws tie arcs automatically.  Notes whose data was not fully
                    # parsed (e.g. drum slots) keep pitch=0 and are already marked;
                    # skip those zero-pitch placeholders only.
                    if nd.is_tie_dest and nd.midi_pitch == 0 and nd.fret == 0 and nd.gpif_string == 0:
                        continue

                    # Convert GPIF string index (0=low) to our convention (1=high).
                    string_num = num_strings - nd.gpif_string

                    events.append(
                        NoteEvent(
                            pitch=nd.midi_pitch,
                            onset=beat_onset,
                            duration=beat_duration,
                            tempo=current_tempo,
                            articulation=nd.articulation,
                            is_tie_dest=nd.is_tie_dest,
                            dynamic=_beat_dynamic(beat_el),
                            string_hint=string_num,
                            fret_hint=nd.fret,
                            voice_hint=voice_idx,
                            let_ring=nd.let_ring,
                            # New notation fields
                            bend_value=nd.bend_value,
                            bend_type=nd.bend_type,
                            slide_type=nd.slide_type,
                            harmonic_type=nd.harmonic_type,
                            harmonic_fret=nd.harmonic_fret,
                            muted=nd.muted,
                            palm_muted=nd.palm_muted,
                            tapping=nd.tapping,
                            accent=nd.accent or beat_accent,
                            accent_strong=nd.accent_strong or beat_accent_strong,
                            tremolo_picking=nd.tremolo_picking or beat_tremolo,
                            vibrato_wide=nd.vibrato_wide,
                            ghost=nd.ghost,
                            staccato=nd.staccato,
                            strum_direction=nd.strum_direction or beat_strum,
                            slap=nd.slap,
                            pop=nd.pop,
                            rasgueado=nd.rasgueado or beat_rasgueado,
                            golpe=nd.golpe or beat_golpe,
                            note_step=nd.pitch_step,
                            note_accidental=nd.pitch_accidental,
                            note_octave=nd.pitch_octave,
                            measure_index=bar_num + 1,
                            tuplet_actual=beat_tuplet_actual,
                            tuplet_normal=beat_tuplet_normal,
                        )
                    )

                beat_onset += beat_duration

        onset = measure_onset + measure_duration

    return sorted(events, key=lambda e: (e.onset, e.voice_hint or 0))


def _measure_beats(masterbar: ET.Element) -> float:
    """Return the duration of a measure in quarter-note beats from its time signature."""
    ts = masterbar.findtext("Time") or "4/4"
    try:
        num_str, den_str = ts.split("/")
        return int(num_str) * 4.0 / int(den_str)
    except (ValueError, ZeroDivisionError):
        return 4.0


_DYNAMIC_MAP: dict[str, Dynamic] = {
    "PPP": Dynamic.PP,
    "PP": Dynamic.PP,
    "P": Dynamic.P,
    "MP": Dynamic.MP,
    "MF": Dynamic.MF,
    "F": Dynamic.F,
    "FF": Dynamic.FF,
    "FFF": Dynamic.FF,
}


def _beat_dynamic(beat_el: ET.Element) -> Dynamic:
    """Extract the Dynamic level from a Beat element."""
    text = (beat_el.findtext("Dynamic") or "MF").strip().upper()
    return _DYNAMIC_MAP.get(text, Dynamic.MF)
