"""Public, deliberately sanitized errors for rig authoring providers."""

from __future__ import annotations


class RigAIError(Exception):
    """Carry an application error without provider bodies or credentials."""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        """Initialize a safe code, user-facing message and HTTP status."""
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
