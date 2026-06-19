"""Geometry-generalization tests for the fretboard hand-viz renderer (M2).

Milestone 1 locked the panel wiring (see ``test_web_hand_viz.py``).  Milestone 2
generalizes the renderer so non-standard fretboards render correctly: drop
tunings, capos, 7/8-string necks and notes above the old hard-coded 15th fret.

Two layers of coverage:

1. **Static source guards** (always run, no JS engine needed) — assert the
   payload builder (``main.js``) and the renderer (``hand_viz.html``) no longer
   hard-code 15 frets / 6 strings / standard tuning, and instead derive geometry
   from the payload's ``fretboard`` block.

2. **Behavioural geometry checks** (run only when ``node`` is available) — load
   the renderer's geometry functions in a stubbed DOM and verify the actual
   numbers for several configurations:
     * standard 6-string (backward-compatibility / default fallbacks),
     * drop-D (low string D2 = MIDI 38) — string count + tempered fret X,
     * a capo at fret 3 — open-string MIDI base shifts,
     * a 7-string neck — string count + per-string Y spacing,
     * a payload whose highest fret is above 15 — fret count grows past 15,
   including the equal-tempered fret X positions (12-TET ``1 - 2^(-f/12)``).
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

# Renderer constants, mirrored here so the expected geometry is independent of
# the implementation we are testing (NUT_X / SCALE_PX / string Y band).
_NUT_X = 110.0
_SCALE_PX = 1120.0
_STRING_Y_TOP = 230.0
_STRING_Y_BOTTOM = 350.0


def _expected_fret_x(fret: int) -> float:
    """Equal-tempered fret X in the renderer's px space (12-TET)."""
    if fret <= 0:
        return _NUT_X
    return _NUT_X + _SCALE_PX * (1.0 - 2.0 ** (-fret / 12.0))


def _expected_string_y(string: int, num_strings: int) -> float:
    spacing = (_STRING_Y_BOTTOM - _STRING_Y_TOP) / (num_strings - 1)
    return _STRING_Y_TOP + (string - 1) * spacing


# --------------------------------------------------------------------------- #
# Layer 1 — static source guards (no JS engine required).
# --------------------------------------------------------------------------- #
def test_payload_builder_threads_real_geometry() -> None:
    """``_buildHandVizPayload`` derives geometry from the track, not constants."""
    js = _MAIN_JS.read_text(encoding="utf-8")
    builder = js[js.index("function _buildHandVizPayload"):]
    builder = builder[: builder.index("\nfunction _postHandVizData")]
    # num_frets follows the music (highest fret + headroom, floor of 12).
    assert "Math.max(12, highestFret + 2)" in builder
    assert "num_frets: numFrets" in builder
    # tuning comes from the active track's real open-string MIDI pitches.
    assert "currentTracks" in builder
    assert "activeTrack.tuning" in builder
    assert "_midiToNoteName" in builder
    # scale_length / capo are threaded when the source exposes them.
    assert "scale_length_mm: scaleLengthMm" in builder
    assert "capo," in builder
    # The old hard-coded geometry block must be gone.
    assert "num_frets: 15" not in builder
    # Standard tuning now appears only as a fallback, not as the sole source.
    assert builder.count("['E2', 'A2', 'D3', 'G3', 'B3', 'E4']") == 1
    assert ": trackTuning" in builder or "trackTuning.map" in builder


def test_renderer_geometry_is_derived_not_hardcoded() -> None:
    """The renderer exposes mutable geometry recomputed at installData time."""
    html = _HAND_VIZ.read_text(encoding="utf-8")
    # Geometry is mutable (let), not const.
    assert "let NUM_FRETS" in html
    assert "let NUM_STRINGS" in html
    assert "let STRING_MIDI_BASE" in html
    assert "let SCALE_LENGTH_MM" in html
    assert "let CAPO_FRET" in html
    # configureGeometry exists and runs before the fretboard/sim are built.
    assert "function configureGeometry(data)" in html
    install = html[html.index("function installData(data)"):]
    install = install[: install.index("\n}")]
    assert "configureGeometry(data)" in install
    # The old hard 6-string / 15-fret assumptions are gone.
    assert "const NUM_FRETS = 15" not in html
    assert "const STRING_MIDI_BASE = " not in html
    assert "for (let s = 6; s >= 1; s--)" not in html
    assert "for (let s = 1; s <= 6; s++)" not in html


# --------------------------------------------------------------------------- #
# Layer 2 — behavioural geometry via node (skipped when node is absent).
# --------------------------------------------------------------------------- #
_NODE = shutil.which("node")


def _run_geometry_in_node(payload: dict) -> dict:
    """Execute the renderer's geometry on ``payload`` in a stubbed DOM via node.

    Extracts the inline ``<script>`` from ``hand_viz.html``, runs it with a
    minimal DOM/window/fetch/raf stub (so the boot IIFE is a no-op), then calls
    ``configureGeometry`` and probes the geometry helpers.  Returns the probed
    values as a dict.
    """
    html = _HAND_VIZ.read_text(encoding="utf-8")
    m = re.search(r"<script>(.*)</script>", html, re.DOTALL)
    assert m, "renderer must contain an inline <script> block"
    script = m.group(1)

    harness = (
        textwrap.dedent(
            """
            // ---- Minimal DOM / window stubs so the boot IIFE is inert. ----
            function FakeEl() {}
            FakeEl.prototype.setAttribute = function () {};
            FakeEl.prototype.appendChild = function () {};
            FakeEl.prototype.removeChild = function () {};
            Object.defineProperty(FakeEl.prototype, 'firstChild', { get() { return null; } });
            FakeEl.prototype.style = {};
            FakeEl.prototype.textContent = '';
            FakeEl.prototype.addEventListener = function () {};
            const _doc = {
              createElementNS: () => new FakeEl(),
              getElementById: () => new FakeEl(),
            };
            globalThis.document = _doc;
            globalThis.window = {
              addEventListener: () => {},
              parent: null,
              postMessage: () => {},
            };
            globalThis.performance = { now: () => 0 };
            globalThis.requestAnimationFrame = () => 0;   // no animation loop
            globalThis.fetch = () => Promise.reject(new Error('no fetch in test'));
            """
        )
        + "\n"
        + script
        + "\n"
        + textwrap.dedent(
            """
            // ---- Probe the geometry on the supplied payload. ----
            const PAYLOAD = __PAYLOAD__;
            configureGeometry(PAYLOAD);
            const probeFrets = [0, 1, 5, 12, 15, 17, 22];
            const out = {
              NUM_FRETS,
              NUM_STRINGS,
              SCALE_LENGTH_MM,
              CAPO_FRET,
              STRING_MIDI_BASE: STRING_MIDI_BASE.slice(),
              STRING_SPACING,
              fretX: probeFrets.map(f => [f, fretX(f)]),
              stringY: Array.from({length: NUM_STRINGS}, (_, i) => [i + 1, stringY(i + 1)]),
              // midiForPosition folds in the capo; probe a couple of positions.
              midi_lowstring_open: midiForPosition(NUM_STRINGS, 0),
              midi_str1_fret5: midiForPosition(1, 5),
            };
            process.stdout.write(JSON.stringify(out));
            """
        ).replace("__PAYLOAD__", json.dumps(payload))
    )

    proc = subprocess.run(
        [_NODE, "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


pytestmark_node = pytest.mark.skipif(_NODE is None, reason="node not available")


@pytestmark_node
def test_geometry_standard_six_string_defaults() -> None:
    """A standard 6-string payload reproduces the historical geometry."""
    payload = {
        "fretboard": {
            "num_frets": 15,
            "scale_length_mm": 648,
            "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
            "capo": 0,
            "num_strings": 6,
        },
        "frames": [],
    }
    g = _run_geometry_in_node(payload)
    assert g["NUM_FRETS"] == 15
    assert g["NUM_STRINGS"] == 6
    assert g["CAPO_FRET"] == 0
    # high→low: string 1 = high E (64) .. string 6 = low E (40).
    assert g["STRING_MIDI_BASE"] == [64, 59, 55, 50, 45, 40]
    for fret, x in g["fretX"]:
        assert x == pytest.approx(_expected_fret_x(fret), abs=1e-6)
    for s, y in g["stringY"]:
        assert y == pytest.approx(_expected_string_y(s, 6), abs=1e-6)


@pytestmark_node
def test_geometry_drop_d_low_string_is_d2() -> None:
    """Drop-D: the lowest string is D2 (MIDI 38), everything else standard."""
    payload = {
        "fretboard": {
            "tuning": ["D2", "A2", "D3", "G3", "B3", "E4"],
        },
        "frames": [{"string": 6, "fret": 5, "finger": "index"}],
    }
    g = _run_geometry_in_node(payload)
    assert g["NUM_STRINGS"] == 6
    # string 6 (lowest, bottom) is now D2 = 38 instead of E2 = 40.
    assert g["STRING_MIDI_BASE"][-1] == 38
    assert g["midi_lowstring_open"] == 38
    # Tempered fret X math is unchanged by tuning.
    for fret, x in g["fretX"]:
        assert x == pytest.approx(_expected_fret_x(fret), abs=1e-6)


@pytestmark_node
def test_geometry_capo_shifts_open_string_midi() -> None:
    """A capo at fret 3 raises every open-string pitch by 3 semitones."""
    payload = {
        "fretboard": {
            "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
            "capo": 3,
        },
        "frames": [],
    }
    g = _run_geometry_in_node(payload)
    assert g["CAPO_FRET"] == 3
    # Low E open with capo 3 -> G2 (40 + 3 = 43).
    assert g["midi_lowstring_open"] == 43
    # High E string, pressed at fret 5, with capo 3 -> 64 + 3 + 5 = 72.
    assert g["midi_str1_fret5"] == 72


@pytestmark_node
def test_geometry_seven_string_count_and_spacing() -> None:
    """A 7-string neck renders 7 strings filling the same Y band."""
    payload = {
        "fretboard": {
            # low B (35) .. high E (64): 7 strings, low→high.
            "tuning": ["B1", "E2", "A2", "D3", "G3", "B3", "E4"],
        },
        "frames": [{"string": 7, "fret": 3, "finger": "index"}],
    }
    g = _run_geometry_in_node(payload)
    assert g["NUM_STRINGS"] == 7
    assert len(g["STRING_MIDI_BASE"]) == 7
    # high→low: string 1 = high E (64), string 7 = low B (35).
    assert g["STRING_MIDI_BASE"][0] == 64
    assert g["STRING_MIDI_BASE"][-1] == 35
    # Seven strings fill the fixed band -> spacing = 120 / 6 = 20.
    assert g["STRING_SPACING"] == pytest.approx((350 - 230) / 6, abs=1e-6)
    for s, y in g["stringY"]:
        assert y == pytest.approx(_expected_string_y(s, 7), abs=1e-6)
    # Top and bottom strings pin the band edges.
    assert g["stringY"][0][1] == pytest.approx(_STRING_Y_TOP, abs=1e-6)
    assert g["stringY"][-1][1] == pytest.approx(_STRING_Y_BOTTOM, abs=1e-6)


@pytestmark_node
def test_geometry_high_fret_grows_neck_past_fifteen() -> None:
    """A payload using fret 17 yields a neck longer than the old 15-fret cap."""
    payload = {
        "fretboard": {
            "tuning": ["E2", "A2", "D3", "G3", "B3", "E4"],
            "num_frets": 19,   # what the builder would compute for highest=17.
        },
        "frames": [{"string": 1, "fret": 17, "finger": "index"}],
    }
    g = _run_geometry_in_node(payload)
    assert g["NUM_FRETS"] == 19
    # Fret 17 has a defined, monotonically-increasing tempered X.
    x15 = _expected_fret_x(15)
    x17 = _expected_fret_x(17)
    assert x17 > x15
    probe = {f: x for f, x in g["fretX"]}
    assert probe[17] == pytest.approx(x17, abs=1e-6)
    # Still inside the scene width (NUT_X + SCALE_PX = 1230 < 1440).
    assert probe[17] < 1440
