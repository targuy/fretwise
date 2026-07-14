"""Tests for ``fretwise.playback.build_performance`` — the P1 phrasing engine.

Locks the musical contract the browser player relies on: velocity from dynamics
× articulation, sounding duration (articulation-scaled + let-ring look-ahead),
and a dense pitch-bend curve for bends/slides/vibrato (the fix for the old
stair-stepped bends).
"""

from __future__ import annotations

from typing import Any

from fretwise.playback import build_performance


def _note(**kw: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "pitch": 60, "onset": 0.0, "duration": 1.0, "tempo": 120.0,
        "articulation": "normal", "dynamic": "mf", "string": 3,
    }
    base.update(kw)
    return base


def _perf(note: dict[str, Any]) -> dict[str, Any]:
    build_performance([note])
    return note["perf"]


# ── velocity ──────────────────────────────────────────────────────────────

def test_velocity_from_dynamic() -> None:
    assert _perf(_note(dynamic="mf"))["velocity"] == 80
    assert _perf(_note(dynamic="ff"))["velocity"] == 112
    assert _perf(_note(dynamic="pp"))["velocity"] == 32


def test_velocity_unknown_dynamic_defaults_to_80() -> None:
    assert _perf(_note(dynamic="sfz"))["velocity"] == 80


def test_accent_raises_ghost_lowers_velocity() -> None:
    assert _perf(_note(accent_strong=True))["velocity"] == max(1, round(80 * 1.32))
    assert _perf(_note(ghost=True))["velocity"] == round(80 * 0.45)


def test_velocity_clamped_to_1_127() -> None:
    v = _perf(_note(dynamic="ff", accent_strong=True, slap=True, golpe=True))["velocity"]
    assert 1 <= v <= 127


# ── duration / articulation ─────────────────────────────────────────────────

def test_plain_note_keeps_its_duration() -> None:
    assert _perf(_note(duration=2.0))["dur_beats"] == 2.0


def test_staccato_shortens() -> None:
    assert _perf(_note(duration=1.0, staccato=True))["dur_beats"] == 0.45


def test_palm_mute_shortens() -> None:
    assert _perf(_note(duration=1.0, palm_muted=True))["dur_beats"] == 0.55


def test_hammer_on_is_legato_no_attack() -> None:
    p = _perf(_note(articulation="hammer_on"))
    assert p["attack"] is False
    # velocity softened by the hammer/pull 0.82 factor
    assert p["velocity"] == round(80 * 0.82)


def test_plain_note_has_attack() -> None:
    assert _perf(_note())["attack"] is True


# ── let ring look-ahead ─────────────────────────────────────────────────────

def test_let_ring_extends_to_next_note_on_same_string() -> None:
    notes = [
        _note(onset=0.0, duration=1.0, string=3, let_ring=True),
        _note(onset=4.0, duration=1.0, string=3),  # same string, 4 beats later
    ]
    build_performance(notes)
    # Rings up to ~just before the next strike (4.0 - 0.02).
    assert abs(notes[0]["perf"]["dur_beats"] - 3.98) < 1e-6


def test_let_ring_ignores_other_strings() -> None:
    notes = [
        _note(onset=0.0, duration=1.0, string=3, let_ring=True),
        _note(onset=2.0, duration=1.0, string=5),  # different string
        _note(onset=6.0, duration=1.0, string=3),  # next on string 3
    ]
    build_performance(notes)
    assert abs(notes[0]["perf"]["dur_beats"] - 5.98) < 1e-6


def test_let_ring_with_no_later_note_rings_out_capped() -> None:
    p = _perf(_note(duration=1.0, string=3, let_ring=True))
    assert p["dur_beats"] == 1.0 + 8.0  # articulated + max_ring_beats


def test_let_ring_cap_is_honoured() -> None:
    notes = [
        _note(onset=0.0, duration=1.0, string=3, let_ring=True),
        _note(onset=100.0, duration=1.0, string=3),
    ]
    build_performance(notes, max_ring_beats=6.0)
    assert notes[0]["perf"]["dur_beats"] == 1.0 + 6.0


# ── bend / slide / vibrato curve ────────────────────────────────────────────

def test_plain_note_has_no_bend_curve() -> None:
    assert _perf(_note())["bend"] is None


def test_bend_produces_dense_smooth_curve() -> None:
    # A one-beat bend at 120bpm = 0.5s → ~0.5/0.018 ≈ 28 samples (+reset).
    p = _perf(_note(duration=1.0, bend_value=2.0, bend_type="normal"))
    curve = p["bend"]
    assert curve is not None
    assert len(curve) >= 8, "curve must be densely sampled, not stair-stepped"
    # Monotone-ish rise to the 2-semitone target then hold.
    semis = [pt[1] for pt in curve]
    assert max(semis) >= 1.9
    # Starts near 0.
    assert abs(curve[0][1]) < 0.2
    # Ends recentered.
    assert curve[-1][1] == 0.0
    # Offsets are in beats within the note span (+ a small reset tail).
    assert curve[0][0] == 0.0
    assert curve[-1][0] <= 1.0 + 0.05


def test_prebend_starts_already_bent() -> None:
    p = _perf(_note(duration=1.0, bend_value=2.0, bend_type="pre_bend"))
    curve = p["bend"]
    assert curve is not None
    assert curve[0][1] >= 1.9  # pre-bent from the very start


def test_shift_slide_targets_next_note_on_string() -> None:
    notes = [
        _note(onset=0.0, duration=1.0, pitch=60, string=3, slide_type="shift"),
        _note(onset=1.0, duration=1.0, pitch=64, string=3),  # +4 semitones
    ]
    build_performance(notes)
    curve = notes[0]["perf"]["bend"]
    assert curve is not None
    # The slide should reach about +4 semitones by the end of the gesture.
    assert max(pt[1] for pt in curve) >= 3.5


def test_vibrato_oscillates() -> None:
    p = _perf(_note(duration=2.0, articulation="vibrato"))
    curve = p["bend"]
    assert curve is not None
    semis = [pt[1] for pt in curve]
    assert max(semis) > 0.1 and min(semis) < -0.1, "vibrato must swing both ways"


def test_wide_vibrato_swings_wider_than_normal() -> None:
    normal = _perf(_note(duration=2.0, articulation="vibrato"))["bend"]
    wide = _perf(_note(duration=2.0, articulation="vibrato", vibrato_wide=True))["bend"]
    assert max(pt[1] for pt in wide) > max(pt[1] for pt in normal)


# ── staff-only tracks (no string) ───────────────────────────────────────────

def test_note_without_string_still_gets_velocity_and_duration() -> None:
    p = _perf(_note(string=None, duration=1.5, dynamic="f"))
    assert p["velocity"] == 96
    assert p["dur_beats"] == 1.5
    assert p["bend"] is None
