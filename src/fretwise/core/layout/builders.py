"""Layout builders from canonical semantic model."""

from __future__ import annotations

from dataclasses import dataclass, replace

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
    pitch_to_staff_y,
    raw_measure_width,
    string_row_y,
)


@dataclass(frozen=True)
class _MeasurePack:
    number: int
    beats: int
    time_denominator: int
    raw_width: float
    event_layouts: list[EventLayout]
    collision_issues: list[CollisionIssue]


def canonical_to_page_layout(
    score: Score, *, rules: LayoutRules | None = None, mode: str = "standard_tablature"
) -> PageLayout:
    """Build the first-page layout contract from a canonical score."""
    layout_rules = rules or default_layout_rules()
    # Adjust system height based on rendering mode so vertical spacing is appropriate.
    # standard_tablature uses the default 168 (standard staff + gap + tab + rhythm zone).
    # standard-only needs only ~80 px (staff + ledger lines + dynamics room).
    if mode == "standard":
        layout_rules = replace(layout_rules, system_height=80.0)
    elif mode in ("tablature", "tablature_rhythm"):
        layout_rules = replace(layout_rules, system_height=130.0)
    systems: list[SystemLayout] = []
    packs = _measure_packs(score, rules=layout_rules, mode=mode)
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
        system_y = layout_rules.margin_y + (system_index - 1) * (
            layout_rules.system_height + layout_rules.system_gap
        )

        cursor_x = layout_rules.margin_x
        measure_layouts: list[MeasureLayout] = []
        for chunk_index, pack in enumerate(chunk):
            width = pack.raw_width * scale
            left_inset = layout_rules.system_leading_inset if chunk_index == 0 else 0.0
            measure_layouts.append(
                MeasureLayout(
                    measure_number=pack.number,
                    x=cursor_x,
                    y=system_y,
                    width=width,
                    height=layout_rules.staff_height,
                    beats_per_measure=pack.beats,
                    time_denominator=pack.time_denominator,
                    event_layouts=_remap_event_x(
                        pack.event_layouts,
                        from_width=pack.raw_width,
                        to_x=cursor_x,
                        to_width=width,
                        left_inset=left_inset,
                        y_offset=system_y - layout_rules.margin_y,
                    ),
                    collision_issues=list(pack.collision_issues),
                )
            )
            cursor_x += width

        staff = StaffLayout(
            staff_id=f"staff-{system_index}",
            x=layout_rules.margin_x,
            y=system_y,
            width=layout_rules.content_width,
            height=layout_rules.staff_height,
            measure_layouts=measure_layouts,
        )
        systems.append(
            SystemLayout(
                system_id=f"system-{system_index}",
                x=layout_rules.margin_x,
                y=system_y,
                width=layout_rules.content_width,
                height=layout_rules.system_height,
                staves=[staff],
            )
        )

    required_height = (
        layout_rules.margin_y
        + len(system_chunks) * layout_rules.system_height
        + max(0, len(system_chunks) - 1) * layout_rules.system_gap
        + layout_rules.margin_y
    )

    return PageLayout(
        page_number=1,
        width=layout_rules.page_width,
        height=max(layout_rules.page_height, required_height),
        systems=systems,
        metadata={
            "title": score.title,
            "standard_staff_spacing": str(layout_rules.standard_staff_spacing),
            "tab_staff_spacing": str(layout_rules.tab_staff_spacing),
            "standard_tab_gap": str(layout_rules.standard_tab_gap),
            "system_leading_inset": str(layout_rules.system_leading_inset),
            "notehead_rx": str(layout_rules.notehead_rx),
            "notehead_ry": str(layout_rules.notehead_ry),
            "notehead_rotation_deg": str(layout_rules.notehead_rotation_deg),
            "notehead_stroke_width": str(layout_rules.notehead_stroke_width),
            "stem_notehead_dx": str(layout_rules.stem_notehead_dx),
            "rest_block_width": str(layout_rules.rest_block_width),
            "rest_block_height": str(layout_rules.rest_block_height),
        },
    )


def _measure_packs(
    score: Score, *, rules: LayoutRules, mode: str = "standard_tablature"
) -> list[_MeasurePack]:
    if not score.tracks:
        return []
    track = score.tracks[0]
    if not track.staff_groups or not track.staff_groups[0].staves:
        return []
    staff = track.staff_groups[0].staves[0]

    packs: list[_MeasurePack] = []
    for measure in staff.measures:
        beats_raw = max(1, measure.time_signature.numerator)
        time_denominator = measure.time_signature.denominator
        # Convert to quarter-beat count: e.g. 6/8 → 6*4//8 = 3, 4/4 → 4
        q_beats = max(1, beats_raw * 4 // time_denominator)
        # Two-pass: compute measure width from onset positions first so that
        # event x values are placed consistently with the remapping scale.
        onset_positions = _onset_beat_positions(measure.voices, beats_per_measure=q_beats)
        raw_width = raw_measure_width(onset_positions, q_beats, rules)
        events, collision_issues = _measure_event_layouts(
            measure.number,
            q_beats,
            measure.voices,
            rules=rules,
            measure_width=raw_width,
            mode=mode,
        )
        packs.append(
            _MeasurePack(
                number=measure.number,
                beats=q_beats,
                time_denominator=time_denominator,
                raw_width=raw_width,
                event_layouts=events,
                collision_issues=collision_issues,
            )
        )
    return packs


def _onset_beat_positions(voices: list[object], *, beats_per_measure: int) -> list[float]:
    """Collect sorted unique onset positions within a measure, in beats."""
    positions: set[float] = set()
    beats = max(1, beats_per_measure)
    for voice in voices:
        for event in getattr(voice, "events", []):
            rel_onset = round(getattr(event, "onset", 0.0) % beats, 9)
            positions.add(rel_onset)
    return sorted(positions)


def _measure_event_layouts(
    measure_number: int,
    beats_per_measure: int,
    voices: list[object],
    *,
    rules: LayoutRules,
    measure_width: float | None = None,
    mode: str = "standard_tablature",
) -> tuple[list[EventLayout], list[CollisionIssue]]:
    del measure_number
    # Use the caller-provided width so that proportional x values are consistent
    # with the from_width used in the later _remap_event_x call.
    width = measure_width if measure_width is not None else rules.measure_min_width
    layouts: list[EventLayout] = []

    for voice in voices:
        events = getattr(voice, "events", [])
        for event in events:
            rel_onset = event.onset % beats_per_measure
            x = event_anchor_x(
                onset_in_measure=rel_onset,
                beats_per_measure=beats_per_measure,
                measure_width=width,
                rules=rules,
            )
            y = string_row_y(string_num=3, rules=rules)
            metadata: dict[str, str] = {"event_type": event.__class__.__name__}
            metadata["voice_number"] = str(getattr(voice, "number", 0))
            layout_hints = getattr(event, "layout_hints", [])
            for hint in layout_hints:
                hint_key = str(getattr(hint, "key", "")).strip()
                hint_value = str(getattr(hint, "value", "")).strip()
                if hint_key:
                    metadata[hint_key] = hint_value
            if isinstance(event, CanonicalNoteEvent):
                string_num = 3
                if event.tab_info is not None and event.tab_info.string is not None:
                    string_num = max(1, min(6, event.tab_info.string))
                if mode in ("standard", "standard_tablature"):
                    y = pitch_to_staff_y(
                        event.pitch_notated,
                        staff_y_origin=rules.row_top,
                        staff_spacing=rules.standard_staff_spacing,
                    )
                else:
                    y = string_row_y(string_num=string_num, rules=rules)
                metadata["pitch_notated"] = str(event.pitch_notated)
                if event.tab_info is not None and event.tab_info.fret is not None:
                    metadata["tab_fret"] = str(event.tab_info.fret)
                metadata["tab_string"] = str(string_num)
                if event.techniques:
                    metadata["techniques"] = ",".join(
                        sorted({tech.name for tech in event.techniques})
                    )
                if event.dynamic is not None and event.dynamic.mark:
                    metadata["dynamic"] = event.dynamic.mark

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

    # Center notes within the measure: shift all events right by half the
    # trailing space so that left and right margins are approximately equal.
    if layouts:
        beats = max(1, beats_per_measure)
        max_onset_frac = max(
            (ev.onset % beats) / beats for ev in layouts
        )
        tail_frac = 1.0 - max_onset_frac
        usable_w = max(20.0, width - rules.measure_lr_pad * 2)
        centering_dx = tail_frac * usable_w / 2.0
        if centering_dx > 0.5:
            layouts = [
                EventLayout(
                    event_id=ev.event_id,
                    onset=ev.onset,
                    duration=ev.duration,
                    x=ev.x + centering_dx,
                    y=ev.y,
                    metadata=dict(ev.metadata),
                )
                for ev in layouts
            ]

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
    events: list[EventLayout],
    *,
    from_width: float,
    to_x: float,
    to_width: float,
    left_inset: float = 0.0,
    y_offset: float = 0.0,
) -> list[EventLayout]:
    if from_width <= 0:
        return events
    usable_width = max(8.0, to_width - max(0.0, left_inset))
    scale = usable_width / from_width
    return [
        EventLayout(
            event_id=event.event_id,
            onset=event.onset,
            duration=event.duration,
            x=to_x + max(0.0, left_inset) + event.x * scale,
            y=event.y + y_offset,
            metadata=dict(event.metadata),
        )
        for event in events
    ]
