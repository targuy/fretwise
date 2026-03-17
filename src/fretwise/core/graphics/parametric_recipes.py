"""Parametric recipe catalog for deformable notation objects."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class RecipeDefinition:
    """Definition of one parametric draw recipe."""

    recipe_id: str
    required_params: tuple[str, ...]
    optional_params: tuple[str, ...] = ()
    notes: str = ""
    tags: tuple[str, ...] = field(default_factory=tuple)


def default_recipe_catalog() -> dict[str, RecipeDefinition]:
    """Return default recipe definitions used by notation-core."""
    return {
        "tab_lines": RecipeDefinition(
            recipe_id="tab_lines",
            required_params=("x", "y", "width", "count", "spacing"),
            tags=("tab", "grid"),
        ),
        "staff_lines": RecipeDefinition(
            recipe_id="staff_lines",
            required_params=("x", "y", "width", "count", "spacing"),
            tags=("standard", "grid"),
        ),
        "stem_line": RecipeDefinition(
            recipe_id="stem_line",
            required_params=("x", "y0", "y1"),
            optional_params=("width",),
            tags=("rhythm", "standard"),
        ),
        "tie_arc": RecipeDefinition(
            recipe_id="tie_arc",
            required_params=("x0", "y0", "x1", "y1"),
            optional_params=("curvature",),
            tags=("standard", "span"),
        ),
        "slur_arc": RecipeDefinition(
            recipe_id="slur_arc",
            required_params=("x0", "y0", "x1", "y1"),
            optional_params=("curvature",),
            tags=("standard", "span"),
        ),
        "beam_group": RecipeDefinition(
            recipe_id="beam_group",
            required_params=("x0", "x1", "y", "level"),
            optional_params=("thickness",),
            tags=("rhythm", "deformable"),
        ),
        "bend_curve": RecipeDefinition(
            recipe_id="bend_curve",
            required_params=("x0", "y0", "x1", "y1"),
            optional_params=("label",),
            tags=("tab", "technique"),
        ),
        "let_ring_span": RecipeDefinition(
            recipe_id="let_ring_span",
            required_params=("x0", "x1", "y"),
            optional_params=("dash",),
            tags=("tab", "technique", "span"),
        ),
        "palm_mute_span": RecipeDefinition(
            recipe_id="palm_mute_span",
            required_params=("x0", "x1", "y"),
            optional_params=("label", "dash"),
            tags=("tab", "technique", "span"),
        ),
    }
