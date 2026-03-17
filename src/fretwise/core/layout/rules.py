"""Centralized layout rules for page/system/measure placement."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LayoutRules:
    """Layout constants and thresholds."""

    page_width: float = 1200.0
    page_height: float = 380.0
    margin_x: float = 60.0
    margin_y: float = 40.0
    content_width: float = 1080.0
    system_height: float = 240.0
    staff_height: float = 240.0
    measure_min_width: float = 120.0
    measure_max_width: float = 240.0
    measure_lr_pad: float = 20.0
    row_top: float = 100.0
    row_spacing: float = 18.0
    width_per_onset: float = 40.0
    min_event_spacing: float = 14.0


def default_layout_rules() -> LayoutRules:
    """Return the default layout rule set."""
    return LayoutRules()


def raw_measure_width(unique_onset_count: int, rules: LayoutRules) -> float:
    """Compute a raw measure width from rhythmic density."""
    return min(
        rules.measure_max_width,
        max(
            rules.measure_min_width,
            rules.measure_lr_pad * 2 + max(1, unique_onset_count) * rules.width_per_onset,
        ),
    )


def event_anchor_x(
    *,
    onset_in_measure: float,
    beats_per_measure: int,
    measure_width: float,
    rules: LayoutRules,
) -> float:
    """Compute event anchor x inside a measure frame."""
    beats = max(1, beats_per_measure)
    frac = onset_in_measure / beats
    usable_w = max(20.0, measure_width - rules.measure_lr_pad * 2)
    return rules.measure_lr_pad + frac * usable_w


def string_row_y(*, string_num: int, rules: LayoutRules) -> float:
    """Return y anchor for one tablature string row."""
    s = max(1, min(6, string_num))
    return rules.row_top + (s - 1) * rules.row_spacing + 4.0

