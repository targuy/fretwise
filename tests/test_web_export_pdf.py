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
    _render_legacy_pdf_payload,
    _safe_pdf_filename,
    create_app,
)


class _DummyAdapter:
    track_name: str = "Lead Guitar"
    section_markers: dict[int, str] = {1: "Intro"}
    chord_diagrams: list[Any] = []
    chord_markers: dict[str, str] = {}
    beats_per_measure: float = 4.0

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


def _legacy_result() -> Any:
    note_event = NoteEvent(
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
    state = SimpleNamespace(
        string_num=1,
        fret=0,
        finger="1",
        hand_position=0,
    )
    return SimpleNamespace(
        note_id=1,
        note_event=note_event,
        state=state,
        cost=1.23,
    )


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


def test_render_legacy_pdf_payload_returns_pdf_and_zero_conformance_count(
    tmp_path: Path,
) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    captured: dict[str, Any] = {}

    def _fake_render_pdf_tab(*_args: Any, **kwargs: Any) -> None:
        output = _args[1]
        assert isinstance(output, Path)
        output.write_bytes(b"%PDF-legacy")

    def _fake_shadow(*_args: Any, **kwargs: Any) -> tuple[int, bool]:
        captured["representation_mode"] = kwargs["representation_mode"]
        return 0, False

    from fretwise.web import app as web_app

    monkeypatch = pytest.MonkeyPatch()
    monkeypatch.setattr(web_app, "render_pdf_tab", _fake_render_pdf_tab)
    monkeypatch.setattr(web_app, "_shadow_core_conformance_outcome", _fake_shadow)
    pdf_bytes, conformance_issues, shadow_failed = _render_legacy_pdf_payload(
        file_path,
        adapter,
        adapter.parse(file_path),
        mode="reference",
        representation_mode=RepresentationMode.TAB_RHYTHM,
    )
    monkeypatch.undo()
    assert pdf_bytes.startswith(b"%PDF-legacy")
    assert conformance_issues == 0
    assert shadow_failed is False
    assert captured["representation_mode"] == RepresentationMode.TAB_RHYTHM


def test_render_legacy_pdf_payload_reports_shadow_core_conformance_count(
    monkeypatch: Any, tmp_path: Path
) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    def _fake_run_core(*_args: Any, **_kwargs: Any) -> Any:
        return SimpleNamespace(conformance_issues=[object(), object()])

    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _fake_run_core)

    pdf_bytes, conformance_issues, shadow_failed = _render_legacy_pdf_payload(
        file_path,
        adapter,
        adapter.parse(file_path),
        mode="reference",
        representation_mode=RepresentationMode.TAB,
    )
    assert pdf_bytes.startswith(b"%PDF-")
    assert conformance_issues == 2
    assert shadow_failed is False


def test_render_legacy_pdf_payload_ignores_shadow_core_failures(
    monkeypatch: Any, tmp_path: Path
) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    def _raise(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("boom")

    monkeypatch.setattr("fretwise.web.app._run_core_pipeline_for_events", _raise)

    pdf_bytes, conformance_issues, shadow_failed = _render_legacy_pdf_payload(
        file_path,
        adapter,
        adapter.parse(file_path),
        mode="reference",
        representation_mode=RepresentationMode.TAB,
    )
    assert pdf_bytes.startswith(b"%PDF-")
    assert conformance_issues == 0
    assert shadow_failed is True


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
        events: list[NoteEvent], *, mode: str
    ) -> tuple[list[Any], dict[str, int]]:
        del mode
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
            mode="reference",
            representation_mode="standard+tablature",
        )
    )
    assert payload["representation_mode"] == "standard_tablature"
    assert payload["core_svg"] == "<svg id='core'/>"
    assert payload["core_conformance_issues"] == 2
    assert payload["results"][0]["string"] == 1


def test_export_pdf_core_engine_uses_requested_representation_mode(
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

    captured: dict[str, Any] = {}

    def _fake_render(
        _filepath: Path,
        _adapter: Any,
        _events: list[NoteEvent],
        *,
        representation_mode: RepresentationMode,
    ) -> tuple[bytes, int]:
        captured["representation_mode"] = representation_mode
        return b"%PDF-core", 0

    monkeypatch.setattr("fretwise.web.app._load_adapter_and_events", _fake_load)
    monkeypatch.setattr("fretwise.web.app._render_core_pdf_payload", _fake_render)

    endpoint = _route_endpoint(app, "/api/export/pdf/{filename}")
    response = asyncio.run(
        endpoint(
            filename="song.gp",
            track_id=None,
            mode="reference",
            engine="core",
            representation_mode="tab+rhythm",
        )
    )
    assert response.status_code == 200
    assert response.headers["x-fretwise-pdf-engine"] == "core"
    assert captured["representation_mode"] == RepresentationMode.TAB_RHYTHM
