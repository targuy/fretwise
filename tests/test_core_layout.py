"""Tests for layout contracts and builders."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.layout import canonical_to_page_layout
from fretwise.core.scene import layout_to_render_scene
from fretwise.models import Articulation, Dynamic, NoteEvent


def _note(
    *,
    pitch: int,
    onset: float,
    string_hint: int | None = None,
    fret_hint: int | None = None,
) -> NoteEvent:
    return NoteEvent(
        pitch=pitch,
        onset=onset,
        duration=1.0,
        tempo=120.0,
        articulation=Articulation.NORMAL,
        dynamic=Dynamic.MF,
        voice_hint=0,
        string_hint=string_hint,
        fret_hint=fret_hint,
    )


def test_canonical_to_page_layout_contract_has_page_system_staff_measure() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=1.0, string_hint=1, fret_hint=2),
            _note(pitch=67, onset=2.0, string_hint=2, fret_hint=8),
        ],
    )
    completed = run_core_pipeline_from_raw(raw_score).completed_score
    canonical = completed_to_canonical_score(completed)
    page_layout = canonical_to_page_layout(canonical)

    assert page_layout.page_number == 1
    assert page_layout.systems
    staff_layout = page_layout.systems[0].staves[0]
    assert staff_layout.measure_layouts
    measure = staff_layout.measure_layouts[0]
    assert measure.beats_per_measure == 4
    assert measure.event_layouts
    assert measure.event_layouts[0].event_id == "n0"


def test_canonical_to_page_layout_normalizes_measure_widths_per_system() -> None:
    events: list[NoteEvent] = []
    for measure_idx in range(12):
        events.append(
            _note(
                pitch=64 + (measure_idx % 5),
                onset=float(measure_idx * 4),
                string_hint=1,
                fret_hint=measure_idx % 7,
            )
        )
    raw_score = legacy_parse_to_raw_score(
        Path("long-song.gp"),
        source_format="gpif",
        events=events,
    )
    canonical = completed_to_canonical_score(run_core_pipeline_from_raw(raw_score).completed_score)
    page_layout = canonical_to_page_layout(canonical)

    assert len(page_layout.systems) >= 2
    for system in page_layout.systems:
        total_w = sum(m.width for m in system.staves[0].measure_layouts)
        assert abs(total_w - system.width) < 1e-6


def test_layout_to_render_scene_uses_layout_event_coordinates() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=2, fret_hint=5)],
    )
    completed = run_core_pipeline_from_raw(raw_score).completed_score
    canonical = completed_to_canonical_score(completed)
    page_layout = canonical_to_page_layout(canonical)
    scene = layout_to_render_scene(page_layout=page_layout, score=canonical)

    first_measure = page_layout.systems[0].staves[0].measure_layouts[0]
    first_event = first_measure.event_layouts[0]
    notes_layer = scene.document_scene.pages[0].systems[0].staves[0].layer_groups[1]
    note_texts = [t for t in notes_layer.text_instances if t.metadata.get("kind") == "note"]

    assert note_texts
    assert note_texts[0].x == first_event.x
    assert note_texts[0].y == first_event.y
    assert note_texts[0].text == "5"
