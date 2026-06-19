"""Tests for filename -> metadata parsing and file_info enrichment.

Covers the library-UX metadata cleanup (E2.1): filenames shaped like
``Artist - Title - MM-DD-YYYY.gp`` must yield a clean Title/Artist/Year, with
real songs_index metadata taking precedence over the filename parse.
"""

from __future__ import annotations

from pathlib import Path

from fretwise.web.songs_index import (
    CATALOG_COLUMNS,
    enrich_file_info,
    load_index,
    load_index_from_text,
    merge_catalog,
    parse_filename_metadata,
    serialize_index,
)


def test_parse_spaced_separator_with_date():
    meta = parse_filename_metadata("Aerosmith - Back In The Saddle - 10-16-2024.gp")
    assert meta == {
        "title": "Back In The Saddle",
        "artist": "Aerosmith",
        "year": "2024",
    }


def test_parse_tight_separator_with_date():
    meta = parse_filename_metadata("Metallica-Enter Sandman-01-02-2020.gp")
    assert meta["artist"] == "Metallica"
    assert meta["title"] == "Enter Sandman"
    assert meta["year"] == "2020"


def test_parse_no_extension():
    meta = parse_filename_metadata("Artist-Title-01-02-2020")
    assert meta == {"title": "Title", "artist": "Artist", "year": "2020"}


def test_parse_no_date():
    meta = parse_filename_metadata("Pink Floyd - Time.gp")
    assert meta == {"title": "Time", "artist": "Pink Floyd"}
    assert "year" not in meta


def test_parse_no_artist_separator():
    meta = parse_filename_metadata("SomeStandaloneSong.gp")
    assert meta == {"title": "SomeStandaloneSong"}
    assert "artist" not in meta


def test_parse_title_is_stripped_of_trailing_date_only():
    # The single-digit month/day form is also recognised.
    meta = parse_filename_metadata("Band - Song Name - 3-4-1999.gp5")
    assert meta["year"] == "1999"
    assert meta["title"] == "Song Name"


def test_enrich_uses_filename_when_no_index():
    info = {"name": "Aerosmith - Back In The Saddle - 10-16-2024.gp", "stem": "", "format": "gp"}
    enriched = enrich_file_info(info, {})
    assert enriched["meta"]["title"] == "Back In The Saddle"
    assert enriched["meta"]["artist"] == "Aerosmith"
    assert enriched["meta"]["year"] == "2024"
    # Album/Genre are NOT invented.
    assert "album" not in enriched["meta"]
    assert "genre" not in enriched["meta"]


def test_enrich_index_overrides_filename():
    name = "Aerosmith - Back In The Saddle - 10-16-2024.gp"
    info = {"name": name, "stem": "", "format": "gp"}
    index = {name: {"filename": name, "title": "Real Title", "genre": "Rock", "artist": ""}}
    enriched = enrich_file_info(info, index)
    # Real non-empty index value wins.
    assert enriched["meta"]["title"] == "Real Title"
    # Empty index value does NOT clobber the filename-derived artist.
    assert enriched["meta"]["artist"] == "Aerosmith"
    # Index supplies a genre; year still comes from the filename.
    assert enriched["meta"]["genre"] == "Rock"
    assert enriched["meta"]["year"] == "2024"


def test_enrich_empty_name_is_defensive():
    enriched = enrich_file_info({"name": "", "stem": "", "format": "gp"}, {})
    # No crash; meta may be absent or empty.
    assert "meta" not in enriched or isinstance(enriched["meta"], dict)


def test_enrich_surfaces_album_genre_notes_from_catalog():
    name = "Aerosmith - Back In The Saddle - 10-16-2024.gp"
    info = {"name": name, "stem": "", "format": "gp"}
    index = {
        name: {
            "filename": name,
            "album": "Rocks",
            "genre": "Hard Rock",
            "notes": "Watch the slide intro",
        }
    }
    meta = enrich_file_info(info, index)["meta"]
    assert meta["album"] == "Rocks"
    assert meta["genre"] == "Hard Rock"
    assert meta["notes"] == "Watch the slide intro"
    # Filename-derived fields are still present alongside catalog fields.
    assert meta["title"] == "Back In The Saddle"
    assert meta["year"] == "2024"


def test_enrich_does_not_copy_key_columns_into_meta():
    name = "Song.gp"
    index = {name: {"filename": name, "stem": "Song", "title": "Real"}}
    meta = enrich_file_info({"name": name, "stem": "Song", "format": "gp"}, index)["meta"]
    assert "filename" not in meta
    assert "stem" not in meta
    assert meta["title"] == "Real"


# ── load_index ──────────────────────────────────────────────────────


def _write_tsv(tmp_path: Path, text: str, *, encoding: str = "utf-8") -> Path:
    p = tmp_path / "songs.tsv"
    p.write_text(text, encoding=encoding)
    return p


def test_load_index_missing_file_returns_empty(tmp_path):
    assert load_index(tmp_path / "nope.tsv") == {}
    assert load_index("") == {}


def test_load_index_keys_by_filename_and_stem(tmp_path):
    p = _write_tsv(
        tmp_path,
        "filename\ttitle\tartist\talbum\tgenre\tyear\tnotes\n"
        "Song.gp\tTitle\tArtist\tAlbum\tRock\t1999\tCapo 2\n",
    )
    idx = load_index(p)
    assert idx["Song.gp"]["title"] == "Title"
    # Indexed by stem too.
    assert idx["Song"]["genre"] == "Rock"
    assert idx["Song.gp"]["album"] == "Album"
    assert idx["Song.gp"]["notes"] == "Capo 2"


def test_load_index_tolerates_partial_columns(tmp_path):
    p = _write_tsv(
        tmp_path,
        "filename\tgenre\n"
        "A.gp\tJazz\n",
    )
    row = load_index(p)["A.gp"]
    assert row["genre"] == "Jazz"
    assert "album" not in row


def test_load_index_handles_bom_and_strips_whitespace(tmp_path):
    p = _write_tsv(
        tmp_path,
        "filename\ttitle\n"
        "  B.gp  \t  Padded Title  \n",
        encoding="utf-8-sig",
    )
    idx = load_index(p)
    assert idx["B.gp"]["title"] == "Padded Title"


def test_load_index_accepts_alias_key_columns(tmp_path):
    p = _write_tsv(tmp_path, "file\tgenre\nC.gp\tMetal\n")
    assert load_index(p)["C.gp"]["genre"] == "Metal"


def test_load_index_skips_rows_without_a_key(tmp_path):
    p = _write_tsv(
        tmp_path,
        "filename\tgenre\n"
        "\tOrphan\n"
        "D.gp\tBlues\n",
    )
    idx = load_index(p)
    assert "D.gp" in idx
    assert all(v.get("genre") != "Orphan" for v in idx.values())


def test_load_index_then_catalog_overrides_filename(tmp_path):
    # End-to-end: catalog title wins over the filename-derived title.
    p = _write_tsv(
        tmp_path,
        "filename\ttitle\tgenre\n"
        "Aerosmith - Back In The Saddle - 10-16-2024.gp\tReal Title\tRock\n",
    )
    idx = load_index(p)
    name = "Aerosmith - Back In The Saddle - 10-16-2024.gp"
    meta = enrich_file_info({"name": name, "stem": "", "format": "gp"}, idx)["meta"]
    assert meta["title"] == "Real Title"
    assert meta["genre"] == "Rock"
    # Year still comes from the filename.
    assert meta["year"] == "2024"


# ── load_index_from_text ───────────────────────────────────────────


def test_load_index_from_text_empty_returns_empty():
    assert load_index_from_text("") == {}


def test_load_index_from_text_parses_and_keys_by_filename_and_stem():
    text = (
        "filename\ttitle\tartist\tgenre\n"
        "Song.gp\tTitle\tArtist\tRock\n"
    )
    idx = load_index_from_text(text)
    assert idx["Song.gp"]["title"] == "Title"
    assert idx["Song"]["genre"] == "Rock"


def test_load_index_from_text_tolerates_leading_bom():
    text = "﻿filename\ttitle\nA.gp\tHello\n"
    assert load_index_from_text(text)["A.gp"]["title"] == "Hello"


def test_load_index_reuses_load_index_from_text(tmp_path):
    p = _write_tsv(tmp_path, "filename\tgenre\nX.gp\tJazz\n")
    assert load_index(p) == load_index_from_text("filename\tgenre\nX.gp\tJazz\n")


# ── serialize_index ─────────────────────────────────────────────────


def test_serialize_index_uses_canonical_column_order():
    text = serialize_index([{"filename": "A.gp", "artist": "Band", "title": "Song"}])
    header = text.splitlines()[0]
    assert header.split("\t") == list(CATALOG_COLUMNS)
    # Round-trips back through the loader.
    row = load_index_from_text(text)["A.gp"]
    assert row["title"] == "Song"
    assert row["artist"] == "Band"


def test_serialize_index_skips_rows_without_filename():
    text = serialize_index([{"title": "Orphan"}, {"filename": "B.gp", "title": "Keep"}])
    idx = load_index_from_text(text)
    assert list(idx) == ["B.gp", "B"]


def test_serialize_index_preserves_unknown_columns():
    text = serialize_index([{"filename": "C.gp", "tuning": "Drop D"}])
    assert "tuning" in text.splitlines()[0]
    assert load_index_from_text(text)["C.gp"]["tuning"] == "Drop D"


def test_serialize_index_round_trip_through_load():
    rows = [
        {"filename": "A.gp", "title": "T1", "artist": "Ar1", "genre": "Rock"},
        {"filename": "B.gp", "title": "T2", "year": "1999"},
    ]
    idx = load_index_from_text(serialize_index(rows))
    assert idx["A.gp"]["genre"] == "Rock"
    assert idx["B.gp"]["year"] == "1999"


# ── merge_catalog ───────────────────────────────────────────────────


def test_merge_catalog_adds_new_rows_into_empty_catalog():
    text, updated, added = merge_catalog(
        "", [{"filename": "A.gp", "title": "Song A", "artist": "Band"}]
    )
    assert (updated, added) == (0, 1)
    assert load_index_from_text(text)["A.gp"]["title"] == "Song A"


def test_merge_catalog_upserts_by_filename_and_counts():
    existing = "filename\ttitle\tgenre\nA.gp\tOld\tRock\n"
    incoming = [
        {"filename": "A.gp", "title": "New", "album": "Rocks"},  # update
        {"filename": "B.gp", "title": "Brand New"},               # add
    ]
    text, updated, added = merge_catalog(existing, incoming)
    assert (updated, added) == (1, 1)
    idx = load_index_from_text(text)
    # New non-empty value overrides; untouched field preserved.
    assert idx["A.gp"]["title"] == "New"
    assert idx["A.gp"]["genre"] == "Rock"
    assert idx["A.gp"]["album"] == "Rocks"
    assert idx["B.gp"]["title"] == "Brand New"


def test_merge_catalog_empty_incoming_value_does_not_clobber():
    existing = "filename\ttitle\nA.gp\tKeep Me\n"
    text, updated, added = merge_catalog(
        existing, [{"filename": "A.gp", "title": "", "artist": "Added"}]
    )
    assert (updated, added) == (1, 0)  # artist added -> counts as a change
    idx = load_index_from_text(text)
    assert idx["A.gp"]["title"] == "Keep Me"
    assert idx["A.gp"]["artist"] == "Added"


def test_merge_catalog_no_change_is_not_counted_as_update():
    existing = "filename\ttitle\nA.gp\tSame\n"
    _, updated, added = merge_catalog(existing, [{"filename": "A.gp", "title": "Same"}])
    assert (updated, added) == (0, 0)


def test_merge_catalog_skips_rows_without_filename():
    _, updated, added = merge_catalog("", [{"title": "No key"}])
    assert (updated, added) == (0, 0)


def test_merge_catalog_ignores_extra_keys():
    text, _, added = merge_catalog(
        "", [{"filename": "A.gp", "title": "T", "bogus": "ignored", "year": "2001"}]
    )
    assert added == 1
    row = load_index_from_text(text)["A.gp"]
    assert "bogus" not in row
    assert row["year"] == "2001"
