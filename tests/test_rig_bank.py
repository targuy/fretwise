"""Tests for structured Valeton GP-180 rig banks and MIDI activation data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fretwise.rig_bank import (
    RigBank,
    RigBankError,
    RigBinding,
    RigModule,
    RigProfile,
    _match_model,
    load_rig_bank,
    read_valeton_suite_effect_catalog,
    save_rig_bank,
)
from tools.seed_gp180_rig_bank import _apply_captured_modules, build_bank


def test_load_missing_rig_bank_returns_empty(tmp_path: Path) -> None:
    bank = load_rig_bank(tmp_path / "rig_bank.json")

    assert bank.profiles == ()
    assert bank.bindings == ()


def test_gp180_seed_preserves_first_five_captured_module_chains(tmp_path: Path) -> None:
    path = tmp_path / "rig_bank.json"
    save_rig_bank(path, build_bank())

    _apply_captured_modules(path)
    bank = load_rig_bank(path)

    expected = {
        0: (("NR", "Gate 3", True), ("WAH", "V-Wah", False), ("DST", "Green OD", True),
            ("AMP", "Flagman 1", True), ("CAB/IR", "Flagman 4x12", True),
            ("DLY", "Pure", True), ("RVB", "Hall", True), ("VOL", "Volume", True)),
        1: (("PRE", "COMP", True), ("AMP", "Dark Twin", True),
            ("CAB/IR", "Twin 2x12", True), ("RVB", "Spring", True), ("VOL", "Volume", True)),
        2: (("NR", "Gate 3", True), ("AMP", "Tweedy", True),
            ("CAB/IR", "TWD LUX 1x12", True), ("RVB", "Spring", True), ("VOL", "Volume", True)),
        3: (("AMP", "Foxy 30N", True), ("CAB/IR", "Foxy 2x12", True),
            ("RVB", "Spring", True), ("VOL", "Volume", True)),
        4: (("NR", "Gate 3", True), ("AMP", "Foxy 30TB", True),
            ("CAB/IR", "Foxy 1x12", True), ("RVB", "Spring", True), ("VOL", "Volume", True)),
    }
    for profile in bank.profiles[:5]:
        actual = tuple((module.module, module.model, module.active) for module in profile.modules)
        assert actual == expected[profile.program]

    assert tuple((m.module, m.model) for m in bank.profiles[5].modules) == (
        ("NR", "Gate 3"),
        ("AMP", "UK 900"),
        ("CAB/IR", "UK 30 4x12"),
        ("RVB", "Spring"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[9].modules) == (
        ("NR", "Gate 3"),
        ("AMP", "EV 51"),
        ("CAB/IR", "Mess 4x12"),
        ("RVB", "Plate"),
        ("VOL", "Volume"),
    )
    assert all(profile.modules for profile in bank.profiles[:100])
    assert tuple((m.module, m.model) for m in bank.profiles[10].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Green OD"),
        ("AMP", "EV 51"),
        ("CAB/IR", "UK 30 4x12"),
        ("DLY", "Dual Echo"),
        ("RVB", "Church"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[19].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Green OD"),
        ("AMP", "Bellman 59B"),
        ("CAB/IR", "TWD LUX 1x12"),
        ("MOD", "G-Chorus"),
        ("RVB", "Plate"),
        ("VOL", "Volume"),
    )
    assert not bank.profiles[18].modules[5].active
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[20].modules) == (
        ("NR", "Gate 3", True),
        ("WAH", "V-Wah", False),
        ("DST", "Red Haze", True),
        ("AMP", "UK 45+", True),
        ("CAB/IR", "UK 30 4x12", True),
        ("EQ", "Guitar EQ 1", True),
        ("MOD", "V-Roto", False),
        ("RVB", "Plate", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[24].modules) == (
        ("PRE", "COMP", True),
        ("MOD", "O-Phase", False),
        ("AMP", "Dark Twin", True),
        ("CAB/IR", "Twin 2x12", True),
        ("EQ", "Guitar EQ 1", False),
        ("DLY", "Pure", False),
        ("RVB", "Plate", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[29].modules) == (
        ("NR", "Gate 3"),
        ("PRE", "OD 9"),
        ("DST", "Tube Clipper"),
        ("AMP", "UK 50+"),
        ("CAB/IR", "Bog 2x12"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[30].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Scream OD"),
        ("AMP", "Mess 2C+ 3"),
        ("CAB/IR", "Mess 4x12"),
        ("DLY", "BBD Delay S"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[34].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Darktale"),
        ("AMP", "Dark Twin"),
        ("CAB/IR", "Bellman 4x10"),
        ("MOD", "C-Chorus"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[39].modules) == (
        ("PRE", "COMP4", True),
        ("AMP", "Dark Twin", True),
        ("CAB/IR", "Twin 2x12", True),
        ("EQ", "Guitar EQ 1", False),
        ("DLY", "Pure", True),
        ("RVB", "Tube Spring", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[40].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Scream OD"),
        ("AMP", "Foxy 30TB"),
        ("CAB/IR", "UK 30 4x12"),
        ("RVB", "N-Star"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[41].modules) == (
        ("NR", "Gate 3", True),
        ("PRE", "COMP", True),
        ("AMP", "Dark Twin", True),
        ("CAB/IR", "Twin 2x12", False),
        ("MOD", "C-Chorus", True),
        ("DLY", "Pure", True),
        ("RVB", "Hall", True),
        ("VOL", "Volume", True),
    )
    assert not bank.profiles[46].modules[5].active
    assert tuple((m.module, m.model) for m in bank.profiles[49].modules) == (
        ("NR", "Gate 3"),
        ("MOD", "O-Phase"),
        ("PRE", "Boost"),
        ("AMP", "EV 51"),
        ("CAB/IR", "Mess 4x12"),
        ("DLY", "Pure"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[50].modules) == (
        ("NR", "Gate 3", True),
        ("PRE", "Boost", True),
        ("DST", "Yellow OD", False),
        ("AMP", "EV 51", True),
        ("CAB/IR", "Mess 4x12", True),
        ("EQ", "Guitar EQ 1", False),
        ("MOD", "Jet", True),
        ("DLY", "Pure", True),
        ("RVB", "Hall", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[54].modules) == (
        ("NR", "Gate 3"),
        ("DST", "OD 9"),
        ("AMP", "Mess DualM"),
        ("CAB/IR", "Mess 4x12"),
        ("EQ", "Guitar EQ 2"),
        ("RVB", "Plate"),
        ("VOL", "Volume"),
    )
    assert not bank.profiles[56].modules[5].active
    assert tuple((m.module, m.model) for m in bank.profiles[59].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Darktale"),
        ("AMP", "Dark Twin"),
        ("CAB/IR", "Twin 2x12"),
        ("MOD", "C-Chorus"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[60].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Green OD"),
        ("AMP", "Foxy 30TB"),
        ("CAB/IR", "Foxy 1x12"),
        ("DLY", "Pure"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[66].modules) == (
        ("NR", "Gate 3"),
        ("AMP", "Flagman 1"),
        ("CAB/IR", "Flagman 4x12"),
        ("PRE", "Pitch"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[68].modules) == (
        ("NR", "Gate 3", True),
        ("WAH", "V-Wah", True),
        ("DST", "Green OD", True),
        ("AMP", "Mess2C+ 2", True),
        ("CAB/IR", "Mess 4x12", True),
        ("EQ", "Guitar EQ 1", False),
        ("MOD", "G-Chorus", False),
        ("DLY", "Pure", True),
        ("RVB", "Plate", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[69].modules) == (
        ("NR", "Gate 3"),
        ("PRE", "COMP4"),
        ("AMP", "Bog BlueV"),
        ("CAB/IR", "Bog 2x12"),
        ("MOD", "Auto Swell"),
        ("DLY", "Sweet Echo"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[70].modules) == (
        ("NR", "Gate 3"),
        ("PRE", "Step Filter"),
        ("AMP", "Silver Twin"),
        ("CAB/IR", "REV 2x12"),
        ("DLY", "Digital Delay S"),
        ("RVB", "Sweet Space"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[75].modules) == (
        ("NR", "Gate 3", True),
        ("AMP", "EV 51", True),
        ("CAB/IR", "Mess 4x12", True),
        ("MOD", "Freeze", False),
        ("DLY", "Pure", True),
        ("RVB", "Hall", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[78].modules) == (
        ("NR", "Gate 3"),
        ("DST", "Tube Clipper"),
        ("AMP", "Mess2C+ 1"),
        ("PRE", "OCTA"),
        ("CAB/IR", "Mess 4x12"),
        ("MOD", "Detune"),
        ("RVB", "Concert"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[79].modules) == (
        ("PRE", "Boost", True),
        ("AMP", "Z38 CL", True),
        ("CAB/IR", "Foxy 2x12", True),
        ("MOD", "C-Chorus", False),
        ("RVB", "Shimmer", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[80].modules) == (
        ("NR", "Gate 3"),
        ("PRE", "S to H"),
        ("DST", "OD 9"),
        ("AMP", "UK 800"),
        ("CAB/IR", "UK 30 4x12"),
        ("DLY", "BBD Delay S"),
        ("RVB", "Hall"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[84].modules) == (
        ("NR", "Gate 3", True),
        ("PRE", "COMP4", False),
        ("DST", "Red Haze", True),
        ("AMP", "Silver Twin", True),
        ("CAB/IR", "TWD LUX 1x12", False),
        ("EQ", "Guitar EQ 2", True),
        ("MOD", "O-Phase", False),
        ("RVB", "Room", True),
        ("VOL", "Volume", True),
    )
    assert not bank.profiles[85].modules[5].active
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[89].modules) == (
        ("NR", "Gate 1", True),
        ("PRE", "Micro Boost", True),
        ("WAH", "B-Wah", False),
        ("DST", "Bass Hammer", True),
        ("CAB/IR", "AMPG 8x10", True),
        ("EQ", "Bass EQ 1", True),
        ("MOD", "B-Jet", False),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model) for m in bank.profiles[90].modules) == (
        ("NR", "Gate 3"),
        ("PRE", "COMP4"),
        ("DST", "Black Bass"),
        ("AMP", "Mess Bass"),
        ("CAB/IR", "Mess BS 2x10"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[94].modules) == (
        ("NR", "Gate 1", True),
        ("PRE", "COMP4", True),
        ("WAH", "B-Wah", False),
        ("DST", "Lazaro", True),
        ("AMP", "Bass Pre", True),
        ("CAB/IR", "AMPG 8x10", True),
        ("EQ", "Bass EQ 1", True),
        ("MOD", "Detune", True),
        ("RVB", "Room", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[95].modules) == (
        ("NR", "Gate 3", False),
        ("AMP", "AC Pre", True),
        ("CAB/IR", "AC", False),
        ("EQ", "Guitar EQ 2", True),
        ("RVB", "Hall", True),
        ("VOL", "Volume", True),
    )
    assert tuple((m.module, m.model, m.active) for m in bank.profiles[99].modules) == (
        ("NR", "Gate 3", True),
        ("AMP", "AC Pre", True),
        ("CAB/IR", "AC", False),
        ("EQ", "Guitar EQ 2", True),
        ("RVB", "Hall", True),
        ("PRE", "COMP4", True),
        ("VOL", "Volume", True),
    )
    by_program = {profile.program: profile for profile in bank.profiles}
    assert tuple((m.module, m.model) for m in by_program[100].modules) == (
        ("NR", "Gate 1"),
        ("PRE", "OD 9"),
        ("AMP", "UK 45"),
        ("CAB/IR", "UK Vintage 4x12"),
        ("RVB", "Room"),
        ("VOL", "Volume"),
    )
    assert by_program[101].modules == ()
    assert tuple((m.module, m.model) for m in by_program[102].modules) == (
        ("AMP", "Dark Twin"),
        ("CAB/IR", "Twin 2x12"),
        ("DLY", "Tape"),
        ("RVB", "Plate"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model) for m in by_program[103].modules) == (
        ("NR", "Gate 1"),
        ("AMP", "UK 45JP"),
        ("CAB/IR", "UK 2x12"),
        ("EQ", "Guitar EQ 1"),
        ("DLY", "Tape"),
        ("RVB", "Plate"),
        ("VOL", "Volume"),
    )
    assert tuple((m.module, m.model, m.active) for m in by_program[109].modules) == (
        ("NR", "Gate 1", True),
        ("PRE", "Boost", True),
        ("DST", "Micro Boost", False),
        ("AMP", "Dizz VH", True),
        ("CAB/IR", "Dizz 4x12", True),
        ("EQ", "Guitar EQ 1", True),
        ("MOD", "Freeze", False),
        ("DLY", "Digital Delay S", True),
        ("RVB", "Plate", False),
        ("VOL", "Volume", True),
    )


def test_rig_bank_save_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "rigs" / "rig_bank.json"
    bank = RigBank(
        profiles=(
            RigProfile(
                id="vh-right-now",
                name="Right Now Lead",
                program=142,
                artist="Van Halen",
                genre="arena rock",
                tags=("lead", "wet"),
                modules=(
                    RigModule(module="AMP", model="US Deluxe"),
                    RigModule(module="RVB", model="Room"),
                ),
            ),
        ),
        bindings=(RigBinding(scope="song", key="Right Now", profile_id="vh-right-now"),),
    )

    save_rig_bank(path, bank)
    loaded = load_rig_bank(path)

    assert loaded == bank
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"]
    assert loaded.profiles[0].modules[0].model == "US Deluxe"


def test_rig_profile_modules_validate_slots_and_active_models() -> None:
    assert RigModule(module="cab", model="US 2x12").module == "CAB/IR"
    assert RigModule(module="N->S", model="Pitch").module == "N→S"

    with pytest.raises(RigBankError, match="unsupported GP-180 module"):
        RigModule(module="UNKNOWN", model="Thing")
    with pytest.raises(RigBankError, match="requires a model"):
        RigModule(module="RVB", model="")


def test_rig_bank_resolution_priority_song_artist_genre_metadata() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(id="genre-rock", name="Rock Rhythm", program=12, genre="rock"),
            RigProfile(id="artist-vh", name="Van Halen Brown", program=42, artist="Van Halen"),
            RigProfile(id="song-jump", name="Jump Synth Guitar", program=90),
            RigProfile(id="song-panama", name="Panama", program=91),
        ),
        bindings=(
            RigBinding(scope="genre", key="rock", profile_id="genre-rock"),
            RigBinding(scope="artist", key="Van Halen", profile_id="artist-vh"),
            RigBinding(scope="song", key="Jump", profile_id="song-jump"),
        ),
    )

    assert bank.resolve(profile_id="song-panama").profile.id == "song-panama"
    assert bank.resolve(song="Jump", artist="Van Halen", genre="rock").profile.id == "song-jump"
    assert (
        bank.resolve(song="Unchained", artist="Van Halen", genre="rock").profile.id
        == "artist-vh"
    )
    assert bank.resolve(song="Other", artist="Other", genre="rock").profile.id == "genre-rock"


def test_rig_bank_resolution_falls_back_to_profile_metadata() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(id="artist-meta", name="Artist Meta", program=7, artist="The Cure"),
            RigProfile(id="genre-meta", name="Genre Meta", program=8, genre="post punk"),
        ),
    )

    assert bank.resolve(artist="the cure").profile.id == "artist-meta"
    assert bank.resolve(genre="Post Punk").profile.id == "genre-meta"


def test_rig_bank_recommendation_explains_exact_binding() -> None:
    bank = RigBank(
        profiles=(RigProfile(id="pf", name="Numb of PF", program=47),),
        bindings=(RigBinding(scope="song", key="Comfortably Numb", profile_id="pf"),),
    )

    recommendation = bank.recommend(song="Comfortably Numb", artist="Pink Floyd")

    assert recommendation.profile.id == "pf"
    assert recommendation.source == "song_binding"
    assert recommendation.score == 100
    assert "chanson" in recommendation.reasons[0]


def test_rig_bank_recommendation_uses_subgenre_and_tags() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(id="jazz-clean", name="JAZZ Clean", program=25, genre="jazz"),
            RigProfile(
                id="post-rock",
                name="POST ROCK",
                program=40,
                genre="post-rock",
                tags=("ambient",),
            ),
        ),
    )

    recommendation = bank.recommend(
        song="Long Crescendo",
        artist="Unknown",
        genre="ambient post-rock",
    )

    assert recommendation.profile.id == "post-rock"
    assert recommendation.source == "genre_match"
    assert recommendation.score > 0
    assert recommendation.reasons


def test_rig_bank_recommendation_prefers_most_positive_active_module_matches() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(
                id="artist-default",
                name="Artist Default",
                program=10,
                artist="Example Band",
                modules=(RigModule(module="AMP", model="UK 50"),),
            ),
            RigProfile(
                id="closest-chain",
                name="Closest Chain",
                program=11,
                genre="rock",
                modules=(
                    RigModule(module="AMP", model="UK 50"),
                    RigModule(module="DLY", model="Tape"),
                ),
            ),
        ),
    )

    recommendation = bank.recommend(
        artist="Example Band",
        genre="rock",
        target_modules=(
            RigModule(module="AMP", model="uk-50"),
            RigModule(module="DLY", model="tape"),
            RigModule(module="RVB", model="Room"),
        ),
    )

    assert recommendation is not None
    assert recommendation.profile.id == "closest-chain"
    assert recommendation.source == "module_match"
    assert recommendation.positive_matches == 1
    assert recommendation.to_json()["module_match"]["coverage"] == 0.5
    assert recommendation.to_json()["module_match"]["amp_match_module"] == "AMP"


def test_rig_bank_recommendation_module_matching_falls_back_when_no_positive_match() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(id="hard", name="Hard", program=1, genre="hard rock"),
            RigProfile(
                id="jazz",
                name="Jazz",
                program=2,
                genre="jazz",
                modules=(RigModule(module="AMP", model="Jazz AMP"),),
            ),
        ),
    )

    recommendation = bank.recommend(
        genre="hard rock",
        target_modules=(RigModule(module="AMP", model="UK 50"),),
    )

    assert recommendation is not None
    assert recommendation.profile.id == "hard"
    assert recommendation.source == "profile_genre"
    assert "Rapprochement par style et nom" in recommendation.reasons[0]


def test_rig_bank_recommendation_requires_amp_gate_before_secondary_modules() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(
                id="wrong-amp-wet",
                name="Wrong Amp Wet",
                program=1,
                genre="rock",
                modules=(
                    RigModule(module="AMP", model="US Twin"),
                    RigModule(module="CAB/IR", model="UK 4x12"),
                    RigModule(module="DLY", model="Tape"),
                    RigModule(module="RVB", model="Hall"),
                ),
            ),
            RigProfile(
                id="right-amp-dry",
                name="Right Amp Dry",
                program=2,
                genre="rock",
                modules=(
                    RigModule(module="AMP", model="UK 50"),
                    RigModule(module="DLY", model="Tape"),
                ),
            ),
        )
    )

    recommendation = bank.recommend(
        genre="rock",
        target_modules=(
            RigModule(module="AMP", model="UK 50"),
            RigModule(module="CAB/IR", model="UK 4x12"),
            RigModule(module="DLY", model="Tape"),
            RigModule(module="RVB", model="Hall"),
        ),
    )

    assert recommendation is not None
    assert recommendation.profile.id == "right-amp-dry"
    assert recommendation.positive_matches == 1


def test_rig_bank_recommendation_accepts_ns_as_amp_gate() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(
                id="ns-amp",
                name="N-S Amp",
                program=1,
                modules=(
                    RigModule(module="N→S", model="UK 50"),
                    RigModule(module="DLY", model="Tape"),
                ),
            ),
        )
    )

    recommendation = bank.recommend(
        target_modules=(
            RigModule(module="AMP", model="UK 50"),
            RigModule(module="DLY", model="Tape"),
        )
    )

    assert recommendation is not None
    assert recommendation.source == "module_match"
    assert recommendation.to_json()["module_match"]["amp_match_module"] == "N→S"


def test_rig_bank_recommendation_ignores_nr_eq_and_vol_in_module_score() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(
                id="utility-only",
                name="Utility Only",
                program=1,
                modules=(
                    RigModule(module="AMP", model="UK 50"),
                    RigModule(module="NR", model="Gate 3"),
                    RigModule(module="EQ", model="Guitar EQ 1"),
                    RigModule(module="VOL", model="Volume"),
                ),
            ),
            RigProfile(
                id="tone-match",
                name="Tone Match",
                program=2,
                modules=(
                    RigModule(module="AMP", model="UK 50"),
                    RigModule(module="RVB", model="Hall"),
                ),
            ),
        )
    )

    recommendation = bank.recommend(
        target_modules=(
            RigModule(module="AMP", model="UK 50"),
            RigModule(module="NR", model="Gate 3"),
            RigModule(module="EQ", model="Guitar EQ 1"),
            RigModule(module="VOL", model="Volume"),
            RigModule(module="RVB", model="Hall"),
        )
    )

    assert recommendation is not None
    assert recommendation.profile.id == "tone-match"
    assert recommendation.positive_matches == 1
    assert recommendation.to_json()["module_match"]["active_target_count"] == 1


def test_rig_bank_recommendation_without_target_amp_falls_back_by_style_and_name() -> None:
    bank = RigBank(
        profiles=(RigProfile(id="ambient", name="Ambient Clean", program=1, genre="ambient"),)
    )

    recommendation = bank.recommend(
        genre="ambient",
        target_modules=(RigModule(module="DLY", model="Tape"),),
    )

    assert recommendation is not None
    assert recommendation.source == "profile_genre"
    assert recommendation.reasons[0] == (
        "Rapprochement par style et nom : rig conseillé sans ampli AMP/N→S actif."
    )


@pytest.mark.parametrize(
    ("module", "valeton_name", "reference_name"),
    (
        ("AMP", "Foxy 30TB", "Vox AC30 Top Boost"),
        ("AMP", "Foxy 30TB", "Vox AC30"),
        ("AMP", "EV 51", "EVH 5150"),
        ("AMP", "UK 800", "Marshall JCM800"),
        ("AMP", "Mess DualM", "Mesa Dual Rectifier"),
        ("CAB/IR", "UK 30 4x12", "Marshall V30 4x12"),
        ("DST", "Green OD", "Ibanez Tube Screamer"),
        ("MOD", "C-Chorus", "Chorus"),
        ("DLY", "BBD Delay S", "Bucket Brigade Delay"),
        ("RVB", "Plate", "Plate Reverb"),
    ),
)
def test_gp180_model_match_resolves_slot_specific_clone_aliases(
    module: str, valeton_name: str, reference_name: str
) -> None:
    match = _match_model(module, valeton_name, reference_name)

    assert match.matched is True
    assert match.method == "alias"


@pytest.mark.parametrize(
    ("module", "left", "right"),
    (
        ("AMP", "Foxy 30N", "Vox AC30 Top Boost"),
        ("AMP", "UK 800", "Marshall JCM900"),
        ("AMP", "Mess 2C+ 1", "Mesa Dual Rectifier"),
        ("AMP", "EVH 5150", "Peavey 6505"),
        ("CAB/IR", "Foxy 1x12", "Vox 2x12"),
        ("CAB/IR", "UK 30 4x12", "Mesa 4x12"),
        ("PRE", "COMP4", "Compressor"),
        ("MOD", "C-Chorus", "Bass Chorus"),
        ("RVB", "Tube Spring", "Spring"),
    ),
)
def test_gp180_model_match_rejects_nearby_but_distinct_models(
    module: str, left: str, right: str
) -> None:
    assert _match_model(module, left, right).matched is False


def test_gp180_model_match_accepts_typo_not_model_change() -> None:
    typo = _match_model("AMP", "Marshal JCM800", "Marshall JCM800")

    assert typo.matched is True
    assert typo.method == "typo"
    assert _match_model("AMP", "Marshall JCM800", "Marshall JCM900").matched is False


def test_rig_bank_recommendation_uses_aliases_after_amp_gate() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(
                id="wrong-amp",
                name="Wrong but wet",
                program=1,
                modules=(
                    RigModule(module="AMP", model="UK 800"),
                    RigModule(module="CAB/IR", model="UK 30 4x12"),
                    RigModule(module="DLY", model="BBD Delay S"),
                ),
            ),
            RigProfile(
                id="ac30-chain",
                name="AC30 chain",
                program=2,
                modules=(
                    RigModule(module="AMP", model="Foxy 30TB"),
                    RigModule(module="CAB/IR", model="UK 30 4x12"),
                    RigModule(module="DLY", model="BBD Delay S"),
                ),
            ),
        )
    )

    recommendation = bank.recommend(
        target_modules=(
            RigModule(module="AMP", model="Vox AC30 Top Boost"),
            RigModule(module="CAB/IR", model="Marshall V30 4x12"),
            RigModule(module="DLY", model="Bucket Brigade Delay"),
        )
    )

    assert recommendation is not None
    assert recommendation.profile.id == "ac30-chain"
    assert recommendation.positive_matches == 2
    assert recommendation.amp_match_method == "alias"
    assert "[alias]" in recommendation.reasons[0]
    assert recommendation.to_json()["module_match"]["matched_module_methods"] == [
        "CAB/IR=alias",
        "DLY=alias",
    ]


def test_rig_profile_from_json_infers_missing_genre_for_settings() -> None:
    profile = RigProfile.from_json(
        {
            "id": "gp180-055-metal-of-lica",
            "name": "055 Metal of Lica",
            "program": 54,
            "tags": ["factory", "metallica"],
        }
    )

    assert profile.genre == "thrash metal"
    assert profile.to_json()["genre"] == "thrash metal"


def test_rig_bank_recommendation_uses_nearest_profile_genre() -> None:
    bank = RigBank(
        profiles=(
            RigProfile(id="hard", name="UK900 DIST", program=5, genre="hard rock"),
            RigProfile(id="jazz", name="JAZZ Clean", program=25, genre="jazz"),
        ),
    )

    recommendation = bank.recommend(genre="classic hard rock")

    assert recommendation.profile.id == "hard"
    assert recommendation.source == "genre_match"
    assert recommendation.matched_key == "hard rock"
    assert any("Genre approchant" in reason for reason in recommendation.reasons)


def test_rig_bank_rejects_missing_binding_target() -> None:
    with pytest.raises(RigBankError, match="unknown profile"):
        RigBank(bindings=(RigBinding(scope="song", key="A", profile_id="missing"),))


def test_gp180_midi_bytes_for_first_and_last_user_presets() -> None:
    assert RigProfile(id="factory", name="Factory 000", program=0).midi_bytes() == (
        (0xB0, 0, 0),
        (0xC0, 0),
    )
    assert RigProfile(id="user-100", name="User 100", program=100).midi_bytes() == (
        (0xB0, 0, 0),
        (0xC0, 100),
    )
    assert RigProfile(id="user-199", name="User 199", program=199).midi_bytes() == (
        (0xB0, 0, 1),
        (0xC0, 71),
    )


def test_gp180_midi_bytes_respect_channel_and_explicit_bank() -> None:
    profile = RigProfile(
        id="banked",
        name="Banked",
        program=130,
        midi_channel=3,
        bank_msb=2,
        bank_lsb=5,
    )

    assert profile.midi_bytes() == ((0xB2, 0, 2), (0xB2, 32, 5), (0xC2, 2))


def test_valeton_suite_effect_catalog_reads_module_tables(tmp_path: Path) -> None:
    table = {
        "modules": [
            {
                "name": "AMP",
                "module": [
                    {"fxtitle": "UK 50"},
                    {"name": "US Deluxe"},
                    {"fxtitle": "UK 50"},
                ],
            },
            {"name": "DST", "module": [{"fxtitle": "T Screamer"}]},
        ],
    }
    path = tmp_path / "module_data.json"
    path.write_text(json.dumps(table), encoding="utf-8")

    assert read_valeton_suite_effect_catalog([path]) == {
        "AMP": ["UK 50", "US Deluxe"],
        "DST": ["T Screamer"],
    }


def test_seed_gp180_bank_contains_captured_presets_and_valid_bindings() -> None:
    bank = build_bank()

    assert len(bank.profiles) == 105
    assert len(bank.bindings) == 40
    assert all(profile.genre for profile in bank.profiles)
    assert bank.get_profile("gp180-046-back-in-dc").artist == "AC/DC"
    assert bank.get_profile("gp180-110-muse").artist == "Muse"
    assert bank.resolve(song="Comfortably Numb").profile.id == "gp180-048-numb-of-pf"
    assert bank.resolve(artist="Dire Straits").profile.id == "gp180-053-straits-clean"
