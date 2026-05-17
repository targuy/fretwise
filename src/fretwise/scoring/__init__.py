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

from fretwise.models import Articulation, Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.profile import PlayerProfile, default_profile

logger = logging.getLogger(__name__)

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
    Finger.MIDDLE: 1.15,
    Finger.RING: 1.3,
    Finger.PINKY: 1.5,
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
#
# R-W3  Floor constraint — no finger below hand position
#   For any fretted FingeringState, fret >= hand_position.
#   Rationale: hand_position = fret of INDEX (offset=0). Any other finger at a
#   fret LOWER than INDEX's position would physically cross below the index —
#   anatomically impossible without extreme wrist contortion.
#   The generator guarantees this by construction (hand_position = fret − offset
#   → fret = hand_position + offset ≥ hand_position for offset ≥ 0).
#   Post-processing resolvers must not break this invariant: when computing a
#   new target_hp, skip notes whose fret < target_hp rather than clamping.
#   Enforced by: generator invariant + guard in resolve_arpeggio_chord_fingering()
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


@dataclass(frozen=True)
class RulePreferences:
    """Runtime toggles for optional fingering arbitration heuristics."""

    same_finger_motion_penalty: bool = True
    infer_implicit_legato: bool = True


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
        rule_preferences: RulePreferences | None = None,
    ) -> None:
        self._weights = weights or CostWeights.reference()
        self._profile = profile or default_profile()
        self._rule_preferences = rule_preferences or RulePreferences()
        # B integration: per-note-index segment anchor lookup. Populated by
        # the pipeline before each voice's Viterbi run via set_segment_anchors.
        # None disables segment-aware shift (fallback to A' tolerance).
        self._segment_anchors: list[int | None] | None = None

    def set_segment_anchors(self, anchors: list[int | None]) -> None:
        """Activate segment-aware shift cost for the next Viterbi run.

        Args:
            anchors: One entry per note in the sequence. ``anchors[i]`` is the
                fret anchor of the segment containing note ``i``, or ``None``
                if the note is not anchored (open strings, unhinted notes).
                A None on either side of a transition falls back to the
                A' per-state shift cost for that transition.
        """
        self._segment_anchors = list(anchors)

    def clear_segment_anchors(self) -> None:
        """Disable segment-aware shift cost (fallback to A' behaviour)."""
        self._segment_anchors = None

    def transition_cost(
        self,
        s1: FingeringState,
        s2: FingeringState,
        note: NoteEvent,
        index: int | None = None,
    ) -> float:
        """Compute the composite transition cost between two fingering states.

        Args:
            s1: The previous (source) fingering state.
            s2: The next (target) fingering state.
            note: The NoteEvent associated with s2 (provides tempo context).
            index: Index of s2 in the sequence (0-based). Used to consult
                segment anchors when ``set_segment_anchors`` has been called.
                Defaults to None for backward compatibility with callers that
                don't track positional context.

        Returns:
            Non-negative composite cost. Lower = more desirable transition.
        """
        w = self._weights
        anchor_prev: int | None = None
        anchor_curr: int | None = None
        if (
            self._segment_anchors is not None
            and index is not None
            and 0 < index < len(self._segment_anchors)
        ):
            anchor_prev = self._segment_anchors[index - 1]
            anchor_curr = self._segment_anchors[index]
        c_meca = compute_mechanical_cost(
            s1,
            s2,
            note,
            rule_preferences=self._rule_preferences,
            segment_anchor_prev=anchor_prev,
            segment_anchor_curr=anchor_curr,
        )
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
    open_transition = (
        s1.finger == Finger.OPEN
        or s2.finger == Finger.OPEN
        or s1.fret == 0
        or s2.fret == 0
    )

    # hand_position = fret - finger_offset, so changing finger alone can change hp by up
    # to 3 even if the hand stays physically anchored. Absorb a 1-fret tolerance so that
    # adjacent finger swaps (e.g. INDEX@3 → MIDDLE@5: hp 3→4) don't read as a real shift.
    raw_shift = abs(s2.hand_position - s1.hand_position)
    shift = max(0, raw_shift - 1)
    if shift == 0:
        return 0.0
    # beats_per_minute / 60 = beats per second; duration in beats → seconds
    # Short duration = fast note = harder to shift
    seconds = note.duration * 60.0 / max(note.tempo, 1.0)
    tempo_factor = 1.0 / max(seconds, 0.1)  # cap to avoid infinity
    if open_transition:
        # Open strings allow hand motion while sounding, but the reset is not free.
        return 0.35 * shift * tempo_factor

    return shift * tempo_factor


def cost_position_shift_segment_aware(
    s1: FingeringState,
    s2: FingeringState,
    note: NoteEvent,
    anchor_prev: int,
    anchor_curr: int,
) -> float:
    """Segment-aware variant of ``cost_position_shift`` (B integration).

    When both notes belong to the same segment (same anchor), the cost is 0:
    the hand is physically anchored, no real wrist motion is required. When
    they belong to different segments, the cost is proportional to the
    anchor delta — which is the actual physical hand-position change.

    This eliminates the F2/F3/F4 pathologies caused by the per-state
    ``hand_position = fret - finger_offset`` confounding finger changes with
    real wrist shifts.

    Args:
        s1: Source state.
        s2: Target state.
        note: NoteEvent for s2 (provides tempo / duration).
        anchor_prev: Hand anchor (lowest fret) of the segment containing s1.
        anchor_curr: Hand anchor of the segment containing s2.

    Returns:
        Non-negative cost. 0.0 when same segment.
    """
    if anchor_prev == anchor_curr:
        return 0.0

    open_transition = (
        s1.finger == Finger.OPEN
        or s2.finger == Finger.OPEN
        or s1.fret == 0
        or s2.fret == 0
    )
    shift = abs(anchor_curr - anchor_prev)
    seconds = note.duration * 60.0 / max(note.tempo, 1.0)
    tempo_factor = 1.0 / max(seconds, 0.1)
    if open_transition:
        return 0.35 * shift * tempo_factor
    return shift * tempo_factor


def cost_stretch(s1: FingeringState, s2: FingeringState) -> float:
    """Penalty for large fret stretches within a hand position.

    The stretch cost is the deviation from the finger's natural offset in the
    current hand position:

    - INDEX natural offset = 0
    - MIDDLE natural offset = 1
    - RING natural offset = 2
    - PINKY natural offset = 3

    Example: ring on fret 3 with hand_position 1 is natural (offset 2), so
    stretch = 0.  This avoids over-penalising ring/pinky in first-position
    chord shapes and arpeggios.

    Higher frets on the neck are physically easier because fret spacing is
    smaller, so we apply a mild reduction factor.

    Args:
        s1: Source state (unused in MVP; reserved for context in Phase 2).
        s2: Target state.

    Returns:
        Non-negative cost.
    """
    if s2.fret == 0:
        return 0.0

    desired_offset = max(s2.fret - s2.hand_position, 0)
    natural_offset = _FINGER_OFFSET.get(s2.finger, 0)
    stretch = abs(desired_offset - natural_offset)

    # Frets above 12 are physically closer together; reduce cost slightly.
    position_factor = 1.0 - 0.3 * min(s2.hand_position / 12.0, 1.0)
    return stretch * position_factor


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


def cost_same_finger_motion(
    s1: FingeringState,
    s2: FingeringState,
    note: NoteEvent,
    *,
    rule_preferences: RulePreferences | None = None,
) -> float:
    """Penalty for dragging the same fretting finger through a melodic run.

    Reusing the same finger on a new fret is mechanically possible, but in fast
    passages it often produces unrealistic one-finger lines where the whole hand
    chases every note.  This cost discourages that pattern while preserving
    barré-like movement across strings on the same fret.

    No penalty is applied when:
    - Either note is open.
    - A different finger is used.
    - The fret does not change (barré / finger roll territory).
    - The target note is an explicit slide destination.

    Args:
        s1: Previous fingering state.
        s2: Next fingering state.
        note: Note event for s2 (tempo and duration context).

    Returns:
        Non-negative penalty.
    """
    prefs = rule_preferences or RulePreferences()
    if not prefs.same_finger_motion_penalty:
        return 0.0

    if s1.finger == Finger.OPEN or s2.finger == Finger.OPEN:
        return 0.0
    if s1.finger != s2.finger:
        return 0.0

    fret_delta = abs(s2.fret - s1.fret)
    if fret_delta == 0:
        return 0.0

    if note.slide_type is not None or note.articulation == Articulation.SLIDE:
        return 0.0

    # Optional heuristic: if notation is missing but the movement strongly
    # resembles a brief legato on the same string, avoid over-penalizing it.
    if (
        prefs.infer_implicit_legato
        and s1.string_num == s2.string_num
        and fret_delta == 1
        and note.duration <= 0.5
    ):
        return 0.0

    string_delta = abs(s2.string_num - s1.string_num)
    seconds = note.duration * 60.0 / max(note.tempo, 1.0)
    tempo_factor = 1.0 / max(seconds, 0.2)
    return ((1.5 * fret_delta) + (0.75 * string_delta)) * tempo_factor


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
            logger.debug(
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
            logger.debug(
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


# ---------------------------------------------------------------------------
# Sedentary / pivot fingers
#
# See docs/finger_placement_strategy.md for the full specification.  This
# resolver annotates each FingeringResult with the fingers that remain
# pressed (planted) at that note but are NOT its active finger.  It does
# not rewrite FingeringState — it only populates the `planted_fingers`
# field.  Safe to run anywhere in the pipeline without invalidating
# downstream resolvers.
# ---------------------------------------------------------------------------

# Max beats a finger may remain "planted" without reuse before it is
# considered released.  4 beats = 1 full 4/4 measure; beyond that the
# player has almost certainly lifted the finger even if the hand itself
# did not shift.
_SEDENTARY_MAX_INACTIVE_BEATS: float = 4.0

# Max distance (in notes) within which the NEXT use of a finger must
# occur at the same (string, fret) to justify staying planted (R3a).
_SEDENTARY_REUSE_LOOKAHEAD_NOTES: int = 4

# Max onset gap (beats) that qualifies two notes as "same chord context"
# for the arpeggiation rule R3b.
_SEDENTARY_CHORD_CONTEXT_BEATS: float = 2.0


def _has_future_reuse(
    results: list[FingeringResult],
    start_idx: int,
    finger: Finger,
    pos: tuple[int, int],
    lookahead: int = _SEDENTARY_REUSE_LOOKAHEAD_NOTES,
) -> bool:
    """True iff the NEXT use of ``finger`` after ``start_idx`` is at ``pos``.

    Biomechanical invariant: a finger is sedentary only if its *next action*
    is to re-press the same (string, fret).  If the finger's next action is
    to move to a different position, it is NOT staying put between now and
    then — the "planted" label would be misleading.

    Implementation: scan forward notes in order and return the verdict on
    the FIRST encountered use of ``finger``.  If none occurs within the
    lookahead, return False.
    """
    end = min(len(results), start_idx + 1 + lookahead)
    for j in range(start_idx + 1, end):
        st = results[j].state
        if st.finger == finger:
            return (st.string_num, st.fret) == pos
    return False


def _in_chord_context(
    pos_onset: float,
    pos_hand: int,
    current: FingeringResult,
) -> bool:
    """True iff the planted finger's placement shares a chord context with the
    current note (same ``hand_position`` and close in time)."""
    if pos_hand != current.state.hand_position:
        return False
    return (current.note_event.onset - pos_onset) <= _SEDENTARY_CHORD_CONTEXT_BEATS


# ---------------------------------------------------------------------------
# Partial-barre detection
#
# When a chord has 2+ notes on ADJACENT strings at the SAME fret, a real
# guitarist plays them with a single INDEX barre, not with two-or-three
# separate fingers stacked at the same fret.  The state generator produces
# one FingeringState per finger per note; Viterbi+ordering then picks a
# plausible-but-cramped "3 fingers on one fret" solution that is unplayable
# as soon as a 4th finger is needed somewhere else on a different fret.
#
# This resolver detects the barre candidate sub-group of a chord, assigns
# INDEX to all barre notes, and re-assigns the remaining fingers (MIDDLE,
# RING, PINKY) based on their natural offset from hp = barre_fret.
# ---------------------------------------------------------------------------


def _find_partial_barre(
    chord_notes: list[tuple[int, int, int]],
) -> tuple[list[int], int] | tuple[None, None]:
    """Find the subset of chord notes at the lowest fret that form a barre.

    Rule:
      * Contiguous-string subset of >= 2 notes → partial barre (always).
      * Non-contiguous subset of >= 3 notes at the same lowest fret → full
        barre across the gaps (the index is physically flat across the neck;
        for 3+ notes the barre is always the natural fingering).

    Args:
        chord_notes: list of (note_idx, string_num, fret) for the fretted
            notes of one chord.

    Returns:
        (list of note indices forming the barre, barre_fret) or
        (None, None) if no barre applies.
    """
    if len(chord_notes) < 2:
        return None, None
    lowest_fret = min(f for _, _, f in chord_notes)
    lowest_notes = [(idx, s) for idx, s, f in chord_notes if f == lowest_fret]
    if len(lowest_notes) < 2:
        return None, None

    lowest_notes.sort(key=lambda x: x[1])
    strings = [s for _, s in lowest_notes]

    # Case 1 — entire lowest-fret set is contiguous.
    is_contiguous = all(
        strings[i + 1] - strings[i] == 1 for i in range(len(strings) - 1)
    )
    if is_contiguous:
        return [idx for idx, _ in lowest_notes], lowest_fret

    # Case 2 — non-contiguous lowest-fret notes.  Accept as a FULL barre
    # only if there are 3+ notes (the physical reality of a flat index
    # across the neck in E/A-shape barre chords).  For 2 non-contiguous
    # notes, two separate fingers are the natural choice.
    if len(lowest_notes) >= 3:
        return [idx for idx, _ in lowest_notes], lowest_fret

    # Case 3 — contiguous sub-run within a larger non-contiguous set.
    best: list[tuple[int, int]] = [lowest_notes[0]]
    current: list[tuple[int, int]] = [lowest_notes[0]]
    for n in lowest_notes[1:]:
        if n[1] == current[-1][1] + 1:
            current.append(n)
        else:
            if len(current) > len(best):
                best = list(current)
            current = [n]
    if len(current) > len(best):
        best = current
    if len(best) >= 2:
        return [idx for idx, _ in best], lowest_fret
    return None, None


def resolve_chord_partial_barre(
    results: list[FingeringResult],
) -> list[FingeringResult]:
    """Collapse adjacent-string same-fret chord subsets to an INDEX barre.

    Rule: a chord whose lowest fret is occupied by 2+ adjacent-string notes
    is naturally played with an index barre across those strings.  Using
    three separate fingers at the same fret forces stacked geometry and
    makes any extra extension (pinky two frets above, for instance)
    physically impossible.

    The resolver:
      * Detects the contiguous-strings lowest-fret subset
      * Assigns INDEX to every note of the subset
      * Sets ``hand_position = barre_fret`` on every note of the chord
      * Re-assigns MIDDLE / RING / PINKY to the remaining fretted notes
        based on their natural offset from ``barre_fret``
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)

    for indices in onset_groups.values():
        if len(indices) < 2:
            continue
        fretted: list[tuple[int, int, int]] = [
            (idx, resolved[idx].state.string_num, resolved[idx].state.fret)
            for idx in indices
            if resolved[idx].state.fret > 0
            and resolved[idx].state.finger is not Finger.OPEN
        ]
        if len(fretted) < 2:
            continue

        barre_indices, barre_fret = _find_partial_barre(fretted)
        if barre_indices is None or barre_fret is None:
            continue

        # Assign INDEX + hp=barre_fret to all barre notes.
        barre_set = set(barre_indices)
        for note_idx in barre_indices:
            r = resolved[note_idx]
            resolved[note_idx] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=r.state.fret,
                    finger=Finger.INDEX,
                    hand_position=barre_fret,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
                planted_fingers=r.planted_fingers,
            )

        # Assign remaining fretted notes using natural offsets at hp=barre_fret.
        remaining = sorted(
            [(idx, resolved[idx].state.fret, resolved[idx].state.string_num)
             for idx in indices
             if idx not in barre_set
             and resolved[idx].state.fret > 0
             and resolved[idx].state.finger is not Finger.OPEN],
            key=lambda t: (t[1], t[2]),
        )
        available = [Finger.MIDDLE, Finger.RING, Finger.PINKY]
        for ri, fret, _ in remaining:
            offset = fret - barre_fret
            chosen: Finger | None = None
            # Prefer natural offset → finger; fallback to next available higher rank.
            for off in range(max(1, offset), 4):
                fng = _FRETTED_FINGERS[off]
                if fng in available:
                    chosen = fng
                    available.remove(fng)
                    break
            if chosen is None:
                # Fallback: lower rank (stretch backward) — rare.
                # Clamp the start at 3 (last valid _FRETTED_FINGERS index) for
                # the case where the note sits more than 4 frets above the barre.
                for off in range(min(max(0, offset) - 1, 3), 0, -1):
                    fng = _FRETTED_FINGERS[off]
                    if fng in available:
                        chosen = fng
                        available.remove(fng)
                        break
            if chosen is None:
                continue  # nothing feasible; leave as-is

            r = resolved[ri]
            resolved[ri] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=fret,
                    finger=chosen,
                    hand_position=barre_fret,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
                planted_fingers=r.planted_fingers,
            )

    return resolved


# ---------------------------------------------------------------------------
# Unified hand-position per chord
#
# Each fretting finger has its own "natural" hp (= fret − finger_offset).  The
# state generator uses that formula so a single FingeringState carries one
# hp.  When 4 fingers press one chord the 4 hps diverge (eg {5,6,7} for BB
# King's Bm).  But the wrist is physically at ONE place.  This resolver
# snaps every note of a chord to the same hp (the lowest fret of the chord).
# ---------------------------------------------------------------------------


def resolve_chord_unified_hand_position(
    results: list[FingeringResult],
) -> list[FingeringResult]:
    """Snap all fretted notes in each chord to a single hand_position.

    The unified hp is the MINIMUM hand_position across all fretted notes in
    the chord, which equals the fret where the index finger would sit.

    Using min(hand_position) instead of min(fret) is correct because
    hand_position = fret − finger_offset, so each note already encodes where
    the wrist must be.  For a chord where MIDDLE is on the lowest fret
    (e.g. fret 2, natural hp=1), min(fret)=2 would be wrong (forces the
    palm one position too far toward the body); min(hand_position)=1 is right.

    This is a data-integrity fix only — the `finger` field of each note
    is left untouched; only `hand_position` is updated.
    """
    onset_groups: dict[float, list[int]] = defaultdict(list)
    for idx, r in enumerate(results):
        onset_groups[round(r.note_event.onset, 6)].append(idx)

    resolved = list(results)
    for indices in onset_groups.values():
        if len(indices) < 2:
            continue
        fretted = [
            idx for idx in indices
            if resolved[idx].state.fret > 0
            and resolved[idx].state.finger is not Finger.OPEN
        ]
        if len(fretted) < 2:
            continue
        # When INDEX is present its fret IS the hand_position (offset=0).
        # Otherwise anchor at the lowest natural hp so every finger sits as
        # close to its natural offset as possible.
        index_in_chord = [idx for idx in fretted if resolved[idx].state.finger is Finger.INDEX]
        if index_in_chord:
            new_hp = resolved[index_in_chord[0]].state.fret
        else:
            new_hp = min(resolved[idx].state.hand_position for idx in fretted)
        for idx in fretted:
            r = resolved[idx]
            if r.state.hand_position == new_hp:
                continue
            resolved[idx] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=r.state.fret,
                    finger=r.state.finger,
                    hand_position=new_hp,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
                planted_fingers=r.planted_fingers,
            )
    return resolved


# ---------------------------------------------------------------------------
# Arpeggio chord fingering stabilisation
#
# Stairway-to-Heaven-style arpeggios repeat the same (string, fret) positions
# within a short window (2–4 beats per chord).  Viterbi optimises each note
# independently and therefore assigns INDEX to the cheapest note, which drifts
# the hand position back and forth instead of holding the chord shape.
#
# This resolver detects "arpeggio windows" (groups of consecutive notes whose
# collective (string, fret) positions span ≤ 4 frets) and re-fingerises every
# note in the window using the natural chord shape, anchored to the lowest
# hand_position in the window.
#
# Rule: within an arpeggio window the hand DOES NOT MOVE — all notes share the
# same hand_position and use the finger consistent with that position.
# ---------------------------------------------------------------------------

_ARPEGGIO_WINDOW_BEATS: float = 4.0   # max onset span for one arpeggio chord
_ARPEGGIO_MAX_SPAN: int = 4           # max fret distance (standard reach)
_ARPEGGIO_MIN_NOTES: int = 3          # minimum notes to trigger stabilisation


def resolve_arpeggio_chord_fingering(
    results: list[FingeringResult],
    window_beats: float = _ARPEGGIO_WINDOW_BEATS,
    max_span: int = _ARPEGGIO_MAX_SPAN,
    min_notes: int = _ARPEGGIO_MIN_NOTES,
) -> list[FingeringResult]:
    """Stabilise hand position across arpeggio patterns.

    Groups consecutive non-open notes into windows where all fretted positions
    fit within ``max_span`` frets.  Within each window every note is
    re-fingerised to a single hand_position (the minimum natural hp of the
    window) and the appropriate finger derived from its fret offset.

    This prevents the hand from oscillating by ±1–2 frets across an arpeggio
    that a guitarist would play entirely from one chord shape.

    Notes with open strings, muted notes, or bends/slides that span across the
    window boundary are left untouched.

    Args:
        results: FingeringResult list sorted by onset.
        window_beats: Maximum beat span for a single arpeggio window.
        max_span: Maximum fret range (fretted notes only) to qualify.
        min_notes: Minimum number of fretted notes required.

    Returns:
        New list with stabilised arpeggio hand positions.
    """
    if not results:
        return results

    resolved = list(results)
    n = len(resolved)
    i = 0

    while i < n:
        r0 = resolved[i]
        # Skip open strings, muted notes, slides/bends (technique-sensitive).
        if (
            r0.state.fret == 0
            or r0.state.finger is Finger.OPEN
            or r0.note_event.muted
            or r0.note_event.slide_type is not None
            or r0.note_event.bend_value
        ):
            i += 1
            continue

        onset0 = r0.note_event.onset
        # Collect the window: all consecutive fretted notes within window_beats
        # whose frets stay within max_span of the first note.
        window_indices: list[int] = [i]
        min_fret = r0.state.fret
        max_fret = r0.state.fret

        j = i + 1
        while j < n:
            rj = resolved[j]
            if rj.note_event.onset - onset0 > window_beats:
                break
            if (
                rj.state.fret == 0
                or rj.state.finger is Finger.OPEN
                or rj.note_event.muted
                or rj.note_event.slide_type is not None
                or rj.note_event.bend_value
            ):
                j += 1
                continue
            new_min = min(min_fret, rj.state.fret)
            new_max = max(max_fret, rj.state.fret)
            if new_max - new_min > max_span:
                break
            min_fret = new_min
            max_fret = new_max
            window_indices.append(j)
            j += 1

        if len(window_indices) < min_notes:
            i += 1
            continue

        # Compute target hand_position: minimum natural hp across window.
        target_hp = min(
            resolved[k].state.hand_position for k in window_indices
        )
        if target_hp < 1:
            target_hp = 1

        # Re-fingerise each note: choose the finger whose natural position
        # (target_hp + offset) best matches the note's fret.
        for k in window_indices:
            r = resolved[k]
            fret = r.state.fret
            if fret == 0:
                continue
            offset = fret - target_hp
            # R-W3: fret must be >= hand_position. If fret < target_hp the note
            # sits below the anchor — skip rather than clamp (clamping to offset=0
            # would assign INDEX with hp > fret, violating the floor constraint).
            if offset < 0:
                continue
            offset = min(3, offset)
            new_finger = _FRETTED_FINGERS[offset]
            if new_finger == r.state.finger and r.state.hand_position == target_hp:
                continue  # already correct
            # Validate: only rewrite if the new assignment is not more
            # stretched than the original (avoid making things worse).
            old_stretch = abs((r.state.fret - r.state.hand_position)
                              - _FINGER_OFFSET.get(r.state.finger, 0))
            new_stretch = abs(offset - _FINGER_OFFSET.get(new_finger, 0))
            if new_stretch > old_stretch:
                continue
            resolved[k] = FingeringResult(
                note_id=r.note_id,
                note_event=r.note_event,
                state=FingeringState(
                    string_num=r.state.string_num,
                    fret=fret,
                    finger=new_finger,
                    hand_position=target_hp,
                ),
                cost=r.cost,
                alternatives=r.alternatives,
                planted_fingers=r.planted_fingers,
            )

        i = j if j > i + 1 else i + 1

    return resolved


# ---------------------------------------------------------------------------
# Pinky run correction
#
# Viterbi's shift penalty (position_shift × tempo_factor) can reach 10–13
# for a 3-fret shift at fast tempos, far exceeding the ~0.5 extra cost of
# using pinky over index.  For a run of N consecutive notes at the same
# (string, fret), Viterbi will therefore keep the pinky planted at an
# artificially low hand position rather than shift the wrist to let the
# index play a fret it was designed for.  In practice no guitarist uses
# pinky for ≥3 repeated strikes on the same fret when the hand can move.
#
# This resolver detects such runs and rewrites them to INDEX at hp=fret,
# but only when the current hp is "wasted" — i.e. no OTHER finger uses
# that hp in a surrounding window.  That guard keeps legitimate cases
# (scales, riffs where pinky is just the natural finger for one note
# while ring/middle/index play nearby frets) untouched.
# ---------------------------------------------------------------------------

_PINKY_RUN_MIN: int = 3       # run length that triggers the rewrite
_PINKY_RUN_WINDOW: int = 8    # notes before/after to inspect for shared hp


def resolve_pinky_run_to_index(
    results: list[FingeringResult],
    *,
    min_run: int = _PINKY_RUN_MIN,
    window: int = _PINKY_RUN_WINDOW,
) -> list[FingeringResult]:
    """Rewrite runs of repeated same-fret PINKY notes to INDEX at hp = fret.

    A run is a maximal contiguous sequence of FingeringResult with identical
    ``(string, fret, finger=PINKY, hand_position)``.  The rewrite only fires
    when:

    * The run is at least ``min_run`` notes long.
    * No other note within ``window`` positions uses the same
      ``hand_position`` with a non-PINKY, non-OPEN finger.  (If another
      finger shares the hp, the hp is "justified" and pinky is the correct
      natural choice for its fret.)

    Args:
        results: FingeringResult list, in temporal order (as produced by
            the merged pipeline).
        min_run: Minimum run length for the rewrite (default 3).
        window: Lookaround window (in notes) for the "hp-shared" guard
            (default 8).

    Returns:
        The same list with matching runs rewritten in place.
    """
    n = len(results)
    i = 0
    while i < n:
        r0 = results[i]
        if r0.state.finger is not Finger.PINKY:
            i += 1
            continue
        fret = r0.state.fret
        string = r0.state.string_num
        hp = r0.state.hand_position

        j = i + 1
        while j < n:
            s = results[j].state
            if s.finger is not Finger.PINKY: break
            if s.string_num != string: break
            if s.fret != fret: break
            if s.hand_position != hp: break
            j += 1

        run_len = j - i
        if run_len < min_run:
            i = j
            continue

        # "hp-shared" guard — any non-PINKY, non-OPEN finger uses this hp
        # inside the window?  If so, hp is legitimate — leave the pinky run.
        w_start = max(0, i - window)
        w_end   = min(n, j + window)
        hp_shared = False
        for k in range(w_start, w_end):
            if i <= k < j:
                continue
            s = results[k].state
            if s.hand_position == hp and s.finger not in (Finger.OPEN, Finger.PINKY):
                hp_shared = True
                break

        if not hp_shared:
            # Rewrite each note in the run to INDEX at hp = fret.
            for k in range(i, j):
                old = results[k]
                new_state = FingeringState(
                    string_num=old.state.string_num,
                    fret=fret,
                    finger=Finger.INDEX,
                    hand_position=fret,
                )
                results[k] = FingeringResult(
                    note_id=old.note_id,
                    note_event=old.note_event,
                    state=new_state,
                    cost=old.cost,
                    alternatives=old.alternatives,
                    planted_fingers=old.planted_fingers,
                )
            logger.debug(
                "pinky-run: rewrote %d notes at (s%d, f%d) "
                "from PINKY/hp=%d to INDEX/hp=%d",
                run_len, string, fret, hp, fret,
            )

        i = j

    return results


def resolve_sedentary_fingers(
    results: list[FingeringResult],
    *,
    max_inactive_beats: float = _SEDENTARY_MAX_INACTIVE_BEATS,
    allow_chord_context: bool = False,
) -> list[FingeringResult]:
    """Annotate each FingeringResult with its sedentary (planted) fingers.

    A finger F is planted at note N iff ALL the following hold:

    * **R1 — non-interference.** F's placed (S, R) does not change N's
      sounding pitch: either S ≠ N.string, or (S == N.string and R < N.fret,
      i.e. covered from above).
    * **R2 — reachability.** R lies in ``[max(1, hp − 1), hp + 4]`` where
      ``hp = N.hand_position``.
    * **R3 — utility.**
        - **R3a (always on)**: F is reused at exactly (S, R) within
          ``_SEDENTARY_REUSE_LOOKAHEAD_NOTES`` notes.
        - **R3b (disabled by default)**: F's placement and N share the same
          ``hand_position`` and are within ``_SEDENTARY_CHORD_CONTEXT_BEATS``
          beats.  Helpful for classical-style "plant ahead" technique but
          OVER-triggers in pop/rock where every finger used is usually
          reused; disabled by default, enable via ``allow_chord_context``.

    The resolver mutates ``FingeringResult.planted_fingers`` in place and
    returns the same list.  It never touches ``FingeringState``.

    Args:
        results: FingeringResult list, sorted by onset.
        max_inactive_beats: Maximum time a finger may remain planted
            without reuse before being considered released (default 8).
        allow_chord_context: If True, also enables R3b (classical-style
            placement) in addition to R3a.  Defaults to False.

    Returns:
        The same list, with ``planted_fingers`` populated on every entry.
    """
    # Registry: Finger -> (string, fret, onset_beat, hand_position, note_idx)
    last_pos: dict[Finger, tuple[int, int, float, int, int] | None] = {
        Finger.INDEX: None, Finger.MIDDLE: None, Finger.RING: None, Finger.PINKY: None,
    }

    for i, r in enumerate(results):
        active = r.state.finger
        active_string = r.state.string_num
        active_fret = r.state.fret
        hp = r.state.hand_position
        onset = r.note_event.onset

        # Step 1 — update registry for the active finger BEFORE evaluating.
        # OPEN / muted notes do not place a finger.
        if active not in (Finger.OPEN,) and not r.note_event.muted:
            last_pos[active] = (active_string, active_fret, onset, hp, i)

        # Step 2 — any non-active finger at the same fret must be cleared.
        # Same-string+same-fret is physically impossible (two fingers can't
        # share one point).  Same-fret-different-string is visually indistinct
        # in the hand visualisation and is cleared to avoid showing two markers
        # at the same horizontal position (confusing for the user).
        for f in list(last_pos):
            if f == active:
                continue
            pos = last_pos[f]
            if pos is None:
                continue
            s_prev, f_prev, _, _, _ = pos
            if f_prev == active_fret and active_fret > 0:
                last_pos[f] = None

        # Step 3 — evaluate remaining entries against r for sedentary status.
        planted: dict[str, tuple[int, int]] = {}
        for f in (Finger.INDEX, Finger.MIDDLE, Finger.RING, Finger.PINKY):
            if f == active:
                continue
            pos = last_pos[f]
            if pos is None:
                continue
            s_prev, f_prev, onset_prev, hp_prev, idx_prev = pos

            # R3 timeout — too much elapsed time without any activity.
            if onset - onset_prev > max_inactive_beats:
                last_pos[f] = None
                continue

            # R2 — reachability AND hand stability.  A finger is only
            # considered still planted if the HAND has not shifted since
            # placement.  Even if its fret remains within reach of the new
            # hp, a hand-position change pulls all fingers with it unless
            # the player explicitly uses it as a guide finger (rare).
            if hp_prev != hp:
                last_pos[f] = None
                continue
            if not (max(1, hp - 1) <= f_prev <= hp + 4):
                last_pos[f] = None
                continue

            # R1 — non-interference.
            if s_prev == active_string:
                # Same string: OK only if planted fret is strictly below active
                # (covered from above).  Equal would have been cleared in step 2.
                if f_prev >= active_fret:
                    last_pos[f] = None
                    continue

            # Ordering-with-active sanity check: if active's rank is lower
            # (e.g. INDEX) but planted's fret is below active's, that would
            # force a crossing.  Skip — finger cannot stay planted.
            a_rank = _FINGER_RANK.get(active, -1)
            p_rank = _FINGER_RANK[f]
            if active is not Finger.OPEN and a_rank >= 0:
                if (a_rank < p_rank and f_prev < active_fret) or (
                    a_rank > p_rank and f_prev > active_fret
                ):
                    # Finger rank and fret would cross — planted finger physically
                    # impossible while active is where it is.
                    last_pos[f] = None
                    continue

            # R3 — utility.  R3a (future reuse) is the primary rule; R3b
            # (chord context) is opt-in because it over-triggers in pop/rock.
            useful = _has_future_reuse(results, i, f, (s_prev, f_prev))
            if not useful and allow_chord_context:
                useful = _in_chord_context(onset_prev, hp_prev, r)
            if not useful:
                continue  # keep in registry for possible future use

            planted[f.value] = (s_prev, f_prev)

        r.planted_fingers = planted

    return results


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
    *,
    rule_preferences: RulePreferences | None = None,
    segment_anchor_prev: int | None = None,
    segment_anchor_curr: int | None = None,
) -> float:
    """Aggregate mechanical cost C_méca(s1, s2).

    Combines components:
    1. Position shift (wrist movement, tempo-weighted) — segment-aware when
       both ``segment_anchor_prev`` and ``segment_anchor_curr`` are provided,
       per-state hp delta otherwise (A' tolerance fallback).
    2. Stretch (fret span from hand position).
    3. String change (number of strings crossed).
    4. Finger difficulty (intrinsic per-finger cost).
    5. Same-finger-motion penalty.
    6. Sequential crossing penalty (R-S1).

    Special case — same string and same fret:
    - Same finger: cost 0 (finger already placed, no movement).
    - Different finger: large penalty (redundant swap, physically wasteful).

    Args:
        s1: Previous fingering state.
        s2: Next fingering state.
        note: NoteEvent for s2 (tempo and duration context).
        rule_preferences: Optional rule toggles.
        segment_anchor_prev: Optional anchor of the segment containing s1.
            When both anchors are provided, segment-aware shift cost is used.
        segment_anchor_curr: Optional anchor of the segment containing s2.

    Returns:
        Non-negative mechanical cost.
    """
    prefs = rule_preferences or RulePreferences()

    if s1.string_num == s2.string_num and s1.fret == s2.fret and s1.fret != 0:
        if s1.finger == s2.finger:
            return 0.0  # finger already in place — re-articulate at zero cost
        else:
            # Switching finger on the same fret: wasteful, add stiff penalty
            return cost_finger_difficulty(s2) + 4.0

    if segment_anchor_prev is not None and segment_anchor_curr is not None:
        shift_cost = cost_position_shift_segment_aware(
            s1, s2, note, segment_anchor_prev, segment_anchor_curr,
        )
    else:
        shift_cost = cost_position_shift(s1, s2, note)

    return (
        shift_cost
        + cost_stretch(s1, s2)
        + cost_string_change(s1, s2)
        + cost_finger_difficulty(s2)
        + cost_same_finger_motion(s1, s2, note, rule_preferences=prefs)
        + cost_sequential_crossing(s1, s2)
    )
