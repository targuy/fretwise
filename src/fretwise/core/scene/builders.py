"""Scene builders from canonical semantic model."""

from __future__ import annotations

from fretwise.core.canonical import NoteEvent as CanonicalNoteEvent
from fretwise.core.canonical import RestEvent as CanonicalRestEvent
from fretwise.core.canonical import Score
from fretwise.core.layout import PageLayout, canonical_to_page_layout
from fretwise.core.scene.models import (
    DocumentScene,
    GlyphInstance,
    LayerGroup,
    PageScene,
    RecipeInstance,
    RenderScene,
    StaffScene,
    SystemScene,
    TextInstance,
)

_PAGE_W = 1200.0
_PAGE_H = 380.0
_MARGIN_X = 60.0
_MARGIN_Y = 40.0
_STAFF_W = 1080.0
_STAFF_H = 240.0
_TAB_Y = _MARGIN_Y + 60.0
_TAB_SPACING = 18.0
_STAFF_STD_Y = _MARGIN_Y - 8.0
_STAFF_STD_SPACING = 12.0
_STANDARD_STEM_TOP_Y = _STAFF_STD_Y - 10.0
_REST_GAP_BREAK = 0.115
_TAB_SPAN_PAD = 6.0
_ARC_ONSET_TOLERANCE = 0.06
_SLUR_TECHNIQUES = frozenset({"legato", "hammer_on", "pull_off", "slide"})
_MODES_WITH_TAB = {"tablature", "tablature_rhythm", "standard_tablature"}
_MODES_WITH_STANDARD = {"standard", "standard_tablature"}


def canonical_to_render_scene(score: Score, *, mode: str = "tablature") -> RenderScene:
    """Build a scene representation from canonical score through layout."""
    page_layout = canonical_to_page_layout(score)
    return layout_to_render_scene(page_layout=page_layout, score=score, mode=mode)


def layout_to_render_scene(
    *, page_layout: PageLayout, score: Score, mode: str = "tablature"
) -> RenderScene:
    """Build render scene from explicit page layout contract."""
    has_tab = mode in _MODES_WITH_TAB
    has_standard = mode in _MODES_WITH_STANDARD

    staff_layer = LayerGroup(layer_id="staff")
    notes_layer = LayerGroup(layer_id="notes")
    time_num, time_den = _score_time_signature(score)

    staff_layer.glyph_instances.append(
        GlyphInstance(
            glyph_id="time_signature",
            x=_MARGIN_X + 30.0,
            y=_STAFF_STD_Y + 2.0 * _STAFF_STD_SPACING,
            size=12.0,
            metadata={"numerator": time_num, "denominator": time_den},
        )
    )
    if has_standard:
        staff_layer.glyph_instances.append(
            GlyphInstance(
                glyph_id="clef",
                x=_MARGIN_X + 10.0,
                y=_STAFF_STD_Y + 2.0 * _STAFF_STD_SPACING,
                size=14.0,
                metadata={"clef": "treble"},
            )
        )

    if has_standard:
        staff_layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="staff_lines",
                params={
                    "x": _MARGIN_X,
                    "y": _STAFF_STD_Y,
                    "width": _STAFF_W,
                    "count": 5,
                    "spacing": _STAFF_STD_SPACING,
                },
            )
        )
    if has_tab:
        staff_layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="tab_lines",
                params={
                    "x": _MARGIN_X,
                    "y": _TAB_Y,
                    "width": _STAFF_W,
                    "count": 6,
                    "spacing": _TAB_SPACING,
                },
            )
        )

    if page_layout.systems and page_layout.systems[0].staves:
        first_staff_layout = page_layout.systems[0].staves[0]
        for measure_layout in first_staff_layout.measure_layouts:
            standard_rhythm_events: list[tuple[float, float, float, float]] = []
            standard_connection_events: list[dict[str, object]] = []
            tab_span_events: list[dict[str, object]] = []
            # Measure marker.
            notes_layer.text_instances.append(
                TextInstance(
                    text=str(measure_layout.measure_number),
                    x=measure_layout.x + 2.0,
                    y=_MARGIN_Y + 36.0,
                    font_size=8.0,
                    metadata={"kind": "measure_number"},
                )
            )
            for event_layout in measure_layout.event_layouts:
                if has_tab:
                    text = event_layout.metadata.get("tab_fret") or event_layout.metadata.get(
                        "pitch_notated", "0"
                    )
                    notes_layer.text_instances.append(
                        TextInstance(
                            text=str(text),
                            x=event_layout.x,
                            y=event_layout.y,
                            font_size=11.0,
                            metadata={
                                "kind": "note",
                                "event_id": event_layout.event_id,
                                "tab_string": event_layout.metadata.get("tab_string", "3"),
                            },
                        )
                    )
                    techniques = _parse_techniques(event_layout.metadata.get("techniques"))
                    tab_span_events.append(
                        {
                            "event_id": event_layout.event_id,
                            "x": event_layout.x,
                            "y": event_layout.y,
                            "onset": event_layout.onset,
                            "tab_string": _safe_int(event_layout.metadata.get("tab_string")) or 3,
                            "techniques": techniques,
                        }
                    )
                if has_standard:
                    event_type = event_layout.metadata.get("event_type")
                    if event_type == "RestEvent":
                        _append_rest_glyph(
                            notes_layer,
                            x=event_layout.x,
                            event_id=event_layout.event_id,
                        )
                    else:
                        note_y = _standard_note_y(event_layout.metadata)
                        techniques = _parse_techniques(event_layout.metadata.get("techniques"))
                        pitch = _safe_int(event_layout.metadata.get("pitch_notated")) or 64
                        accidental = _accidental_glyph_for_pitch(pitch)
                        if accidental is not None:
                            notes_layer.glyph_instances.append(
                                GlyphInstance(
                                    glyph_id=accidental,
                                    x=event_layout.x - 9.0,
                                    y=note_y + 0.5,
                                    size=9.0,
                                    metadata={"event_id": event_layout.event_id},
                                )
                            )
                        notes_layer.glyph_instances.append(
                            GlyphInstance(
                                glyph_id="notehead",
                                x=event_layout.x,
                                y=note_y,
                                size=3.0,
                                metadata={"event_id": event_layout.event_id},
                            )
                        )
                        standard_rhythm_events.append(
                            (event_layout.x, event_layout.onset, event_layout.duration, note_y)
                        )
                        standard_connection_events.append(
                            {
                                "event_id": event_layout.event_id,
                                "x": event_layout.x,
                                "y": note_y,
                                "onset": event_layout.onset,
                                "duration": event_layout.duration,
                                "pitch": pitch,
                                "techniques": techniques,
                            }
                        )
            if has_standard and standard_rhythm_events:
                _append_standard_rhythm(
                    notes_layer,
                    measure_number=measure_layout.measure_number,
                    beats_per_measure=measure_layout.beats_per_measure,
                    events=standard_rhythm_events,
                )
            if has_standard and standard_connection_events:
                _append_standard_connections(notes_layer, standard_connection_events)
            if has_tab and tab_span_events:
                _append_tab_technique_spans(
                    notes_layer,
                    measure_x=measure_layout.x,
                    measure_width=measure_layout.width,
                    events=tab_span_events,
                )
    else:
        # Fallback path for empty/unplaced layouts.
        if score.tracks:
            first_track = score.tracks[0]
            if first_track.staff_groups and first_track.staff_groups[0].staves:
                staff = first_track.staff_groups[0].staves[0]
                for measure in staff.measures:
                    measure_x = _MARGIN_X + (measure.number - 1) * 160.0
                    notes_layer.text_instances.append(
                        TextInstance(
                            text=str(measure.number),
                            x=measure_x + 2.0,
                            y=_MARGIN_Y + 36.0,
                            font_size=8.0,
                            metadata={"kind": "measure_number"},
                        )
                    )
                    for voice in measure.voices:
                        for event in voice.events:
                            if isinstance(event, CanonicalNoteEvent):
                                if has_tab:
                                    _append_note_text(notes_layer, event, measure_x)
                                if has_standard:
                                    note_x = measure_x + (event.onset % 4.0) * 36.0 + 28.0
                                    note_y = _standard_note_y(
                                        {"pitch_notated": str(event.pitch_notated)}
                                    )
                                    accidental = _accidental_glyph_for_pitch(event.pitch_notated)
                                    if accidental is not None:
                                        notes_layer.glyph_instances.append(
                                            GlyphInstance(
                                                glyph_id=accidental,
                                                x=note_x - 9.0,
                                                y=note_y + 0.5,
                                                size=9.0,
                                                metadata={"event_id": event.event_id},
                                            )
                                        )
                                    notes_layer.glyph_instances.append(
                                        GlyphInstance(
                                            glyph_id="notehead",
                                            x=note_x,
                                            y=note_y,
                                            size=3.0,
                                            metadata={"event_id": event.event_id},
                                        )
                                    )
                                    if _base_duration(event.duration) < 4.0:
                                        notes_layer.recipe_instances.append(
                                            RecipeInstance(
                                                recipe_id="stem_line",
                                                params={
                                                    "x": note_x,
                                                    "y0": _standard_note_y(
                                                        {"pitch_notated": str(event.pitch_notated)}
                                                    )
                                                    - 3.0,
                                                    "y1": _STANDARD_STEM_TOP_Y,
                                                    "width": 0.8,
                                                },
                                            )
                                        )
                            elif isinstance(event, CanonicalRestEvent) and has_standard:
                                _append_rest_glyph(
                                    notes_layer,
                                    x=measure_x + (event.onset % 4.0) * 36.0 + 28.0,
                                    event_id=event.event_id,
                                )

    staff_scene = StaffScene(
        staff_id="staff-1",
        x=_MARGIN_X,
        y=_MARGIN_Y,
        width=_STAFF_W,
        height=_STAFF_H,
        layer_groups=[staff_layer, notes_layer],
    )
    system_scene = SystemScene(
        system_id="system-1",
        x=_MARGIN_X,
        y=_MARGIN_Y,
        width=_STAFF_W,
        height=_STAFF_H,
        staves=[staff_scene],
    )
    page_scene = PageScene(
        page_number=1,
        width=_PAGE_W,
        height=_PAGE_H,
        systems=[system_scene],
    )
    document_scene = DocumentScene(title=score.title, pages=[page_scene])
    return RenderScene(document_scene=document_scene)


def _append_note_text(layer: LayerGroup, event: CanonicalNoteEvent, measure_x: float) -> None:
    column_x = measure_x + (event.onset % 4.0) * 36.0 + 28.0
    if event.tab_info is not None and event.tab_info.string is not None:
        string_num = max(1, min(6, event.tab_info.string))
    else:
        string_num = 3
    y = _MARGIN_Y + 60.0 + (string_num - 1) * 18.0 + 4.0

    text = str(event.pitch_notated)
    if event.tab_info is not None and event.tab_info.fret is not None:
        text = str(event.tab_info.fret)

    layer.text_instances.append(
        TextInstance(
            text=text,
            x=column_x,
            y=y,
            font_size=11.0,
            metadata={
                "kind": "note",
                "event_id": event.event_id,
                "tab_string": str(string_num),
            },
        )
    )


def _standard_note_y(metadata: dict[str, str]) -> float:
    pitch_raw = metadata.get("pitch_notated", "64")
    try:
        pitch = int(pitch_raw)
    except ValueError:
        pitch = 64

    # Simple linear projection for a proof-of-contract staff placement.
    y = _STAFF_STD_Y + 4 * _STAFF_STD_SPACING - (pitch - 64) * 2.0
    low = _STAFF_STD_Y - 12.0
    high = _STAFF_STD_Y + 4 * _STAFF_STD_SPACING + 12.0
    return max(low, min(high, y))


def _append_rest_glyph(layer: LayerGroup, *, x: float, event_id: str) -> None:
    layer.glyph_instances.append(
        GlyphInstance(
            glyph_id="rest",
            x=x,
            y=_STAFF_STD_Y + 2.0 * _STAFF_STD_SPACING,
            size=11.0,
            metadata={"event_id": event_id},
        )
    )


def _score_time_signature(score: Score) -> tuple[int, int]:
    for track in score.tracks:
        for staff_group in track.staff_groups:
            for staff in staff_group.staves:
                for measure in staff.measures:
                    return measure.time_signature.numerator, measure.time_signature.denominator
    return 4, 4


def _append_standard_rhythm(
    layer: LayerGroup,
    *,
    measure_number: int,
    beats_per_measure: int,
    events: list[tuple[float, float, float, float]],
) -> None:
    short_stems: list[tuple[float, float, float, int]] = []
    for x, onset, duration, note_y in sorted(events, key=lambda item: item[1]):
        base_dur = _base_duration(duration)
        if base_dur >= 4.0:
            continue
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="stem_line",
                params={
                    "x": x,
                    "y0": note_y - 3.0,
                    "y1": _STANDARD_STEM_TOP_Y,
                    "width": 0.8,
                },
                metadata={"onset": onset, "duration": duration},
            )
        )
        if base_dur < 1.0:
            short_stems.append((x, onset, duration, _flag_count(duration)))

    beam_groups = _beam_groups(
        [(x, onset, duration) for x, onset, duration, _flag_count_ in short_stems],
        beats_per_measure=beats_per_measure,
        measure_number=measure_number,
    )
    beamed_onsets = {onset for group in beam_groups for _x, onset, _duration in group}
    for x, onset, _duration, flag_count in short_stems:
        if onset in beamed_onsets or flag_count <= 0:
            continue
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="flag_stack",
                params={
                    "x": x,
                    "y": _STANDARD_STEM_TOP_Y,
                    "count": flag_count,
                    "spacing": 4.0,
                },
                metadata={"onset": onset},
            )
        )

    for group in beam_groups:
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="beam_group",
                params={
                    "x0": group[0][0],
                    "x1": group[-1][0],
                    "y": _STANDARD_STEM_TOP_Y,
                    "level": 1,
                    "thickness": 2.5,
                },
            )
        )


def _beam_groups(
    stems: list[tuple[float, float, float]],
    *,
    beats_per_measure: int,
    measure_number: int,
) -> list[list[tuple[float, float, float]]]:
    if len(stems) < 2:
        return []

    measure_onset = max(0.0, (measure_number - 1) * beats_per_measure)
    beat_boundaries = frozenset(
        round(measure_onset + step, 9)
        for step in range(1, max(1, beats_per_measure))
    )

    groups: list[list[tuple[float, float, float]]] = []
    current: list[tuple[float, float, float]] = []
    for x, onset, duration in stems:
        if not current:
            current.append((x, onset, duration))
            continue
        _prev_x, prev_onset, prev_duration = current[-1]
        prev_end = prev_onset + prev_duration
        has_rest_gap = (onset - prev_end) >= _REST_GAP_BREAK
        crosses_beat = any(prev_onset < bb <= onset for bb in beat_boundaries)
        if has_rest_gap or crosses_beat:
            if len(current) >= 2:
                groups.append(current)
            current = [(x, onset, duration)]
            continue
        current.append((x, onset, duration))

    if len(current) >= 2:
        groups.append(current)
    return groups


def _base_duration(duration: float) -> float:
    dotted_bases = (8.0, 4.0, 2.0, 1.0, 0.5, 0.25, 0.125)
    for base in dotted_bases:
        if abs(duration - base * 1.5) < 0.01:
            return base
    return duration


def _flag_count(duration: float) -> int:
    base = _base_duration(duration)
    if base >= 1.0:
        return 0
    if base >= 0.5:
        return 1
    if base >= 0.25:
        return 2
    return 3


def _append_tab_technique_spans(
    layer: LayerGroup,
    *,
    measure_x: float,
    measure_width: float,
    events: list[dict[str, object]],
) -> None:
    by_string: dict[int, list[dict[str, object]]] = {}
    for event in events:
        string_num = int(event.get("tab_string", 3))
        by_string.setdefault(string_num, []).append(event)

    for string_num, notes in by_string.items():
        notes_sorted = sorted(notes, key=lambda item: float(item.get("onset", 0.0)))
        for idx, event in enumerate(notes_sorted):
            techs = set(event.get("techniques", set()))
            if not techs.intersection({"let_ring", "palm_mute"}):
                continue

            x = float(event.get("x", 0.0))
            y = float(event.get("y", 0.0))
            x0 = x + _TAB_SPAN_PAD
            next_x = (
                float(notes_sorted[idx + 1].get("x", x))
                if idx + 1 < len(notes_sorted)
                else measure_x + measure_width - 4.0
            )
            x1 = min(measure_x + measure_width - 4.0, next_x - _TAB_SPAN_PAD)
            if x1 <= x0 + 1.0:
                continue

            if "let_ring" in techs:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="let_ring_span",
                        params={"x0": x0, "x1": x1, "y": y - 8.0, "dash": "2,2"},
                        metadata={
                            "string": str(string_num),
                            "event_id": str(event.get("event_id")),
                        },
                    )
                )
            if "palm_mute" in techs:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="palm_mute_span",
                        params={"x0": x0, "x1": x1, "y": y - 14.0, "label": "P.M.", "dash": "3,2"},
                        metadata={
                            "string": str(string_num),
                            "event_id": str(event.get("event_id")),
                        },
                    )
                )


def _append_standard_connections(
    layer: LayerGroup,
    events: list[dict[str, object]],
) -> None:
    if len(events) < 2:
        return

    ordered = sorted(events, key=lambda item: float(item.get("onset", 0.0)))
    for prev, curr in zip(ordered, ordered[1:]):
        prev_onset = float(prev.get("onset", 0.0))
        prev_duration = float(prev.get("duration", 0.0))
        curr_onset = float(curr.get("onset", 0.0))
        expected_next = prev_onset + prev_duration
        contiguous = abs(expected_next - curr_onset) <= _ARC_ONSET_TOLERANCE
        if not contiguous:
            continue

        prev_pitch = int(prev.get("pitch", 64))
        curr_pitch = int(curr.get("pitch", 64))
        prev_techniques = set(prev.get("techniques", set()))
        arc_x0 = float(prev.get("x", 0.0)) + 3.0
        arc_x1 = float(curr.get("x", 0.0)) - 3.0
        if arc_x1 <= arc_x0 + 1.0:
            continue
        arc_y0 = float(prev.get("y", 0.0)) + 4.0
        arc_y1 = float(curr.get("y", 0.0)) + 4.0

        if prev_pitch == curr_pitch:
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="tie_arc",
                    params={
                        "x0": arc_x0,
                        "y0": arc_y0,
                        "x1": arc_x1,
                        "y1": arc_y1,
                        "curvature": 8.0,
                    },
                    metadata={
                        "start_event_id": str(prev.get("event_id")),
                        "end_event_id": str(curr.get("event_id")),
                    },
                )
            )
            continue

        if prev_techniques.intersection(_SLUR_TECHNIQUES):
            layer.recipe_instances.append(
                RecipeInstance(
                    recipe_id="slur_arc",
                    params={
                        "x0": arc_x0,
                        "y0": arc_y0,
                        "x1": arc_x1,
                        "y1": arc_y1,
                        "curvature": 10.0,
                    },
                    metadata={
                        "start_event_id": str(prev.get("event_id")),
                        "end_event_id": str(curr.get("event_id")),
                    },
                )
            )


def _parse_techniques(value: str | None) -> set[str]:
    if not value:
        return set()
    return {item.strip() for item in value.split(",") if item.strip()}


def _safe_int(value: str | None) -> int | None:
    try:
        return int(value) if value is not None else None
    except ValueError:
        return None


def _accidental_glyph_for_pitch(pitch: int) -> str | None:
    pitch_class = pitch % 12
    if pitch_class in {1, 6}:
        return "accidental_sharp"
    if pitch_class in {3, 8, 10}:
        return "accidental_flat"
    return None
