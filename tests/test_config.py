"""Tests for the centralized configuration loader (``fretwise.config``)."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest

from fretwise.config import (
    ConfigNode,
    config,
    get_config,
    reload_config,
)


@pytest.fixture(autouse=True)
def _clean_config_cache() -> Iterator[None]:
    """Ensure each test starts and ends with a fresh, default-only config."""
    reload_config()
    yield
    reload_config()


def test_get_config_returns_mapping_with_known_sections() -> None:
    cfg = get_config()
    assert isinstance(cfg, dict)
    for section in (
        "scoring",
        "generator",
        "biomechanics",
        "optimizer",
        "export",
        "notation",
        "layout",
        "web",
    ):
        assert section in cfg, f"missing section: {section}"


def test_get_config_is_cached() -> None:
    assert get_config() is get_config()


def test_scoring_weights_match_code_defaults() -> None:
    weights = get_config()["scoring"]["weights"]
    assert weights["reference"] == [1.0, 1.0, 0.0, 0.0]
    assert weights["performance"] == [1.0, 0.5, 2.0, 0.0]
    assert weights["musical"] == [1.0, 2.0, 1.0, 0.0]
    assert weights["learning"] == [1.0, 0.5, 1.0, 1.5]


def test_generator_and_biomechanics_max_fret_are_distinct() -> None:
    cfg = get_config()
    assert cfg["generator"]["max_fret"] == 22
    assert cfg["biomechanics"]["max_fret"] == 24
    assert cfg["generator"]["standard_tuning"] == [64, 59, 55, 50, 45, 40]


def test_export_written_octave_shift_matches_literal() -> None:
    assert get_config()["export"]["musicxml"]["written_octave_shift"] == 12


def test_optimizer_max_alternatives_matches_literal() -> None:
    assert get_config()["optimizer"]["max_alternatives"] == 3


def test_web_upload_caps_match_literals() -> None:
    web = get_config()["web"]
    assert web["max_score_upload_bytes"] == 50 * 1024 * 1024
    assert web["max_soundfont_upload_bytes"] == 512 * 1024 * 1024


def test_attribute_access_mirrors_mapping_access() -> None:
    cfg = config()
    assert isinstance(cfg, ConfigNode)
    assert cfg.scoring.weights.performance == [1.0, 0.5, 2.0, 0.0]
    assert cfg.generator.max_fret == 22
    assert cfg.export.musicxml.written_octave_shift == 12
    # Nested node is itself a ConfigNode supporting both styles.
    assert isinstance(cfg.scoring, ConfigNode)
    assert cfg.scoring["weights"]["performance"] == cfg.scoring.weights.performance


def test_missing_keys_behave_sanely() -> None:
    cfg = config()
    with pytest.raises(AttributeError):
        _ = cfg.does_not_exist
    with pytest.raises(KeyError):
        _ = cfg["does_not_exist"]
    assert cfg.get("does_not_exist") is None
    assert cfg.get("does_not_exist", 42) == 42
    assert "scoring" in cfg
    assert "does_not_exist" not in cfg


def test_node_helpers() -> None:
    cfg = config()
    scoring = cfg.scoring
    assert "weights" in scoring
    assert len(scoring) == len(get_config()["scoring"])
    assert set(iter(scoring)) == set(get_config()["scoring"].keys())
    assert scoring.to_dict() == get_config()["scoring"]


def test_env_override_deep_merges_over_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    override = tmp_path / "override.yaml"
    override.write_text(
        "generator:\n"
        "  max_fret: 99\n"
        "scoring:\n"
        "  weights:\n"
        "    performance: [9.0, 9.0, 9.0, 9.0]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("FRETWISE_CONFIG", str(override))
    reload_config()

    cfg = get_config()
    # Overridden values win.
    assert cfg["generator"]["max_fret"] == 99
    assert cfg["scoring"]["weights"]["performance"] == [9.0, 9.0, 9.0, 9.0]
    # Sibling keys not mentioned in the override are preserved from defaults.
    assert cfg["generator"]["standard_tuning"] == [64, 59, 55, 50, 45, 40]
    assert cfg["scoring"]["weights"]["reference"] == [1.0, 1.0, 0.0, 0.0]


def test_missing_override_file_falls_back_to_defaults(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("FRETWISE_CONFIG", str(tmp_path / "nope.yaml"))
    reload_config()
    assert get_config()["generator"]["max_fret"] == 22


def test_reload_config_picks_up_env_change(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert get_config()["generator"]["max_fret"] == 22
    override = tmp_path / "o.yaml"
    override.write_text("generator:\n  max_fret: 7\n", encoding="utf-8")
    monkeypatch.setenv("FRETWISE_CONFIG", str(override))
    # Stale cache still returns the old value until reloaded.
    assert get_config()["generator"]["max_fret"] == 22
    reload_config()
    assert get_config()["generator"]["max_fret"] == 7
