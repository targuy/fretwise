"""Scoring module (M4) — cost functions C_méca and C_music.

Implements the composite cost function:

    C(s1, s2) = α·C_méca(s1, s2) + β·C_music(s1, s2) + γ·C_joueur(s1, s2) + δ·C_péda(s1, s2)

Active components:
- C_méca: mechanical cost (position shift, stretch, string change, finger difficulty)
- C_music: musical cost (legato, slide, vibrato, bend, harmonic, tapping)

Stubs (returning 0.0):
- C_joueur: player feasibility cost (Phase 3)
- C_péda: pedagogical cost (Phase 3)

The coefficients α, β, γ, δ are **never** hardcoded in Viterbi (M5);
they are injected here as parameters so every mode (performance, musical,
learning, reference) can be expressed without modifying M5.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

logger = logging.getLogger(__name__)

from fretwise.models import Articulation, Finger, FingeringResult, FingeringState, NoteEvent
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

# ---------------------------------------------------------------------------
# Biomechanical rules for chord finger assignment
#
# These rules define the physical constraints of the human hand on a guitar
# neck. They are enforced by post-processing resolvers (M4) after Viterbi
# (M5), because Viterbi optimises note-by-note (time axis) and cannot see
# simultaneous chord constraints.
#
# Rule codes: R-C* = chord rules, R-S* = sequential rules, R-W* = wrist rules.
#
# R-C1  No-duplicate fingers
#   Two simultaneously fretted notes cannot share the same finger.
#   Exception: barré chords (one finger covering multiple strings at same fret).
#   Enforced by: resolve_chord_conflicts()
#
# R-C2  Open strings
#   Open strings (fret=0) require no fretting finger.  They are excluded from
#   all chord finger checks.
#
# R-C3  Monotone ordering
#   For any two simultaneously fretted notes A and B:
#       rank(A) < rank(B)  →  fret(A) ≤ fret(B)
#   where rank: INDEX=0, MIDDLE=1, RING=2, PINKY=3.
#   Violation means fingers physically cross each other (impossible).
#   Enforced by: resolve_chord_finger_ordering()
#
# R-C4  Finger-pair span limits (comfortable reach, not maximum stretch)
#   Maximum comfortable fret gap = rank_diff + 1:
#       INDEX  – MIDDLE : 2 frets  (rank_diff=1)
#       INDEX  – RING   : 3 frets  (rank_diff=2)
#       INDEX  – PINKY  : 4 frets  (rank_diff=3)
#       MIDDLE – RING   : 2 frets  (rank_diff=1)
#       MIDDLE – PINKY  : 3 frets  (rank_diff=2)
#       RING   – PINKY  : 2 frets  (rank_diff=1)
#   Enforced by: resolve_chord_finger_span()
#
# R-C5  Natural hand position / no finger skipping
#   The natural hand position (hp) equals the fret of the lowest note.
#   Each finger's natural fret = hp + its_offset, where
#   natural_offset = {INDEX:0, MIDDLE:1, RING:2, PINKY:3}.
#   A finger CANNOT skip over another finger's natural position.  For example:
#       frets [2, 4, 4]:  hp=2
#                         INDEX@2  (natural: hp+0=2)
#                         RING@4   (natural: hp+2=4, not MIDDLE whose natural is hp+1=3)
#                         PINKY@4  (stretch back 1 from natural hp+3=5)
#       Wrong: INDEX@2, MIDDLE@4, PINKY@4
#              (MIDDLE jumps from its natural position 3 to 4, skipping RING's territory)
#       Correct: INDEX@2, RING@4, PINKY@4
#   Implemented by: _natural_finger_assignment() used in both chord resolvers.
#
# R-C6  String-rank diagonal preference
#   The left wrist bends more naturally inward (toward the player's body) than
#   outward, producing a diagonal from high-pitch strings (string 1, high e) to
#   low-pitch strings (string 6, low E).  Lower-rank fingers (INDEX, MIDDLE)
#   align naturally with higher-pitch strings; higher-rank fingers (RING, PINKY)
#   with lower-pitch strings.
#   Rule: for any two simultaneously fretted notes at the SAME fret, the note on
#   the lower string number (higher pitch) should have the lower-rank finger.
#       Example 300003:  string 1 fret 3  →  INDEX (or MIDDLE)
#                        string 6 fret 3  →  MIDDLE (or RING/PINKY)
#       Wrong:  RING on string 1, MIDDLE on string 6
#       Correct: INDEX on string 1, MIDDLE on string 6
#   When frets differ, R-C3 takes absolute priority; R-C6 only applies as a
#   tiebreaker within equal-fret subgroups.
#   Implemented by: _natural_finger_assignment() with notes sorted by
#   (fret, string_num) in resolve_chord_string_diagonal().
#
# R-S1  Sequential crossing penalty
#   In a melodic run within the same hand position, finger rank direction must
#   match fret direction (ascending frets → ascending rank, and vice versa).
#   Penalty: _SEQUENTIAL_CROSS_PENALTY (2.0) added to C_méca.
#   Exempt when the hand position shifts > _SHIFT_EXEMPT_THRESHOLD frets.
#   Implemented by: cost_sequential_crossing(), in compute_mechanical_cost()
#
# R-S2  Section / shape consistency
#   Identical chord shapes (same string+fret positions) receive the same finger
#   assignment throughout the piece.  Shape-equivalent chords (same relative
#   pattern at different neck positions, e.g. 442→664→886) also share the same
#   relative finger assignment.
#   Enforced by: resolve_section_consistency()
#
# R-W1  Total chord fret span ≤ 4 frets
#   All fretted notes in a chord must lie within a 4-fret window.
#   Outlier notes are revoiced to alternative positions when possible.
#   Enforced by: resolve_chord_stretch()
#
# R-W2  Tempo-weighted wrist shift cost
#   Shifting the hand position between consecutive notes costs:
#   C_shift = |Δposition| / max(duration_seconds, 0.1)
#   Implemented by: cost_position_shift(), in compute_mechanical_cost()
# ---------------------------------------------------------------------------


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
        c_music = compute_musical_cost(s1, s2, note)
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
    For ANY two simultaneously fretted notes A and B:
        rank(A) < rank(B)  →  fret(A) ≤ fret(B)
    Violation means fingers would physically cross (impossible).

    The check uses all-pairs comparison so equal-fret groups containing a
    low-rank finger alongside a high-rank finger are correctly flagged when a
    LOWER fret note exists in the chord (the bug in the old sequential algo).

    Correction: re-sort the existing set of fingers by rank and assign them to
    notes sorted by fret (lowest-rank → lowest-fret).

    Open strings and notes already at fret 0 are never touched.
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue

        fretted = [
            (idx, resolved[idx].state.fret, resolved[idx].state.finger,
             resolved[idx].state.string_num)
            for idx in indices
            if resolved[idx].state.fret > 0 and resolved[idx].state.finger != Finger.OPEN
        ]
        if len(fretted) < 2:
            continue

        # Skip barré chords (duplicate fingers or more notes than fingers available).
        unique_fingers = {f for _, _, f, _ in fretted}
        if len(fretted) > len(unique_fingers) or len(fretted) > 4:
            continue

        # All-pairs monotone check (R-C3): for every pair (A, B),
        # rank(A) < rank(B) must imply fret(A) ≤ fret(B).
        is_monotone = True
        for i in range(len(fretted)):
            _, fret_a, finger_a, _ = fretted[i]
            rank_a = _FINGER_RANK.get(finger_a, 0)
            for j in range(i + 1, len(fretted)):
                _, fret_b, finger_b, _ = fretted[j]
                rank_b = _FINGER_RANK.get(finger_b, 0)
                if (rank_a < rank_b and fret_a > fret_b) or (
                    rank_b < rank_a and fret_b > fret_a
                ):
                    is_monotone = False
                    break
            if not is_monotone:
                break

        if is_monotone:
            continue

        # Correction: use natural hand position algorithm (R-C5 + R-C6).
        # Sort by (fret, string_num): within equal frets, high-pitch strings
        # (low string_num) come first so lower-rank fingers land there (diagonal).
        fretted_by_fret = sorted(fretted, key=lambda t: (t[1], t[3]))
        frets_sorted = [t[1] for t in fretted_by_fret]
        note_indices_sorted = [t[0] for t in fretted_by_fret]

        valid_fingers = _natural_finger_assignment(frets_sorted)
        if valid_fingers is None:
            onset_val = resolved[fretted[0][0]].note_event.onset
            logger.warning(
                "No valid finger assignment for chord at onset %.3f "
                "(frets %s) — leaving current assignment.",
                onset_val, frets_sorted,
            )
            continue

        new_finger_map = dict(zip(note_indices_sorted, valid_fingers))

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


# Maximum comfortable fret span between two fingers in a chord.
# Formula: max_span = rank_diff + 1  (1 fret slack beyond the natural offset gap).
# Adjacent fingers (rank_diff=1): max 2 frets.
# Skip-one  fingers (rank_diff=2): max 3 frets.
# Index–Pinky       (rank_diff=3): max 4 frets (= chord stretch limit).
_MAX_FINGER_PAIR_SPAN: dict[tuple[int, int], int] = {
    (0, 1): 2,  # index–middle
    (0, 2): 3,  # index–ring
    (0, 3): 4,  # index–pinky
    (1, 2): 2,  # middle–ring
    (1, 3): 3,  # middle–pinky
    (2, 3): 2,  # ring–pinky
}

_FRETTED_FINGERS: list[Finger] = [Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY]


def _natural_finger_assignment(frets: list[int]) -> list[Finger] | None:
    """Assign fingers to sorted frets using the natural hand position algorithm (R-C5).

    The natural hand position (hp) is derived from the lowest fret::

        hp = frets[0]

    For each fret (ascending), the preferred finger is the one whose natural
    position equals the fret::

        natural_offset = fret - hp
        preferred: _FRETTED_FINGERS[natural_offset]  (INDEX=0, MIDDLE=1, RING=2, PINKY=3)

    If the naturally preferred finger is already taken, the next higher-rank
    finger is tried first (toward pinky) — preventing a lower-rank finger from
    jumping over a higher-rank finger's natural territory (R-C5).  Only if no
    higher-rank finger is available does the algorithm fall back to lower-rank
    fingers (stretch toward headstock).

    After assignment, all finger-pair span limits (R-C4) are validated.

    Args:
        frets: Fret values sorted ascending (ties allowed), length 1–4.

    Returns:
        List of Finger values (same length as frets), or None if no valid
        assignment exists within anatomical limits.
    """
    n = len(frets)
    if n == 0 or n > 4:
        return None

    hp = frets[0]
    available = list(range(4))  # 0=INDEX, 1=MIDDLE, 2=RING, 3=PINKY offsets
    result_offsets: list[int] = []

    for fret in frets:
        natural = fret - hp
        chosen: int | None = None

        # Prefer natural offset or the first available higher offset (toward pinky).
        for off in range(max(0, natural), 4):
            if off in available:
                chosen = off
                available.remove(off)
                break

        # Fallback: try lower offsets (stretch toward headstock).
        if chosen is None:
            for off in range(max(0, natural) - 1, -1, -1):
                if off in available:
                    chosen = off
                    available.remove(off)
                    break

        if chosen is None:
            return None  # no finger left

        result_offsets.append(chosen)

    fingers = [_FRETTED_FINGERS[o] for o in result_offsets]

    # Validate R-C4: all finger-pair span limits.
    for i in range(n):
        for j in range(i + 1, n):
            ri = _FINGER_RANK[fingers[i]]
            rj = _FINGER_RANK[fingers[j]]
            low_rank, high_rank = (ri, rj) if ri < rj else (rj, ri)
            gap = abs(frets[j] - frets[i])
            if gap > _MAX_FINGER_PAIR_SPAN.get((low_rank, high_rank), 4):
                return None

    return fingers


def resolve_chord_finger_span(results: list[FingeringResult]) -> list[FingeringResult]:
    """Enforce per-finger-pair fret-span limits within simultaneous chords.

    Even after monotone ordering is correct, a chord can still be unplayable
    if two anatomically adjacent fingers are assigned frets that are too far
    apart.  The biomechanical limits (comfortable reach, not extreme stretch):

        Adjacent fingers  (rank diff 1): max 2 frets
        Skip-one fingers  (rank diff 2): max 3 frets
        Index–Pinky       (rank diff 3): max 4 frets

    Derivation: natural spacing between consecutive fingers = 1 fret (the
    1-finger-per-fret rule), so allowing 1 extra fret of stretch gives the
    max = rank_diff + 1.

    When a violation is detected the algorithm searches for the lexicographically
    smallest valid finger assignment (index preferred) that satisfies both
    monotone ordering and all pair-span limits.  If none exists the chord is
    left unchanged and a warning is logged.

    This resolver must run AFTER resolve_chord_finger_ordering.
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue

        fretted = [
            (idx, resolved[idx].state.fret, resolved[idx].state.finger,
             resolved[idx].state.string_num)
            for idx in indices
            if resolved[idx].state.fret > 0 and resolved[idx].state.finger != Finger.OPEN
        ]
        if len(fretted) < 2:
            continue

        unique_fingers = {f for _, _, f, _ in fretted}
        if len(fretted) > len(unique_fingers) or len(fretted) > 4:
            continue

        # Check all pairs for span violations (R-C4).
        has_violation = False
        for i in range(len(fretted)):
            _, fret_a, finger_a, _ = fretted[i]
            rank_a = _FINGER_RANK.get(finger_a, 0)
            for j in range(i + 1, len(fretted)):
                _, fret_b, finger_b, _ = fretted[j]
                rank_b = _FINGER_RANK.get(finger_b, 0)
                if rank_a >= rank_b:
                    continue
                gap = abs(fret_b - fret_a)
                if gap > _MAX_FINGER_PAIR_SPAN.get((rank_a, rank_b), 4):
                    has_violation = True
                    break
            if has_violation:
                break

        if not has_violation:
            continue

        # Search for a valid reassignment using natural algorithm (R-C5 + R-C6).
        fretted_by_fret = sorted(fretted, key=lambda t: (t[1], t[3]))
        frets_sorted = [t[1] for t in fretted_by_fret]
        note_indices_sorted = [t[0] for t in fretted_by_fret]

        valid_fingers = _natural_finger_assignment(frets_sorted)
        if valid_fingers is None:
            onset_val = resolved[fretted[0][0]].note_event.onset
            logger.warning(
                "No valid finger assignment for chord at onset %.3f "
                "(frets %s) — leaving current assignment.",
                onset_val, frets_sorted,
            )
            continue

        for note_idx, new_finger in zip(note_indices_sorted, valid_fingers):
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


def resolve_chord_string_diagonal(results: list[FingeringResult]) -> list[FingeringResult]:
    """Apply the string-rank diagonal preference within simultaneous chords (R-C6).

    The left wrist's natural inward bend aligns lower-rank fingers with
    higher-pitch strings (string 1 = high e) and higher-rank fingers with
    lower-pitch strings (string 6 = low E).

    This resolver sorts fretted notes by ``(fret, string_num)`` and calls
    ``_natural_finger_assignment``:

    - For **equal-fret** notes the sort puts lower string numbers first, so
      lower-rank fingers land on higher-pitch strings.  Example: ``300003``
      → INDEX on string 1, MIDDLE on string 6 (not RING/MIDDLE reversed).
    - For **different-fret** notes R-C3 already forces the correct rank order
      via fret sorting; this resolver reinforces the same outcome.

    Barré chords (duplicate fingers or > 4 fretted notes) are skipped.
    This resolver must run **after** resolve_chord_finger_ordering and
    resolve_chord_finger_span, and **before** resolve_section_consistency.
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue

        fretted = [
            (idx, resolved[idx].state.fret, resolved[idx].state.finger,
             resolved[idx].state.string_num)
            for idx in indices
            if resolved[idx].state.fret > 0 and resolved[idx].state.finger != Finger.OPEN
        ]
        if len(fretted) < 2:
            continue

        # Skip barré chords.
        unique_fingers = {f for _, _, f, _ in fretted}
        if len(fretted) > len(unique_fingers) or len(fretted) > 4:
            continue

        # Sort by (fret, string_num) — canonical diagonal order.
        fretted_sorted = sorted(fretted, key=lambda t: (t[1], t[3]))
        current_fingers = [t[2] for t in fretted_sorted]
        frets_sorted = [t[1] for t in fretted_sorted]
        note_indices_sorted = [t[0] for t in fretted_sorted]

        valid_fingers = _natural_finger_assignment(frets_sorted)
        if valid_fingers is None or valid_fingers == current_fingers:
            continue

        for note_idx, new_finger in zip(note_indices_sorted, valid_fingers):
            r = resolved[note_idx]
            if r.state.finger == new_finger:
                continue
            offset = _FINGER_OFFSET.get(new_finger, 0)
            hp = max(1, r.state.fret - offset)
            resolved[note_idx] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=r.state.fret,
                    finger=new_finger,
                    hand_position=hp,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
            )

    return resolved


def _chord_relative_shape(
    notes: list[tuple[int, int]],
) -> frozenset[tuple[int, int]]:
    """Return the relative shape of a chord as (string_delta, fret_delta) from anchor.

    The anchor is the note with the lowest fret (ties broken by lowest string
    number, i.e. highest-pitch string).  This makes chords at different
    positions on the neck share the same shape key when they use the same
    fingering pattern — e.g. a power-chord shape is the same regardless of
    which position it is played at.

    Args:
        notes: List of (string_num, fret) for each note in the chord.

    Returns:
        Frozenset of (string_delta, fret_delta) tuples.
    """
    anchor_fret = min(f for _, f in notes if f > 0) if any(f > 0 for _, f in notes) else 0
    anchor_str = min(s for s, f in notes if f == anchor_fret) if anchor_fret > 0 else min(s for s, _ in notes)
    return frozenset((s - anchor_str, f - anchor_fret) for s, f in notes)


def resolve_section_consistency(results: list[FingeringResult]) -> list[FingeringResult]:
    """Enforce consistent finger assignments for identical and shape-equivalent chords.

    Two passes:

    **Pass 1 — Exact match**: chords sharing the same absolute (string, fret)
    positions across the song get the same finger assignment.  The first fully
    resolved occurrence sets the canonical.

    **Pass 2 — Shape match**: chords with the same *relative* shape
    (string_delta, fret_delta from the lowest-fret anchor note) but at
    different positions on the neck get the same *relative* finger assignment.
    For example, a power-chord shape played at fret 2 and again at fret 6 will
    receive the same finger roles (index on root, ring+pinky on the fifth).

    This resolver must run **after** all chord-conflict, stretch, ordering, and
    span resolvers so the canonical is always taken from a fully-valid chord.

    Args:
        results: Fully post-processed FingeringResult list.

    Returns:
        New list with cross-song fingering consistency enforced.
    """
    resolved = list(results)

    onset_to_indices: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(resolved):
        onset_to_indices[round(r.note_event.onset, 6)].append(idx)

    def _apply_canon(
        indices: list[int],
        finger_map: dict[tuple[int, int], Finger],
    ) -> None:
        """Apply a canonical finger map {(string, fret): Finger} to a chord."""
        desired = [finger_map.get(
            (resolved[i].state.string_num, resolved[i].state.fret), resolved[i].state.finger
        ) for i in indices]
        # Guard: never assign OPEN to a fretted note, or a fretting finger to an open string.
        desired = [
            f if (f == Finger.OPEN) == (resolved[i].state.fret == 0) else resolved[i].state.finger
            for i, f in zip(indices, desired)
        ]
        fretted = [f for f in desired if f != Finger.OPEN]
        if len(fretted) != len(set(fretted)):
            return  # would introduce conflicts — skip
        for i, new_finger in zip(indices, desired):
            r = resolved[i]
            if r.state.finger == new_finger:
                continue
            offset = _FINGER_OFFSET.get(new_finger, 0) if new_finger != Finger.OPEN else 0
            hp = max(1, r.state.fret - offset) if new_finger != Finger.OPEN else r.state.hand_position
            resolved[i] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=r.state.fret,
                    finger=new_finger,
                    hand_position=hp,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
            )

    # ── Pass 1: exact (string, fret) shape ──────────────────────────────────
    # canonical_exact: frozenset{(str,fret)} → {(str,fret): Finger}
    canonical_exact: dict[frozenset[tuple[int, int]], dict[tuple[int, int], Finger]] = {}

    for onset in sorted(onset_to_indices.keys()):
        indices = onset_to_indices[onset]
        abs_shape = frozenset(
            (resolved[i].state.string_num, resolved[i].state.fret) for i in indices
        )
        if abs_shape not in canonical_exact:
            canonical_exact[abs_shape] = {
                (resolved[i].state.string_num, resolved[i].state.fret): resolved[i].state.finger
                for i in indices
            }
        else:
            _apply_canon(indices, canonical_exact[abs_shape])

    # ── Pass 2: relative shape (transposed patterns) ─────────────────────────
    # relative_canon: frozenset{(dstr,dfret)} → {(dstr,dfret): Finger}
    # Applied only to multi-note chords (shape shift is only meaningful there).
    relative_canon: dict[frozenset[tuple[int, int]], dict[tuple[int, int], Finger]] = {}

    for onset in sorted(onset_to_indices.keys()):
        indices = onset_to_indices[onset]
        if len(indices) < 2:
            continue  # single notes handled by pass 1

        notes = [(resolved[i].state.string_num, resolved[i].state.fret) for i in indices]
        rel_shape = _chord_relative_shape(notes)

        # Compute anchor for this occurrence.
        anchor_fret = min(f for _, f in notes if f > 0) if any(f > 0 for _, f in notes) else 0
        anchor_str = (
            min(s for s, f in notes if f == anchor_fret) if anchor_fret > 0
            else min(s for s, _ in notes)
        )

        if rel_shape not in relative_canon:
            # Only store as canonical if the chord has at least one fretted note.
            # All-open chords should never dictate fingers for fretted chords.
            if any(f > 0 for _, f in notes):
                relative_canon[rel_shape] = {
                    (s - anchor_str, f - anchor_fret): resolved[i].state.finger
                    for i, (s, f) in zip(indices, notes)
                }
        else:
            # Build absolute finger map for this occurrence from the relative canon.
            rel_c = relative_canon[rel_shape]
            abs_map: dict[tuple[int, int], Finger] = {
                (anchor_str + ds, anchor_fret + df): finger
                for (ds, df), finger in rel_c.items()
            }
            _apply_canon(indices, abs_map)

    return resolved


def compute_musical_cost(
    s1: FingeringState,
    s2: FingeringState,
    note: NoteEvent,
) -> float:
    """Aggregate musical cost C_music(s1, s2).

    Penalises fingering choices that conflict with the note's articulation.
    Each sub-component returns a non-negative cost; their sum is the total
    C_music for the transition.

    Components:
    1. Legato same-string requirement (hammer-on, pull-off, legato)
    2. Slide same-string requirement
    3. Vibrato position quality (open-string penalty, low-fret penalty)
    4. Bend feasibility (open-string impossible, thick-string difficulty)
    5. Harmonic position matching (natural harmonics at specific frets)

    Args:
        s1: Previous (source) fingering state.
        s2: Next (target) fingering state.
        note: NoteEvent for s2 (provides articulation context).

    Returns:
        Non-negative musical cost.
    """
    cost = 0.0

    # --- 1. Legato same-string requirement ---
    # Hammer-on, pull-off, and legato are physically impossible across strings.
    if note.articulation in (
        Articulation.HAMMER_ON,
        Articulation.PULL_OFF,
        Articulation.LEGATO,
    ):
        if s1.string_num != s2.string_num:
            cost += 5.0  # strong penalty: technique impossible across strings

    # --- 2. Slide same-string requirement ---
    # Slides require the finger to glide along a single string.
    if note.slide_type is not None:
        if s1.string_num != s2.string_num:
            cost += 5.0  # slide impossible across strings

    # --- 3. Vibrato position quality ---
    # Vibrato is achieved by oscillating the fretting finger. Open strings
    # cannot be vibrated (no fretting finger); very low frets near the nut
    # have less room for finger oscillation.
    if note.articulation in (Articulation.VIBRATO, Articulation.WIDE_VIBRATO):
        if s2.fret == 0:
            cost += 4.0  # open string: vibrato impossible
        elif s2.fret <= 2:
            cost += 1.5  # frets 1-2: vibrato awkward near the nut
    # Wide vibrato needs more finger travel; penalise further on low frets.
    if note.vibrato_wide and 0 < s2.fret <= 3:
        cost += 1.0

    # --- 4. Bend feasibility ---
    # Bending requires pushing/pulling the string sideways.  Open strings
    # cannot be bent.  Wound strings (6, 5, 4) are harder to bend,
    # especially for larger bend values.
    if note.bend_value is not None and note.bend_value > 0:
        if s2.fret == 0:
            cost += 6.0  # open string: bend impossible
        else:
            # Wound strings (low E=6, A=5, D=4) require more force.
            if s2.string_num >= 5:
                cost += 1.5 * note.bend_value  # strings 5-6: heavy wound
            elif s2.string_num == 4:
                cost += 0.8 * note.bend_value  # string 4: medium wound

    # --- 5. Natural harmonic position matching ---
    # Natural harmonics ring at specific fret positions (5, 7, 12, 19).
    # If the source specifies a harmonic_fret, the fingering should match.
    if note.harmonic_type == "natural" and note.harmonic_fret is not None:
        if s2.fret != note.harmonic_fret:
            cost += 4.0  # wrong fret for the harmonic node

    # --- 6. Muted / tapping modifiers ---
    # Tapping is easier at higher frets where the action is lower.
    if note.tapping and s2.fret < 5:
        cost += 1.5  # tapping near the nut is harder

    return cost


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
