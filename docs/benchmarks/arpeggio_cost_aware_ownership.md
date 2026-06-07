# Arpeggio resolver — cost-aware ownership benchmark

Measures how much of the final left-hand *finger* assignment is owned by the
13 post-Viterbi `resolve_*` heuristics versus the cost layer (Viterbi + the
injected `CostFunction`), before and after making
`resolve_arpeggio_chord_fingering` cost-aware.

## Method (spike ablation)

Per fixture, the real `run_pipeline` is run twice on the **same** parsed
`NoteEvent`s — performance mode, `chord_finger_classifier=None`:

- **normal**: all 13 resolvers active.
- **ablated**: every `resolve_*` monkeypatched to identity.

Ownership = fraction of final `FingeringState.finger` values that *differ*
between the two runs (keyed by `(round(onset, 4), pitch, voice_hint)`). The
"arpeggio share" column ablates *only* `resolve_arpeggio_chord_fingering`
(all other resolvers active), isolating its own contribution.

Script: `scripts/measure_arpeggio_ownership.py` (throwaway; may be deleted).

## Results

Resolver ownership = fraction of fingers the resolvers overwrite. Lower is
better (more of the final output is owned by the cost layer).

| Fixture | notes | resolver own BEFORE | AFTER | arpeggio share BEFORE | AFTER |
|---|---:|---:|---:|---:|---:|
| Albert Collins – Frosty | 789 | 71.5% | 30.4% | 56.4% | 15.1% |
| B.B. King – Rock Me Baby | 344 | 66.9% | 29.4% | 63.7% | 23.8% |
| Buena Vista – Chan Chan | 906 | 65.9% | 36.5% | 44.2% | 13.2% |
| GNR – November Rain | 690 | 63.9% | 22.0% | 54.2% | 10.9% |
| AC/DC – Highway To Hell | 207 | 55.1% | 28.5% | 46.9% | 14.5% |
| Dream Theater – Pull Me Under | 2547 | 35.8% | 28.5% | 11.9% | 4.6% |
| Fleetwood Mac – Albatross | 336 | 33.3% | 5.4% | 32.1% | 4.2% |
| Nirvana – Smells Like Teen Spirit | 44 | 47.7% | 0.0% | 47.7% | 0.0% |

### Aggregate

| Metric | BEFORE | AFTER |
|---|---:|---:|
| Resolver ownership (all 13) | **51.0%** (2991/5863) | **27.8%** (1627/5863) |
| Arpeggio-resolver share | **33.6%** (1968/5863) | **9.5%** (556/5863) |
| Cost-layer ownership (1 − all) | **49.0%** | **72.2%** |

## Interpretation

- The arpeggio resolver's overwrite share dropped **33.6% → 9.5%** (a ~72%
  reduction): it now overrides Viterbi only when the override is
  cost-neutral-or-better under the injected weights/profile.
- Aggregate cost-layer ownership rose **49.0% → 72.2%**, clearing the
  60–70% go/no-go gate.
- Anti-oscillation is retained: a clear single-position arpeggio whose
  stabilisation is cost-neutral still gets stabilised (see
  `tests/test_scoring.py::TestResolveArpeggioCostAware`).
