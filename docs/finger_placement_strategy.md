# Finger placement strategy — sedentary and pivot fingers

> **Scope.** How FretWise decides which left-hand fingers stay planted on the
> fretboard when they are not actively sounding a note. Intended as a spec for
> implementors and as an educational reference for readers of the project.

---

## 1. Problem statement

The baseline FretWise pipeline (M1→M5 + resolvers) decides, for every note,
which finger presses which string at which fret. It does **not** decide what
the other three fingers do. In reality, skilled players do not lift a finger
the instant its note has sounded — they **leave it down** whenever leaving it
down is cheaper than lifting and replacing it later. This document defines the
rules for those "background" finger decisions and the algorithm that derives
them deterministically from the output of M5.

Three vocabulary conventions:

- **Active finger** at note `N` — the finger in `FingeringResult.state.finger`.
- **Sedentary finger** — a finger that is pressed on the fretboard at note `N`
  but is not `N`'s active finger. It was placed by a previous note and has not
  been lifted since.
- **Pivot finger** — a sedentary finger that is retained across a chord change
  *specifically because it is shared with the next chord voicing*. (Subset of
  sedentary.)

---

## 2. Why this matters

Three benefits, roughly in order of importance:

1. **Execution speed.** Every finger already in position is a finger that
   does not need to travel during the next attack. For fast passages this is
   the dominant factor in playability.
2. **Tone and intonation.** A planted finger stays flexed at the same
   geometry; re-planting it produces a tiny re-attack artefact and often a
   slight pitch dip. Classical guitar pedagogy calls this *déjà placé*.
3. **Mental load.** Fewer simultaneous motor commands = fewer mistakes at
   tempo. This is the basis of Troy Grady's "chunking" work in rock guitar
   and Pumping Nylon's "anchor" discussion in classical.

---

## 3. When may a finger stay planted? — the three rules

A finger `F` currently pressing `(S, R)` may stay planted on a subsequent note
`N` if and only if **all three** of the following hold.

### R1. Non-interference (must be silent at N)

A planted finger is acceptable only if it does not change the sounding pitch
of `N`. Given `N.state = (S_n, R_n)`:

- **R1a — different string**: `S ≠ S_n`. The planted finger's string is not
  struck at this attack, so pressure is inaudible.
  *(User's example: "sa corde n'est pas frappée".)*
- **R1b — covered from a higher fret**: `S = S_n` *and* `R < R_n`. A finger
  pressing closer to the bridge dominates the pitch; the lower finger's
  pressure is cancelled.
  *(User's example: "un autre doigt sur la meme corde appuit une case à droite
  ce qui annule son effet".)*
- **R1c — identical position**: `S = S_n` *and* `R = R_n`. The planted
  finger *is* the active finger. It is reported as active, not sedentary.

Any other case makes the planted finger sound the wrong pitch and is
forbidden.

### R2. Biomechanical reachability

The planted position `(S, R)` must still be reachable given `N`'s
`hand_position`. Concretely:

- The fret `R` lies in `[max(1, hp − 1), hp + 4]`, where `hp = N.hand_position`.
  The `−1` tolerance covers a stretched index; the `+4` covers a stretched
  pinky on low positions.
- The finger's rank must not violate the ordering constraint with the active
  finger: if the active finger's rank is higher (e.g. ring) and it is on a
  lower fret than `R`, the planted finger would be crossing under — forbid.
  *(This is the same invariant already enforced by `resolve_chord_finger_
  ordering`, applied here to planted fingers against the active one.)*

### R3. Utility

Keeping a finger down must give a real benefit; otherwise the player would
let it relax. At least one of:

- **R3a — upcoming reuse**: `F` is used again at the exact same `(S, R)`
  within a lookahead window of `REUSE_LOOKAHEAD` notes (default 8).
- **R3b — chord context**: the current note `N` shares `hand_position` with
  the most recent note that placed `F`, and the temporal gap is short
  (`≤ 2` beats). This is the **arpeggiation / block-chord case**.
- **R3c — muting role**: `F` sits on a string that another voice is NOT
  supposed to sound but that would ring sympathetically (e.g. pinky mutes
  string 1 while thumb plays string 6). Not implemented in v1 — planned.

If none of R3a, R3b, R3c applies, the finger is considered "released" and
is not reported as sedentary at `N`.

---

## 4. Worked example — C major arpeggio

Notes, one per eighth note, hand_position = 1 throughout:

| # | Onset | (s, r) | Active finger |
|---|-------|--------|---------------|
| 1 | 0.0   | (5, 3) | ring          |
| 2 | 0.5   | (4, 2) | middle        |
| 3 | 1.0   | (3, 0) | open          |
| 4 | 1.5   | (2, 1) | index         |
| 5 | 2.0   | (1, 0) | open          |
| 6 | 2.5   | (5, 3) | ring          |

Applying R1/R2/R3 note by note:

- **Note 1**: first note; no prior placements. `planted = ∅`.
- **Note 2**: `ring` is placed at (5, 3). At note 2, active = middle at (4, 2).
  R1a holds (5 ≠ 4). R2 holds (3 in [1, 5]). R3b holds (same hand_position,
  gap 0.5 beats). → `planted = {ring: (5, 3)}`.
- **Note 3** (open): active = none. Both `ring` at (5, 3) and `middle` at (4, 2)
  still satisfy R1a, R2, R3b. → `planted = {ring: (5, 3), middle: (4, 2)}`.
- **Note 4**: active = index at (2, 1). Previous planted set still satisfies
  the rules. → `planted = {ring: (5, 3), middle: (4, 2)}`.
- **Note 5** (open): `planted = {ring: (5, 3), middle: (4, 2), index: (2, 1)}`
  — the complete C shape is held during the arpeggiation.
- **Note 6** (ring re-press at (5, 3)): ring is the active finger again.
  R1c — reported active, not planted. Middle and index remain planted by R3b.
  `planted = {middle: (4, 2), index: (2, 1)}`.

This matches how a guitarist actually plays an arpeggiated C: the whole chord
shape stays down.

---

## 5. Counter-example — position shift lifts fingers

Notes:

| # | Onset | (s, r) | finger | hand_pos |
|---|-------|--------|--------|----------|
| 1 | 0.0   | (5, 3) | ring   | 1        |
| 2 | 0.5   | (4, 2) | middle | 1        |
| 3 | 1.0   | (5, 7) | ring   | 5        |

At note 3, `hp = 5`. Middle's placed fret 2 is outside `[4, 9]` (R2 fails).
→ `planted = ∅` at note 3 — correct: shifting up the neck vacates low-position
fingers.

---

## 6. Counter-example — blocking

Notes (hypothetical, same string):

| # | Onset | (s, r) | finger |
|---|-------|--------|--------|
| 1 | 0.0   | (3, 5) | ring   |
| 2 | 0.5   | (3, 3) | index  |

At note 2, ring is at (3, 5) and the active index is at (3, 3) on the same
string. R1b fails because `5 > 3` — ring's higher fret would dominate the
pitch. Ring must be released.

→ `planted = ∅`.

Note that the inverse case (ring at (3, 3), index at (3, 5)) is valid: R1b
holds (`3 < 5`), index covers ring's placement from above.

---

## 7. Algorithm

Implemented as a single forward scan `resolve_sedentary_fingers(results)`,
injected into `pipeline.py` after `resolve_finger_continuity` and before
`resolve_chord_conflicts`.

```
last_pos: Finger -> (string, fret, onset_beat)  — current placement registry

for i, r in enumerate(results):
    hp = r.state.hand_position
    active = r.state.finger
    planted = {}

    # Step 1 — update registry for the active finger FIRST.
    if active not in (OPEN, MUTED) and not r.note_event.muted:
        last_pos[active] = (r.state.string_num, r.state.fret, r.note_event.onset)

    # Step 2 — any other finger whose registry entry is at r's (string, fret)
    # must be cleared: two fingers cannot share one position.
    for F, pos in list(last_pos.items()):
        if F == active or pos is None: continue
        if pos.string == r.state.string_num and pos.fret == r.state.fret:
            last_pos[F] = None

    # Step 3 — evaluate remaining registry entries against r for sedentary status.
    for F, pos in last_pos.items():
        if F == active or pos is None: continue
        if r.note_event.onset - pos.onset > MAX_INACTIVE_BEATS: continue   # R3a timeout
        if not (max(1, hp - 1) <= pos.fret <= hp + 4): continue             # R2
        if pos.string == r.state.string_num and pos.fret >= r.state.fret:  # R1b/R1c
            continue
        if not (has_future_reuse(F, pos, i) or in_chord_context(pos, r, i)):
            continue                                                        # R3
        planted[F] = (pos.string, pos.fret)

    r.planted_fingers = planted
```

Helpers:

- `has_future_reuse(F, pos, i)` — True if some `j > i` with
  `results[j].state.finger == F and (string, fret) == pos` within
  `REUSE_LOOKAHEAD` notes.
- `in_chord_context(pos, r, i)` — True if `pos.onset_beat` and
  `r.note_event.onset` are within 2 beats AND both imply the same
  `hand_position`.

**Complexity.** `O(N × F × K)` where `N` = notes, `F = 4` fingers,
`K = REUSE_LOOKAHEAD` — effectively linear in N.

---

## 8. Data-model extension

Minimal addition to `fretwise/models.py`:

```python
@dataclass
class FingeringResult:
    note_id: int
    note_event: NoteEvent
    state: FingeringState
    cost: float
    alternatives: list[tuple[FingeringState, float]] = field(default_factory=list)
    # NEW:
    planted_fingers: dict[str, tuple[int, int]] = field(default_factory=dict)
    # Key = Finger value ("index"/"middle"/"ring"/"pinky")
    # Value = (string_num, fret) where that finger is planted.
```

Default `{}` preserves every existing construction site unchanged.

---

## 9. Rendering contract

The hand-viz layer should:

1. Draw each active finger with full opacity and a pulse halo at note-on.
2. Draw each planted (sedentary) finger with **reduced opacity** (~0.55) and
   **no halo** — it is not currently being struck.
3. Draw each **idle** finger (neither active nor planted) as a short folded
   stub above the fretboard, per the existing convention.
4. Legend in the HUD must explicitly name the three states.

This gives the viewer a direct visual answer to "which fingers are down right
now?" at every instant of the animation.

---

## 10. Validation against public guitar pedagogy

Rules R1–R3 match the prescriptions found across reference sources. Short
cross-reference:

- **Scott Tennant, *Pumping Nylon*** (classical) — "planted" / "planting
  ahead" — fingers set on strings they will play next; rule: "plant when the
  planted string is not currently sounding". Matches R1a + R3a.
- **Troy Grady, *Cracking the Code*** (rock) — "one-way pickslanting and
  finger economy": leave fingers on intermediate strings during sweep
  arpeggios. Matches R1a + R3b.
- **Aaron Shearer, *Classic Guitar Technique*** — "prepare where possible,
  release only where necessary". Matches the general forward-scan policy.
- **Jamey Aebersold / jazz pedagogy** — "common tone" voice leading across
  chord changes: keep the shared finger down. Matches R3b + the pivot-finger
  subset.

No source consulted advocates lifting fingers preemptively; all advocate
release-on-demand. This is why the algorithm is "sedentary by default".

---

## 11. Integration with existing resolvers

Execution order in `pipeline.py`:

```
[per voice]
  optimizer.solve                     (M5)
  resolve_finger_continuity
  resolve_chord_conflicts
  resolve_chord_stretch
  resolve_chord_finger_ordering
  resolve_chord_finger_span
  resolve_chord_string_diagonal
  resolve_section_consistency
[merge voices, sort by onset]
[if multi-voice]
  resolve_chord_conflicts
  resolve_chord_finger_ordering
  resolve_chord_finger_span
  resolve_chord_string_diagonal
resolve_sedentary_fingers              ← NEW (runs on fully merged list)
```

Rationale for placement at the very end:

- The sedentary pass READS the final active-finger decision on every note.
  Running it per-voice would mean each voice has its own independent
  planted-finger history, but there is only **one** physical hand playing
  both voices.
- Running it after the inter-voice second pass guarantees every
  `FingeringState` is stable when planted fingers are computed.

The sedentary pass is **read-only w.r.t. `FingeringState`** — it only
writes to the new `planted_fingers` field. It therefore cannot invalidate any
downstream resolver and can be toggled on/off without breaking the rest of
the pipeline.

---

## 12. Non-goals (v1)

- Barre-style planting where one finger covers multiple strings
  (`planted_fingers` currently maps one finger → one (string, fret)).
- Muting role (R3c) — recognised in the spec, not yet implemented.
- Slide-chain continuity across position shifts — a slide is a lift, not a
  plant. Already handled correctly by R2 on the destination note.
- Thumb usage (behind the neck). Out of scope for the left-hand model.

---

## 13. Summary

A finger is sedentary at note `N` if, and only if:

1. **It is not in the way** (same string only if its fret is lower, otherwise
   any string).
2. **It is still reachable** from `N`'s hand position.
3. **Keeping it there is useful** — either used again soon, or the notes form
   a chord context in the same hand position.

This converts the player's implicit rule "don't lift what you'll need again"
into a deterministic post-processing step that plugs in behind the existing
Viterbi pipeline without touching M1–M5.
