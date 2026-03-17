"""Tests for notation-core extension registries."""

from __future__ import annotations

from pathlib import Path

from fretwise.core.ingest import CompletedScore
from fretwise.core.registries import (
    GlyphRegistry,
    InputFormatRegistry,
    OutputBackendRegistry,
    RecipeRegistry,
    TransformationRegistry,
    ValidatorRegistry,
    build_default_registries,
)
from fretwise.core.scene import DocumentScene, RenderScene
from fretwise.core.validate import ValidationReport


def test_build_default_registries_exposes_expected_keys() -> None:
    registries = build_default_registries()
    assert set(registries.keys()) == {
        "input_formats",
        "output_backends",
        "glyphs",
        "recipes",
        "transformations",
        "validators",
    }
    assert isinstance(registries["input_formats"], InputFormatRegistry)
    assert isinstance(registries["output_backends"], OutputBackendRegistry)
    assert isinstance(registries["glyphs"], GlyphRegistry)
    assert isinstance(registries["recipes"], RecipeRegistry)
    assert isinstance(registries["transformations"], TransformationRegistry)
    assert isinstance(registries["validators"], ValidatorRegistry)


def test_registry_register_get_replace_and_unregister() -> None:
    registry = InputFormatRegistry("input_formats")

    def extractor(_path: Path) -> object:
        return object()

    registry.register("gpif", extractor, metadata={"priority": 10})
    assert registry.has("gpif")
    assert registry.get("gpif") is extractor
    assert len(registry) == 1
    assert registry.keys() == ["gpif"]
    assert registry.get_entry("gpif").metadata["priority"] == 10

    def extractor_v2(_path: Path) -> object:
        return object()

    try:
        registry.register("gpif", extractor_v2)
        assert False, "register should reject duplicate keys by default"
    except KeyError:
        pass

    registry.register("gpif", extractor_v2, replace=True)
    assert registry.get("gpif") is extractor_v2
    registry.unregister("gpif")
    assert len(registry) == 0


def test_registry_rejects_empty_key() -> None:
    registry = GlyphRegistry("glyphs")

    try:
        registry.register("   ", lambda: object())
        assert False, "register should reject empty keys"
    except ValueError:
        pass


def test_registry_preserves_registration_order() -> None:
    registry = RecipeRegistry("recipes")
    registry.register("tab_lines", lambda: {"recipe": "tab_lines"})
    registry.register("bend_curve", lambda: {"recipe": "bend_curve"})
    registry.register("tie_arc", lambda: {"recipe": "tie_arc"})
    assert registry.keys() == ["tab_lines", "bend_curve", "tie_arc"]


def test_output_backend_and_validator_registry_callable_contracts() -> None:
    out_registry = OutputBackendRegistry("output_backends")
    val_registry = ValidatorRegistry("validators")
    tx_registry = TransformationRegistry("transformations")

    out_registry.register("svg", lambda scene: "<svg />")
    val_registry.register(
        "baseline",
        lambda completed: ValidationReport(
            source_path=completed.source_path,
            source_format=completed.source_format,
            checked_notes=len(completed.notes),
        ),
    )
    tx_registry.register("noop", lambda score: score)

    scene = RenderScene(document_scene=DocumentScene(title="song"))
    assert out_registry.get("svg")(scene) == "<svg />"

    completed_score = CompletedScore(
        source_path="song.gp",
        source_format="gpif",
        notes=[],
    )
    report = val_registry.get("baseline")(completed_score)
    assert report.checked_notes == 0
    assert report.source_format == "gpif"

    # Minimal smoke call for transformation registry.
    from fretwise.core.canonical import Score

    score = Score(score_id="s1", title="song")
    assert tx_registry.get("noop")(score) is score


def test_registry_clear_removes_all_entries() -> None:
    registry = InputFormatRegistry("input_formats")
    registry.register("gpif", lambda _path: object())
    registry.register("mid", lambda _path: object())
    assert len(registry) == 2
    registry.clear()
    assert len(registry) == 0
    assert registry.keys() == []
