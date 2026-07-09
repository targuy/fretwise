"""Abstract base class and exceptions for parser adapters."""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class HarvesterError(Exception):
    """Base exception for all harvester errors."""


class ParseError(HarvesterError):
    """Raised when a score file cannot be read or interpreted."""


class UnsupportedFormatError(ParseError):
    """Raised when the file extension is not handled by this adapter."""


class BaseParser(ABC):

    @abstractmethod
    def parse(self, path: Path) -> dict[str, Any]:
        """Parse a score file and return one unified-schema record."""

    @abstractmethod
    def supports(self, path: Path) -> bool:
        """Return True if this adapter can handle the given file."""
