"""Saved/generated fingerings remain readable but never certify fatal constraints."""

from __future__ import annotations

import json
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from fretwise.biomechanics import validate_fingering_results
from fretwise.export.gp_writer import write_gp_with_fingerings
from fretwise.models import Finger
from fretwise.web.app import (
    FINGERING_ALGO_VERSION,
    _fingering_data_path,
    _solve_cache_clear,
)
from tests.test_web_fingering_version_status import _Case, _sidecar, _solve
from tests.test_web_fingering_version_status import case as case


@pytest.mark.parametrize("version", ["2.2", FINGERING_ALGO_VERSION])
@pytest.mark.parametrize("saved_report", [False, True])
def test_invalid_saved_decisions_are_flagged_without_optimizing(
    case: _Case, version: str, saved_report: bool,
) -> None:
    case.results[1].state.finger = Finger.OPEN
    report = validate_fingering_results([case.results[1]])
    assert report.fatal_count > 0
    _sidecar(case, header=version, tracks={1: version})
    if saved_report:
        path = _fingering_data_path(case.source)
        data = json.loads(path.read_text(encoding="utf-8"))
        data["tracks"]["1"]["audit"] = {
            "available": True, "overall": "clean", "biomechanical_report": asdict(report),
        }
        path.write_text(json.dumps(data), encoding="utf-8")
    before = {path.name: path.read_bytes() for path in case.source.parent.glob("*")}
    payload = _solve(TestClient(case.app))
    assert payload["fingering_validity"] == "invalid"
    assert payload["biomechanical_fatal"] == report.fatal_count
    assert payload["fatal_measures"] == [1]
    assert payload["fingering_is_current"] is (version == FINGERING_ALGO_VERSION)
    assert payload["fingering_is_outdated"] is (version == "2.2")
    assert payload["core_svg"] == "<svg/>"
    assert before == {path.name: path.read_bytes() for path in case.source.parent.glob("*")}


def test_failed_audit_does_not_lose_computed_guard_on_save_or_reopen(
    case: _Case, monkeypatch: pytest.MonkeyPatch,
) -> None:
    case.results[1].state.finger = Finger.OPEN
    report = validate_fingering_results([case.results[1]])
    monkeypatch.setattr("fretwise.web.app._run_legacy_pipeline_with_guard", lambda events:
                        SimpleNamespace(results=[case.results[1]], biomechanical_report=report))
    monkeypatch.setattr("fretwise.web.app._safe_audit", lambda *args:
                        {"available": False, "error": "Model unavailable"})
    client = TestClient(case.app)
    response = client.post("/api/save/gp/song.gp?track_id=1")
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["sidecar_saved"] is True
    assert saved["fingering_validity"] == "invalid"
    assert saved["biomechanical_fatal"] == report.fatal_count
    loaded = _solve(client)
    assert loaded["fingering_is_current"] is True
    assert loaded["fingering_validity"] == "invalid"
    assert loaded["biomechanical_fatal"] == report.fatal_count
    assert loaded["core_svg"] == "<svg/>"
    # Existing GP guard remains scoped to the GP export; reading is unaffected.
    assert client.get("/api/export/gp/song.gp?track_id=1").status_code == 409


def test_unknown_legacy_rows_cannot_be_reported_valid(case: _Case) -> None:
    _sidecar(case, header=FINGERING_ALGO_VERSION, tracks={1: FINGERING_ALGO_VERSION})
    path = _fingering_data_path(case.source)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["tracks"]["1"]["results"][0]["onset"] = 1000
    path.write_text(json.dumps(data), encoding="utf-8")
    payload = _solve(TestClient(case.app))
    assert payload["fingering_validity"] == "unknown"
    assert payload["biomechanical_fatal"] is None
    assert payload["fingering_is_current"] is True


def test_valid_current_and_unfingered_tracks_have_distinct_status(case: _Case) -> None:
    client = TestClient(case.app)
    assert _solve(client)["fingering_validity"] == "unavailable"
    _sidecar(case, header=FINGERING_ALGO_VERSION, tracks={1: FINGERING_ALGO_VERSION})
    payload = _solve(client)
    assert payload["fingering_validity"] == "valid"
    assert payload["biomechanical_fatal"] == 0
    assert payload["fingering_validation_scope"] == "displayed"


def test_legacy_invalid_saved_scope_does_not_claim_valid_embedded_decisions_invalid(
    case: _Case,
) -> None:
    case.source.write_bytes(write_gp_with_fingerings(case.source, {"1": "I"}))
    case.results[1].state.finger = Finger.OPEN
    _sidecar(case, header="2.2", tracks={1: "2.2"})
    payload = _solve(TestClient(case.app))
    assert payload["fingering_validity"] == "invalid"
    assert payload["fingering_validation_scope"] == "saved"
    assert payload["stats"]["from_embedded"] is True
    assert payload["results"][0]["finger"] == "index"


def test_invalid_embedded_display_takes_priority_over_valid_old_saved_report(case: _Case) -> None:
    case.source.write_bytes(write_gp_with_fingerings(case.source, {"1": "I"}))
    _sidecar(case, header="2.2", tracks={1: "2.2"})
    path = _fingering_data_path(case.source)
    data = json.loads(path.read_text(encoding="utf-8"))
    data["tracks"]["1"]["validation"] = {
        "fingering_validity": "valid", "biomechanical_fatal": 0,
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    case.results[1].note_event.fret_hint = 40
    case.results[1].note_event.pitch = 104
    _solve_cache_clear()
    payload = _solve(TestClient(case.app))
    assert payload["fingering_validity"] == "invalid"
    assert payload["fingering_validation_scope"] == "displayed"
    assert payload["biomechanical_fatal"] > 0
