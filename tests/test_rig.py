"""Tests for the Valeton GP-180 rig parser, lookup, and bulk index.

Covers three things that have each broken in production:

1. **The ``rig_`` prefix-strip regression** — chaining
   ``.removeprefix("rig_").removeprefix("rig")`` corrupted any song whose name
   starts with "ri" (``rig_right_now_…`` → ``ht_now_…``), so its rig silently
   vanished from the library's has-rig column. ``_rig_body`` must strip the
   prefix exactly once.

2. **Index/``find_rig`` agreement** — ``GET /api/files`` uses the bulk
   :func:`build_rig_index` + :func:`partition_has_rig` for speed, while
   ``GET /api/rig/{file}`` uses :func:`find_rig`. They must agree for every
   file, or the library shows a rig icon that the detail endpoint can't resolve
   (or vice-versa).

3. **Markdown parsing** — active vs inactive effects, preset/param extraction,
   and pedal-image mapping.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from fretwise.rig import (
    _find_guitar_image,
    _fingerprint,
    _rig_body,
    build_rig_index,
    find_rig,
    find_rigs_dir,
    parse_rig,
    partition_has_rig,
)

# A realistic rig file (trimmed from a real grade-D fixture).
_SAMPLE_RIG = """# Rig GP-180 — Accept · Balls To The Wall

Artiste : Accept
Chanson : Balls To The Wall
Genre : classic rock
Accordage : Mi standard (E standard)
Capo : non
Guitare originale : Non précisé (Les Paul ou Strat)
Fiabilité : D — À confirmer (aucune référence solide)

Chaîne GP-180 :
NR → PRE → WAH → DST → N→S → AMP → CAB/IR → EQ → MOD → DLY → RVB → VOL

Réglages GP-180 :
- NR : Gate 1 · Threshold −55 dB (à serrer si single coils bruyants)
- PRE : off
- WAH : off
- DST : Non
- N→S : Non (aucune SnapTone dédiée)
- AMP : UK 50 — Gain 55 · Bass 48 · Mid 60 · Treble 58 · Presence 55 · Level 60
- CAB / IR : UK Vintage 4x12 · Level 60
- EQ : Guitar EQ 1 · neutre · à ajuster
- MOD : Non
- DLY : Non
- RVB : Room · Mix 8
- VOL : Level 60 · rôle = niveau final

Notes de jeu :
- Réglage générique classic rock à affiner à l'oreille
- Régler les niveaux à l'oreille

Limites / compromis :
- Fiabilité D : aucune référence dans le référentiel embarqué

- date_added : 02-11-2026
"""


def _make_rig(rigs_dir: Path, stem: str, content: str = _SAMPLE_RIG) -> Path:
    rigs_dir.mkdir(parents=True, exist_ok=True)
    path = rigs_dir / f"{stem}.md"
    path.write_text(content, encoding="utf-8")
    return path


# --------------------------------------------------------------------------- #
# 1. The prefix-strip regression.
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize(
    "stem, expected",
    [
        ("rig_right_now_van_halen", "right_now_van_halen"),   # the regression
        ("rig_riff_raff_acdc", "riff_raff_acdc"),             # song also starts "ri"
        ("rig_balls_to_the_wall_accept", "balls_to_the_wall_accept"),
        ("rig_1979_smashing_pumpkins", "1979_smashing_pumpkins"),
        ("rignospace", "nospace"),                            # bare "rig" prefix
        ("no_prefix_here", "no_prefix_here"),                 # nothing to strip
    ],
)
def test_rig_body_strips_prefix_exactly_once(stem: str, expected: str) -> None:
    assert _rig_body(stem) == expected


def test_right_now_does_not_get_mangled_into_ht_now() -> None:
    """Direct guard on the exact bug: 'right_now' must survive prefix stripping.

    The old chained-removeprefix code turned the body into ``ht_now_van_halen``
    (fingerprint ``htnowvanhalen``); the fixed code keeps the leading "right".
    """
    body = _rig_body("rig_right_now_van_halen")
    assert body == "right_now_van_halen"
    assert _fingerprint(body) == "rightnowvanhalen"
    # The bug produced this exact wrong fingerprint — it must NOT come back.
    assert _fingerprint(body) != "htnowvanhalen"
    assert body.startswith("right")


# --------------------------------------------------------------------------- #
# 2. Lookup + bulk index agreement.
# --------------------------------------------------------------------------- #
def test_find_rig_exact_match(tmp_path: Path) -> None:
    rigs = tmp_path / "rigs"
    _make_rig(rigs, "rig_balls_to_the_wall_accept")
    got = find_rig("Accept - Balls To The Wall - 02-11-2026.gp", rigs)
    assert got is not None
    assert got.name == "rig_balls_to_the_wall_accept.md"


def test_find_rig_resolves_van_halen_right_now(tmp_path: Path) -> None:
    """The regression file resolves via both the exact and index paths."""
    rigs = tmp_path / "rigs"
    _make_rig(rigs, "rig_right_now_van_halen")
    name = "Van Halen - Right Now - 04-25-2026.gp"
    assert find_rig(name, rigs) is not None
    idx = build_rig_index(rigs)
    assert partition_has_rig(name, idx) is True


def test_find_rig_handles_fingered_and_undated_names(tmp_path: Path) -> None:
    rigs = tmp_path / "rigs"
    _make_rig(rigs, "rig_balls_to_the_wall_accept")
    for name in (
        "Accept - Balls To The Wall.gp",                       # no date
        "Accept - Balls To The Wall - 02-11-2026.gp",          # dated
        "Accept - Balls To The Wall - 02-11-2026_fingered.gp",  # fingered variant
    ):
        assert find_rig(name, rigs) is not None, name


def test_find_rig_returns_none_when_absent(tmp_path: Path) -> None:
    rigs = tmp_path / "rigs"
    _make_rig(rigs, "rig_balls_to_the_wall_accept")
    assert find_rig("Nobody - No Such Song - 01-01-2026.gp", rigs) is None


def test_index_and_find_rig_agree_for_every_file(tmp_path: Path) -> None:
    """Bulk has-rig (index) and single lookup (find_rig) must never disagree."""
    rigs = tmp_path / "rigs"
    for stem in (
        "rig_right_now_van_halen",          # starts with "ri" — the trap
        "rig_balls_to_the_wall_accept",
        "rig_smells_like_teen_spirit_nirvana",
        "rig_that_smell_lynyrd_skynyrd",
        "rig_1979_smashing_pumpkins",
    ):
        _make_rig(rigs, stem)
    idx = build_rig_index(rigs)

    partitions = [
        "Van Halen - Right Now - 04-25-2026.gp",
        "Accept - Balls To The Wall - 02-11-2026.gp",
        "Nirvana - Smells Like Teen Spirit - 12-18-2025.gp",
        "Lynyrd Skynyrd - That Smell - 03-24-2026.gp",
        "The Smashing Pumpkins - 1979 - 01-01-2026.gp",
        "Some Band - Unmatched Song - 01-01-2026.gp",   # no rig
    ]
    for name in partitions:
        via_index = partition_has_rig(name, idx)
        via_find = find_rig(name, rigs) is not None
        assert via_index == via_find, f"disagreement on {name!r}"


def test_build_rig_index_missing_dir_is_empty_and_safe() -> None:
    """A missing/None rigs dir yields an empty index and never raises."""
    assert build_rig_index(None) == set()
    assert build_rig_index(Path("Z:/definitely/not/here")) == set()
    assert partition_has_rig("Anything - At All.gp", set()) is False


# --------------------------------------------------------------------------- #
# 3. Markdown parsing.
# --------------------------------------------------------------------------- #
def test_parse_rig_extracts_metadata() -> None:
    data = parse_rig(_SAMPLE_RIG)
    assert data["artist"] == "Accept"
    assert data["song"] == "Balls To The Wall"
    assert data["genre"] == "classic rock"
    assert data["fiabilite"] == "D"
    assert data["accordage"].startswith("Mi standard")
    assert data["capo"] == "non"
    assert data["notes"] and "classic rock" in data["notes"]
    assert data["limites"] and "Fiabilité D" in data["limites"]


def test_parse_rig_active_vs_inactive_effects() -> None:
    reg = parse_rig(_SAMPLE_RIG)["reglages"]
    # Active effects carry a preset; inactive ones are flagged off with no preset.
    assert reg["NR"]["active"] is True
    assert reg["AMP"]["active"] is True
    assert reg["RVB"]["active"] is True
    for off in ("PRE", "WAH", "DST", "N→S", "MOD", "DLY"):
        assert reg[off]["active"] is False, off
        assert reg[off]["preset"] is None


def test_parse_rig_preset_and_param_split() -> None:
    reg = parse_rig(_SAMPLE_RIG)["reglages"]
    # "UK 50 — Gain 55 · Bass 48 …" → preset is just the amp name.
    assert reg["AMP"]["preset"] == "UK 50"
    assert reg["AMP"]["params"] and "Gain 55" in reg["AMP"]["params"]
    assert reg["CAB/IR"]["preset"] == "UK Vintage 4x12"
    assert reg["EQ"]["preset"] == "Guitar EQ 1"


def test_parse_rig_maps_pedal_images() -> None:
    reg = parse_rig(_SAMPLE_RIG)["reglages"]
    # Specific art is used only when the file ships; AMP/CAB do.
    assert reg["AMP"]["image"] == "29_AMP_UK45_Marshall_JTM45.jpg"
    assert reg["CAB/IR"]["image"] == "41_CAB_UK4x12_Marshall.jpg"
    # Gate 1 / Guitar EQ 1 have no shipped art -> generic per-category fallback
    # (never a broken image) keyed off the chain slot.
    assert reg["NR"]["image"] == "nose gate.png"
    assert reg["EQ"]["image"] == "equalizer.png"
    # Inactive effects never carry an image.
    assert reg["DST"]["image"] is None


def test_parse_rig_active_effect_falls_back_to_category_image() -> None:
    """An active effect with no specific pedal match gets generic category art."""
    reg = parse_rig(_SAMPLE_RIG)["reglages"]
    # "Room" matches no specific reverb pedal, so RVB falls back to the generic.
    assert reg["RVB"]["active"] is True
    assert reg["RVB"]["image"] == "reverb.png"


@pytest.mark.parametrize(
    "name, expected",
    [
        ("Fender Stratocaster SSS (Gilmour)", "stratocaster sss.jpg"),
        ("Gibson Les Paul humbuckers", "gibson les paul junior.png"),
        ("Gibson SG humbuckers (Iommi)", "gibson sg.png"),
        ("Telecaster (Open G - Richards)", "telecaster.jpg"),
        ("Strat / Jackson superstrat humbucker", "stratocaster sss.jpg"),
        ("Non précisé (Les Paul ou Strat)", "gibson les paul junior.png"),
        (None, None),
        ("Some unknown lutherie", None),
    ],
)
def test_find_guitar_image_matches_known_models(name, expected) -> None:
    assert _find_guitar_image(name) == expected


def test_parse_rig_sets_guitar_images() -> None:
    data = parse_rig(_SAMPLE_RIG)
    # "Non précisé (Les Paul ou Strat)" → longest keyword "les paul" wins.
    assert data["guitare_originale_image"] == "gibson les paul junior.png"
    # No "Guitare cible" field in the sample → None.
    assert data["guitare_cible_image"] is None


def test_find_rigs_dir_prefers_local_subdir(tmp_path: Path) -> None:
    rigs = tmp_path / "rigs"
    rigs.mkdir()
    assert find_rigs_dir(tmp_path) == rigs
