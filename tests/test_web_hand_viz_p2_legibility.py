"""Guard tests for P2 board-legibility mechanisms (H-4/H-5/H-7, T-P2.1..T-P2.3).

Mirrors the other test_web_hand_viz*.py source-presence guards. Behavior
(cell dimensions, open-string highlight timing, fret-0..22 sprite count) was
verified interactively — see docs/plan_impl_slope_main3d.md §5 — including a
synthetic open-string note (the demo song has none) confirming the highlight
turns on for the note's duration and off afterward, with only the played
string's material/cell affected.
"""
from __future__ import annotations

from pathlib import Path

_STATIC_DIR = Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static"


def _hand3d_js() -> str:
    return (_STATIC_DIR / "js" / "hand3d.js").read_text(encoding="utf-8")


def _hand_viz_html() -> str:
    return (_STATIC_DIR / "hand_viz.html").read_text(encoding="utf-8")


def test_fret_numbering_starts_at_zero_not_two() -> None:
    """H-4: the nut (open string) must carry a '0' label; the old loop
    started at fret 2, silently dropping both '0' and '1'."""
    js = _hand3d_js()
    assert 'this._addFretNumber(0, wx(fretX(0)), dotY + 0.16, boardZ0 + boardWidthZ * 0.06);' in js
    assert "for (let fr = 1; fr <= visibleFrets; fr++) {" in js
    assert "for (let fr = 2; fr <= visibleFrets; fr++) {" not in js


def test_played_cell_spans_the_full_fret_space_and_string_spacing() -> None:
    """H-5: the cell is the fret-space (wire r-1 to wire r) by one full
    inter-string spacing — not an arbitrary fraction of either."""
    js = _hand3d_js()
    method_start = js.index("_updatePlayedFrets(kin) {")
    method_end = js.index("\n  }", method_start)
    body = js[method_start:method_end]
    assert "Math.abs(x1 - x0) * 0.95" in body
    assert "(this._stringSpacing || 1) * 0.92" in body


def test_open_string_lighting_mechanism_present() -> None:
    """H-7: an open-string note (no finger involved) must light the string
    itself and a nut-side cell for its duration — this was previously
    entirely unimplemented in the 3D view (0 visual feedback)."""
    js = _hand3d_js()
    assert "_updateOpenStrings(kin) {" in js
    method_start = js.index("_updateOpenStrings(kin) {")
    method_end = js.index("\n  }", method_start)
    body = js[method_start:method_end]
    assert "kin.openStrings" in body
    assert "mesh.material = isOpen ? this._openStringHotMat : this._stringBaseMat[s]" in body
    # Each string mesh must keep its OWN material reference (not a shared
    # one) so relighting string s never affects its neighbours.
    assert "this._stringBaseMat[s] = baseMat;" in js


def test_open_strings_forwarded_from_shared_simulator_state() -> None:
    """buildKinSnapshot must forward sampleState()'s already
    duration-filtered openStrings Set, not recompute open/closed itself
    (single source of truth, matching the rest of buildKinSnapshot)."""
    html = _hand_viz_html()
    assert "function buildKinSnapshot(sim, sampled) {" in html
    assert "openStrings: sampled ? sampled.openStrings : new Set()," in html
    assert "HAND3D_RENDERER.update(buildKinSnapshot(CURRENT_SIM, getSampledState()));" in html


def test_guitar_body_anchored_beyond_the_last_fret() -> None:
    """H-3: the dedicated view's guitar body must never overlap the fret
    span — it's anchored past the last visible fret (x1), not at a fixed
    offset that could drift into occluding territory as fret count changes.
    Verified live: body group x=76.5 vs neckX1=51.4 (25wu clearance);
    headstock group x=-187.1 sits before the nut, the opposite side."""
    js = _hand3d_js()
    assert "body.position.set(x1 + mm(58), -1.5, 0);" in js
