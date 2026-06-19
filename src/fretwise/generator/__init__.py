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

from fretwise.config import config
from fretwise.models import Finger, FingeringState, NoteEvent

logger = logging.getLogger(__name__)

# -------------------------------------------------------------------------
# Constants (sourced from fretwise.config -> defaults.yaml: ``generator``)
# -------------------------------------------------------------------------

_GENERATOR_CONFIG = config().generator

# MIDI note values for open strings in standard EADGBE tuning (index = string - 1).
STANDARD_TUNING: list[int] = list(_GENERATOR_CONFIG.standard_tuning)

# Maximum fret number supported (standard 22-fret neck).
MAX_FRET: int = _GENERATOR_CONFIG.max_fret

# Highest hand position tracked for open-string states.
_MAX_OPEN_HAND_POSITION: int = _GENERATOR_CONFIG.max_open_hand_position

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
        max_open_hand_position: Highest hand position tracked for open-string states.
    """

    open_string_pitches: list[int] = None  # type: ignore[assignment]
    max_fret: int = MAX_FRET
    max_open_hand_position: int = _MAX_OPEN_HAND_POSITION

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

        When the source file (GP) provides authoritative string/fret hints,
        only states for that exact position are generated — the Viterbi then
        optimises the finger assignment only, not the string/fret placement.
        This guarantees chord voicings match the source tab and prevents the
        optimizer from creating unplayable chords with gaps between strings.

        When no hints are available (e.g. MIDI, MusicXML without tab data),
        all physically valid (string, fret) positions are enumerated.

        Args:
            note: The note whose pitch we need to cover.

        Returns:
            List of FingeringState.  May be empty for pitches outside
            the instrument's range.
        """
        pitches = self._config.open_string_pitches
        max_fret = self._config.max_fret

        # --- Hint-constrained mode (GP source tab) ---------------------------
        # When both string and fret are known from the source, generate states
        # for that single position only.  The hint overrides free exploration.
        if (
            note.string_hint is not None
            and note.fret_hint is not None
            and 1 <= note.string_hint <= len(pitches)
            and 0 <= note.fret_hint <= max_fret
        ):
            return self._states_for_position(note.string_hint, note.fret_hint)

        # --- Free-exploration mode (no source tab data) ----------------------
        states: list[FingeringState] = []

        for string_idx, open_pitch in enumerate(pitches):
            string_num = string_idx + 1
            fret = note.pitch - open_pitch

            if fret < 0 or fret > max_fret:
                continue

            states.extend(self._states_for_position(string_num, fret))

        if not states:
            logger.debug(
                "No valid states for pitch %d (MIDI) with tuning %s, max_fret=%d.",
                note.pitch,
                pitches,
                max_fret,
            )

        return states

    def _states_for_position(self, string_num: int, fret: int) -> list[FingeringState]:
        """Return FingeringStates for a fixed (string, fret) position.

        Generates OPEN states for fret 0 across a bounded hand-position range
        (to preserve continuity through open notes), or one state per finger
        for fretted positions (hand_position derives from finger offset).
        """
        if fret == 0:
            max_open_hp = max(1, min(self._config.max_open_hand_position, self._config.max_fret))
            return [
                FingeringState(
                    string_num=string_num,
                    fret=0,
                    finger=Finger.OPEN,
                    hand_position=hp,
                )
                for hp in range(1, max_open_hp + 1)
            ]

        states: list[FingeringState] = []
        for finger in _FRETTING_FINGERS:
            hand_position = fret - _FINGER_OFFSET[finger]
            if hand_position < 1:
                continue
            states.append(
                FingeringState(
                    string_num=string_num,
                    fret=fret,
                    finger=finger,
                    hand_position=hand_position,
                )
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
