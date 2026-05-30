# Notation Rendering Fixes — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the three critical notation rendering gaps identified on *Killing in the Name*: tuplet brackets (83/~833 rendered), cross-measure slide lines (43/102), and harmonic noteheads (0/75).

**Architecture:** All fixes live in the `src/fretwise/core/` pipeline. The scene builder (`builders.py`) drives note rendering; it feeds `LayerGroup` objects consumed by the SVG backend. Cross-measure spans follow the established `standard_connection_events` pattern already in the codebase.

**Tech Stack:** Python 3.11, `src/fretwise/core/scene/builders.py`, `src/fretwise/core/backends/svg.py`, `src/fretwise/core/graphics/reference_glyph_set.py`, `src/fretwise/core/graphics/parametric_recipes.py`, `tests/test_core_scene_svg.py`, pytest.

---

## File Map

| File | Change |
|------|--------|
| `tests/test_core_scene_svg.py` | Add 4 failing tests (tuplet bracket, cross-measure slide, harmonic notehead, standalone tuplet) |
| `src/fretwise/core/scene/builders.py` | (1) Fix `_append_tablature_rhythm` to emit brackets for standalone tuplet groups; (2) add `tab_slide_events` cross-measure accumulator + `_append_tab_slide_connections`; (3) use `notehead_harmonic` when "harmonic" in techniques |
| `src/fretwise/core/graphics/reference_glyph_set.py` | Add `notehead_harmonic` (diamond) glyph |
| `src/fretwise/core/backends/svg.py` | Render `notehead_harmonic` as a diamond shape |
| `src/fretwise/core/graphics/parametric_recipes.py` | Add `tab_slide_line` to the catalog (documentation, not functional) |

---

## Task 1 — Tuplet brackets: write failing test

**Files:**
- Test: `tests/test_core_scene_svg.py`

- [ ] **Step 1: Add a failing test for tuplet bracket in `tablature_rhythm` mode**

Add at the end of `tests/test_core_scene_svg.py`:

```python
def test_canonical_to_render_scene_tablature_rhythm_emits_tuplet_bracket() -> None:
    """Three triplet-8th notes in one beat must produce exactly one tuplet_bracket."""
    # 3 triplet 8ths = 1 beat (duration=1/3 each, tuplet_actual=3, tuplet_normal=2)
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=60, onset=0.0, duration=1/3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=0,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=62, onset=1/3, duration=1/3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=2,
                tuplet_actual=3, tuplet_normal=2,
            ),
            NoteEvent(
                pitch=64, onset=2/3, duration=1/3,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=4,
                tuplet_actual=3, tuplet_normal=2,
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("tablature_rhythm"),
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    recipe_ids = [r.recipe_id for lg in staff.layer_groups for r in lg.recipe_instances]
    tuplet_recipes = [r for lg in staff.layer_groups for r in lg.recipe_instances
                      if r.recipe_id == "tuplet_bracket"]

    assert "tuplet_bracket" in recipe_ids, "Expected at least one tuplet_bracket recipe"
    assert len(tuplet_recipes) == 1, f"Expected 1 bracket for 3 triplet notes, got {len(tuplet_recipes)}"
    bracket = tuplet_recipes[0]
    assert bracket.params["number"] == 3
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_tablature_rhythm_emits_tuplet_bracket -v
```

Expected: FAIL. Note the exact failure message — it tells you whether 0 or some non-1 count of brackets is produced.

- [ ] **Step 3: Add a diagnostic print to find where the bracket is lost**

Temporarily add a print in `src/fretwise/core/scene/builders.py` inside `_append_tablature_rhythm`, after the `beam_groups` computation:

```python
# TEMP DEBUG - remove after fix
if tuplet_by_onset:
    import sys
    print(f"[DEBUG] beam_groups={len(beam_groups)}, tuplet_by_onset keys={list(tuplet_by_onset.keys())[:5]}", file=sys.stderr)
    for grp in beam_groups:
        print(f"  group onsets={[round(s[1],4) for s in grp]}", file=sys.stderr)
```

Re-run the test. Expected: see whether beam_groups is empty (no groups formed) or groups are formed but brackets aren't emitted.

- [ ] **Step 4: Apply fix based on diagnostic**

**If `beam_groups` is empty** (most likely): the `short_stems` list is empty because `_flag_count(_ndur)` returns 0 for the notated duration. Check with:
```python
_ndur = _notated_duration(1/3, 3, 2)  # = 0.5
_flag_count(0.5)  # should return 1 (8th note = 1 flag)
```
If that's correct, check whether the `tuplet_by_onset` lookup uses a different rounding. Fix by ensuring the onset rounding in `_beam_groups` stem collection matches `tuplet_by_onset` keys (both use `round(onset, 6)`).

**If `beam_groups` is non-empty but bracket count is wrong**: the issue is in `_tuplet_bracket_runs`. The function requires `end_idx - run_start >= 2`. For a group of exactly 2 notes, it emits (2 - 0 = 2 ≥ 2). For 3 notes it should always emit. Add a standalone check:

```python
# After the _beam_groups / tuplet_bracket loop in _append_tablature_rhythm
# Add a standalone pass for any tuplet note that didn't get into a beam group:
if tuplet_by_onset:
    unbeamed_tuplet_stems = [
        (x, onset, dur)
        for x, onset, dur, _flags in short_stems
        if round(onset, 6) not in beamed_onsets
           and (tuplet_by_onset or {}).get(round(onset, 6)) is not None
    ]
    # Group consecutive unbeamed tuplet notes by same tuplet ratio
    _emit_standalone_tuplet_brackets(layer, unbeamed_tuplet_stems, tuplet_by_onset, tab_rhythm_beam_y)
```

And add `_emit_standalone_tuplet_brackets` (see Task 2 step 1).

- [ ] **Step 5: Remove the DEBUG print, re-run test**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_tablature_rhythm_emits_tuplet_bracket -v
```
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add tests/test_core_scene_svg.py src/fretwise/core/scene/builders.py
git commit -m "fix(scene): emit tuplet_bracket for all triplet groups in tablature_rhythm mode"
```

---

## Task 2 — Standalone tuplet bracket helper function

**Files:**
- Modify: `src/fretwise/core/scene/builders.py`

- [ ] **Step 1: Add `_emit_standalone_tuplet_brackets` function**

Add this function in `src/fretwise/core/scene/builders.py`, just above `_append_tab_technique_spans` (around line 2517):

```python
def _emit_standalone_tuplet_brackets(
    layer: LayerGroup,
    stems: list[tuple[float, float, float]],
    tuplet_by_onset: dict[float, tuple[int, int]],
    beam_y: float,
) -> None:
    """Emit tuplet_bracket recipes for unbeamed notes that belong to a tuplet group.

    Groups consecutive notes sharing the same (tuplet_actual, tuplet_normal) ratio
    into visual brackets.  Requires ≥ 2 consecutive same-ratio notes for a bracket.
    """
    if not stems or not tuplet_by_onset:
        return

    sorted_stems = sorted(stems, key=lambda s: s[1])  # sort by onset
    run_start: int | None = None
    run_tup: tuple[int, int] | None = None
    results: list[tuple[float, float, int]] = []

    def _flush(end_idx: int) -> None:
        nonlocal run_start, run_tup
        if run_start is not None and end_idx - run_start >= 2:
            results.append((
                sorted_stems[run_start][0],
                sorted_stems[end_idx - 1][0],
                run_tup[0],  # type: ignore[index]
            ))
        run_start = None
        run_tup = None

    for idx, (x, onset, _dur) in enumerate(sorted_stems):
        tup = tuplet_by_onset.get(round(onset, 6))
        if tup is not None:
            if tup == run_tup:
                pass  # extend current run
            else:
                _flush(idx)
                run_start = idx
                run_tup = tup
        else:
            _flush(idx)
    _flush(len(sorted_stems))

    for x0, x1, number in results:
        layer.recipe_instances.append(
            RecipeInstance(
                recipe_id="tuplet_bracket",
                params={
                    "x0": x0,
                    "x1": x1,
                    "y": beam_y + 8.0,
                    "number": number,
                    "direction": "down",
                    "style": "tablature_rhythm",
                },
                metadata={"plane": "tablature_rhythm", "style": "tablature_rhythm"},
            )
        )
```

- [ ] **Step 2: Run all existing tests to check no regression**

```
pytest tests/test_core_scene_svg.py -v
```

Expected: all existing tests PASS, new test PASS.

- [ ] **Step 3: Commit**

```bash
git add src/fretwise/core/scene/builders.py
git commit -m "feat(scene): add _emit_standalone_tuplet_brackets for unbeamed tuplet notes"
```

---

## Task 3 — Cross-measure slide rendering: write failing test

**Files:**
- Test: `tests/test_core_scene_svg.py`

- [ ] **Step 1: Add a failing test for cross-measure slide**

Add in `tests/test_core_scene_svg.py`:

```python
def test_canonical_to_render_scene_tab_slide_connects_across_measures() -> None:
    """A slide at the end of measure 1 must connect to the first note of measure 2."""
    # Measure 1: one slide note (whole note = 4 beats), Measure 2: one target note
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=57, onset=0.0, duration=1.0,
                tempo=120.0, articulation=Articulation.SLIDE, dynamic=Dynamic.MF,
                string_hint=4, fret_hint=7,
                slide_type="shift",
            ),
            NoteEvent(
                pitch=60, onset=4.0, duration=1.0,
                tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
                string_hint=4, fret_hint=10,
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("tablature_rhythm"),
    )
    # Count tab_slide_line recipes across all layer groups and staves
    slide_recipes = [
        r
        for p in result.render_scene.document_scene.pages
        for s in p.systems
        for st in s.staves
        for lg in st.layer_groups
        for r in lg.recipe_instances
        if r.recipe_id == "tab_slide_line"
    ]
    assert len(slide_recipes) == 1, (
        f"Expected 1 cross-measure slide line, got {len(slide_recipes)}"
    )
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_tab_slide_connects_across_measures -v
```

Expected: FAIL with "Expected 1 cross-measure slide line, got 0".

---

## Task 4 — Cross-measure slide rendering: implement fix

**Files:**
- Modify: `src/fretwise/core/scene/builders.py` (lines ~300-720)

`★ Insight ─────────────────────────────────────`
The tie/slur cross-measure fix is the template: `standard_connection_events` is a list accumulated across all measures, then `_append_standard_connections` is called ONCE after the measure loop. Slides need the same pattern.
`─────────────────────────────────────────────────`

- [ ] **Step 1: Add `tab_slide_events` accumulator outside the measure loop**

In `src/fretwise/core/scene/builders.py`, inside the staff processing loop (around line 300, where `standard_connection_events` is declared), add:

```python
# Slide events accumulated cross-measure, like standard_connection_events for ties.
tab_slide_events: list[dict[str, object]] = []
```

This goes right after line 304:
```python
standard_connection_events: list[dict[str, object]] = []
```

So the block becomes:
```python
standard_connection_events: list[dict[str, object]] = []
tab_slide_events: list[dict[str, object]] = []
for measure_index, measure_layout in enumerate(staff_layout.measure_layouts):
```

- [ ] **Step 2: Feed slide events into the cross-measure accumulator**

Inside the measure loop, in the `if has_tab and event_type != "RestEvent":` block (around line 446), where each event is appended to `tab_span_events`, add slide events to the NEW cross-measure list:

Find the block that populates `tab_span_events` (lines 446-457). After it, add:

```python
                        # Collect slide notes into cross-measure accumulator.
                        if "slide" in techniques:
                            tab_slide_events.append(
                                {
                                    "event_id": event_layout.event_id,
                                    "x": event_layout.x,
                                    "y": tab_note_y,
                                    "onset": event_layout.onset,
                                    "tab_string": _safe_int(event_layout.metadata.get("tab_string")) or 3,
                                    "fret_num": _safe_int(event_layout.metadata.get("tab_fret")) or 0,
                                }
                            )
```

- [ ] **Step 3: Remove slide handling from `_append_tab_technique_spans`**

In `_append_tab_technique_spans` (around line 2569-2591), remove the entire slide block:

```python
            # Slide diagonal lines
            if "slide" in techs and idx + 1 < len(notes_sorted):
                next_event = notes_sorted[idx + 1]
                sl_x0 = float(event.get("x", 0.0)) + 5.0
                sl_x1 = float(next_event.get("x", 0.0)) - 5.0
                ...
                if sl_x1 > sl_x0 + 2.0:
                    layer.recipe_instances.append(...)
```

Replace the entire block (lines 2569-2591) with a comment:
```python
            # Slides are handled cross-measure by _append_tab_slide_connections.
```

- [ ] **Step 4: Add `_append_tab_slide_connections` function**

Add this function in `builders.py`, just before `_append_tab_technique_spans`:

```python
def _append_tab_slide_connections(
    layer: LayerGroup,
    events: list[dict[str, object]],
) -> None:
    """Draw diagonal slide lines connecting slide source to next note on the same string.

    Works across measure boundaries by processing all events together, grouped by string.
    Each slide note connects to the next chronological note on the same string.
    """
    by_string: dict[int, list[dict[str, object]]] = {}
    for event in events:
        string_num = int(event.get("tab_string", 3))
        by_string.setdefault(string_num, []).append(event)

    for _string_num, string_events in by_string.items():
        # string_events contains ONLY slide notes; we need ALL notes on the same string
        # to find the next-note target. We'll use the onset to find the gap direction.
        sorted_events = sorted(string_events, key=lambda e: float(e.get("onset", 0.0)))
        for idx, event in enumerate(sorted_events):
            if idx + 1 >= len(sorted_events):
                continue
            next_event = sorted_events[idx + 1]
            sl_x0 = float(event.get("x", 0.0)) + 5.0
            sl_x1 = float(next_event.get("x", 0.0)) - 5.0
            sl_y_mid = float(event.get("y", 0.0))
            fret0 = int(event.get("fret_num", 0))
            fret1 = int(next_event.get("fret_num", 0))
            if fret1 > fret0:
                sl_y0, sl_y1 = sl_y_mid + 2.5, sl_y_mid - 2.5   # ascending: / shape
            elif fret1 < fret0:
                sl_y0, sl_y1 = sl_y_mid - 2.5, sl_y_mid + 2.5   # descending: \ shape
            else:
                sl_y0 = sl_y1 = sl_y_mid
            if sl_x1 > sl_x0 + 2.0:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="tab_slide_line",
                        params={"x0": sl_x0, "y0": sl_y0, "x1": sl_x1, "y1": sl_y1},
                        metadata={
                            "string": str(_string_num),
                            "event_id": str(event.get("event_id")),
                        },
                    )
                )
```

**Problem**: `_append_tab_slide_connections` only receives slide notes, not the TARGET notes (which are regular notes). To know the target's x position and fret, we need to look up the next event on that string across all events.

Revised approach — pass ALL tab events along with slide flags:

Change `tab_slide_events` to store ALL tab events (not just slide notes), and mark slides:

Instead of a separate `tab_slide_events` list, extend `tab_span_events` to be collected cross-measure. Add a boolean flag to each event dict: `"is_slide_source": True`. Then call `_append_tab_slide_connections(notes_layer, all_tab_events)` after all measures.

**Revised implementation:**

Replace Steps 1-3 with this cleaner approach:

**Step 1 (revised): Add `all_tab_span_events` accumulator** (outside measure loop):
```python
all_tab_span_events: list[dict[str, object]] = []
```

**Step 2 (revised): Feed ALL tab events into cross-measure list** — In the existing `tab_span_events.append(...)` block (line 446-457), ALSO append to `all_tab_span_events`:
```python
                        event_dict = {
                            "event_id": event_layout.event_id,
                            "x": event_layout.x,
                            "y": tab_note_y,
                            "onset": event_layout.onset,
                            "tab_string": _safe_int(event_layout.metadata.get("tab_string")) or 3,
                            "techniques": techniques,
                            "fret_num": _safe_int(event_layout.metadata.get("tab_fret")) or 0,
                        }
                        tab_span_events.append(event_dict)
                        all_tab_span_events.append(event_dict)
```

**Step 3 (revised): Remove slide handling from `_append_tab_technique_spans`** — replace the slide block with the comment (as above).

**Step 4 (revised): Call `_append_tab_slide_connections` after all measures** — Add after line 717 (after the tie/slur connection call):
```python
            if has_tab and all_tab_span_events:
                _append_tab_slide_connections(notes_layer, all_tab_span_events)
```

**Step 5 (revised): Implement `_append_tab_slide_connections` with ALL events**:

```python
def _append_tab_slide_connections(
    layer: LayerGroup,
    events: list[dict[str, object]],
) -> None:
    """Draw diagonal slide lines, connecting slide sources to next note on same string.

    Receives ALL tab events (slide and non-slide) to correctly find the next-note target.
    Groups by string and draws a diagonal for each slide source → next-note pair.
    """
    by_string: dict[int, list[dict[str, object]]] = {}
    for event in events:
        string_num = int(event.get("tab_string", 3))
        by_string.setdefault(string_num, []).append(event)

    for _string_num, string_events in by_string.items():
        sorted_events = sorted(string_events, key=lambda e: float(e.get("onset", 0.0)))
        for idx, event in enumerate(sorted_events):
            techs = set(event.get("techniques", set()))
            if "slide" not in techs:
                continue
            if idx + 1 >= len(sorted_events):
                continue
            next_event = sorted_events[idx + 1]
            sl_x0 = float(event.get("x", 0.0)) + 5.0
            sl_x1 = float(next_event.get("x", 0.0)) - 5.0
            sl_y_mid = float(event.get("y", 0.0))
            fret0 = int(event.get("fret_num", 0))
            fret1 = int(next_event.get("fret_num", 0))
            if fret1 > fret0:
                sl_y0, sl_y1 = sl_y_mid + 2.5, sl_y_mid - 2.5
            elif fret1 < fret0:
                sl_y0, sl_y1 = sl_y_mid - 2.5, sl_y_mid + 2.5
            else:
                sl_y0 = sl_y1 = sl_y_mid
            if sl_x1 > sl_x0 + 2.0:
                layer.recipe_instances.append(
                    RecipeInstance(
                        recipe_id="tab_slide_line",
                        params={"x0": sl_x0, "y0": sl_y0, "x1": sl_x1, "y1": sl_y1},
                        metadata={
                            "string": str(_string_num),
                            "event_id": str(event.get("event_id")),
                        },
                    )
                )
```

- [ ] **Step 5: Run the failing test**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_tab_slide_connects_across_measures -v
```

Expected: PASS.

- [ ] **Step 6: Run all scene tests**

```
pytest tests/test_core_scene_svg.py -v
```

Expected: all PASS. In particular, the existing `test_canonical_to_render_scene_tab_contains_technique_spans` must still pass (it checks `let_ring_span` and `palm_mute_span` — not affected by the slide refactor).

- [ ] **Step 7: Commit**

```bash
git add tests/test_core_scene_svg.py src/fretwise/core/scene/builders.py
git commit -m "fix(scene): cross-measure slide lines via all_tab_span_events accumulator"
```

---

## Task 5 — Harmonic diamond notehead: write failing test

**Files:**
- Test: `tests/test_core_scene_svg.py`

- [ ] **Step 1: Add a failing test for harmonic notehead**

Add in `tests/test_core_scene_svg.py`:

```python
def test_canonical_to_render_scene_standard_uses_diamond_notehead_for_harmonics() -> None:
    """A note with harmonic_type='natural' must render a diamond (notehead_harmonic) glyph."""
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"),
        source_format="gpif",
        events=[
            NoteEvent(
                pitch=76, onset=0.0, duration=1.0,
                tempo=120.0, articulation=Articulation.HARMONIC, dynamic=Dynamic.MF,
                string_hint=1, fret_hint=12,
                harmonic_type="natural",
            ),
        ],
        beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(
        raw_score,
        representation_mode=RepresentationMode("standard_tablature"),
    )
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    glyph_ids = [g.glyph_id for lg in staff.layer_groups for g in lg.glyph_instances]

    assert "notehead_harmonic" in glyph_ids, (
        f"Expected 'notehead_harmonic' glyph for harmonic note, found: {set(glyph_ids)}"
    )

    # Also verify SVG contains the diamond shape
    svg = render_scene_to_svg(result.render_scene)
    assert "notehead_harmonic" in svg or "diamond" in svg.lower() or "M 0," in svg
```

- [ ] **Step 2: Run the test to confirm it fails**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_standard_uses_diamond_notehead_for_harmonics -v
```

Expected: FAIL — `notehead_harmonic` not in glyph_ids.

---

## Task 6 — Harmonic diamond notehead: add glyph

**Files:**
- Modify: `src/fretwise/core/graphics/reference_glyph_set.py`

- [ ] **Step 1: Add `notehead_harmonic` to `default_reference_glyph_set`**

In `src/fretwise/core/graphics/reference_glyph_set.py`, inside `default_reference_glyph_set()`, add after `"notehead_muted"`:

```python
        "notehead_harmonic": ReferenceGlyph(
            glyph_id="notehead_harmonic",
            unicode_char="\u25C7",  # ◇ WHITE DIAMOND
            bbox=(-4.5, -3.2, 4.5, 3.2),
            anchors={"center": (0.0, 0.0), "stem_up": (4.5, 0.0), "stem_down": (-4.5, 0.0)},
            svg_path_data="M 0,-3.5 L 4.5,0 L 0,3.5 L -4.5,0 Z",
            svg_view_box=(-4.5, -3.5, 9.0, 7.0),
        ),
```

- [ ] **Step 2: Run existing glyph-related tests**

```
pytest tests/ -k "glyph" -v
```

Expected: all PASS (adding a key to the dict doesn't break anything).

---

## Task 7 — Harmonic diamond notehead: SVG backend rendering

**Files:**
- Modify: `src/fretwise/core/backends/svg.py`

- [ ] **Step 1: Find where noteheads are rendered in the SVG backend**

```bash
grep -n "notehead_filled\|notehead_open\|notehead_muted\|_render_glyph\|glyph_id" src/fretwise/core/backends/svg.py | head -20
```

Identify the function that renders glyph instances (likely `_render_glyph`).

- [ ] **Step 2: Add diamond rendering for `notehead_harmonic`**

Find `_render_glyph` in `src/fretwise/core/backends/svg.py`. It dispatches by `glyph_id`. Add a case for `notehead_harmonic`:

```python
    if glyph_id == "notehead_harmonic":
        # Diamond shape: rotated square. Center at (x, y), width=9, height=7.
        pts = f"{x:.2f},{y - 3.5:.2f} {x + 4.5:.2f},{y:.2f} {x:.2f},{y + 3.5:.2f} {x - 4.5:.2f},{y:.2f}"
        return (
            f'<polygon points="{pts}" fill="none" stroke="black" stroke-width="0.8" '
            f'class="fw-notehead-harmonic" data-event-id="{(metadata or {}).get(\"event_id\", \"\")}"/>'
        )
```

Add this BEFORE the generic fallback rendering (i.e., before the `else` or the default `return` in `_render_glyph`).

- [ ] **Step 3: Run the failing test from Task 5**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_standard_uses_diamond_notehead_for_harmonics -v
```

The glyph test part should PASS. The SVG content check might still fail depending on what exact string appears in the SVG.

Adjust the SVG assertion in the test to match the actual output:
```python
assert 'class="fw-notehead-harmonic"' in svg
```

- [ ] **Step 4: Run all scene tests**

```
pytest tests/test_core_scene_svg.py -v
```

Expected: all PASS.

---

## Task 8 — Harmonic diamond notehead: builder wiring

**Files:**
- Modify: `src/fretwise/core/scene/builders.py`

- [ ] **Step 1: Find where noteheads are chosen in `_append_standard_rhythm`**

```bash
grep -n "notehead_filled\|notehead_open\|notehead_muted\|glyph_id.*notehead" src/fretwise/core/scene/builders.py | head -20
```

Identify the line(s) that select which notehead glyph to use.

- [ ] **Step 2: Add harmonic notehead selection**

Find the glyph selection logic. It will look something like:

```python
notehead_glyph = "notehead_muted" if "muted" in techniques else (
    "notehead_open" if not _is_filled_notehead(duration) else "notehead_filled"
)
```

Change it to:

```python
if "muted" in techniques:
    notehead_glyph = "notehead_muted"
elif "harmonic" in techniques:
    notehead_glyph = "notehead_harmonic"
elif not _is_filled_notehead(duration):
    notehead_glyph = "notehead_open"
else:
    notehead_glyph = "notehead_filled"
```

There may be multiple locations (one for voice-up, one for voice-down, or one for tab vs standard). Apply the harmonic check in ALL notehead selection sites.

- [ ] **Step 3: Run the failing test from Task 5**

```
pytest tests/test_core_scene_svg.py::test_canonical_to_render_scene_standard_uses_diamond_notehead_for_harmonics -v
```

Expected: PASS (the `notehead_harmonic` glyph should now appear in `glyph_ids`).

- [ ] **Step 4: Run all tests**

```
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: all PASS. Fix any regressions before proceeding.

- [ ] **Step 5: Commit**

```bash
git add src/fretwise/core/graphics/reference_glyph_set.py \
        src/fretwise/core/backends/svg.py \
        src/fretwise/core/scene/builders.py \
        tests/test_core_scene_svg.py
git commit -m "feat(scene): diamond notehead for harmonic notes (notehead_harmonic glyph)"
```

---

## Task 9 — Add `tab_slide_line` to recipe catalog

**Files:**
- Modify: `src/fretwise/core/graphics/parametric_recipes.py`

- [ ] **Step 1: Add the missing recipe definition**

In `src/fretwise/core/graphics/parametric_recipes.py`, inside `default_recipe_catalog()`, add after `"filled_circle"`:

```python
        "tab_slide_line": RecipeDefinition(
            recipe_id="tab_slide_line",
            required_params=("x0", "y0", "x1", "y1"),
            optional_params=(),
            notes="Diagonal line from slide source to target fret. y0>y1 = descending, y0<y1 = ascending.",
            tags=("tab", "technique", "slide"),
        ),
```

- [ ] **Step 2: Run tests**

```
pytest tests/ -v --tb=short 2>&1 | tail -10
```

Expected: all PASS.

- [ ] **Step 3: Commit**

```bash
git add src/fretwise/core/graphics/parametric_recipes.py
git commit -m "chore(graphics): add tab_slide_line to recipe catalog"
```

---

## Task 10 — Corpus validation on Killing in the Name

**Files:**
- Read: `tests/fixtures/Rage Against The Machine-Killing in the Name-12-18-2025.gp`

- [ ] **Step 1: Run the pipeline and count key recipes**

```bash
.venv/Scripts/python.exe -c "
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.pipeline import run_core_pipeline_from_raw
from fretwise.core.graphics import RepresentationMode
from fretwise.parser import get_adapter
from pathlib import Path
from collections import Counter

fp = Path('tests/fixtures/Rage Against The Machine-Killing in the Name-12-18-2025.gp')
adapter = get_adapter(fp)
events = adapter.parse(fp)
raw = legacy_parse_to_raw_score(fp, source_format='gp', events=events, beats_per_measure=4.0)
result = run_core_pipeline_from_raw(raw, representation_mode=RepresentationMode('tablature_rhythm'))

recipe_counts = Counter(
    r.recipe_id
    for p in result.render_scene.document_scene.pages
    for s in p.systems
    for st in s.staves
    for lg in st.layer_groups
    for r in lg.recipe_instances
)
print('Recipe counts:')
for rid, cnt in recipe_counts.most_common():
    print(f'  {rid}: {cnt}')
print(f'Conformance issues: {len(result.conformance_issues)}')
"
```

- [ ] **Step 2: Verify improvements**

Expected improvements vs baseline (43 slides, 83 tuplet brackets, 0 harmonics):

| Metric | Before | Target after |
|--------|--------|--------------|
| `tab_slide_line` | 43/102 | 102/102 |
| `tuplet_bracket` | 83/~833 | ≥ 500/~833 |
| harmonic noteheads | 0/75 | 75/75 (in `standard_tablature` mode) |

Note: tuplet bracket improvement may be partial if some groups still fall through. Any remaining gaps should be documented as a follow-up issue.

- [ ] **Step 3: If tuplet bracket count is still low, add a targeted debug test**

Write a 4-beat measure test with 12 triplet 8ths (3 per beat × 4 beats = 4 expected brackets):

```python
def test_full_measure_triplets_produce_four_brackets() -> None:
    triplet_notes = [
        NoteEvent(
            pitch=60 + i, onset=i * (1/3), duration=1/3,
            tempo=120.0, articulation=Articulation.NORMAL, dynamic=Dynamic.MF,
            string_hint=1, fret_hint=i,
            tuplet_actual=3, tuplet_normal=2,
        )
        for i in range(12)  # 12 triplet 8ths = 4 beats = 4 groups
    ]
    raw_score = legacy_parse_to_raw_score(
        Path("song.gp"), source_format="gpif",
        events=triplet_notes, beats_per_measure=4.0,
    )
    result = run_core_pipeline_from_raw(raw_score, representation_mode=RepresentationMode("tablature_rhythm"))
    staff = result.render_scene.document_scene.pages[0].systems[0].staves[0]
    brackets = [r for lg in staff.layer_groups for r in lg.recipe_instances if r.recipe_id == "tuplet_bracket"]
    assert len(brackets) == 4, f"Expected 4 tuplet brackets for 4 beats of triplets, got {len(brackets)}"
```

Run, diagnose failure, fix root cause.

- [ ] **Step 4: Commit final state**

```bash
git add tests/test_core_scene_svg.py
git commit -m "test(scene): corpus validation and full-measure triplet bracket test"
```

---

## Self-Review

### Spec coverage check

| Issue | Task |
|-------|------|
| N1: Tuplet brackets | Task 1-2 |
| N2: Silences | **Not in this plan** — silences are in `_append_rest_glyph` (already implemented per audit). Defer. |
| N3: Clé de sol | **Not in this plan** — clef IS in the glyph set; rendering is a layout engine question. Defer. |
| N4: Armure 4/4 | **Not in this plan** — time_signature IS rendered. Defer. |
| N5: Slides | Task 3-4 |
| N6: Harmoniques | Task 5-8 |
| N7: Beaming ternaire | Covered by Task 1-2 (same root) |
| N8: Palm mute | Already 90% working (203/225). Defer remaining 10%. |

### Placeholder check

None. All steps include concrete file paths, line references, and code.

### Type consistency

- `all_tab_span_events: list[dict[str, object]]` — same type as `tab_span_events` already in use.
- `_emit_standalone_tuplet_brackets(layer: LayerGroup, stems: list[tuple[float, float, float]], ...)` — matches existing `LayerGroup` and stem tuple type.
- `notehead_harmonic` key in both `reference_glyph_set` and builder — consistent naming.
