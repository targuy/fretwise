"""Tests for ``fretwise convert`` + GP/MusicXML round-trip invariants.

The ``convert`` command turns a parsed score into MusicXML (from GP / MusicXML /
MIDI) or re-annotates a GP source. These tests cover the command wiring (target
inference, error paths, meter pass-through, ``--no-fingering``) plus a
writer-level round-trip asserting the invariants the interop plan requires:
pitches, rhythm, measures and fingerings survive the trip.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from click.testing import CliRunner

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent

pytest.importorskip("music21")

from fretwise.cli import main  # noqa: E402
from fretwise.export.musicxml_writer import write_musicxml  # noqa: E402
from fretwise.parser.musicxml_adapter import MusicXmlAdapter  # noqa: E402

_MIDI_FIXTURE = (
    Path(__file__).parent / "fixtures" / "Nirvana-Smells Like Teen Spirit-12-18-2025.mid"
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _FakeAdapter:
    """Deterministic adapter: a 6/8 measure with two hinted notes.

    String/fret hints make the optimizer use hint-constrained generation, so the
    test is fast and deterministic (no full state-space search).
    """

    track_name = "Lead Guitar"
    section_markers: dict[int, str] = {}
    beats_per_measure = 3.0  # 6/8 expressed in quarter beats
    time_denominator = 8

    def parse(self, path: Path) -> list[NoteEvent]:
        return [
            NoteEvent(
                pitch=64, onset=0.0, duration=0.5, tempo=120.0,
                string_hint=1, fret_hint=0,
            ),
            NoteEvent(
                pitch=60, onset=0.5, duration=0.5, tempo=120.0,
                string_hint=5, fret_hint=3,
            ),
        ]


def _patch_adapter(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("fretwise.cli.get_adapter", lambda _p: _FakeAdapter())


def _fr(
    note_id: int, pitch: int, onset: float, string_num: int, fret: int,
    finger: Finger, duration: float = 1.0,
) -> FingeringResult:
    return FingeringResult(
        note_id=note_id,
        note_event=NoteEvent(pitch=pitch, onset=onset, duration=duration, tempo=120.0),
        state=FingeringState(
            string_num=string_num, fret=fret, finger=finger, hand_position=max(1, fret),
        ),
        cost=0.0,
    )


def _time_sig(root: ET.Element) -> tuple[str | None, str | None]:
    t = next(root.iter("time"))
    return (t.findtext("beats"), t.findtext("beat-type"))


def _technicals(root: ET.Element) -> list[ET.Element]:
    return list(root.iter("technical"))


# ---------------------------------------------------------------------------
# convert — MusicXML target
# ---------------------------------------------------------------------------


def test_convert_to_musicxml_carries_meter_and_fingering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_adapter(monkeypatch)
    src = tmp_path / "Artist-Song.gp"
    src.write_bytes(b"stub")  # content irrelevant — adapter is patched
    out = tmp_path / "Artist-Song.musicxml"

    result = CliRunner().invoke(main, ["convert", str(src), str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    assert _time_sig(root) == ("6", "8")  # compound meter preserved, not 3/4
    assert _technicals(root), "expected <technical> fingering blocks"


def test_convert_no_fingering_emits_plain_staff(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_adapter(monkeypatch)
    src = tmp_path / "x.gp"
    src.write_bytes(b"stub")
    out = tmp_path / "x.musicxml"

    result = CliRunner().invoke(
        main, ["convert", str(src), str(out), "--no-fingering"]
    )

    assert result.exit_code == 0, result.output
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    assert not _technicals(root), "--no-fingering must not emit tablature technicals"
    assert any(n.find("pitch") is not None for n in root.iter("note"))


def test_convert_infers_xml_extension(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_adapter(monkeypatch)
    src = tmp_path / "x.gp"
    src.write_bytes(b"stub")
    out = tmp_path / "x.xml"  # .xml → musicxml

    result = CliRunner().invoke(main, ["convert", str(src), str(out)])

    assert result.exit_code == 0, result.output
    assert out.exists()


def test_convert_ambiguous_extension_requires_to(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_adapter(monkeypatch)
    src = tmp_path / "x.gp"
    src.write_bytes(b"stub")
    out = tmp_path / "x.bin"

    result = CliRunner().invoke(main, ["convert", str(src), str(out)])
    assert result.exit_code != 0
    assert "infer target format" in result.output.lower()

    ok = CliRunner().invoke(main, ["convert", str(src), str(out), "--to", "musicxml"])
    assert ok.exit_code == 0, ok.output
    assert out.exists()


# ---------------------------------------------------------------------------
# convert — Guitar Pro target
# ---------------------------------------------------------------------------


def test_convert_to_gp_from_non_gp_source_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _patch_adapter(monkeypatch)
    src = tmp_path / "x.mid"  # not a .gp source
    src.write_bytes(b"stub")
    out = tmp_path / "x.gp"

    result = CliRunner().invoke(main, ["convert", str(src), str(out)])

    assert result.exit_code != 0
    assert "from a .gp" in result.output or "from scratch" in result.output


# ---------------------------------------------------------------------------
# Round-trip invariants
# ---------------------------------------------------------------------------


def test_roundtrip_preserves_pitches_meter_and_fingering(tmp_path: Path) -> None:
    # A short 6/8 phrase with real fingerings.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN, duration=0.5),
        _fr(1, 60, 0.5, 5, 3, Finger.RING, duration=0.5),
        _fr(2, 55, 1.0, 4, 0, Finger.OPEN, duration=1.0),
    ]
    out = tmp_path / "rt.musicxml"
    write_musicxml(results, out, beats_per_measure=3.0, time_denominator=8)

    root = ET.fromstring(out.read_text(encoding="utf-8"))
    # mesures / meter
    assert _time_sig(root) == ("6", "8")
    # doigtés — fretted notes keep a <fingering>
    fingerings = {f.text for f in root.iter("fingering")}
    assert "3" in fingerings  # the ring-finger note survived
    # hauteurs — re-parse and compare (written = sounding + 12 transposing staff)
    events = MusicXmlAdapter().parse(out)
    assert sorted(e.pitch for e in events) == sorted(
        r.note_event.pitch + 12 for r in results
    )


@pytest.mark.skipif(not _MIDI_FIXTURE.exists(), reason="MIDI fixture not present")
def test_convert_midi_fixture_produces_valid_musicxml(tmp_path: Path) -> None:
    # End-to-end on a real file. --no-fingering keeps it fast (no Viterbi).
    out = tmp_path / "nirvana.musicxml"
    result = CliRunner().invoke(
        main, ["convert", str(_MIDI_FIXTURE), str(out), "--no-fingering", "-q"]
    )
    assert result.exit_code == 0, result.output
    root = ET.fromstring(out.read_text(encoding="utf-8"))
    notes = [n for n in root.iter("note") if n.find("pitch") is not None]
    assert notes, "expected notes in the converted MusicXML"
    assert list(root.iter("measure")), "expected measures in the converted MusicXML"
