"""Read-only adaptation of persisted fingerings to the versioned hand contract."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue

from fretwise.models import Finger, FingeringResult, FingeringState, NoteEvent
from fretwise.performance.hand_performance import build_hand_performance


class HandPerformanceRequest(BaseModel):
    """References existing score data; never requests an optimization pass."""

    model_config = ConfigDict(extra="forbid", strict=True)
    scoreId: str = Field(min_length=1, max_length=255)
    trackId: str = Field(min_length=1, max_length=32)
    scoreRevision: str = Field(min_length=1)
    fingeringRevision: str = Field(min_length=1)
    range: dict[str, int] | None = None
    handProfileId: str = "adult-reference-left"
    handProfileRevision: str = "1"
    instrumentProfileId: str = "six-string-648"
    instrumentProfileRevision: str = "1"


def source_revision(path: Path) -> str:
    """Hash source contents instead of timestamps or a mutable display name."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def fingering_revision(rows: Sequence[Mapping[str, object]]) -> str:
    """Hash the final serialized decisions, including user changes and holds."""
    return hashlib.sha256(json.dumps(rows, sort_keys=True, ensure_ascii=True,
                                     separators=(",", ":")).encode()).hexdigest()


def build_saved_hand_performance(
    events: Sequence[NoteEvent],
    rows: Sequence[Mapping[str, object]],
    context: Mapping[str, object],
    instrument: Mapping[str, object] | None = None,
) -> dict[str, JsonValue]:
    """Join every saved row to its exact source occurrence, without recomputing."""
    unused = list(rows)
    results: list[FingeringResult] = []
    playback_timing: dict[str, object] = {}
    for index, event in enumerate(events):
        matches = [row for row in unused
                   if row.get("source_note_id") == event.source_note_id
                   and abs(float(cast(float, row.get("onset", -1))) - event.onset) < 1e-7
                   and row.get("pitch") == event.pitch
                   and (row.get("voice_hint") or 0) == (event.voice_hint or 0)]
        if len(matches) != 1:
            raise ValueError("Saved fingering/source occurrence missing or ambiguous")
        row = matches[0]
        unused.remove(row)
        finger = str(row.get("finger", "")).removeprefix("Finger.").lower()
        state = FingeringState(
            string_num=int(cast(int, row["string"])), fret=int(cast(int, row["fret"])),
            finger=Finger(finger), hand_position=int(cast(int, row.get("hand_position", 1))),
        )
        planted = cast(Mapping[str, Sequence[int]], row.get("planted_fingers") or {})
        results.append(FingeringResult(
            note_id=index, note_event=event, state=state, cost=0.0,
            planted_fingers={key: (value[0], value[1]) for key, value in planted.items()},
            let_ring_end=(float(cast(float, row["let_ring_end"]))
                          if row.get("let_ring_end") is not None else None),
        ))
        if isinstance(row.get("perf"), dict):
            playback_timing[str(index)] = row["perf"]
    if unused:
        raise ValueError("Saved fingerings contain unknown source occurrences")
    resolved_context = dict(context)
    resolved_context["performanceByNoteId"] = playback_timing
    return build_hand_performance(events, results, resolved_context, instrument)
