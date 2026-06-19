"""Verify tuplet bracket emission in tab_rhythm and standard_tab views."""
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from fretwise.parser.gpif_adapter import GpifAdapter
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.graphics import RepresentationMode

fp = Path('Red Hot Chili Peppers-Under The Bridge-10-26-2025.gp')
adapter = GpifAdapter()
events = adapter.parse(fp)
raw = legacy_parse_to_raw_score(
    fp,
    source_format='gpif',
    events=events,
    track_name=getattr(adapter, 'track_name', '') or '',
    beats_per_measure=float(getattr(adapter, 'beats_per_measure', 4.0) or 4.0),
    time_denominator=int(getattr(adapter, 'time_denominator', 4) or 4),
    has_anacrusis=bool(getattr(adapter, 'has_anacrusis', False)),
    section_markers=dict(getattr(adapter, 'section_markers', {}) or {}),
    chord_markers=dict(getattr(adapter, 'chord_markers', {}) or {}),
    chord_diagrams=list(getattr(adapter, 'chord_diagrams', []) or []),
)

for mode in (RepresentationMode.TAB_RHYTHM, RepresentationMode.STANDARD_TAB):
    result = run_core_pipeline_from_raw(raw, representation_mode=mode)
    scene = result.render_scene
    brackets = [
        ri
        for page in scene.document_scene.pages
        for system in page.systems
        for staff in system.staves
        for layer in staff.layer_groups
        for ri in layer.recipe_instances
        if ri.recipe_id == 'tuplet_bracket'
    ]
    print(f"[{mode.value}] Total tuplet_bracket instances: {len(brackets)}")
    for b in brackets[:8]:
        x0 = b.params['x0']
        x1 = b.params['x1']
        y  = b.params['y']
        n  = b.params['number']
        print(f"  x0={x0:.1f} x1={x1:.1f} y={y:.1f} n={n}")
