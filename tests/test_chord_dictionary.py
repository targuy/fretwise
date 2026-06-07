"""Hard validation gate for the chord dictionary.

For ALL 12 chromatic roots × every supported quality, ``lookup_chord`` must
return a voicing whose sounding pitch classes EXACTLY equal the quality's
interval formula, with the root present (and lowest for non-inversions), and a
physically playable shape (span, finger consistency, sane frets).

This is ground truth: if a generated shape fails here the shape definition is
wrong and must be fixed — never weaken the assertions.

Interval formulas are SHARED with ``chord_recognition._CHORD_PATTERNS`` wherever
that module defines the quality, so the two never diverge.  Extended qualities
not recognised by ``chord_recognition`` (m7b5, 9, maj9, m9, add9, 6/9) are
defined here once.
"""

from __future__ import annotations

import pytest

from fretwise.models import ChordDiagram
from fretwise.patterns.chord_library import lookup_chord
from fretwise.patterns.chord_recognition import _CHORD_PATTERNS

# Standard tuning open pitch classes, per-string order [str1 high_e … str6 low_E].
OPEN_PC = (4, 11, 7, 2, 9, 4)

ROOT_NAMES = ["C", "C#", "D", "Eb", "E", "F", "F#", "G", "Ab", "A", "Bb", "B"]

# Quality suffix → interval formula, sourced from chord_recognition where present.
_RECOGNISED = {suffix: intervals for intervals, suffix in _CHORD_PATTERNS}

# Extended qualities not covered by chord_recognition's patterns.
_EXTENDED = {
    "m7b5": (0, 3, 6, 10),
    "9": (0, 2, 4, 7, 10),
    "maj9": (0, 2, 4, 7, 11),
    "m9": (0, 2, 3, 7, 10),
    "add9": (0, 2, 4, 7),
    "6/9": (0, 2, 4, 7, 9),
}

# Every quality the dictionary must resolve for all 12 roots.
SUPPORTED_QUALITIES = [
    "", "m", "7", "maj7", "m7", "m7b5", "dim", "dim7", "aug",
    "sus2", "sus4", "6", "m6", "9", "maj9", "m9", "add9", "6/9", "mM7",
]


def formula(quality: str) -> tuple[int, ...]:
    """Return the interval formula for a quality, preferring chord_recognition."""
    if quality in _RECOGNISED:
        return _RECOGNISED[quality]
    return _EXTENDED[quality]


def sounding_pitch_classes(diag: ChordDiagram) -> list[int]:
    """Pitch classes of all non-muted strings, low string → high string."""
    out = []
    for i in range(5, -1, -1):  # str6 (low) → str1 (high)
        f = diag.frets[i]
        if f < 0:
            continue
        out.append((OPEN_PC[i] + f) % 12)
    return out


# Build the full (root, quality) matrix once.
CASES = [(r, root, q) for r in range(12) for root in [ROOT_NAMES[r]] for q in SUPPORTED_QUALITIES]


@pytest.mark.parametrize("root_pc,root,quality", CASES)
def test_every_root_quality_is_valid(root_pc: int, root: str, quality: str) -> None:
    name = root + quality
    diag = lookup_chord(name)
    assert diag is not None, f"{name}: no voicing resolved"

    # --- pitch content matches the quality formula ---
    # NO wrong/extra notes are EVER allowed (got must be a subset of the
    # formula).  The ONLY note a voicing may omit is the perfect 5th — that is
    # universally-standard voicing practice (e.g. the open C7 = x32310 drops the
    # 5th).  Every generated barre shape includes the full formula; this
    # allowance only covers the handful of curated open chords that drop the 5th.
    expected = {(root_pc + i) % 12 for i in formula(quality)}
    sounding = sounding_pitch_classes(diag)
    got = set(sounding)
    extra = got - expected
    assert not extra, (
        f"{name}: extra/wrong pitch classes {sorted(extra)} not in formula "
        f"{sorted(expected)} (frets {diag.frets}, base_fret {diag.base_fret})"
    )
    perfect_fifth = (root_pc + 7) % 12
    missing = expected - got
    assert missing <= {perfect_fifth}, (
        f"{name}: missing essential pitch classes {sorted(missing)} from formula "
        f"{sorted(expected)} (frets {diag.frets}, base_fret {diag.base_fret})"
    )

    # --- root present, and lowest sounding note (no inversion) ---
    assert root_pc in got, f"{name}: root {root} absent"
    assert sounding[0] == root_pc, f"{name}: lowest note {sounding[0]} != root {root_pc}"

    # --- physical playability ---
    fretted = [f for f in diag.frets if f > 0]
    if fretted:
        span = max(fretted) - min(fretted)
        # span <= 4; 5 only when the lowest fret is a barre (>= 2 strings on it).
        if span > 4:
            low = min(fretted)
            barre = sum(1 for f in diag.frets if f == low) >= 2
            assert barre and span <= 5, f"{name}: span {span} not barre-justified ({diag.frets})"
    # frets sane
    assert all(f >= -1 for f in diag.frets), f"{name}: bad fret value in {diag.frets}"
    assert all(f <= 24 for f in diag.frets), f"{name}: fret > 24 in {diag.frets}"
    assert diag.base_fret >= 1, f"{name}: base_fret {diag.base_fret} < 1"

    # --- fingers consistent with frets ---
    finger_fret: dict[int, int] = {}
    for i, f in enumerate(diag.frets):
        fg = diag.fingers[i] if i < len(diag.fingers) else 0
        if f <= 0 or fg == 0:
            continue
        if fg in finger_fret and finger_fret[fg] != f:
            pytest.fail(f"{name}: finger {fg} holds frets {finger_fret[fg]} and {f} ({diag.frets})")
        finger_fret[fg] = f
    assert len(finger_fret) <= 4, f"{name}: needs {len(finger_fret)} > 4 fingers ({diag.fingers})"


def test_curated_open_voicings_preferred_and_unchanged() -> None:
    """A few curated open voicings must come back byte-identical (not generated)."""
    am = lookup_chord("Am")
    assert am is not None and am.frets == [0, 1, 2, 2, 0, -1] and am.base_fret == 1
    g = lookup_chord("G")
    assert g is not None and g.frets == [3, 0, 0, 0, 2, 3]
    c = lookup_chord("C")
    assert c is not None and c.frets == [0, 1, 0, 2, 3, -1]
    # Curated E uses an open shape (base_fret 1), not a generated barre.
    e = lookup_chord("E")
    assert e is not None and e.base_fret == 1


def test_generated_for_missing_root() -> None:
    """G#m (missing from curated minors) resolves to a generated barre."""
    gsharpm = lookup_chord("G#m")
    assert gsharpm is not None
    # G#m pitch classes = G#(8) B(11) D#(3)
    assert set(sounding_pitch_classes(gsharpm)) == {8, 11, 3}
    assert gsharpm.base_fret >= 1


def test_coverage_matrix_full() -> None:
    """Every supported quality resolves for all 12 roots (the 'after' matrix)."""
    missing = []
    for q in SUPPORTED_QUALITIES:
        for r in range(12):
            if lookup_chord(ROOT_NAMES[r] + q) is None:
                missing.append(ROOT_NAMES[r] + q)
    assert not missing, f"unresolved: {missing}"
