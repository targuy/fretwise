"""Tests for centralized layout rules helpers."""

from __future__ import annotations

from fretwise.core.layout.rules import (
    default_layout_rules,
    event_anchor_x,
    raw_measure_width,
    string_row_y,
)


def test_raw_measure_width_empty_returns_minimum() -> None:
    rules = default_layout_rules()
    assert raw_measure_width([], 4, rules) == rules.measure_min_width


def test_raw_measure_width_dense_rhythm_respects_max() -> None:
    rules = default_layout_rules()
    # 64 very short onsets (extreme case) should not exceed the configured cap.
    positions = [i / 16.0 for i in range(64)]
    assert raw_measure_width(positions, 4, rules) <= rules.measure_max_width


def test_raw_measure_width_invariant_whole_equals_four_quarters() -> None:
    """Fundamental invariant: equivalent rhythmic content → identical width."""
    rules = default_layout_rules()
    whole = raw_measure_width([0.0], 4, rules)
    quarters = raw_measure_width([0.0, 1.0, 2.0, 3.0], 4, rules)
    assert whole == quarters


def test_raw_measure_width_invariant_half_plus_two_quarters_equals_four_quarters() -> None:
    rules = default_layout_rules()
    mix = raw_measure_width([0.0, 2.0, 3.0], 4, rules)
    quarters = raw_measure_width([0.0, 1.0, 2.0, 3.0], 4, rules)
    assert mix == quarters


def test_raw_measure_width_invariant_two_halves_equals_four_quarters() -> None:
    rules = default_layout_rules()
    halves = raw_measure_width([0.0, 2.0], 4, rules)
    quarters = raw_measure_width([0.0, 1.0, 2.0, 3.0], 4, rules)
    assert halves == quarters


def test_raw_measure_width_sixteenth_run_wider_than_quarters() -> None:
    rules = default_layout_rules()
    sixteenths = raw_measure_width([i * 0.25 for i in range(16)], 4, rules)
    quarters = raw_measure_width([0.0, 1.0, 2.0, 3.0], 4, rules)
    assert sixteenths > quarters


def test_raw_measure_width_eighth_notes_same_as_quarters() -> None:
    """8th notes (gap=0.5 beat, ideal=16 > min_note_width=14) still fill evenly."""
    rules = default_layout_rules()
    eighths = raw_measure_width([i * 0.5 for i in range(8)], 4, rules)
    quarters = raw_measure_width([0.0, 1.0, 2.0, 3.0], 4, rules)
    assert eighths == quarters


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

