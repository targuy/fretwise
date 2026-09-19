# Joint fingering and sustained contacts

Implemented from `specifications/notion_fingering_animation_2026-09-14.md`,
sections 2.1–2.4, 4.4 and FW-01/FW-05/FW-06. M5's public interface is unchanged.

`GeneratorConfig.position_mode="tablature"` preserves source string/fret hints.
Malformed or out-of-range hints produce no admissible candidate; they never
silently enable rearrangement. `"rearrange"` explicitly explores positions with
the same pitch using the configured tuning. Contraction and extension around
neutral finger offsets permit ring finger at fret 2 and first-position chords.
These candidate bounds are search limits, not measured anatomical limits.

Source annotations use `source_finger_policy="prefer"` by default: source fingers
come first when candidate costs tie. `"lock"` restricts admissible candidates;
`"ignore"` leaves annotation out of candidate ordering. Preference avoids turning
previous FretWise-generated annotations into permanent user locks. Existing
`ConstrainedStateGenerator` user locks remain hard constraints after heuristics.

After legacy Viterbi/rules/ML, `hand_planning.plan_hand_configurations` checks
whole-hand occupations and runs a bounded beam search when repair is necessary.
Held notes in every voice participate, including let-ring until the next attack
on that string. Same-voice rearticulation replaces the previous string pitch;
different voices cannot silently truncate notated sustain. Ties retain the same
contact unless an explicit future substitution contract authorizes otherwise.
Index barres may pass behind higher notes, but cannot cut an open/lower note.

Cross-voice unisons preserve all source occurrences and durations while sharing
one physical contact. Final cumulative costs are recomputed per voice. Obsolete
independent note alternatives are cleared; the joint API returns up to two
complete-sequence alternatives when a search ran. The web review's existing
phrase recalculation remains available.

`valid` means discrete contact compatibility within this model. It does not
certify joint angles, continuous motion, skin contact, acoustics or musical
naturalness. The finite beam (48 by default) can miss an admissible path:
`search_failed` therefore means no path found within the search, not proven
impossibility. Original notes and explicit locks remain present; final independent
biomechanical validation exposes conflicts. Source notes lacking candidates are
marked `BIO-SOURCE-001`; unsupported pitches without source positions raise an
explicit error instead of being silently dropped.

Regression tests: `tests/test_hand_planning.py`, alongside generator,
biomechanics, pipeline, optimizer, scoring and review tests. Synthetic local
measurement on 19 September 2026: 1,000 monophonic source-position notes,
120 BPM, 0.25-beat duration, 0.222 s total pipeline time; no corrective beam
search needed. This measures neither NAS latency nor a musical corpus verdict.
