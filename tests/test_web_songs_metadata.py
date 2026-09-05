"""Tests for the songs_metadata.json catalog reader + reconciliation.

Covers the library-list rework: songs_metadata.json entries (nom/artiste/
genre/type_guitare/difficulte) are matched to actual score filenames on every
read, never trusted from a persisted key, so the list stays in sync with the
partitions directory across startups.
"""

from __future__ import annotations

import json

from fretwise.web.songs_metadata import (
    CATALOG_FILENAME,
    load_songs_metadata,
    load_songs_metadata_from_text,
    reconcile_songs_metadata,
)


def test_load_songs_metadata_missing_file_returns_empty(tmp_path):
    assert load_songs_metadata(tmp_path / "nope.json") == []


def test_load_songs_metadata_from_text_malformed_returns_empty():
    assert load_songs_metadata_from_text("{not json") == []
    assert load_songs_metadata_from_text('{"not": "a list"}') == []
    assert load_songs_metadata_from_text("") == []


def test_load_songs_metadata_round_trip(tmp_path):
    entries = [
        {"nom": "Highway To Hell", "artiste": "AC/DC", "genre": "Hard Rock",
         "type_guitare": "Gibson SG", "type_guitare_incertain": False,
         "difficulte": "Intermédiaire", "difficulte_source": "gp_analysis"},
    ]
    path = tmp_path / CATALOG_FILENAME
    path.write_text(json.dumps(entries), encoding="utf-8")
    assert load_songs_metadata(path) == entries


def test_reconcile_exact_match_maps_fields():
    entries = [
        {"nom": "Highway To Hell", "artiste": "AC/DC", "genre": "Hard Rock",
         "type_guitare": "Gibson SG", "difficulte": "Intermédiaire"},
    ]
    index, missing, new_files = reconcile_songs_metadata(
        entries, ["AC_DC - Highway To Hell.gp"]
    )
    assert missing == []
    assert new_files == []
    assert index["AC_DC - Highway To Hell.gp"] == {
        "title": "Highway To Hell",
        "artist": "AC/DC",
        "genre": "Hard Rock",
        "type_guitare": "Gibson SG",
        "difficulte": "Intermédiaire",
    }


def test_reconcile_matches_despite_date_suffix_and_tight_hyphen():
    entries = [{"nom": "Back In Black", "artiste": "AC/DC", "genre": "Hard Rock",
                "type_guitare": "", "difficulte": ""}]
    index, missing, new_files = reconcile_songs_metadata(
        entries, ["AC_DC-Back In Black-07-11-2026.gp"]
    )
    assert missing == []
    assert index["AC_DC-Back In Black-07-11-2026.gp"]["title"] == "Back In Black"


def test_reconcile_matches_despite_extra_filename_suffix():
    # Filename carries extra descriptive words beyond the catalog's nom/artiste
    # (e.g. "Rock Band Version") — still a valid match since a superset of the
    # catalog's tokens is present in the filename.
    entries = [{"nom": "Wanted Dead Or Alive", "artiste": "Bon Jovi", "genre": "Rock",
                "type_guitare": "", "difficulte": ""}]
    index, missing, new_files = reconcile_songs_metadata(
        entries, ["Bon Jovi - Wanted Dead Or Alive - Rock Band Version.gp"]
    )
    assert missing == []
    assert index["Bon Jovi - Wanted Dead Or Alive - Rock Band Version.gp"]["title"] == (
        "Wanted Dead Or Alive"
    )


def test_reconcile_entry_with_no_file_is_reported_missing_and_excluded():
    entries = [{"nom": "Some Deleted Song", "artiste": "Nobody", "genre": "",
                "type_guitare": "", "difficulte": ""}]
    index, missing, new_files = reconcile_songs_metadata(entries, ["Other Artist - Other Song.gp"])
    assert index == {}
    assert missing == entries
    assert new_files == ["Other Artist - Other Song.gp"]


def test_reconcile_file_with_no_entry_is_reported_new_and_still_listed():
    index, missing, new_files = reconcile_songs_metadata([], ["Unknown Artist - New Song.gp"])
    assert index == {}
    assert missing == []
    assert new_files == ["Unknown Artist - New Song.gp"]


def test_reconcile_duplicate_entries_do_not_double_claim_one_file():
    # Two catalog rows for the same song but only one file on disk: only one
    # of them can win the file; the other is reported missing rather than both
    # silently pointing at the same filename.
    entries = [
        {"nom": "Girl From Mars", "artiste": "Ash", "genre": "Rock",
         "type_guitare": "", "difficulte": "Débutant"},
        {"nom": "Girl From Mars", "artiste": "Ash", "genre": "Rock",
         "type_guitare": "", "difficulte": "Avancé"},
    ]
    index, missing, new_files = reconcile_songs_metadata(entries, ["Ash - Girl From Mars.gp"])
    assert len(index) == 1
    assert len(missing) == 1
    assert new_files == []


def test_reconcile_duplicate_entries_match_two_distinct_files():
    entries = [
        {"nom": "Girl From Mars", "artiste": "Ash", "genre": "Rock",
         "type_guitare": "", "difficulte": "Débutant"},
        {"nom": "Girl From Mars", "artiste": "Ash", "genre": "Rock",
         "type_guitare": "", "difficulte": "Avancé"},
    ]
    files = ["Ash - Girl From Mars.gp", "Ash - Girl From Mars - Acoustic.gp"]
    index, missing, new_files = reconcile_songs_metadata(entries, files)
    assert missing == []
    assert new_files == []
    assert set(index) == set(files)


def test_reconcile_empty_entries_and_no_files():
    assert reconcile_songs_metadata([], []) == ({}, [], [])
