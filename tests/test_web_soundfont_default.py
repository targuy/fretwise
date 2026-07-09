"""Tests for ``_prefer_gm_bank`` — the default-soundfont picker.

Background: the default resolution used the alphabetically-first soundfont in the
directory. With a mix of banks that lands on a non-GM, guitar-only pack (e.g.
"East_West_-_…Guitar Samples Collection.sf3" sorts before "GeneralUser-GS.sf3"),
so bass/drums/keys tracks have no GM program and collapse onto one timbre — tabs
sound wrong whatever soundfont is later tried. The picker must prefer a GM bank.
"""

from __future__ import annotations

from pathlib import Path

from fretwise.web.app import _prefer_gm_bank


def _p(name: str) -> Path:
    return Path("data/sounds") / name


def test_prefers_general_midi_over_alphabetically_first() -> None:
    """The real regression: a guitar pack sorts first but GeneralUser wins."""
    banks = [
        _p("East_West_-_Steve_Stevens_Guitar_Samples_Collection.sf3"),
        _p("GeneralUser-GS.sf3"),
        _p("StrixGuitarPack.sf3"),
        _p("alex_gm.sf3"),
    ]
    assert _prefer_gm_bank(banks) == _p("GeneralUser-GS.sf3")


def test_gm_suffix_in_name_is_recognized() -> None:
    """A "…_gm" bank is a valid GM hint when no "general" name is present."""
    banks = [_p("StrixGuitarPack.sf3"), _p("alex_gm.sf3")]
    assert _prefer_gm_bank(banks) == _p("alex_gm.sf3")


def test_falls_back_to_first_when_no_gm_bank() -> None:
    """No GM-looking name ⇒ keep the (pre-sorted) first candidate, never None."""
    banks = [_p("StrixGuitarPack.sf3"), _p("East_West.sf3")]
    assert _prefer_gm_bank(banks) == _p("StrixGuitarPack.sf3")


def test_empty_returns_none() -> None:
    assert _prefer_gm_bank([]) is None


def test_gm_is_not_matched_inside_unrelated_words() -> None:
    """"gm" must be a token, not a substring of e.g. "Enigma" or "Pigment"."""
    banks = [_p("Enigma_Pigment_Pack.sf3"), _p("GeneralUser-GS.sf3")]
    assert _prefer_gm_bank(banks) == _p("GeneralUser-GS.sf3")
