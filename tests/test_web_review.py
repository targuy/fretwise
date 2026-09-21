"""End-to-end smoke tests for the review HTTP endpoints (FastAPI TestClient)."""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.web.app import _build_review_hand_performance, create_app

_FIXTURE = (
    Path(__file__).parent / "fixtures"
    / "Nirvana-Smells Like Teen Spirit-12-18-2025.mid"
)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    shutil.copy2(_FIXTURE, tmp_path / _FIXTURE.name)
    return TestClient(create_app(fixtures_dir=tmp_path))


def _first_file(client: TestClient) -> str:
    files = client.get("/api/files").json()
    assert files, "fixture not listed"
    return files[0]["name"]


def test_review_endpoint_responds(client: TestClient) -> None:
    name = _first_file(client)
    res = client.get(f"/api/review/{quote(name)}")
    assert res.status_code == 200
    body = res.json()
    assert "items" in body
    assert "counts" in body


def test_alternatives_endpoint_responds(client: TestClient) -> None:
    name = _first_file(client)
    res = client.get(f"/api/review/{quote(name)}/alternatives", params={"measure_index": 1})
    assert res.status_code == 200
    body = res.json()
    assert body["measure_index"] == 1
    assert isinstance(body["alternatives"], list)
    # Tempo + tuning remain available for the compact look-ahead host.
    assert isinstance(body["tempo"], (int, float))
    assert isinstance(body["tuning"], list) and len(body["tuning"]) == 6
    for alt in body["alternatives"]:
        # Animation consumes the canonical v2 contract, not a reconstruction
        # from the legacy frame list in the browser.
        assert alt["hand_performance_error"] is None
        performance = alt["hand_performance"]
        assert performance["schemaVersion"] == "1.1"
        assert performance["range"]["startTick"] == 0
        rendered = {
            (note["fingering"]["stringNo"], note["fingering"]["fretAbs"],
             note["fingering"]["finger"])
            for note in performance["notes"]
        }
        expected = {
            (fingering["string"], fingering["fret"], fingering["finger"])
            for fingering in alt["fingerings"]
        }
        assert rendered == expected
        # Proposed (non-current) alternatives are all playable.
        if not alt["is_current"]:
            assert alt["playable"] is True


def test_review_alternative_builds_shifted_canonical_hand_performance() -> None:
    events = [
        NoteEvent(
            pitch=60,
            onset=8.0,
            duration=0.5,
            tempo=120,
            string_hint=2,
            fret_hint=1,
            voice_hint=0,
            measure_index=3,
            source_note_id="review-a",
        ),
        NoteEvent(
            pitch=64,
            onset=8.5,
            duration=0.5,
            tempo=120,
            string_hint=1,
            fret_hint=0,
            voice_hint=0,
            measure_index=3,
            source_note_id="review-b",
        ),
    ]
    results = [
        FingeringResult(10, events[0], FingeringState(2, 1, Finger.INDEX, 1), 0.0),
        FingeringResult(11, events[1], FingeringState(1, 0, Finger.OPEN, 1), 0.0),
    ]
    alternative = [
        {"note_id": 10, "string": 3, "fret": 5, "finger": "ring", "hand_position": 3},
        {"note_id": 11, "string": 1, "fret": 0, "finger": "open", "hand_position": 3},
    ]

    performance = _build_review_hand_performance(
        results,
        alternative,
        filename="review.gp",
        track_id=2,
        measure_index=3,
        score_revision_value="source-revision",
        tuning=[40, 45, 50, 55, 59, 64],
    )

    assert performance["schemaVersion"] == "1.1"
    assert performance["range"]["startTick"] == 0
    assert performance["notes"][0]["onTick"] == 0
    assert performance["notes"][0]["fingering"] == {
        "finger": "ring",
        "stringNo": 3,
        "fretAbs": 5,
        "handPositionHint": 3,
        "provenance": "computed",
        "locked": False,
    }


def test_review_hand_preview_uses_versioned_same_origin_transport() -> None:
    js = (
        Path(__file__).parents[1]
        / "src" / "fretwise" / "web" / "static" / "js" / "review.js"
    ).read_text(encoding="utf-8")

    assert "alternative.hand_performance" in js
    assert "type: 'fretwise:load'" in js
    assert "type !== 'fretwise:ready'" in js
    assert "window.location.origin" in js
    assert "{ type: 'fretwise-hand-data'" not in js
    assert "}, '*');" not in js


def test_choice_persists_sidecar_and_corpus(client: TestClient, tmp_path: Path) -> None:
    name = _first_file(client)
    body = {
        "measure_index": 1,
        "onset": 0.0,
        "severity": "high_cost",
        "reasons": ["coût 4.0× base"],
        "chosen": [{
            "note_id": 0, "string": 2, "fret": 5, "finger": "index",
            "hand_position": 5, "onset": 0.0, "pitch": 64, "voice_hint": 0,
        }],
        "rejected": [{
            "note_id": 0, "string": 2, "fret": 5, "finger": "ring",
            "hand_position": 3, "onset": 0.0, "pitch": 64, "voice_hint": 0,
        }],
    }
    res = client.post(f"/api/review/{quote(name)}/choice", json=body)
    assert res.status_code == 200
    assert res.json()["saved"] is True

    fb_dir = tmp_path / ".fretwise_feedback"
    assert fb_dir.exists()
    assert (fb_dir / "feedback_corpus.jsonl").exists()
    sidecars = list(fb_dir.glob("*.feedback.json"))
    assert sidecars, "per-song sidecar not written"


def test_choice_rejects_empty_chosen(client: TestClient) -> None:
    name = _first_file(client)
    res = client.post(f"/api/review/{quote(name)}/choice", json={"chosen": []})
    assert res.status_code == 400
