"""Read-only transport for the HeadRush Core's local control API.

The Core serves a React app ("Headrush Remote Editor") on ``http://<host>/`` and,
underneath it, an undocumented object-tree RPC API discovered by reading that
app's bundle::

    GET  /api/v1/subtree/<path>            # meta + values for a whole subtree
    GET  /api/v1/object-meta/<path>        # type, minimum, maximum, x-options
    GET  /api/v1/object-properties/<path>  # current values
    PUT  /api/v1/object-properties/<path>  # write            (NOT implemented here)
    POST /api/v1/object-method/<path>/<m>  # call             (allow-listed here)

No authentication is required for reads. See ``docs/headrush_core.md`` for the
full design, the object map, and the open questions.

**This module never writes.** It exposes no PUT, and :meth:`CoreClient.query`
refuses any method outside :data:`PURE_METHODS` — a hard-coded allow-list of
calls that only read device state. Writing to the instrument is a later phase
with its own confirmation gates; keeping the read path incapable of writing is
what makes it safe to run against a live rig library.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from fretwise.parser.base import FretwiseError

#: Default mDNS name of the device. Override with ``FRETWISE_CORE_HOST`` — an IP
#: literal is preferred for anything but casual reads, because ``*.local`` is
#: spoofable on a shared network (docs/headrush_core.md §5.5).
DEFAULT_HOST = "headrushcore.local"

#: Environment variable holding the host (name or IP, optional ``:port``).
HOST_ENV_VAR = "FRETWISE_CORE_HOST"

#: Object-method calls that only read device state. Anything not listed here is
#: refused by :meth:`CoreClient.query`. Kept deliberately short: every addition
#: must be justified as side-effect free.
PURE_METHODS: frozenset[tuple[str, str]] = frozenset(
    {
        ("/Evil/API/Blocks", "categoryBlocks"),
        ("/Evil/API/Blocks", "categoryBlocksFlags"),
        ("/Evil/API/Blocks", "categoryOfBlock"),
        ("/Evil/API/Blocks", "blockPresets"),
        ("/Evil/API/Setlists", "getSetlist"),
        ("/Evil/API/Setlists", "numSetlistsContainingRig"),
        ("/Evil/API/Rigs", "getSortMode"),
        ("/Evil/API/Rigs", "getSortIsAscending"),
        ("/Evil/API/Rigs", "canSaveNewRig"),
    }
)


class DeviceError(FretwiseError):
    """Base class for HeadRush Core transport failures."""


class DeviceUnreachableError(DeviceError):
    """The device did not answer (powered off, off-network, or mDNS failed)."""


class DeviceProtocolError(DeviceError):
    """The device answered, but not with what the API contract promises."""


class DeviceNotFoundError(DeviceProtocolError):
    """The device answered 404: the requested file does not exist on it."""


class UnsafeMethodError(DeviceError):
    """A caller tried to invoke an object-method that is not known to be pure."""


@runtime_checkable
class DeviceTransport(Protocol):
    """Read-only view of a device's object tree.

    Deliberately has no write member: code typed against this Protocol is
    statically incapable of modifying the instrument, so the safety rule is
    enforced by ``mypy --strict`` rather than by discipline.
    """

    def subtree(self, path: str) -> dict[str, Any]:
        """Return ``{objectPath: {"meta": ..., "value": ...}}`` under ``path``."""

    def meta(self, path: str) -> dict[str, Any]:
        """Return the JSON-Schema-ish description of one object's properties."""

    def properties(self, path: str) -> dict[str, Any]:
        """Return one object's current property values."""

    def query(self, path: str, method: str, arguments: list[Any]) -> Any:
        """Call an allow-listed, side-effect-free object method."""


@dataclass(frozen=True)
class DeviceIdentity:
    """The version anchor a write contract would later be pinned against.

    ``app_version`` matters because ``Blocks.ModuleTypes`` is a *positional*
    array: a firmware update that inserts a module shifts every id after it.
    """

    app_version: str
    device_name: str
    product: str

    @property
    def contract_id(self) -> str:
        """Return the identifier used to name catalog artifacts on disk."""
        return f"{self.product}-{self.app_version}"


@dataclass(frozen=True)
class RigSummary:
    """One rig as listed by ``/Evil/API/Rigs``."""

    rig_id: str
    name: str
    colour: int
    #: MIDI Program Change assigned to this rig, or ``None`` when unassigned
    #: (the device stores -1). Only the *loaded* rig exposes this, so it is
    #: ``None`` for every other entry in a listing.
    program_change: int | None = None


@dataclass(frozen=True)
class ChainSlot:
    """One of the 14 positions in a rig's signal chain."""

    slot: int
    module_type: int
    module_name: str

    @property
    def is_empty(self) -> bool:
        """Return True when nothing occupies this slot."""
        return self.module_type == 0


@dataclass(frozen=True)
class DeviceSnapshot:
    """Everything ``device_probe`` reports, captured in one pass."""

    identity: DeviceIdentity
    loaded_rig: RigSummary
    rigs: tuple[RigSummary, ...]
    chain: tuple[ChainSlot, ...]
    cpu_percent: float
    midi_settings: dict[str, Any]
    general_settings: dict[str, Any]
    available_program_changes: tuple[int, ...] = field(default=())

    @property
    def assigned_program_changes(self) -> tuple[int, ...]:
        """Return the Program Change numbers currently taken, low to high.

        ``availableProgMIDICC`` is relative to the loaded rig: the device offers
        a rig its *own* Program Change as still available, so the raw complement
        misses it. Verified on hardware — from ``Accoustique`` the list held 127
        entries with 112 excluded, while from the rig that owns 112 it held all
        128. The loaded rig's own assignment is therefore added back here.
        """
        free = set(self.available_program_changes)
        assigned = {pc for pc in range(128) if pc not in free}
        if self.loaded_rig.program_change is not None:
            assigned.add(self.loaded_rig.program_change)
        return tuple(sorted(assigned))


def resolve_host(host: str | None = None) -> str:
    """Return the device host to talk to.

    Args:
        host: Explicit host (name or ``name:port``). When omitted, falls back to
            ``FRETWISE_CORE_HOST`` and then to :data:`DEFAULT_HOST`.

    Returns:
        The host string, without scheme.
    """
    return host or os.environ.get(HOST_ENV_VAR) or DEFAULT_HOST


class CoreClient:
    """Read-only HTTP client for one HeadRush Core.

    Uses :mod:`urllib` rather than ``httpx`` so the read path stays importable
    in the stdlib-only contexts FretWise cares about, and because the device
    speaks plain unauthenticated HTTP on the LAN.

    Args:
        host: Device host; see :func:`resolve_host`.
        timeout: Per-request timeout in seconds. Subtree dumps of
            ``/Evil/Engine/Patch`` are ~1 MB and want a generous value.
    """

    def __init__(self, host: str | None = None, timeout: float = 20.0) -> None:
        self.host = resolve_host(host)
        self.timeout = timeout
        self.base_url = f"http://{self.host}/api/v1"

    # -- transport ----------------------------------------------------------

    def _get(self, endpoint: str, path: str) -> Any:
        """Issue one GET and decode the JSON body.

        Args:
            endpoint: API endpoint segment, e.g. ``object-properties``.
            path: Device object path, e.g. ``/Evil/API/Rigs``.

        Raises:
            DeviceUnreachableError: The device did not answer.
            DeviceProtocolError: The answer was not decodable JSON.
        """
        url = f"{self.base_url}/{endpoint}{_quote_object_path(path)}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:  # answered, but with an error code
            raise DeviceProtocolError(f"{url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceUnreachableError(
                f"no answer from {self.host} — is the Core powered on and on this network? "
                f"Set {HOST_ENV_VAR} to an IP literal if mDNS is unreliable."
            ) from exc
        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise DeviceProtocolError(f"{url} did not return JSON") from exc

    def subtree(self, path: str) -> dict[str, Any]:
        """Return ``{objectPath: {"meta": ..., "value": ...}}`` under ``path``."""
        result = self._get("subtree", path)
        if not isinstance(result, dict):
            raise DeviceProtocolError(f"subtree{path} did not return an object")
        return result

    def meta(self, path: str) -> dict[str, Any]:
        """Return one object's property schemas."""
        result = self._get("object-meta", path)
        if not isinstance(result, dict):
            raise DeviceProtocolError(f"object-meta{path} did not return an object")
        return result

    def properties(self, path: str) -> dict[str, Any]:
        """Return one object's current property values."""
        result = self._get("object-properties", path)
        if not isinstance(result, dict):
            raise DeviceProtocolError(f"object-properties{path} did not return an object")
        return result

    def query(self, path: str, method: str, arguments: list[Any]) -> Any:
        """Call an allow-listed, side-effect-free object method.

        Args:
            path: Object path owning the method.
            method: Method name; must appear in :data:`PURE_METHODS`.
            arguments: Positional arguments, JSON-encodable.

        Returns:
            The method's return value.

        Raises:
            UnsafeMethodError: ``method`` is not on the pure allow-list.
            DeviceUnreachableError: The device did not answer.
            DeviceProtocolError: The answer did not carry a return value.
        """
        if (path, method) not in PURE_METHODS:
            raise UnsafeMethodError(
                f"{path}/{method} is not on the read-only allow-list. "
                "This client cannot write to the device; use a later-phase writer."
            )
        url = f"{self.base_url}/object-method{_quote_object_path(path)}/{method}"
        body = json.dumps({"arguments": arguments}).encode()
        request = urllib.request.Request(
            url, data=body, headers={"Content-Type": "application/json"}, method="POST"
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise DeviceProtocolError(f"{url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceUnreachableError(f"no answer from {self.host}") from exc
        except json.JSONDecodeError as exc:
            raise DeviceProtocolError(f"{url} did not return JSON") from exc
        if not isinstance(payload, dict) or "methodReturnValue" not in payload:
            raise DeviceProtocolError(f"{url} returned no methodReturnValue")
        return payload["methodReturnValue"]

    def file(self, path: str) -> bytes:
        """GET one static file the device serves under ``/files/`` (block pictures).

        Args:
            path: Absolute URL path, already percent-encoded, e.g.
                ``/files/Evil/Web/Blocks/img/Pressor.webp``.

        Raises:
            ValueError: ``path`` is outside ``/files/``.
            DeviceNotFoundError: The device has no such file.
            DeviceUnreachableError: The device did not answer.
            DeviceProtocolError: The device answered with another error.
        """
        if not path.startswith("/files/") or ".." in path:
            raise ValueError(f"chemin hors de /files/ : {path!r}")
        url = f"http://{self.host}{path}"
        try:
            with urllib.request.urlopen(url, timeout=self.timeout) as response:
                data: bytes = response.read()
                return data
        except urllib.error.HTTPError as exc:
            if exc.code == 404:
                raise DeviceNotFoundError(f"{url} returned HTTP 404") from exc
            raise DeviceProtocolError(f"{url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceUnreachableError(f"no answer from {self.host}") from exc

    # -- derived reads ------------------------------------------------------

    def identity(self) -> DeviceIdentity:
        """Return the firmware/product anchor for this device."""
        gui = self.properties("/Evil/Gui")
        rigs = self.properties("/Evil/API/Rigs")
        return DeviceIdentity(
            app_version=str(gui.get("AppVersion", "")),
            device_name=str(gui.get("DeviceName", "")),
            product=str(rigs.get("product", "")),
        )

    def rigs(self) -> tuple[RigSummary, ...]:
        """Return every rig stored on the device, in the device's own order."""
        props = self.properties("/Evil/API/Rigs")
        ids = props.get("AllRigIds") or []
        names = props.get("AllRigNames") or []
        colours = props.get("AllRigColors") or []
        if not (isinstance(ids, list) and isinstance(names, list)):
            raise DeviceProtocolError("AllRigIds/AllRigNames missing from /Evil/API/Rigs")
        return tuple(
            RigSummary(
                rig_id=str(rig_id),
                name=str(name),
                colour=int(colour) if isinstance(colour, int) else -1,
            )
            for rig_id, name, colour in zip(ids, names, _pad(colours, len(ids)))
        )

    def module_types(self) -> tuple[str, ...]:
        """Return the positional ``ModuleTypes`` table (index = module type id)."""
        blocks = self.properties("/Evil/API/Blocks")
        types = blocks.get("ModuleTypes")
        if not isinstance(types, list):
            raise DeviceProtocolError("ModuleTypes missing from /Evil/API/Blocks")
        return tuple(str(name) for name in types)

    def chain(self, module_types: tuple[str, ...] | None = None) -> tuple[ChainSlot, ...]:
        """Return the 14 slots of the currently loaded rig.

        Args:
            module_types: Pre-fetched ``ModuleTypes`` table, to avoid a second
                round trip when the caller already has it.
        """
        names = module_types if module_types is not None else self.module_types()
        props = self.properties("/Evil/Engine/Patch/Chain")
        slots: list[ChainSlot] = []
        for slot in range(1, 15):
            raw = props.get(f"ModuleType{slot}", 0)
            type_id = int(raw) if isinstance(raw, int) else 0
            label = names[type_id] if 0 <= type_id < len(names) else f"<unknown {type_id}>"
            slots.append(ChainSlot(slot=slot, module_type=type_id, module_name=label))
        return tuple(slots)

    def cpu_percent(self) -> float:
        """Return the CPU load as the device's own screen shows it.

        ``CPUTimeSmoothed`` is normalized 0.0-1.0 and ``object-meta`` declares
        ``maximum: 200`` with a ``"%.0f %%"`` format, so the displayed
        percentage is ``200 x`` the raw value (docs/headrush_core.md §2.3).
        """
        raw = self.properties("/Evil/Engine/CPUMeter").get("CPUTimeSmoothed", 0.0)
        value = float(raw) if isinstance(raw, (int, float)) else 0.0
        return min(100.0, max(0.0, value * 200.0))

    def snapshot(self) -> DeviceSnapshot:
        """Capture identity, rig inventory, loaded chain and settings in one pass."""
        rig_props = self.properties("/Evil/API/Rigs")
        gui = self.properties("/Evil/Gui")
        raw_pc = rig_props.get("loadedProgMIDICC", -1)
        loaded_pc = int(raw_pc) if isinstance(raw_pc, int) and raw_pc >= 0 else None
        available = rig_props.get("availableProgMIDICC") or []
        module_types = self.module_types()
        return DeviceSnapshot(
            identity=DeviceIdentity(
                app_version=str(gui.get("AppVersion", "")),
                device_name=str(gui.get("DeviceName", "")),
                product=str(rig_props.get("product", "")),
            ),
            loaded_rig=RigSummary(
                rig_id=str(rig_props.get("loadedID", "")),
                name=str(rig_props.get("loadedName", "")),
                colour=int(rig_props.get("loadedColor", -1) or -1),
                program_change=loaded_pc,
            ),
            rigs=self.rigs(),
            chain=self.chain(module_types),
            cpu_percent=self.cpu_percent(),
            midi_settings=self.properties("/Evil/Engine/Settings/Midi"),
            general_settings=self.properties("/Evil/Engine/Settings/General"),
            available_program_changes=tuple(
                int(pc) for pc in available if isinstance(pc, int)
            ),
        )


def _quote_object_path(path: str) -> str:
    """Percent-encode an object path while keeping its separators readable."""
    if not path.startswith("/"):
        path = "/" + path
    return urllib.parse.quote(path, safe="/")


def _pad(values: Any, length: int) -> list[Any]:
    """Return ``values`` as a list of exactly ``length`` items, padding with -1."""
    items = list(values) if isinstance(values, list) else []
    return items + [-1] * (length - len(items))


@runtime_checkable
class DeviceWriteTransport(Protocol):
    """Read *and* write access to a device's object tree.

    Deliberately a separate Protocol from :class:`DeviceTransport`: code typed
    against the read-only one cannot modify the instrument, and ``mypy --strict``
    enforces that rather than leaving it to discipline. Only the applier accepts
    this wider interface.
    """

    def subtree(self, path: str) -> dict[str, Any]:
        """Return ``{objectPath: {"meta": ..., "value": ...}}`` under ``path``."""

    def meta(self, path: str) -> dict[str, Any]:
        """Return the JSON-Schema-ish description of one object's properties."""

    def properties(self, path: str) -> dict[str, Any]:
        """Return one object's current property values."""

    def query(self, path: str, method: str, arguments: list[Any]) -> Any:
        """Call an allow-listed, side-effect-free object method."""

    def set_properties(self, path: str, values: dict[str, Any]) -> None:
        """Write property values to one object."""

    def invoke(self, path: str, method: str, arguments: list[Any]) -> Any:
        """Call any object method, including mutating ones."""


class CoreWriteClient(CoreClient):
    """A client that can also write.

    Kept as a distinct class rather than a flag on :class:`CoreClient` so that a
    module which never imports this name is provably incapable of mutating the
    instrument. Every write path in FretWise goes through
    :mod:`fretwise.devices.headrush_core.pusher`, which owns the safety gates —
    this class is only the transport.
    """

    def set_properties(self, path: str, values: dict[str, Any]) -> None:
        """PUT property values to one object.

        Note that a PUT alone is **not persisted** for every property: the rig's
        MIDI Program Change, for instance, reverts on the next rig load unless
        ``Rigs.saveRig`` follows. ``dirty`` does not reliably flag this.

        Raises:
            DeviceUnreachableError: The device did not answer.
            DeviceProtocolError: The device rejected the write.
        """
        url = f"{self.base_url}/object-properties{_quote_object_path(path)}"
        request = urllib.request.Request(
            url,
            data=json.dumps(values).encode(),
            headers={"Content-Type": "application/json"},
            method="PUT",
        )
        try:
            urllib.request.urlopen(request, timeout=self.timeout).close()
        except urllib.error.HTTPError as exc:
            raise DeviceProtocolError(f"PUT {url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceUnreachableError(f"no answer from {self.host}") from exc

    def invoke(self, path: str, method: str, arguments: list[Any]) -> Any:
        """Call any object method, including mutating ones.

        Unlike :meth:`CoreClient.query` this has no allow-list — the caller is
        responsible for the safety gates.

        Raises:
            DeviceUnreachableError: The device did not answer.
            DeviceProtocolError: The answer carried no return value.
        """
        url = f"{self.base_url}/object-method{_quote_object_path(path)}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps({"arguments": arguments}).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read())
        except urllib.error.HTTPError as exc:
            raise DeviceProtocolError(f"{url} returned HTTP {exc.code}") from exc
        except (urllib.error.URLError, OSError) as exc:
            raise DeviceUnreachableError(f"no answer from {self.host}") from exc
        except json.JSONDecodeError as exc:
            raise DeviceProtocolError(f"{url} did not return JSON") from exc
        if not isinstance(payload, dict) or "methodReturnValue" not in payload:
            raise DeviceProtocolError(f"{url} returned no methodReturnValue")
        return payload["methodReturnValue"]
