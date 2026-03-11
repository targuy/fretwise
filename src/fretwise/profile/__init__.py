"""Player profile module (M6) — Sprint 1 stub.

In Phase 3, this module will:
- Store and load per-player calibration data (morphology, dexterity, history)
- Expose a PlayerProfile object consumed by M4 (Scoring)
- Manage re-calibration sessions and progression tracking

Sprint 1 contract: exposes a fixed "average guitarist" profile so that
M4 can be developed against a stable interface.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class PlayerProfile:
    """Calibration parameters for a single guitarist.

    Phase 1 uses default values representing a generic intermediate player.
    All fields are injectable so M4 never depends on hardcoded constants.

    Attributes:
        max_stretch_semitones: Maximum comfortable fret span between index
            and pinky (default: 4, typical for intermediate players).
        max_shift_per_beat: Maximum position shift (in frets) comfortable
            per beat at any tempo (default: 5).
        finger_cost: Intrinsic cost per finger (index=lowest, pinky=highest).
    """

    max_stretch_semitones: int = 4
    max_shift_per_beat: float = 5.0
    finger_cost: dict[str, float] = field(
        default_factory=lambda: {
            "open": 0.0,
            "index": 1.0,
            "middle": 1.5,
            "ring": 2.0,
            "pinky": 2.5,
        }
    )


def default_profile() -> PlayerProfile:
    """Return the default intermediate-player profile used in Phase 1."""
    return PlayerProfile()
