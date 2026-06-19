"""Diagnose TAB+Rhythm tuplet bracket emission vs tuplet events per measure."""
import sys
from pathlib import Path
sys.path.insert(0, 'src')

from fretwise.parser.gpif_adapter import GpifAdapter
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.graphics import RepresentationMode
from fretwise.core.normalize import normalize_raw_score
from fretwise.core.complete import complete_normalized_score
from fretwise.core.canonical import completed_to_canonical_score
from fretwise.core.layout.builders import canonical_to_page_layout

fp = Path('Red Hot Chili Peppers-Under The Bridge-10-26-2025.gp')
adapter = GpifAdapter()
events = adapter.parse(fp)
raw = legacy_parse_to_raw_score(
    fp, source_format='gpif', events=events,
    track_name=getattr(adapter, 'track_name', '') or '',
    beats_per_measure=float(getattr(adapter, 'beats_per_measure', 4.0) or 4.0),
    time_denominator=int(getattr(adapter, 'time_denominator', 4) or 4),
    has_anacrusis=bool(getattr(adapter, 'has_anacrusis', False)),
    section_markers=dict(getattr(adapter, 'section_markers', {}) or {}),
    chord_markers=dict(getattr(adapter, 'chord_markers', {}) or {}),
    chord_diagrams=list(getattr(adapter, 'chord_diagrams', []) or []),
)

norm = normalize_raw_score(raw)
comp = complete_normalized_score(norm)
canon = completed_to_canonical_score(comp)
page_layout = canonical_to_page_layout(canon)

# Collect per-measure tuplet event counts from layout
measures_with_tuplets: dict[int, list[float]] = {}
for system in page_layout.systems:
    for staff in system.staves:
        for ml in staff.measure_layouts:
            for ev in ml.event_layouts:
                ta = ev.metadata.get("tuplet_actual")
                tn = ev.metadata.get("tuplet_normal")
                if ta and tn and str(ta) != str(tn) and ev.metadata.get("event_type") != "RestEvent":
                    measures_with_tuplets.setdefault(ml.measure_number, []).append(ev.onset)

print(f"\nMeasures with tuplet events: {sorted(measures_with_tuplets.keys())}")
for m, onsets in sorted(measures_with_tuplets.items()):
    unique = sorted(set(round(o, 3) for o in onsets))
    print(f"  m{m}: {len(onsets)} events at onsets {unique}")

# Now get the TAB+Rhythm scene and count brackets per y-region (approx per system)
result = run_core_pipeline_from_raw(raw, representation_mode=RepresentationMode.TAB_RHYTHM)
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
print(f"\nTotal TAB+Rhythm tuplet_bracket instances: {len(brackets)}")
for b in brackets:
    print(f"  x0={b.params['x0']:.1f} x1={b.params['x1']:.1f} y={b.params['y']:.1f} n={b.params['number']} dir={b.params.get('direction','?')}")

# Also check beam groups for a specific measure
print("\n--- Beam group diagnostics for measures with tuplets ---")
from fretwise.core.scene.builders import _beam_groups, _notated_duration, _flag_count, _base_duration, _tuplet_bracket_runs, _collapse_tablature_rhythm_events
_REST_GAP_BREAK = 0.115

for system in page_layout.systems:
    for staff in system.staves:
        for ml in staff.measure_layouts:
            if ml.measure_number not in measures_with_tuplets:
                continue
            # Build tuplet_by_onset
            tuplet_by_onset = {}
            for ev in ml.event_layouts:
                if ev.metadata.get("event_type") == "RestEvent":
                    continue
                ta = ev.metadata.get("tuplet_actual")
                tn = ev.metadata.get("tuplet_normal")
                if ta and tn and str(ta) != str(tn):
                    try:
                        tuplet_by_onset[round(ev.onset, 6)] = (int(ta), int(tn))
                    except Exception:
                        pass
            # Build tab rhythm events (simplified, duration only)
            short_stems = []
            for ev in sorted(ml.event_layouts, key=lambda e: e.onset):
                if ev.metadata.get("event_type") == "RestEvent":
                    continue
                onset = ev.onset
                duration = ev.duration
                tup = tuplet_by_onset.get(round(onset, 6))
                ndur = _notated_duration(duration, tup[0] if tup else None, tup[1] if tup else None)
                base_dur = _base_duration(ndur)
                if base_dur < 1.0:
                    already = any(abs(s[1] - onset) < 1e-6 for s in short_stems)
                    if not already:
                        short_stems.append((0.0, onset, duration, _flag_count(ndur)))
            if not short_stems:
                continue
            grps = _beam_groups(
                [(x, o, d) for x, o, d, _ in short_stems],
                beats_per_measure=ml.beats_per_measure,
                measure_number=ml.measure_number,
                time_denominator=ml.time_denominator,
            )
            print(f"\nMeasure {ml.measure_number}: {len(grps)} beam groups, tuplet_by_onset keys={list(tuplet_by_onset.keys())}")
            for gi, grp in enumerate(grps):
                onsets_in_grp = [round(o, 4) for _, o, _ in grp]
                runs = _tuplet_bracket_runs(grp, tuplet_by_onset)
                print(f"  group {gi}: onsets={onsets_in_grp} → {len(runs)} bracket run(s): {runs}")
