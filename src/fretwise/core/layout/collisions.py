"""Collision and spacing policies for layout event anchors."""

from __future__ import annotations

from fretwise.core.layout.models import CollisionIssue, CollisionSeverity, EventLayout


def enforce_min_event_spacing(
    events: list[EventLayout], *, min_spacing: float
) -> tuple[list[EventLayout], list[CollisionIssue]]:
    """Ensure monotonic x-spacing between consecutive events.

    Returns adjusted events (sorted by onset/event_id) and traceable issues.
    """
    if not events:
        return [], []

    sorted_events = sorted(events, key=lambda event: (event.onset, event.event_id))
    adjusted: list[EventLayout] = []
    issues: list[CollisionIssue] = []
    prev_x: float | None = None

    for event in sorted_events:
        target_x = event.x
        if prev_x is not None and target_x < prev_x + min_spacing:
            new_x = prev_x + min_spacing
            shift = new_x - target_x
            issues.append(
                CollisionIssue(
                    code="LAY-COLL-001",
                    severity=CollisionSeverity.LOW,
                    message="Event x adjusted to satisfy minimum horizontal spacing.",
                    event_ids=(event.event_id,),
                    metadata={"shift": f"{shift:.3f}", "min_spacing": f"{min_spacing:.3f}"},
                )
            )
            target_x = new_x

        adjusted.append(
            EventLayout(
                event_id=event.event_id,
                onset=event.onset,
                duration=event.duration,
                x=target_x,
                y=event.y,
                metadata=dict(event.metadata),
            )
        )
        prev_x = target_x

    return adjusted, issues

