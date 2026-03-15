"""Post-render bounding-box collision checker (RENDER-12).

Provides a lightweight mechanism to record the bounding boxes of rendered
objects and detect overlaps after a measure is drawn.  Intended for debug
and test use — nothing is written to the PDF.

Usage
-----
>>> tracker = CollisionTracker()
>>> tracker.add("oval", onset=1.0, string=1, x=100, y=200, w=10, h=7)
>>> tracker.add("finger", onset=1.0, string=1, x=94, y=193, w=5, h=5)
>>> collisions = tracker.check()
>>> assert len(collisions) == 0
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class BBox:
    """Axis-aligned bounding box for a rendered object."""

    kind: str           # "oval", "finger", "rest", "beam", "stem", "chord_name"
    onset: float        # beat onset the object belongs to (-1 for non-note objects)
    string: int         # string number 1-6 (-1 for non-string objects)
    x0: float           # left edge (pt)
    y0: float           # bottom edge (pt)
    x1: float           # right edge (pt)
    y1: float           # top edge (pt)

    def overlaps(self, other: BBox) -> bool:
        """Return True if this box overlaps *other* (touching edges don't count)."""
        return (
            self.x0 < other.x1
            and self.x1 > other.x0
            and self.y0 < other.y1
            and self.y1 > other.y0
        )


@dataclass(frozen=True)
class Collision:
    """A detected overlap between two rendered objects."""

    a: BBox
    b: BBox

    def __str__(self) -> str:
        return (
            f"COLLISION: {self.a.kind}(onset={self.a.onset:.2f},str={self.a.string}) "
            f"overlaps {self.b.kind}(onset={self.b.onset:.2f},str={self.b.string})"
        )


# Pairs of object kinds that are *allowed* to overlap (e.g. fret oval erases string line).
_ALLOWED_PAIRS: frozenset[frozenset[str]] = frozenset(
    frozenset(p)
    for p in [
        ("oval", "stem"),       # oval drawn over stem base
        ("oval", "string"),     # oval erases string line (intentional)
        ("rest", "string"),     # rest disc erases string line (intentional)
    ]
)


@dataclass
class CollisionTracker:
    """Accumulates bounding boxes and detects overlapping objects."""

    _boxes: list[BBox] = field(default_factory=list)

    def add(
        self,
        kind: str,
        onset: float,
        string: int,
        x: float,
        y: float,
        w: float,
        h: float,
    ) -> None:
        """Register a rendered object by its top-left corner, width and height.

        Args:
            kind: Object type label (e.g. "oval", "finger", "rest").
            onset: Beat onset this object is tied to, or -1.
            string: Guitar string number (1=high e … 6=low E), or -1.
            x: Left edge x position (pt).
            y: Bottom edge y position (pt).
            w: Width (pt).
            h: Height (pt).
        """
        self._boxes.append(BBox(kind, onset, string, x, y, x + w, y + h))

    def add_bbox(self, box: BBox) -> None:
        """Register a pre-built BBox."""
        self._boxes.append(box)

    def check(self) -> list[Collision]:
        """Return all pairwise collisions among registered boxes.

        Pairs in ``_ALLOWED_PAIRS`` are skipped.

        Returns:
            List of Collision objects (empty if no overlaps).
        """
        collisions: list[Collision] = []
        boxes = self._boxes
        for i in range(len(boxes)):
            for j in range(i + 1, len(boxes)):
                a, b = boxes[i], boxes[j]
                pair = frozenset({a.kind, b.kind})
                if pair in _ALLOWED_PAIRS:
                    continue
                if a.overlaps(b):
                    collisions.append(Collision(a, b))
        return collisions

    def clear(self) -> None:
        """Reset all recorded boxes (call between measures)."""
        self._boxes.clear()

    def __len__(self) -> int:
        return len(self._boxes)
