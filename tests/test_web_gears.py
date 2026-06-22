"""HTTP tests for the new-format gears source (single flat dir, JSON > .md)."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from fretwise.web import settings as web_settings
from fretwise.web.app import create_app


def _doc(artist: str, title: str, confidence: str = "high") -> dict:
    return {
        "schemaVersion": "songsgear.fretwise.rig.v1",
        "exportKind": "rig",
        "song": {"artist": artist, "title": title, "genre": "hard rock"},
        "rig": {
            "rigName": f"{artist} - {title} - Valeton GP-180",
            "status": "draft", "confidence": confidence, "needsReview": True,
            "equipment": {"model": "Valeton GP-180"},
            "guitar": "Gibson SG", "output": "FRFR / headphones",
            "toneProfile": "Crunch.", "signalChainSummary": "UK SLP into UK Vintage 4x12.",
            "blocks": [
                {"order": 6, "role": "Amplifier", "module": "AMP", "model": "UK SLP",
                 "active": True, "settings": {"gain": 42}, "purpose": "", "matchQuality": "exact",
                 "gap": "", "alternatives": []},
            ],
        },
        "musicalVerdict": {"targetTone": "Crunch.", "mustHave": [], "avoid": [], "gearClues": [],
                           "corrections": [], "confidence": confidence, "needsManualReview": False},
        "musicalContext": {"primaryGenre": "hard rock", "styleTags": [], "targetTone": "Crunch.",
                           "confidence": confidence},
        "improvements": {"summary": "ok", "proposals": [
            {"priority": "P1", "type": "IR", "target": "Cabinet", "recommendedAsset": "Greenback IR",
             "reason": "x", "replacesBlockOrder": 7, "whenToUse": "always", "expectedGain": "high",
             "requiredIfGp180Gap": True}]},
        "validation": {"ok": True, "errors": [], "warnings": []},
        "source": {"workflow": "economic_production_v1", "finalVerdictSource": "openai",
                   "usedLocalGp180Fallback": False, "usedLocalImprovementsFallback": False},
    }


_LEGACY_MD = """# Rig GP-180 — AC/DC · Highway to Hell

Artiste : AC/DC
Chanson : Highway to Hell
Genre : hard rock
Fiabilité : B — Solide

Réglages GP-180 :
- AMP : UK 45 · Gain 45
"""


def _client(tmp_path: Path, monkeypatch, *, with_md: bool = False, with_json: bool = False) -> TestClient:
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    rigs = tmp_path / "rigs"
    rigs.mkdir()
    if with_md:
        (rigs / "rig_highway_to_hell_ac_dc.md").write_text(_LEGACY_MD, encoding="utf-8")
    gears = tmp_path / "gears"
    gears.mkdir()
    if with_json:
        (gears / "ac-dc__highway-to-hell.json").write_text(
            json.dumps(_doc("AC/DC", "Highway to Hell")), encoding="utf-8"
        )
    web_settings.save({"gears_dir": str(gears)})
    app = create_app(fixtures_dir=tmp_path)
    return TestClient(app)


def test_gears_json_is_served_as_view(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_json=True)
    res = client.get("/api/rig/AC_DC - Highway to Hell.gp5")
    assert res.status_code == 200
    view = res.json()
    assert view["is_gears"] is True
    assert view["fiabilite"] == "A"  # high -> A
    assert view["reglages"]["AMP"]["preset"] == "UK SLP"
    assert view["improvements"]["proposals"]


def test_gears_json_preferred_over_legacy_md(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_md=True, with_json=True)
    view = client.get("/api/rig/AC_DC - Highway to Hell.gp5").json()
    # JSON wins: grade A and the gears AMP, not the .md's B / UK 45.
    assert view.get("is_gears") is True
    assert view["fiabilite"] == "A"
    assert view["reglages"]["AMP"]["preset"] == "UK SLP"


def test_legacy_md_used_when_no_gears_json(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_md=True, with_json=False)
    view = client.get("/api/rig/AC_DC - Highway to Hell.gp5").json()
    assert view.get("is_gears") is not True
    assert view["fiabilite"] == "B"  # from the .md
    assert view["reglages"]["AMP"]["preset"] == "UK 45"


def test_no_models_endpoint(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_json=True)
    assert client.get("/api/gears/models").status_code == 404


def test_missing_song_404(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_json=True)
    assert client.get("/api/rig/Nobody - Unknown.gp5").status_code == 404
