"""Tests for layout contracts and builders."""

from __future__ import annotations

from pathlib import Path

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.layout import canonical_to_page_layout, default_layout_rules
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
    assert page_layout.height > default_layout_rules().page_height
    for system in page_layout.systems:
        total_w = sum(m.width for m in system.staves[0].measure_layouts)
        assert abs(total_w - system.width) < 1e-6
    system_ys = [system.y for system in page_layout.systems]
    assert system_ys == sorted(system_ys)


def test_canonical_to_page_layout_insets_first_measure_for_clef_and_time_signature() -> None:
    events: list[NoteEvent] = []
    for measure_idx in range(9):
        events.append(
            _note(
                pitch=64 + (measure_idx % 4),
                onset=float(measure_idx * 4),
                string_hint=2,
                fret_hint=measure_idx % 5,
            )
        )
    raw_score = legacy_parse_to_raw_score(
        Path("lead-inset-song.gp"),
        source_format="gpif",
        events=events,
    )
    canonical = completed_to_canonical_score(run_core_pipeline_from_raw(raw_score).completed_score)
    rules = default_layout_rules()
    page_layout = canonical_to_page_layout(canonical, rules=rules)

    for system in page_layout.systems:
        first_measure = system.staves[0].measure_layouts[0]
        assert first_measure.event_layouts
        first_event_x = min(event.x for event in first_measure.event_layouts)
        assert first_event_x >= first_measure.x + rules.system_leading_inset - 1.0


def test_canonical_to_page_layout_exports_engraving_parameters_in_metadata() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("meta-song.gp"),
        source_format="gpif",
        events=[_note(pitch=64, onset=0.0, string_hint=1, fret_hint=0)],
    )
    canonical = completed_to_canonical_score(run_core_pipeline_from_raw(raw_score).completed_score)
    rules = default_layout_rules()
    page_layout = canonical_to_page_layout(canonical, rules=rules)

    assert page_layout.metadata.get("standard_staff_spacing") == str(rules.standard_staff_spacing)
    assert page_layout.metadata.get("tab_staff_spacing") == str(rules.tab_staff_spacing)
    assert page_layout.metadata.get("standard_tab_gap") == str(rules.standard_tab_gap)
    assert page_layout.metadata.get("notehead_rx") == str(rules.notehead_rx)
    assert page_layout.metadata.get("rest_block_width") == str(rules.rest_block_width)


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
    assert note_texts[0].y != first_event.y
    assert note_texts[0].text == "5"


def test_layout_enforces_min_spacing_and_reports_collision_issues() -> None:
    # Two very close onsets in the same measure force spacing correction.
    raw_score = legacy_parse_to_raw_score(
        Path("dense.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.00, string_hint=1, fret_hint=0),
            _note(pitch=66, onset=0.05, string_hint=1, fret_hint=2),
            _note(pitch=67, onset=0.10, string_hint=1, fret_hint=3),
        ],
    )
    completed = run_core_pipeline_from_raw(raw_score).completed_score
    canonical = completed_to_canonical_score(completed)
    rules = default_layout_rules()
    page_layout = canonical_to_page_layout(canonical, rules=rules)

    measure = page_layout.systems[0].staves[0].measure_layouts[0]
    events = measure.event_layouts
    assert measure.collision_issues
    assert all(issue.code == "LAY-COLL-001" for issue in measure.collision_issues)

    # Events are ordered and spaced according to the active policy.
    for i in range(1, len(events)):
        assert events[i].x - events[i - 1].x >= rules.min_event_spacing - 1e-6


def test_layout_keeps_same_onset_events_aligned_for_chords() -> None:
    raw_score = legacy_parse_to_raw_score(
        Path("chord.gp"),
        source_format="gpif",
        events=[
            _note(pitch=64, onset=0.0, string_hint=1, fret_hint=0),
            _note(pitch=52, onset=0.0, string_hint=5, fret_hint=3),
            _note(pitch=66, onset=1.0, string_hint=1, fret_hint=2),
        ],
    )
    completed = run_core_pipeline_from_raw(raw_score).completed_score
    canonical = completed_to_canonical_score(completed)
    page_layout = canonical_to_page_layout(canonical)
    events = page_layout.systems[0].staves[0].measure_layouts[0].event_layouts

    onset_zero = [event for event in events if abs(event.onset) < 1e-9]
    assert len(onset_zero) == 2
    assert abs(onset_zero[0].x - onset_zero[1].x) < 1e-6
