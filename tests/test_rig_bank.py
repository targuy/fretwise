"""Tests for structured Valeton GP-180 rig banks and MIDI activation data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fretwise.rig_bank import (
    RigBank,
    RigBankError,
    RigBinding,
    RigProfile,
    load_rig_bank,
    read_valeton_suite_effect_catalog,
    save_rig_bank,
)
from tools.seed_gp180_rig_bank import build_bank


def test_load_missing_rig_bank_returns_empty(tmp_path: Path) -> None:
    bank = load_rig_bank(tmp_path / "rig_bank.json")

    assert bank.profiles == ()
    assert bank.bindings == ()


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
            ),
        ),
        bindings=(RigBinding(scope="song", key="Right Now", profile_id="vh-right-now"),),
    )

    save_rig_bank(path, bank)
    loaded = load_rig_bank(path)

    assert loaded == bank
    assert json.loads(path.read_text(encoding="utf-8"))["schema_version"]


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

    assert len(bank.profiles) == 104
    assert len(bank.bindings) == 40
    assert all(profile.genre for profile in bank.profiles)
    assert bank.get_profile("gp180-046-back-in-dc").artist == "AC/DC"
    assert bank.resolve(song="Comfortably Numb").profile.id == "gp180-048-numb-of-pf"
    assert bank.resolve(artist="Dire Straits").profile.id == "gp180-053-straits-clean"
