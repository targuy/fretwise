"""Lazy optional-dependency loader for the training pipeline.

The heavy ML training dependencies (xgboost, scikit-learn, onnxmltools,
pandas, tqdm) and the scraping dependencies (requests, beautifulsoup4/lxml)
are NOT part of FretWise's core dependencies — they are planned as an
optional pixi feature named ``train``. Every ``fretwise.dataset`` module must
stay importable without them; only *using* a training entry point without the
dependency installed raises a clear :class:`ImportError`.
"""
from __future__ import annotations

import importlib
from typing import Any

_INSTALL_HINT = (
    "is required by the FretWise training pipeline (fretwise.dataset) but is "
    "not installed. Install the optional training dependencies — planned pixi "
    "feature 'train' — e.g.: pip install xgboost scikit-learn onnxmltools "
    "onnx onnxruntime pandas tqdm requests beautifulsoup4 lxml"
)


class MissingDependency:
    """Placeholder module that raises a helpful ImportError on first use."""

    def __init__(self, name: str, error: ImportError) -> None:
        self._name = name
        self._error = error

    def _raise(self) -> Any:
        raise ImportError(f"'{self._name}' {_INSTALL_HINT}") from self._error

    def __getattr__(self, attr: str) -> Any:
        self._raise()

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        self._raise()

    def __bool__(self) -> bool:
        return False

    def __repr__(self) -> str:
        return f"<MissingDependency {self._name!r}>"


def optional_import(name: str) -> Any:
    """Import ``name`` if available, else return a :class:`MissingDependency`."""
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        return MissingDependency(name, exc)


def optional_attr(module_name: str, attr: str) -> Any:
    """``from module_name import attr`` with the same lazy-failure semantics."""
    mod = optional_import(module_name)
    if isinstance(mod, MissingDependency):
        return MissingDependency(f"{module_name}.{attr}", mod._error)
    return getattr(mod, attr)
