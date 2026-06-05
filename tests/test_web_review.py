"""End-to-end smoke tests for the review HTTP endpoints (FastAPI TestClient)."""
from __future__ import annotations

import shutil
from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from fretwise.web.app import create_app

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
