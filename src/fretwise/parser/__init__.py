"""Parser package (M1).

Public surface:
    BaseParser        — abstract adapter interface
    GuitarProAdapter  — .gp3/.gp4/.gp5 via PyGuitarPro
    GpifAdapter       — .gp (Guitar Pro 7/8) via native GPIF XML parsing
    get_adapter       — auto-select the right adapter for a file path
    ParseError        — base parse exception
    UnsupportedFormatError — unsupported extension
"""

from pathlib import Path

from fretwise.parser.base import BaseParser, FretwiseError, ParseError, UnsupportedFormatError
from fretwise.parser.gpif_adapter import GpifAdapter
from fretwise.parser.guitarpro_adapter import GuitarProAdapter

_ADAPTERS: list[BaseParser] = [GuitarProAdapter(), GpifAdapter()]


def get_adapter(path: Path) -> BaseParser:
    """Return the appropriate parser adapter for *path*.

    Args:
        path: Path to a score file.

    Returns:
        The first adapter that supports the file's extension.

    Raises:
        UnsupportedFormatError: If no adapter supports the extension.
    """
    for adapter in _ADAPTERS:
        if adapter.supports(path):
            return adapter
    raise UnsupportedFormatError(
        f"No parser adapter found for '{path.suffix}'. "
        "Supported: .gp3, .gp4, .gp5 (GuitarPro), .gp (Guitar Pro 7/8)."
    )


__all__ = [
    "BaseParser",
    "FretwiseError",
    "GpifAdapter",
    "GuitarProAdapter",
    "ParseError",
    "UnsupportedFormatError",
    "get_adapter",
]
