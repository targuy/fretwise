"""Runtime capability profiles for desktop and server deployments."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Literal

RuntimeProfile = Literal["desktop", "server"]
RuntimeCapability = Literal["midi_output"]


@dataclass(frozen=True)
class RuntimeCapabilities:
    """Capabilities enabled for one FretWise runtime profile."""

    profile: RuntimeProfile
    midi_output: bool

    def to_json(self) -> dict[str, object]:
        """Return a JSON-serializable capability document."""
        return {
            "profile": self.profile,
            "midi_output": self.midi_output,
        }


def resolve_runtime_capabilities(profile: str | None = None) -> RuntimeCapabilities:
    """Resolve runtime capabilities from an explicit profile or environment.

    ``desktop`` preserves hardware MIDI behaviour. ``server`` cannot open host
    MIDI outputs. Automated LLM rig generation is a separate offline batch tool,
    never a web runtime capability. Unknown profiles fail closed.
    """
    raw_profile = profile if profile is not None else os.environ.get(
        "FRETWISE_RUNTIME_PROFILE", "desktop"
    )
    normalized = raw_profile.strip().lower()
    if normalized == "desktop":
        return RuntimeCapabilities(profile="desktop", midi_output=True)
    if normalized == "server":
        return RuntimeCapabilities(profile="server", midi_output=False)
    raise ValueError(
        "FRETWISE_RUNTIME_PROFILE must be 'desktop' or 'server', "
        f"got {raw_profile!r}"
    )
