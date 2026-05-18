"""Tests for fretwise.export.gp_writer.

The writer is pure (string-in / bytes-out) so we test it without needing
an actual Guitar Pro install. Where possible we read back the rewritten
archive to confirm the structure round-trips cleanly.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

from fretwise.export.gp_writer import (
    GPIF_CONTENT_NAME,
    _inject_left_fingering,
    fingerings_by_source_id,
    write_gp_with_fingerings,
)
from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent


_SAMPLE_GPIF = """<?xml version="1.0" encoding="UTF-8"?>
<GPIF>
  <Score>
    <Notes>
      <Note id="0">
        <InstrumentArticulation>0</InstrumentArticulation>
        <Properties>
          <Property name="Fret"><Fret>5</Fret></Property>
          <Property name="String"><String>3</String></Property>
          <Property name="Midi"><Number>62</Number></Property>
        </Properties>
      </Note>
      <Note id="1">
        <InstrumentArticulation>0</InstrumentArticulation>
        <Properties>
          <Property name="Fret"><Fret>7</Fret></Property>
          <Property name="String"><String>3</String></Property>
        </Properties>
      </Note>
    </Notes>
  </Score>
</GPIF>
"""


def _build_zip(xml: str) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(GPIF_CONTENT_NAME, xml.encode("utf-8"))
        z.writestr("Content/extras.bin", b"opaque")
    return buf.getvalue()


def _result(note_id: int, source_note_id: str | None, finger: Finger,
            fret: int = 5) -> FingeringResult:
    event = NoteEvent(
        pitch=60, onset=float(note_id), duration=0.5, tempo=120.0,
        source_note_id=source_note_id,
    )
    state = FingeringState(
        string_num=3, fret=fret, finger=finger, hand_position=5,
    )
    return FingeringResult(
        note_id=note_id, note_event=event, state=state,
        cost=1.0, alternatives=[],
    )


# ---------------------------------------------------------------------------
# fingerings_by_source_id
# ---------------------------------------------------------------------------


def test_fingerings_by_source_id_skips_missing_source_id() -> None:
    results = [
        _result(0, "0", Finger.INDEX),
        _result(1, None, Finger.MIDDLE),  # no source_note_id → skipped
        _result(2, "2", Finger.RING),
    ]
    mapping = fingerings_by_source_id(results)
    assert mapping == {"0": 1, "2": 3}


def test_fingerings_by_source_id_skips_open_strings() -> None:
    """Open-string notes (fret=0 + finger=open) carry no LH annotation."""
    results = [
        _result(0, "0", Finger.OPEN, fret=0),  # truly open
        _result(1, "1", Finger.INDEX, fret=5),
    ]
    mapping = fingerings_by_source_id(results)
    assert mapping == {"1": 1}


def test_fingerings_by_source_id_full_mapping_values() -> None:
    """Each finger name maps to the GPIF integer convention."""
    results = [
        _result(0, "0", Finger.OPEN, fret=2),
        _result(1, "1", Finger.INDEX),
        _result(2, "2", Finger.MIDDLE),
        _result(3, "3", Finger.RING),
        _result(4, "4", Finger.PINKY),
    ]
    mapping = fingerings_by_source_id(results)
    assert mapping == {"0": 0, "1": 1, "2": 2, "3": 3, "4": 4}


# ---------------------------------------------------------------------------
# _inject_left_fingering (pure string-level)
# ---------------------------------------------------------------------------


def test_inject_left_fingering_adds_property_to_matching_notes() -> None:
    out = _inject_left_fingering(_SAMPLE_GPIF, {"0": 1, "1": 3})
    # Each Note should have a LeftFingering Property with the right integer.
    assert '<Property name="LeftFingering"><Fingering>1</Fingering></Property>' in out
    assert '<Property name="LeftFingering"><Fingering>3</Fingering></Property>' in out
    # Pre-existing Properties (Fret/String/Midi) remain intact.
    assert '<Property name="Fret"><Fret>5</Fret></Property>' in out
    assert '<Property name="Midi"><Number>62</Number></Property>' in out


def test_inject_left_fingering_idempotent_on_resave() -> None:
    """Running the writer twice must not stack duplicate LeftFingering blocks."""
    once = _inject_left_fingering(_SAMPLE_GPIF, {"0": 1})
    twice = _inject_left_fingering(once, {"0": 2})  # overwrite to a new value
    assert twice.count('<Property name="LeftFingering">') == 1
    assert '<Property name="LeftFingering"><Fingering>2</Fingering></Property>' in twice


def test_inject_left_fingering_skips_notes_without_mapping() -> None:
    out = _inject_left_fingering(_SAMPLE_GPIF, {"0": 2})
    # Note id="0" gets it; Note id="1" stays untouched.
    assert out.count('<Property name="LeftFingering">') == 1


def test_inject_left_fingering_empty_mapping_returns_xml_unchanged() -> None:
    assert _inject_left_fingering(_SAMPLE_GPIF, {}) == _SAMPLE_GPIF


# ---------------------------------------------------------------------------
# write_gp_with_fingerings (zip round-trip)
# ---------------------------------------------------------------------------


def test_write_gp_with_fingerings_round_trip(tmp_path: Path) -> None:
    src = tmp_path / "song.gp"
    src.write_bytes(_build_zip(_SAMPLE_GPIF))

    payload = write_gp_with_fingerings(src, {"0": 1, "1": 4})

    # Output is a valid zip and preserves the unrelated entry.
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        assert set(z.namelist()) == {GPIF_CONTENT_NAME, "Content/extras.bin"}
        assert z.read("Content/extras.bin") == b"opaque"
        xml = z.read(GPIF_CONTENT_NAME).decode("utf-8")
        assert '<Property name="LeftFingering"><Fingering>1</Fingering></Property>' in xml
        assert '<Property name="LeftFingering"><Fingering>4</Fingering></Property>' in xml


def test_write_gp_with_fingerings_rejects_non_zip(tmp_path: Path) -> None:
    bogus = tmp_path / "song.gp5"
    bogus.write_bytes(b"\x00\x01\x02 not a zip")
    with pytest.raises(ValueError, match="GP 7/8"):
        write_gp_with_fingerings(bogus, {})


def test_write_gp_with_fingerings_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        write_gp_with_fingerings(tmp_path / "nope.gp", {})
