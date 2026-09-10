"""Turn a rig binding document into an ordered, validated write plan — offline.

This is the last step that touches no hardware. It reads a
``fretwise.device.binding.v1`` document plus the generated catalog, resolves every
module name and parameter value against what the device actually offers, and emits
the exact sequence of calls a writer would make.

Producing the plan separately from applying it is what makes the write path
reviewable: a plan is a diffable artifact, it can be read before anything is
touched, and every failure it can detect — an unknown module, an out-of-range
value, a mistyped enum label, an ordering violation, a duplicated module type —
is found here rather than halfway through mutating a real rig, which the device
offers no way to roll back.

The plan deliberately ends **without** ``saveRig``: committing is the applier's
decision, taken after the read-back check.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fretwise.devices.headrush_core.catalog import BlockSchema, Catalog
from fretwise.devices.headrush_core.chain import (
    Placement,
    assign_slots,
    check_relocation,
    placement_calls,
    validate_order,
)
from fretwise.devices.headrush_core.params import ParamError, device_value, format_display

#: Schema id of the input document.
BINDING_SCHEMA_VERSION = "fretwise.device.binding.v1"

#: Reserved prefix. The applier refuses any rig whose name lacks it, so the blast
#: radius on hand-made rigs is zero.
GENERATED_PREFIX = "#FW - "


class PlanError(ValueError):
    """The binding document cannot be turned into a valid plan."""


@dataclass(frozen=True)
class Step:
    """One device call, with a human-readable description."""

    kind: str
    path: str
    method: str | None
    payload: dict[str, Any]
    describe: str

    def __str__(self) -> str:
        return self.describe


@dataclass
class Plan:
    """An ordered write plan plus everything found wrong while building it."""

    rig_name: str
    program_change: int | None
    app_version: str
    placements: list[Placement] = field(default_factory=list)
    steps: list[Step] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def is_applicable(self) -> bool:
        """Return True when nothing blocks this plan from being applied."""
        return not self.errors

    def render(self) -> str:
        """Render the plan as a report suitable for review before any write."""
        lines = [
            f"Plan pour {self.rig_name!r}",
            f"  firmware cible : {self.app_version}",
            f"  MIDI PROG      : {self.program_change if self.program_change is not None else '—'}",
            f"  blocs          : {len(self.placements)}",
            "",
            "  Chaîne :",
        ]
        for placement in self.placements:
            marker = "*" if placement.is_frozen_head else " "
            lines.append(
                f"   {placement.slot:>2}{marker} CC{placement.bypass_cc:<3} "
                f"{placement.category:<12} {placement.module}"
            )
        lines += ["", f"  Écritures ({len(self.steps)}) :"]
        lines += [f"   {i:>3}. {step}" for i, step in enumerate(self.steps, start=1)]
        if self.warnings:
            lines += ["", "  Avertissements :"] + [f"   - {w}" for w in self.warnings]
        if self.errors:
            lines += ["", "  ERREURS (plan non applicable) :"] + [f"   - {e}" for e in self.errors]
        else:
            lines += ["", "  Plan applicable. saveRig() reste à la charge de l'applicateur."]
        return "\n".join(lines)


def load_binding(path: Path) -> dict[str, Any]:
    """Read a binding document and check its schema id.

    Raises:
        PlanError: The file is not a binding of the expected schema version.
    """
    payload: Any = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PlanError(f"{path} does not contain a JSON object")
    if payload.get("schemaVersion") != BINDING_SCHEMA_VERSION:
        raise PlanError(
            f"{path} is not a {BINDING_SCHEMA_VERSION} document "
            f"(found {payload.get('schemaVersion')!r})"
        )
    result: dict[str, Any] = payload
    return result


def _resolve_category(catalog: Catalog, module: str) -> str | None:
    """Return the selector category of a module, tolerating the ``X 2`` twin form."""
    base = module[:-2] if module.endswith(" 2") else module
    for category, names in catalog.category_blocks.items():
        if base in names:
            return category
    return None


def build_plan(binding: dict[str, Any], catalog: Catalog) -> Plan:
    """Turn a binding document into a validated write plan.

    Args:
        binding: Parsed ``fretwise.device.binding.v1`` document.
        catalog: Catalog generated from the target device.

    Returns:
        A :class:`Plan`; inspect ``errors`` before applying it.
    """
    rig = binding.get("rig") or {}
    name = str(rig.get("name", ""))
    declared = str((binding.get("device") or {}).get("appVersion", ""))
    plan = Plan(
        rig_name=name,
        program_change=rig.get("programChange"),
        app_version=catalog.app_version,
    )

    if not name.startswith(GENERATED_PREFIX):
        plan.errors.append(
            f"le nom du rig doit commencer par {GENERATED_PREFIX!r} — "
            "garde-fou contre l'écrasement d'un rig fait main"
        )
    if declared and declared != catalog.app_version:
        plan.errors.append(
            f"le binding vise le firmware {declared}, le catalogue est {catalog.app_version} : "
            "les identifiants de module sont positionnels, régénérer le catalogue"
        )

    entries = binding.get("blocks") or []
    resolved: list[tuple[str, str]] = []
    for entry in entries:
        module = str(entry.get("module", ""))
        if catalog.block(module) is None:
            plan.errors.append(f"bloc inconnu du catalogue : {module!r}")
            continue
        if catalog.module_type_id(module) is None:
            plan.errors.append(f"{module!r} n'est pas un ModuleType plaçable")
            continue
        category = _resolve_category(catalog, module)
        if category is None:
            plan.warnings.append(f"{module!r} : catégorie inconnue, placé dans la queue libre")
            category = "?"
        resolved.append((module, category))

    if plan.errors:
        return plan

    try:
        plan.placements = assign_slots(resolved)
    except Exception as exc:  # ChainError and anything assign_slots raises
        plan.errors.append(str(exc))
        return plan

    plan.errors.extend(check_relocation(plan.placements))
    for problem in validate_order(plan.placements):
        (plan.warnings if problem.startswith("note:") else plan.errors).append(problem)

    for zero_based, module in placement_calls(plan.placements):
        plan.steps.append(
            Step(
                kind="method",
                path="/Evil/Engine/Patch/Chain",
                method="setModuleTypeInternal",
                payload={"arguments": [zero_based, catalog.module_type_id(module)]},
                describe=f"slot {zero_based + 1:>2} <- {module}"
                f"  (argument 0-indexé : {zero_based})",
            )
        )

    params_by_module = {
        str(e.get("module", "")): (e.get("params") or {}) for e in entries
    }
    for placement in plan.placements:
        block = catalog.block(placement.module)
        if block is None:
            continue
        wanted = params_by_module.get(placement.module) or {}
        if not wanted:
            continue
        body, notes, errors = _param_body(block, wanted)
        plan.warnings.extend(notes)
        plan.errors.extend(errors)
        if body:
            plan.steps.append(
                Step(
                    kind="put",
                    path=f"/Evil/Engine/Patch/{block.name}",
                    method=None,
                    payload=body,
                    describe=f"slot {placement.slot:>2}  {placement.module} : "
                    + ", ".join(f"{k}={v}" for k, v in notes_to_pairs(block, wanted)),
                )
            )

    if plan.program_change is not None:
        plan.steps.append(
            Step(
                kind="put",
                path="/Evil/API/Rigs",
                method=None,
                payload={"loadedProgMIDICC": int(plan.program_change)},
                describe=f"MIDI PROG <- {plan.program_change} "
                f"(affiché {int(plan.program_change) + 1} sur l'écran)",
            )
        )
    return plan


def notes_to_pairs(block: BlockSchema, wanted: dict[str, Any]) -> list[tuple[str, str]]:
    """Return ``(name, formatted value)`` pairs for a block's requested parameters."""
    pairs: list[tuple[str, str]] = []
    for key, value in wanted.items():
        param = block.param(key)
        if param is None:
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and not param.options:
            pairs.append((key, format_display(param, float(value))))
        else:
            pairs.append((key, str(value)))
    return pairs


def _param_body(
    block: BlockSchema, wanted: dict[str, Any]
) -> tuple[dict[str, Any], list[str], list[str]]:
    """Convert requested display values into a PUT body, collecting problems."""
    body: dict[str, Any] = {}
    notes: list[str] = []
    errors: list[str] = []
    for key, value in wanted.items():
        param = block.param(key)
        if param is None:
            errors.append(f"{block.name} n'a pas de paramètre {key!r}")
            continue
        try:
            body[key] = device_value(param, value)
        except ParamError as exc:
            errors.append(f"{block.name}.{key} : {exc}")
    return body, notes, errors
