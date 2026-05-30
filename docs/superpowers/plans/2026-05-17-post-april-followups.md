# Post-April Follow-ups — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close out the residual work surfaced by the 2026-05-17 audit of the three 2026-04-20 plans (`finger-bias-audit.md`, `notation-rendering-fixes.md`, `ui-cleanup.md`) and bring plan tracking in line with the shipped reality.

**Architecture:** Two concrete code changes (cross-measure slide coverage + optional triplet test) live in `src/fretwise/core/scene/builders.py` and `tests/test_core_scene_svg.py`. The remaining work is documentation hygiene — marking checkboxes on superseded plans and updating `STATUS.md` if needed.

**Tech Stack:** Python 3.11, `src/fretwise/core/scene/builders.py`, `tests/test_core_scene_svg.py`, pytest. Markdown for plan/status edits.

---

## Audit summary (2026-05-17)

| Plan | Reported boxes | Actual state |
|---|---|---|
| `2026-04-20-finger-bias-audit.md` | 0/21 done (tracking) | **21/21 implemented** — scripts, reports, tests, and analysis in `docs/core_notation_gap_audit.md` all present. Conclusion: algorithm behavior is correct (Hypothesis B), no fix required. |
| `2026-04-20-notation-rendering-fixes.md` | 0/38 done (tracking) | **37/38 implemented** — tuplet brackets, harmonic noteheads, cross-measure slides all wired (commit `7ceefb5`, 2026-04-20). One optional follow-up test missing. Slides at 80/102 (78%), not 102/102. |
| `2026-04-20-ui-cleanup.md` | 0/29 done (tracking) | **29/29 implemented** — Mode selector, Engine selector, hand-viz checkbox all removed; hand-viz button wired into the toolbar; legacy helpers deleted. |

---

## File Map

| File | Change |
|------|--------|
| `tests/test_core_scene_svg.py` | Add `test_full_measure_triplets_produce_four_brackets()` (optional follow-up from notation plan Task 10.3). |
| `src/fretwise/core/scene/builders.py` | Investigate why 22/102 cross-measure slides on *Killing in the Name* fail to render. Likely culprits: legato vs shift detection, slide-in/slide-out grace notes, slides whose target spans more than one barline. |
| `docs/superpowers/plans/2026-04-20-finger-bias-audit.md` | Mark all 21 checkboxes `- [x]` and prepend a "Completed 2026-04-20 — see audit 2026-05-17" header. |
| `docs/superpowers/plans/2026-04-20-notation-rendering-fixes.md` | Mark 37/38 checkboxes `- [x]`; leave Task 10.3 unchecked (or mark `- [ ]` with a note "see this plan"). |
| `docs/superpowers/plans/2026-04-20-ui-cleanup.md` | Mark all 29 checkboxes `- [x]` and prepend completion header. |
| `STATUS.md` | Confirm Phase 4 entry still accurate; add a "Refactor `core/` + P0/P1/P2 notation" section reflecting that the rendering fixes plan is essentially done (cite the residual slide gap). |

---

## Task 1 — Cross-measure slide coverage gap (P1)

**Context:** After commit `7ceefb5`, *Killing in the Name* renders 80/102 cross-measure slides correctly. The 22 missing ones need to be characterised before any fix.

- [ ] **Step 1: Add a diagnostic script `scripts/diag_cross_measure_slides.py`** that runs the core pipeline on `partitions/Rage Against The Machine-Killing in the Name.gp5` (or whichever file in the corpus), enumerates every note with `slide_type` set, and reports which ones produced a `tab_slide_line` recipe vs which were dropped. Group dropped slides by reason: `target_missing`, `target_off_screen`, `legato_vs_shift_mismatch`, `slide_in_grace`, `slide_out_no_target`, `unknown`.

- [ ] **Step 2: Run the diagnostic and save output** to `docs/benchmarks/cross_measure_slides_diag.txt`. Identify the dominant failure category.

- [ ] **Step 3: Write a failing scene-builder test** in `tests/test_core_scene_svg.py` that reproduces the dominant failure mode in isolation (synthetic 2-note input). Name it `test_cross_measure_slide_<failure_mode>_renders()`.

- [ ] **Step 4: Fix `_append_tab_slide_connections` or `all_tab_span_events` accumulation** in `src/fretwise/core/scene/builders.py` so the failing test passes. Keep the existing 80 working cases passing (full test suite must remain green).

- [ ] **Step 5: Re-run the diagnostic** and confirm the slide count moves from 80/102 toward 102/102. Accept any improvement ≥ 90/102; document the remainder as known-edge-case in `docs/p0-bridge-contract.md` if needed.

- [ ] **Step 6: Commit** as `fix(notation): improve cross-measure slide coverage on Killing in the Name (80→XX/102)`.

**Acceptance:** Diagnostic report exists; slide coverage on the target file ≥ 90/102; no regression in `tests/test_core_scene_svg.py`.

---

## Task 2 — Optional: triplet-bracket follow-up test (P3)

**Context:** Task 10.3 from `2026-04-20-notation-rendering-fixes.md` was deferred because the main fix (101 brackets vs baseline 83) was deemed sufficient. Adding this test guards against regression.

- [ ] **Step 1: Add `test_full_measure_triplets_produce_four_brackets()`** in `tests/test_core_scene_svg.py`. Input: a full 4/4 measure of 12 eighth-note triplets (4 groups of 3, `tuplet_actual=3 tuplet_normal=2`). Expected: scene contains exactly 4 `tuplet_bracket` recipe instances with `count=3` each.

- [ ] **Step 2: Run the test, confirm it passes** against current `_emit_standalone_tuplet_brackets`. If it fails, that indicates a regression in tuplet detection and Task 10.3's original concern was valid — escalate.

- [ ] **Step 3: Commit** as `test(notation): full-measure triplet bracket coverage`.

**Acceptance:** New test passes; no regression elsewhere.

---

## Task 3 — Plan hygiene: mark superseded plans as complete (P2)

**Context:** Three plans show 0% completion in checkbox tracking despite being effectively shipped. Future audits will repeat the same work unless this is fixed.

- [ ] **Step 1: Update `2026-04-20-finger-bias-audit.md`** — mark all 21 checkboxes `- [x]` and prepend below the front-matter quote block:

```markdown
> **Status: ✅ COMPLETED 2026-04-20.** Verified by audit on 2026-05-17 (see `2026-05-17-post-april-followups.md`). All scripts, reports, and tests are in the repo; conclusion documented in `docs/core_notation_gap_audit.md` "Finger Bias Analysis" section.
```

- [ ] **Step 2: Update `2026-04-20-notation-rendering-fixes.md`** — mark 37/38 checkboxes `- [x]`. Leave Task 10.3's checkbox `- [ ]` and add an inline note `(deferred — see 2026-05-17-post-april-followups.md Task 2)`. Prepend completion header citing commit `7ceefb5` and the slide-coverage caveat (80/102).

- [ ] **Step 3: Update `2026-04-20-ui-cleanup.md`** — mark all 29 checkboxes `- [x]` and prepend completion header.

- [ ] **Step 4: Commit** as `docs(plans): mark April plans complete after 2026-05-17 audit`.

**Acceptance:** Reading any of the three April plans surfaces its completion status without re-running an audit.

---

## Task 4 — STATUS.md refresh (P2)

**Context:** `STATUS.md` was last touched 2026-03-17 / 2026-05-04 and lists Phase 4 as complete but says nothing about the refactor sub-phases (P0/P1/P2 notation, finger-bias audit, UI cleanup). The newly added `CLAUDE.md` already mentions "Refactor `core/` + P0/P1/P2 notation — EN COURS". Make `STATUS.md` agree.

- [ ] **Step 1: Read current `STATUS.md`** to confirm the Phase table and the "Architecture actuelle" section are still accurate against `src/fretwise/core/` layout.

- [ ] **Step 2: Add a sub-section under Phase 4** titled `### 4G — Notation core refactor (P0/P1/P2)` listing the completed items (P0 bridge contract, pitch_to_staff_y, per-measure timesig, notation_mode centralisation, dense passage layout, polyphonic offsets) and the in-flight residual (cross-measure slide coverage gap).

- [ ] **Step 3: Update "Métriques actuelles"** — tests count is likely > 588 now (73 new tests from `test_notation_mode.py`, `test_notation_utils.py`, `test_hand_viz.py`). Run `pytest --collect-only -q | tail -5` to get the real number.

- [ ] **Step 4: Commit** as `docs(status): record P0/P1/P2 notation refactor + audit results`.

**Acceptance:** `STATUS.md` accurately reflects the codebase as of 2026-05-17 and references the audit + this plan.

---

## Out-of-scope / explicitly not in this plan

- **Phase 5 (Player Profile) kick-off** — separate plan when ready.
- **Removal of legacy `export/pdf_tab.py`** — keep parallel renderers until the cross-measure slide gap closes and the conformance score holds at 0 issues on the full corpus.
- **MIDI parser maintenance** — no MIDI test fixtures or work required per user direction (2026-05-17).
- **Committing the current uncommitted state** — user has explicitly directed "no files to send to git" (2026-05-17). Re-confirm before any `git add`.

---

## Suggested execution order

1. Task 3 (plan hygiene) — fastest, prevents repeat audits. ~15 min.
2. Task 4 (STATUS.md refresh) — quick documentation alignment. ~15 min.
3. Task 1 (cross-measure slides) — substantive work; depends on diagnostic findings. ~1–3 h.
4. Task 2 (optional triplet test) — only if Task 1 surfaces a regression risk. ~15 min.
