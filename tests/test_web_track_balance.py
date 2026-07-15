"""Backing-track mix balance (Lot G).

The open (primary) track is MIDI channel 0 and its level is owned by the UI
slider. Every *other* track used to get a flat 0.8, which does not balance a
real arrangement: Stairway to Heaven ships five guitars, one bass, one drum kit
and a vocal line — five same-timbre sources at 0.8 bury the lone bass at 0.8,
and the ten backing tracks together bury the open track.

``_rebalanceSecondaryChannels`` fixes that with two rules: a per-kind level, and
equal-power sharing inside a kind (N same-kind tracks each get level/sqrt(N)).

These tests execute the real ``playback.js`` in Node rather than grepping the
source, so they fail if the behaviour regresses, not just if the text moves.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

_PLAYBACK_JS = (
    Path(__file__).parents[1] / "src" / "fretwise" / "web" / "static" / "js" / "playback.js"
)

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not available")


def _run(script: str) -> dict:
    """Run a Node snippet with PlaybackEngine imported; return its JSON stdout."""
    # A file:// URL, not a bare path: Node rejects absolute Windows paths as ESM
    # specifiers (ERR_UNSUPPORTED_ESM_URL_SCHEME — the drive letter reads as a scheme).
    harness = f"""
import {{ PlaybackEngine }} from {json.dumps(_PLAYBACK_JS.as_uri())};

// The engine only touches the renderer lazily; a stub is enough to construct it.
const renderer = {{ tempo: 120, bpm: 4, measures: [], measureNumbers: [] }};
const engine = new PlaybackEngine(renderer, {{ tempo: 120, beatsPerMeasure: 4 }});

// Ids must keep increasing across calls: addSecondaryChannel replaces a track
// with the same id, which would silently drop state a test just set up.
let _nextTrackId = 1;
function addTracks(specs) {{
  specs.forEach((s) => {{
    const id = _nextTrackId++;
    engine.addSecondaryChannel(id, s.name ?? `t${{id}}`, [], 4, s.program ?? 25, s.kind);
  }});
}}
function levels() {{
  return engine._secondaryChannels.map((c) => ({{
    trackId: c.trackId, kind: c.kind, gain: Number(c.gain.toFixed(4)),
    midiChannel: c.midiChannel, manual: !!c.gainManual,
  }}));
}}
{script}
"""
    proc = subprocess.run(
        ["node", "--input-type=module", "-e", harness],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert proc.returncode == 0, f"node failed:\n{proc.stderr}"
    return json.loads(proc.stdout)


def test_single_track_of_each_kind_gets_its_kind_level() -> None:
    """One track per kind → each sits at its mixing-desk level, unshared."""
    out = _run("""
addTracks([
  { kind: 'bass' }, { kind: 'drums' }, { kind: 'vocal' },
  { kind: 'guitar' }, { kind: 'other' },
]);
console.log(JSON.stringify(Object.fromEntries(levels().map(l => [l.kind, l.gain]))));
""")
    assert out == {
        "bass": 0.85,
        "drums": 0.75,
        "vocal": 0.80,
        "guitar": 0.62,
        "other": 0.55,
    }


def test_same_kind_tracks_share_level_equal_power() -> None:
    """Five guitars each get level/sqrt(5) — the section sits where one guitar would."""
    out = _run("""
addTracks([
  { kind: 'guitar' }, { kind: 'guitar' }, { kind: 'guitar' },
  { kind: 'guitar' }, { kind: 'guitar' },
]);
console.log(JSON.stringify(levels().map(l => l.gain)));
""")
    expected = round(0.62 / 5**0.5, 4)
    assert out == [expected] * 5
    assert all(g < 0.62 for g in out), "sharing must lower each guitar, not raise it"


def test_five_guitars_do_not_bury_the_lone_bass() -> None:
    """The Stairway case: one bass must stay above any single guitar in the stack."""
    out = _run("""
addTracks([
  { kind: 'guitar' }, { kind: 'guitar' }, { kind: 'guitar' },
  { kind: 'guitar' }, { kind: 'guitar' }, { kind: 'bass' },
  { kind: 'drums' }, { kind: 'vocal' },
]);
console.log(JSON.stringify(levels().map(l => ({ kind: l.kind, gain: l.gain }))));
""")
    by_kind = {}
    for entry in out:
        by_kind.setdefault(entry["kind"], []).append(entry["gain"])
    guitar = by_kind["guitar"][0]
    assert by_kind["bass"][0] > guitar
    assert by_kind["drums"][0] > guitar
    assert by_kind["vocal"][0] > guitar


def test_removing_a_track_rebalances_the_survivors() -> None:
    """Dropping one of two guitars gives the remaining one the full guitar level."""
    out = _run("""
addTracks([{ kind: 'guitar' }, { kind: 'guitar' }]);
const before = levels()[0].gain;
engine.removeSecondaryChannel(2);
const after = levels()[0].gain;
console.log(JSON.stringify({ before, after }));
""")
    assert out["before"] == round(0.62 / 2**0.5, 4)
    assert out["after"] == 0.62


def test_unknown_kind_falls_back_to_default_level() -> None:
    """A kind the mix table doesn't know must not yield NaN/undefined gain."""
    out = _run("""
addTracks([{ kind: 'theremin' }]);
console.log(JSON.stringify(levels()[0]));
""")
    assert out["gain"] == 0.62
    assert out["kind"] == "theremin"


def test_missing_kind_defaults_to_other() -> None:
    """No kind from the backend (MusicXML/MIDI) → mixed as a supporting part."""
    out = _run("""
engine.addSecondaryChannel(1, 'unnamed', [], 4, 25, undefined);
console.log(JSON.stringify(levels()[0]));
""")
    assert out["kind"] == "other"
    assert out["gain"] == 0.55


def test_drum_track_without_kind_still_mixes_as_drums() -> None:
    """Percussion is detected by name; it must mix as drums, not as 'other'."""
    out = _run("""
engine.addSecondaryChannel(1, 'John Bonham | Drums', [], 4, 0, undefined);
console.log(JSON.stringify(levels()[0]));
""")
    assert out["kind"] == "drums"
    assert out["gain"] == 0.75
    assert out["midiChannel"] == 9, "drums must stay on the GM percussion channel"


def test_manual_level_survives_a_rebalance() -> None:
    """An explicit user level must not be overwritten when another track loads."""
    out = _run("""
addTracks([{ kind: 'guitar' }]);
const ch = engine._secondaryChannels[0].midiChannel;
engine.setChannelVolume(ch, 0.2);           // user pulls this track down
addTracks([{ kind: 'guitar' }]);            // another guitar arrives -> rebalance
console.log(JSON.stringify(levels()));
""")
    manual = next(entry for entry in out if entry["manual"])
    assert manual["gain"] == 0.2, "rebalance clobbered the user's explicit level"


def test_primary_channel_volume_is_not_a_secondary_and_stays_slider_owned() -> None:
    """setChannelVolume(0) drives the open track only; backing levels are untouched."""
    out = _run("""
addTracks([{ kind: 'guitar' }, { kind: 'bass' }]);
const before = levels().map(l => l.gain);
engine.setChannelVolume(0, 0.35);
console.log(JSON.stringify({
  primary: engine.primaryVolume,
  before, after: levels().map(l => l.gain),
  manual: levels().map(l => l.manual),
}));
""")
    assert out["primary"] == 0.35
    assert out["after"] == out["before"]
    assert out["manual"] == [False, False], "channel 0 must not pin a backing track"
