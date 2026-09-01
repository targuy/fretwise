"""Atomically switch FretWise runtime to its UGREEN HTTPS endpoint."""

from __future__ import annotations

import os
from pathlib import Path


def _update(path: Path, updates: dict[str, str], mode: int) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    seen: set[str] = set()
    output: list[str] = []
    for line in lines:
        key = line.split("=", 1)[0] if "=" in line else ""
        if key in updates:
            output.append(f"{key}={updates[key]}")
            seen.add(key)
        else:
            output.append(line)
    output.extend(f"{key}={value}" for key, value in updates.items() if key not in seen)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text("\n".join(output) + "\n", encoding="utf-8")
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def main() -> None:
    """Apply HTTPS base URL, Host allowlist and loopback-only backend binding."""
    shared = Path("/volume2/docker/fretwise/shared")
    _update(
        shared / "fretwise.env",
        {
            "FRETWISE_BASE_URL": "https://fretwise.mblanche.direct.ug.link",
            "FRETWISE_ALLOWED_HOSTS": (
                "fretwise.mblanche.direct.ug.link,mblanche,mblanche.familleguitard.fr,"
                "192.168.1.50,localhost,127.0.0.1"
            ),
        },
        0o600,
    )
    _update(
        shared / "compose.env",
        {"FRETWISE_BIND_ADDRESS": "127.0.0.1"},
        0o640,
    )


if __name__ == "__main__":
    main()
