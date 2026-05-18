"""Tests for web PDF export helpers (legacy/core engines)."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import HTTPException

from fretwise.core.graphics import RepresentationMode
from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import UnsupportedFormatError
from fretwise.web.app import (
    _infer_source_format,
    _load_adapter_and_events,
    _parse_representation_mode,
    _render_core_pdf_payload,
    _run_core_pipeline_for_events,
    _safe_pdf_filename,
    create_app,
)


class _DummyAdapter:
    track_name: str = "Lead Guitar"
    section_markers: dict[int, str] = {1: "Intro"}
    chord_diagrams: list[Any] = []
    chord_markers: dict[str, str] = {}
    beats_per_measure: float = 4.0
    measure_time_signatures: dict[int, tuple[int, int]] = {}
    key_signature_fifths: int = 0
    time_denominator: int = 4
    has_anacrusis: bool = False

    def parse(self, _path: Path) -> list[NoteEvent]:
        return [
            NoteEvent(
                pitch=64,
                onset=0.0,
                duration=1.0,
                tempo=120.0,
                articulation=Articulation.NORMAL,
                dynamic=Dynamic.MF,
                voice_hint=0,
                string_hint=1,
                fret_hint=0,
            ),
            NoteEvent(
                pitch=66,
                onset=1.0,
                duration=1.0,
                tempo=120.0,
                articulation=Articulation.NORMAL,
                dynamic=Dynamic.MF,
                voice_hint=0,
                string_hint=1,
                fret_hint=2,
            ),
        ]

    def parse_track(self, path: Path, _track_id: int) -> list[NoteEvent]:
        return self.parse(path)


def _legacy_result(events: list[NoteEvent] | None = None) -> Any:
    note_event = (events[0] if events else None) or NoteEvent(
        pitch=64,
        onset=0.0,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=1,
        fret_hint=0,
    )
    state = SimpleNamespace(string_num=1, fret=0, finger="1", hand_position=0)
    return SimpleNamespace(note_id=1, note_event=note_event, state=state, cost=1.23)


def _route_endpoint(app: Any, path: str) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def test_parse_representation_mode_accepts_aliases_and_rejects_invalid() -> None:
    assert _parse_representation_mode("tab") == RepresentationMode.TAB
    assert _parse_representation_mode("standard") == RepresentationMode.STANDARD
    assert _parse_representation_mode("standard+tablature") == RepresentationMode.STANDARD_TAB
    assert _parse_representation_mode("tablature rhythm") == RepresentationMode.TAB_RHYTHM

    with pytest.raises(HTTPException) as exc:
        _parse_representation_mode("nope")
    assert exc.value.status_code == 400


def test_render_core_pdf_payload_returns_pdf_and_conformance_count(tmp_path: Path) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    captured: dict[str, Any] = {}

    def _fake_run_core(*args: Any, **kwargs: Any) -> Any:
        captured["representation_mode"] = kwargs["representation_mode"]
        return SimpleNamespace(
            render_scene=SimpleNamespace(document_scene=SimpleNamespace(pages=[])),
            conformance_issues=[object(), object()],
        )

    def _fake_pdf_bytes(_scene: Any) -> bytes:
        return b"%PDF-1.4 test"

    from fretwise.web import app as web_app

    captured.clear()
    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(web_app, "_run_core_pipeline_for_events", _fake_run_core)
    monkeypatch.setattr(web_app, "render_scene_to_pdf_bytes", _fake_pdf_bytes)
    pdf_bytes, conformance_issues = _render_core_pdf_payload(
        file_path,
        adapter,
        adapter.parse(file_path),
        representation_mode=RepresentationMode.STANDARD_TAB,
    )
    monkeypatch.undo()
    assert pdf_bytes.startswith(b"%PDF-")
    assert conformance_issues == 2
    assert captured["representation_mode"] == RepresentationMode.STANDARD_TAB


def test_load_adapter_and_events_uses_parse_track_when_requested(
    monkeypatch: Any, tmp_path: Path
) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()
    monkeypatch.setattr("fretwise.web.app.get_adapter", lambda _path: adapter)

    got_adapter, events = _load_adapter_and_events(file_path, track_id=1)
    assert got_adapter is adapter
    assert len(events) == 2
    assert events[0].fret_hint == 0


def test_load_adapter_and_events_raises_http_400_on_unsupported_format(
    monkeypatch: Any, tmp_path: Path
) -> None:
    file_path = tmp_path / "song.unsupported"
    file_path.touch()

    def _raise(_path: Path) -> _DummyAdapter:
        raise UnsupportedFormatError("unsupported")

    monkeypatch.setattr("fretwise.web.app.get_adapter", _raise)
    with pytest.raises(HTTPException) as exc:
        _load_adapter_and_events(file_path, track_id=None)
    assert exc.value.status_code == 400


def test_source_format_and_safe_pdf_filename_helpers() -> None:
    assert _infer_source_format(Path("a.gp")) == "gpif"
    assert _infer_source_format(Path("a.mxl")) == "musicxml"
    assert _infer_source_format(Path("a.mid")) == "mid"
    assert _safe_pdf_filename("A/B:C*D") == "A_B_C_D.pdf"


def test_solve_endpoint_exposes_core_svg_and_representation_mode(
    monkeypatch: Any, tmp_path: Path
) -> None:
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _DummyAdapter()

    def _fake_load(
        _filepath: Path,
        *,
        track_id: int | None = None,
    ) -> tuple[Any, list[NoteEvent]]:
        del track_id
        return adapter, adapter.parse(file_path)

    def _fake_legacy(
        events: list[NoteEvent], *, rule_preferences: Any = None
    ) -> tuple[list[Any], dict[str, int]]:
        del rule_preferences
        return [_legacy_result() for _ in events], {"parsed": len(events)}

    def _fake_core(*_args: Any, **kwargs: Any) -> Any:
        assert kwargs["representation_mode"] == RepresentationMode.STANDARD_TAB
        return SimpleNamespace(svg="<svg id='core'/>", conformance_issues=[object(), object()])

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline", _fake_legacy)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _fake_core)

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    payload = asyncio.run(
        endpoint(
            filename="song.gp",
            track_id=None,
            representation_mode="standard+tablature",
        )
    )
    assert payload["representation_mode"] == "standard_tablature"
    assert payload["core_svg"] == "<svg id='core'/>"
    assert payload["core_conformance_issues"] == 2
    assert payload["results"][0]["string"] == 1


def test_solve_endpoint_caches_repeat_calls(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Second identical /api/solve call must hit the cache (no re-pipeline)."""
    from fretwise.web.app import _solve_cache_clear

    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _DummyAdapter()
    _solve_cache_clear()

    call_count = {"pipeline": 0, "core": 0}

    def _fake_load(
        _filepath: Path, *, track_id: int | None = None,
    ) -> tuple[Any, list[NoteEvent]]:
        del track_id
        return adapter, adapter.parse(file_path)

    def _fake_legacy(
        events: list[NoteEvent], *, rule_preferences: Any = None,
    ) -> tuple[list[Any], dict[str, int]]:
        call_count["pipeline"] += 1
        return [_legacy_result() for _ in events], {"parsed": len(events)}

    def _fake_core(*_args: Any, **kwargs: Any) -> Any:
        del kwargs
        call_count["core"] += 1
        return SimpleNamespace(svg="<svg/>", conformance_issues=[])

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline", _fake_legacy)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _fake_core)

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    asyncio.run(endpoint(
        filename="song.gp", track_id=None,
        representation_mode="standard+tablature",
    ))
    asyncio.run(endpoint(
        filename="song.gp", track_id=None,
        representation_mode="standard+tablature",
    ))
    # Second call must be served from cache → pipeline runs exactly once.
    assert call_count["pipeline"] == 1
    assert call_count["core"] == 1


def test_solve_endpoint_embeds_audit_field(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """The /api/solve response must include an 'audit' field auto-computed
    from events + results + section_markers."""
    from fretwise.models import Finger, FingeringResult, FingeringState

    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)

    class _AdapterWithMeasures(_DummyAdapter):
        # Override the default Intro marker — keep it simple so the audit
        # produces a deterministic shape.
        section_markers = {1: "Movement A", 3: "Movement B"}

        def parse(self, _path: Path) -> list[NoteEvent]:
            return [
                NoteEvent(
                    pitch=64, onset=0.0, duration=0.5, tempo=120.0,
                    measure_index=1,
                ),
                NoteEvent(
                    pitch=66, onset=1.0, duration=0.5, tempo=120.0,
                    measure_index=2,
                ),
                NoteEvent(
                    pitch=67, onset=2.0, duration=0.5, tempo=120.0,
                    measure_index=3,
                ),
                NoteEvent(
                    pitch=69, onset=3.0, duration=0.5, tempo=120.0,
                    measure_index=4,
                ),
            ]

    adapter = _AdapterWithMeasures()

    def _fake_load(
        _filepath: Path, *, track_id: int | None = None,
    ) -> tuple[Any, list[NoteEvent]]:
        del track_id
        return adapter, adapter.parse(file_path)

    def _fake_legacy(
        events: list[NoteEvent], *, rule_preferences: Any = None
    ) -> tuple[list[Any], dict[str, int]]:
        del rule_preferences
        # Use real FingeringResult so audit_score can read measure_index +
        # voice_hint via the embedded NoteEvent.
        out: list[FingeringResult] = []
        for i, ev in enumerate(events):
            state = FingeringState(
                string_num=3, fret=5, finger=Finger.INDEX, hand_position=5,
            )
            out.append(FingeringResult(
                note_id=i, note_event=ev, state=state,
                cost=1.0, alternatives=[],
            ))
        return out, {"parsed": len(events)}

    def _fake_core(*_args: Any, **kwargs: Any) -> Any:
        del kwargs
        return SimpleNamespace(svg="<svg/>", conformance_issues=[])

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline", _fake_legacy)
    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _fake_core)
    # Force ML model off so the test doesn't depend on the ONNX file.
    monkeypatch.setattr(
        "fretwise.web.app._get_player_cost_model", lambda: None,
    )

    endpoint = _route_endpoint(app, "/api/solve/{filename}")
    payload = asyncio.run(endpoint(
        filename="song.gp", track_id=None,
        representation_mode="standard+tablature",
    ))

    assert "audit" in payload
    audit = payload["audit"]
    assert audit["available"] is True
    assert audit["overall"] in ("clean", "suspect", "bad")
    assert audit["ml_signal_available"] is False
    # Explicit section markers → 2 movements named Movement A / Movement B.
    movements = audit["movements"]
    assert len(movements) == 2
    assert [m["span"]["name"] for m in movements] == ["Movement A", "Movement B"]
    assert all(m["span"]["source"] == "explicit" for m in movements)
    # All notes are cheap and the source is clean → both movements clean.
    assert all(m["verdict"] == "clean" for m in movements)


def test_export_pdf_uses_legacy_engine_and_shadows_core_conformance(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """Export goes through the legacy renderer (fingering present); the core
    engine is run in shadow to report conformance via response headers."""
    file_path = tmp_path / "song.gp"
    file_path.touch()
    app = create_app(tmp_path)
    adapter = _DummyAdapter()

    def _fake_load(
        _filepath: Path,
        *,
        track_id: int | None = None,
    ) -> tuple[Any, list[NoteEvent]]:
        del track_id
        return adapter, adapter.parse(file_path)

    captured: dict[str, Any] = {}

    def _fake_legacy_render(
        _filepath: Path, _adapter: Any, _events: list[NoteEvent],
    ) -> bytes:
        captured["legacy_called"] = True
        return b"%PDF-legacy"

    def _fake_shadow(
        _filepath: Path, _adapter: Any, _events: list[NoteEvent],
        *, representation_mode: RepresentationMode,
    ) -> tuple[int, bool]:
        captured["shadow_representation_mode"] = representation_mode
        return 0, False

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._render_legacy_pdf_payload", _fake_legacy_render)
    monkeypatch.setattr(
        "fretwise.web.app._shadow_core_conformance_outcome", _fake_shadow,
    )

    endpoint = _route_endpoint(app, "/api/export/pdf/{filename}")
    response = asyncio.run(
        endpoint(
            filename="song.gp",
            track_id=None,
            representation_mode="tab+rhythm",
        )
    )
    assert response.status_code == 200
    assert response.headers["x-fretwise-pdf-engine"] == "legacy"
    assert captured["legacy_called"] is True
    assert captured["shadow_representation_mode"] == RepresentationMode.TAB_RHYTHM


def test_run_core_pipeline_for_events_propagates_measure_time_signatures(
    monkeypatch: Any, tmp_path: Path
) -> None:
    """_run_core_pipeline_for_events must pass measure_time_signatures to legacy_parse_to_raw_score.

    Regression test for the Aigle Noir bug: the web handler was calling
    legacy_parse_to_raw_score without measure_time_signatures, causing the
    mapper to use a uniform global meter for all measures even when the
    score contained meter changes (e.g. 4/4 → 3/4 at measure 77).
    """
    file_path = tmp_path / "song.gp"
    file_path.touch()

    class _VariableMeterAdapter(_DummyAdapter):
        beats_per_measure: float = 4.0
        measure_time_signatures: dict[int, tuple[int, int]] = {
            1: (4, 4),
            77: (3, 4),
        }
        key_signature_fifths: int = -2  # Bb major (2 flats)

    adapter = _VariableMeterAdapter()
    events = [
        NoteEvent(
            pitch=60,
            onset=0.0,
            duration=1.0,
            tempo=120.0,
            articulation=Articulation.NORMAL,
            dynamic=Dynamic.MF,
            voice_hint=0,
            string_hint=1,
            fret_hint=0,
            measure_index=1,
        )
    ]

    captured: dict[str, Any] = {}

    import fretwise.core.ingest.adapters as ingest_adapters

    original_fn = ingest_adapters.legacy_parse_to_raw_score

    def _capturing_legacy_parse(path: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return original_fn(path, **kwargs)

    monkeypatch.setattr(
        "fretwise.web.app.legacy_parse_to_raw_score",
        _capturing_legacy_parse,
    )

    # Run with a fake downstream pipeline that just returns a minimal result
    from fretwise.core.ingest import RawScore

    def _fake_run_core(raw: RawScore, **kwargs: Any) -> Any:
        return SimpleNamespace(
            normalized_score=None,
            completed_score=None,
            validation_report=None,
            decision_outcome=None,
            canonical_score=None,
            render_scene=SimpleNamespace(document_scene=SimpleNamespace(pages=[])),
            conformance_issues=[],
            svg="<svg/>",
        )

    monkeypatch.setattr("fretwise.web.app.run_core_pipeline_from_raw", _fake_run_core)

    _run_core_pipeline_for_events(
        file_path,
        adapter,
        events,
        representation_mode=RepresentationMode.STANDARD_TAB,
    )

    assert "measure_time_signatures" in captured, (
        "measure_time_signatures was not passed to legacy_parse_to_raw_score"
    )
    assert captured["measure_time_signatures"] == {1: (4, 4), 77: (3, 4)}, (
        f"Expected measure_time_signatures {{1:(4,4), 77:(3,4)}}, "
        f"got {captured.get('measure_time_signatures')}"
    )
    assert "key_signature_fifths" in captured, (
        "key_signature_fifths was not passed to legacy_parse_to_raw_score"
    )
    assert captured["key_signature_fifths"] == -2
