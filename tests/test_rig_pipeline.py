"""Tests for the grounded rig pipeline (facts -> override -> validate)."""
from __future__ import annotations

import json
from pathlib import Path

from fretwise.rig_generation import ProcessResult, SongRigGenerationService
from fretwise.rig_pipeline import (
    JsonFactsProvider,
    SongFacts,
    apply_facts_override,
    facts_key,
    generate_grounded_rig,
    in_palette,
    preset_of,
    validate_against_palette,
)

_RAW = {
    "schema_version": "codex_output_schema_v1",
    "artist": "Foo Fighters",
    "song": "Everlong",
    "genre": "Alternative Rock",
    "accordage": "E standard",          # wrong on purpose -> override must fix
    "capo": "non",
    "recommended_guitar": "Fender Stratocaster, micro chevalet",
    "signal_chain": "AMP -> CAB",
    "rig": {
        "nr": "Off", "pre": "Off", "dst": "Dist+ (MXR) · Drive 55",
        "amp": "UK 50 · Gain 65 · Bass 50", "cab": "UK Vintage 4x12", "eq": "Off",
        "mod": "Off", "dly": "Off", "rvb": "Off",
    },
    "reliability": "A",
    "comments": "x",
}

_FACTS = SongFacts(
    artist="Foo Fighters", title="Everlong", tuning="Drop D (DADGBE)", capo="non",
    guitar="Gibson Les Paul", amp="Mesa Dual Recto", dst="Rat", nr="Gate 1",
    mod="Off", dly="Off", rvb="Room", reliability="B",
)


def test_facts_key_normalizes_artist_and_title():
    assert facts_key("Foo Fighters", "Everlong") == facts_key("foo  fighters", "Everlong!")


def test_songfacts_json_round_trip():
    again = SongFacts.from_json(json.loads(json.dumps(_FACTS.to_json())))
    assert again == _FACTS


def test_preset_of_and_in_palette():
    assert preset_of("UK 50 · Gain 65") == "UK 50"
    assert in_palette("amp", "Mesa Dual Recto · Gain 70")
    assert not in_palette("amp", "Mesa Triple Rectifier")  # not on the device
    assert in_palette("dst", "Off")


def test_apply_facts_override_writes_hard_facts_and_keeps_params():
    out = apply_facts_override(_RAW, _FACTS)
    assert out["accordage"] == "Drop D (DADGBE)"
    assert out["recommended_guitar"].startswith("Gibson Les Paul")
    # amp preset forced, model's numeric params preserved
    assert out["rig"]["amp"].startswith("Mesa Dual Recto")
    assert "Gain 65" in out["rig"]["amp"]
    assert out["rig"]["dst"].startswith("Rat")
    assert out["rig"]["nr"] == "Gate 1"
    assert out["rig"]["rvb"] == "Room"
    assert out["reliability"] == "B"  # honest grade, not the model's inflated "A"


def test_validate_flags_out_of_palette():
    flags = validate_against_palette({"amp": "Mesa Triple Rectifier", "dst": "Off"},
                                     guitar="Gretsch White Falcon")
    assert any("amp" in f for f in flags)
    assert any("guitare" in f for f in flags)
    assert validate_against_palette({"amp": "UK 50 · Gain 60"}, guitar="Gibson SG") == []


def test_json_facts_provider_lookup_and_upsert(tmp_path: Path):
    db = tmp_path / "facts.json"
    provider = JsonFactsProvider(db)
    assert provider.get_facts("Foo Fighters", "Everlong") is None
    provider.upsert(_FACTS)
    reloaded = JsonFactsProvider(db)  # persisted to disk
    got = reloaded.get_facts("FOO fighters", "everlong")  # normalized lookup
    assert got is not None and got.tuning == "Drop D (DADGBE)"


def _fake_service() -> SongRigGenerationService:
    def runner(cmd: list[str], cwd: str, timeout: int) -> ProcessResult:  # noqa: ARG001
        return ProcessResult(0, json.dumps(_RAW), "")
    return SongRigGenerationService(runner=runner)


def test_generate_grounded_rig_applies_override_and_marks_grounded():
    res = generate_grounded_rig(_fake_service(), "Foo Fighters", "Everlong", facts=_FACTS)
    assert res.grounded is True
    assert res.reliability == "B"
    assert res.view["accordage"] == "Drop D (DADGBE)"
    assert res.view["reglages"]["AMP"]["preset"].startswith("Mesa Dual Recto")
    assert res.view["reglages"]["DST"]["preset"].startswith("Rat")


def test_generate_ungrounded_is_flagged_and_graded_down():
    res = generate_grounded_rig(_fake_service(), "Foo Fighters", "Everlong", facts=None)
    assert res.grounded is False
    assert res.reliability == "D"
    assert res.view["grounded"] is False
    # ungrounded keeps the model's (wrong) tuning -> that's why it's graded down
    assert res.view["accordage"] == "E standard"
