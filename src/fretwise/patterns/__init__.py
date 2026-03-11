"""Pattern recognition module (M3) — Sprint 1 stub.

In Phase 2, this module will:
- Load chord/scale patterns from YAML files in patterns/data/
- Match sub-sequences of NoteEvents against known patterns
- Return constrained FingeringState lists that reduce the search space

Sprint 1 contract: returns the input state lists unchanged (zero constraints).
The interface is stable; M5 (Viterbi) depends only on this signature.
"""

from __future__ import annotations

from fretwise.models import FingeringState, NoteEvent


class PatternMatcher:
    """Apply pattern constraints to a state sequence.

    Phase 2 implementation will load YAML pattern databases and narrow
    down the state space for recognized chord/scale segments.
    """

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
            Possibly constrained state lists (stub: returns input unchanged).
        """
        # Stub: no pattern constraints in Phase 1.
        return state_lists
