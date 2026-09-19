"""Integrate quarter-note tempo segments without resetting the score origin."""

from __future__ import annotations

from bisect import bisect_right
from collections.abc import Sequence
from dataclasses import dataclass
from math import isfinite

from fretwise.models import NoteEvent


@dataclass(frozen=True)
class TempoMap:
    """A piecewise-constant beat/BPM map including changes during rests."""

    points: tuple[tuple[float, float], ...]

    def __post_init__(self) -> None:
        if not self.points or self.points[0][0] != 0:
            raise ValueError("Tempo map must begin at beat zero")
        previous = -1.0
        for beat, bpm in self.points:
            if not isfinite(beat) or not isfinite(bpm) or beat <= previous or bpm <= 0:
                raise ValueError("Tempo points must be finite, increasing and positive")
            previous = beat

    @classmethod
    def from_events(cls, events: Sequence[NoteEvent]) -> TempoMap:
        """Prefer source tempo metadata, otherwise derive local note changes."""
        supplied = next((event.tempo_points for event in events if event.tempo_points), ())
        if supplied:
            return cls(supplied)
        ordered = sorted(events, key=lambda event: event.onset)
        points = [(0.0, ordered[0].tempo if ordered else 120.0)]
        for event in ordered:
            if event.tempo != points[-1][1]:
                if event.onset == points[-1][0]:
                    raise ValueError("Conflicting tempos at the same score beat")
                points.append((event.onset, event.tempo))
        return cls(tuple(points))

    def beat_to_seconds(self, beat: float) -> float:
        """Integrate all tempo segments preceding a nonnegative score beat."""
        if not isfinite(beat) or beat < 0:
            raise ValueError("Score beat must be finite and nonnegative")
        seconds = 0.0
        for index, (start, bpm) in enumerate(self.points):
            end = self.points[index + 1][0] if index + 1 < len(self.points) else beat
            if beat <= start:
                break
            seconds += (min(beat, end) - start) * 60.0 / bpm
        return seconds

    def duration_seconds(self, onset: float, duration: float) -> float:
        """Integrate a note crossing any number of tempo boundaries."""
        if not isfinite(duration) or duration < 0:
            raise ValueError("Duration must be finite and nonnegative")
        return self.beat_to_seconds(onset + duration) - self.beat_to_seconds(onset)

    def bpm_at(self, beat: float) -> float:
        """Return the constant tempo at a score position."""
        index = bisect_right([point[0] for point in self.points], beat) - 1
        return self.points[max(index, 0)][1]
