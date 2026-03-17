"""Layout builders from canonical semantic model."""

from __future__ import annotations

from dataclasses import dataclass

from fretwise.core.canonical import NoteEvent as CanonicalNoteEvent
from fretwise.core.canonical import Score
from fretwise.core.layout.models import (
    EventLayout,
    MeasureLayout,
    PageLayout,
    StaffLayout,
    SystemLayout,
)

_PAGE_W = 1200.0
_PAGE_H = 380.0
_MARGIN_X = 60.0
_MARGIN_Y = 40.0
_CONTENT_W = 1080.0
_SYSTEM_H = 240.0
_STAFF_H = 240.0
_MEASURE_MIN_W = 120.0
_MEASURE_MAX_W = 240.0
_MEASURE_LR_PAD = 20.0
_ROW_TOP = _MARGIN_Y + 60.0
_ROW_SPACING = 18.0


@dataclass(frozen=True)
class _MeasurePack:
    number: int
    beats: int
    raw_width: float
    event_layouts: list[EventLayout]


def canonical_to_page_layout(score: Score) -> PageLayout:
    """Build the first-page layout contract from a canonical score."""
    systems: list[SystemLayout] = []
    packs = _measure_packs(score)
    if not packs:
        return PageLayout(
            page_number=1,
            width=_PAGE_W,
            height=_PAGE_H,
            systems=[],
            metadata={"title": score.title},
        )

    system_chunks = _chunk_measures_into_systems(packs, _CONTENT_W)
    for system_index, chunk in enumerate(system_chunks, start=1):
        total_raw = sum(pack.raw_width for pack in chunk)
        scale = _CONTENT_W / total_raw if total_raw > 0 else 1.0

        cursor_x = _MARGIN_X
        measure_layouts: list[MeasureLayout] = []
        for pack in chunk:
            width = pack.raw_width * scale
            measure_layouts.append(
                MeasureLayout(
                    measure_number=pack.number,
                    x=cursor_x,
                    y=_MARGIN_Y,
                    width=width,
                    height=_STAFF_H,
                    beats_per_measure=pack.beats,
                    event_layouts=_remap_event_x(
                        pack.event_layouts,
                        from_width=pack.raw_width,
                        to_x=cursor_x,
                        to_width=width,
                    ),
                )
            )
            cursor_x += width

        staff = StaffLayout(
            staff_id=f"staff-{system_index}",
            x=_MARGIN_X,
            y=_MARGIN_Y,
            width=_CONTENT_W,
            height=_STAFF_H,
            measure_layouts=measure_layouts,
        )
        systems.append(
            SystemLayout(
                system_id=f"system-{system_index}",
                x=_MARGIN_X,
                y=_MARGIN_Y,
                width=_CONTENT_W,
                height=_SYSTEM_H,
                staves=[staff],
            )
        )

    return PageLayout(
        page_number=1,
        width=_PAGE_W,
        height=_PAGE_H,
        systems=systems,
        metadata={"title": score.title},
    )


def _measure_packs(score: Score) -> list[_MeasurePack]:
    if not score.tracks:
        return []
    track = score.tracks[0]
    if not track.staff_groups or not track.staff_groups[0].staves:
        return []
    staff = track.staff_groups[0].staves[0]

    packs: list[_MeasurePack] = []
    for measure in staff.measures:
        beats = max(1, measure.time_signature.numerator)
        events = _measure_event_layouts(measure.number, beats, measure.voices)
        unique_onsets = len({e.onset for e in events})
        raw_width = min(
            _MEASURE_MAX_W,
            max(_MEASURE_MIN_W, _MEASURE_LR_PAD * 2 + unique_onsets * 40.0),
        )
        packs.append(
            _MeasurePack(
                number=measure.number,
                beats=beats,
                raw_width=raw_width,
                event_layouts=events,
            )
        )
    return packs


def _measure_event_layouts(
    measure_number: int,
    beats_per_measure: int,
    voices: list[object],
) -> list[EventLayout]:
    del measure_number
    layouts: list[EventLayout] = []
    usable_w = max(20.0, _MEASURE_MIN_W - _MEASURE_LR_PAD * 2)

    for voice in voices:
        events = getattr(voice, "events", [])
        for event in events:
            rel_onset = event.onset % beats_per_measure
            frac = rel_onset / beats_per_measure
            x = _MEASURE_LR_PAD + frac * usable_w
            y = _ROW_TOP + 2 * _ROW_SPACING
            metadata: dict[str, str] = {"event_type": event.__class__.__name__}
            if isinstance(event, CanonicalNoteEvent):
                string_num = 3
                if event.tab_info is not None and event.tab_info.string is not None:
                    string_num = max(1, min(6, event.tab_info.string))
                y = _ROW_TOP + (string_num - 1) * _ROW_SPACING + 4.0
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

    layouts.sort(key=lambda layout: (layout.onset, layout.event_id))
    return layouts


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

