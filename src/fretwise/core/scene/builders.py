"""Scene builders from canonical semantic model."""

from __future__ import annotations

from fretwise.core.canonical import NoteEvent as CanonicalNoteEvent
from fretwise.core.canonical import Score
from fretwise.core.layout import PageLayout, canonical_to_page_layout
from fretwise.core.scene.models import (
    DocumentScene,
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


def canonical_to_render_scene(score: Score) -> RenderScene:
    """Build a scene representation from canonical score through layout."""
    page_layout = canonical_to_page_layout(score)
    return layout_to_render_scene(page_layout=page_layout, score=score)


def layout_to_render_scene(*, page_layout: PageLayout, score: Score) -> RenderScene:
    """Build render scene from explicit page layout contract."""
    staff_layer = LayerGroup(layer_id="staff")
    notes_layer = LayerGroup(layer_id="notes")

    # Add baseline tab lines recipe.
    staff_layer.recipe_instances.append(
        RecipeInstance(
            recipe_id="tab_lines",
            params={
                "x": _MARGIN_X,
                "y": _MARGIN_Y + 60.0,
                "width": _STAFF_W,
                "count": 6,
                "spacing": 18.0,
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
                text = event_layout.metadata.get("tab_fret") or event_layout.metadata.get(
                    "pitch_notated", "0"
                )
                notes_layer.text_instances.append(
                    TextInstance(
                        text=str(text),
                        x=event_layout.x,
                        y=event_layout.y,
                        font_size=11.0,
                        metadata={"kind": "note", "event_id": event_layout.event_id},
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
                                _append_note_text(notes_layer, event, measure_x)

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
            metadata={"kind": "note", "event_id": event.event_id},
        )
    )
