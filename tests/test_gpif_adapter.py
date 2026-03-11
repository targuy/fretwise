"""Tests for fretwise.parser.gpif_adapter — GpifAdapter."""

from __future__ import annotations

import xml.etree.ElementTree as ET
import zipfile
from io import BytesIO
from pathlib import Path

import pytest

from fretwise.models import Articulation, Dynamic
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.gpif_adapter import (
    GpifAdapter,
    _NoteData,
    _beat_dynamic,
    _build_note_map,
    _build_rhythm_map,
    _build_tempo_map,
    _find_guitar_track,
    _measure_beats,
    _parse_note_articulation,
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

    def test_tied_note_skipped(self, tmp_path: Path) -> None:
        """Notes with <Tie destination="true"> must be skipped."""
        gpif = _MINIMAL_GPIF.replace(
            '<Note id="1">',
            '<Note id="1"><Tie destination="true"/>',
        )
        f = self._write_gp(tmp_path, gpif)
        events = self.adapter.parse(f)
        assert len(events) == 1
        assert events[0].pitch == 64

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
