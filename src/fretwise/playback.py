"""Performance phrasing for web playback.

Turns the raw per-note data (pitch, onset, duration, articulation, effects)
into an explicit *performance* directive per note — velocity, sounding
duration, and a densely-sampled pitch-bend curve — so the browser player can
apply expression verbatim instead of re-deriving it inline.

Why this exists (P1): the JS player computed expression note-by-note, with two
weaknesses this module fixes at the source (and makes unit-testable):

* **Bends/slides/vibrato were stair-stepped.** MIDI pitch-wheel is a step
  change held until the next message; the player emitted only the envelope's
  corner points, so a bend jumped in coarse steps instead of gliding. Here we
  sample the envelope densely (~20 ms) so the same pitch-wheel path sounds
  smooth.
* **Let ring was a flat ×1.35.** A let-ring note should sustain until the same
  string is played again. With per-string look-ahead we extend its sounding
  duration to the next note on that string (capped), so arpeggios and chords
  ring the way the tab intends.

Everything is expressed in **quarter-note beats** (the parser's onset/duration
unit); the tempo→seconds conversion stays in the player (per-measure, from the
tempo map). The one place tempo is used here is picking the bend sample count so
the curve targets ~20 ms spacing — for that we read each note's own ``tempo``.
"""

from __future__ import annotations

import math
from typing import Any

# GM velocity per dynamic marking (matches the player's _dynamicToVelocity).
_DYNAMIC_VELOCITY: dict[str, int] = {
    "pp": 32, "p": 48, "mp": 64, "mf": 80, "f": 96, "ff": 112,
}
_DEFAULT_VELOCITY = 80

# Target spacing between successive pitch-bend samples, in seconds. Small enough
# that the stepped pitch-wheel reads as a smooth glide, large enough to keep the
# event count modest. Bounded by _BEND_MIN_SAMPLES.._BEND_MAX_SAMPLES per note.
_BEND_TARGET_DT = 0.018
_BEND_MIN_SAMPLES = 8
_BEND_MAX_SAMPLES = 64

# Fixed slide amounts (semitones) for slides with no explicit target note.
_SLIDE_IN_ABOVE = 2.0
_SLIDE_IN_BELOW = -2.0
_SLIDE_OUT_UP = 2.0
_SLIDE_OUT_DOWN = -2.0


def _dynamic_velocity(dynamic: Any) -> int:
    return _DYNAMIC_VELOCITY.get(str(dynamic), _DEFAULT_VELOCITY)


def _is_legato(note: dict[str, Any]) -> bool:
    """A hammer-on / pull-off note that should slur from the previous one."""
    return str(note.get("articulation")) in ("hammer_on", "pull_off")


def _velocity_for(note: dict[str, Any]) -> int:
    """Final MIDI velocity: dynamic marking scaled by articulation accents.

    Ports the player's _expressionForNote velocity scaling exactly so the
    perf-path and the legacy fallback stay in agreement.
    """
    scale = 1.0
    if note.get("ghost"):
        scale *= 0.45
    if note.get("muted"):
        scale *= 0.65
    if note.get("palm_muted"):
        scale *= 0.78
    if note.get("accent"):
        scale *= 1.15
    if note.get("accent_strong"):
        scale *= 1.32
    if note.get("slap") or note.get("pop"):
        scale *= 1.22
    if note.get("golpe"):
        scale *= 1.35
    if note.get("tapping"):
        scale *= 1.1
    if note.get("rasgueado"):
        scale *= 1.12
    art = str(note.get("articulation"))
    if art in ("hammer_on", "pull_off"):
        scale *= 0.82
    elif art == "legato":
        scale *= 0.9
    vel = round(_dynamic_velocity(note.get("dynamic")) * scale)
    return max(1, min(127, vel))


def _articulation_duration_beats(note: dict[str, Any]) -> float:
    """Sounding duration in beats from articulation alone (no let-ring yet).

    Mirrors the player's _expressionForNote duration scaling, minus the absolute
    0.12 s muted floor (which needs tempo and is applied per-measure downstream).
    """
    dur = float(note.get("duration", 0.0) or 0.0)
    art = str(note.get("articulation"))
    if note.get("palm_muted"):
        dur *= 0.55
    if note.get("staccato") or art == "staccato":
        dur *= 0.45
    if note.get("rasgueado"):
        dur *= 0.82
    if art in ("hammer_on", "pull_off"):
        dur *= 1.08
    elif art == "legato":
        dur *= 1.12
    if note.get("muted") or note.get("golpe"):
        dur *= 0.28
    return max(0.01, dur)


def _let_ring_duration_beats(
    note: dict[str, Any],
    next_same_string_onset: float | None,
    articulated: float,
    max_ring_beats: float,
) -> float:
    """Extend a let-ring note's sounding duration to the next use of its string.

    The note rings until the same string is struck again; with no later note on
    that string it rings out to ``max_ring_beats``. Never shorter than the note's
    own articulated duration.
    """
    onset = float(note.get("onset", 0.0) or 0.0)
    if next_same_string_onset is not None:
        # Ring right up to (a hair before) the next strike on this string.
        target = max(0.0, next_same_string_onset - onset - 0.02)
    else:
        target = articulated + max_ring_beats
    return max(articulated, min(target, articulated + max_ring_beats))


def _slide_target_semitones(
    note: dict[str, Any],
    slide_type: str,
    next_same_string_pitch: float | None,
) -> float | None:
    """Semitone target of a slide, or None when it can't be determined."""
    if slide_type == "slide_in_above":
        return _SLIDE_IN_ABOVE
    if slide_type == "slide_in_below":
        return _SLIDE_IN_BELOW
    if slide_type == "slide_out_up":
        return _SLIDE_OUT_UP
    if slide_type == "slide_out_down":
        return _SLIDE_OUT_DOWN
    # Shift/legato slide: glide to the next note on the same string.
    if next_same_string_pitch is None:
        return None
    pitch = note.get("pitch")
    if not isinstance(pitch, (int, float)):
        return None
    return float(next_same_string_pitch) - float(pitch)


def _bend_control_points(
    note: dict[str, Any],
    next_same_string_pitch: float | None,
) -> list[tuple[float, float]]:
    """Piecewise-linear (frac, semitones) envelope for bend + slide.

    Ports the player's _basePitchPoints. ``frac`` is 0..1 of the bend span.
    Returns just ``[(0, 0)]`` when the note is neither bent nor slid.
    """
    points: list[tuple[float, float]] = []

    bend_value = note.get("bend_value")
    if isinstance(bend_value, (int, float)) and abs(float(bend_value)) > 0.001:
        bv = float(bend_value)
        btype = str(note.get("bend_type") or "normal")
        if btype == "release":
            points += [(0.0, bv), (0.68, 0.0)]
        elif btype == "pre_bend":
            points += [(0.0, bv), (0.9, bv)]
        elif btype == "pre_bend_release":
            points += [(0.0, bv), (0.78, 0.0)]
        else:  # normal bend: ramp up, hold
            points += [(0.34, bv), (0.9, bv)]

    raw_slide = note.get("slide_type")
    slide_type = raw_slide or ("shift" if str(note.get("articulation")) == "slide" else None)
    if slide_type:
        target = _slide_target_semitones(note, str(slide_type), next_same_string_pitch)
        if target is not None:
            if slide_type in ("slide_in_above", "slide_in_below"):
                points += [(0.0, target), (0.22, 0.0)]
            elif slide_type in ("slide_out_up", "slide_out_down"):
                points += [(0.2, 0.0), (0.85, target)]
            else:  # shift slide into the next note
                points += [(0.08, 0.0), (0.82, target)]

    # A pre-bend/shift-etc. may already pin frac 0; only backfill the implicit
    # "starts unbent" baseline when nothing claims that instant.
    if not any(p[0] == 0.0 for p in points):
        points.insert(0, (0.0, 0.0))

    points.sort(key=lambda p: p[0])
    return points


def _interpolate(points: list[tuple[float, float]], frac: float) -> float:
    """Linear interpolation of the (frac, semitones) envelope at ``frac``."""
    prev = points[0]
    for nxt in points[1:]:
        if frac <= nxt[0]:
            span = max(1e-4, nxt[0] - prev[0])
            t = max(0.0, min(1.0, (frac - prev[0]) / span))
            return prev[1] + (nxt[1] - prev[1]) * t
        prev = nxt
    return prev[1]


def _has_vibrato(note: dict[str, Any]) -> bool:
    art = str(note.get("articulation"))
    return art in ("vibrato", "wide_vibrato") or bool(note.get("vibrato_wide"))


def _bend_curve_beats(
    note: dict[str, Any],
    next_same_string_pitch: float | None,
    default_tempo: float,
) -> list[list[float]] | None:
    """Dense ``[beat_offset, semitones]`` pitch-bend curve, or None.

    ``beat_offset`` is in quarter-beats from the note onset. The envelope (bend +
    slide) is sampled densely, vibrato (a sine) added on top, and a final reset
    to 0 appended just past the span so the wheel recenters for the next note on
    the channel. Returns None when the note carries no pitch expression.
    """
    has_bend = isinstance(note.get("bend_value"), (int, float))
    has_slide = bool(note.get("slide_type")) or str(note.get("articulation")) == "slide"
    has_vib = _has_vibrato(note)
    if not (has_bend or has_slide or has_vib):
        return None

    # Bend timing follows the *notated* duration, not any let-ring extension —
    # the gesture belongs to the written note, not the sustain tail.
    span_beats = max(0.05, float(note.get("duration", 0.0) or 0.0))
    tempo = float(note.get("tempo") or 0.0) or default_tempo
    span_seconds = span_beats * 60.0 / max(1.0, tempo)
    n = int(round(span_seconds / _BEND_TARGET_DT))
    n = max(_BEND_MIN_SAMPLES, min(_BEND_MAX_SAMPLES, n))

    envelope = _bend_control_points(note, next_same_string_pitch)

    # Vibrato parameters (ported from _pitchSamplesForNote).
    wide = bool(note.get("vibrato_wide")) or str(note.get("articulation")) == "wide_vibrato"
    vib_amp = 0.45 if wide else 0.22
    vib_rate = 5.3 if wide else 6.2
    vib_start = min(0.35, 0.12 / span_seconds) if span_seconds > 0 else 0.0

    curve: list[list[float]] = []
    for i in range(n + 1):
        frac = i / n
        semis = _interpolate(envelope, frac)
        if has_vib and frac >= vib_start:
            semis += math.sin((frac - vib_start) * span_seconds * vib_rate * math.tau) * vib_amp
        curve.append([round(frac * span_beats, 5), round(semis, 4)])
    # Recenter the wheel just after the gesture.
    curve.append([round(span_beats + 0.02, 5), 0.0])
    return curve


def build_performance(
    notes: list[dict[str, Any]],
    *,
    default_tempo: float = 120.0,
    max_ring_beats: float = 8.0,
) -> list[dict[str, Any]]:
    """Attach a ``perf`` directive to each note dict (in place) and return them.

    ``perf`` fields consumed by the player's perf-path:

    * ``velocity`` — final MIDI velocity (1-127), dynamics × articulation.
    * ``dur_beats`` — sounding duration in quarter-beats (articulation-scaled,
      and let-ring-extended to the next use of the string).
    * ``attack`` — ``False`` for hammer-on/pull-off (slur; the player softens it).
    * ``bend`` — dense ``[beat_offset, semitones]`` curve, or ``None``.

    Notes are treated as one track (per-string look-ahead is within the list).
    Order is not assumed; look-ahead is computed from onsets. Notes with no
    string (staff-only tracks) still get velocity/duration, just no string-based
    let-ring or shift-slide target.

    Args:
        notes: Serialized note dicts (mutated in place).
        default_tempo: Fallback BPM when a note carries no ``tempo``.
        max_ring_beats: Cap on how long a let-ring note sustains.

    Returns:
        The same list, for convenience.
    """
    # Per string: the sorted (onset, pitch) of every note, to answer "next strike
    # on this string after t" for let-ring extension and shift-slide targets.
    by_string: dict[Any, list[tuple[float, Any]]] = {}
    for note in notes:
        s = note.get("string")
        if s is None:
            continue
        onset = float(note.get("onset", 0.0) or 0.0)
        by_string.setdefault(s, []).append((onset, note.get("pitch")))
    for events in by_string.values():
        events.sort(key=lambda e: e[0])

    def _next_on_string(string: Any, onset: float) -> tuple[float, Any] | None:
        events = by_string.get(string)
        if not events:
            return None
        for ev in events:
            if ev[0] > onset + 1e-5:
                return ev
        return None

    for note in notes:
        onset = float(note.get("onset", 0.0) or 0.0)
        string = note.get("string")
        nxt = _next_on_string(string, onset) if string is not None else None
        next_onset = nxt[0] if nxt else None
        next_pitch = nxt[1] if nxt and isinstance(nxt[1], (int, float)) else None

        articulated = _articulation_duration_beats(note)
        if note.get("let_ring"):
            dur_beats = _let_ring_duration_beats(note, next_onset, articulated, max_ring_beats)
        else:
            dur_beats = articulated

        note["perf"] = {
            "velocity": _velocity_for(note),
            "dur_beats": round(dur_beats, 5),
            "attack": not _is_legato(note),
            "bend": _bend_curve_beats(note, next_pitch, default_tempo),
        }
    return notes
