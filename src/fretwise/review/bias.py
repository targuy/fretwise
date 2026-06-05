"""Immediate re-bias of solves from captured feedback.

Two complementary mechanisms, both honouring the M5 contract (the Viterbi
optimizer is never modified — we only inject a constrained state generator and a
biased :class:`fretwise.ml.PlayerCostModel`):

* :class:`ConstrainedStateGenerator` — hard-locks specific notes to a chosen
  fingering (exact reproduction of the user's pick, independent of γ). Also used
  by the measure-alternatives re-solve to freeze the surrounding context.
* :class:`FeedbackBiasedPlayerCost` — softly lowers the cost of user-preferred
  state shapes and raises the cost of rejected ones, so the preference
  generalises to similar passages.
"""

from __future__ import annotations

from collections.abc import Mapping

from fretwise.config import ConfigNode, config
from fretwise.generator import StateGenerator
from fretwise.ml import PlayerContext, PlayerCostModel
from fretwise.models import FingeringState, NoteEvent
from fretwise.review.feedback import SongFeedback

# Lock key: (onset rounded, pitch, voice_hint).
LockKey = tuple[float, int, int | None]


class ConstrainedStateGenerator(StateGenerator):
    """State generator that forces chosen notes to a single locked state.

    Subclasses :class:`fretwise.generator.StateGenerator` so it is accepted
    wherever the pipeline expects a generator. Locked notes yield exactly one
    state; all other notes defer to the wrapped base generator.
    """

    def __init__(
        self,
        base: StateGenerator,
        locked: Mapping[LockKey, FingeringState],
    ) -> None:
        """Initialize the constrained generator.

        Args:
            base: The underlying free state generator.
            locked: Map of ``(onset, pitch, voice_hint)`` → forced state.
        """
        super().__init__()
        self._base = base
        self._locked = dict(locked)

    @staticmethod
    def _key(note: NoteEvent) -> LockKey:
        return (round(note.onset, 6), note.pitch, note.voice_hint)

    def states_for(self, note: NoteEvent) -> list[FingeringState]:
        """Return the locked state for ``note`` or defer to the base generator."""
        locked = self._locked.get(self._key(note))
        if locked is not None:
            return [locked]
        return self._base.states_for(note)

    def states_for_sequence(
        self, notes: list[NoteEvent]
    ) -> list[list[FingeringState]]:
        """Return a state list per note (locked where applicable)."""
        return [self.states_for(n) for n in notes]


class FeedbackBiasedPlayerCost(PlayerCostModel):
    """Player cost that nudges toward preferred and away from rejected shapes.

    Wraps an inner :class:`fretwise.ml.PlayerCostModel` (the learned ONNX model
    or ``None``) and adjusts its output by a fixed weight whenever the current
    state matches a user-preferred or user-rejected ``(string, fret, finger)``
    signature. Output is clamped to be non-negative, as required by the contract.
    """

    def __init__(
        self,
        inner: PlayerCostModel | None,
        feedback: SongFeedback,
        *,
        cfg: ConfigNode | None = None,
    ) -> None:
        """Initialize the biased cost.

        Args:
            inner: The wrapped player-cost model, or ``None`` for a zero base.
            feedback: Recorded feedback to derive preferences from.
            cfg: ``config().review`` node; loaded from defaults when ``None``.
        """
        review_cfg = cfg if cfg is not None else config().review
        self._inner = inner
        self._prefer = feedback.preferred_signatures()
        self._reject = feedback.rejected_signatures()
        self._prefer_w = float(review_cfg.bias.prefer_weight)
        self._reject_w = float(review_cfg.bias.reject_weight)

    def _delta(self, string: int, fret: int, finger: str) -> float:
        sig = (string, fret, finger)
        delta = 0.0
        if sig in self._prefer:
            delta -= self._prefer_w
        if sig in self._reject:
            delta += self._reject_w
        return delta

    def transition_cost(
        self,
        prev_string: int,
        prev_fret: int,
        prev_finger: str,
        curr_string: int,
        curr_fret: int,
        curr_finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        """Inner transition cost adjusted by the feedback bias (≥ 0)."""
        base = 0.0
        if self._inner is not None:
            base = self._inner.transition_cost(
                prev_string, prev_fret, prev_finger,
                curr_string, curr_fret, curr_finger,
                hand_position, context,
            )
        return max(0.0, base + self._delta(curr_string, curr_fret, curr_finger))

    def emission_cost(
        self,
        string: int,
        fret: int,
        finger: str,
        hand_position: int,
        context: PlayerContext,
    ) -> float:
        """Inner emission cost adjusted by the feedback bias (≥ 0)."""
        base = 0.0
        if self._inner is not None:
            base = self._inner.emission_cost(
                string, fret, finger, hand_position, context,
            )
        return max(0.0, base + self._delta(string, fret, finger))
