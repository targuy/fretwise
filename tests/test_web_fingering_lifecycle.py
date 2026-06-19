"""Tests for the on-demand fingering lifecycle in the web app.

Covers the three behaviours added when fingering generation became explicit:

1. Embedded ``<LeftFingering>`` in a GP file is read back (so a partition that
   already carries fingers shows them on open, without re-running Viterbi).
2. ``/api/files`` flags such files as having (non-current) fingerings.
3. ``/api/library/cleanup`` strips legacy ``_fingered`` suffixes and moves
   duplicates to ``.trash`` (recoverable), preferring the cleaner-named file.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from types import SimpleNamespace
from typing import Any

from fretwise.export.gp_writer import GPIF_CONTENT_NAME
from fretwise.models import (
    Articulation,
    Dynamic,
    Finger,
    FingeringResult,
    FingeringState,
    NoteEvent,
)
from fretwise.web.app import (
    _annotate_serialized_review_status,
    _gp_has_embedded_fingering,
    _merged_gp_fingering_mapping,
    _read_embedded_gp_fingerings,
    _solve_cache_clear,
    create_app,
)

_GPIF_WITH_FINGERS = """<?xml version="1.0" encoding="UTF-8"?>
<GPIF><Score><Notes>
  <Note id="0"><LeftFingering>I</LeftFingering>
    <Properties><Property name="Fret"><Fret>5</Fret></Property></Properties></Note>
  <Note id="1"><LeftFingering>A</LeftFingering>
    <Properties><Property name="Fret"><Fret>7</Fret></Property></Properties></Note>
  <Note id="2">
    <Properties><Property name="Fret"><Fret>0</Fret></Property></Properties></Note>
</Notes></Score></GPIF>
"""

_GPIF_NO_FINGERS = """<?xml version="1.0" encoding="UTF-8"?>
<GPIF><Score><Notes>
  <Note id="0"><Properties><Property name="Fret"><Fret>5</Fret></Property></Properties></Note>
</Notes></Score></GPIF>
"""


def _write_gp(path: Path, xml: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(GPIF_CONTENT_NAME, xml.encode("utf-8"))
    path.write_bytes(buf.getvalue())


def _route_endpoint(app: Any, path: str) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def _note(source_note_id: str | None, onset: float = 0.0) -> NoteEvent:
    return NoteEvent(
        pitch=60,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        string_hint=1,
        fret_hint=5,
        source_note_id=source_note_id,
    )


def _result(
    source_note_id: str | None,
    finger: Finger = Finger.INDEX,
    *,
    onset: float = 0.0,
) -> FingeringResult:
    return FingeringResult(
        note_id=1,
        note_event=_note(source_note_id, onset),
        state=FingeringState(
            string_num=1,
            fret=5,
            finger=finger,
            hand_position=5,
        ),
        cost=0.0,
    )


def _clean_guard_payload(results: list[FingeringResult]) -> SimpleNamespace:
    return SimpleNamespace(
        results=results,
        biomechanical_report=SimpleNamespace(
            fatal_count=0,
            high_count=0,
            violations=[],
            by_measure=lambda: {},
        ),
    )


class _Adapter:
    track_name = "Guitar"
    midi_program = 24
    section_markers: dict[int, str] = {}
    chord_diagrams: list[Any] = []
    chord_markers: dict[str, str] = {}
    beats_per_measure = 4.0
    measure_time_signatures: dict[int, tuple[int, int]] = {}
    time_denominator = 4


def test_read_embedded_gp_fingerings_round_trip(tmp_path: Path) -> None:
    gp = tmp_path / "song.gp"
    _write_gp(gp, _GPIF_WITH_FINGERS)
    assert _gp_has_embedded_fingering(gp) is True
    embedded = _read_embedded_gp_fingerings(gp)
    # Open-string note (id=2, no LeftFingering) is absent; fretted ones present.
    assert embedded == {"0": "I", "1": "A"}


def test_embedded_reader_handles_missing_and_plain_files(tmp_path: Path) -> None:
    plain = tmp_path / "plain.gp"
    _write_gp(plain, _GPIF_NO_FINGERS)
    assert _gp_has_embedded_fingering(plain) is False
    assert _read_embedded_gp_fingerings(plain) == {}
    # A non-GP / non-zip file never raises.
    junk = tmp_path / "note.txt"
    junk.write_text("not a zip")
    assert _gp_has_embedded_fingering(junk) is False
    assert _read_embedded_gp_fingerings(junk) == {}


def test_gp_save_merge_preserves_existing_track_fingerings(tmp_path: Path) -> None:
    """Saving another track must not erase LeftFingering already in the GP."""
    gp = tmp_path / "song.gp"
    _write_gp(gp, _GPIF_WITH_FINGERS)

    merged = _merged_gp_fingering_mapping(gp, {"2": "M"})

    assert merged["0"] == "I"
    assert merged["1"] == "A"
    assert merged["2"] == "M"


def test_save_gp_invalidates_solve_cache_after_writing_sidecar(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """A stale no-fingering solve response must not survive a save."""
    _solve_cache_clear()
    gp = tmp_path / "song.gp"
    _write_gp(gp, _GPIF_NO_FINGERS)
    app = create_app(tmp_path)
    adapter = _Adapter()
    events = [_note("0")]
    results = [_result("0")]

    def _fake_load(_path: Path, *, track_id: int | None = None) -> tuple[Any, list[NoteEvent]]:
        del track_id
        return adapter, events

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr(
        "fretwise.web.app._run_core_pipeline_for_events",
        lambda *_args, **_kwargs: SimpleNamespace(
            svg="<svg/>",
            conformance_issues=[],
            render_scene=None,
            canonical_score=None,
        ),
    )
    monkeypatch.setattr(
        "fretwise.web.app._run_legacy_pipeline_with_guard",
        lambda _events: _clean_guard_payload(results),
    )
    monkeypatch.setattr(
        "fretwise.web.app._safe_audit",
        lambda *_args, **_kwargs: {"available": True, "overall": "clean"},
    )

    solve_endpoint = _route_endpoint(app, "/api/solve/{filename}")
    save_endpoint = _route_endpoint(app, "/api/save/gp/{filename}")

    before = solve_endpoint(
        filename="song.gp",
        track_id=0,
        representation_mode="standard_tablature",
    )
    assert before["results"] == []
    assert before["has_saved_fingering"] is False

    saved = save_endpoint(filename="song.gp", track_id=0)
    assert saved["sidecar_saved"] is True

    after = solve_endpoint(
        filename="song.gp",
        track_id=0,
        representation_mode="standard_tablature",
    )
    assert after["has_saved_fingering"] is True
    assert len(after["results"]) == 1
    assert after["results"][0]["source_note_id"] == "0"


def test_serialize_marks_fretted_note_without_source_id_red_candidate() -> None:
    from fretwise.web.app import _serialize_result

    row = _serialize_result(_result(None))

    assert row["source_note_id"] is None
    assert row["gp_fingering_export_status"] == "missing_source_note_id"


def test_serialize_result_preserves_expression_fields() -> None:
    from fretwise.web.app import _serialize_result

    result = _result("expr-1")
    note = result.note_event
    note.harmonic_resultant_pitch = 76
    note.ghost = True
    note.staccato = True
    note.strum_direction = "down"
    note.slap = True
    note.pop = True
    note.rasgueado = True
    note.golpe = True

    row = _serialize_result(result)

    assert row["harmonic_resultant_pitch"] == 76
    assert row["ghost"] is True
    assert row["staccato"] is True
    assert row["strum_direction"] == "down"
    assert row["slap"] is True
    assert row["pop"] is True
    assert row["rasgueado"] is True
    assert row["golpe"] is True


def test_serialize_staff_note_preserves_expression_fields() -> None:
    from fretwise.web.app import _serialize_staff_note

    note = _note("staff-expr")
    note.harmonic_resultant_pitch = 88
    note.ghost = True
    note.staccato = True
    note.strum_direction = "up"
    note.slap = True
    note.pop = True
    note.rasgueado = True
    note.golpe = True

    row = _serialize_staff_note(note, 42)

    assert row["note_id"] == 42
    assert row["finger"] is None
    assert row["harmonic_resultant_pitch"] == 88
    assert row["ghost"] is True
    assert row["staccato"] is True
    assert row["strum_direction"] == "up"
    assert row["slap"] is True
    assert row["pop"] is True
    assert row["rasgueado"] is True
    assert row["golpe"] is True


def test_annotate_serialized_review_status_marks_impossible_and_suspect() -> None:
    rows: list[dict[str, Any]] = [
        {"note_id": 1, "review_severity": "ok"},
        {"note_id": 2, "review_severity": "ok"},
        {"note_id": 3, "review_severity": "ok"},
    ]
    audit = {
        "biomechanical_report": {
            "violations": [
                {"severity": "high", "note_ids": [1]},
                {"severity": "fatal", "note_ids": [2, 3]},
                {"severity": "medium", "note_ids": [3]},
            ],
        },
    }

    annotated = _annotate_serialized_review_status(rows, audit)

    assert [row["review_severity"] for row in annotated] == [
        "suspect",
        "impossible",
        "impossible",
    ]


def test_files_endpoint_flags_embedded_fingerings(tmp_path: Path) -> None:
    _write_gp(tmp_path / "with.gp", _GPIF_WITH_FINGERS)
    _write_gp(tmp_path / "without.gp", _GPIF_NO_FINGERS)
    app = create_app(tmp_path)
    import asyncio

    endpoint = _route_endpoint(app, "/api/files")
    resp = asyncio.run(endpoint())
    import json

    files = {f["name"]: f for f in json.loads(bytes(resp.body))}
    assert files["with.gp"]["has_fingering"] is True
    # Embedded-only → present but version unknown → not current.
    assert files["with.gp"]["fingering_is_current"] is False
    assert files["without.gp"]["has_fingering"] is False


def test_cleanup_strips_fingered_and_trashes_duplicates(tmp_path: Path) -> None:
    # Legacy output + its plain source both present → fingered copy wins.
    _write_gp(tmp_path / "song.gp", _GPIF_NO_FINGERS)
    _write_gp(tmp_path / "song_fingered.gp", _GPIF_WITH_FINGERS)
    app = create_app(tmp_path)

    endpoint = _route_endpoint(app, "/api/library/cleanup")
    report = endpoint()

    # song_fingered.gp → song.gp (the plain loser went to .trash first).
    assert any(r["to"] == "song.gp" for r in report["renamed"])
    assert (tmp_path / "song.gp").exists()
    assert not (tmp_path / "song_fingered.gp").exists()
    trash = tmp_path / ".trash"
    assert trash.exists() and any(trash.iterdir())
    # The surviving song.gp carries the embedded fingerings.
    assert _gp_has_embedded_fingering(tmp_path / "song.gp") is True
