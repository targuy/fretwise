"""Centralized configuration loader for FretWise.

This leaf module loads the packaged ``defaults.yaml`` once (cached) and exposes
the project's tunable constants through two equivalent access styles:

* **Dotted attribute access** via :func:`config`::

      from fretwise.config import config

      config().scoring.weights.performance      # -> [1.0, 0.5, 2.0, 0.0]
      config().generator.max_fret               # -> 22
      config().export.musicxml.written_octave_shift  # -> 12

* **Plain mapping access** via :func:`get_config`::

      from fretwise.config import get_config

      get_config()["scoring"]["weights"]["performance"]
      get_config()["generator"]["max_fret"]

An optional override file may be supplied through the ``FRETWISE_CONFIG``
environment variable; its contents are deep-merged over the packaged defaults
(override scalars and list values win; nested mappings merge recursively).

The module has no dependencies beyond PyYAML and the standard library, and
imports nothing from the rest of :mod:`fretwise`, so it is safe to import from
any domain without risking circular imports.
"""

from __future__ import annotations

import os
from functools import lru_cache
from importlib import resources
from typing import Any

import yaml

__all__ = ["ConfigNode", "config", "get_config", "reload_config"]

_DEFAULTS_RESOURCE = "defaults.yaml"
_OVERRIDE_ENV_VAR = "FRETWISE_CONFIG"


class ConfigNode:
    """Read-only view over a configuration mapping with attribute access.

    Wraps a plain ``dict`` so that nested keys can be reached either as
    attributes (``node.scoring.weights``) or items (``node["scoring"]``).
    Nested mappings are wrapped lazily; lists and scalars are returned as-is.
    """

    __slots__ = ("_data",)

    def __init__(self, data: dict[str, Any]) -> None:
        """Initialize the node.

        Args:
            data: The underlying mapping to expose.
        """
        object.__setattr__(self, "_data", data)

    def __getattr__(self, name: str) -> Any:
        """Return the value for ``name``, wrapping nested mappings.

        Args:
            name: Configuration key to look up.

        Returns:
            A :class:`ConfigNode` for nested mappings, otherwise the raw value.

        Raises:
            AttributeError: If ``name`` is not a known configuration key.
        """
        try:
            value = self._data[name]
        except KeyError as exc:
            raise AttributeError(name) from exc
        return ConfigNode(value) if isinstance(value, dict) else value

    def __getitem__(self, key: str) -> Any:
        """Return the value for ``key``, wrapping nested mappings.

        Args:
            key: Configuration key to look up.

        Returns:
            A :class:`ConfigNode` for nested mappings, otherwise the raw value.
        """
        value = self._data[key]
        return ConfigNode(value) if isinstance(value, dict) else value

    def __contains__(self, key: object) -> bool:
        """Return whether ``key`` is present at this level."""
        return key in self._data

    def get(self, key: str, default: Any = None) -> Any:
        """Return the value for ``key`` or ``default`` if absent.

        Args:
            key: Configuration key to look up.
            default: Value to return when ``key`` is missing.

        Returns:
            A :class:`ConfigNode` for nested mappings, the raw value, or
            ``default``.
        """
        if key not in self._data:
            return default
        value = self._data[key]
        return ConfigNode(value) if isinstance(value, dict) else value

    def to_dict(self) -> dict[str, Any]:
        """Return a shallow copy of the underlying mapping."""
        return dict(self._data)

    def __iter__(self) -> Any:
        """Iterate over the keys at this level."""
        return iter(self._data)

    def __len__(self) -> int:
        """Return the number of keys at this level."""
        return len(self._data)

    def __repr__(self) -> str:
        """Return a debug representation of the node."""
        return f"ConfigNode({self._data!r})"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a copy of ``base``.

    Nested mappings merge key by key; for every other type the override value
    replaces the base value wholesale.

    Args:
        base: The base mapping (typically the packaged defaults).
        override: The mapping whose values take precedence.

    Returns:
        A new merged mapping; neither input is mutated.
    """
    merged = dict(base)
    for key, value in override.items():
        existing = merged.get(key)
        if isinstance(existing, dict) and isinstance(value, dict):
            merged[key] = _deep_merge(existing, value)
        else:
            merged[key] = value
    return merged


def _load_defaults() -> dict[str, Any]:
    """Load and parse the packaged ``defaults.yaml``.

    Returns:
        The parsed defaults as a plain mapping.
    """
    text = resources.files(__package__).joinpath(_DEFAULTS_RESOURCE).read_text(encoding="utf-8")
    data = yaml.safe_load(text)
    if not isinstance(data, dict):
        raise ValueError(f"{_DEFAULTS_RESOURCE} must parse to a mapping, got {type(data).__name__}")
    return data


def _load_override() -> dict[str, Any]:
    """Load the optional override file named by ``FRETWISE_CONFIG``.

    Returns:
        The parsed override mapping, or an empty mapping if the env var is
        unset, points at a missing file, or yields an empty document.
    """
    path = os.environ.get(_OVERRIDE_ENV_VAR)
    if not path:
        return {}
    try:
        with open(path, encoding="utf-8") as handle:
            data = yaml.safe_load(handle)
    except FileNotFoundError:
        return {}
    if data is None:
        return {}
    if not isinstance(data, dict):
        raise ValueError(
            f"{_OVERRIDE_ENV_VAR} file must parse to a mapping, got {type(data).__name__}"
        )
    return data


@lru_cache(maxsize=1)
def get_config() -> dict[str, Any]:
    """Return the merged configuration as a plain mapping (cached).

    Loads the packaged defaults once, deep-merging any override file pointed to
    by the ``FRETWISE_CONFIG`` environment variable over them. The result is
    cached for the life of the process; call :func:`reload_config` to discard
    the cache (e.g. after changing the env var in a test).

    Returns:
        The merged configuration mapping.
    """
    return _deep_merge(_load_defaults(), _load_override())


def config() -> ConfigNode:
    """Return the merged configuration as a dotted-access :class:`ConfigNode`.

    Returns:
        A :class:`ConfigNode` wrapping the result of :func:`get_config`.
    """
    return ConfigNode(get_config())


def reload_config() -> None:
    """Clear the cached configuration so the next access reloads from disk.

    Useful in tests that set or change ``FRETWISE_CONFIG`` at runtime.
    """
    get_config.cache_clear()
