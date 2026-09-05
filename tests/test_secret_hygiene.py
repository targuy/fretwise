"""Regression checks preventing credentials from entering tracked examples."""

from __future__ import annotations

import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
_ADMIN_PASSWORD_ASSIGNMENT = re.compile(
    r"^[ \t#]*FRETWISE_ADMIN_PASSWD=(?P<value>\S+)",
    re.MULTILINE,
)
_SAFE_EXAMPLE_VALUES = {
    "<strong-random-password>",
    "change-me",
}


def test_admin_password_examples_are_placeholders() -> None:
    """Documentation and source comments must never contain a real admin password."""
    candidates = [
        _REPO_ROOT / ".env.example",
        *(_REPO_ROOT / "docs").rglob("*.md"),
        *(_REPO_ROOT / "src").rglob("*.py"),
    ]
    violations: list[str] = []

    for path in candidates:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in _ADMIN_PASSWORD_ASSIGNMENT.finditer(text):
            if match.group("value") not in _SAFE_EXAMPLE_VALUES:
                line = text.count("\n", 0, match.start()) + 1
                violations.append(f"{path.relative_to(_REPO_ROOT)}:{line}")

    assert not violations, "Real-looking FRETWISE_ADMIN_PASSWD value found in: " + ", ".join(
        violations
    )
