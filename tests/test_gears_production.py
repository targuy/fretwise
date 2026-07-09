"""Tests for the ported gears production package (SongsGears producer side).

Covers: byte-compat of the shared naming scheme against the real corpus,
rig/export validators, the mock (offline) generation pipeline, and the
verbose-v1 -> compact-v2 -> adapter chain. No network, no LLM calls.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fretwise.gears import (
    gears_filename,
    gears_filename_for_rig,
    gears_key,
    gears_key_from_filename,
    song_output_to_view,
)
from fretwise.gears.production.fretwise_export import (
    SCHEMA_VERSION,
    attach_fretwise_export,
    validate_fretwise_export,
)
from fretwise.gears.production.llm import generate_rig
from fretwise.gears.production.render import notion_payload
from fretwise.gears.production.schema import SchemaError, load_json, validate_rig
from fretwise.gears.production.skills import (
    default_skills_dir,
    load_gp180_allowed_catalog,
    load_skill_prompt,
)
from fretwise.gears.production.tools.compact_fretwise_gears import (
    COMPACT_SCHEMA_VERSION,
    compact_sheet,
)

REPO = Path(__file__).resolve().parents[1]
GEARS_DIR = REPO / "data" / "gears"
DATA_DIR = REPO / "src" / "fretwise" / "gears" / "production" / "data"


# --- (a) naming: byte-compat with the consumer + real corpus ------------------

# Expected values computed with the existing fretwise.gears.naming code (the
# consumer reference). The producer must land on exactly these filenames.
NAMING_CASES = [
    ("AC/DC", "Highway to Hell", "ac-dc__highway-to-hell"),
    ("Earth, Wind & Fire", "Boogie Wonderland", "earth-wind-and-fire__boogie-wonderland"),
    ("Guns N' Roses", "Sweet Child O' Mine", "guns-n-roses__sweet-child-o-mine"),
    ("Jean-Jacques Goldman", "Là-bas", "jean-jacques-goldman__la-bas"),
    ("Noir Désir", "L'Homme pressé", "noir-desir__l-homme-presse"),
    ("Mötley Crüe", "Kickstart My Heart", "motley-crue__kickstart-my-heart"),
]


@pytest.mark.parametrize(("artist", "title", "expected"), NAMING_CASES)
def test_gears_key_expected_values(artist: str, title: str, expected: str) -> None:
    assert gears_key(artist, title) == expected
    assert gears_filename(artist, title) == f"{expected}.json"


@pytest.mark.parametrize(("artist", "title", "expected"), NAMING_CASES)
def test_gears_filename_for_rig_matches_gears_filename(
    artist: str, title: str, expected: str
) -> None:
    rig = {"song": {"artist": artist, "title": title}}
    assert gears_filename_for_rig(rig) == f"{expected}.json"


def test_gears_filename_for_rig_missing_song_is_empty_key() -> None:
    assert gears_filename_for_rig({}) == "__.json"


def _canonical_stem_key(stem: str) -> str:
    """Mirror the web front office: split on ``__`` and re-slugify each half."""
    if "__" in stem:
        artist, title = stem.split("__", 1)
        return gears_key(artist, title)
    return gears_key("", stem)


@pytest.mark.parametrize(
    "name",
    ["AC_DC__Highway_To_Hell.json", "10cc__I_m_Not_In_Love.json"],
)
def test_real_corpus_sheet_resolves_to_same_key(name: str) -> None:
    """A real data/gears sheet must resolve to the key its own song metadata gives."""
    path = GEARS_DIR / name
    if not path.exists():
        pytest.skip(f"{name} not present in data/gears")
    doc = json.loads(path.read_text(encoding="utf-8"))
    song = doc.get("song", {})
    key_from_metadata = gears_key(song.get("artist", ""), song.get("title", ""))
    assert _canonical_stem_key(path.stem) == key_from_metadata
    # A score filename for the same song resolves to the same key.
    score = f"{song.get('artist', '')} - {song.get('title', '')}.gp5".replace("/", "_")
    assert gears_key_from_filename(score) == key_from_metadata


# --- (b) validators ------------------------------------------------------------

def _minimal_rig() -> dict:
    block = {
        "order": 1,
        "role": "amp",
        "module": "AMP",
        "model": "UK SLP",
        "active": True,
        "settings": {"Gain": 42},
        "purpose": "Core amp.",
        "matchQuality": "exact",
        "gap": "",
        "alternatives": [],
    }
    return {
        "rigName": "AC/DC - Highway to Hell - Valeton GP-180",
        "song": {"artist": "AC/DC", "title": "Highway to Hell", "album": "", "year": 1979},
        "equipment": {"model": "Valeton GP-180"},
        "guitar": "Gibson SG",
        "output": "FRFR / headphones",
        "toneProfile": "Crunch",
        "status": "draft",
        "confidence": "high",
        "signalChainSummary": "UK SLP into UK Vintage 4x12",
        "blocks": [block],
        "general": {
            "targetSound": "Crunch",
            "toneProfile": "Crunch",
            "idealSignalChain": "SG -> Plexi",
            "bestPossibleEquipment": [],
            "productionNotes": [],
        },
        "gp180": {
            "equipment": {"model": "Valeton GP-180"},
            "guitar": "Gibson SG",
            "output": "FRFR / headphones",
            "choicePolicy": "Use only existing GP-180 models.",
            "bestMatchSummary": "UK SLP into UK Vintage 4x12",
            "blocks": [block],
        },
        "improvements": {"summary": "None needed.", "proposals": []},
        "assumptions": [],
        "warnings": [],
        "sources": [],
        "createdFrom": "generated",
        "needsReview": False,
    }


def test_validate_rig_accepts_minimal_valid_rig() -> None:
    rig = _minimal_rig()
    assert validate_rig(rig) is rig


def test_validate_rig_rejects_missing_keys() -> None:
    rig = _minimal_rig()
    del rig["gp180"]
    del rig["confidence"]
    with pytest.raises(SchemaError, match="Missing required keys"):
        validate_rig(rig)


def test_validate_rig_rejects_bad_confidence_and_empty_blocks() -> None:
    rig = _minimal_rig()
    rig["confidence"] = "certain"
    with pytest.raises(SchemaError, match="confidence"):
        validate_rig(rig)
    rig = _minimal_rig()
    rig["blocks"] = []
    with pytest.raises(SchemaError, match="blocks"):
        validate_rig(rig)


def _verbose_v1_record() -> dict:
    """Minimal verbose production record (economic_production_v1 shape)."""
    return {
        "metadata": {
            "workflow": "economic_production_v1",
            "sourceIndex": 7,
            "models": {"ollama": "test", "openaiJudge": "test", "claudeFallback": "test"},
            "finalVerdictSource": "openai",
            "openaiAction": "accept",
            "usedLocalGp180Fallback": False,
            "usedLocalImprovementsFallback": False,
        },
        "song": {
            "artist": "AC/DC",
            "title": "Highway to Hell",
            "album": "",
            "year": 1979,
            "genre": "hard rock",
        },
        "genreClassification": {
            "genre": "hard rock",
            "subgenres": ["classic rock"],
            "confidence": "high",
            "rationale": "Iconic.",
        },
        "finalVerdict": {
            "targetTone": "Dry Marshall crunch with bright upper mids",
            "mustHave": ["Power-amp drive"],
            "avoid": ["High gain"],
            "gearClues": ["Marshall Plexi"],
            "corrections": [],
            "confidence": "high",
            "needsManualReview": False,
        },
        "generated": {"Ollama": {"rig": _minimal_rig()}},
        "validation": {"ok": True, "errors": [], "warnings": []},
        "timings": [],
    }


def test_validate_fretwise_export_ok_on_attached_record() -> None:
    record = attach_fretwise_export(_verbose_v1_record())
    export = record["fretwiseExport"]
    assert export["schemaVersion"] == SCHEMA_VERSION
    validation = validate_fretwise_export(export)
    assert validation["ok"] is True
    assert validation["errors"] == []


def test_validate_fretwise_export_rejects_empty_object() -> None:
    validation = validate_fretwise_export({})
    assert validation["ok"] is False
    assert "Wrong schemaVersion." in validation["errors"]
    assert any("song" in error for error in validation["errors"])


# --- mock pipeline (no network) --------------------------------------------------

def _packaged_config() -> dict:
    return load_json(str(DATA_DIR / "config.example.json"))


def test_mock_generate_rig_is_schema_valid_and_offline() -> None:
    config = _packaged_config()
    request = {
        "artist": "AC/DC",
        "title": "Highway to Hell",
        "album": "",
        "year": "1979",
        "equipment": "Valeton GP-180",
        "guitar": "Gibson SG",
        "output": "FRFR / headphones",
        "mode": "best_match",
    }
    rig = generate_rig("mock", "mock-song-v1", request, "skill prompt", {}, config)
    assert rig["song"]["artist"] == "AC/DC"
    assert rig["blocks"]
    assert gears_filename_for_rig(rig) == "ac-dc__highway-to-hell.json"
    payload = notion_payload(rig, config)
    assert payload["properties"]["Rig Name"]["title"][0]["text"]["content"] == rig["rigName"]
    assert payload["children"]


def test_packaged_skills_resolve_and_catalog_parses() -> None:
    config = _packaged_config()
    base_dir = str(DATA_DIR)
    assert default_skills_dir().is_dir()
    prompt = load_skill_prompt(base_dir, config)
    assert "Skill stage" in prompt
    catalog = load_gp180_allowed_catalog(base_dir, config)
    assert "GP-180 ALLOWED MODEL CATALOG" in catalog
    assert "UK SLP" in catalog


def test_packaged_skills_resolve_from_foreign_base_dir(tmp_path: Path) -> None:
    """Config paths fall back to the packaged data when absent from base_dir."""
    config = _packaged_config()
    prompt = load_skill_prompt(str(tmp_path), config)
    assert "Skill stage" in prompt


# --- (c) compaction and adapter round-trip ---------------------------------------

def test_real_v2_sheet_renders_through_adapter() -> None:
    path = GEARS_DIR / "AC_DC__Highway_To_Hell.json"
    if not path.exists():
        candidates = sorted(GEARS_DIR.glob("*.json")) if GEARS_DIR.is_dir() else []
        if not candidates:
            pytest.skip("no sheet available in data/gears")
        path = candidates[0]
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["schemaVersion"] == COMPACT_SCHEMA_VERSION
    view = song_output_to_view(doc)
    assert view["is_gears"] is True
    assert view["artist"]
    assert view["reglages"]


def test_compact_v1_to_v2_then_adapter() -> None:
    record = attach_fretwise_export(_verbose_v1_record())
    compact = compact_sheet(record, source_file="AC_DC__Highway_To_Hell.json")
    assert compact["schemaVersion"] == COMPACT_SCHEMA_VERSION
    assert compact["id"] == "AC_DC__Highway_To_Hell"
    assert compact["song"]["artist"] == "AC/DC"
    assert compact["song"]["genre"] == "hard rock"
    # History keys are gone from the compact sheet.
    for key in ("musicDraft", "openaiJudge", "generated", "timings", "fretwiseExport"):
        assert key not in compact
    view = song_output_to_view(compact)
    assert view["is_gears"] is True
    assert view["artist"] == "AC/DC"
    assert view["song"] == "Highway to Hell"
    assert view["fiabilite"] == "A"  # confidence high -> A
    assert view["reglages"]["AMP"]["preset"] == "UK SLP"
