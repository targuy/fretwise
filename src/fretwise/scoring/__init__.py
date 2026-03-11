"""Scoring module (M4) — mechanical cost function C_méca.

Implements the composite cost function:

    C(s1, s2) = α·C_méca(s1, s2) + β·C_music(s1, s2) + γ·C_joueur(s1, s2) + δ·C_péda(s1, s2)

Sprint 1 scope: C_méca only (α=1, β=0, γ=0, δ=0).
C_music, C_joueur, C_péda are stubs returning 0.0.

The coefficients α, β, γ, δ are **never** hardcoded in Viterbi (M5);
they are injected here as parameters so every mode (performance, musical,
learning, reference) can be expressed without modifying M5.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.profile import PlayerProfile, default_profile

# ---------------------------------------------------------------------------
# Weighting presets (α, β, γ, δ)
# ---------------------------------------------------------------------------

WEIGHTS_REFERENCE: tuple[float, float, float, float] = (1.0, 1.0, 0.0, 0.0)
WEIGHTS_PERFORMANCE: tuple[float, float, float, float] = (1.0, 0.5, 2.0, 0.0)
WEIGHTS_MUSICAL: tuple[float, float, float, float] = (1.0, 2.0, 1.0, 0.0)
WEIGHTS_LEARNING: tuple[float, float, float, float] = (1.0, 0.5, 1.0, 1.5)

# Intrinsic difficulty per finger (index baseline = 1.0).
_FINGER_BASE_COST: dict[Finger, float] = {
    Finger.OPEN: 0.0,
    Finger.INDEX: 1.0,
    Finger.MIDDLE: 1.5,
    Finger.RING: 2.0,
    Finger.PINKY: 2.5,
}

# Natural anatomical rank on the neck (lowest fret = lowest rank).
# INDEX = 0 (closest to headstock), PINKY = 3 (furthest).
_FINGER_RANK: dict[Finger, int] = {
    Finger.OPEN: -1,
    Finger.INDEX: 0,
    Finger.MIDDLE: 1,
    Finger.RING: 2,
    Finger.PINKY: 3,
}


@dataclass
class CostWeights:
    """Composite cost weights (α, β, γ, δ).

    Attributes:
        alpha: Weight for C_méca (mechanical cost).
        beta: Weight for C_music (musical cost).
        gamma: Weight for C_joueur (player feasibility cost).
        delta: Weight for C_péda (pedagogical cost).
    """

    alpha: float = 1.0
    beta: float = 1.0
    gamma: float = 0.0
    delta: float = 0.0

    @classmethod
    def reference(cls) -> CostWeights:
        """Benchmark mode: mechanical + musical, no player profile."""
        return cls(*WEIGHTS_REFERENCE)

    @classmethod
    def performance(cls) -> CostWeights:
        """Concert mode: prioritises player feasibility."""
        return cls(*WEIGHTS_PERFORMANCE)

    @classmethod
    def musical(cls) -> CostWeights:
        """Interpretation mode: prioritises musical expression."""
        return cls(*WEIGHTS_MUSICAL)

    @classmethod
    def learning(cls) -> CostWeights:
        """Practice mode: activates pedagogical cost."""
        return cls(*WEIGHTS_LEARNING)


class CostFunction:
    """Composite cost function injected into the Viterbi optimizer (M5).

    The optimizer calls ``transition_cost(s1, s2, note)`` for every
    consecutive pair of states; this class aggregates the four components.

    Args:
        weights: α/β/γ/δ weighting (default: reference mode).
        profile: Player calibration data (default: intermediate profile).
    """

    def __init__(
        self,
        weights: CostWeights | None = None,
        profile: PlayerProfile | None = None,
    ) -> None:
        self._weights = weights or CostWeights.reference()
        self._profile = profile or default_profile()

    def transition_cost(
        self,
        s1: FingeringState,
        s2: FingeringState,
        note: NoteEvent,
    ) -> float:
        """Compute the composite transition cost between two fingering states.

        Args:
            s1: The previous (source) fingering state.
            s2: The next (target) fingering state.
            note: The NoteEvent associated with s2 (provides tempo context).

        Returns:
            Non-negative composite cost.  Lower = more desirable transition.
        """
        w = self._weights
        c_meca = compute_mechanical_cost(s1, s2, note)
        c_music = 0.0   # stub — Phase 2
        c_joueur = 0.0  # stub — Phase 3
        c_peda = 0.0    # stub — Phase 3
        return w.alpha * c_meca + w.beta * c_music + w.gamma * c_joueur + w.delta * c_peda

    def emission_cost(self, state: FingeringState) -> float:
        """Initial cost for the first note in a sequence.

        Uses the intrinsic finger difficulty as a simple emission cost.

        Args:
            state: Fingering state for the first note.

        Returns:
            Non-negative cost.
        """
        return _FINGER_BASE_COST.get(state.finger, 1.0)


# ---------------------------------------------------------------------------
# C_méca components (pure functions for testability)
# ---------------------------------------------------------------------------


def cost_position_shift(s1: FingeringState, s2: FingeringState, note: NoteEvent) -> float:
    """Cost of moving the wrist between two hand positions.

    The penalty is proportional to the shift distance and scales with
    note speed: a large shift in a fast passage is more costly than the
    same shift in a slow one.

    Args:
        s1: Source state.
        s2: Target state.
        note: Note event for s2 (provides tempo and duration).

    Returns:
        Non-negative cost.
    """
    shift = abs(s2.hand_position - s1.hand_position)
    if shift == 0:
        return 0.0
    # beats_per_minute / 60 = beats per second; duration in beats → seconds
    # Short duration = fast note = harder to shift
    seconds = note.duration * 60.0 / max(note.tempo, 1.0)
    tempo_factor = 1.0 / max(seconds, 0.1)  # cap to avoid infinity
    return shift * tempo_factor


def cost_stretch(s1: FingeringState, s2: FingeringState) -> float:
    """Penalty for large fret stretches within a hand position.

    The stretch cost is the distance between the played fret and the
    hand position (i.e. the finger number minus one).  Higher frets on
    the neck are physically easier because the fret spacing is smaller,
    so we apply a mild reduction factor.

    Args:
        s1: Source state (unused in MVP; reserved for context in Phase 2).
        s2: Target state.

    Returns:
        Non-negative cost.
    """
    if s2.fret == 0:
        return 0.0
    stretch = s2.fret - s2.hand_position  # = finger offset (0–3)
    # Frets above 12 are physically closer together; reduce cost slightly.
    position_factor = 1.0 - 0.3 * min(s2.hand_position / 12.0, 1.0)
    return max(stretch, 0) * position_factor


def cost_string_change(s1: FingeringState, s2: FingeringState) -> float:
    """Cost proportional to the number of strings crossed.

    Adjacent strings have a very low cost; large jumps are penalised.

    Args:
        s1: Source state.
        s2: Target state.

    Returns:
        Non-negative cost.
    """
    strings_crossed = abs(s2.string_num - s1.string_num)
    return float(strings_crossed)


def cost_finger_difficulty(s2: FingeringState) -> float:
    """Intrinsic difficulty of the finger used in state s2.

    Index finger = easiest (1.0); pinky = hardest (2.5).

    Args:
        s2: Target state.

    Returns:
        Non-negative cost.
    """
    return _FINGER_BASE_COST.get(s2.finger, 1.0)


_SEQUENTIAL_CROSS_PENALTY = 2.0
# A position shift larger than this (in frets) means the hand fully relocates,
# making any finger ordering acceptable for the landing note.
_SHIFT_EXEMPT_THRESHOLD = 1


def cost_sequential_crossing(s1: FingeringState, s2: FingeringState) -> float:
    """Penalty when consecutive notes imply a finger-direction/fret-direction mismatch.

    In a scale run that stays in the same hand position, the fingers must
    ascend as frets ascend (INDEX → MIDDLE → RING → PINKY) and descend as
    frets descend.  Doing the opposite (e.g. playing fret 7 with INDEX then
    fret 9 with MIDDLE is fine, but fret 7 with RING then fret 9 with MIDDLE
    would require MIDDLE to cross under RING while RING is still engaged) is
    mechanically clumsy and should carry an explicit penalty.

    No penalty is applied when:
    - Either note uses an open string (only one active finger).
    - The hand position shifts by more than one fret (full relocation; any
      finger order is valid at the new position).
    - Fret does not change (unison / re-articulation).

    Args:
        s1: Previous fingering state.
        s2: Next fingering state.

    Returns:
        0.0 or _SEQUENTIAL_CROSS_PENALTY.
    """
    if s1.finger == Finger.OPEN or s2.finger == Finger.OPEN:
        return 0.0
    if s1.fret == 0 or s2.fret == 0:
        return 0.0
    if abs(s2.hand_position - s1.hand_position) > _SHIFT_EXEMPT_THRESHOLD:
        return 0.0
    fret_dir = s2.fret - s1.fret
    if fret_dir == 0:
        return 0.0
    rank_dir = _FINGER_RANK[s2.finger] - _FINGER_RANK[s1.finger]
    if rank_dir == 0:
        return 0.0
    # Crossing: fret and finger rank move in opposite directions.
    if (fret_dir > 0) != (rank_dir > 0):
        return _SEQUENTIAL_CROSS_PENALTY
    return 0.0


def _build_pitch_voicings(
    results: list[FingeringResult],
) -> dict[int, set[tuple[int, int]]]:
    """Map each MIDI pitch to all (string_num, fret) voicings seen in the song."""
    voicings: dict[int, set[tuple[int, int]]] = defaultdict(set)
    for r in results:
        voicings[r.note_event.pitch].add((r.state.string_num, r.state.fret))
    return voicings


def resolve_chord_stretch(
    results: list[FingeringResult],
    max_fret_span: int = 4,
) -> list[FingeringResult]:
    """Detect and fix chords where the fret span exceeds physical reach.

    A chord where fretted notes span more than ``max_fret_span`` frets (default 4,
    the standard one-finger-per-fret reach for a 4-fret hand position) cannot
    be played without an impossible extension.

    For each such chord the outlier note (farthest from the cluster median) is
    revoiced to the alternative (string_num, fret) for the same pitch that most
    reduces the span.  Revoicing candidates are taken from all voicings of that
    pitch already used elsewhere in the song (so the result stays consistent
    with the actual guitar tuning in the file).

    If no revoicing reduces the span (e.g. the note is genuinely unplayable in
    this chord context), a warning is logged and the note is left unchanged;
    the renderer will display it with a ``!`` marker.

    Args:
        results: Post-processed FingeringResult list.
        max_fret_span: Maximum allowed fret distance between the lowest and
            highest fretted note in a chord (default 4).

    Returns:
        New list with chord stretch violations resolved where possible.
    """
    resolved = list(results)
    voicings = _build_pitch_voicings(resolved)

    onset_to_indices: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(resolved):
        onset_to_indices[round(r.note_event.onset, 6)].append(idx)

    for onset, indices in onset_to_indices.items():
        if len(indices) < 2:
            continue

        fretted = [(idx, resolved[idx].state.string_num, resolved[idx].state.fret)
                   for idx in indices if resolved[idx].state.fret > 0]
        if len(fretted) < 2:
            continue

        frets = [f for _, _, f in fretted]
        if max(frets) - min(frets) <= max_fret_span:
            continue  # chord is within reach

        # Try revoicing every fretted note in the chord, pick whichever
        # revoicing most reduces the span (avoids the "wrong outlier" problem
        # that occurs with only 2 notes when the median equals one endpoint).
        best_fix_idx: int | None = None
        best_fix_pos: tuple[int, int] | None = None
        best_span = max(frets) - min(frets)

        for try_idx, _, _ in fretted:
            try_pitch = resolved[try_idx].note_event.pitch
            other_frets_t = [f for i, _, f in fretted if i != try_idx]
            occupied_t = {resolved[i].state.string_num for i in indices if i != try_idx}
            for string_num, fret in voicings.get(try_pitch, set()):
                if string_num in occupied_t:
                    continue
                new_span = (
                    max(other_frets_t + [fret]) - min(other_frets_t + [fret])
                    if other_frets_t else 0
                )
                if new_span < best_span:
                    best_span = new_span
                    best_fix_idx = try_idx
                    best_fix_pos = (string_num, fret)

        if best_fix_idx is None or best_fix_pos is None:
            current_span = max(frets) - min(frets)
            worst_idx, _, worst_fret = max(fretted, key=lambda t: t[2])
            r_warn = resolved[worst_idx]
            logger.warning(
                "Unresolvable chord span %d at onset %.3f: "
                "note_id=%d pitch=%d fret=%d string=%d — will be marked '!' in tab.",
                current_span, onset,
                r_warn.note_id, r_warn.note_event.pitch,
                worst_fret, r_warn.state.string_num,
            )
            continue

        outlier_idx = best_fix_idx
        string_num, fret = best_fix_pos
        r_out = resolved[outlier_idx]
        other_frets = [f for i, _, f in fretted if i != outlier_idx]
        fingers_used = {
            resolved[i].state.finger for i in indices
            if i != outlier_idx and resolved[i].state.finger != Finger.OPEN
        }
        cluster_min = min(other_frets) if other_frets else fret
        new_state: FingeringState | None = None
        for candidate, offset in (
            (Finger.INDEX, 0), (Finger.MIDDLE, 1), (Finger.RING, 2), (Finger.PINKY, 3)
        ):
            if candidate in fingers_used:
                continue
            if fret - cluster_min == offset:
                hp = max(1, fret - offset)
                new_state = FingeringState(string_num=string_num, fret=fret,
                                           finger=candidate, hand_position=hp)
                break
        if new_state is None:
            # Fallback: first available finger.
            for candidate in (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY):
                if candidate not in fingers_used:
                    offset = _FINGER_OFFSET.get(candidate, 0)
                    hp = max(1, fret - offset)
                    new_state = FingeringState(string_num=string_num, fret=fret,
                                               finger=candidate, hand_position=hp)
                    break

        if new_state is not None:
            resolved[outlier_idx] = FingeringResult(
                note_id=r_out.note_id,
                note_event=r_out.note_event,
                state=new_state,
                cost=r_out.cost,
                alternatives=r_out.alternatives,
            )

    return resolved


def resolve_chord_conflicts(results: list[FingeringResult]) -> list[FingeringResult]:
    """Fix physically impossible finger assignments within chords.

    Viterbi assigns fingers note-by-note along the time axis, so simultaneous
    notes (same onset) can end up with the same finger on different strings —
    which is physically impossible.  This post-processing pass detects such
    conflicts and replaces the offending note's state with the best available
    alternative that uses a different finger.

    Args:
        results: Output from ViterbiOptimizer.solve().

    Returns:
        New list with chord-internal finger conflicts resolved where possible.
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue

        # Iteratively resolve conflicts (one pass per conflict, up to group size).
        for _ in range(len(indices)):
            used_fingers: set[Finger] = set()
            conflict_idx: int | None = None

            for result_idx in indices:
                f = resolved[result_idx].state.finger
                if f == Finger.OPEN:
                    continue
                if f in used_fingers:
                    conflict_idx = result_idx
                    break
                used_fingers.add(f)

            if conflict_idx is None:
                break  # no more conflicts in this onset group

            r = resolved[conflict_idx]
            new_state: FingeringState | None = None
            new_cost = r.cost

            # First try stored alternatives.
            for alt_state, alt_cost in r.alternatives:
                if alt_state.finger == Finger.OPEN or alt_state.finger not in used_fingers:
                    new_state = alt_state
                    new_cost = alt_cost
                    break

            # If no suitable alternative exists, construct a state directly
            # using the least-difficult available finger.
            if new_state is None:
                for candidate in (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY):
                    if candidate not in used_fingers:
                        offset = _FINGER_OFFSET.get(candidate, 0)
                        hp = max(1, r.state.fret - offset)
                        new_state = FingeringState(
                            string_num=r.state.string_num,
                            fret=r.state.fret,
                            finger=candidate,
                            hand_position=hp,
                        )
                        break

            if new_state is not None:
                resolved[conflict_idx] = FingeringResult(
                    note_id=r.note_id,
                    note_event=r.note_event,
                    state=new_state,
                    cost=new_cost,
                    alternatives=r.alternatives,
                )

    return resolved


def resolve_chord_finger_ordering(results: list[FingeringResult]) -> list[FingeringResult]:
    """Enforce monotone finger-rank / fret ordering within simultaneous chords.

    Fingers have a fixed anatomical order on the neck:
    INDEX (rank 0) < MIDDLE (1) < RING (2) < PINKY (3).
    When two or more notes are pressed simultaneously, a finger of lower rank
    MUST be placed at a lower-or-equal fret than any finger of higher rank —
    otherwise the fingers would have to physically cross, which is impossible.

    Algorithm per chord:
    1. Collect all fretted notes (fret > 0, finger != OPEN).
    2. Sort notes by fret ascending.
    3. Sort the set of assigned fingers by rank ascending.
    4. Re-assign fingers to notes in matching order (lowest-rank finger to
       lowest fret, …).  Notes tied on the same fret share a group; the
       relative finger order within a group is unconstrained (partial barré).
    5. If the assignment is already monotone, leave it unchanged.

    Open strings and notes already at fret 0 are never touched.

    This resolver must run AFTER resolve_chord_stretch (stretch fixes can
    alter fret positions and accidentally re-introduce crossing assignments).
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue

        fretted = [
            (idx, resolved[idx].state.fret, resolved[idx].state.finger)
            for idx in indices
            if resolved[idx].state.fret > 0 and resolved[idx].state.finger != Finger.OPEN
        ]
        if len(fretted) < 2:
            continue

        # If more fretted notes than available fingers the chord needs a barré
        # model to be resolved — skip it here (already flagged '!' by chord_stretch).
        unique_fingers = {f for _, _, f in fretted}
        if len(fretted) > len(unique_fingers) or len(fretted) > 4:
            continue

        # Check monotone: as fret increases, finger rank must be non-decreasing.
        fretted_by_fret = sorted(fretted, key=lambda t: t[1])
        is_monotone = True
        max_rank = -1
        prev_fret = -1
        for _, fret, finger in fretted_by_fret:
            rank = _FINGER_RANK.get(finger, 0)
            if fret > prev_fret:
                if rank < max_rank:
                    is_monotone = False
                    break
                max_rank = rank
            # Equal fret: partial barré — skip rank check, don't update max_rank
            prev_fret = fret

        if is_monotone:
            continue

        # Build corrected assignment: sort fingers by rank, assign to fret groups.
        fingers_sorted = sorted(
            {f for _, _, f in fretted},
            key=lambda f: _FINGER_RANK.get(f, 0),
        )
        finger_pool = list(fingers_sorted)

        fret_groups: dict[int, list[int]] = {}
        for idx, fret, _ in fretted_by_fret:
            fret_groups.setdefault(fret, []).append(idx)

        new_finger_map: dict[int, Finger] = {}
        for fret_val in sorted(fret_groups):
            for note_idx in fret_groups[fret_val]:
                if finger_pool:
                    new_finger_map[note_idx] = finger_pool.pop(0)

        for note_idx, new_finger in new_finger_map.items():
            r = resolved[note_idx]
            if r.state.finger == new_finger:
                continue
            offset = _FINGER_OFFSET.get(new_finger, 0)
            hp = max(1, r.state.fret - offset)
            new_state = FingeringState(
                string_num=r.state.string_num,
                fret=r.state.fret,
                finger=new_finger,
                hand_position=hp,
            )
            resolved[note_idx] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=new_state,
                cost=r.cost,
                alternatives=r.alternatives,
            )

    return resolved


# Finger → fret offset from hand_position (index=0, middle=1, ring=2, pinky=3).
_FINGER_OFFSET: dict[Finger, int] = {
    Finger.INDEX: 0, Finger.MIDDLE: 1, Finger.RING: 2, Finger.PINKY: 3,
}


def resolve_finger_continuity(
    results: list[FingeringResult],
    lookback_beats: float = 8.0,
) -> list[FingeringResult]:
    """Preserve finger assignments across arpeggios and repeated positions.

    A guitarist holds a chord shape while picking individual strings one at a
    time.  When a string reappears at the same fret, the finger is still there
    — no need to reassign.  This function enforces that by scanning backwards
    through recent onsets for each note:

    - If the same string was last played at the **same fret** → keep that finger.
    - If the same string was last played at a **different fret** → the finger
      moved; stop looking (no continuity to preserve).
    - If no prior occurrence within ``lookback_beats`` is found → no constraint.

    The lookback covers ``lookback_beats`` quarter-note beats (default 8 = two
    4/4 measures), which is enough for any realistic arpeggio pattern.

    Args:
        results: Output from ViterbiOptimizer.solve() or resolve_chord_conflicts().
        lookback_beats: How far back (in beats) to search for the same string.

    Returns:
        New list with arpeggio-aware finger continuity enforced.
    """
    if not results:
        return results

    resolved = list(results)

    onset_to_indices: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(resolved):
        onset_to_indices[round(r.note_event.onset, 6)].append(idx)

    sorted_onsets = sorted(onset_to_indices.keys())

    for oi in range(1, len(sorted_onsets)):
        curr_onset = sorted_onsets[oi]

        for curr_idx in onset_to_indices[curr_onset]:
            curr_r = resolved[curr_idx]
            if curr_r.state.fret == 0:
                continue  # open string — no left-hand finger to preserve

            # Scan backwards until we find the most recent occurrence of this
            # string, or exceed the lookback window.
            prev_finger: Finger | None = None
            for look_back in range(1, oi + 1):
                prev_onset = sorted_onsets[oi - look_back]
                if curr_onset - prev_onset > lookback_beats:
                    break  # outside the arpeggio window

                same_string_found = False
                for prev_idx in onset_to_indices[prev_onset]:
                    prev_r = resolved[prev_idx]
                    if prev_r.state.string_num != curr_r.state.string_num:
                        continue
                    same_string_found = True
                    if prev_r.state.fret == curr_r.state.fret and prev_r.state.fret != 0:
                        prev_finger = prev_r.state.finger  # same position → reuse
                    # Different fret on same string → finger has moved; no reuse.
                    break

                if same_string_found:
                    break  # found the most recent history for this string

            if prev_finger is None or prev_finger == curr_r.state.finger:
                continue  # nothing to fix

            # Guard: don't propagate a finger already used by another note in
            # the same chord — that would create a new conflict.
            fingers_already_used = {
                resolved[other_idx].state.finger
                for other_idx in onset_to_indices[curr_onset]
                if other_idx != curr_idx
                and resolved[other_idx].state.finger != Finger.OPEN
            }
            if prev_finger in fingers_already_used:
                continue  # propagating would cause a chord finger conflict

            # Search stored alternatives for a match first.
            new_state: FingeringState | None = None
            new_cost = curr_r.cost
            for alt_state, alt_cost in curr_r.alternatives:
                if (alt_state.string_num == curr_r.state.string_num
                        and alt_state.fret == curr_r.state.fret
                        and alt_state.finger == prev_finger):
                    new_state = alt_state
                    new_cost = alt_cost
                    break

            if new_state is None and prev_finger != Finger.OPEN:
                # Construct the state directly from finger + fret.
                offset = _FINGER_OFFSET.get(prev_finger, 0)
                hp = max(1, curr_r.state.fret - offset)
                new_state = FingeringState(
                    string_num=curr_r.state.string_num,
                    fret=curr_r.state.fret,
                    finger=prev_finger,
                    hand_position=hp,
                )

            if new_state is not None:
                resolved[curr_idx] = FingeringResult(
                    note_id=curr_r.note_id,
                    note_event=curr_r.note_event,
                    state=new_state,
                    cost=new_cost,
                    alternatives=curr_r.alternatives,
                )

    return resolved


def resolve_section_consistency(results: list[FingeringResult]) -> list[FingeringResult]:
    """Enforce consistent finger assignments for identical chord shapes.

    Groups all occurrences of the same (string_num, fret) pattern across the
    whole song.  The first occurrence of each shape sets the canonical finger
    assignment; subsequent occurrences adopt it.  This prevents the optimizer
    from drifting and producing different fingerings for the same repeated
    passage (verse/chorus repeats).

    Single-note onsets use per-(string, fret) canonical fingers.
    Multi-note onsets (chords) use the full shape canonical assignment,
    skipping application when it would create new finger conflicts.

    Args:
        results: Post-processed FingeringResult list.

    Returns:
        New list with cross-song fingering consistency enforced.
    """
    resolved = list(results)

    onset_to_indices: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(resolved):
        onset_to_indices[round(r.note_event.onset, 6)].append(idx)

    # canonical[shape] = {(string_num, fret): Finger}
    canonical: dict[frozenset[tuple[int, int]], dict[tuple[int, int], Finger]] = {}

    for onset in sorted(onset_to_indices.keys()):
        indices = onset_to_indices[onset]
        shape = frozenset(
            (resolved[i].state.string_num, resolved[i].state.fret)
            for i in indices
        )

        if shape not in canonical:
            # First occurrence — record as canonical.
            canonical[shape] = {
                (resolved[i].state.string_num, resolved[i].state.fret): resolved[i].state.finger
                for i in indices
            }
            continue

        canon = canonical[shape]

        # Check that applying the canonical assignment won't introduce conflicts.
        desired_fingers = [canon[(resolved[i].state.string_num, resolved[i].state.fret)]
                           for i in indices]
        fretted_desired = [f for f in desired_fingers if f != Finger.OPEN]
        if len(fretted_desired) != len(set(fretted_desired)):
            continue  # canonical assignment itself has conflicts — skip

        for i in indices:
            r = resolved[i]
            pos = (r.state.string_num, r.state.fret)
            desired = canon[pos]
            if r.state.finger == desired:
                continue

            # Apply canonical finger.
            if desired != Finger.OPEN:
                offset = _FINGER_OFFSET.get(desired, 0)
                hp = max(1, r.state.fret - offset)
            else:
                hp = r.state.hand_position
            new_state = FingeringState(
                string_num=r.state.string_num,
                fret=r.state.fret,
                finger=desired,
                hand_position=hp,
            )
            resolved[i] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=new_state,
                cost=r.cost,
                alternatives=r.alternatives,
            )

    return resolved


def compute_mechanical_cost(
    s1: FingeringState,
    s2: FingeringState,
    note: NoteEvent,
) -> float:
    """Aggregate mechanical cost C_méca(s1, s2).

    Combines four components:
    1. Position shift (wrist movement, tempo-weighted)
    2. Stretch (fret span from hand position)
    3. String change (number of strings crossed)
    4. Finger difficulty (intrinsic per-finger cost)

    Special case — same string and same fret:
    - Same finger: cost 0 (finger already placed, no movement).
    - Different finger: large penalty (redundant swap, physically wasteful).

    Args:
        s1: Previous fingering state.
        s2: Next fingering state.
        note: NoteEvent for s2 (tempo and duration context).

    Returns:
        Non-negative mechanical cost.
    """
    if s1.string_num == s2.string_num and s1.fret == s2.fret and s1.fret != 0:
        if s1.finger == s2.finger:
            return 0.0  # finger already in place — re-articulate at zero cost
        else:
            # Switching finger on the same fret: wasteful, add stiff penalty
            return cost_finger_difficulty(s2) + 4.0

    return (
        cost_position_shift(s1, s2, note)
        + cost_stretch(s1, s2)
        + cost_string_change(s1, s2)
        + cost_finger_difficulty(s2)
        + cost_sequential_crossing(s1, s2)
    )
