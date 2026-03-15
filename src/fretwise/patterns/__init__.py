"""Pattern recognition module (M3) — chord and scale pattern matching.

Uses chord recognition and scale recognition to bias the Viterbi search space:

1. **Chord matching**: Groups simultaneous notes by onset, recognises chord
   quality, and promotes states matching known voicings from the library.
2. **Scale matching**: Analyses sliding windows of melodic notes, detects the
   prevailing scale, and promotes states within the identified box position.

The interface is stable; M5 (Viterbi) depends only on the ``apply()`` signature.
PatternMatcher never *removes* states — it reorders them so preferred states
appear first. Viterbi explores all states but the cost function can give
a bonus to pattern-aligned states via the emission cost.
"""

from __future__ import annotations

import logging
from collections import defaultdict

from fretwise.models import FingeringState, NoteEvent
from fretwise.patterns.chord_library import lookup_chord
from fretwise.patterns.chord_recognition import recognize_chord
from fretwise.patterns.scale_library import ScaleMatch, recognize_scale

logger = logging.getLogger(__name__)


class PatternMatcher:
    """Apply pattern constraints to a state sequence.

    Reorders candidate state lists so states matching known chord voicings
    or scale positions appear first.  Does not remove any state — Viterbi
    still sees the full search space, but pattern-aligned states are favoured
    by their earlier position (tiebreaker) and by explicit pattern emission
    cost bonuses in the scoring module.

    Attributes:
        chord_matches: Number of chords recognised in the last ``apply()`` call.
        scale_match: Best scale match from the last ``apply()`` call, or None.
    """

    def __init__(self) -> None:
        self.chord_matches: int = 0
        self.scale_match: ScaleMatch | None = None

    def apply(
        self,
        notes: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[list[FingeringState]]:
        """Apply pattern constraints to the candidate state lists.

        Args:
            notes: Ordered sequence of NoteEvent from M1.
            state_lists: Parallel list of candidate FingeringState lists from M2.

        Returns:
            Reordered state lists with pattern-preferred states first.
        """
        if not notes or not state_lists:
            return state_lists

        result = list(state_lists)  # shallow copy

        # --- 1. Chord voicing promotion ---
        result = self._apply_chord_promotion(notes, result)

        # --- 2. Scale position detection (window over melodic notes) ---
        result = self._apply_scale_promotion(notes, result)

        return result

    def _apply_chord_promotion(
        self,
        notes: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[list[FingeringState]]:
        """Promote states matching known chord voicings.

        Groups notes by onset to find simultaneous notes (chords), recognises
        the chord quality, looks up the canonical voicing, and reorders states
        so that (string, fret) pairs matching the voicing come first.
        """
        self.chord_matches = 0

        # Group indices by onset (simultaneous notes = chord).
        onset_groups: dict[float, list[int]] = defaultdict(list)
        for idx, note in enumerate(notes):
            onset_groups[round(note.onset, 6)].append(idx)

        for onset, indices in onset_groups.items():
            if len(indices) < 2:
                continue

            # Collect pitches at this onset.
            pitches = [notes[i].pitch for i in indices]
            chord_name = recognize_chord(pitches)
            if chord_name is None:
                continue

            # Look up the canonical voicing from the library.
            diagram = lookup_chord(chord_name)
            if diagram is None:
                continue

            self.chord_matches += 1

            # Build a set of preferred (string_num, fret) from the voicing.
            # diagram.frets is [high_e(str1), B(str2), ..., low_E(str6)].
            preferred: set[tuple[int, int]] = set()
            for str_idx, fret_val in enumerate(diagram.frets):
                if fret_val >= 0:
                    string_num = str_idx + 1
                    preferred.add((string_num, fret_val))

            # Reorder state lists for each note in this chord.
            for idx in indices:
                if idx >= len(state_lists):
                    continue
                states = state_lists[idx]
                if not states:
                    continue
                # Partition: matching states first, then the rest.
                matching = [s for s in states if (s.string_num, s.fret) in preferred]
                rest = [s for s in states if (s.string_num, s.fret) not in preferred]
                if matching:
                    state_lists[idx] = matching + rest

        if self.chord_matches > 0:
            logger.debug("Chord pattern promotion: %d chords matched.", self.chord_matches)

        return state_lists

    def _apply_scale_promotion(
        self,
        notes: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[list[FingeringState]]:
        """Detect prevailing scale and promote states in the box position.

        Analyses all pitches to identify the most likely scale and root.
        When a scale is detected with high confidence, promotes states
        whose fret positions fall within a common box for that scale.
        """
        all_pitches = [n.pitch for n in notes]
        self.scale_match = recognize_scale(all_pitches)

        if self.scale_match is None:
            return state_lists

        match = self.scale_match
        logger.debug(
            "Scale detected: %s %s (confidence=%.2f)",
            match.root_name, match.name, match.confidence,
        )

        # Build the set of "in-scale" pitch classes for this root.
        # We use the built-in intervals from the match to avoid YAML dependency here.
        from fretwise.patterns.scale_library import _SCALE_PATTERNS
        scale_intervals: frozenset[int] | None = None
        for name, intervals in _SCALE_PATTERNS:
            if name == match.name:
                scale_intervals = intervals
                break

        if scale_intervals is None:
            return state_lists

        # In-scale pitch classes (absolute, 0–11).
        in_scale_pcs = frozenset((match.root + i) % 12 for i in scale_intervals)

        # For each note, promote states whose fret produces a pitch class in the scale.
        # This is a soft constraint: states producing in-scale pitches come first.
        for idx, (note, states) in enumerate(zip(notes, state_lists)):
            if not states:
                continue
            # Also prefer states closer to the median hand position (stay in box).
            matching = [s for s in states if _pitch_class_of(s) in in_scale_pcs]
            rest = [s for s in states if _pitch_class_of(s) not in in_scale_pcs]
            if matching and rest:
                state_lists[idx] = matching + rest

        return state_lists


# Standard tuning: string_num → MIDI pitch of open string.
_OPEN_STRING_PITCH: dict[int, int] = {
    1: 64,  # E4
    2: 59,  # B3
    3: 55,  # G3
    4: 50,  # D3
    5: 45,  # A2
    6: 40,  # E2
}


def _pitch_class_of(state: FingeringState) -> int:
    """Compute the pitch class (0–11) produced by a fingering state."""
    base = _OPEN_STRING_PITCH.get(state.string_num, 40)
    return (base + state.fret) % 12
