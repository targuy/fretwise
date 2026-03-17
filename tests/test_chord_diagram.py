"""Tests for chord diagram extraction and rendering.

Covers:
- ChordDiagram dataclass instantiation
- GpifAdapter._parse_diagram_collection on a real fixture file
- draw_chord_diagram produces valid PDF bytes
- render_chord_diagrams_pdf on empty and non-empty lists
- render_pdf_tab with chord_diagrams parameter
"""

from __future__ import annotations

import io
import tempfile
from pathlib import Path

import pytest

from fretwise.export.chord_diagram import draw_chord_diagram, render_chord_diagrams_pdf
from fretwise.export.pdf_tab import render_pdf_tab
from fretwise.models import ChordDiagram, Finger, FingeringResult, FingeringState, NoteEvent

# ---------------------------------------------------------------------------
# Fixture paths
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).parent / "fixtures"
_REBEL_REBEL = _FIXTURES / "David Bowie-Rebel Rebel-09-27-2023.gp"


# ---------------------------------------------------------------------------
# ChordDiagram dataclass
# ---------------------------------------------------------------------------


class TestChordDiagramModel:
    def test_basic_instantiation(self) -> None:
        cd = ChordDiagram(name="Am", frets=[-1, 0, 2, 2, 1, 0])
        assert cd.name == "Am"
        assert cd.frets == [-1, 0, 2, 2, 1, 0]
        assert cd.string_count == 6
        assert cd.base_fret == 0
        assert cd.source_id == 0

    def test_custom_fields(self) -> None:
        cd = ChordDiagram(
            name="F#m7",
            frets=[2, 2, 2, 4, 4, 2],
            string_count=6,
            base_fret=2,
            source_id=3,
        )
        assert cd.name == "F#m7"
        assert cd.base_fret == 2
        assert cd.source_id == 3

    def test_muted_strings(self) -> None:
        # Muted = -1
        cd = ChordDiagram(name="D", frets=[-1, -1, 0, 2, 3, 2])
        assert cd.frets[0] == -1
        assert cd.frets[1] == -1

    def test_open_string(self) -> None:
        cd = ChordDiagram(name="Em", frets=[0, 0, 0, 2, 2, 0])
        assert cd.frets[0] == 0  # open high e

    def test_frets_list_is_independent(self) -> None:
        """Mutating frets of one instance should not affect another."""
        cd1 = ChordDiagram(name="A", frets=[0, 2, 2, 2, 0, -1])
        cd2 = ChordDiagram(name="B", frets=[0, 2, 2, 2, 0, -1])
        cd1.frets[0] = 99
        assert cd2.frets[0] == 0


# ---------------------------------------------------------------------------
# GpifAdapter._parse_diagram_collection
# ---------------------------------------------------------------------------


class TestParseChordDiagrams:
    @pytest.mark.skipif(
        not _REBEL_REBEL.exists(),
        reason="Fixture file not found: David Bowie-Rebel Rebel-09-27-2023.gp",
    )
    def test_rebel_rebel_guitar2_has_diagrams(self) -> None:
        """Guitar 2 track in Rebel Rebel has 4 chord diagrams (D, E, A, Bm)."""
        from fretwise.parser.gpif_adapter import GpifAdapter

        adapter = GpifAdapter()
        tracks = adapter.list_guitar_tracks(_REBEL_REBEL)
        # Find Guitar 2 (track id=2)
        guitar2 = next((t for t in tracks if "Guitar 2" in t[1]), None)
        if guitar2 is None:
            pytest.skip("Guitar 2 track not found in Rebel Rebel fixture")
        track_id, _name, _pitches = guitar2
        adapter.parse_track(_REBEL_REBEL, track_id)
        diagrams = adapter.chord_diagrams
        assert len(diagrams) == 4

    @pytest.mark.skipif(
        not _REBEL_REBEL.exists(),
        reason="Fixture file not found: David Bowie-Rebel Rebel-09-27-2023.gp",
    )
    def test_rebel_rebel_diagram_names(self) -> None:
        """Guitar 2 has diagrams named D, E, A, Bm."""
        from fretwise.parser.gpif_adapter import GpifAdapter

        adapter = GpifAdapter()
        tracks = adapter.list_guitar_tracks(_REBEL_REBEL)
        guitar2 = next((t for t in tracks if "Guitar 2" in t[1]), None)
        if guitar2 is None:
            pytest.skip("Guitar 2 track not found in Rebel Rebel fixture")
        track_id, _name, _pitches = guitar2
        adapter.parse_track(_REBEL_REBEL, track_id)
        names = {d.name for d in adapter.chord_diagrams}
        # Expect standard chord names (not empty).
        assert names == {"D", "E", "A", "Bm"}

    @pytest.mark.skipif(
        not _REBEL_REBEL.exists(),
        reason="Fixture file not found: David Bowie-Rebel Rebel-09-27-2023.gp",
    )
    def test_rebel_rebel_frets_length(self) -> None:
        """All diagrams have frets list matching string_count."""
        from fretwise.parser.gpif_adapter import GpifAdapter

        adapter = GpifAdapter()
        tracks = adapter.list_guitar_tracks(_REBEL_REBEL)
        guitar2 = next((t for t in tracks if "Guitar 2" in t[1]), None)
        if guitar2 is None:
            pytest.skip("Guitar 2 track not found in Rebel Rebel fixture")
        track_id, _name, _pitches = guitar2
        adapter.parse_track(_REBEL_REBEL, track_id)
        for d in adapter.chord_diagrams:
            assert len(d.frets) == d.string_count

    @pytest.mark.skipif(
        not _REBEL_REBEL.exists(),
        reason="Fixture file not found: David Bowie-Rebel Rebel-09-27-2023.gp",
    )
    def test_parse_track_also_sets_chord_diagrams(self) -> None:
        from fretwise.parser.gpif_adapter import GpifAdapter

        adapter = GpifAdapter()
        tracks = adapter.list_guitar_tracks(_REBEL_REBEL)
        assert tracks, "Expected at least one guitar track"
        track_id, _name, _pitches = tracks[0]
        adapter.parse_track(_REBEL_REBEL, track_id)
        # chord_diagrams should be a list (may be empty if track has none).
        assert isinstance(adapter.chord_diagrams, list)

    def test_no_diagrams_when_empty_xml(self) -> None:
        """_parse_diagram_collection on a track element without DiagramCollection."""
        import xml.etree.ElementTree as ET

        from fretwise.parser.gpif_adapter import GpifAdapter

        # Minimal track element with a Staff but no DiagramCollection.
        track_xml = """<Track id="0">
            <Staves>
                <Staff>
                    <Properties/>
                </Staff>
            </Staves>
        </Track>"""
        track_el = ET.fromstring(track_xml)
        adapter = GpifAdapter()
        diagrams = adapter._parse_diagram_collection(track_el)
        assert diagrams == []

    def test_parse_diagram_collection_basic(self) -> None:
        """_parse_diagram_collection parses a minimal hand-crafted XML."""
        import xml.etree.ElementTree as ET

        from fretwise.parser.gpif_adapter import GpifAdapter

        track_xml = """<Track id="0">
            <Staves>
                <Staff>
                    <Properties>
                        <Property name="DiagramCollection">
                            <Items>
                                <Item id="0" name="D">
                                    <Diagram stringCount="6" fretCount="5" baseFret="0">
                                        <Fret string="1" fret="2"/>
                                        <Fret string="2" fret="3"/>
                                        <Fret string="3" fret="2"/>
                                        <Fret string="4" fret="0"/>
                                    </Diagram>
                                </Item>
                            </Items>
                        </Property>
                    </Properties>
                </Staff>
            </Staves>
        </Track>"""
        track_el = ET.fromstring(track_xml)
        adapter = GpifAdapter()
        diagrams = adapter._parse_diagram_collection(track_el)

        assert len(diagrams) == 1
        d = diagrams[0]
        assert d.name == "D"
        assert d.source_id == 0
        assert d.base_fret == 0
        assert d.string_count == 6
        assert len(d.frets) == 6
        # Strings listed: 1→2, 2→3, 3→2, 4→0; unlisted strings default to -1.
        assert d.frets[0] == 2   # string 1 (high e)
        assert d.frets[1] == 3   # string 2
        assert d.frets[2] == 2   # string 3
        assert d.frets[3] == 0   # string 4 (open)
        assert d.frets[4] == -1  # string 5 (not listed = muted)
        assert d.frets[5] == -1  # string 6 (not listed = muted)

    def test_parse_diagram_collection_multiple_items(self) -> None:
        """Multiple <Item> elements are all parsed."""
        import xml.etree.ElementTree as ET

        from fretwise.parser.gpif_adapter import GpifAdapter

        track_xml = """<Track id="0">
            <Staves>
                <Staff>
                    <Properties>
                        <Property name="DiagramCollection">
                            <Items>
                                <Item id="0" name="A">
                                    <Diagram stringCount="6" baseFret="0">
                                        <Fret string="2" fret="2"/>
                                        <Fret string="3" fret="2"/>
                                        <Fret string="4" fret="2"/>
                                    </Diagram>
                                </Item>
                                <Item id="1" name="E">
                                    <Diagram stringCount="6" baseFret="0">
                                        <Fret string="2" fret="2"/>
                                        <Fret string="3" fret="2"/>
                                        <Fret string="4" fret="1"/>
                                    </Diagram>
                                </Item>
                            </Items>
                        </Property>
                    </Properties>
                </Staff>
            </Staves>
        </Track>"""
        track_el = ET.fromstring(track_xml)
        adapter = GpifAdapter()
        diagrams = adapter._parse_diagram_collection(track_el)

        assert len(diagrams) == 2
        assert diagrams[0].name == "A"
        assert diagrams[1].name == "E"
        assert diagrams[0].source_id == 0
        assert diagrams[1].source_id == 1

    def test_parse_diagram_with_base_fret(self) -> None:
        """base_fret > 0 is correctly parsed."""
        import xml.etree.ElementTree as ET

        from fretwise.parser.gpif_adapter import GpifAdapter

        track_xml = """<Track id="0">
            <Staves>
                <Staff>
                    <Properties>
                        <Property name="DiagramCollection">
                            <Items>
                                <Item id="2" name="Bm">
                                    <Diagram stringCount="6" baseFret="2">
                                        <Fret string="1" fret="2"/>
                                        <Fret string="2" fret="3"/>
                                        <Fret string="3" fret="4"/>
                                        <Fret string="4" fret="4"/>
                                        <Fret string="5" fret="2"/>
                                    </Diagram>
                                </Item>
                            </Items>
                        </Property>
                    </Properties>
                </Staff>
            </Staves>
        </Track>"""
        track_el = ET.fromstring(track_xml)
        adapter = GpifAdapter()
        diagrams = adapter._parse_diagram_collection(track_el)

        assert len(diagrams) == 1
        d = diagrams[0]
        assert d.name == "Bm"
        assert d.base_fret == 2
        assert d.source_id == 2


# ---------------------------------------------------------------------------
# draw_chord_diagram
# ---------------------------------------------------------------------------


class TestDrawChordDiagram:
    def _make_canvas(self) -> tuple:
        """Return (canvas, buffer) for in-memory PDF rendering."""
        from reportlab.pdfgen import canvas as rl_canvas

        buf = io.BytesIO()
        c = rl_canvas.Canvas(buf)
        return c, buf

    def test_draw_basic_chord_does_not_raise(self) -> None:
        c, buf = self._make_canvas()
        d = ChordDiagram(name="Am", frets=[-1, 0, 2, 2, 1, 0])
        result = draw_chord_diagram(c, d, x=100.0, y=400.0)
        c.save()
        assert buf.tell() > 0
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_draw_returns_positive_dimensions(self) -> None:
        c, buf = self._make_canvas()
        d = ChordDiagram(name="G", frets=[3, 0, 0, 0, 2, 3])
        w, h = draw_chord_diagram(c, d, x=50.0, y=300.0)
        c.save()
        assert w > 0
        assert h > 0

    def test_draw_with_base_fret(self) -> None:
        """Chord with base_fret > 0 should render without error."""
        c, buf = self._make_canvas()
        d = ChordDiagram(name="F#m", frets=[2, 2, 2, 4, 4, 2], base_fret=2)
        w, h = draw_chord_diagram(c, d, x=100.0, y=400.0)
        c.save()
        assert w > 0
        assert h > 0

    def test_draw_all_muted(self) -> None:
        """All-muted chord should render without error."""
        c, buf = self._make_canvas()
        d = ChordDiagram(name="N.C.", frets=[-1, -1, -1, -1, -1, -1])
        w, h = draw_chord_diagram(c, d, x=100.0, y=400.0)
        c.save()
        assert w > 0

    def test_draw_all_open(self) -> None:
        """All-open chord should render without error."""
        c, buf = self._make_canvas()
        d = ChordDiagram(name="Em7", frets=[0, 0, 0, 0, 2, 0])
        w, h = draw_chord_diagram(c, d, x=100.0, y=400.0)
        c.save()
        assert w > 0

    def test_draw_produces_valid_pdf(self) -> None:
        """The PDF output should start with the PDF magic bytes."""
        c, buf = self._make_canvas()
        d = ChordDiagram(name="C", frets=[0, 1, 0, 2, 3, -1])
        draw_chord_diagram(c, d, x=100.0, y=400.0)
        c.save()
        buf.seek(0)
        header = buf.read(4)
        assert header == b"%PDF"


# ---------------------------------------------------------------------------
# render_chord_diagrams_pdf
# ---------------------------------------------------------------------------


class TestRenderChordDiagramsPdf:
    def test_empty_list_creates_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "empty_chords.pdf"
            render_chord_diagrams_pdf([], out, title="Empty Test")
            assert out.exists()
            assert out.stat().st_size > 0
            content = out.read_bytes()
            assert content[:4] == b"%PDF"

    def test_single_diagram(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "single.pdf"
            diagrams = [ChordDiagram(name="Am", frets=[-1, 0, 2, 2, 1, 0])]
            render_chord_diagrams_pdf(diagrams, out)
            assert out.exists()
            assert out.stat().st_size > 0

    def test_multiple_diagrams_one_row(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "multi.pdf"
            diagrams = [
                ChordDiagram(name="D", frets=[-1, -1, 0, 2, 3, 2]),
                ChordDiagram(name="E", frets=[0, 0, 1, 2, 2, 0]),
                ChordDiagram(name="A", frets=[-1, 0, 2, 2, 2, 0]),
                ChordDiagram(name="Bm", frets=[-1, -1, 4, 4, 3, 2], base_fret=2),
            ]
            render_chord_diagrams_pdf(diagrams, out, title="Rebel Rebel Chords")
            assert out.exists()
            assert out.stat().st_size > 0

    def test_more_than_one_row(self) -> None:
        """More diagrams than fit in one row should not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "many.pdf"
            diagrams = [
                ChordDiagram(name=f"C{i}", frets=[0, 1, 0, 2, 3, -1])
                for i in range(14)
            ]
            render_chord_diagrams_pdf(diagrams, out, cols=4)
            assert out.exists()

    def test_output_is_pdf(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "chords.pdf"
            diagrams = [ChordDiagram(name="G", frets=[3, 0, 0, 0, 2, 3])]
            render_chord_diagrams_pdf(diagrams, out)
            content = out.read_bytes()
            assert content[:4] == b"%PDF"


# ---------------------------------------------------------------------------
# render_pdf_tab with chord_diagrams
# ---------------------------------------------------------------------------


def _make_simple_results() -> list[FingeringResult]:
    """Return a minimal list of FingeringResult for PDF rendering tests."""
    note = NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0,
                     string_hint=1, fret_hint=0)
    state = FingeringState(string_num=1, fret=0, finger=Finger.OPEN, hand_position=1)
    return [FingeringResult(note_id=0, note_event=note, state=state, cost=0.0)]


class TestRenderPdfTabWithChordDiagrams:
    def test_no_chord_diagrams_unchanged(self) -> None:
        """render_pdf_tab without chord_diagrams produces a valid PDF."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_no_chords.pdf"
            render_pdf_tab(_make_simple_results(), out, title="Test", artist="Artist")
            assert out.exists()
            content = out.read_bytes()
            assert content[:4] == b"%PDF"

    def test_with_chord_diagrams_none(self) -> None:
        """chord_diagrams=None is handled gracefully."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_none.pdf"
            render_pdf_tab(
                _make_simple_results(), out, title="Test", chord_diagrams=None
            )
            assert out.exists()

    def test_with_chord_diagrams_empty_list(self) -> None:
        """chord_diagrams=[] is handled gracefully (no header rendered)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_empty.pdf"
            render_pdf_tab(
                _make_simple_results(), out, title="Test", chord_diagrams=[]
            )
            assert out.exists()

    def test_with_chord_diagrams_renders_header(self) -> None:
        """chord_diagrams with content produces a valid PDF."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_with_chords.pdf"
            diagrams = [
                ChordDiagram(name="D", frets=[-1, -1, 0, 2, 3, 2]),
                ChordDiagram(name="E", frets=[0, 0, 1, 2, 2, 0]),
                ChordDiagram(name="A", frets=[-1, 0, 2, 2, 2, 0]),
                ChordDiagram(name="Bm", frets=[-1, -1, 4, 4, 3, 2], base_fret=2),
            ]
            render_pdf_tab(
                _make_simple_results(), out,
                title="Rebel Rebel", artist="David Bowie",
                chord_diagrams=diagrams,
            )
            assert out.exists()
            content = out.read_bytes()
            assert content[:4] == b"%PDF"

    def test_with_many_chord_diagrams(self) -> None:
        """More than one row of chord diagrams should not raise."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_many_chords.pdf"
            diagrams = [
                ChordDiagram(name=f"Chord{i}", frets=[0, 1, 0, 2, 3, -1])
                for i in range(12)
            ]
            render_pdf_tab(
                _make_simple_results(), out,
                title="Many Chords",
                chord_diagrams=diagrams,
            )
            assert out.exists()

    def test_with_empty_results_and_chord_diagrams(self) -> None:
        """Empty results + chord_diagrams: still produces a valid PDF."""
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "tab_empty_results.pdf"
            diagrams = [ChordDiagram(name="Am", frets=[-1, 0, 2, 2, 1, 0])]
            render_pdf_tab([], out, title="Empty", chord_diagrams=diagrams)
            assert out.exists()
            content = out.read_bytes()
            assert content[:4] == b"%PDF"
