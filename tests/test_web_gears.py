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


def _doc_v2(artist: str, title: str, confidence: str = "high") -> dict:
    return {
        "schemaVersion": "songsgear.fretwise.gear.v2",
        "song": {"artist": artist, "title": title, "genre": "hard rock"},
        "credits": {
            "guitar": {
                "guitaristsText": "Angus Young / Malcolm Young",
                "type": "Solid-body electric",
                "modelsText": "Gibson SG (Angus) / Gretsch Jet Firebird (Malcolm)",
                "confidence": "high",
            }
        },
        "tone": {"target": "Crunch.", "profile": "Crunch.", "summary": "UK SLP.", "confidence": confidence},
        "rig": {
            "name": f"{artist} - {title} - Valeton GP-180",
            "confidence": confidence,
            "equipment": {"model": "Valeton GP-180"},
            "output": "FRFR / headphones",
            "blocks": [
                {"order": 6, "role": "Amplifier", "module": "AMP", "model": "UK SLP",
                 "active": True, "settings": {"gain": 42}, "purpose": "", "matchQuality": "exact",
                 "gap": "", "alternatives": []},
            ],
        },
        "improvements": {"summary": "ok", "proposals": []},
        "audit": {"validation": {"ok": True, "errors": [], "warnings": []}},
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


def test_song_info_falls_back_to_gears_metadata(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(web_settings, "_CONFIG_DIR", tmp_path / ".fretwise")
    monkeypatch.setattr(web_settings, "_CONFIG_FILE", tmp_path / ".fretwise" / "config.json")
    gears = tmp_path / "gears"
    gears.mkdir()
    (gears / "ac-dc__highway-to-hell.json").write_text(
        json.dumps(_doc_v2("AC/DC", "Highway to Hell")), encoding="utf-8"
    )
    web_settings.save({"gears_dir": str(gears), "index_path": ""})
    client = TestClient(create_app(fixtures_dir=tmp_path))

    res = client.get("/api/song-info/AC_DC - Highway to Hell.gp5")

    assert res.status_code == 200
    info = res.json()
    assert info["artist"] == "AC/DC"
    assert info["title"] == "Highway to Hell"
    assert info["guitarists"] == "Angus Young / Malcolm Young"
    assert info["original_guitar"] == "Gibson SG (Angus) / Gretsch Jet Firebird (Malcolm)"


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


def test_gear_prompt_grounds_in_existing_sheet(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_json=True)
    res = client.get("/api/gears/AC_DC - Highway to Hell.gp5/prompt")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("text/markdown")
    body = res.text
    assert "AC/DC" in body
    assert "Highway to Hell" in body
    assert "songsgear.fretwise.gear.v2" in body
    assert '"UK SLP"' in body  # the existing sheet's AMP model is echoed back for review


def test_gear_prompt_falls_back_to_filename_when_no_sheet(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    res = client.get("/api/gears/AC_DC - Highway to Hell.gp5/prompt")
    assert res.status_code == 200
    assert "AC_DC" in res.text
    assert "Highway to Hell" in res.text


def test_save_gear_sheet_overwrites_existing_in_place(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch, with_json=True)
    gears_dir = Path(web_settings.load()["gears_dir"])
    original_path = gears_dir / "ac-dc__highway-to-hell.json"
    assert original_path.is_file()

    corrected = _doc_v2("AC/DC", "Highway to Hell", confidence="high")
    corrected["rig"]["blocks"][0]["model"] = "UK 45"

    res = client.post("/api/gears/AC_DC - Highway to Hell.gp5/save", json={"gear": corrected})
    assert res.status_code == 200
    payload = res.json()
    assert payload["saved"] == "ac-dc__highway-to-hell.json"
    assert payload["view"]["reglages"]["AMP"]["preset"] == "UK 45"
    # No stray second file: the pre-existing sheet was overwritten, not duplicated.
    assert sorted(p.name for p in gears_dir.glob("*.json")) == ["ac-dc__highway-to-hell.json"]

    view = client.get("/api/rig/AC_DC - Highway to Hell.gp5").json()
    assert view["reglages"]["AMP"]["preset"] == "UK 45"


def test_save_gear_sheet_creates_canonical_file_when_absent(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    gears_dir = Path(web_settings.load()["gears_dir"])
    gear = _doc_v2("Metallica", "Enter Sandman")

    res = client.post("/api/gears/Metallica - Enter Sandman.gp5/save", json={"gear": gear})
    assert res.status_code == 200
    assert res.json()["saved"] == "metallica__enter-sandman.json"
    assert (gears_dir / "metallica__enter-sandman.json").is_file()

    view = client.get("/api/rig/Metallica - Enter Sandman.gp5").json()
    assert view["is_gears"] is True


def test_save_gear_sheet_rejects_invalid_document(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    bad = {"schemaVersion": "songsgear.fretwise.gear.v2", "song": {"artist": "X"}}  # no title, no blocks

    res = client.post("/api/gears/X - Y.gp5/save", json={"gear": bad})

    assert res.status_code == 400
    assert "song.title" in res.text
