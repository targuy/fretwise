"""Parser package (M1).

Public surface:
    BaseParser        — abstract adapter interface
    GuitarProAdapter  — .gp3/.gp4/.gp5 via PyGuitarPro
    GpifAdapter       — .gp (Guitar Pro 7/8) via native GPIF XML parsing
    MusicXmlAdapter   — .xml/.mxl/.musicxml via music21
    MidiAdapter       — .mid/.midi via pretty_midi
    get_adapter       — auto-select the right adapter for a file path
    ParseError        — base parse exception
    UnsupportedFormatError — unsupported extension
"""

from pathlib import Path

from fretwise.parser.base import BaseParser, FretwiseError, ParseError, UnsupportedFormatError
from fretwise.parser.gpif_adapter import GpifAdapter
from fretwise.parser.guitarpro_adapter import GuitarProAdapter
from fretwise.parser.midi_adapter import MidiAdapter
from fretwise.parser.musicxml_adapter import MusicXmlAdapter

_ADAPTERS: list[BaseParser] = [
    GuitarProAdapter(),
    GpifAdapter(),
    MusicXmlAdapter(),
    MidiAdapter(),
]


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

    supported = ".gp3, .gp4, .gp5 (GuitarPro), .gp (GP7/8), .xml, .mxl, .musicxml (MusicXML), .mid, .midi (MIDI)"
    raise UnsupportedFormatError(
        f"No parser adapter found for '{path.suffix}'. Supported: {supported}."
    )


__all__ = [
    "BaseParser",
    "FretwiseError",
    "GpifAdapter",
    "GuitarProAdapter",
    "MidiAdapter",
    "MusicXmlAdapter",
    "ParseError",
    "UnsupportedFormatError",
    "get_adapter",
]
