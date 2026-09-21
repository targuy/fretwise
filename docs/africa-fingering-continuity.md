# Fingering 2.3: real shifts and explicit validation

## Problem

The opening guitar figure in Toto's Africa exposed a scoring inconsistency:
the same segment anchor suppressed the cost of an actual hand-position change.
An index at fret 4 could therefore precede an open string and a middle finger
at fret 2 without paying the expected shift cost. The repeated figure then
used a different finger at fret 4.

This change follows the M4 ergonomic transition contract in
`fretwise_architecture.md` sections 2 and 3 and the stable M5 interface rule in
`fretwise_plan_projet.md`. Source notes, strings, frets and timing must remain
unchanged. It does not impose one preferred fingering on every song.

M4 now keeps the actual transition cost within a segment, and uses the larger
of actual and anchor movement across segments. Fretted-state estimates retain
their configured tolerance; open-string transitions charge the whole movement
with the existing open-string discount. The first state's existing stretch
cost is included in its emission cost. No new coefficients or M5 interface
changes are introduced.

## Validation contract

Engine freshness and biomechanical validity are independent. A result computed
by the current engine can still contain constraints that the bounded planner
could not resolve. The viewer must expose that state instead of implying that
successful calculation or saving establishes playability.

The library remains readable. Existing GP export guards remain in force.
The engine version increases to 2.3 so the outdated-fingering warning offers
recalculation for results previously saved with 2.2.

An exhausted bounded hand search does not prove that the music is impossible.
The warning reports limitations of the selected fingering and validation.

Africa also exposes a separate limitation: the current occupation model holds
`let_ring` notes until the next attack on that string. In the baseline, notes
at fret 12 from measure 76 remain active against fret 4 in measure 77. With
fixed source strings/frets, changing fingers alone cannot satisfy that modeled
span. This release does not silently shorten source sustains or claim to solve
every passage. Failed joint search retains a proposal that is explicitly marked
unvalidated, rather than proving the underlying music impossible.

## Release checks

- Synthetic open-string figures exercise actual shifts and finger continuity.
- Regression suites cover scoring, segmentation, hand planning and phrase arbitration.
- Web tests distinguish current/old versions from valid/invalid/unknown results.
- Real Africa is recalculated in the release image with the library mounted
  read-only; source and saved-sidecar hashes are checked before and after.
- Release readiness, image identity and served web assets are verified before
  reporting deployment complete. The previous immutable release is retained.
