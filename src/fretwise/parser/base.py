"""Abstract base class for all parser adapters (M1).

Each concrete adapter (GuitarPro, MusicXML, MIDI) implements this interface.
Modules M2–M5 depend only on this contract, never on a specific adapter.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path

from fretwise.models import NoteEvent


class FretwiseError(Exception):
    """Base exception for all FretWise domain errors."""


class ParseError(FretwiseError):
    """Raised when a score file cannot be read or interpreted."""


class UnsupportedFormatError(ParseError):
    """Raised when the file extension is not handled by this adapter."""


class BaseParser(ABC):
    """Abstract interface for score parsers.

    Implementing classes must be stateless: ``parse`` can be called
    multiple times on different files without side effects.
    """

    @abstractmethod
    def parse(self, path: Path) -> list[NoteEvent]:
        """Parse a score file and return an ordered sequence of NoteEvents.

        Args:
            path: Absolute or relative path to the score file.

        Returns:
            List of NoteEvent ordered by onset (ascending).  An empty list
            is returned for scores with no playable notes.

        Raises:
            UnsupportedFormatError: If the file extension is not supported.
            ParseError: If the file cannot be opened or decoded.
        """

    @abstractmethod
    def supports(self, path: Path) -> bool:
        """Return True if this adapter can handle the given file.

        Args:
            path: Path whose suffix is checked against supported extensions.

        Returns:
            True when the suffix matches a supported format.
        """
