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

# Classes, not instances: adapters store per-parse results (track_name,
# chord_markers, lyric_markers, key_signature_fifths, …) as mutable instance
# attributes. A module-level singleton instance would be shared across every
# request for the app's lifetime, and /api/solve is a sync route (run in a
# thread pool by FastAPI) — concurrent requests for different tracks/files
# would race on that shared state and corrupt each other's metadata.
# get_adapter() instantiates fresh below so each parse gets its own adapter.
_ADAPTER_CLASSES: list[type[BaseParser]] = [
    GuitarProAdapter,
    GpifAdapter,
    MusicXmlAdapter,
    MidiAdapter,
]


def get_adapter(path: Path) -> BaseParser:
    """Return a fresh parser adapter instance for *path*.

    A new instance is returned on every call — see the note on
    ``_ADAPTER_CLASSES`` for why adapters must never be shared across calls.

    Args:
        path: Path to a score file.

    Returns:
        A new instance of the first adapter class that supports the file's
        extension.

    Raises:
        UnsupportedFormatError: If no adapter supports the extension.
    """
    for adapter_cls in _ADAPTER_CLASSES:
        adapter = adapter_cls()
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
