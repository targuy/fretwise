"""Build the HeadRush Core's block catalog from the device itself.

The Core publishes its whole vocabulary through ``object-meta``: 278 module type
ids, 21 selector categories, and — for every parameter of every block — its type,
display range, unit format, step, default and enumeration labels.

This replaces the GP-180 approach in
:mod:`fretwise.gears.production.gp180_catalog`, which regex-scrapes a Notion
markdown dump. That source is second-hand and demonstrably wrong for this device
(it lists ``Blue Comp``, ``Tube Scream``, ``Klone``, ``Cry Baby Wah`` — none of
which exist on a Core — and conflates blocks with amp models, which are really
values of ``Amp.Type``). The device is the only catalog that is exact and that
moves with the firmware.

The artifact is versioned on ``Gui.AppVersion`` because ``ModuleTypes`` is a
*positional* array: a firmware update that inserts a module shifts every id after
it. Plans and backups must therefore persist **names**, never these integers —
a stale name raises, a stale index silently writes the wrong block.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from fretwise.devices.headrush_core.client import DeviceTransport

#: Schema id of the generated artifact, in the style of the gears schemas.
CATALOG_SCHEMA_VERSION = "fretwise.device.catalog.headrush-core.v1"

#: Object-tree root holding one object per block instance.
PATCH_ROOT = "/Evil/Engine/Patch"

#: Properties that describe the device UI rather than a tunable parameter.
_NON_PARAM_KEYS = frozenset({"labels", "order", "disabled"})


@dataclass(frozen=True)
class ParamSchema:
    """One tunable parameter of one block.

    Continuous parameters are stored on the device as floats in 0.0-1.0, while
    ``minimum``/``maximum`` are in *display* units — so a naive clamp against
    them lets everything through. ``normalize_algo`` selects the curve used to
    map between the two; ``None`` means Linear.
    """

    name: str
    type: str
    minimum: float | None = None
    maximum: float | None = None
    default: Any = None
    unit_format: str | None = None
    grid: float | None = None
    normalize_algo: int | None = None
    #: Enumeration labels, when the parameter is a named choice.
    options: tuple[str, ...] = ()
    read_only: bool = False

    @property
    def is_enum(self) -> bool:
        """Return True when this parameter takes one of a fixed set of labels."""
        return bool(self.options)

    @property
    def is_writable_safely(self) -> bool:
        """Return False for parameters no writer should ever touch.

        ``normalize_algo == 3`` (DelayRatio) is declared in the device UI's enum
        but has **no** entry in its own denormalization table, so even the
        official editor silently falls back to Linear for it.
        """
        return not self.read_only and self.normalize_algo != 3


@dataclass(frozen=True)
class BlockSchema:
    """One block instance as exposed under ``/Evil/Engine/Patch/<name>``."""

    name: str
    path: str
    params: tuple[ParamSchema, ...]
    #: On-screen labels, parallel to ``order``.
    labels: tuple[str, ...] = ()
    #: Parameter display order used by the device UI.
    order: tuple[str, ...] = ()

    @property
    def is_second_instance(self) -> bool:
        """Return True for the ``X 2`` twin of a block type.

        The suffix marks a *second instance of that type in the chain*, not a
        right channel — stereo doubling uses the ``…2`` properties of the same
        object (``Cab.CabType`` / ``Cab.CabType2``).
        """
        return self.name.endswith("_2")

    def param(self, name: str) -> ParamSchema | None:
        """Return one parameter by name, or None when the block has no such knob."""
        for param in self.params:
            if param.name == name:
                return param
        return None


@dataclass(frozen=True)
class Catalog:
    """Everything the device can do, at one firmware version."""

    schema_version: str
    app_version: str
    device_name: str
    product: str
    #: Positional table: index is the module type id used by ``Chain.ModuleTypeN``.
    module_types: tuple[str, ...]
    categories: tuple[str, ...]
    blocks: tuple[BlockSchema, ...]
    #: category -> selectable block names, from the device's own selector.
    category_blocks: dict[str, tuple[str, ...]] = field(default_factory=dict)

    @property
    def contract_hash(self) -> str:
        """Return a digest of the positional module table.

        A write path should refuse to run when this differs from the hash
        recorded alongside a plan: it means module ids have shifted.
        """
        payload = "\n".join(self.module_types).encode()
        return hashlib.sha256(payload).hexdigest()

    def block(self, name: str) -> BlockSchema | None:
        """Return one block by its object name (spaces become underscores)."""
        key = name.replace(" ", "_")
        for block in self.blocks:
            if block.name == key:
                return block
        return None

    def module_type_id(self, name: str) -> int | None:
        """Return the positional id for a module name, or None when absent."""
        try:
            return self.module_types.index(name)
        except ValueError:
            return None

    def to_json(self) -> dict[str, Any]:
        """Return the artifact as a JSON-serializable dict."""
        return {
            "schemaVersion": self.schema_version,
            "appVersion": self.app_version,
            "deviceName": self.device_name,
            "product": self.product,
            "contractHash": self.contract_hash,
            "moduleTypes": list(self.module_types),
            "categories": list(self.categories),
            "categoryBlocks": {k: list(v) for k, v in sorted(self.category_blocks.items())},
            "blocks": [
                {
                    "name": block.name,
                    "path": block.path,
                    "labels": list(block.labels),
                    "order": list(block.order),
                    "params": [_param_to_json(param) for param in block.params],
                }
                for block in self.blocks
            ],
        }


def _param_to_json(param: ParamSchema) -> dict[str, Any]:
    """Serialize one parameter, keeping zeroes.

    A truthiness filter would be a silent data-loss bug here: ``0.0 == False`` in
    Python, so ``minimum: 0.0`` — the lower bound of most percentage parameters —
    would be dropped, and a reader would then denormalize against a missing bound.
    Only genuinely absent values are omitted.
    """
    out: dict[str, Any] = {}
    for key, value in asdict(param).items():
        if value is None or value == ():
            continue
        if key == "read_only" and value is False:
            continue
        out[key] = value
    return out


def _parse_param(name: str, schema: dict[str, Any], value: Any) -> ParamSchema:
    """Build a :class:`ParamSchema` from one ``object-meta`` property entry."""
    options = schema.get("x-options")
    options = options if isinstance(options, dict) else {}
    strings = options.get("strings")
    return ParamSchema(
        name=name,
        type=str(schema.get("type", "unknown")),
        minimum=_as_float(schema.get("minimum")),
        maximum=_as_float(schema.get("maximum")),
        default=options.get("default", value),
        unit_format=_as_str(options.get("format")),
        grid=_as_float(options.get("grid")),
        normalize_algo=_as_int(options.get("normalizeAlgo")),
        options=tuple(str(s) for s in strings) if isinstance(strings, list) else (),
        read_only=bool(schema.get("readOnly", False)),
    )


def parse_blocks(subtree: dict[str, Any]) -> tuple[BlockSchema, ...]:
    """Turn a ``/Evil/Engine/Patch`` subtree dump into block schemas.

    Args:
        subtree: Mapping of object path to ``{"meta": ..., "value": ...}``.

    Returns:
        One :class:`BlockSchema` per block object, sorted by name. The
        non-block ``Chain`` and ``Rig`` objects are skipped.
    """
    blocks: list[BlockSchema] = []
    for path, node in sorted(subtree.items()):
        name = path.rsplit("/", 1)[-1]
        if name in {"Chain", "Rig", "CurrentBlock", "Mix"}:
            continue
        node = node or {}
        meta = node.get("meta") or {}
        value = node.get("value") or {}
        properties = meta.get("properties") or {}
        params = tuple(
            _parse_param(key, schema, value.get(key))
            for key, schema in sorted(properties.items())
            if key not in _NON_PARAM_KEYS and isinstance(schema, dict)
        )
        if not params:
            continue
        blocks.append(
            BlockSchema(
                name=name,
                path=path,
                params=params,
                labels=_as_str_tuple(value.get("labels")),
                order=_as_str_tuple(value.get("order")),
            )
        )
    return tuple(blocks)


def build_catalog(transport: DeviceTransport, *, with_categories: bool = True) -> Catalog:
    """Probe a device and return its full catalog.

    Args:
        transport: A read-only transport; see
            :class:`~fretwise.devices.headrush_core.client.DeviceTransport`.
        with_categories: Also resolve category -> block-name mapping, which costs
            one allow-listed method call per category.

    Returns:
        The assembled :class:`Catalog`.
    """
    gui = transport.properties("/Evil/Gui")
    rigs = transport.properties("/Evil/API/Rigs")
    blocks_props = transport.properties("/Evil/API/Blocks")
    module_types = tuple(str(m) for m in (blocks_props.get("ModuleTypes") or []))
    categories = tuple(str(c) for c in (blocks_props.get("BlockSelectorCategories") or []))

    category_blocks: dict[str, tuple[str, ...]] = {}
    if with_categories:
        for category in categories:
            names = transport.query("/Evil/API/Blocks", "categoryBlocks", [category, False])
            if isinstance(names, list):
                category_blocks[category] = tuple(str(n) for n in names)

    return Catalog(
        schema_version=CATALOG_SCHEMA_VERSION,
        app_version=str(gui.get("AppVersion", "")),
        device_name=str(gui.get("DeviceName", "")),
        product=str(rigs.get("product", "")),
        module_types=module_types,
        categories=categories,
        blocks=parse_blocks(transport.subtree(PATCH_ROOT)),
        category_blocks=category_blocks,
    )


def catalog_path(root: Path, catalog: Catalog) -> Path:
    """Return the on-disk location for a catalog artifact.

    Args:
        root: Repository ``data/`` directory.
        catalog: The catalog being written.
    """
    return root / "devices" / "headrush-core" / "catalog" / f"{catalog.app_version}.json"


def write_catalog(catalog: Catalog, path: Path) -> Path:
    """Write ``catalog`` as pretty JSON, creating parent directories.

    Args:
        catalog: Catalog to serialize.
        path: Destination file.

    Returns:
        The path written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(catalog.to_json(), indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    return path


def _as_float(value: Any) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _as_int(value: Any) -> int | None:
    return int(value) if isinstance(value, int) and not isinstance(value, bool) else None


def _as_str(value: Any) -> str | None:
    return str(value) if isinstance(value, str) else None


def _as_str_tuple(value: Any) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def load_catalog(path: Path) -> Catalog:
    """Read a catalog artifact previously written by :func:`write_catalog`.

    Args:
        path: JSON file produced by ``device_catalog_dump``.

    Returns:
        The parsed :class:`Catalog`.

    Raises:
        ValueError: The file is not a catalog of a known schema version.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("schemaVersion") != CATALOG_SCHEMA_VERSION:
        raise ValueError(
            f"{path} is not a {CATALOG_SCHEMA_VERSION} document "
            f"(found {payload.get('schemaVersion')!r})"
        )
    blocks: list[BlockSchema] = []
    for entry in payload.get("blocks", []):
        params = tuple(
            ParamSchema(
                name=str(p["name"]),
                type=str(p.get("type", "number")),
                minimum=p.get("minimum"),
                maximum=p.get("maximum"),
                default=p.get("default"),
                unit_format=p.get("unit_format"),
                grid=p.get("grid"),
                normalize_algo=p.get("normalize_algo"),
                options=tuple(p.get("options", ())),
                read_only=bool(p.get("read_only", False)),
            )
            for p in entry.get("params", [])
        )
        blocks.append(
            BlockSchema(
                name=str(entry["name"]),
                path=str(entry.get("path", "")),
                params=params,
                labels=tuple(entry.get("labels", ())),
                order=tuple(entry.get("order", ())),
            )
        )
    return Catalog(
        schema_version=str(payload["schemaVersion"]),
        app_version=str(payload.get("appVersion", "")),
        device_name=str(payload.get("deviceName", "")),
        product=str(payload.get("product", "")),
        module_types=tuple(str(m) for m in payload.get("moduleTypes", [])),
        categories=tuple(str(c) for c in payload.get("categories", [])),
        blocks=tuple(blocks),
        category_blocks={
            str(k): tuple(str(x) for x in v)
            for k, v in (payload.get("categoryBlocks") or {}).items()
        },
    )
