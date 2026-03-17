"""Extension registries for notation-core components."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Generic, TypeVar

from fretwise.core.canonical import Score
from fretwise.core.ingest import CompletedScore, RawScore
from fretwise.core.scene import RenderScene
from fretwise.core.validate import ValidationReport

T = TypeVar("T")


@dataclass(frozen=True)
class RegistryEntry(Generic[T]):
    """One registered extension component."""

    key: str
    component: T
    metadata: dict[str, Any] = field(default_factory=dict)


class BaseRegistry(Generic[T]):
    """Ordered key-component registry with explicit collision policy."""

    def __init__(self, registry_name: str) -> None:
        self.registry_name = registry_name
        self._entries: dict[str, RegistryEntry[T]] = {}

    def register(
        self,
        key: str,
        component: T,
        *,
        metadata: dict[str, Any] | None = None,
        replace: bool = False,
    ) -> None:
        """Register a component under *key*.

        Args:
            key: Stable registry key.
            component: Registered component implementation.
            metadata: Optional debug/display metadata.
            replace: Allow replacing an existing entry when True.
        """
        if not key.strip():
            raise ValueError("Registry key must be non-empty.")
        if key in self._entries and not replace:
            raise KeyError(
                f"Key '{key}' already exists in registry '{self.registry_name}'."
            )
        self._entries[key] = RegistryEntry(
            key=key,
            component=component,
            metadata=dict(metadata or {}),
        )

    def unregister(self, key: str) -> None:
        """Remove one entry by key."""
        if key not in self._entries:
            raise KeyError(f"Unknown key '{key}' in registry '{self.registry_name}'.")
        del self._entries[key]

    def clear(self) -> None:
        """Remove all entries."""
        self._entries.clear()

    def get(self, key: str) -> T:
        """Return registered component by key."""
        try:
            return self._entries[key].component
        except KeyError as exc:
            raise KeyError(
                f"Unknown key '{key}' in registry '{self.registry_name}'."
            ) from exc

    def get_entry(self, key: str) -> RegistryEntry[T]:
        """Return full registry entry by key."""
        try:
            return self._entries[key]
        except KeyError as exc:
            raise KeyError(
                f"Unknown key '{key}' in registry '{self.registry_name}'."
            ) from exc

    def has(self, key: str) -> bool:
        """Return True when key is present."""
        return key in self._entries

    def keys(self) -> list[str]:
        """Return keys in registration order."""
        return list(self._entries.keys())

    def entries(self) -> list[RegistryEntry[T]]:
        """Return entries in registration order."""
        return list(self._entries.values())

    def __len__(self) -> int:
        return len(self._entries)


InputExtractor = Callable[[Path], RawScore]
OutputBackend = Callable[[RenderScene], str]
GlyphFactory = Callable[..., object]
RecipeFactory = Callable[..., object]
Transformation = Callable[[Score], Score]
Validator = Callable[[CompletedScore], ValidationReport]


class InputFormatRegistry(BaseRegistry[InputExtractor]):
    """Registry of input extractors keyed by source format."""


class OutputBackendRegistry(BaseRegistry[OutputBackend]):
    """Registry of render-scene output backends."""


class GlyphRegistry(BaseRegistry[GlyphFactory]):
    """Registry of stable glyph providers."""


class RecipeRegistry(BaseRegistry[RecipeFactory]):
    """Registry of parametric draw recipes."""


class TransformationRegistry(BaseRegistry[Transformation]):
    """Registry of canonical-score transformations."""


class ValidatorRegistry(BaseRegistry[Validator]):
    """Registry of input validation pipelines."""


def build_default_registries() -> dict[str, BaseRegistry[Any]]:
    """Create the default registry set used by notation-core."""
    return {
        "input_formats": InputFormatRegistry("input_formats"),
        "output_backends": OutputBackendRegistry("output_backends"),
        "glyphs": GlyphRegistry("glyphs"),
        "recipes": RecipeRegistry("recipes"),
        "transformations": TransformationRegistry("transformations"),
        "validators": ValidatorRegistry("validators"),
    }
