# UI/Backend Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove Mode selector (hardcode Performance), remove Engine selector (hardcode Core), and promote hand-viz from checkbox to toolbar button — deleting all dead code behind these features.

**Architecture:** Backend endpoints lose `mode` and `engine` params; `CostWeights.performance()` is hardcoded in `_run_legacy_pipeline`. Frontend drops two toolbar selectors and wires `🖐 Viz` as a direct toolbar button.

**Tech Stack:** Python/FastAPI (app.py), vanilla JS (main.js, api.js), HTML/CSS

---

### Task 1: Backend cleanup — app.py

**Files:**
- Modify: `src/fretwise/web/app.py`

- [ ] **Step 1: Read app.py to confirm current state**

Run: `grep -n "def _solve_modes\|def _run_legacy_pipeline\|def _render_legacy_pdf_payload\|def _shadow_core_conformance\|mode: str = Query\|engine: str = Query" src/fretwise/web/app.py`

- [ ] **Step 2: Remove `_solve_modes()` helper and hardcode performance in `_run_legacy_pipeline`**

Delete the entire `_solve_modes()` function. In `_run_legacy_pipeline`, replace:
```python
weights = _solve_modes().get(mode, CostWeights.reference())
```
with:
```python
weights = CostWeights.performance()
```

- [ ] **Step 3: Remove `mode` param from `/api/notes`, `/api/solve`, `/api/export/pdf`**

In each endpoint, remove `mode: str = Query(...)` parameter and any `mode=mode` pass-through to `_run_legacy_pipeline`.

- [ ] **Step 4: Remove `engine` param and legacy PDF path from `/api/export/pdf`**

Remove `engine: str = Query("core")` and the `if engine == "legacy":` branch. Always use the core path.

- [ ] **Step 5: Delete `_render_legacy_pdf_payload` and `_shadow_core_conformance_outcome`**

These functions are only called from the now-deleted legacy PDF branch.

- [ ] **Step 6: Run tests**

Run: `pytest tests/test_web_export_pdf.py -v`
Expected: some failures (legacy PDF tests — to be fixed in Task 3)

- [ ] **Step 7: Commit**

```bash
git add src/fretwise/web/app.py
git commit -m "refactor(web): hardcode performance mode, remove engine selector backend"
```

---

### Task 2: API client cleanup — api.js

**Files:**
- Modify: `src/fretwise/web/static/js/api.js`

- [ ] **Step 1: Update `fetchNotes` signature**

New signature (remove `mode`):
```javascript
export async function fetchNotes(filename, trackId, preferences = {}) {
  let url = `/api/notes/${encodeURIComponent(filename)}?`;
  const sameFingerPenalty = preferences.sameFingerPenalty !== false;
  const inferImplicitLegato = preferences.inferImplicitLegato !== false;
  url += `same_finger_motion_penalty=${sameFingerPenalty ? 'true' : 'false'}`;
  url += `&infer_implicit_legato=${inferImplicitLegato ? 'true' : 'false'}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Notes fetch failed');
  }
  return res.json();
}
```

- [ ] **Step 2: Update `fetchSolve` signature**

New signature (remove `mode`):
```javascript
export async function fetchSolve(filename, trackId, representationMode, preferences = {}) {
  const sameFingerPenalty = preferences.sameFingerPenalty !== false;
  const inferImplicitLegato = preferences.inferImplicitLegato !== false;
  let url =
    `/api/solve/${encodeURIComponent(filename)}?` +
    `representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}` +
    `&same_finger_motion_penalty=${sameFingerPenalty ? 'true' : 'false'}` +
    `&infer_implicit_legato=${inferImplicitLegato ? 'true' : 'false'}`;
  if (trackId !== null && trackId !== undefined) url += `&track_id=${trackId}`;
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail || 'Solve failed');
  }
  return res.json();
}
```

- [ ] **Step 3: Update `fetchExportPdf` signature**

New signature (remove `mode`, `engine`, `preferences` — always core, no prefs needed):
```javascript
export async function fetchExportPdf(filename, trackId, representationMode) {
  let url =
    `/api/export/pdf/${encodeURIComponent(filename)}` +
    `?representation_mode=${encodeURIComponent(representationMode || 'standard_tablature')}`;
  if (trackId !== null && trackId !== undefined) {
    url += `&track_id=${trackId}`;
  }
  const res = await fetch(url);
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'PDF export failed' }));
    throw new Error(err.detail || 'PDF export failed');
  }
  const blob = await res.blob();
  const contentDisposition = res.headers.get('content-disposition') || '';
  const conformanceIssuesRaw = res.headers.get('x-fretwise-conformance-issues') || '0';
  const conformanceIssues = Number.parseInt(conformanceIssuesRaw, 10) || 0;
  const conformanceReportRaw = res.headers.get('x-fretwise-conformance-report') || '';
  let conformanceReport = null;
  if (conformanceReportRaw) {
    try { conformanceReport = JSON.parse(conformanceReportRaw); } catch (_err) { conformanceReport = null; }
  }
  let filenameOut = 'fretwise-export.pdf';
  const m = /filename="?([^";]+)"?/i.exec(contentDisposition);
  if (m && m[1]) filenameOut = m[1];
  return { blob, filename: filenameOut, engine: 'core', conformanceIssues, conformanceReport };
}
```

- [ ] **Step 4: Commit**

```bash
git add src/fretwise/web/static/js/api.js
git commit -m "refactor(web): remove mode/engine params from api.js client"
```

---

### Task 3: Test cleanup — test_web_export_pdf.py

**Files:**
- Modify: `tests/test_web_export_pdf.py`

- [ ] **Step 1: Delete legacy PDF tests and helper**

Remove: `_legacy_result()` helper, `test_render_legacy_pdf_payload_returns_bytes`, `test_render_legacy_pdf_payload_filename_sanitized`, `test_render_legacy_pdf_payload_missing_results_raises`.

Remove the `_render_legacy_pdf_payload` import.

- [ ] **Step 2: Update `test_solve_endpoint_exposes_core_svg_and_representation_mode`**

Remove `mode=` from the `_fake_legacy` inner function signature and any `mode` argument passed to it.

- [ ] **Step 3: Update `test_export_pdf_core_engine_uses_requested_representation_mode`**

Remove `mode=` and `engine=` query params from the test request URL.

- [ ] **Step 4: Run tests**

Run: `pytest tests/test_web_export_pdf.py -v`
Expected: all pass

- [ ] **Step 5: Commit**

```bash
git add tests/test_web_export_pdf.py
git commit -m "test(web): remove legacy PDF tests after engine selector removal"
```

---

### Task 4: main.js cleanup

**Files:**
- Modify: `src/fretwise/web/static/js/main.js`

- [ ] **Step 1: Remove DOM refs for mode and engine selectors**

Remove:
```javascript
const selMode = document.getElementById('mode-select');
const pdfEngineSelect = document.getElementById('pdf-engine-select');
```

- [ ] **Step 2: Replace `prefHandViz` checkbox ref with `btnHandViz` button ref**

Remove:
```javascript
const prefHandViz = document.getElementById('pref-hand-viz');
```
Add:
```javascript
const btnHandViz = document.getElementById('btn-hand-viz');
```

- [ ] **Step 3: Remove all `selMode.value` usages**

Find all references like `selMode.value`, `selMode.addEventListener`, etc. and remove them. The mode is now always "performance" — remove any variable that stored or passed it.

- [ ] **Step 4: Remove `pdfEngineSelect` usages**

Remove all references to `pdfEngineSelect.value` and its change listener.

- [ ] **Step 5: Wire `btnHandViz` button**

Replace the `prefHandViz` change listener:
```javascript
// OLD:
prefHandViz.addEventListener('change', () => { ... });

// NEW:
btnHandViz.addEventListener('click', _toggleHandViz);
```

Add helper if not already present:
```javascript
function _toggleHandViz() {
  const panel = document.getElementById('hand-viz-panel');
  const visible = panel.style.display !== 'none';
  panel.style.display = visible ? 'none' : 'flex';
  btnHandViz.classList.toggle('tb-btn-active', !visible);
}
```

- [ ] **Step 6: Update all `fetchNotes`, `fetchSolve`, `fetchExportPdf` call sites**

Remove `mode` argument from every call to these functions in main.js.
For `fetchExportPdf`, also remove `engine` and `preferences` arguments.

- [ ] **Step 7: Commit**

```bash
git add src/fretwise/web/static/js/main.js
git commit -m "refactor(web): remove mode/engine selectors from main.js, wire viz button"
```

---

### Task 5: index.html cleanup

**Files:**
- Modify: `src/fretwise/web/static/index.html`

- [ ] **Step 1: Remove Mode selector**

Delete:
```html
<span class="tb-sep"></span>
<span class="tb-label">Mode</span>
<select id="mode-select" class="toolbar-select" title="...">
  <option value="reference">Reference</option>
  <option value="performance">Performance</option>
  <option value="musical">Musical</option>
  <option value="learning">Learning</option>
</select>
```

- [ ] **Step 2: Remove Engine selector**

Delete:
```html
<span class="tb-label">Engine</span>
<select id="pdf-engine-select" class="toolbar-select" title="PDF export engine">
  <option value="core" selected>Core</option>
  <option value="legacy">Legacy</option>
</select>
```

- [ ] **Step 3: Remove hand-viz preference checkbox**

Delete:
```html
<label class="tb-pref-item" title="Open a floating panel with the animated left-hand visualization...">
  <input type="checkbox" id="pref-hand-viz">
  <span>Show hand visualization</span>
</label>
```

- [ ] **Step 4: Add `🖐 Viz` button to toolbar-left**

After the `✋ Fingers` button, add:
```html
<button id="btn-hand-viz" class="tb-btn" title="Toggle hand visualization panel">🖐 Viz</button>
```

- [ ] **Step 5: Run full test suite**

Run: `pytest -v`
Expected: all pass (≥794)

- [ ] **Step 6: Commit**

```bash
git add src/fretwise/web/static/index.html
git commit -m "feat(web): remove mode/engine selectors, add viz button to toolbar"
```
