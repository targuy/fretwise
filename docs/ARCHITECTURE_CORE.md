# `core/` — notation rendering subsystem

> Status: in flight (Phase 4+ refactor, P0/P1/P2 sub-phases). Bridge contract with the legacy renderer: `docs/p0-bridge-contract.md`.

The `src/fretwise/core/` package is the notation-rendering pipeline introduced during Phase 4. It is **separate from** the fingering pipeline (`parser/` → `generator/` → `scoring/` → `optimizer/` → `pipeline.py`). The legacy renderers (`export/pdf_tab.py`, `export/staff_renderer.py`, `export/combined_renderer.py`) still ship side-by-side; the goal of the refactor is parity, then deprecation.

---

## Data flow

```
raw input (file path + adapter output)
        │
        ▼
   ingest/      ─── RawScore                    (legacy_parse_to_raw_score bridge)
        │
        ▼
   normalize/   ─── NormalizedScore             (rhythm, metadata cleanup)
        │
        ▼
   complete/    ─── CompletedScore              (fill implicit fields)
        │
        ▼
   validate/    ─── ValidationReport
        │
        ▼
   decision/    ─── DecisionOutcome             (per-voice representation policy)
        │
        ▼
   canonical/   ─── CanonicalScore              (Score model — backend-agnostic)
        │
        ▼
   scene/       ─── RenderScene                 (DocumentScene → PageScene → SystemScene
        │                                        → StaffScene → LayerGroup → RecipeInstance)
        │
        ▼
   backends/    ─── SVG string  /  PDF bytes    (consumes RenderScene only)
```

Entry point: `fretwise.core.run_core_pipeline_from_raw(raw_score, representation_mode=...)` returns `CorePipelineResult` (defined in `core/pipeline.py`) with every intermediate artefact plus the final `svg` string and `conformance_issues` list.

---

## Subdirectory responsibilities

| Path | Purpose |
|---|---|
| `core/ingest/` | Adapters that bridge legacy `NoteEvent` lists (or future parsers) into `RawScore` (`models.py`). The `legacy_parse_to_raw_score(...)` adapter is the current bridge used by `web/app.py` and the legacy CLI. |
| `core/normalize/` | `normalize_raw_score(...)` — rhythm normalisation, metadata defaults. |
| `core/complete/` | `complete_normalized_score(...)` — fills in implicit per-note fields needed for layout. |
| `core/validate/` | `validate_completed_score(...)` → `ValidationReport`. Pre-decision sanity checks. |
| `core/decision/` | `decide_from_validation(report, policy=...)` → `DecisionOutcome`. Per-voice/per-staff representation choices. |
| `core/canonical/` | `Score` (backend-agnostic music model) + `completed_to_canonical_score(...)` mapper. Mappers convert layout-agnostic semantic descriptions into ordered, well-typed canonical structures. |
| `core/scene/` | `canonical_to_render_scene(canonical, mode=...)` builds a `RenderScene` of nested scenes ending in `RecipeInstance` objects (recipe id + params). Backend-agnostic. `render_helpers.py` houses duration-to-stem-flag and similar conversions. |
| `core/layout/` | `rules.py` — layout constants and helpers (e.g. `pitch_to_staff_y`). `builders.py` constructs page/system/staff layouts; `collisions.py` detects post-layout overlaps. `canonical_to_page_layout(...)` is the entry point used by the web app for measure-region computation. |
| `core/graphics/` | `RepresentationMode` (StrEnum: `STANDARD`, `TAB`, `STANDARD_TAB`, `TAB_RHYTHM`), `default_notation_policy()`, `parametric_recipes.py` (recipe registry), `reference_glyph_set.py`, `check_scene_conformance(scene, mode, policy)` → `list[ConformanceIssue]`. |
| `core/backends/` | `render_scene_to_svg(scene)` and `render_scene_to_pdf_bytes(scene)`. Each backend consumes only the `RenderScene` — no upstream coupling. |
| `core/notation_mode.py` | **Single source of truth for the 4 canonical mode strings.** Helpers: `has_tab(mode)`, `has_standard(mode)`, `is_valid_mode(mode)`, `system_height_for_mode(mode)`. The frontend (`web/static/js/modeConfig.js`) mirrors these strings — keep them in lock-step. |
| `core/notation_utils.py` | Pure helpers for diatonic step indexing and standard-notation Y placement (`standard_note_y`, `diatonic_step_index`, `diatonic_step_from_name`, `diatonic_step_from_metadata`). Used by both `layout/rules.py` and `scene/builders.py` to prevent staff-position drift between the two subsystems. |
| `core/registries.py` | Registries of recipes and policies used by graphics + scene builders. |
| `core/transform/` | Reserved for future transformation passes. |

---

## Design rules

1. **Backend-agnostic scenes.** The `RenderScene` (in `core/scene/models.py`) is the only contract between layout and rendering. New visual elements must be expressed as parametric recipes (defined in `core/graphics/parametric_recipes.py`), not as direct draw calls inside a backend.
2. **Single source of truth for modes.** Any code that branches on notation mode must call `core/notation_mode.py` helpers. Do not redefine the 4 mode strings or duplicate set-membership tests. The frontend mirror in `web/static/js/modeConfig.js` is the only allowed copy.
3. **No circular imports inside core.** `notation_mode.py` does **not** import from `graphics/`, `scene/`, or `layout/` because those packages mutually depend on each other — the mode strings are stable, pure-string public API.
4. **Layout/scene staff-Y parity.** Both `layout/rules.py` and `scene/builders.py` delegate to `core/notation_utils.standard_note_y(...)`. If you find yourself computing staff Y from MIDI pitch anywhere else, route it through that helper instead.
5. **Conformance check is the gate.** `check_scene_conformance(scene, mode, policy)` returns `ConformanceIssue` items. The current P0/P1/P2 acceptance criterion is **0 issues** for the corpus. The PDF export endpoint surfaces the count in the `X-Fretwise-Conformance-Issues` header.

---

## Where to look first

- New visual feature → `core/graphics/parametric_recipes.py` (recipe), then `core/scene/builders.py` (emit) and `core/backends/svg.py` + `core/backends/pdf.py` (consume).
- New mode → `core/notation_mode.py` + mirror in `web/static/js/modeConfig.js`; update `RepresentationMode` in `core/graphics/notation_policy.py` (keep the string values aligned).
- Layout adjustments → `core/layout/rules.py` + tests `tests/test_core_layout_rules.py`.
- Pipeline integration test → `tests/test_core_input_pipeline.py`, plus per-stage tests `test_core_canonical.py`, `test_core_decision.py`, `test_core_scene_svg.py`, `test_core_backends_pdf.py`, `test_core_validate.py`, `test_core_graphics.py`.
