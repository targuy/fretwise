"""State generator module (M2).

For every NoteEvent, computes the complete set of physically valid
FingeringState objects: all (string, fret) positions that produce the
correct pitch, combined with every plausible finger/hand-position assignment.

The output is the raw state space fed into M3 (pattern filtering) and
ultimately into the Viterbi optimizer (M5).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from fretwise.models import Finger, FingeringState, NoteEvent

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Constants
# -------------------------------------------------------------------------

# MIDI note values for open strings in standard EADGBE tuning (index = string - 1).
STANDARD_TUNING: list[int] = [64, 59, 55, 50, 45, 40]

# Maximum fret number supported (standard 22-fret neck).
MAX_FRET: int = 22

# Fingers that can fret a note (open strings handled separately).
_FRETTING_FINGERS: list[Finger] = [
    Finger.INDEX,
    Finger.MIDDLE,
    Finger.RING,
    Finger.PINKY,
]

# Semitone offset of each finger relative to the index finger.
# index=0, middle=1, ring=2, pinky=3.
_FINGER_OFFSET: dict[Finger, int] = {
    Finger.INDEX: 0,
    Finger.MIDDLE: 1,
    Finger.RING: 2,
    Finger.PINKY: 3,
}


@dataclass
class GeneratorConfig:
    """Configuration for the state generator.

    Attributes:
        open_string_pitches: MIDI pitches for open strings 1–6 (index 0 = string 1).
        max_fret: Highest fret considered during state generation.
    """

    open_string_pitches: list[int] = None  # type: ignore[assignment]
    max_fret: int = MAX_FRET

    def __post_init__(self) -> None:
        if self.open_string_pitches is None:
            self.open_string_pitches = list(STANDARD_TUNING)


class StateGenerator:
    """Generate all valid FingeringState objects for a sequence of NoteEvents.

    Design rule: the generator is stateless with respect to musical context.
    It produces the *full* state space; pruning and optimization are
    responsibilities of M3 (Patterns) and M5 (Viterbi) respectively.

    Example:
        >>> gen = StateGenerator()
        >>> states = gen.states_for(NoteEvent(pitch=64, onset=0.0, duration=1.0, tempo=120.0))
        >>> any(s.fret == 0 and s.string_num == 1 for s in states)
        True
    """

    def __init__(self, config: GeneratorConfig | None = None) -> None:
        self._config = config or GeneratorConfig()

    def states_for(self, note: NoteEvent) -> list[FingeringState]:
        """Return all valid FingeringState objects for a single NoteEvent.

        For each string on which the target pitch can be played within
        ``max_fret``, one open-string state (fret 0) or up to four
        fretted states (one per finger) are generated.

        Args:
            note: The note whose pitch we need to cover.

        Returns:
            List of FingeringState.  May be empty for pitches outside
            the instrument's range.
        """
        states: list[FingeringState] = []
        pitches = self._config.open_string_pitches
        max_fret = self._config.max_fret

        for string_idx, open_pitch in enumerate(pitches):
            string_num = string_idx + 1
            fret = note.pitch - open_pitch

            if fret < 0 or fret > max_fret:
                continue

            if fret == 0:
                states.append(
                    FingeringState(
                        string_num=string_num,
                        fret=0,
                        finger=Finger.OPEN,
                        hand_position=1,
                    )
                )
            else:
                # Each of the four fingers can play the fret; the hand position
                # is derived from the finger offset: hand_pos = fret - offset.
                for finger in _FRETTING_FINGERS:
                    hand_position = fret - _FINGER_OFFSET[finger]
                    if hand_position < 1:
                        # Hand would be at or below the nut — physically impossible.
                        continue
                    states.append(
                        FingeringState(
                            string_num=string_num,
                            fret=fret,
                            finger=finger,
                            hand_position=hand_position,
                        )
                    )

        # If the GP file provided authoritative string/fret hints not covered
        # by the tuning-based generation (e.g. alternate tunings like Eb, Drop D),
        # add states for those positions so no playable note is ever dropped.
        if (
            note.string_hint is not None
            and note.fret_hint is not None
            and 1 <= note.string_hint <= len(pitches)
            and 0 <= note.fret_hint <= max_fret
        ):
            sh, fh = note.string_hint, note.fret_hint
            # Check whether this exact position was already generated.
            already_present = any(
                s.string_num == sh and s.fret == fh for s in states
            )
            if not already_present:
                logger.debug(
                    "Hint-based fallback for pitch %d: string=%d fret=%d "
                    "(tuning %s did not produce this position).",
                    note.pitch, sh, fh, pitches,
                )
                if fh == 0:
                    states.append(
                        FingeringState(
                            string_num=sh, fret=0,
                            finger=Finger.OPEN, hand_position=1,
                        )
                    )
                else:
                    for finger in _FRETTING_FINGERS:
                        hand_position = fh - _FINGER_OFFSET[finger]
                        if hand_position >= 1:
                            states.append(
                                FingeringState(
                                    string_num=sh, fret=fh,
                                    finger=finger, hand_position=hand_position,
                                )
                            )

        if not states:
            logger.debug(
                "No valid states for pitch %d (MIDI) with tuning %s, max_fret=%d.",
                note.pitch,
                pitches,
                max_fret,
            )

        return states

    def states_for_sequence(
        self, notes: list[NoteEvent]
    ) -> list[list[FingeringState]]:
        """Return a state list for every note in a sequence.

        Args:
            notes: Ordered list of NoteEvent (as produced by M1).

        Returns:
            Parallel list of FingeringState lists, one per note.
        """
        return [self.states_for(note) for note in notes]
