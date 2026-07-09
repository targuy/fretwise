"""Tests for the gear.v2 AI-verification prompt builder and validator."""

from __future__ import annotations

from fretwise.gears import build_gear_verification_prompt, validate_gear_v2
from fretwise.gears.verify import _catalog_block


def _valid_doc(**overrides) -> dict:
    doc = {
        "schemaVersion": "songsgear.fretwise.gear.v2",
        "song": {"artist": "AC/DC", "title": "Highway to Hell"},
        "rig": {
            "blocks": [
                {"module": "AMP", "model": "UK 50", "active": True, "matchQuality": "close"},
            ],
        },
    }
    doc.update(overrides)
    return doc


# --- validate_gear_v2 --------------------------------------------------------

def test_validate_gear_v2_accepts_minimal_valid_doc():
    result = validate_gear_v2(_valid_doc())
    assert result == {"ok": True, "errors": [], "warnings": []}


def test_validate_gear_v2_rejects_non_dict():
    result = validate_gear_v2(["not", "a", "dict"])
    assert result["ok"] is False
    assert result["errors"]


def test_validate_gear_v2_flags_wrong_schema_version():
    result = validate_gear_v2(_valid_doc(schemaVersion="songsgear.fretwise.rig.v1"))
    assert result["ok"] is False
    assert any("schemaVersion" in e for e in result["errors"])


def test_validate_gear_v2_flags_missing_song_fields():
    result = validate_gear_v2(_valid_doc(song={"artist": ""}))
    assert result["ok"] is False
    assert any("song.artist" in e for e in result["errors"])
    assert any("song.title" in e for e in result["errors"])


def test_validate_gear_v2_flags_missing_blocks():
    result = validate_gear_v2(_valid_doc(rig={"blocks": []}))
    assert result["ok"] is False
    assert any("rig.blocks" in e for e in result["errors"])


def test_validate_gear_v2_flags_unrecognized_module():
    doc = _valid_doc()
    doc["rig"]["blocks"][0]["module"] = "NOT_A_SLOT"
    result = validate_gear_v2(doc)
    assert result["ok"] is False
    assert any("NOT_A_SLOT" in e for e in result["errors"])


def test_validate_gear_v2_accepts_ascii_arrow_module_alias():
    doc = _valid_doc()
    doc["rig"]["blocks"][0]["module"] = "N->S"
    result = validate_gear_v2(doc)
    assert result["ok"] is True


def test_validate_gear_v2_warns_on_unusual_match_quality():
    doc = _valid_doc()
    doc["rig"]["blocks"][0]["matchQuality"] = "perfect-ish"
    result = validate_gear_v2(doc)
    assert result["ok"] is True
    assert any("matchQuality" in w for w in result["warnings"])


# --- build_gear_verification_prompt ------------------------------------------

def test_prompt_includes_song_identity_and_schema():
    prompt = build_gear_verification_prompt("AC/DC", "Highway to Hell")
    assert "AC/DC" in prompt
    assert "Highway to Hell" in prompt
    assert "songsgear.fretwise.gear.v2" in prompt
    assert "Valeton GP-180" in prompt


def test_prompt_lists_every_gp180_chain_slot():
    prompt = build_gear_verification_prompt("Metallica", "Enter Sandman")
    for slot in ("NR", "PRE", "WAH", "DST", "AMP", "CAB/IR", "EQ", "MOD", "DLY", "RVB", "VOL"):
        assert slot in prompt


def test_prompt_embeds_existing_sheet_for_review():
    existing = _valid_doc()
    prompt = build_gear_verification_prompt("AC/DC", "Highway to Hell", existing=existing)
    assert "Une fiche existe déjà" in prompt
    assert '"UK 50"' in prompt


def test_prompt_without_existing_sheet_has_no_review_section():
    prompt = build_gear_verification_prompt("AC/DC", "Highway to Hell")
    assert "Une fiche existe déjà" not in prompt


def test_catalog_block_groups_models_under_every_slot():
    block = _catalog_block()
    assert "**AMP**" in block
    assert "UK 50" in block  # a real GP-180 amp model shows up under its slot
