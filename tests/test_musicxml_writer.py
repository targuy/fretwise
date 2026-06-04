"""Tests for fretwise.export.musicxml_writer — MusicXML export + round-trip."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent

pytest.importorskip("music21")

from fretwise.export.musicxml_writer import (  # noqa: E402
    _note_midi,
    render_musicxml,
    render_musicxml_multi,
    write_musicxml,
)
from fretwise.parser.musicxml_adapter import MusicXmlAdapter  # noqa: E402

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fr(
    note_id: int,
    pitch: int,
    onset: float,
    string_num: int,
    fret: int,
    finger: Finger,
    duration: float = 1.0,
) -> FingeringResult:
    return FingeringResult(
        note_id=note_id,
        note_event=NoteEvent(pitch=pitch, onset=onset, duration=duration, tempo=120.0),
        state=FingeringState(
            string_num=string_num, fret=fret, finger=finger, hand_position=max(1, fret)
        ),
        cost=0.0,
    )


def _technical_of(note_el: ET.Element) -> dict[str, str]:
    tech = note_el.find("notations/technical")
    if tech is None:
        return {}
    return {child.tag: (child.text or "") for child in tech}


def _melodic_notes(root: ET.Element) -> list[ET.Element]:
    return [n for m in root.iter("measure") for n in m.findall("note")]


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_render_musicxml_empty_returns_valid_document() -> None:
    xml = render_musicxml([])
    root = ET.fromstring(xml)
    assert root.tag in ("score-partwise", "score-timewise")


def test_harmonic_note_exports_as_dyad_with_diamond_resultant() -> None:
    # A 12th-fret natural harmonic: fretted fundamental (sounding 51) + resultant
    # overtone an octave up (sounding 63). MuseScore draws both noteheads; the
    # resultant is a diamond with no fingering.
    fund = _fr(0, 51, 0.0, 6, 12, Finger.INDEX)
    fund.note_event.harmonic_resultant_pitch = 63
    root = ET.fromstring(render_musicxml([fund]))
    notes = [n for n in _melodic_notes(root) if n.find("pitch") is not None]
    assert len(notes) == 2, "harmonic must emit a 2-notehead dyad"
    by_written = {_note_pitch(n): n for n in notes}
    # Written = sounding + 12: fundamental 63, resultant 75.
    assert 63 in by_written and 75 in by_written
    fundamental, resultant = by_written[63], by_written[75]
    # Fundamental: normal notehead + tablature technical (it is fretted/fingered).
    assert fundamental.findtext("notehead") in (None, "normal")
    assert _technical_of(fundamental).get("fret") == "12"
    # Resultant: diamond notehead, no fingering/technical.
    assert resultant.findtext("notehead") == "diamond"
    assert _technical_of(resultant) == {}


def _note_pitch(note_el: ET.Element) -> int:
    p = note_el.find("pitch")
    step = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[p.findtext("step")]
    return (int(p.findtext("octave")) + 1) * 12 + step + int(float(p.findtext("alter", "0")))


def test_single_notes_carry_string_fret_fingering() -> None:
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),
        _fr(1, 60, 1.0, 5, 3, Finger.RING),
    ]
    root = ET.fromstring(render_musicxml(results))
    notes = [n for n in _melodic_notes(root) if n.find("rest") is None]
    open_tech = _technical_of(notes[0])
    assert open_tech["string"] == "1"
    assert open_tech["fret"] == "0"
    assert "fingering" not in open_tech  # open string → no finger
    ring_tech = _technical_of(notes[1])
    assert ring_tech == {"string": "5", "fret": "3", "fingering": "3"}


def test_chord_members_keep_independent_string_fret_fingering() -> None:
    # C3 / E3 / G3 struck together — each on its own string.
    results = [
        _fr(0, 48, 0.0, 6, 3, Finger.MIDDLE),
        _fr(1, 52, 0.0, 5, 2, Finger.INDEX),
        _fr(2, 55, 0.0, 4, 0, Finger.OPEN),
    ]
    root = ET.fromstring(render_musicxml(results))
    techs = [_technical_of(n) for n in _melodic_notes(root) if n.find("rest") is None]
    assert {"string": "6", "fret": "3", "fingering": "2"} in techs
    assert {"string": "5", "fret": "2", "fingering": "1"} in techs
    assert {"string": "4", "fret": "0"} in techs  # open, no fingering


def test_gap_between_notes_produces_a_rest() -> None:
    # Notes at beat 0 and beat 3 → a rest fills beats 1–2.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),
        _fr(1, 60, 3.0, 5, 3, Finger.RING),
    ]
    root = ET.fromstring(render_musicxml(results))
    assert any(n.find("rest") is not None for n in _melodic_notes(root))


def _time_signature(root: ET.Element) -> tuple[str, str]:
    t = next(root.iter("time"))
    return (t.findtext("beats", ""), t.findtext("beat-type", ""))


def test_compound_meter_uses_real_denominator() -> None:
    # 6/8 is stored as 3.0 QUARTER beats; the writer must recover the 6/8 meter
    # from (beats_per_measure=3.0, time_denominator=8) — NOT emit 3/4.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN, duration=0.5),
        _fr(1, 60, 0.5, 5, 3, Finger.RING, duration=0.5),
    ]
    root = ET.fromstring(
        render_musicxml(results, beats_per_measure=3.0, time_denominator=8)
    )
    assert _time_signature(root) == ("6", "8")


def test_default_meter_remains_four_four() -> None:
    # Backward compatibility: the default (4.0 quarter beats, denominator 4) and
    # the legacy single-arg call both notate as 4/4.
    results = [_fr(0, 64, 0.0, 1, 0, Finger.OPEN)]
    assert _time_signature(ET.fromstring(render_musicxml(results))) == ("4", "4")
    assert _time_signature(
        ET.fromstring(render_musicxml(results, beats_per_measure=4.0))
    ) == ("4", "4")


def test_metadata_title_and_composer_are_written() -> None:
    results = [_fr(0, 60, 0.0, 5, 3, Finger.RING)]
    root = ET.fromstring(render_musicxml(results, title="My Song", artist="Me"))
    text = ET.tostring(root, encoding="unicode")
    assert "My Song" in text
    assert "Me" in text


def test_inexpressible_durations_are_quantized_and_exportable() -> None:
    # Raw MIDI-like onsets/durations that music21 cannot notate verbatim.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN, duration=0.0625),
        _fr(1, 60, 0.2291, 5, 3, Finger.RING, duration=0.4791),
        _fr(2, 62, 0.7499, 4, 0, Finger.OPEN, duration=0.2083),
    ]
    # Must not raise and every fretted note keeps its technical block.
    root = ET.fromstring(render_musicxml(results))
    techs = [_technical_of(n) for n in _melodic_notes(root) if n.find("rest") is None]
    assert all("string" in t and "fret" in t for t in techs)
    assert len(techs) == 3


def test_write_musicxml_roundtrips_pitches_and_onsets(tmp_path: Path) -> None:
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),
        _fr(1, 60, 1.0, 5, 3, Finger.RING),
        _fr(2, 48, 3.0, 6, 3, Finger.MIDDLE),
        _fr(3, 52, 3.0, 5, 2, Finger.INDEX),
        _fr(4, 55, 3.0, 4, 0, Finger.OPEN),
    ]
    out = tmp_path / "song.musicxml"
    write_musicxml(results, out, title="RT", artist="FW")
    assert out.exists()

    # The export writes WRITTEN pitch = sounding + one octave on a transposing
    # staff (MuseScore's GP guitar convention). The MusicXmlAdapter reads the
    # written <pitch> verbatim, so the round-tripped pitches are sounding + 12.
    events = MusicXmlAdapter().parse(out)
    got = {(e.pitch, round(e.onset, 3)) for e in events}
    expected = {(76, 0.0), (72, 1.0), (60, 3.0), (64, 3.0), (67, 3.0)}
    assert got == expected


def test_export_uses_transposing_staff_and_written_pitch() -> None:
    # The export must DISPLAY at MuseScore's octave: a plain treble clef plus a
    # <transpose octave-change=-1>, with <pitch> written one octave above the
    # internal (sounding) pitch so a reader still sounds the original note.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),   # sounding E4 -> written E5 (76)
        _fr(1, 60, 1.0, 5, 3, Finger.RING),   # sounding C4 -> written C5 (72)
    ]
    root = ET.fromstring(render_musicxml(results))

    # Exactly one transposing staff, dropping an octave.
    transposes = list(root.iter("transpose"))
    assert len(transposes) == 1
    assert transposes[0].findtext("octave-change") == "-1"

    # Plain treble clef (G/2), NOT a clef-octave-change=-1 (Treble8vb).
    clef = root.find(".//clef")
    assert clef is not None
    assert clef.findtext("sign") == "G"
    assert clef.findtext("line") == "2"
    assert clef.find("clef-octave-change") is None

    # Written <pitch> = sounding + 12; internal FingeringResult pitch unchanged.
    written = {_note_midi(n) for n in _melodic_notes(root) if n.find("rest") is None}
    assert written == {76, 72}
    assert results[0].note_event.pitch == 64  # internal pitch untouched


def _voice_numbers(root: ET.Element) -> list[int]:
    return [
        int(v.text)
        for v in root.iter("voice")
        if v.text is not None and v.text.strip().isdigit()
    ]


def test_voices_are_one_based_never_zero() -> None:
    # Regression: music21's makeVoices used 0-based ids, emitting <voice>0</voice>,
    # which MuseScore silently drops (whole part renders empty). Voices must be
    # 1-based. (For a single-voice part music21 may omit <voice> entirely, which
    # is valid — but it must NEVER emit a 0.)
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),
        _fr(1, 60, 1.0, 5, 3, Finger.RING),
        _fr(2, 62, 2.0, 4, 0, Finger.OPEN),
    ]
    xml = render_musicxml(results)
    assert "<voice>0</voice>" not in xml
    voices = _voice_numbers(ET.fromstring(xml))
    assert all(v >= 1 for v in voices)


def _clef_of(part_el: ET.Element) -> tuple[str | None, str | None]:
    clef = part_el.find(".//clef")
    if clef is None:
        return (None, None)
    return (clef.findtext("sign"), clef.findtext("line"))


def _transpose_octave_of(part_el: ET.Element) -> str | None:
    tr = part_el.find(".//transpose")
    return tr.findtext("octave-change") if tr is not None else None


def test_render_musicxml_multi_empty_returns_valid_document() -> None:
    xml = render_musicxml_multi([])
    root = ET.fromstring(xml)
    assert root.tag in ("score-partwise", "score-timewise")


def test_render_musicxml_multi_skips_empty_parts() -> None:
    parts = [
        {"name": "Empty", "kind": "guitar", "results": []},
        {"name": "Gtr", "kind": "guitar",
         "results": [_fr(0, 60, 0.0, 5, 3, Finger.RING)]},
    ]
    root = ET.fromstring(render_musicxml_multi(parts))
    assert len(root.findall("part")) == 1
    assert len(root.findall("part-list/score-part")) == 1


def test_render_musicxml_multi_emits_one_part_and_scorepart_per_track() -> None:
    parts = [
        {"name": "Voice", "kind": "vocal",
         "results": [_fr(0, 64, 0.0, 1, 0, Finger.OPEN)]},
        {"name": "Lead", "kind": "guitar",
         "results": [_fr(0, 60, 0.0, 5, 3, Finger.RING)]},
        {"name": "Bass", "kind": "bass",
         "results": [_fr(0, 40, 0.0, 6, 0, Finger.OPEN)]},
        {"name": "Kit", "kind": "drums",
         "results": [_fr(0, 38, 0.0, 1, 0, Finger.OPEN)]},
    ]
    root = ET.fromstring(render_musicxml_multi(parts, title="T", artist="A"))
    assert len(root.findall("part")) == 4
    score_parts = root.findall("part-list/score-part")
    assert len(score_parts) == 4
    names = [sp.findtext("part-name") for sp in score_parts]
    assert names == ["Voice", "Lead", "Bass", "Kit"]
    # part ids in <part-list> match the <part> elements, in order.
    list_ids = [sp.get("id") for sp in score_parts]
    part_ids = [p.get("id") for p in root.findall("part")]
    assert list_ids == part_ids


def test_render_musicxml_multi_applies_per_kind_clef_and_transpose() -> None:
    parts = [
        {"name": "Voice", "kind": "vocal",
         "results": [_fr(0, 64, 0.0, 1, 0, Finger.OPEN)]},
        {"name": "Lead", "kind": "guitar",
         "results": [_fr(0, 60, 0.0, 5, 3, Finger.RING)]},
        {"name": "Bass", "kind": "bass",
         "results": [_fr(0, 40, 0.0, 6, 0, Finger.OPEN)]},
        {"name": "Kit", "kind": "drums",
         "results": [_fr(0, 38, 0.0, 1, 0, Finger.OPEN)]},
    ]
    root = ET.fromstring(render_musicxml_multi(parts))
    voice, guitar, bass, drums = root.findall("part")

    # Vocal: plain treble, concert pitch (no transpose).
    assert _clef_of(voice) == ("G", "2")
    assert _transpose_octave_of(voice) is None
    # Guitar: treble + octave-down transpose, with tablature technicals.
    assert _clef_of(guitar) == ("G", "2")
    assert _transpose_octave_of(guitar) == "-1"
    assert list(guitar.iter("technical")), "guitar part must carry technicals"
    # Bass: F clef + octave-down transpose, staff-only (no technicals).
    assert _clef_of(bass) == ("F", "4")
    assert _transpose_octave_of(bass) == "-1"
    assert not list(bass.iter("technical"))
    # Drums: percussion clef, concert pitch, staff-only.
    assert drums.find(".//clef").findtext("sign") == "percussion"
    assert _transpose_octave_of(drums) is None
    assert not list(drums.iter("technical"))


def test_render_musicxml_multi_guitar_part_matches_single_part_content() -> None:
    # A guitar part inside a multi-part score must carry the same per-note
    # string/fret/fingering as the single-part renderer.
    results = [
        _fr(0, 64, 0.0, 1, 0, Finger.OPEN),
        _fr(1, 60, 1.0, 5, 3, Finger.RING),
    ]
    multi = ET.fromstring(
        render_musicxml_multi([{"name": "Gtr", "kind": "guitar", "results": results}])
    )
    single = ET.fromstring(render_musicxml(results))

    def _techs(root: ET.Element) -> list[dict[str, str]]:
        return [
            {child.tag: (child.text or "") for child in tech}
            for tech in root.iter("technical")
        ]

    multi_techs = _techs(multi)
    single_techs = _techs(single)
    assert multi_techs == single_techs
    assert {"string": "5", "fret": "3", "fingering": "3"} in multi_techs


def test_render_musicxml_multi_drums_written_at_concert_pitch() -> None:
    # Concert-pitch parts must NOT shift the written octave (no +12).
    parts = [{"name": "Kit", "kind": "drums",
              "results": [_fr(0, 38, 0.0, 1, 0, Finger.OPEN)]}]
    root = ET.fromstring(render_musicxml_multi(parts))
    written = {_note_midi(n) for n in _melodic_notes(root) if n.find("rest") is None}
    assert written == {38}  # not 50


def test_overlapping_durations_yield_multiple_one_based_voices() -> None:
    # Genuine polyphony: a 4-beat held note sustaining UNDER four quarter-note
    # melody notes. This must split into >= 2 independent voices, every voice
    # numbered >= 1 (no voice 0 that MuseScore would drop).
    results = [
        _fr(0, 48, 0.0, 6, 3, Finger.MIDDLE, duration=4.0),  # held bass
        _fr(1, 64, 0.0, 1, 0, Finger.OPEN, duration=1.0),
        _fr(2, 65, 1.0, 1, 1, Finger.INDEX, duration=1.0),
        _fr(3, 67, 2.0, 1, 3, Finger.RING, duration=1.0),
        _fr(4, 69, 3.0, 2, 2, Finger.MIDDLE, duration=1.0),
    ]
    xml = render_musicxml(results)
    assert "<voice>0</voice>" not in xml
    voices = _voice_numbers(ET.fromstring(xml))
    assert voices, "expected explicit <voice> elements for polyphony"
    assert min(voices) >= 1
    assert len(set(voices)) >= 2
