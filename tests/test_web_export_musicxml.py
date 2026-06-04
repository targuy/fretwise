"""Tests for the web MusicXML export endpoint (/api/export/musicxml)."""

from __future__ import annotations

import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytest.importorskip("music21")

from fretwise.web.app import create_app  # noqa: E402

_FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "Nirvana-Smells Like Teen Spirit-12-18-2025.mid"
)


def _client_with_fixture(tmp_path: Path) -> tuple[TestClient, str]:
    dest = tmp_path / _FIXTURE.name
    shutil.copy(_FIXTURE, dest)
    return TestClient(create_app(tmp_path)), dest.name


def test_export_musicxml_returns_valid_document(tmp_path: Path) -> None:
    client, name = _client_with_fixture(tmp_path)
    res = client.get(f"/api/export/musicxml/{name}")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert ".musicxml" in res.headers["content-disposition"]

    root = ET.fromstring(res.text)
    assert root.tag in ("score-partwise", "score-timewise")
    # Every fretted note must carry a tablature technical block.
    technicals = list(root.iter("technical"))
    assert technicals, "expected per-note <technical> string/fret blocks"


def test_export_musicxml_not_blocked_by_biomechanical_guard(tmp_path: Path) -> None:
    # Unlike GP export, MusicXML is a view format and must succeed even when the
    # guard reports violations — the count is surfaced via a header instead.
    client, name = _client_with_fixture(tmp_path)
    res = client.get(f"/api/export/musicxml/{name}")
    assert res.status_code == 200
    assert "x-fretwise-note-count" in res.headers
    assert int(res.headers["x-fretwise-note-count"]) > 0


def test_export_musicxml_missing_file_is_404(tmp_path: Path) -> None:
    client = TestClient(create_app(tmp_path))
    res = client.get("/api/export/musicxml/nope.mid")
    assert res.status_code == 404


def test_export_musicxml_scope_current_matches_default(tmp_path: Path) -> None:
    # scope=current (or absent) must hit the unchanged single-track path: same
    # one-part document, same content. (music21 assigns a random part id, so we
    # compare structure/length rather than raw bytes.)
    client, name = _client_with_fixture(tmp_path)
    default = client.get(f"/api/export/musicxml/{name}")
    current = client.get(f"/api/export/musicxml/{name}", params={"scope": "current"})
    assert current.status_code == 200
    assert ".musicxml" in current.headers["content-disposition"]
    assert "_all" not in current.headers["content-disposition"]
    assert default.text.count("<part ") == 1
    assert current.text.count("<part ") == 1
    assert len(default.text) == len(current.text)
    assert "x-fretwise-part-count" not in default.headers


def test_export_musicxml_unknown_scope_is_400(tmp_path: Path) -> None:
    client, name = _client_with_fixture(tmp_path)
    res = client.get(f"/api/export/musicxml/{name}", params={"scope": "bogus"})
    assert res.status_code == 400


def test_export_musicxml_scope_all_returns_multipart_document(tmp_path: Path) -> None:
    # scope=all returns a valid multi-part score with the _all filename suffix
    # and a part-count header. The MIDI adapter exposes a single track, so the
    # fallback yields exactly one (guitar) part with tablature technicals.
    client, name = _client_with_fixture(tmp_path)
    res = client.get(f"/api/export/musicxml/{name}", params={"scope": "all"})
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    assert "_all.musicxml" in res.headers["content-disposition"]
    assert res.headers["x-fretwise-part-count"] == "1"
    assert int(res.headers["x-fretwise-note-count"]) > 0

    root = ET.fromstring(res.text)
    assert root.tag in ("score-partwise", "score-timewise")
    parts = root.findall("part")
    assert len(parts) == 1
    score_parts = root.findall("part-list/score-part")
    assert len(score_parts) == 1
    # part-list ids line up 1:1 with <part> ids.
    assert [sp.get("id") for sp in score_parts] == [p.get("id") for p in parts]
    # Guitar fallback → tablature technicals present.
    assert list(root.iter("technical")), "expected per-note <technical> blocks"


def test_guard_summary_reports_fatal_measures_separately() -> None:
    # The GP-export block message must cite the FATAL measures specifically,
    # not every measure that has any violation.
    from types import SimpleNamespace

    from fretwise.biomechanics import (
        BiomechanicalReport,
        BiomechanicalSeverity,
        BiomechanicalViolation,
    )
    from fretwise.web.app import _guard_summary

    report = BiomechanicalReport(
        checked_notes=10,
        violations=(
            BiomechanicalViolation(
                code="x", severity=BiomechanicalSeverity.FATAL,
                message="impossible stretch", measure_index=6,
            ),
            BiomechanicalViolation(
                code="x", severity=BiomechanicalSeverity.FATAL,
                message="impossible stretch", measure_index=10,
            ),
            BiomechanicalViolation(
                code="y", severity=BiomechanicalSeverity.HIGH,
                message="awkward", measure_index=14,
            ),
        ),
    )
    summary = _guard_summary(SimpleNamespace(biomechanical_report=report))
    assert summary["fatal"] == 2
    assert summary["fatal_measures"] == [6, 10]  # not 14 (high, not fatal)
    assert summary["fatal_measure_count"] == 2
