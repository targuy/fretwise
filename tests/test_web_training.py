"""Smoke tests for the /api/training/* endpoints (scale/chord warm-up module)."""
from __future__ import annotations

from pathlib import Path
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from fretwise.web.app import create_app


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return TestClient(create_app(fixtures_dir=tmp_path))


def test_training_scales_lists_known_scales(client: TestClient) -> None:
    res = client.get("/api/training/scales")
    assert res.status_code == 200
    body = res.json()
    names = {s["name"] for s in body}
    assert "major" in names
    assert "minor_pentatonic" in names
    assert all(s["label"] for s in body)


def test_training_scale_boxes_g_major(client: TestClient) -> None:
    res = client.get("/api/training/scale/major", params={"root": "G"})
    assert res.status_code == 200
    body = res.json()
    assert body["root"] == "G"
    assert body["boxes"]
    pos1 = next(b for b in body["boxes"] if b["name"] == "position_1")
    low_e_frets = sorted(n["fret"] for n in pos1["notes"] if n["string"] == 6)
    assert low_e_frets == [3, 5, 7]


def test_training_scale_boxes_default_root(client: TestClient) -> None:
    res = client.get("/api/training/scale/major")
    assert res.status_code == 200
    assert res.json()["root"] == "E"


def test_training_scale_boxes_unknown_scale_404s(client: TestClient) -> None:
    res = client.get("/api/training/scale/nonexistent_scale")
    assert res.status_code == 404


def test_training_chord_am(client: TestClient) -> None:
    res = client.get("/api/training/chord/Am")
    assert res.status_code == 200
    body = res.json()
    assert body["name"] == "Am"
    assert body["voicings"][0]["frets"] == [0, 1, 2, 2, 0, -1]


def test_training_chord_offers_alternate_positions(client: TestClient) -> None:
    """A chord with no open voicing (C#m) must still return playable barre positions."""
    res = client.get(f"/api/training/chord/{quote('C#m')}")
    assert res.status_code == 200
    voicings = res.json()["voicings"]
    assert len(voicings) >= 2
    frets = [v["base_fret"] for v in voicings]
    assert frets == sorted(frets)  # lowest position first


def test_training_chord_unknown_404s(client: TestClient) -> None:
    res = client.get("/api/training/chord/Zzzz9")
    assert res.status_code == 404
