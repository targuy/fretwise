"""Viterbi optimizer module (M5).

Implements the dynamic programming algorithm that finds the minimum-cost
path through the state graph produced by M2/M3.

ARCHITECTURAL RULE: This module's public interface (ViterbiOptimizer) must
never change.  The cost function is injected, never hardcoded.  All future
improvements to the scoring model (Phase 2–4) must happen in M4, not here.

Complexity: O(N × S²) where N = number of notes and S = states per note.
For a typical song (720 notes, 20 states/note) this is ~260 000 operations,
well within the < 100 ms target.
"""

from __future__ import annotations

import logging
import math
from typing import Protocol

from fretwise.config import config
from fretwise.models import FingeringResult, FingeringState, NoteEvent

logger = logging.getLogger(__name__)

# Number of top alternative states retained per note in each FingeringResult.
# Sourced from fretwise.config -> defaults.yaml: ``optimizer.max_alternatives``.
_MAX_ALTERNATIVES: int = config().optimizer.max_alternatives


class CostFunctionProtocol(Protocol):
    """Structural type for cost functions injected into ViterbiOptimizer.

    Any object with these two methods satisfies the contract. The ``index``
    parameter on ``transition_cost`` is optional (defaults to None) so
    implementations that don't need positional context stay compatible.
    Segment-aware implementations (B integration) use ``index`` to consult
    a per-note-index anchor lookup populated by the pipeline.
    """

    def transition_cost(
        self,
        s1: FingeringState,
        s2: FingeringState,
        note: NoteEvent,
        index: int | None = None,
    ) -> float:
        """Cost of transitioning from s1 to s2 when playing note.

        Args:
            s1: Source state.
            s2: Target state.
            note: NoteEvent for s2 (current step).
            index: Index of the current step in the sequence (0-based).
                Always non-None when passed by ``ViterbiOptimizer.solve``;
                callers passing None opt out of positional context.
        """
        ...

    def emission_cost(self, state: FingeringState) -> float:
        """Initial cost for the first note in a sequence."""
        ...


class ViterbiOptimizer:
    """Minimum-cost path finder over the fingering state graph.

    The optimizer is deliberately cost-function-agnostic.  It only assumes
    that lower cost = more desirable, and that costs are non-negative.

    Args:
        cost_fn: A CostFunctionProtocol implementation (typically
            ``fretwise.scoring.CostFunction``).

    Example:
        >>> from fretwise.scoring import CostFunction
        >>> optimizer = ViterbiOptimizer(CostFunction())
        >>> results = optimizer.solve(notes, state_lists)
    """

    def __init__(self, cost_fn: CostFunctionProtocol) -> None:
        self._cost_fn = cost_fn

    def solve(
        self,
        notes: list[NoteEvent],
        state_lists: list[list[FingeringState]],
    ) -> list[FingeringResult]:
        """Find the minimum-cost fingering sequence via the Viterbi algorithm.

        Args:
            notes: Ordered list of NoteEvent (N notes).
            state_lists: Parallel list of candidate FingeringState lists,
                one list per note.  Lists must be non-empty.

        Returns:
            List of FingeringResult of length N, one per note, containing the
            optimal state, its cost, and the top alternative states.

        Raises:
            ValueError: If ``notes`` and ``state_lists`` have different lengths,
                or if any state list is empty.
        """
        if len(notes) != len(state_lists):
            raise ValueError(
                f"notes ({len(notes)}) and state_lists ({len(state_lists)}) "
                "must have the same length."
            )
        if not notes:
            return []

        # Validate no empty state lists.
        for i, states in enumerate(state_lists):
            if not states:
                raise ValueError(f"state_lists[{i}] is empty (no valid states for note).")

        n = len(notes)

        # viterbi[i][j] = minimum cumulative cost to reach state j at step i.
        # backtrack[i][j] = index of the predecessor state at step i-1.
        viterbi: list[list[float]] = [[] for _ in range(n)]
        backtrack: list[list[int]] = [[] for _ in range(n)]

        # --- Initialisation (first note) ---
        first_states = state_lists[0]
        viterbi[0] = [self._cost_fn.emission_cost(s) for s in first_states]
        backtrack[0] = [-1] * len(first_states)

        # --- Recursion ---
        for i in range(1, n):
            prev_states = state_lists[i - 1]
            curr_states = state_lists[i]
            note = notes[i]

            viterbi[i] = [math.inf] * len(curr_states)
            backtrack[i] = [-1] * len(curr_states)

            for j, s2 in enumerate(curr_states):
                for k, s1 in enumerate(prev_states):
                    cost = viterbi[i - 1][k] + self._cost_fn.transition_cost(
                        s1, s2, note, index=i,
                    )
                    if cost < viterbi[i][j]:
                        viterbi[i][j] = cost
                        backtrack[i][j] = k

        # --- Backtracking ---
        best_path_indices: list[int] = [0] * n
        last = viterbi[n - 1]
        best_path_indices[n - 1] = int(min(range(len(last)), key=lambda j: last[j]))

        for i in range(n - 2, -1, -1):
            best_path_indices[i] = backtrack[i + 1][best_path_indices[i + 1]]

        # --- Build results ---
        results: list[FingeringResult] = []
        for i, (note, state_idx) in enumerate(zip(notes, best_path_indices)):
            chosen = state_lists[i][state_idx]
            chosen_cost = viterbi[i][state_idx]

            # Collect alternatives (all states except chosen, sorted by cost).
            alternatives = sorted(
                [
                    (state_lists[i][j], viterbi[i][j])
                    for j in range(len(state_lists[i]))
                    if j != state_idx
                ],
                key=lambda t: t[1],
            )

            results.append(
                FingeringResult(
                    note_id=i,
                    note_event=note,
                    state=chosen,
                    cost=chosen_cost,
                    alternatives=alternatives[:_MAX_ALTERNATIVES],  # top N alternatives
                )
            )

        logger.debug(
            "Viterbi solved %d notes; total cost = %.2f",
            n,
            viterbi[n - 1][best_path_indices[n - 1]],
        )
        return results
