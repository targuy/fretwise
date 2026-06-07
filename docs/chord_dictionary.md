# Chord dictionary — movable barre generation

FretWise's chord dictionary combines a **curated set of 78 open-position
voicings** with **on-the-fly generation of standard movable barre voicings** so
that every chromatic root resolves to a correct, playable fingering for the
common chord qualities.

## How lookup works

`fretwise.patterns.chord_library.lookup_chord(name)` resolves a chord name in
this order (curated voicings always win):

1. **Exact** curated match (e.g. `Am`, `G7`, `Fmaj7`).
2. **Case-insensitive** curated match.
3. **Slash chord** — strip the bass note (`C/G` → `C`). The slash branch is
   guarded so quality suffixes that contain `/` (like `6/9`) are *not* mistaken
   for a slash bass.
4. **Generated movable barre voicing** for the `(root, quality)` pair.

The 78 curated open voicings are byte-identical and preferred; generation only
fills the gaps.

## Movable shapes and transposition

`data/patterns/chord_voicings.yaml` has a `movable_shapes:` section defining the
canonical **E-shape** (root on string 6, low E) and **A-shape** (root on string
5, A) forms per quality. Each shape stores per-string fret **offsets** from an
anchor fret (`0` = at the anchor, `n` = anchor + n, `-1` = muted), in the usual
`[str1 high_e … str6 low_E]` order.

To generate `(root, quality)`:

1. Look up the quality's families (E-shape and/or A-shape).
2. For each family, the **anchor fret** is the lowest fret ≥ 1 where the root
   pitch class lands on the shape's root string
   (`anchor = (root_pc − open_root_pc) mod 12`, using `12` instead of `0` so an
   open-string root uses the fret-12 octave shape rather than open strings).
3. Absolute frets = offset + anchor. **Fingers are derived** deterministically
   (one finger per distinct fret, lowest fret = index = barre), which guarantees
   a finger never holds two different frets.
4. The **lower-anchor** family is preferred (more playable); ties favour the
   E-shape.

## Validation gate

`tests/test_chord_dictionary.py` validates **every** voicing the system returns
(curated and generated), for all 12 roots × 19 qualities, asserting:

- sounding pitch classes (from frets + standard tuning, muted strings excluded)
  contain **no notes outside** the quality's interval formula and omit **at most
  the perfect 5th** (a universally-standard voicing allowance, e.g. open C7);
- the **root is present and is the lowest** sounding note;
- the shape is **physically playable**: fret span ≤ 4 (5 only with a barre),
  fingers consistent with frets, ≤ 4 fingers, frets in range, sane `base_fret`.

The interval formulas are **shared** with
`fretwise.patterns.chord_recognition._CHORD_PATTERNS` so the two modules never
diverge. This gate exposed and fixed four genuinely-wrong curated voicings (`Fm`
had F-major frets, `Gadd9` dropped the 9th, `Dadd9` dropped the 3rd, `C#dim` was
actually a dim7).

## Coverage (roots covered per quality)

| Quality | Before | After |
|---|---|---|
| major | 12/12 | 12/12 |
| m | 11/12 | 12/12 |
| 7 | 6/12 | 12/12 |
| maj7 | 6/12 | 12/12 |
| m7 | 4/12 | 12/12 |
| m7b5 | 0/12 | 12/12 |
| dim | 2/12 | 12/12 |
| dim7 | 0/12 | 12/12 |
| aug | 2/12 | 12/12 |
| sus2 | 2/12 | 12/12 |
| sus4 | 4/12 | 12/12 |
| 6 | 3/12 | 12/12 |
| m6 | 1/12 | 12/12 |
| 9 | 3/12 | 12/12 |
| maj9 | 0/12 | 12/12 |
| m9 | 0/12 | 12/12 |
| add9 | 3/12 | 12/12 |
| 6/9 | 0/12 | 12/12 |
| mM7 | 1/12 | 12/12 |
| **TOTAL** | **60/228** | **228/228** |

### Notes on shape choices

- **dim7, m7b5, dim, sus2, maj9, add9, 6/9** use a single A-shape family; **aug,
  m9** use a single E-shape. One family per quality is sufficient for full
  12-root coverage (the shape slides chromatically); the others provide an
  E/A choice for lower-position playability.
- **m9** uses the compact E-shape `0 2 0 0 2 X` (root..9th..b3..b7..5) because
  the full 5-note A-shape m9 needs five distinct frets — unplayable with four
  fingers. The chosen shape keeps the complete formula within a 2-fret span.
- **9-family** chords keep the full formula (root, 3, 5, b7, 9); the only
  standard omission permitted anywhere is the perfect 5th, used by a few curated
  open chords.
