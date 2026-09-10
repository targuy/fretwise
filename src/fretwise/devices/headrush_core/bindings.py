"""Which rig on the device belongs to which song.

The device identifies a rig by GUID; FretWise identifies a song by
``artist-slug__title-slug`` (:mod:`fretwise.gears.naming`). This store is the only
place the two meet.

Why a GUID and not the name: rig names are editable on the touchscreen and are not
unique, so a name is a label, not an identity. Why not the Program Change: there
are 128 of them for a library of songs, and the allocation is meant to be
reassigned per set — an identity cannot be revocable.

The store also carries the hash of the binding last written, which is what makes a
re-push a no-op when nothing changed, and — more importantly — what distinguishes
*updating* a song's rig (load its GUID, mutate, ``saveRig``) from *creating* one
(``saveRigAs``, which always mints a new GUID and would otherwise pile up
duplicates on every regeneration).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fretwise.gears.naming import gears_key

#: Schema id of the store document.
BINDINGS_SCHEMA_VERSION = "fretwise.device.bindings.v1"


@dataclass
class RigBinding:
    """One song's rig on one device."""

    key: str
    artist: str
    title: str
    rig_id: str
    rig_name: str
    program_change: int | None = None
    binding_hash: str = ""
    app_version: str = ""
    updated_at: str = ""

    def to_json(self) -> dict[str, Any]:
        """Return the entry as a JSON-serializable dict."""
        return {k: v for k, v in asdict(self).items() if v not in (None, "")}


@dataclass
class BindingStore:
    """The whole song-to-rig table, loaded from and saved to one JSON file."""

    path: Path
    entries: dict[str, RigBinding] = field(default_factory=dict)

    @classmethod
    def load(cls, path: Path) -> BindingStore:
        """Read the store, returning an empty one when the file does not exist yet."""
        store = cls(path=path)
        if not path.exists():
            return store
        payload = json.loads(path.read_text(encoding="utf-8"))
        if payload.get("schemaVersion") != BINDINGS_SCHEMA_VERSION:
            raise ValueError(
                f"{path} is not a {BINDINGS_SCHEMA_VERSION} document "
                f"(found {payload.get('schemaVersion')!r})"
            )
        for raw in payload.get("rigs", []):
            entry = RigBinding(
                key=str(raw["key"]),
                artist=str(raw.get("artist", "")),
                title=str(raw.get("title", "")),
                rig_id=str(raw.get("rigId", "")),
                rig_name=str(raw.get("rigName", "")),
                program_change=raw.get("programChange"),
                binding_hash=str(raw.get("bindingHash", "")),
                app_version=str(raw.get("appVersion", "")),
                updated_at=str(raw.get("updatedAt", "")),
            )
            store.entries[entry.key] = entry
        return store

    def save(self) -> Path:
        """Write the store, sorted by song key so the file diffs cleanly."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "schemaVersion": BINDINGS_SCHEMA_VERSION,
            "rigs": [
                {
                    "key": e.key,
                    "artist": e.artist,
                    "title": e.title,
                    "rigId": e.rig_id,
                    "rigName": e.rig_name,
                    "programChange": e.program_change,
                    "bindingHash": e.binding_hash,
                    "appVersion": e.app_version,
                    "updatedAt": e.updated_at,
                }
                for e in sorted(self.entries.values(), key=lambda x: x.key)
            ],
        }
        self.path.write_text(
            json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        return self.path

    def get(self, artist: str, title: str) -> RigBinding | None:
        """Return the entry for a song, or None when it has no rig yet."""
        return self.entries.get(gears_key(artist, title))

    def record(
        self,
        artist: str,
        title: str,
        *,
        rig_id: str,
        rig_name: str,
        binding_hash: str,
        app_version: str,
        program_change: int | None = None,
        now: datetime | None = None,
    ) -> RigBinding:
        """Insert or update a song's entry.

        Args:
            artist: Song artist.
            title: Song title.
            rig_id: The device GUID this song now maps to.
            rig_name: Name shown on the device screen.
            binding_hash: Digest of the binding written, for no-op detection.
            app_version: Firmware the rig was written on.
            program_change: MIDI Program Change, when one is allocated.
            now: Timestamp; defaults to the current UTC time.

        Returns:
            The stored entry.
        """
        key = gears_key(artist, title)
        existing = self.entries.get(key)
        entry = RigBinding(
            key=key,
            artist=artist,
            title=title,
            rig_id=rig_id,
            rig_name=rig_name,
            program_change=(
                program_change if program_change is not None
                else (existing.program_change if existing else None)
            ),
            binding_hash=binding_hash,
            app_version=app_version,
            updated_at=(now or datetime.now(UTC)).isoformat(timespec="seconds"),
        )
        self.entries[key] = entry
        return entry

    def assigned_program_changes(self) -> set[int]:
        """Return every Program Change this store has handed out."""
        return {e.program_change for e in self.entries.values() if e.program_change is not None}


def binding_hash(document: dict[str, Any]) -> str:
    """Return a digest of a binding document, ignoring key order."""
    payload = json.dumps(document, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode()).hexdigest()


def default_store_path(data_root: Path) -> Path:
    """Return the canonical location of the store."""
    return data_root / "devices" / "headrush-core" / "bindings.json"
