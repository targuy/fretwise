"""Tests du package fretwise.partitions (lib pure, rebuild_indexes, paths).

Aucun test ne touche le répertoire iCloud réel ni le réseau : tout passe par
tmp_path et monkeypatch des variables d'environnement.
"""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fretwise.partitions import paths, rebuild_indexes
from fretwise.partitions.lib import (
    is_partition_file,
    normalize_identity,
    parse_filename,
    to_display_entry,
)

# ── parse_filename (cas repris de scripts/test_lib_partitions.py) ─────────────

PARSE_CASES = [
    ("AC_DC-Back In Black-12-05-2025.gp",
     ("AC/DC", "Back In Black", "12-05-2025", False)),
    ("AC_DC - Back In Black - 12-05-2025.gp",
     ("AC/DC", "Back In Black", "12-05-2025", False)),
    ("AC_DC - Back In Black - 12-05-2025_fingered.gp",
     ("AC/DC", "Back In Black", "12-05-2025", True)),
    ("Blink-182 - All The Small Things - 06-12-2024.gp",
     ("Blink-182", "All The Small Things", "06-12-2024", False)),
    ("10cc-I'm Not In Love-10-26-2025.gp",
     ("10cc", "I'm Not In Love", "10-26-2025", False)),
    ("Pink Floyd - Echoes - 03-26-2026_fingered.gp",
     ("Pink Floyd", "Echoes", "03-26-2026", True)),
    ("Solo.gp",
     ("Solo", "", None, False)),
]


@pytest.mark.parametrize(("filename", "expected"), PARSE_CASES)
def test_parse_filename(filename: str, expected: tuple) -> None:
    p = parse_filename(filename)
    assert (p.artist, p.title, p.date, p.fingered) == expected


def test_normalize_identity_acdc_variants_are_equal() -> None:
    assert normalize_identity("AC/DC", "Back In Black") == \
        normalize_identity("AC_DC", "BACK in black")


def test_normalize_identity_strips_accents_and_fingered() -> None:
    assert normalize_identity("Téléphone", "Un Autre Monde") == \
        normalize_identity("Telephone", "un autre monde fingered")


def test_to_display_entry() -> None:
    assert to_display_entry("AC_DC-Back In Black-12-05-2025.gp") == "AC/DC - Back In Black"
    assert to_display_entry("Solo.gp") == "Solo"


def test_is_partition_file() -> None:
    assert is_partition_file("a.gp")
    assert is_partition_file("a.GP5")
    assert is_partition_file("a.gpx")
    assert not is_partition_file("a.mid")
    assert not is_partition_file("a.gp.txt")


# ── paths : les variables d'environnement sont honorées ───────────────────────

def test_paths_honor_env_vars(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("FRETWISE_PARTITIONS_ROOT", str(tmp_path / "rootx"))
    monkeypatch.setenv("FRETWISE_DOWNLOADS_DIR", str(tmp_path / "dl"))
    monkeypatch.setenv("FRETWISE_GDRIVE_DIR", str(tmp_path / "gd"))

    root = tmp_path / "rootx"
    assert paths.partitions_root() == root
    assert paths.downloads_dir() == tmp_path / "dl"
    assert paths.gdrive_dir() == tmp_path / "gd"
    assert paths.gp_dir() == root / "partitions"
    assert paths.doublons_archive_dir() == root / "_doublons_archive"
    assert paths.notion_queue_dir() == root / "_notion_queue"
    assert paths.archive_logs_dir() == root / "_archive_logs"
    assert paths.songs_index_path() == root / "songs_index.tsv"
    assert paths.liste_partitions_path() == root / "liste_partitions.txt"


def test_paths_defaults_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FRETWISE_PARTITIONS_ROOT", raising=False)
    monkeypatch.delenv("FRETWISE_DOWNLOADS_DIR", raising=False)
    assert str(paths.partitions_root()) == paths.DEFAULT_PARTITIONS_ROOT
    assert paths.downloads_dir() == Path.home() / "Downloads"


# ── rebuild_indexes sur un faux workspace ─────────────────────────────────────

def test_rebuild_indexes_on_tmp_workspace(tmp_path: Path) -> None:
    gp = tmp_path / "partitions"
    gp.mkdir()
    (gp / "AC_DC-Back In Black-12-05-2025.gp").touch()
    (gp / "Pink Floyd - Echoes - 03-26-2026_fingered.gp").touch()
    (gp / "Solo.gp").touch()
    (gp / "notes.txt").touch()  # ignoré : pas une partition

    rc = rebuild_indexes.main(["--root", str(tmp_path)])
    assert rc == 0

    liste = (tmp_path / "liste_partitions.txt").read_text(encoding="utf-8")
    assert "AC/DC - Back In Black" in liste
    assert "Pink Floyd - Echoes" in liste
    assert "Solo" in liste
    assert "notes" not in liste

    tsv = tmp_path / "songs_index.tsv"
    rows = list(csv.DictReader(tsv.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    assert len(rows) == 3
    by_file = {r["file"]: r for r in rows}
    acdc = by_file["AC_DC-Back In Black-12-05-2025.gp"]
    assert acdc["artist"] == "AC/DC"
    assert acdc["title"] == "Back In Black"
    assert acdc["date_added"] == "12-05-2025"
    assert acdc["fingered"] == ""
    floyd = by_file["Pink Floyd - Echoes - 03-26-2026_fingered.gp"]
    assert floyd["fingered"] == "1"


def test_rebuild_indexes_preserves_metadata(tmp_path: Path) -> None:
    gp = tmp_path / "partitions"
    gp.mkdir()
    (gp / "AC_DC-Back In Black-12-05-2025.gp").touch()

    assert rebuild_indexes.main(["--root", str(tmp_path)]) == 0

    # Enrichit manuellement le TSV, puis rebuild : les métadonnées survivent
    tsv = tmp_path / "songs_index.tsv"
    content = tsv.read_text(encoding="utf-8").splitlines()
    rows = list(csv.DictReader(content, delimiter="\t"))
    rows[0]["genre"] = "Hard Rock"
    rows[0]["year"] = "1980"
    with tsv.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()), delimiter="\t")
        w.writeheader()
        w.writerows(rows)

    assert rebuild_indexes.main(["--root", str(tmp_path)]) == 0
    rows2 = list(csv.DictReader(tsv.read_text(encoding="utf-8").splitlines(), delimiter="\t"))
    assert rows2[0]["genre"] == "Hard Rock"
    assert rows2[0]["year"] == "1980"


def test_rebuild_indexes_missing_dir_returns_1(tmp_path: Path) -> None:
    assert rebuild_indexes.main(["--root", str(tmp_path / "nope")]) == 1
