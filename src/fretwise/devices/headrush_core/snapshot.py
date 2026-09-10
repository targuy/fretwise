"""Capture and compare the complete state of the rig currently loaded on a Core.

**Scope, and why it is what it is.** The device only exposes the *loaded* rig:
``/Evil/API/Rigs`` lists identities, but ``Chain`` and ``Patch/<Block>`` reflect
whatever is loaded right now. Reading a different rig therefore requires
``loadRig()`` — a write. So a whole-library backup is impossible on the read-only
path, and this module deliberately captures one rig: the one on screen.

That is still the piece that matters first. Before any write phase mutates a
scratch rig, a snapshot taken here is the thing that lets you put it back.

Backups are built from ``GET /object-properties`` rather than
``Blocks.serializeBlock``: the GET returns every parameter as named fields, so a
snapshot is diffable and reviewable, while ``serializeBlock`` is a POST (a write
by this driver's rules) returning an opaque blob whose round-trip fidelity is
still unproven — see ``docs/headrush_core.md`` §7.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from fretwise.devices.headrush_core.client import ChainSlot, DeviceIdentity, DeviceTransport

#: Schema id of a snapshot document.
SNAPSHOT_SCHEMA_VERSION = "fretwise.device.state.headrush-core.v1"

#: Object holding the rig-level settings (name, tempo, MIDI out, pedal state).
RIG_PATH = "/Evil/Engine/Patch/Rig"

#: Object holding footswitch assignments and the whole scene model.
FOOTSWITCH_PATH = "/Evil/Engine/FootSwitch"

#: Object holding chain topology.
CHAIN_PATH = "/Evil/Engine/Patch/Chain"

#: Properties that describe the device UI rather than rig state.
_UI_KEYS = frozenset({"labels", "order", "disabled"})


@dataclass(frozen=True)
class RigSnapshot:
    """Everything that defines the loaded rig, as read from the device."""

    schema_version: str
    captured_at: str
    identity: DeviceIdentity
    rig_id: str
    rig_name: str
    program_change: int | None
    chain: tuple[ChainSlot, ...]
    #: Block object name -> its parameter values (normalized floats, raw enums).
    blocks: dict[str, dict[str, Any]]
    rig_settings: dict[str, Any]
    footswitch: dict[str, Any]
    cpu_percent: float
    #: Names of chain modules with no matching Patch object, if any.
    unresolved_modules: tuple[str, ...] = field(default=())

    @property
    def occupied_slots(self) -> tuple[ChainSlot, ...]:
        """Return only the slots that actually hold a block."""
        return tuple(slot for slot in self.chain if not slot.is_empty)

    def to_json(self) -> dict[str, Any]:
        """Return the snapshot as a JSON-serializable dict."""
        return {
            "schemaVersion": self.schema_version,
            "capturedAt": self.captured_at,
            "device": {
                "appVersion": self.identity.app_version,
                "deviceName": self.identity.device_name,
                "product": self.identity.product,
            },
            "rig": {
                "id": self.rig_id,
                "name": self.rig_name,
                "programChange": self.program_change,
            },
            "chain": [
                {"slot": s.slot, "moduleType": s.module_type, "module": s.module_name}
                for s in self.chain
            ],
            "blocks": self.blocks,
            "rigSettings": self.rig_settings,
            "footswitch": self.footswitch,
            "cpuPercent": round(self.cpu_percent, 1),
            "unresolvedModules": list(self.unresolved_modules),
        }


@dataclass(frozen=True)
class Change:
    """One differing value between two snapshots."""

    scope: str
    key: str
    before: Any
    after: Any

    def __str__(self) -> str:
        return f"{self.scope}.{self.key}: {self.before!r} -> {self.after!r}"


def _object_name(module_name: str) -> str:
    """Return the Patch object name for a chain module label.

    ``/Evil/Engine/Patch`` replaces spaces with underscores, so ``"BBD Delay"``
    lives at ``/Evil/Engine/Patch/BBD_Delay``. The " 2" twin of a type becomes
    ``BBD_Delay_2`` under the same rule.
    """
    return module_name.replace(" ", "_")


def _clean(properties: dict[str, Any]) -> dict[str, Any]:
    """Drop UI-only keys so a snapshot carries rig state, not screen layout."""
    return {k: v for k, v in sorted(properties.items()) if k not in _UI_KEYS}


def capture_rig(transport: DeviceTransport, *, now: datetime | None = None) -> RigSnapshot:
    """Read the complete state of the rig currently loaded on the device.

    Args:
        transport: Read-only transport.
        now: Capture timestamp; defaults to the current UTC time. Injectable so
            tests produce byte-stable snapshots.

    Returns:
        The assembled :class:`RigSnapshot`.
    """
    stamp = (now or datetime.now(UTC)).isoformat(timespec="seconds")
    gui = transport.properties("/Evil/Gui")
    rig_props = transport.properties("/Evil/API/Rigs")
    blocks_props = transport.properties("/Evil/API/Blocks")
    module_types = [str(m) for m in (blocks_props.get("ModuleTypes") or [])]

    chain_props = transport.properties(CHAIN_PATH)
    chain: list[ChainSlot] = []
    for slot_number in range(1, 15):
        raw = chain_props.get(f"ModuleType{slot_number}", 0)
        type_id = int(raw) if isinstance(raw, int) else 0
        label = module_types[type_id] if 0 <= type_id < len(module_types) else ""
        chain.append(
            ChainSlot(slot=slot_number, module_type=type_id, module_name=label or f"<{type_id}>")
        )

    blocks: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    for slot in chain:
        if slot.is_empty:
            continue
        name = _object_name(slot.module_name)
        if name in blocks:
            continue  # the same object backs both occurrences; read it once
        try:
            values = _clean(transport.properties(f"/Evil/Engine/Patch/{name}"))
        except Exception:  # noqa: BLE001 - an absent object must not lose the backup
            values = {}
        if values:
            blocks[name] = values
        else:
            # An empty read is indistinguishable from a missing object, and both
            # mean the same thing for a backup: this block was NOT captured.
            # Recording it as an empty dict would make the snapshot look complete.
            unresolved.append(slot.module_name)

    raw_pc = rig_props.get("loadedProgMIDICC", -1)
    cpu_raw = transport.properties("/Evil/Engine/CPUMeter").get("CPUTimeSmoothed", 0.0)

    return RigSnapshot(
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        captured_at=stamp,
        identity=DeviceIdentity(
            app_version=str(gui.get("AppVersion", "")),
            device_name=str(gui.get("DeviceName", "")),
            product=str(rig_props.get("product", "")),
        ),
        rig_id=str(rig_props.get("loadedID", "")),
        rig_name=str(rig_props.get("loadedName", "")),
        program_change=int(raw_pc) if isinstance(raw_pc, int) and raw_pc >= 0 else None,
        chain=tuple(chain),
        blocks=blocks,
        rig_settings=_clean(transport.properties(RIG_PATH)),
        footswitch=_clean(transport.properties(FOOTSWITCH_PATH)),
        cpu_percent=min(100.0, max(0.0, float(cpu_raw) * 200.0)),
        unresolved_modules=tuple(unresolved),
    )


def diff_snapshots(before: RigSnapshot, after: RigSnapshot) -> list[Change]:
    """Return every value that differs between two snapshots.

    This is the verification primitive a later write phase needs: push, re-read,
    and assert the diff is exactly what was intended. Volatile readings (CPU load,
    capture time) are excluded — they change on their own.

    Args:
        before: Reference snapshot.
        after: Snapshot to compare against it.

    Returns:
        Changes ordered by scope then key.
    """
    changes: list[Change] = []

    if before.rig_id != after.rig_id:
        changes.append(Change("rig", "id", before.rig_id, after.rig_id))
    if before.rig_name != after.rig_name:
        changes.append(Change("rig", "name", before.rig_name, after.rig_name))
    if before.program_change != after.program_change:
        changes.append(
            Change("rig", "programChange", before.program_change, after.program_change)
        )

    for old_slot, new_slot in zip(before.chain, after.chain):
        if old_slot.module_name != new_slot.module_name:
            changes.append(
                Change("chain", f"slot{old_slot.slot}", old_slot.module_name, new_slot.module_name)
            )

    for scope, old_map, new_map in (
        ("rigSettings", before.rig_settings, after.rig_settings),
        ("footswitch", before.footswitch, after.footswitch),
    ):
        changes.extend(_diff_mapping(scope, old_map, new_map))

    for name in sorted(set(before.blocks) | set(after.blocks)):
        old_block = before.blocks.get(name)
        new_block = after.blocks.get(name)
        if old_block is None:
            changes.append(Change("blocks", name, None, "<added>"))
        elif new_block is None:
            changes.append(Change("blocks", name, "<present>", None))
        else:
            changes.extend(_diff_mapping(f"blocks.{name}", old_block, new_block))

    return changes


def _diff_mapping(scope: str, old: dict[str, Any], new: dict[str, Any]) -> list[Change]:
    """Return the per-key differences between two flat property mappings."""
    changes: list[Change] = []
    for key in sorted(set(old) | set(new)):
        old_value = old.get(key)
        new_value = new.get(key)
        if _differs(old_value, new_value):
            changes.append(Change(scope, key, old_value, new_value))
    return changes


def _differs(old: Any, new: Any) -> bool:
    """Return True when two property values are meaningfully different.

    Floats coming back from the device carry float32 rounding, so an exact
    comparison would report noise on every capture.
    """
    if isinstance(old, float) or isinstance(new, float):
        try:
            return abs(float(old) - float(new)) > 1e-6
        except (TypeError, ValueError):
            return True
    return bool(old != new)


def write_snapshot(snapshot: RigSnapshot, path: Path) -> Path:
    """Write ``snapshot`` as pretty JSON, creating parent directories."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(snapshot.to_json(), indent=1, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    return path


def load_snapshot(path: Path) -> RigSnapshot:
    """Read a snapshot previously written by :func:`write_snapshot`.

    Raises:
        ValueError: The file is not a snapshot of a known schema version.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != SNAPSHOT_SCHEMA_VERSION:
        raise ValueError(
            f"{path} is not a {SNAPSHOT_SCHEMA_VERSION} document "
            f"(found {payload.get('schemaVersion')!r})"
        )
    device = payload.get("device") or {}
    rig = payload.get("rig") or {}
    return RigSnapshot(
        schema_version=str(payload["schemaVersion"]),
        captured_at=str(payload.get("capturedAt", "")),
        identity=DeviceIdentity(
            app_version=str(device.get("appVersion", "")),
            device_name=str(device.get("deviceName", "")),
            product=str(device.get("product", "")),
        ),
        rig_id=str(rig.get("id", "")),
        rig_name=str(rig.get("name", "")),
        program_change=rig.get("programChange"),
        chain=tuple(
            ChainSlot(
                slot=int(entry["slot"]),
                module_type=int(entry["moduleType"]),
                module_name=str(entry["module"]),
            )
            for entry in payload.get("chain", [])
        ),
        blocks=dict(payload.get("blocks") or {}),
        rig_settings=dict(payload.get("rigSettings") or {}),
        footswitch=dict(payload.get("footswitch") or {}),
        cpu_percent=float(payload.get("cpuPercent", 0.0)),
        unresolved_modules=tuple(payload.get("unresolvedModules") or []),
    )


def default_snapshot_path(root: Path, snapshot: RigSnapshot) -> Path:
    """Return a stable on-disk location for one rig's backup.

    Named by rig GUID rather than by rig name: names are editable on the device
    and not unique, GUIDs are the only stable identity a backup can key on.
    """
    return root / "devices" / "headrush-core" / "backups" / f"{snapshot.rig_id or 'unknown'}.json"
