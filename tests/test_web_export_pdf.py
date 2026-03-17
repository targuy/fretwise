"""Tests for web PDF export helpers (legacy/core engines)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from fretwise.models import Articulation, Dynamic, NoteEvent
from fretwise.parser.base import UnsupportedFormatError
from fretwise.web.app import (
    _infer_source_format,
    _load_adapter_and_events,
    _render_core_pdf_bytes,
    _render_legacy_pdf_bytes,
    _safe_pdf_filename,
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


def test_render_core_pdf_bytes_returns_pdf(tmp_path: Path) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    pdf_bytes = _render_core_pdf_bytes(file_path, adapter, adapter.parse(file_path))
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/Type /Page" in pdf_bytes


def test_render_legacy_pdf_bytes_returns_pdf(tmp_path: Path) -> None:
    adapter = _DummyAdapter()
    file_path = tmp_path / "song.gp"
    file_path.touch()

    pdf_bytes = _render_legacy_pdf_bytes(
        file_path,
        adapter,
        adapter.parse(file_path),
        mode="reference",
    )
    assert pdf_bytes.startswith(b"%PDF-")
    assert b"/Type /Page" in pdf_bytes


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

