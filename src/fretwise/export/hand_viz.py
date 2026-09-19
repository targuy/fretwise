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
from fretwise.performance import TempoMap, build_hand_performance


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
        max_seconds: Cut-off from the score origin, including initial rests.
        tuning: 6-string tuning, low-to-high. Defaults to standard EADGBE.
        num_frets: Number of frets to render.
        scale_length_mm: Physical scale length, used for fret geometry.

    Returns:
        The dict that was serialised (handy for tests).
    """
    if tuning is None:
        tuning = ["E2", "A2", "D3", "G3", "B3", "E4"]

    tempo = results[0].note_event.tempo if results else 120.0
    tempo_map = TempoMap.from_events([result.note_event for result in results])
    frames: list[dict[str, Any]] = []
    included_results: list[FingeringResult] = []

    for r in sorted(results, key=lambda result: result.note_event.onset):
        ne = r.note_event
        onset_sec = tempo_map.beat_to_seconds(ne.onset)
        if onset_sec >= max_seconds:
            break
        duration_sec = tempo_map.duration_seconds(ne.onset, ne.duration)
        included_results.append(r)
        # Serialise planted (sedentary) fingers as a dict {finger: [s, f]}
        # so the browser side can read them as plain JS objects.
        planted = {fname: [int(pos[0]), int(pos[1])] for fname, pos in r.planted_fingers.items()}
        frames.append(
            {
                "note_id": r.note_id,
                "onset_sec": round(onset_sec, 4),
                "duration_sec": duration_sec,
                "onset_beat": ne.onset,
                "duration_beat": round(ne.duration, 4),
                "string": r.state.string_num,
                "fret": r.state.fret,
                "finger": r.state.finger.value,
                "hand_position": r.state.hand_position,
                "pitch": ne.pitch,
                "voice": ne.voice_hint or 0,
                "planted": planted,
                "source_note_id": ne.source_note_id,
                "articulation": ne.articulation.value,
                "bend_points": [list(point) for point in ne.bend_points],
                "is_tie_dest": ne.is_tie_dest,
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
    # Tuning labels are the same scientific-pitch notation accepted elsewhere.
    from music21.pitch import Pitch

    data["handPerformance"] = build_hand_performance(
        [result.note_event for result in included_results],
        included_results,
        instrument={
            "scaleLengthM": scale_length_mm / 1000,
            "fretCount": max(num_frets, max((r.state.fret for r in included_results), default=0)),
            "strings": [
                {"number": i + 1, "openPitchMidi": int(Pitch(label).midi)}
                for i, label in enumerate(reversed(tuning))
            ],
        },
    )

    p = Path(output_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return data
