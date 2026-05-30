"""Export fingering results as JSON for the hand-viz browser visualization.

The JSON schema is consumed by ``web/hand_viz.html`` to render the animated
top-down view of the left hand moving on the fretboard, driven by the
results produced by the optimizer (M5) + post-processing resolvers.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fretwise.models import FingeringResult


def export_hand_viz_json(
    results: list[FingeringResult],
    output_path: Path | str,
    *,
    title: str = "",
    artist: str = "",
    track_name: str = "",
    max_seconds: float = 10.0,
    tuning: list[str] | None = None,
    num_frets: int = 15,
    scale_length_mm: float = 648.0,
) -> dict[str, Any]:
    """Export the first ``max_seconds`` of fingerings to a JSON file.

    Args:
        results: FingeringResult list, already optimised and sorted by onset.
        output_path: Path to write the JSON file to.
        title: Song title for the viewer HUD.
        artist: Artist name for the viewer HUD.
        track_name: Track label for the viewer HUD.
        max_seconds: Cut-off duration from the first note onset.
        tuning: 6-string tuning, low-to-high. Defaults to standard EADGBE.
        num_frets: Number of frets to render.
        scale_length_mm: Physical scale length, used for fret geometry.

    Returns:
        The dict that was serialised (handy for tests).
    """
    if tuning is None:
        tuning = ["E2", "A2", "D3", "G3", "B3", "E4"]

    tempo = results[0].note_event.tempo if results else 120.0
    frames: list[dict[str, Any]] = []

    first_onset_beat = results[0].note_event.onset if results else 0.0
    for r in results:
        ne = r.note_event
        local_tempo = ne.tempo or tempo
        # Normalise onset so t=0 corresponds to the first note.
        onset_sec = (ne.onset - first_onset_beat) * 60.0 / local_tempo
        if onset_sec >= max_seconds:
            break
        duration_sec = max(0.08, ne.duration * 60.0 / local_tempo)
        # Serialise planted (sedentary) fingers as a dict {finger: [s, f]}
        # so the browser side can read them as plain JS objects.
        planted = {
            fname: [int(pos[0]), int(pos[1])]
            for fname, pos in r.planted_fingers.items()
        }
        frames.append(
            {
                "note_id": r.note_id,
                "onset_sec": round(onset_sec, 4),
                "duration_sec": round(duration_sec, 4),
                "onset_beat": round(ne.onset - first_onset_beat, 4),
                "duration_beat": round(ne.duration, 4),
                "string": r.state.string_num,
                "fret": r.state.fret,
                "finger": r.state.finger.value,
                "hand_position": r.state.hand_position,
                "pitch": ne.pitch,
                "voice": ne.voice_hint or 0,
                "planted": planted,
            },
        )

    data: dict[str, Any] = {
        "meta": {
            "title": title,
            "artist": artist,
            "track": track_name,
            "tempo": tempo,
            "max_seconds": max_seconds,
        },
        "fretboard": {
            "num_frets": num_frets,
            "scale_length_mm": scale_length_mm,
            "tuning": tuning,
        },
        "frames": frames,
    }

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
