"""Explicit let-ring releases survive persistence and drive audio and hand together."""

from copy import deepcopy

import pytest

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.performance import build_hand_performance
from fretwise.playback import build_performance
from fretwise.web.app import _saved_fingering_validation, _serialize_result
from fretwise.web.hand_performance import build_saved_hand_performance, fingering_revision


def _results() -> list[FingeringResult]:
    events = [
        NoteEvent(64, 0, 0.5, 120, string_hint=2, fret_hint=5, let_ring=True,
                  source_note_id="shared"),
        NoteEvent(66, 2, 0.5, 120, string_hint=1, fret_hint=2, source_note_id="change"),
        NoteEvent(64, 4, 0.5, 120, string_hint=2, fret_hint=5, let_ring=True,
                  source_note_id="shared"),
    ]
    return [FingeringResult(
        index, event, FingeringState(event.string_hint, event.fret_hint, Finger.INDEX, 2),
        0.0, let_ring_end=2.0 if index == 0 else None,
    ) for index, event in enumerate(events)]


def test_release_survives_saved_roundtrip_and_shared_source_ids() -> None:
    results = _results()
    rows = [_serialize_result(result) for result in results]
    original = deepcopy(rows)
    build_performance(rows)
    assert rows[0]["perf"]["dur_beats"] == 2.0
    assert rows[2]["perf"]["dur_beats"] > 0.5
    doc = build_saved_hand_performance([r.note_event for r in results], rows, {})
    ppq = doc["ppq"]
    assert doc["notes"][0]["soundEndTick"] == 2 * ppq
    assert doc["notes"][0]["notatedEndTick"] == 0.5 * ppq
    assert doc["noteExecution"][0]["dampingAtTick"] == 2 * ppq
    assert [(r["duration"], r["let_ring"]) for r in rows] == [
        (r["duration"], r["let_ring"]) for r in original
    ]
    altered = deepcopy(rows)
    altered[0]["let_ring_end"] = 3.0
    assert fingering_revision(rows) != fingering_revision(altered)


def test_direct_hand_builder_uses_same_explicit_release_without_audio_rows() -> None:
    results = _results()
    doc = build_hand_performance([r.note_event for r in results], results)
    assert doc["notes"][0]["soundEndTick"] == 2 * doc["ppq"]


def test_early_release_cannot_shorten_written_tie_chain() -> None:
    results = _results()[:1]
    origin = results[0]
    origin.note_event.duration = 1.0
    origin.let_ring_end = 0.25
    continuation = NoteEvent(64, 1, 2, 120, string_hint=2, fret_hint=5,
                             is_tie_dest=True, source_note_id="tie")
    results.append(FingeringResult(1, continuation, origin.state, 0.0))
    rows = [_serialize_result(result) for result in results]
    build_performance(rows)
    assert rows[0]["perf"]["dur_beats"] == 3.0
    doc = build_hand_performance([r.note_event for r in results], results)
    assert doc["notes"][0]["soundEndTick"] == 3 * doc["ppq"]
    validity = _saved_fingering_validation(rows, None, None, [r.note_event for r in results])
    assert validity["fingering_validity"] == "invalid"


@pytest.mark.parametrize("release", [float("nan"), float("inf")])
def test_nonfinite_release_is_rejected_by_hand_contract(release: float) -> None:
    results = _results()
    results[0].let_ring_end = release
    with pytest.raises(ValueError, match="finite"):
        build_hand_performance([r.note_event for r in results], results)
