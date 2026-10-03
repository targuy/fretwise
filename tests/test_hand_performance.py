"""Behavioral checks for source fidelity and the HandPerformance 1.1 contract."""

from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from pydantic import ValidationError

from fretwise.models import Articulation, Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.parser.gpif_adapter import _build_note_map, _build_performance_tempo_map
from fretwise.performance import (
    HandPerformance,
    TempoMap,
    build_hand_performance,
    validate_hand_performance,
)
from fretwise.playback import build_performance


def _result(
    event: NoteEvent,
    note_id: int = 0,
    string: int = 1,
    fret: int = 5,
    finger: Finger = Finger.INDEX,
) -> FingeringResult:
    return FingeringResult(note_id, event, FingeringState(string, fret, finger, 5), 0.0)


def _document() -> dict:
    event = NoteEvent(69, 0.0, 1.0, 120.0, source_note_id="source-0")
    return build_hand_performance([event], [_result(event)])


def test_tempo_integrates_across_boundaries_and_inside_held_note() -> None:
    tempo = TempoMap(((0.0, 120.0), (2.0, 60.0)))
    assert tempo.beat_to_seconds(4) == 3.0
    assert tempo.duration_seconds(1, 3) == 2.5
    assert tempo.beat_to_seconds(4) / 2 == 1.5


def test_full_tempo_metadata_preserves_initial_silence_changes() -> None:
    event = NoteEvent(69, 4.0, 0.25, 60.0, tempo_points=((0.0, 120.0), (2.0, 60.0)))
    tempo = TempoMap.from_events([event])
    assert tempo.beat_to_seconds(event.onset) == 3.0
    performance = build_hand_performance([event], [_result(event)])
    assert performance["notes"][0]["onTick"] == 3840
    assert performance["range"]["startTick"] == 0
    assert performance["tempoMap"][1] == {"tick": 1920, "usPerQuarter": 1_000_000.0}


def test_sixteenth_at_240_bpm_has_no_80ms_floor() -> None:
    tempo = TempoMap(((0.0, 240.0),))
    assert tempo.duration_seconds(0, 0.25) == 0.0625


def test_occurrence_ids_are_distinct_for_repeated_source_note() -> None:
    a = NoteEvent(69, 0, 1, 120, source_note_id="n1")
    b = NoteEvent(69, 4, 1, 120, source_note_id="n1")
    performance = build_hand_performance([a, b], [_result(b, 1), _result(a)])
    assert [note["occurrenceId"] for note in performance["notes"]] == ["n1@1", "n1@2"]
    assert {note["sourceNoteId"] for note in performance["notes"]} == {"n1"}


def test_curve_keeps_plateau_and_release_in_absolute_ticks() -> None:
    event = NoteEvent(69, 2, 2, 120, bend_points=((0, 0), (0.25, 200), (0.75, 200), (1, 0)))
    performance = build_hand_performance([event], [_result(event)])
    bend = performance["expressions"][0]
    assert bend["cents"]["points"] == [
        {"tick": 1920, "value": 0},
        {"tick": 2400, "value": 200},
        {"tick": 3360, "value": 200},
        {"tick": 3840, "value": 0},
    ]
    assert bend["preBend"] is False


def test_short_gp_bend_holds_last_pitch_until_note_end() -> None:
    event = NoteEvent(69, 2, 0.25, 120, bend_points=((0, 0), (0.25, 50)))
    performance = build_hand_performance([event], [_result(event)])
    assert performance["expressions"][0]["cents"]["points"] == [
        {"tick": 1920, "value": 0},
        {"tick": 1980, "value": 50},
        {"tick": 2160, "value": 50},
    ]


def test_gp_bend_with_offset_origin_covers_note_from_onset() -> None:
    event = NoteEvent(69, 0, 1, 120, bend_points=((0.25, 0), (0.75, 100)))
    performance = build_hand_performance([event], [_result(event)])
    assert performance["expressions"][0]["cents"]["points"] == [
        {"tick": 0, "value": 0},
        {"tick": 240, "value": 0},
        {"tick": 720, "value": 100},
        {"tick": 960, "value": 100},
    ]


def test_prebend_starts_at_source_deformation() -> None:
    event = NoteEvent(69, 0, 1, 120, bend_points=((0, 200), (1, 0)))
    performance = build_hand_performance([event], [_result(event)])
    assert performance["expressions"][0]["preBend"] is True


def test_missing_bend_curve_remains_unknown_with_explicit_diagnostic() -> None:
    event = NoteEvent(69, 0, 1, 120, bend_value=2.0)
    performance = build_hand_performance([event], [_result(event)])
    assert performance["expressions"][0]["sourceKind"] == "bend"
    assert performance["expressions"][0]["kind"] == "unknown"
    assert "EXPRESSION_DATA_INCOMPLETE" in {d["code"] for d in performance["diagnostics"]}


def test_audio_policy_is_shared_for_staccato_duration_and_velocity() -> None:
    event = NoteEvent(69, 2, 1, 120, staccato=True)
    performance = build_hand_performance(
        [event],
        [_result(event)],
        {
            "performanceByNoteId": {"0": {"dur_beats": 0.45, "velocity": 42}},
        },
    )
    note = performance["notes"][0]
    assert note["notatedEndTick"] == 2880
    assert note["soundEndTick"] == 2352
    assert note["velocity"] == 42
    assert performance["noteExecution"][0]["sustainRequiredUntilTick"] == 2352
    assert not any(d["code"] == "TIMING_AMBIGUOUS" for d in performance["diagnostics"])


def test_source_and_user_fingering_provenance_and_locks() -> None:
    event = NoteEvent(69, 0, 1, 120, source_finger=Finger.INDEX, source_note_id="n1")
    performance = build_hand_performance([event], [_result(event)])
    assert performance["notes"][0]["fingering"]["provenance"] == "source"
    performance = build_hand_performance(
        [event],
        [_result(event)],
        {
            "userNoteIds": ["n1"],
            "lockedNoteIds": ["n1"],
        },
    )
    assert performance["notes"][0]["fingering"]["provenance"] == "user"
    assert performance["notes"][0]["fingering"]["locked"] is True


def test_hammer_origin_targets_destination_without_repicking_origin() -> None:
    a = NoteEvent(
        69,
        0,
        1,
        120,
        articulation=Articulation.HAMMER_ON,
        source_note_id="a",
        technique_to_source_note_id="b",
    )
    b = NoteEvent(71, 1, 1, 120, source_note_id="b")
    performance = build_hand_performance(
        [a, b], [_result(a), _result(b, 1, fret=7, finger=Finger.RING)]
    )
    assert [execution["attackKind"] for execution in performance["noteExecution"]] == [
        "pick",
        "hammer_on",
    ]
    assert performance["expressions"][0]["noteIds"] == ["a@1", "b@1"]
    validate_hand_performance(performance)


def test_barre_has_interval_and_keeps_selected_fingers() -> None:
    a = NoteEvent(69, 0, 2, 120, source_note_id="a")
    b = NoteEvent(64, 1, 2, 120, source_note_id="b")
    performance = build_hand_performance([a, b], [_result(a), _result(b, 1, string=2)])
    assert performance["barres"][0]["startTick"] == 960
    assert performance["barres"][0]["endTick"] == 1920
    assert performance["barres"][0]["stringNos"] == [1, 2]


@pytest.mark.parametrize(
    "mutation",
    [
        lambda doc: doc.update(schemaVersion="2.0"),
        lambda doc: doc["tempoMap"].append(deepcopy(doc["tempoMap"][0])),
        lambda doc: doc["notes"].append(deepcopy(doc["notes"][0])),
        lambda doc: doc["notes"][0]["fingering"].update(stringNo=7),
        lambda doc: doc["notes"][0]["fingering"].update(finger="open"),
        lambda doc: doc["notes"][0].update(expressionIds=["absent"]),
        lambda doc: doc["noteExecution"].clear(),
        lambda doc: doc["tempoMap"][0].update(usPerQuarter=float("nan")),
    ],
)
def test_invalid_contract_rejected(mutation) -> None:
    document = _document()
    mutation(document)
    with pytest.raises(ValidationError):
        validate_hand_performance(document)


def test_gpif_sibling_bend_units_and_source_finger_are_preserved() -> None:
    root = ET.fromstring("""<GPIF><Notes><Note id="n1"><LeftFingering>3</LeftFingering>
    <Properties><Property name="Bended"><Enable/></Property>
    <Property name="BendOriginValue"><Float>0</Float></Property>
    <Property name="BendMiddleValue"><Float>100</Float></Property>
    <Property name="BendMiddleOffset1"><Float>25</Float></Property>
    <Property name="BendMiddleOffset2"><Float>75</Float></Property>
    <Property name="BendDestinationValue"><Float>0</Float></Property>
    </Properties></Note></Notes></GPIF>""")
    note = _build_note_map(root)["n1"]
    assert note.bend_points == ((0, 0), (0.25, 200), (0.75, 200), (1, 0))
    assert note.bend_value == 2
    assert note.source_finger == Finger.RING


def test_gpif_tempo_automation_inside_measure() -> None:
    root = ET.fromstring("""<GPIF><MasterBars><MasterBar><Time>4/4</Time></MasterBar>
    <MasterBar><Time>3/4</Time></MasterBar></MasterBars><MasterTrack><Automations>
    <Automation><Type>Tempo</Type><Bar>0</Bar><Position>0</Position><Value>120 2</Value>
    </Automation><Automation><Type>Tempo</Type><Bar>1</Bar><Position>0.5</Position>
    <Value>60 2</Value></Automation></Automations></MasterTrack></GPIF>""")
    assert _build_performance_tempo_map(root) == ((0, 120), (5.5, 60))


def test_audio_preserves_exact_bend_knots() -> None:
    rows = [
        {
            "pitch": 69,
            "onset": 0,
            "duration": 1,
            "string": 1,
            "bend_points": [[0, 0], [0.25, 200], [0.75, 200], [1, 0]],
        }
    ]
    curve = build_performance(rows)[0]["perf"]["bend"]
    assert [0.25, 2.0] in curve and [0.75, 2.0] in curve and [1.0, 0.0] in curve


def test_tuplet_ppq_keeps_seventh_subdivision_exact() -> None:
    event = NoteEvent(69, 1 / 7, 1 / 7, 120)
    performance = build_hand_performance([event], [_result(event)])
    assert performance["ppq"] == 6720
    assert performance["notes"][0]["onTick"] == 960


def test_missing_result_is_not_silently_dropped() -> None:
    with pytest.raises(ValueError, match="Every source occurrence"):
        build_hand_performance([NoteEvent(69, 0, 1, 120)], [])


def test_published_schema_matches_runtime_models() -> None:
    schema = (Path(__file__).parents[1] / "src/fretwise/performance/schemas"
              / "hand-performance-1.1.schema.json")
    assert json.loads(schema.read_text(encoding="utf-8")) == HandPerformance.model_json_schema()


def test_audio_hammer_chain_only_picks_first_origin() -> None:
    rows = [
        {"source_note_id": "a", "technique_to_source_note_id": "b", "onset": 0,
         "duration": 1, "string": 1, "pitch": 65, "articulation": "hammer_on"},
        {"source_note_id": "b", "technique_to_source_note_id": "c", "onset": 1,
         "duration": 1, "string": 1, "pitch": 67, "articulation": "hammer_on"},
        {"source_note_id": "c", "onset": 2, "duration": 1, "string": 1, "pitch": 69},
    ]
    assert [row["perf"]["attack"] for row in build_performance(rows)] == [True, False, False]


def test_musicxml_dotted_tempo_and_silent_change_keep_quarter_units() -> None:
    import music21

    from fretwise.parser.musicxml_adapter import _extract_note_events

    part = music21.stream.Part()
    part.insert(0, music21.tempo.MetronomeMark(number=60,
                                            referent=music21.duration.Duration(1.5)))
    part.insert(0, music21.note.Rest(quarterLength=4))
    part.insert(2, music21.tempo.MetronomeMark(number=60))
    part.insert(4, music21.note.Note("E4", quarterLength=1))
    event = _extract_note_events(part)[0]
    assert event.tempo_points == ((0, 90), (2, 60))
    assert TempoMap.from_events([event]).beat_to_seconds(4) == pytest.approx(10 / 3)


def test_midi_short_note_and_tempo_change_in_rest_are_preserved() -> None:
    import pretty_midi

    from fretwise.parser.midi_adapter import _extract_note_events

    midi = pretty_midi.PrettyMIDI(initial_tempo=120)
    instrument = pretty_midi.Instrument(program=25)
    instrument.notes.append(pretty_midi.Note(velocity=80, pitch=64, start=2.0, end=2.01))
    events = _extract_note_events(midi, instrument)
    assert events[0].duration == pytest.approx(0.02)
    assert events[0].tempo_points == ((0, 120),)
