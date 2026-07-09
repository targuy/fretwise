"""TransitionPlayerCostV4 feature extractor (FretWise ML Training Spec v2 §5).

Extends transition_cost_v3 with phrase / position context:
  - hand_position, position_anchor
  - tempo and duration in seconds
  - techniques and articulation flags
  - chord membership
  - phrase / window context (recent index-anchor presence)

Internal string convention: 0=high_E, 5=low_E (same as v3 unified).
The spec file exposes this and converts to 1-based at the FretWise boundary.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence

V4_FEATURE_NAMES = [
    # Per-state features (prev)
    "prev_string",
    "prev_fret",
    "prev_finger",
    "prev_hand_position",
    "prev_anchor",
    "prev_midi",
    "prev_string_group",
    "prev_is_open",
    "prev_is_high_fret",
    "prev_finger_is_index",
    "prev_finger_is_pinky",
    "prev_finger_is_open",
    "prev_duration_beats",
    # Per-state features (curr)
    "curr_string",
    "curr_fret",
    "curr_hand_position",
    "curr_anchor",
    "curr_midi",
    "curr_string_group",
    "curr_is_open",
    "curr_is_high_fret",
    "curr_fret_relative_to_anchor",
    "curr_duration_beats",
    # Pair-level features
    "fret_distance",
    "fret_distance_abs",
    "string_distance",
    "string_distance_abs",
    "interval_semitones",
    "interval_abs",
    "interval_direction",
    "same_string",
    "same_fret",
    "same_hand_position",
    "same_anchor",
    "position_shift",
    "measure_delta",
    "voice_same",
    # Tempo / timing
    "tempo_bpm",
    "seconds_to_move",
    # Articulation / technique flags
    "tech_hammer_on",
    "tech_pull_off",
    "tech_slide",
    "tech_bend",
    "tech_vibrato",
    "tech_let_ring",
    "tech_staccato",
    "tech_palm_mute",
    "bend_value",
    "articulation_score",
    # Chord context
    "is_chord_member",
    "chord_size",
    # Anchor-role heuristics (priors the model can override)
    "pinky_is_anchor_plus_3",
    "pinky_without_index_anchor",
    "index_anchor_present_recently",
    "finger_offset_error",
]

FINGER_OFFSET = {1: 0, 2: 1, 3: 2, 4: 3}


def _string_group(string: int) -> int:
    return 0 if string <= 2 else 1


def _has_tech(techniques: Sequence[str], name: str) -> int:
    return int(name in (techniques or []))


def _articulation_score(articulation: str | None) -> float:
    table = {
        None: 0.0,
        "normal": 0.0,
        "staccato": 1.0,
        "tenuto": -0.5,
        "accent": 0.5,
        "fermata": -1.0,
    }
    return table.get(articulation, 0.0)


def _seconds_per_beat(tempo_bpm: float) -> float:
    return 60.0 / max(tempo_bpm, 1.0)


def build_v4_features(
    prev: dict,
    curr: dict,
    *,
    tempo_bpm: float = 120.0,
    history: Sequence[dict] | None = None,
) -> dict[str, float]:
    """Build the 50-feature vector for the transition (prev -> curr).

    `history` is a recent window of prior notes (last ~8). Used to compute the
    `index_anchor_present_recently` prior.
    """
    history = list(history or [])

    prev_string = prev.get("string") or 0
    prev_fret = prev.get("fret") or 0
    prev_finger = prev.get("finger") or 0
    prev_midi = prev.get("midi") or 0
    prev_duration = prev.get("duration", 1.0)
    prev_anchor = prev.get("position_anchor") or prev.get("anchor") or prev_fret
    prev_hand_position = prev.get("hand_position")
    if prev_hand_position is None:
        prev_hand_position = prev_fret - FINGER_OFFSET.get(prev_finger, 0)

    curr_string = curr.get("string") or 0
    curr_fret = curr.get("fret") or 0
    curr_finger = curr.get("finger") or 0
    curr_midi = curr.get("midi") or 0
    curr_duration = curr.get("duration", 1.0)
    curr_anchor = curr.get("position_anchor") or curr.get("anchor") or curr_fret
    curr_hand_position = curr.get("hand_position")
    if curr_hand_position is None:
        curr_hand_position = curr_fret - FINGER_OFFSET.get(curr_finger, 0)

    techs = curr.get("techniques") or []
    bend_value = float(curr.get("bend_value") or 0.0)
    articulation = curr.get("articulation")

    voice_same = int(prev.get("voice", 0) == curr.get("voice", 0))
    measure_delta = int((curr.get("measure") or 0) - (prev.get("measure") or 0))
    same_string = int(prev_string == curr_string)
    same_fret = int(prev_fret == curr_fret)
    same_hand_position = int(prev_hand_position == curr_hand_position)
    same_anchor = int(prev_anchor == curr_anchor)
    fret_distance = curr_fret - prev_fret
    string_distance = curr_string - prev_string
    interval = curr_midi - prev_midi

    # Recent-history prior: did an INDEX note appear in the last few notes?
    recent_window = history[-6:]
    index_recent = int(any((n.get("finger") or 0) == 1 for n in recent_window))

    # Pinky-role priors
    pinky_is_anchor_plus_3 = int(
        curr_finger == 4 and curr_fret == curr_anchor + FINGER_OFFSET[4]
    )
    has_index_recent_or_curr = index_recent or any(
        (n.get("finger") or 0) == 1 for n in [prev, curr]
    )
    pinky_without_index_anchor = int(curr_finger == 4 and not has_index_recent_or_curr)

    # Finger offset error: how far the current finger lands from its natural slot.
    natural_offset = FINGER_OFFSET.get(curr_finger, 0)
    actual_offset = curr_fret - curr_anchor
    finger_offset_error = abs(actual_offset - natural_offset)

    secs_per_beat = _seconds_per_beat(tempo_bpm)

    return {
        "prev_string": float(prev_string),
        "prev_fret": float(prev_fret),
        "prev_finger": float(prev_finger),
        "prev_hand_position": float(prev_hand_position),
        "prev_anchor": float(prev_anchor),
        "prev_midi": float(prev_midi),
        "prev_string_group": float(_string_group(prev_string)),
        "prev_is_open": float(prev_fret == 0),
        "prev_is_high_fret": float(prev_fret >= 7),
        "prev_finger_is_index": float(prev_finger == 1),
        "prev_finger_is_pinky": float(prev_finger == 4),
        "prev_finger_is_open": float(prev_finger == 0),
        "prev_duration_beats": float(prev_duration),
        "curr_string": float(curr_string),
        "curr_fret": float(curr_fret),
        "curr_hand_position": float(curr_hand_position),
        "curr_anchor": float(curr_anchor),
        "curr_midi": float(curr_midi),
        "curr_string_group": float(_string_group(curr_string)),
        "curr_is_open": float(curr_fret == 0),
        "curr_is_high_fret": float(curr_fret >= 7),
        "curr_fret_relative_to_anchor": float(curr_fret - curr_anchor),
        "curr_duration_beats": float(curr_duration),
        "fret_distance": float(fret_distance),
        "fret_distance_abs": float(abs(fret_distance)),
        "string_distance": float(string_distance),
        "string_distance_abs": float(abs(string_distance)),
        "interval_semitones": float(interval),
        "interval_abs": float(abs(interval)),
        "interval_direction": float(1 if interval > 0 else (-1 if interval < 0 else 0)),
        "same_string": float(same_string),
        "same_fret": float(same_fret),
        "same_hand_position": float(same_hand_position),
        "same_anchor": float(same_anchor),
        "position_shift": float(abs(fret_distance) > 4),
        "measure_delta": float(measure_delta),
        "voice_same": float(voice_same),
        "tempo_bpm": float(tempo_bpm),
        "seconds_to_move": float(prev_duration * secs_per_beat),
        "tech_hammer_on": float(_has_tech(techs, "hammer_on")),
        "tech_pull_off": float(_has_tech(techs, "pull_off")),
        "tech_slide": float(_has_tech(techs, "slide")),
        "tech_bend": float(_has_tech(techs, "bend")),
        "tech_vibrato": float(_has_tech(techs, "vibrato")),
        "tech_let_ring": float(_has_tech(techs, "let_ring")),
        "tech_staccato": float(_has_tech(techs, "staccato")),
        "tech_palm_mute": float(_has_tech(techs, "palm_mute")),
        "bend_value": bend_value,
        "articulation_score": _articulation_score(articulation),
        "is_chord_member": float(curr.get("is_chord_member", False)),
        "chord_size": float(curr.get("chord_size", 1)),
        "pinky_is_anchor_plus_3": float(pinky_is_anchor_plus_3),
        "pinky_without_index_anchor": float(pinky_without_index_anchor),
        "index_anchor_present_recently": float(index_recent),
        "finger_offset_error": float(finger_offset_error),
    }


class RollingHistory:
    """Maintain a rolling buffer of recent notes for v4 feature extraction."""

    def __init__(self, max_len: int = 8) -> None:
        self._buf: deque[dict] = deque(maxlen=max_len)

    def push(self, note: dict) -> None:
        self._buf.append(note)

    def as_list(self) -> list[dict]:
        return list(self._buf)


__all__ = ["V4_FEATURE_NAMES", "build_v4_features", "RollingHistory"]
