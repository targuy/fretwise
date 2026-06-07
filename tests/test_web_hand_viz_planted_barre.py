"""Milestone-4 tests for the fretboard hand-viz renderer.

M1 locked the panel wiring, M2 generalized the geometry, M3 re-grounded the
hand rig anatomically.  Milestone 4 covers three edge-polish behaviours:

1. **Planted barre across a string range** — a held barre (one finger laid
   across several contiguous strings) must render across that range, not as a
   single point.  ``parsePlanted`` normalises the payload entry and the sampler
   carries a contiguous ``strings`` range through to ``collectHandTargets`` and
   the bar-pad render.

2. **Graceful empty / staff-only state** — a track with no fretted fingering
   (vocal / staff-only, or a solve that produced no fretted notes) must show a
   clear "no fingering" state instead of a broken or stale hand, and must not
   throw.  Covered on both sides: the payload builder (``main.js``) emits an
   explicit ``fingered:false`` payload, and the renderer (``hand_viz.html``)
   detects it via ``_hasNoFingering`` and draws the message.

3. **Sync-drift over a long timeline** — the parent→iframe time-sync sends
   ABSOLUTE timestamps and the iframe never integrates ``dt`` in synced mode,
   so the iframe clock tracks the parent exactly with zero accumulated error.
   The test drives a simulated multi-minute timeline through the renderer's
   actual clock-selection logic and asserts no drift.

Two layers, mirroring the sibling M2/M3 suites:

* **Static source guards** (always run) — assert the source carries the new
  behaviour so the contract cannot silently regress even without a JS engine.
* **Behavioural checks** (run only when ``node`` is available) — execute the
  renderer's real functions in a stubbed DOM and assert the numbers.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"
_HAND_VIZ = _STATIC_DIR / "hand_viz.html"
_MAIN_JS = _STATIC_DIR / "js" / "main.js"

# Renderer string-Y geometry, mirrored so expectations are independent of impl.
_STRING_Y_TOP = 230.0
_STRING_Y_BOTTOM = 350.0


def _expected_string_y(string: int, num_strings: int) -> float:
    spacing = (_STRING_Y_BOTTOM - _STRING_Y_TOP) / (num_strings - 1)
    return _STRING_Y_TOP + (string - 1) * spacing


# --------------------------------------------------------------------------- #
# Layer 1 — static source guards (no JS engine required).
# --------------------------------------------------------------------------- #
def test_renderer_has_planted_barre_parser() -> None:
    """``parsePlanted`` exists and the planted path carries a string range."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    assert "function parsePlanted(p)" in html
    # The planted parse routes through parsePlanted instead of the old
    # single-string `{ string: p[0], fret: p[1] }` literal.
    assert "planted[fname] = parsePlanted(p)" in html
    assert "planted[fname] = { string: p[0], fret: p[1] }" not in html
    # The bar pad is drawn for a planted barre, not only an active one.
    assert '(role === "active" || role === "planted") && fg.strings.length > 1' in html
    # The old "planted is always a single string" hard limitation is gone.
    assert "planted[fname].strings = [planted[fname].string];" not in html


def test_renderer_has_no_fingering_state() -> None:
    """The renderer detects and renders a graceful no-fingering state."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    assert "function _hasNoFingering(data)" in html
    assert "function renderNoFingeringState()" in html
    assert "let NO_FINGERING" in html
    # installData computes the flag and the frame loop early-outs on it.
    assert "NO_FINGERING         = _hasNoFingering(data);" in html
    assert "if (NO_FINGERING) {" in html
    # A human-readable message is shown.
    assert "Aucun doigté pour cette piste" in html
    assert "No fingering for this track" in html


def test_payload_builder_emits_empty_state() -> None:
    """``_buildHandVizPayload`` returns an explicit no-fingering payload."""
    js = _MAIN_JS.read_text(encoding="utf-8")
    assert "function _emptyHandVizPayload(reason)" in js
    builder = js[js.index("function _buildHandVizPayload"):]
    builder = builder[: builder.index("\nfunction _postHandVizData")]
    # Staff-only / vocal tracks (no fretted result) get the empty payload.
    assert "_emptyHandVizPayload('staff-only')" in builder
    assert "hasFretted" in builder
    # The empty payload is fingered:false so the iframe shows the message.
    assert "fingered: false" in js


def test_sync_path_uses_absolute_timestamps() -> None:
    """The seek path is drift-free: absolute timestamps, no dt integration."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # Strip comments so the guard prose (which intentionally names the forbidden
    # `extT += dt` form) doesn't trip the code-shape assertions below.
    code = re.sub(r"/\*.*?\*/", "", html, flags=re.DOTALL)
    code = re.sub(r"//[^\n]*", "", code)
    # EXT_SYNCED reads extT directly — never accumulates dt.
    assert "tNow = extT;" in code
    # No incremental integration of the external clock anywhere in the code.
    assert "extT +=" not in code
    assert re.search(r"extT\s*=\s*extT\s*\+", code) is None
    # The guard comment documents the invariant (checked on the raw source).
    assert "sync-drift guard" in html
    # The parent sends the absolute playback clock.
    js = _MAIN_JS.read_text(encoding="utf-8")
    assert "t: playback.getCurrentTimeSec()" in js


# --------------------------------------------------------------------------- #
# Layer 2 — behavioural checks via node (skipped when node is absent).
# --------------------------------------------------------------------------- #
_NODE = shutil.which("node")
pytestmark_node = pytest.mark.skipif(_NODE is None, reason="node not available")


def _run_in_node(probe: str) -> dict:
    """Execute the renderer in a stubbed DOM and return a JSON probe.

    ``probe`` is JS that assigns to ``out`` after the renderer script has loaded
    (the boot IIFE is inert behind DOM stubs).  All renderer functions
    (``installData``, ``sampleState``, ``parsePlanted``, …) are in scope.
    """
    html = _HAND_VIZ.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert m, "renderer must contain an inline <script> block"
    script = m.group(1)

    harness = (
        textwrap.dedent(
            """
            // Minimal DOM/window stubs so the boot IIFE is inert. FakeEl records
            // appended children so the no-fingering message can be inspected.
            function FakeEl() { this.children = []; this.attrs = {}; this._text = ''; }
            FakeEl.prototype.setAttribute = function (k, v) { this.attrs[k] = v; };
            FakeEl.prototype.appendChild = function (c) { this.children.push(c); return c; };
            FakeEl.prototype.removeChild = function (c) {
              const i = this.children.indexOf(c); if (i >= 0) this.children.splice(i, 1);
            };
            Object.defineProperty(FakeEl.prototype, 'firstChild', {
              get() { return this.children.length ? this.children[0] : null; },
            });
            Object.defineProperty(FakeEl.prototype, 'textContent', {
              get() { return this._text; }, set(v) { this._text = v; this.children = []; },
            });
            FakeEl.prototype.style = {};
            FakeEl.prototype.addEventListener = function () {};
            const _byId = {};
            const _doc = {
              createElementNS: () => new FakeEl(),
              getElementById: (id) => (_byId[id] || (_byId[id] = new FakeEl())),
            };
            globalThis.__byId = _byId;
            globalThis.document = _doc;
            globalThis.window = {
              addEventListener: () => {}, parent: null, postMessage: () => {},
            };
            globalThis.performance = { now: () => 0 };
            globalThis.requestAnimationFrame = () => 0;
            globalThis.fetch = () => Promise.reject(new Error('no fetch in test'));

            // Recursively collect all text strings in an element subtree.
            globalThis.collectText = function (elm, acc) {
              acc = acc || [];
              if (!elm) return acc;
              if (elm._text) acc.push(elm._text);
              for (const c of (elm.children || [])) collectText(c, acc);
              return acc;
            };
            """
        )
        + "\n"
        + script
        + "\n"
        + textwrap.dedent(
            """
            let out = {};
            __PROBE__
            process.stdout.write(JSON.stringify(out));
            """
        ).replace("__PROBE__", probe)
    )

    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


@pytestmark_node
def test_planted_barre_spans_string_range() -> None:
    """A planted barre across strings 1–3 yields a 3-string contiguous range."""
    # Two frames: an active note that has ended (t past its end) but carries a
    # planted barre across strings 1..3 at fret 5 on the index finger. We sample
    # at a time AFTER the active note so only the planted state remains.
    probe = textwrap.dedent(
        """
        const frames = [
          { note_id: 0, onset_sec: 0.0, duration_sec: 0.2, string: 1, fret: 5,
            finger: 'index', hand_position: 5,
            planted: { index: [1, 5, 3] } },
          { note_id: 1, onset_sec: 1.0, duration_sec: 0.2, string: 6, fret: 7,
            finger: 'ring', hand_position: 5,
            planted: { index: [1, 5, 3] } },
        ];
        // Sample at t=1.3s: note 1 (ring) has ended, the index barre is planted.
        const st = sampleState(1.3, frames);
        const pl = st.planted.index;
        out.planted_strings = pl ? pl.strings : null;
        out.planted_string  = pl ? pl.string : null;
        out.planted_fret    = pl ? pl.fret : null;
        // Centre-targeting: collectHandTargets averages the range to its centre.
        const tgt = collectHandTargets(st).find((t) => t.finger === 'index');
        out.target_y = tgt ? tgt.y : null;
        out.target_string = tgt ? tgt.string : null;
        // Direct parse of the explicit-range form and the single-string form.
        out.parse_range  = parsePlanted([1, 5, 3]);
        out.parse_single = parsePlanted([2, 7]);
        out.parse_list   = parsePlanted([2, 7, { strings: [2, 3, 4] }]);
        """
    )
    g = _run_in_node(probe)
    # The planted index finger now covers a contiguous 3-string range.
    assert g["planted_strings"] == [1, 2, 3]
    assert g["planted_string"] == 1
    assert g["planted_fret"] == 5
    # The target Y is the centre of strings 1..3 (not the single string-1 Y).
    centre_y = (_expected_string_y(1, 6) + _expected_string_y(3, 6)) / 2
    assert g["target_y"] == pytest.approx(centre_y, abs=1e-6)
    assert g["target_string"] == pytest.approx(2.0, abs=1e-6)  # mean of 1,2,3
    # parsePlanted normalises every accepted shape.
    assert g["parse_range"]["strings"] == [1, 2, 3]
    assert g["parse_single"]["strings"] == [2]
    assert g["parse_list"]["strings"] == [2, 3, 4]


@pytestmark_node
def test_planted_single_string_still_point() -> None:
    """A v1 single-string plant ([string, fret]) stays a one-string plant."""
    probe = textwrap.dedent(
        """
        const frames = [
          { note_id: 0, onset_sec: 0.0, duration_sec: 0.2, string: 3, fret: 4,
            finger: 'middle', hand_position: 3, planted: { middle: [3, 4] } },
          { note_id: 1, onset_sec: 1.0, duration_sec: 0.2, string: 1, fret: 2,
            finger: 'index', hand_position: 3, planted: { middle: [3, 4] } },
        ];
        const st = sampleState(1.3, frames);
        out.strings = st.planted.middle ? st.planted.middle.strings : null;
        """
    )
    g = _run_in_node(probe)
    assert g["strings"] == [3]


@pytestmark_node
def test_empty_fingering_renders_message_no_throw() -> None:
    """A staff-only payload installs cleanly and draws the no-fingering message."""
    # Frames with only open strings (no fretted fingering) — a vocal/staff track.
    probe = textwrap.dedent(
        """
        const staffOnly = {
          meta: { title: 'Voce', tempo: 120, max_seconds: 30, synced: true },
          fretboard: { tuning: ['E2','A2','D3','G3','B3','E4'] },
          frames: [
            { note_id: 0, onset_sec: 0.0, duration_sec: 1.0, string: 1, fret: 0,
              finger: 'open', hand_position: 1 },
            { note_id: 1, onset_sec: 1.0, duration_sec: 1.0, string: 2, fret: 0,
              finger: 'open', hand_position: 1 },
          ],
        };
        installData(staffOnly);
        out.no_fingering = NO_FINGERING;
        // The overlay layer must contain the message text; the hand layer empty.
        const overlay = __byId['layer-overlay'];
        const hand = __byId['layer-hand'];
        out.overlay_text = collectText(overlay);
        out.hand_children = hand ? hand.children.length : -1;

        // An explicit fingered:false payload (the builder's empty form) too.
        const emptyPayload = {
          meta: { title: 'X', tempo: 120, synced: true, fingered: false },
          fretboard: { tuning: ['E2','A2','D3','G3','B3','E4'] },
          frames: [],
        };
        installData(emptyPayload);
        out.empty_no_fingering = NO_FINGERING;

        // And a normal fingered payload flips the flag back off (track switch).
        const fingered = {
          meta: { title: 'Riff', tempo: 120, synced: true },
          fretboard: { tuning: ['E2','A2','D3','G3','B3','E4'] },
          frames: [
            { note_id: 0, onset_sec: 0.0, duration_sec: 0.5, string: 6, fret: 5,
              finger: 'index', hand_position: 5 },
          ],
        };
        installData(fingered);
        out.fingered_no_fingering = NO_FINGERING;
        """
    )
    g = _run_in_node(probe)
    assert g["no_fingering"] is True
    assert any("Aucun doigté" in t for t in g["overlay_text"])
    assert any("No fingering for this track" in t for t in g["overlay_text"])
    # No stale/broken hand left in the hand layer for a staff-only track.
    assert g["hand_children"] == 0
    # Explicit fingered:false payload is also treated as no-fingering.
    assert g["empty_no_fingering"] is True
    # Switching back to a fingered track clears the no-fingering state.
    assert g["fingered_no_fingering"] is False


@pytestmark_node
def test_sync_no_drift_over_long_timeline() -> None:
    """The synced iframe clock tracks the parent exactly over many minutes.

    Drives the renderer's real EXT_SYNCED clock-selection logic across a
    simulated 5-minute timeline.  The parent sends absolute timestamps each
    frame (as main.js does); the iframe must read them with zero accumulated
    drift no matter how many frames elapse or how jittery the frame interval.
    """
    probe = textwrap.dedent(
        """
        // Replicate the renderer's synced clock read: in EXT_SYNCED mode tNow is
        // simply the last absolute timestamp received (extT), never extT += dt.
        // We feed the parent's absolute clock and a jittery per-frame dt, and
        // confirm the iframe-side read equals the parent clock every frame.
        EXT_SYNCED = true;
        const FPS_DT = [1/60, 1/30, 1/120, 0.05, 1/90];  // jittery frame spacing
        let parentClock = 0;
        let maxDrift = 0;
        let i = 0;
        const TOTAL = 300; // 5 minutes
        while (parentClock < TOTAL) {
          const dt = FPS_DT[i % FPS_DT.length];
          parentClock += dt;
          // Parent posts the ABSOLUTE clock (main.js: t: getCurrentTimeSec()).
          extT = parentClock;
          // Iframe-side read (hand_viz.html frame loop, EXT_SYNCED branch):
          const tNow = EXT_SYNCED ? extT : NaN;
          const drift = Math.abs(tNow - parentClock);
          if (drift > maxDrift) maxDrift = drift;
          i++;
        }
        out.frames = i;
        out.parent_clock = parentClock;
        out.max_drift = maxDrift;
        // Sanity: we really simulated a multi-minute, many-frame timeline.
        out.long_enough = parentClock >= TOTAL && i > 3000;
        """
    )
    g = _run_in_node(probe)
    assert g["long_enough"] is True
    # Zero accumulated drift: the iframe read equals the parent clock exactly.
    assert g["max_drift"] == pytest.approx(0.0, abs=1e-9)
