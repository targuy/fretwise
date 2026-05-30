"""Tests for fretwise.core.notation_mode — canonical mode strings and helpers."""

from __future__ import annotations

import pytest

from fretwise.core.notation_mode import (
    ALL_MODES,
    has_standard,
    has_tab,
    is_valid_mode,
    system_height_for_mode,
)


class TestCanonicalModeStrings:
    def test_all_modes_contains_four_canonical_values(self) -> None:
        assert set(ALL_MODES) == {
            "standard",
            "tablature",
            "standard_tablature",
            "tablature_rhythm",
        }

    def test_all_modes_is_tuple(self) -> None:
        assert isinstance(ALL_MODES, tuple)


class TestIsValidMode:
    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_canonical_values_are_valid(self, mode: str) -> None:
        assert is_valid_mode(mode) is True

    @pytest.mark.parametrize(
        "mode",
        ["", "tab", "hybrid", "STANDARD", "standard_tab", "unknown"],
    )
    def test_non_canonical_values_are_invalid(self, mode: str) -> None:
        assert is_valid_mode(mode) is False


class TestHasTab:
    @pytest.mark.parametrize(
        "mode", ["tablature", "tablature_rhythm", "standard_tablature"]
    )
    def test_modes_with_tab(self, mode: str) -> None:
        assert has_tab(mode) is True

    def test_standard_only_has_no_tab(self) -> None:
        assert has_tab("standard") is False

    def test_unknown_mode_has_no_tab(self) -> None:
        assert has_tab("foo") is False


class TestHasStandard:
    @pytest.mark.parametrize("mode", ["standard", "standard_tablature"])
    def test_modes_with_standard(self, mode: str) -> None:
        assert has_standard(mode) is True

    @pytest.mark.parametrize("mode", ["tablature", "tablature_rhythm"])
    def test_tab_only_modes_have_no_standard(self, mode: str) -> None:
        assert has_standard(mode) is False


class TestSystemHeightForMode:
    def test_standard_only(self) -> None:
        assert system_height_for_mode("standard") == 80.0

    @pytest.mark.parametrize("mode", ["tablature", "tablature_rhythm"])
    def test_tab_modes(self, mode: str) -> None:
        assert system_height_for_mode(mode) == 130.0

    def test_standard_tablature_default(self) -> None:
        assert system_height_for_mode("standard_tablature") == 168.0

    def test_unknown_mode_uses_default(self) -> None:
        # Defensive: unknown strings fall through to the standard_tablature height.
        assert system_height_for_mode("anything-else") == 168.0


class TestModeMutualExclusion:
    """Sanity: every canonical mode has at least one staff."""

    @pytest.mark.parametrize("mode", ALL_MODES)
    def test_every_mode_has_some_staff(self, mode: str) -> None:
        assert has_tab(mode) or has_standard(mode)
