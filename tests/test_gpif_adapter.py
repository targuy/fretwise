"""Tests for fretwise.parser.gpif_adapter — GpifAdapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from fretwise.models import Articulation, Dynamic, HarmonicType
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.gpif_adapter import (
    KIND_BASS,
    KIND_DRUMS,
    KIND_GUITAR,
    KIND_OTHER,
    KIND_VOCAL,
    GpifAdapter,
    _beat_dynamic,
    _build_note_map,
    _build_rhythm_map,
    _build_tempo_map,
    _classify_track_kind,
    _harmonic_node_offset,
    _list_all_tracks,
    _measure_beats,
    _NoteData,
    _parse_harmonic,
    _parse_int_fret,
    _parse_note_articulation,
    classify_kind_for_program,
)

# ---------------------------------------------------------------------------
# Helpers — minimal GPIF XML builders
# ---------------------------------------------------------------------------


def _xml(content: str) -> ET.Element:
    return ET.fromstring(content)


def _make_gpif_zip(gpif_xml: str) -> bytes:
    """Return a minimal .gp ZIP archive containing the given GPIF XML."""
    buf = BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("Content/score.gpif", gpif_xml)
    return buf.getvalue()


_MINIMAL_GPIF = """<?xml version="1.0" encoding="utf-8"?>
<GPIF>
  <MasterTrack>
    <Automations>
      <Automation>
        <Type>Tempo</Type><Bar>0</Bar><Position>0</Position>
        <Value>120 2</Value>
      </Automation>
    </Automations>
  </MasterTrack>
  <Tracks>
    <Track id="0">
      <Name>Lead Guitar</Name>
      <InstrumentSet><Type>electricGuitar</Type></InstrumentSet>
      <Staves>
        <Staff>
          <Properties>
            <Property name="Tuning">
              <Pitches>40 45 50 55 59 64</Pitches>
              <Instrument>Guitar</Instrument>
            </Property>
          </Properties>
        </Staff>
      </Staves>
    </Track>
  </Tracks>
  <MasterBars>
    <MasterBar>
      <Time>4/4</Time>
      <Bars>0</Bars>
    </MasterBar>
  </MasterBars>
  <Bars>
    <Bar id="0"><Clef>G2</Clef><Voices>0 -1 -1 -1</Voices></Bar>
  </Bars>
  <Voices>
    <Voice id="0"><Beats>0 1</Beats></Voice>
  </Voices>
  <Beats>
    <Beat id="0">
      <Rhythm ref="0"/>
      <Notes>0</Notes>
    </Beat>
    <Beat id="1">
      <Rhythm ref="0"/>
      <Notes>1</Notes>
    </Beat>
  </Beats>
  <Notes>
    <Note id="0">
      <Properties>
        <Property name="String"><String>4</String></Property>
        <Property name="Fret"><Fret>5</Fret></Property>
        <Property name="Midi"><Number>64</Number></Property>
      </Properties>
    </Note>
    <Note id="1">
      <Properties>
        <Property name="String"><String>5</String></Property>
        <Property name="Fret"><Fret>2</Fret></Property>
        <Property name="Midi"><Number>66</Number></Property>
      </Properties>
    </Note>
  </Notes>
  <Rhythms>
    <Rhythm id="0"><NoteValue>Quarter</NoteValue></Rhythm>
  </Rhythms>
</GPIF>"""


_NON_POSITIONAL_TRACK_IDS_GPIF = """<?xml version="1.0" encoding="utf-8"?>
<GPIF>
  <MasterTrack>
    <Automations>
      <Automation>
        <Type>Tempo</Type><Bar>0</Bar><Position>0</Position>
        <Value>120 2</Value>
      </Automation>
    </Automations>
  </MasterTrack>
  <Tracks>
    <Track id="10">
      <Name>Guitar A</Name>
      <InstrumentSet><Type>electricGuitar</Type></InstrumentSet>
      <Staves>
        <Staff>
          <Properties>
            <Property name="Tuning">
              <Pitches>40 45 50 55 59 64</Pitches>
              <Instrument>Guitar</Instrument>
            </Property>
          </Properties>
        </Staff>
      </Staves>
    </Track>
    <Track id="42">
      <Name>Guitar B</Name>
      <InstrumentSet><Type>electricGuitar</Type></InstrumentSet>
      <Staves>
        <Staff>
          <Properties>
            <Property name="Tuning">
              <Pitches>40 45 50 55 59 64</Pitches>
              <Instrument>Guitar</Instrument>
            </Property>
          </Properties>
        </Staff>
      </Staves>
    </Track>
  </Tracks>
  <MasterBars>
    <MasterBar>
      <Time>4/4</Time>
      <Bars>0 1</Bars>
    </MasterBar>
  </MasterBars>
  <Bars>
    <Bar id="0"><Clef>G2</Clef><Voices>0 -1 -1 -1</Voices></Bar>
    <Bar id="1"><Clef>G2</Clef><Voices>1 -1 -1 -1</Voices></Bar>
  </Bars>
  <Voices>
    <Voice id="0"><Beats>0</Beats></Voice>
    <Voice id="1"><Beats>1</Beats></Voice>
  </Voices>
  <Beats>
    <Beat id="0"><Rhythm ref="0"/><Notes>0</Notes></Beat>
    <Beat id="1"><Rhythm ref="0"/><Notes>1</Notes></Beat>
  </Beats>
  <Notes>
    <Note id="0">
      <Properties>
        <Property name="String"><String>4</String></Property>
        <Property name="Fret"><Fret>3</Fret></Property>
        <Property name="Midi"><Number>60</Number></Property>
      </Properties>
    </Note>
    <Note id="1">
      <Properties>
        <Property name="String"><String>4</String></Property>
        <Property name="Fret"><Fret>5</Fret></Property>
        <Property name="Midi"><Number>62</Number></Property>
      </Properties>
    </Note>
  </Notes>
  <Rhythms>
    <Rhythm id="0"><NoteValue>Quarter</NoteValue></Rhythm>
  </Rhythms>
</GPIF>"""


# ---------------------------------------------------------------------------
# GpifAdapter.supports()
# ---------------------------------------------------------------------------


class TestSupports:
    def setup_method(self) -> None:
        self.adapter = GpifAdapter()

    def test_supports_gp(self) -> None:
        assert self.adapter.supports(Path("song.gp"))
        assert self.adapter.supports(Path("song.GP"))

    @pytest.mark.parametrize("ext", [".gp5", ".gp4", ".gpx", ".xml", ".mid"])
    def test_does_not_support_other(self, ext: str) -> None:
        assert not self.adapter.supports(Path(f"song{ext}"))


# ---------------------------------------------------------------------------
# GpifAdapter.parse() — error paths
# ---------------------------------------------------------------------------


class TestParseErrors:
    def setup_method(self) -> None:
        self.adapter = GpifAdapter()

    def test_unsupported_extension_raises(self, tmp_path: Path) -> None:
        with pytest.raises(UnsupportedFormatError):
            self.adapter.parse(tmp_path / "song.gp5")

    def test_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(ParseError, match="not found"):
            self.adapter.parse(tmp_path / "missing.gp")

    def test_not_a_zip_raises(self, tmp_path: Path) -> None:
        f = tmp_path / "bad.gp"
        f.write_bytes(b"not a zip")
        with pytest.raises(ParseError):
            self.adapter.parse(f)

    def test_zip_without_gpif_raises(self, tmp_path: Path) -> None:
        buf = BytesIO()
        with zipfile.ZipFile(buf, "w") as zf:
            zf.writestr("other.txt", "hello")
        f = tmp_path / "no_gpif.gp"
        f.write_bytes(buf.getvalue())
        with pytest.raises(ParseError):
            self.adapter.parse(f)


# ---------------------------------------------------------------------------
# Happy path — parsing from in-memory archive
# ---------------------------------------------------------------------------


class TestParseHappyPath:
    def setup_method(self) -> None:
        self.adapter = GpifAdapter()

    def _write_gp(self, tmp_path: Path, gpif: str) -> Path:
        f = tmp_path / "song.gp"
        f.write_bytes(_make_gpif_zip(gpif))
        return f

    def test_two_notes_parsed(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        assert len(events) == 2

    def test_note_pitch_from_midi_property(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        pitches = {e.pitch for e in events}
        assert 64 in pitches
        assert 66 in pitches

    def test_onset_sequential(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        assert events[0].onset == pytest.approx(0.0)
        assert events[1].onset == pytest.approx(1.0)  # quarter note = 1 beat

    def test_tempo_from_automation(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        assert all(e.tempo == pytest.approx(120.0) for e in events)

    def test_string_hint_converted(self, tmp_path: Path) -> None:
        """GPIF string 4 (B, 0-indexed from low) → string_num 2 (6-string)."""
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        e = next(ev for ev in events if ev.pitch == 64)
        assert e.string_hint == 2   # 6 - 4 = 2
        assert e.fret_hint == 5

    def test_fret_hint_set(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MINIMAL_GPIF)
        events = self.adapter.parse(f)
        e = next(ev for ev in events if ev.pitch == 66)
        assert e.fret_hint == 2

    def test_no_guitar_track_returns_empty(self, tmp_path: Path) -> None:
        gpif = _MINIMAL_GPIF.replace("<Type>electricGuitar</Type>", "<Type>drumKit</Type>")
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse(f)
        assert events == []

    def test_tied_note_emitted_as_event(self, tmp_path: Path) -> None:
        """Notes with <Tie destination="true"> must still be emitted as NoteEvents.

        The tie-destination notehead is a real sounding note (its attack is
        sustained from a previous note); skipping it would leave the measure
        empty and render a spurious whole-measure rest.  The tie arc itself is
        added by _append_standard_connections when two consecutive same-pitch
        notes are contiguous in onset.
        """
        gpif = _MINIMAL_GPIF.replace(
            '<Note id="1">',
            '<Note id="1"><Tie destination="true"/>',
        )
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse(f)
        # Both the origin note (pitch 64) and the tie-destination note (pitch 66)
        # must be present.
        assert len(events) == 2
        pitches = {e.pitch for e in events}
        assert 64 in pitches
        assert 66 in pitches

    def test_fractional_string_note_skipped(self, tmp_path: Path) -> None:
        """Drum notes with fractional String (e.g. "5.5") must be skipped."""
        gpif = _MINIMAL_GPIF.replace(
            "<String>4</String>",
            "<String>5.5</String>",
        )
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse(f)
        # The note with fractional string should be skipped.
        assert all(e.pitch != 64 or e.string_hint is not None for e in events)

    def test_parse_extracts_notated_pitch_spelling(self, tmp_path: Path) -> None:
        gpif = _MINIMAL_GPIF.replace(
            "<Property name=\"Midi\"><Number>64</Number></Property>",
            (
                "<Property name=\"Midi\"><Number>64</Number></Property>"
                "<Property name=\"TransposedPitch\">"
                "<Pitch><Step>F</Step><Accidental>#</Accidental><Octave>5</Octave></Pitch>"
                "</Property>"
            ),
        )
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse(f)
        target = next(event for event in events if event.pitch == 64)

        assert target.note_step == "F"
        assert target.note_accidental == "sharp"
        assert target.note_octave == 5

    def test_parse_track_uses_track_position_not_numeric_track_id(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _NON_POSITIONAL_TRACK_IDS_GPIF)
        events = self.adapter.parse_track(f, 42)

        assert len(events) == 1
        assert events[0].pitch == 62
        assert self.adapter.track_name == "Guitar B"

    def test_parse_works_with_non_positional_track_ids(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _NON_POSITIONAL_TRACK_IDS_GPIF)
        events = self.adapter.parse(f)

        assert len(events) == 1
        assert events[0].pitch == 60


# ---------------------------------------------------------------------------
# _build_tempo_map
# ---------------------------------------------------------------------------


class TestBuildTempoMap:
    def test_single_automation(self) -> None:
        root = _xml(
            "<GPIF><MasterTrack><Automations>"
            "<Automation><Type>Tempo</Type><Bar>0</Bar>"
            "<Value>120 2</Value></Automation>"
            "</Automations></MasterTrack></GPIF>"
        )
        result = _build_tempo_map(root)
        assert result == [(0, 120.0)]

    def test_multiple_automations_sorted(self) -> None:
        root = _xml(
            "<GPIF><MasterTrack><Automations>"
            "<Automation><Type>Tempo</Type><Bar>5</Bar><Value>140 2</Value></Automation>"
            "<Automation><Type>Tempo</Type><Bar>0</Bar><Value>100 2</Value></Automation>"
            "</Automations></MasterTrack></GPIF>"
        )
        result = _build_tempo_map(root)
        assert result[0] == (0, 100.0)
        assert result[1] == (5, 140.0)

    def test_no_automations_defaults_to_120(self) -> None:
        root = _xml("<GPIF><MasterTrack><Automations/></MasterTrack></GPIF>")
        result = _build_tempo_map(root)
        assert result == [(0, 120.0)]


# ---------------------------------------------------------------------------
# _build_rhythm_map
# ---------------------------------------------------------------------------


class TestBuildRhythmMap:
    def test_quarter_note(self) -> None:
        root = _xml(
            "<GPIF><Rhythms>"
            "<Rhythm id='0'><NoteValue>Quarter</NoteValue></Rhythm>"
            "</Rhythms></GPIF>"
        )
        m = _build_rhythm_map(root)
        assert m["0"] == pytest.approx(1.0)

    def test_dotted_quarter(self) -> None:
        root = _xml(
            "<GPIF><Rhythms>"
            '<Rhythm id="0"><NoteValue>Quarter</NoteValue>'
            '<AugmentationDot count="1"/></Rhythm>'
            "</Rhythms></GPIF>"
        )
        m = _build_rhythm_map(root)
        assert m["0"] == pytest.approx(1.5)

    def test_triplet_eighth(self) -> None:
        root = _xml(
            "<GPIF><Rhythms>"
            '<Rhythm id="0"><NoteValue>Eighth</NoteValue>'
            '<PrimaryTuplet num="3" den="2"/></Rhythm>'
            "</Rhythms></GPIF>"
        )
        m = _build_rhythm_map(root)
        assert m["0"] == pytest.approx(0.5 * 2 / 3)

    @pytest.mark.parametrize(
        "note_value, expected",
        [
            ("Whole", 4.0),
            ("Half", 2.0),
            ("Quarter", 1.0),
            ("Eighth", 0.5),
            ("16th", 0.25),
            ("32nd", 0.125),
        ],
    )
    def test_note_values(self, note_value: str, expected: float) -> None:
        root = _xml(
            f"<GPIF><Rhythms>"
            f"<Rhythm id='0'><NoteValue>{note_value}</NoteValue></Rhythm>"
            f"</Rhythms></GPIF>"
        )
        m = _build_rhythm_map(root)
        assert m["0"] == pytest.approx(expected)


# ---------------------------------------------------------------------------
# _parse_note_articulation
# ---------------------------------------------------------------------------


class TestParseNoteArticulation:
    def test_no_effect(self) -> None:
        assert _parse_note_articulation({}) == Articulation.NORMAL

    def test_hammer_on(self) -> None:
        props = {"HammerOn": ET.Element("Property")}
        assert _parse_note_articulation(props) == Articulation.HAMMER_ON

    def test_pull_off(self) -> None:
        props = {"PullOff": ET.Element("Property")}
        assert _parse_note_articulation(props) == Articulation.PULL_OFF

    def test_vibrato(self) -> None:
        props = {"Vibrato": ET.Element("Property")}
        assert _parse_note_articulation(props) == Articulation.VIBRATO

    def test_slide_with_flags(self) -> None:
        slide_el = ET.fromstring("<Property name='Slide'><Flags>4</Flags></Property>")
        props = {"Slide": slide_el}
        assert _parse_note_articulation(props) == Articulation.SLIDE

    def test_bend(self) -> None:
        props = {"Bend": ET.Element("Property")}
        assert _parse_note_articulation(props) == Articulation.BEND

    def test_hammer_takes_priority(self) -> None:
        props = {"HammerOn": ET.Element("Property"), "Vibrato": ET.Element("Property")}
        assert _parse_note_articulation(props) == Articulation.HAMMER_ON


# ---------------------------------------------------------------------------
# _measure_beats
# ---------------------------------------------------------------------------


class TestMeasureBeats:
    @pytest.mark.parametrize(
        "time_sig, expected",
        [
            ("4/4", 4.0),
            ("3/4", 3.0),
            ("6/8", 3.0),
            ("2/2", 4.0),
            ("5/4", 5.0),
        ],
    )
    def test_time_signatures(self, time_sig: str, expected: float) -> None:
        mb = ET.fromstring(f"<MasterBar><Time>{time_sig}</Time></MasterBar>")
        assert _measure_beats(mb) == pytest.approx(expected)

    def test_missing_time_defaults_to_four_four(self) -> None:
        mb = ET.fromstring("<MasterBar/>")
        assert _measure_beats(mb) == pytest.approx(4.0)


# ---------------------------------------------------------------------------
# _beat_dynamic
# ---------------------------------------------------------------------------


class TestBeatDynamic:
    @pytest.mark.parametrize(
        "text, expected",
        [
            ("F", Dynamic.F),
            ("MF", Dynamic.MF),
            ("PP", Dynamic.PP),
            ("FF", Dynamic.FF),
            ("MP", Dynamic.MP),
            ("P", Dynamic.P),
        ],
    )
    def test_known_dynamics(self, text: str, expected: Dynamic) -> None:
        beat = ET.fromstring(f"<Beat><Dynamic>{text}</Dynamic></Beat>")
        assert _beat_dynamic(beat) == expected

    def test_missing_dynamic_defaults_mf(self) -> None:
        beat = ET.fromstring("<Beat/>")
        assert _beat_dynamic(beat) == Dynamic.MF


# ---------------------------------------------------------------------------
# get_adapter integration
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# _build_note_map — GP7/8 note-child interpretation marks
# ---------------------------------------------------------------------------


class TestBuildNoteMapNoteChildren:
    """GP7/8 carries LetRing/Vibrato/Accent/AntiAccent as direct children of
    <Note> (siblings of <Properties>), NOT as named Properties.

    These regression tests pin the children-vs-Properties distinction: the same
    tag names placed *inside* <Properties> must NOT trigger the marks, while the
    note-child layout must.
    """

    @staticmethod
    def _note_map(note_xml: str) -> _NoteData:
        root = _xml(f"<root><Notes>{note_xml}</Notes></root>")
        return _build_note_map(root)["0"]

    def test_let_ring_child_sets_let_ring(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><LetRing/></Note>'
        )
        assert nd.let_ring is True

    def test_let_ring_inside_properties_is_ignored(self) -> None:
        # The historical bug: LetRing looked up in props is never present here.
        nd = self._note_map(
            '<Note id="0"><Properties>'
            '<Property name="LetRing"/>'
            "</Properties></Note>"
        )
        assert nd.let_ring is False

    def test_vibrato_wide_child(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><Vibrato>Wide</Vibrato></Note>'
        )
        assert nd.vibrato_wide is True
        assert nd.articulation == Articulation.WIDE_VIBRATO

    def test_vibrato_slight_child_is_plain_vibrato(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><Vibrato>Slight</Vibrato></Note>'
        )
        assert nd.vibrato_wide is False
        assert nd.articulation == Articulation.VIBRATO

    def test_accent_flag_four_is_accent(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><Accent>4</Accent></Note>'
        )
        assert nd.accent is True
        assert nd.accent_strong is False

    def test_accent_flag_eight_is_strong_accent(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><Accent>8</Accent></Note>'
        )
        assert nd.accent_strong is True
        assert nd.accent is False

    def test_accent_low_flag_is_neither(self) -> None:
        # Flags 1/2 are detached/staccato hints, not accents (>) or marcato.
        nd = self._note_map(
            '<Note id="0"><Properties/><Accent>1</Accent></Note>'
        )
        assert nd.accent is False
        assert nd.accent_strong is False

    def test_anti_accent_child_sets_ghost(self) -> None:
        nd = self._note_map(
            '<Note id="0"><Properties/><AntiAccent/></Note>'
        )
        assert nd.ghost is True

    def test_no_marks_defaults(self) -> None:
        nd = self._note_map('<Note id="0"><Properties/></Note>')
        assert nd.let_ring is False
        assert nd.vibrato_wide is False
        assert nd.accent is False
        assert nd.accent_strong is False
        assert nd.ghost is False


class TestParseIntFret:
    """`_parse_int_fret` tolerates the float fret strings GP8 emits."""

    @pytest.mark.parametrize(
        ("text", "expected"),
        [
            ("12", 12),
            ("12.000000", 12),
            ("2.400000", 2),
            ("4.000000", 4),
            ("", None),
            (None, None),
            ("garbage", None),
        ],
    )
    def test_parse(self, text: str | None, expected: int | None) -> None:
        assert _parse_int_fret(text) == expected


class TestHarmonicNodeOffset:
    """Standard guitar harmonic-node fret → overtone semitone offset."""

    @pytest.mark.parametrize(
        ("node", "offset"),
        [(12, 12), (24, 24), (7, 19), (19, 19), (5, 24), (4, 28), (2, 36)],
    )
    def test_known_nodes(self, node: int, offset: int) -> None:
        assert _harmonic_node_offset(node) == offset

    def test_unknown_node_returns_zero(self) -> None:
        assert _harmonic_node_offset(99) == 0

    def test_none_returns_zero(self) -> None:
        assert _harmonic_node_offset(None) == 0


class TestBuildNoteMapHarmonics:
    """GP7/8 stores HarmonicType/HarmonicFret as *sibling* Properties.

    Regression for the bug where ``_parse_note_properties`` only inspected
    ``props["Harmonic"]`` (which holds just ``<Enable/>``): the type defaulted to
    NATURAL and the fret was always None.

    A harmonic is modelled as a dyad (matching Guitar Pro / MuseScore): the
    fretted *fundamental* keeps its played pitch (``midi_pitch``) and notated
    spelling, while ``harmonic_resultant_pitch`` carries the sounding overtone
    (fundamental + node offset).  The optimizer fingers the fundamental; the
    engraver adds a diamond notehead for the resultant.
    """

    @staticmethod
    def _note(note_xml: str) -> _NoteData:
        root = _xml(f"<root><Notes>{note_xml}</Notes></root>")
        return _build_note_map(root)["0"]

    def _harmonic_note(self, htype: str, hfret: str, midi: int) -> _NoteData:
        return self._note(
            f'<Note id="0"><Properties>'
            f'<Property name="Fret"><Fret>12</Fret></Property>'
            f'<Property name="String"><String>0</String></Property>'
            f'<Property name="Midi"><Number>{midi}</Number></Property>'
            f'<Property name="ConcertPitch"><Pitch>'
            f"<Step>D</Step><Accidental>#</Accidental><Octave>4</Octave>"
            f"</Pitch></Property>"
            f'<Property name="Harmonic"><Enable /></Property>'
            f'<Property name="HarmonicType"><HType>{htype}</HType></Property>'
            f'<Property name="HarmonicFret"><HFret>{hfret}</HFret></Property>'
            f"</Properties></Note>"
        )

    def test_natural_twelfth_fret_node(self) -> None:
        # 12th-fret natural harmonic on D#3 (51): the fretted fundamental stays
        # 51 (where the finger is); the resultant overtone sounds D#4 (63 = 51 + 12).
        nd = self._harmonic_note("natural", "12.000000", midi=51)
        assert nd.harmonic_type == HarmonicType.NATURAL
        assert nd.harmonic_fret == 12
        assert nd.articulation == Articulation.HARMONIC
        assert nd.midi_pitch == 51
        assert nd.harmonic_resultant_pitch == 63

    def test_artificial_harmonic_type_not_defaulted_to_natural(self) -> None:
        nd = self._harmonic_note("artificial", "12.000000", midi=53)
        assert nd.harmonic_type == HarmonicType.ARTIFICIAL
        assert nd.harmonic_fret == 12
        assert nd.midi_pitch == 53
        assert nd.harmonic_resultant_pitch == 65  # 53 + 12

    def test_feedback_harmonic_maps_to_artificial(self) -> None:
        nd = self._harmonic_note("feedback", "12.000000", midi=60)
        assert nd.harmonic_type == HarmonicType.ARTIFICIAL
        assert nd.midi_pitch == 60
        assert nd.harmonic_resultant_pitch == 72  # 60 + 12

    def test_node_two_point_four_adds_three_octaves(self) -> None:
        # Node ≈ fret 2.4 (8th harmonic) sounds three octaves up.
        nd = self._harmonic_note("natural", "2.400000", midi=46)
        assert nd.harmonic_fret == 2
        assert nd.midi_pitch == 46
        assert nd.harmonic_resultant_pitch == 82  # 46 + 36

    def test_fretted_fundamental_keeps_notated_spelling(self) -> None:
        # The fundamental is the played note, so its ConcertPitch spelling (D#4)
        # is retained; the overtone is added separately as the resultant.
        nd = self._harmonic_note("natural", "12.000000", midi=51)
        assert nd.pitch_step == "D"
        assert nd.pitch_octave == 4
        assert nd.pitch_accidental == "sharp"

    def test_unknown_node_leaves_pitch_with_no_resultant(self) -> None:
        nd = self._harmonic_note("natural", "99.000000", midi=51)
        assert nd.harmonic_fret == 99
        assert nd.midi_pitch == 51  # no known offset → unchanged
        assert nd.harmonic_resultant_pitch is None  # no separate overtone
        assert nd.pitch_step == "D"  # spelling kept

    def test_non_harmonic_note_pitch_untouched(self) -> None:
        nd = self._note(
            '<Note id="0"><Properties>'
            '<Property name="String"><String>0</String></Property>'
            '<Property name="Fret"><Fret>12</Fret></Property>'
            '<Property name="Midi"><Number>51</Number></Property>'
            "</Properties></Note>"
        )
        assert nd.harmonic_type is None
        assert nd.midi_pitch == 51
        assert nd.articulation == Articulation.NORMAL


class TestParseHarmonicLegacy:
    """`_parse_harmonic` keeps parsing the legacy nested GP5 layout."""

    def test_nested_type_and_float_fret(self) -> None:
        prop = _xml(
            '<Property name="Harmonic">'
            "<HarmonicType>Artificial</HarmonicType>"
            "<HarmonicFret>12.000000</HarmonicFret>"
            "</Property>"
        )
        h_type, h_fret = _parse_harmonic(prop)
        assert h_type == HarmonicType.ARTIFICIAL
        assert h_fret == 12

    def test_missing_fret_is_none(self) -> None:
        prop = _xml(
            '<Property name="Harmonic"><HarmonicType>Natural</HarmonicType></Property>'
        )
        h_type, h_fret = _parse_harmonic(prop)
        assert h_type == HarmonicType.NATURAL
        assert h_fret is None


_REAL_GP = (
    Path(__file__).resolve().parents[1]
    / "partitions"
    / "Alice in Chains - Would_ - 04-03-2026.gp"
)


@pytest.mark.skipif(not _REAL_GP.exists(), reason="reference .gp fixture absent")
class TestRealFileHarmonics:
    """End-to-end check against the Alice in Chains reference file.

    Lead Guitar (first guitar track) measure 2 is a run of 12th-fret natural
    harmonics.  Each keeps its fretted fundamental pitch (the finger position)
    and carries the overtone (fundamental + 12) in ``harmonic_resultant_pitch``,
    so the engraver renders a fretted notehead plus a stacked diamond.
    """

    def test_measure_two_natural_harmonics(self) -> None:
        adapter = GpifAdapter()
        events = adapter.parse(_REAL_GP)
        harmonics = [
            e for e in events if e.measure_index == 2 and e.harmonic_type is not None
        ]
        assert harmonics, "expected harmonic notes in measure 2"
        for e in harmonics:
            assert e.harmonic_type == HarmonicType.NATURAL
            assert e.harmonic_fret == 12
            assert e.articulation == Articulation.HARMONIC
        # The first harmonic (GPIF note 86) is fretted D#3 = 51 at the 12th fret
        # (where the finger sits) and rings the octave overtone D#4 = 63.
        note_86 = next(e for e in harmonics if e.source_note_id == "86")
        assert note_86.pitch == 51
        assert note_86.fret_hint == 12
        assert note_86.harmonic_resultant_pitch == 63


class TestGetAdapter:
    def test_gp_returns_gpif_adapter(self) -> None:
        from fretwise.parser import get_adapter

        adapter = get_adapter(Path("song.gp"))
        assert isinstance(adapter, GpifAdapter)

    def test_gp5_returns_guitarpro_adapter(self) -> None:
        from fretwise.parser import get_adapter
        from fretwise.parser.guitarpro_adapter import GuitarProAdapter

        adapter = get_adapter(Path("song.gp5"))
        assert isinstance(adapter, GuitarProAdapter)

    def test_unsupported_raises(self) -> None:
        from fretwise.parser import get_adapter

        with pytest.raises(UnsupportedFormatError):
            get_adapter(Path("song.gpx"))


# ---------------------------------------------------------------------------
# Track-kind classification (_classify_track_kind / classify_kind_for_program)
# ---------------------------------------------------------------------------


class TestClassifyTrackKind:
    """Classify guitar / bass / drums / vocal / other from GPIF signals."""

    def test_explicit_guitar_type(self) -> None:
        assert _classify_track_kind("electricguitar", 30, "Lead Guitar") == KIND_GUITAR

    def test_guitar_program_only(self) -> None:
        # Type empty, program in 24-31 guitar range.
        assert _classify_track_kind("", 25, "Steel Strings") == KIND_GUITAR

    def test_electric_bass_type(self) -> None:
        assert _classify_track_kind("electricbass", 34, "Bass") == KIND_BASS

    def test_acoustic_bass_type(self) -> None:
        assert _classify_track_kind("acousticbass", 32, "Upright") == KIND_BASS

    def test_bass_program_only(self) -> None:
        assert _classify_track_kind("", 35, "Fretless") == KIND_BASS

    def test_drumkit_type(self) -> None:
        assert _classify_track_kind("drumkit", 0, "Drums") == KIND_DRUMS

    def test_percussion_type(self) -> None:
        assert _classify_track_kind("percussion", 0, "Congas") == KIND_DRUMS

    def test_vocal_name_with_cello_instrument(self) -> None:
        # The real-world Alice in Chains case: GP stores vocals as cello (42).
        assert _classify_track_kind("cello", 42, "Layne Staley | Lead Vocals") == KIND_VOCAL

    def test_backing_vocals_name(self) -> None:
        assert _classify_track_kind("cello", 42, "Jerry Cantrell | Backing Vocals") == KIND_VOCAL

    def test_vocal_program(self) -> None:
        # Choir Aahs (52) with no type/name hint still classifies as vocal.
        assert _classify_track_kind("", 52, "") == KIND_VOCAL

    def test_voice_instrument_type(self) -> None:
        assert _classify_track_kind("voice", -1, "Singer") == KIND_VOCAL

    def test_unknown_instrument_is_other(self) -> None:
        # Saxophone (66) — not guitar/bass/drums/vocal.
        assert _classify_track_kind("saxophone", 66, "Tenor Sax") == KIND_OTHER

    def test_drums_takes_priority_over_name(self) -> None:
        # A drumkit named with a misleading token still classifies as drums.
        assert _classify_track_kind("drumkit", 0, "Drum & Bass Kit") == KIND_DRUMS

    def test_public_helper_matches_internal(self) -> None:
        # classify_kind_for_program is a thin wrapper (no instrument type).
        assert classify_kind_for_program(30) == KIND_GUITAR
        assert classify_kind_for_program(34) == KIND_BASS
        assert classify_kind_for_program(42, "Lead Vocals") == KIND_VOCAL
        assert classify_kind_for_program(-1, "") == KIND_OTHER


# A multi-instrument GPIF: guitar (id 0), bass (id 1), drums (id 2), vocal (id 3).
_MULTITRACK_GPIF = """<?xml version="1.0" encoding="utf-8"?>
<GPIF>
  <MasterTrack>
    <Automations>
      <Automation>
        <Type>Tempo</Type><Bar>0</Bar><Position>0</Position>
        <Value>120 2</Value>
      </Automation>
    </Automations>
  </MasterTrack>
  <Tracks>
    <Track id="0">
      <Name>Lead Guitar</Name>
      <InstrumentSet><Type>electricGuitar</Type></InstrumentSet>
      <Sounds><Sound><MIDI><Program>30</Program></MIDI></Sound></Sounds>
      <Staves><Staff><Properties>
        <Property name="Tuning"><Pitches>40 45 50 55 59 64</Pitches></Property>
      </Properties></Staff></Staves>
    </Track>
    <Track id="1">
      <Name>Bass Guitar</Name>
      <InstrumentSet><Type>electricBass</Type></InstrumentSet>
      <Sounds><Sound><MIDI><Program>34</Program></MIDI></Sound></Sounds>
      <Staves><Staff><Properties>
        <Property name="Tuning"><Pitches>28 33 38 43</Pitches></Property>
      </Properties></Staff></Staves>
    </Track>
    <Track id="2">
      <Name>Drum Kit</Name>
      <InstrumentSet><Type>drumKit</Type></InstrumentSet>
      <Sounds><Sound><MIDI><Program>0</Program></MIDI></Sound></Sounds>
      <Staves><Staff><Properties>
        <Property name="Tuning"><Pitches>0 0 0 0 0 0</Pitches></Property>
      </Properties></Staff></Staves>
    </Track>
    <Track id="3">
      <Name>Lead Vocals</Name>
      <InstrumentSet><Type>cello</Type></InstrumentSet>
      <Sounds><Sound><MIDI><Program>42</Program></MIDI></Sound></Sounds>
      <Staves><Staff><Properties>
        <Property name="Tuning"><Pitches>39 44 49 54 58 63</Pitches></Property>
      </Properties></Staff></Staves>
    </Track>
  </Tracks>
  <MasterBars>
    <MasterBar><Time>4/4</Time><Bars>0 1 2 3</Bars></MasterBar>
  </MasterBars>
  <Bars>
    <Bar id="0"><Clef>G2</Clef><Voices>0 -1 -1 -1</Voices></Bar>
    <Bar id="1"><Clef>F4</Clef><Voices>1 -1 -1 -1</Voices></Bar>
    <Bar id="2"><Clef>Neutral</Clef><Voices>2 -1 -1 -1</Voices></Bar>
    <Bar id="3"><Clef>G2</Clef><Voices>3 -1 -1 -1</Voices></Bar>
  </Bars>
  <Voices>
    <Voice id="0"><Beats>0</Beats></Voice>
    <Voice id="1"><Beats>1</Beats></Voice>
    <Voice id="2"><Beats>2</Beats></Voice>
    <Voice id="3"><Beats>3</Beats></Voice>
  </Voices>
  <Beats>
    <Beat id="0"><Rhythm ref="0"/><Notes>0</Notes></Beat>
    <Beat id="1"><Rhythm ref="0"/><Notes>1</Notes></Beat>
    <Beat id="2"><Rhythm ref="0"/><Notes>2</Notes></Beat>
    <Beat id="3"><Rhythm ref="0"/><Notes>3</Notes></Beat>
  </Beats>
  <Notes>
    <Note id="0"><Properties>
      <Property name="String"><String>4</String></Property>
      <Property name="Fret"><Fret>5</Fret></Property>
      <Property name="Midi"><Number>64</Number></Property>
    </Properties></Note>
    <Note id="1"><Properties>
      <Property name="String"><String>3</String></Property>
      <Property name="Fret"><Fret>3</Fret></Property>
      <Property name="Midi"><Number>43</Number></Property>
    </Properties></Note>
    <Note id="2"><Properties>
      <Property name="String"><String>0</String></Property>
      <Property name="Fret"><Fret>0</Fret></Property>
      <Property name="Midi"><Number>38</Number></Property>
    </Properties></Note>
    <Note id="3"><Properties>
      <Property name="String"><String>2</String></Property>
      <Property name="Fret"><Fret>1</Fret></Property>
      <Property name="Midi"><Number>60</Number></Property>
    </Properties></Note>
  </Notes>
  <Rhythms>
    <Rhythm id="0"><NoteValue>Quarter</NoteValue></Rhythm>
  </Rhythms>
</GPIF>"""


class TestListAllTracks:
    """_list_all_tracks / GpifAdapter.list_all_tracks list every instrument."""

    def setup_method(self) -> None:
        self.adapter = GpifAdapter()

    def _write_gp(self, tmp_path: Path, gpif: str) -> Path:
        f = tmp_path / "song.gp"
        f.write_bytes(_make_gpif_zip(gpif))
        return f

    def test_lists_all_four_kinds_in_score_order(self) -> None:
        root = _xml(_MULTITRACK_GPIF)
        tracks = _list_all_tracks(root)
        # Order preserved (NOT score-sorted), and every track present.
        assert [(tid, kind) for tid, _name, _t, kind in tracks] == [
            (0, KIND_GUITAR),
            (1, KIND_BASS),
            (2, KIND_DRUMS),
            (3, KIND_VOCAL),
        ]

    def test_includes_name_and_tuning(self) -> None:
        root = _xml(_MULTITRACK_GPIF)
        tracks = {tid: (name, tuning, kind) for tid, name, tuning, kind in _list_all_tracks(root)}
        assert tracks[1] == ("Bass Guitar", [28, 33, 38, 43], KIND_BASS)
        assert tracks[2][1] == [0, 0, 0, 0, 0, 0]  # drum tuning is all-zero

    def test_adapter_method_round_trips(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MULTITRACK_GPIF)
        tracks = self.adapter.list_all_tracks(f)
        assert len(tracks) == 4
        kinds = {tid: kind for tid, _n, _t, kind in tracks}
        assert kinds == {0: KIND_GUITAR, 1: KIND_BASS, 2: KIND_DRUMS, 3: KIND_VOCAL}

    def test_list_all_tracks_superset_of_guitar_only(self, tmp_path: Path) -> None:
        f = self._write_gp(tmp_path, _MULTITRACK_GPIF)
        all_ids = {tid for tid, *_ in self.adapter.list_all_tracks(f)}
        guitar_ids = {tid for tid, *_ in self.adapter.list_guitar_tracks(f)}
        # Guitar-only listing is a strict subset (only the guitar track).
        assert guitar_ids == {0}
        assert guitar_ids < all_ids

    def test_parse_track_on_vocal_track_extracts_pitches(self, tmp_path: Path) -> None:
        # Non-guitar track must parse for staff-only rendering (pitch from MIDI).
        f = self._write_gp(tmp_path, _MULTITRACK_GPIF)
        events = self.adapter.parse_track(f, 3)
        assert len(events) == 1
        assert events[0].pitch == 60

    def test_parse_track_without_tuning_does_not_raise(self, tmp_path: Path) -> None:
        # A track whose staff has no <Tuning> still parses (no ParseError).
        gpif = _MULTITRACK_GPIF.replace(
            '<Property name="Tuning"><Pitches>39 44 49 54 58 63</Pitches></Property>',
            "",
        )
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse_track(f, 3)  # vocal track, now tuningless
        assert len(events) == 1
        assert events[0].pitch == 60
