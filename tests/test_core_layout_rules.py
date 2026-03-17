"""Tests for centralized layout rules helpers."""

from __future__ import annotations

from fretwise.core.layout.rules import (
    default_layout_rules,
    event_anchor_x,
    raw_measure_width,
    string_row_y,
)


def test_raw_measure_width_is_clamped() -> None:
    rules = default_layout_rules()
    assert raw_measure_width(0, rules) == rules.measure_min_width
    assert raw_measure_width(999, rules) == rules.measure_max_width


def test_event_anchor_x_stays_within_measure_padding() -> None:
    rules = default_layout_rules()
    x0 = event_anchor_x(
        onset_in_measure=0.0,
        beats_per_measure=4,
        measure_width=rules.measure_min_width,
        rules=rules,
    )
    x1 = event_anchor_x(
        onset_in_measure=3.0,
        beats_per_measure=4,
        measure_width=rules.measure_min_width,
        rules=rules,
    )
    assert x0 >= rules.measure_lr_pad
    assert x1 > x0


def test_string_row_y_maps_to_tab_rows() -> None:
    rules = default_layout_rules()
    y1 = string_row_y(string_num=1, rules=rules)
    y6 = string_row_y(string_num=6, rules=rules)
    assert y6 > y1

