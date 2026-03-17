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
                if has_standard:
                    event_type = event_layout.metadata.get("event_type")
                    if event_type == "RestEvent":
                        _append_rest_glyph(
                            notes_layer,
                            x=event_layout.x,
                            event_id=event_layout.event_id,
                        )
                    else:
                        notes_layer.glyph_instances.append(
                            GlyphInstance(
                                glyph_id="notehead",
                                x=event_layout.x,
                                y=_standard_note_y(event_layout.metadata),
                                size=3.0,
                                metadata={"event_id": event_layout.event_id},
                            )
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
                                    notes_layer.glyph_instances.append(
                                        GlyphInstance(
                                            glyph_id="notehead",
                                            x=measure_x + (event.onset % 4.0) * 36.0 + 28.0,
                                            y=_standard_note_y(
                                                {"pitch_notated": str(event.pitch_notated)}
                                            ),
                                            size=3.0,
                                            metadata={"event_id": event.event_id},
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
