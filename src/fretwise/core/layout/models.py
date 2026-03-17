"""Layout contracts between canonical model and render scene."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class EventLayout:
    """Placed event anchor inside one measure."""

    event_id: str
    onset: float
    duration: float
    x: float
    y: float
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class MeasureLayout:
    """Placed measure region inside a staff."""

    measure_number: int
    x: float
    y: float
    width: float
    height: float
    beats_per_measure: int
    event_layouts: list[EventLayout] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class StaffLayout:
    """Contract for one laid-out staff."""

    staff_id: str
    x: float
    y: float
    width: float
    height: float
    measure_layouts: list[MeasureLayout] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class SystemLayout:
    """Contract for one laid-out system."""

    system_id: str
    x: float
    y: float
    width: float
    height: float
    staves: list[StaffLayout] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)


@dataclass
class PageLayout:
    """Contract for one laid-out page."""

    page_number: int
    width: float
    height: float
    systems: list[SystemLayout] = field(default_factory=list)
    metadata: dict[str, str] = field(default_factory=dict)

