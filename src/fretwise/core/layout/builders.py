"""Layout builders from canonical semantic model."""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.core.canonical import NoteEvent as CanonicalNoteEvent
from fretwise.core.canonical import Score
from fretwise.core.layout.collisions import enforce_min_event_spacing
from fretwise.core.layout.models import (
    CollisionIssue,
    EventLayout,
    MeasureLayout,
    PageLayout,
    StaffLayout,
    SystemLayout,
)
from fretwise.core.layout.rules import (
    LayoutRules,
    default_layout_rules,
    event_anchor_x,
    raw_measure_width,
    string_row_y,
)


@dataclass(frozen=True)
class _MeasurePack:
    number: int
    beats: int
    raw_width: float
    event_layouts: list[EventLayout]
    collision_issues: list[CollisionIssue]


def canonical_to_page_layout(
    score: Score, *, rules: LayoutRules | None = None
) -> PageLayout:
    """Build the first-page layout contract from a canonical score."""
    layout_rules = rules or default_layout_rules()
    systems: list[SystemLayout] = []
    packs = _measure_packs(score, rules=layout_rules)
    if not packs:
        return PageLayout(
            page_number=1,
            width=layout_rules.page_width,
            height=layout_rules.page_height,
            systems=[],
            metadata={"title": score.title},
        )

    system_chunks = _chunk_measures_into_systems(packs, layout_rules.content_width)
    for system_index, chunk in enumerate(system_chunks, start=1):
        total_raw = sum(pack.raw_width for pack in chunk)
        scale = layout_rules.content_width / total_raw if total_raw > 0 else 1.0

        cursor_x = layout_rules.margin_x
        measure_layouts: list[MeasureLayout] = []
        for pack in chunk:
            width = pack.raw_width * scale
            measure_layouts.append(
                MeasureLayout(
                    measure_number=pack.number,
                    x=cursor_x,
                    y=layout_rules.margin_y,
                    width=width,
                    height=layout_rules.staff_height,
                    beats_per_measure=pack.beats,
                    event_layouts=_remap_event_x(
                        pack.event_layouts,
                        from_width=pack.raw_width,
                        to_x=cursor_x,
                        to_width=width,
                    ),
                    collision_issues=list(pack.collision_issues),
                )
            )
            cursor_x += width

        staff = StaffLayout(
            staff_id=f"staff-{system_index}",
            x=layout_rules.margin_x,
            y=layout_rules.margin_y,
            width=layout_rules.content_width,
            height=layout_rules.staff_height,
            measure_layouts=measure_layouts,
        )
        systems.append(
            SystemLayout(
                system_id=f"system-{system_index}",
                x=layout_rules.margin_x,
                y=layout_rules.margin_y,
                width=layout_rules.content_width,
                height=layout_rules.system_height,
                staves=[staff],
            )
        )

    return PageLayout(
        page_number=1,
        width=layout_rules.page_width,
        height=layout_rules.page_height,
        systems=systems,
        metadata={"title": score.title},
    )


def _measure_packs(score: Score, *, rules: LayoutRules) -> list[_MeasurePack]:
    if not score.tracks:
        return []
    track = score.tracks[0]
    if not track.staff_groups or not track.staff_groups[0].staves:
        return []
    staff = track.staff_groups[0].staves[0]

    packs: list[_MeasurePack] = []
    for measure in staff.measures:
        beats = max(1, measure.time_signature.numerator)
        events, collision_issues = _measure_event_layouts(
            measure.number,
            beats,
            measure.voices,
            rules=rules,
        )
        unique_onsets = len({e.onset for e in events})
        raw_width = raw_measure_width(unique_onsets, rules)
        packs.append(
            _MeasurePack(
                number=measure.number,
                beats=beats,
                raw_width=raw_width,
                event_layouts=events,
                collision_issues=collision_issues,
            )
        )
    return packs


def _measure_event_layouts(
    measure_number: int,
    beats_per_measure: int,
    voices: list[object],
    *,
    rules: LayoutRules,
) -> tuple[list[EventLayout], list[CollisionIssue]]:
    del measure_number
    layouts: list[EventLayout] = []

    for voice in voices:
        events = getattr(voice, "events", [])
        for event in events:
            rel_onset = event.onset % beats_per_measure
            x = event_anchor_x(
                onset_in_measure=rel_onset,
                beats_per_measure=beats_per_measure,
                measure_width=rules.measure_min_width,
                rules=rules,
            )
            y = string_row_y(string_num=3, rules=rules)
            metadata: dict[str, str] = {"event_type": event.__class__.__name__}
            if isinstance(event, CanonicalNoteEvent):
                string_num = 3
                if event.tab_info is not None and event.tab_info.string is not None:
                    string_num = max(1, min(6, event.tab_info.string))
                y = string_row_y(string_num=string_num, rules=rules)
                metadata["pitch_notated"] = str(event.pitch_notated)
                if event.tab_info is not None and event.tab_info.fret is not None:
                    metadata["tab_fret"] = str(event.tab_info.fret)
                metadata["tab_string"] = str(string_num)

            layouts.append(
                EventLayout(
                    event_id=event.event_id,
                    onset=event.onset,
                    duration=event.duration,
                    x=x,
                    y=y,
                    metadata=metadata,
                )
            )

    adjusted, collision_issues = enforce_min_event_spacing(
        layouts,
        min_spacing=rules.min_event_spacing,
    )
    return adjusted, collision_issues


def _chunk_measures_into_systems(
    packs: list[_MeasurePack], available_width: float
) -> list[list[_MeasurePack]]:
    chunks: list[list[_MeasurePack]] = []
    current: list[_MeasurePack] = []
    current_width = 0.0

    for pack in packs:
        if current and current_width + pack.raw_width > available_width:
            chunks.append(current)
            current = [pack]
            current_width = pack.raw_width
            continue
        current.append(pack)
        current_width += pack.raw_width

    if current:
        chunks.append(current)
    return chunks


def _remap_event_x(
    events: list[EventLayout], *, from_width: float, to_x: float, to_width: float
) -> list[EventLayout]:
    if from_width <= 0:
        return events
    scale = to_width / from_width
    return [
        EventLayout(
            event_id=event.event_id,
            onset=event.onset,
            duration=event.duration,
            x=to_x + event.x * scale,
            y=event.y,
            metadata=dict(event.metadata),
        )
        for event in events
    ]
