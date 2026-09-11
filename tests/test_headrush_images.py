"""Tests for the block pictures: path rule, validation, and the failure-aware cache."""

from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.devices.headrush_core.client import DeviceNotFoundError, DeviceUnreachableError
from fretwise.devices.headrush_core.images import (
    ImageCache,
    all_image_relpaths,
    cache_name,
    image_relpath,
    image_url_path,
    image_variant,
)
from fretwise.web.device_routes import _load_headrush_catalog, catalog_is_available

pytestmark = pytest.mark.skipif(
    not catalog_is_available(),
    reason="no HeadRush catalog artifact — run scripts/device_catalog_dump.py",
)

WEBP = b"RIFF\x10\x00\x00\x00WEBPVP8 fake-picture"


@pytest.fixture(scope="module")
def catalog():
    return _load_headrush_catalog()


# --- the path rule, from the Remote Editor's bundle ----------------------------


def test_amp_picture_follows_the_amp_model(catalog):
    assert image_relpath(catalog, "Amp", "82 Lead 800 100W") == "Amp/82 Lead 800 100W"


def test_cab_picture_follows_the_cab_type(catalog):
    assert image_relpath(catalog, "Cab", "4x12 Green 25W") == "Cab/4x12 Green 25W"


def test_other_blocks_use_their_own_name(catalog):
    assert image_relpath(catalog, "Pressor") == "Pressor"


def test_a_second_instance_uses_the_first_ones_picture(catalog):
    assert image_relpath(catalog, "Amp 2") == "Amp"


def test_an_amp_without_a_model_falls_back_to_the_generic_picture(catalog):
    assert image_relpath(catalog, "Amp") == "Amp"


def test_variant_comes_from_the_model_parameters():
    assert image_variant("Amp", {"Type": "69 Plexiglas 100W"}) == "69 Plexiglas 100W"
    assert image_variant("Cab 2", {"CabType": "4x12 65W"}) == "4x12 65W"
    assert image_variant("Pressor", {"Gain": 52}) == ""


# --- nothing but catalog names can reach the device URL ------------------------


@pytest.mark.parametrize("module", ["Klone", "../../api/v1/subtree/Evil", "", "Amp/../x"])
def test_unknown_blocks_are_refused(catalog, module):
    with pytest.raises(ValueError):
        image_relpath(catalog, module)


def test_an_invented_amp_model_is_refused(catalog):
    with pytest.raises(ValueError):
        image_relpath(catalog, "Amp", "../../secret")


def test_url_path_is_percent_encoded_segment_by_segment():
    assert image_url_path("Amp/69 Plexiglas 100W") == (
        "/files/Evil/Web/Blocks/img/Amp/69%20Plexiglas%20100W.webp"
    )


def test_cache_names_are_safe_and_distinct():
    a, b = cache_name("Cab/4x12 65W"), cache_name("Cab/4x12_65W")
    assert a != b
    assert "/" not in a and " " not in a and a.endswith(".webp")


def test_every_picture_is_listed_once(catalog):
    relpaths = all_image_relpaths(catalog)
    assert len(relpaths) == len(set(relpaths))
    assert "Pressor" in relpaths and "Amp/82 Lead 800 100W" in relpaths
    assert "Empty Slot" not in relpaths
    assert not any(r.endswith(" 2") for r in relpaths)


# --- the cache ------------------------------------------------------------------


def test_cache_downloads_once_then_serves_from_disk(tmp_path: Path):
    cache = ImageCache(tmp_path)
    calls: list[str] = []

    def fetch(url_path: str) -> bytes:
        calls.append(url_path)
        return WEBP

    first = cache.fetch("Pressor", fetch)
    second = cache.fetch("Pressor", fetch)
    assert first == second and first is not None and first.read_bytes() == WEBP
    assert calls == ["/files/Evil/Web/Blocks/img/Pressor.webp"]


def test_cache_refuses_what_is_not_a_webp(tmp_path: Path):
    cache = ImageCache(tmp_path)
    assert cache.fetch("Pressor", lambda _p: b"<html>not found</html>") is None
    assert not any(tmp_path.iterdir())


def test_a_missing_picture_is_not_asked_again(tmp_path: Path):
    cache = ImageCache(tmp_path)
    calls: list[str] = []

    def fetch(url_path: str) -> bytes:
        calls.append(url_path)
        raise DeviceNotFoundError("404")

    assert cache.fetch("Pressor", fetch) is None
    assert cache.fetch("Pressor", fetch) is None
    assert len(calls) == 1
    assert cache.offline is False


def test_an_unreachable_device_is_not_retried_until_the_delay_passes(tmp_path: Path):
    now = [100.0]
    cache = ImageCache(tmp_path, retry_after_s=60.0, clock=lambda: now[0])
    calls: list[str] = []

    def fetch(url_path: str) -> bytes:
        calls.append(url_path)
        raise DeviceUnreachableError("off")

    assert cache.fetch("Pressor", fetch) is None
    assert cache.fetch("Gate", fetch) is None  # fails fast, no second connection
    assert len(calls) == 1 and cache.offline
    now[0] += 61.0
    assert cache.fetch("Gate", lambda _p: WEBP) is not None
