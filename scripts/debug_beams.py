"""Diagnostic: capture actual stem direction events for Rising Sun."""

import sys
sys.path.insert(0, "src")

from pathlib import Path
from fretwise.parser.gpif_adapter import GpifAdapter
from fretwise.core.ingest.adapters import legacy_parse_to_raw_score
from fretwise.core.pipeline import run_core_pipeline_from_raw
from fretwise.core.graphics import RepresentationMode

import fretwise.core.scene.builders as bld

_orig_rhythm = bld._append_standard_rhythm
_captured: list[dict] = []


def _patched_rhythm(
    layer,
    *,
    measure_number,
    beats_per_measure,
    time_denominator,
    events,
    stem_top_y,
    stem_bottom_y,
    staff_spacing,
    stem_offset,
):
    if measure_number <= 8:
        _captured.append(
            {
                "mnum": measure_number,
                "stem_top_y": stem_top_y,
                "stem_bottom_y": stem_bottom_y,
                "staff_spacing": staff_spacing,
                "events": [
                    (round(x, 1), round(onset, 2), round(dur, 3), round(ny, 1), d)
                    for x, onset, dur, ny, d in events
                ],
            }
        )
    return _orig_rhythm(
        layer,
        measure_number=measure_number,
        beats_per_measure=beats_per_measure,
        time_denominator=time_denominator,
        events=events,
        stem_top_y=stem_top_y,
        stem_bottom_y=stem_bottom_y,
        staff_spacing=staff_spacing,
        stem_offset=stem_offset,
    )


bld._append_standard_rhythm = _patched_rhythm

adapter = GpifAdapter()
events = adapter.parse(
    Path("The Animals-The House Of The Rising Sun-12-25-2025.gp")
)
raw_score = legacy_parse_to_raw_score(
    Path("The Animals-The House Of The Rising Sun-12-25-2025.gp"),
    source_format="gp",
    events=events,
    track_name=adapter.track_name,
    beats_per_measure=float(adapter.beats_per_measure),
    time_denominator=adapter.time_denominator,
    has_anacrusis=adapter.has_anacrusis,
    section_markers=adapter.section_markers,
    chord_markers=adapter.chord_markers,
    chord_diagrams=adapter.chord_diagrams,
)
result = run_core_pipeline_from_raw(
    raw_score, representation_mode=RepresentationMode.STANDARD_TAB
)

for c in _captured:
    mnum = c["mnum"]
    dirs = set(d for _, _, _, _, d in c["events"])
    print(
        f"M{mnum}: top={c['stem_top_y']:.0f} bot={c['stem_bottom_y']:.0f} "
        f"sp={c['staff_spacing']:.0f} dirs={dirs} n_events={len(c['events'])}"
    )
    for x, onset, dur, ny, d in c["events"]:
        print(f"  onset={onset:6.2f} dur={dur:.3f} note_y={ny:6.1f} dir={d}")
    print()
