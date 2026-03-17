"""Backend-independent render scene dataclasses."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class GlyphInstance:
    """Stable (non-deformable) glyph placement."""

    glyph_id: str
    x: float
    y: float
    size: float = 1.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class RecipeInstance:
    """Parametric (deformable) draw recipe placement."""

    recipe_id: str
    params: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextInstance:
    """Text placement in a scene layer."""

    text: str
    x: float
    y: float
    font_family: str = "Helvetica"
    font_size: float = 10.0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LayerGroup:
    """Logical draw layer grouping."""

    layer_id: str
    glyph_instances: list[GlyphInstance] = field(default_factory=list)
    recipe_instances: list[RecipeInstance] = field(default_factory=list)
    text_instances: list[TextInstance] = field(default_factory=list)


@dataclass
class StaffScene:
    """Scene for one staff region."""

    staff_id: str
    x: float
    y: float
    width: float
    height: float
    layer_groups: list[LayerGroup] = field(default_factory=list)


@dataclass
class SystemScene:
    """Scene for one system on a page."""

    system_id: str
    x: float
    y: float
    width: float
    height: float
    staves: list[StaffScene] = field(default_factory=list)


@dataclass
class PageScene:
    """Scene for one page."""

    page_number: int
    width: float
    height: float
    systems: list[SystemScene] = field(default_factory=list)


@dataclass
class DocumentScene:
    """Top-level scene container."""

    title: str
    pages: list[PageScene] = field(default_factory=list)


@dataclass
class RenderScene:
    """Canonical render scene passed to output backends."""

    document_scene: DocumentScene
