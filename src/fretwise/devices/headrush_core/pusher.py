"""Apply a write plan to a real HeadRush Core, with the gates that make it safe.

The device offers **no transaction and no rollback**: provisioning a rig is N
separate calls, and a failure halfway leaves a real rig half-written. Everything
here exists because of that.

**Three independent locks**, each covering a different way to write by accident:

1. ``FRETWISE_HEADRUSH_ALLOW_WRITE`` in the environment — the script launched by
   mistake, or a test that wandered onto the LAN;
2. an explicit ``confirm=True`` — the interactive typo;
3. a ``confirm_token`` computed from the plan — the race. The device is re-read
   immediately before the first write and the token recomputed; if the instrument
   moved between planning and applying, :class:`DeviceBusy` is raised instead of
   writing over whatever is there now.

**Two guards on what may be touched at all**: the loaded rig's name must carry the
reserved prefix (so the blast radius on hand-made rigs is zero), and the pending
save dialog must be closed (a pending change silently blocks rig loads and makes
every subsequent read report the *previous* rig).

**Closed-loop verification**: after the parameter writes, every value is read back
and re-denormalized. An error beyond one ``grid`` step means the curve or the value
was wrong, and it is caught mechanically rather than by ear.

``saveRig`` is called only when asked, and only after verification passes — because
a PUT alone does not persist (the Program Change reverts on the next rig load) while
``dirty`` does not reliably flag that it needs saving.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from typing import Any

from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.devices.headrush_core.client import DeviceError, DeviceWriteTransport
from fretwise.devices.headrush_core.params import round_trip_error, to_display, within_grid
from fretwise.devices.headrush_core.plan import GENERATED_PREFIX, Plan

#: Environment variable that must be set for any write to happen.
WRITE_ENV_VAR = "FRETWISE_HEADRUSH_ALLOW_WRITE"

#: Objects the applier is allowed to write to. Anything else is a bug in a plan.
_WRITABLE_ROOTS = ("/Evil/Engine/Patch/", "/Evil/API/Rigs", "/Evil/Engine/Tempo")


class WriteRefused(DeviceError):
    """A safety gate rejected the write."""


class DeviceBusy(DeviceError):
    """The instrument changed between planning and applying."""


class VerificationFailed(DeviceError):
    """A value read back does not match what was written."""


@dataclass
class ApplyReport:
    """What an apply run did, and what it checked."""

    dry_run: bool
    rig_name: str
    applied: list[str] = field(default_factory=list)
    verified: list[str] = field(default_factory=list)
    mismatches: list[str] = field(default_factory=list)
    saved: bool = False

    @property
    def ok(self) -> bool:
        """Return True when everything applied and verified."""
        return not self.mismatches

    def render(self) -> str:
        """Render the run as a report."""
        head = "SIMULATION (aucune écriture)" if self.dry_run else "APPLIQUÉ"
        lines = [f"{head} — {self.rig_name!r}", ""]
        lines += [f"  {i:>3}. {a}" for i, a in enumerate(self.applied, start=1)]
        if self.verified:
            lines += ["", f"  Relectures conformes : {len(self.verified)}"]
        if self.mismatches:
            lines += ["", "  ÉCARTS À LA RELECTURE :"] + [f"   - {m}" for m in self.mismatches]
        lines += ["", f"  saveRig() : {'oui' if self.saved else 'non'}"]
        return "\n".join(lines)


def write_allowed(write_enabled: bool | None = None) -> bool:
    """Return whether lock 1 is open.

    Args:
        write_enabled: The installation's own opt-in (the web app's "allow writes"
            setting). ``None`` means the caller has no such setting, and only the
            environment variable counts. Either one opens the lock; neither is on
            by default.
    """
    return bool(write_enabled) or bool(os.environ.get(WRITE_ENV_VAR))


def plan_token(plan: Plan) -> str:
    """Return a digest of a plan's steps, used to detect a stale plan."""
    payload = json.dumps(
        [[s.kind, s.path, s.method, s.payload] for s in plan.steps],
        sort_keys=True,
        ensure_ascii=False,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def device_token(transport: DeviceWriteTransport) -> str:
    """Return a digest of the device state a plan was built against."""
    rigs = transport.properties("/Evil/API/Rigs")
    chain = transport.properties("/Evil/Engine/Patch/Chain")
    payload = json.dumps(
        {
            "loadedID": rigs.get("loadedID"),
            "loadedName": rigs.get("loadedName"),
            "chain": [chain.get(f"ModuleType{s}") for s in range(1, 15)],
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()


def _check_gates(
    transport: DeviceWriteTransport,
    plan: Plan,
    catalog: Catalog,
    *,
    confirm: bool,
    confirm_token: str | None,
    write_enabled: bool | None = None,
) -> None:
    """Raise unless every safety gate is satisfied."""
    if not plan.is_applicable:
        raise WriteRefused(
            "le plan porte des erreurs : " + " · ".join(plan.errors)
        )
    if not write_allowed(write_enabled):
        raise WriteRefused(
            f"écriture désactivée ({WRITE_ENV_VAR} absent, option non cochée) — "
            "verrou 1/3, aucune écriture"
        )
    if not confirm:
        raise WriteRefused("confirm=False — verrou 2/3, aucune écriture")

    expected = plan_token(plan)
    if confirm_token is not None and confirm_token != expected:
        raise WriteRefused(
            f"jeton de confirmation périmé (attendu {expected[:12]}…) — verrou 3/3"
        )

    identity = transport.properties("/Evil/Gui")
    if str(identity.get("AppVersion")) != catalog.app_version:
        raise WriteRefused(
            f"l'appareil est en {identity.get('AppVersion')}, le catalogue en "
            f"{catalog.app_version} : identifiants de module positionnels, régénérer"
        )

    dialog = transport.properties("/Evil/API/RigSaveDialog")
    if dialog.get("displayDialog"):
        raise WriteRefused(
            "un dialogue de sauvegarde est ouvert sur l'appareil : il bloque les "
            "chargements de rig et fausse toute relecture. Le résoudre à la main "
            "(Save ou Discard) avant de relancer"
        )

    rigs = transport.properties("/Evil/API/Rigs")
    loaded = str(rigs.get("loadedName", ""))
    if not loaded.startswith(GENERATED_PREFIX):
        raise WriteRefused(
            f"le rig chargé est {loaded!r} : l'applicateur n'écrit que dans un rig "
            f"dont le nom commence par {GENERATED_PREFIX!r}. Charger le bac à sable."
        )


def _verify_chain(transport: DeviceWriteTransport, plan: Plan, catalog: Catalog) -> list[str]:
    """Return mismatches between the intended chain and what the device now holds."""
    chain = transport.properties("/Evil/Engine/Patch/Chain")
    problems: list[str] = []
    for placement in plan.placements:
        actual_id = chain.get(f"ModuleType{placement.slot}")
        expected_id = catalog.module_type_id(placement.module)
        if actual_id != expected_id:
            actual_name = (
                catalog.module_types[actual_id]
                if isinstance(actual_id, int) and 0 <= actual_id < len(catalog.module_types)
                else str(actual_id)
            )
            problems.append(
                f"slot {placement.slot} : attendu {placement.module!r}, trouvé "
                f"{actual_name!r} — un type déjà présent a pu être DÉPLACÉ"
            )
    return problems


def _verify_params(transport: DeviceWriteTransport, plan: Plan, catalog: Catalog) -> tuple[
    list[str], list[str]
]:
    """Read back every written parameter and check it against the intent."""
    verified: list[str] = []
    mismatches: list[str] = []
    for step in plan.steps:
        if step.kind != "put" or not step.path.startswith("/Evil/Engine/Patch/"):
            continue
        block_name = step.path.rsplit("/", 1)[-1]
        block = catalog.block(block_name)
        if block is None:
            continue
        actual = transport.properties(step.path)
        for key, written in step.payload.items():
            param = block.param(key)
            if param is None:
                continue
            got = actual.get(key)
            if param.type == "boolean" or param.options:
                if got != written:
                    mismatches.append(f"{block_name}.{key} : écrit {written!r}, relu {got!r}")
                else:
                    verified.append(f"{block_name}.{key}")
                continue
            if not isinstance(got, (int, float)) or not isinstance(written, (int, float)):
                mismatches.append(f"{block_name}.{key} : type inattendu à la relecture")
                continue
            intended = to_display(param, float(written))
            error = round_trip_error(param, intended)
            if abs(float(got) - float(written)) > 1e-4 or not within_grid(param, error):
                mismatches.append(
                    f"{block_name}.{key} : écrit {written:.6f}, relu {float(got):.6f} "
                    f"(écart affiché {error:.4g})"
                )
            else:
                verified.append(f"{block_name}.{key}")
    return verified, mismatches


def apply_plan(
    plan: Plan,
    catalog: Catalog,
    transport: DeviceWriteTransport,
    *,
    dry_run: bool = True,
    confirm: bool = False,
    confirm_token: str | None = None,
    save: bool = False,
    settle_s: float = 1.2,
    write_enabled: bool | None = None,
) -> ApplyReport:
    """Apply a plan to the device, or simulate it.

    Args:
        plan: A plan whose ``is_applicable`` is True.
        catalog: The catalog the plan was built against.
        transport: Write-capable transport.
        dry_run: When True (the default) nothing is written; the report lists what
            would have been.
        confirm: Second lock — must be explicitly True.
        confirm_token: Third lock — :func:`plan_token` of the plan as reviewed.
        save: Call ``Rigs.saveRig`` after verification passes. A PUT alone does
            not persist, so leaving this False means the change is live but
            temporary.
        settle_s: Pause after each chain edit, letting the engine rebuild.
        write_enabled: First lock as an installation setting; see
            :func:`write_allowed`.

    Returns:
        An :class:`ApplyReport`.

    Raises:
        WriteRefused: A safety gate rejected the write.
        DeviceBusy: The instrument moved between planning and applying.
    """
    report = ApplyReport(dry_run=dry_run, rig_name=plan.rig_name)

    if dry_run:
        for step in plan.steps:
            report.applied.append(f"[simulé] {step.describe}")
        return report

    _check_gates(
        transport,
        plan,
        catalog,
        confirm=confirm,
        confirm_token=confirm_token,
        write_enabled=write_enabled,
    )
    before = device_token(transport)

    for step in plan.steps:
        if not any(step.path.startswith(root) for root in _WRITABLE_ROOTS):
            raise WriteRefused(f"le plan vise un objet non autorisé : {step.path}")

    if device_token(transport) != before:
        raise DeviceBusy("l'état de l'appareil a changé pendant les contrôles")

    for step in plan.steps:
        if step.kind == "method" and step.method:
            transport.invoke(step.path, step.method, list(step.payload["arguments"]))
            time.sleep(settle_s)
        else:
            transport.set_properties(step.path, step.payload)
        report.applied.append(step.describe)

    report.mismatches.extend(_verify_chain(transport, plan, catalog))
    verified, mismatches = _verify_params(transport, plan, catalog)
    report.verified.extend(verified)
    report.mismatches.extend(mismatches)

    if save and report.ok:
        transport.invoke("/Evil/API/Rigs", "saveRig", [])
        report.saved = True
    return report


def summarize_state(transport: DeviceWriteTransport) -> dict[str, Any]:
    """Return the few properties worth showing before and after an apply."""
    rigs = transport.properties("/Evil/API/Rigs")
    cpu = transport.properties("/Evil/Engine/CPUMeter").get("CPUTimeSmoothed", 0.0)
    return {
        "rig": rigs.get("loadedName"),
        "programChange": rigs.get("loadedProgMIDICC"),
        "dirty": rigs.get("dirty"),
        "cpuPercent": round(float(cpu) * 200.0, 1),
    }


def promote_loaded_rig(
    transport: DeviceWriteTransport,
    name: str,
    *,
    colour: int = -1,
    wait_s: float = 2.0,
) -> str:
    """Save the loaded rig under a new name and return the GUID it was given.

    ``saveRigAs`` always mints a **new** GUID — it is the only call that
    duplicates. That is what makes it the promotion primitive (sandbox becomes a
    named rig) and also why it must never be used to update: re-running it would
    pile up a new rig on every regeneration. Updating goes through
    :func:`apply_plan` on the song's existing GUID followed by ``saveRig``.

    Args:
        transport: Write-capable transport.
        name: Name for the promoted rig; must carry the reserved prefix.
        colour: Device colour index, ``-1`` to keep the current one.
        wait_s: Pause before reading the new rig back; the device writes it to
            flash first.

    Returns:
        The GUID of the newly created rig.

    Raises:
        WriteRefused: The name lacks the guard prefix, or the device declined.
        DeviceBusy: The device did not report the new rig as loaded afterwards.
    """
    if not name.startswith(GENERATED_PREFIX):
        raise WriteRefused(
            f"un rig promu doit être nommé {GENERATED_PREFIX!r}… — reçu {name!r}"
        )
    before = str(transport.properties("/Evil/API/Rigs").get("loadedID", ""))
    if transport.invoke("/Evil/API/Rigs", "saveRigAs", [name, colour]) is False:
        raise WriteRefused(f"l'appareil a refusé saveRigAs({name!r})")
    time.sleep(wait_s)
    rigs = transport.properties("/Evil/API/Rigs")
    new_id = str(rigs.get("loadedID", ""))
    if not new_id or new_id == before:
        raise DeviceBusy(
            "saveRigAs n'a pas produit de nouveau rig chargé — état de l'appareil incertain"
        )
    if str(rigs.get("loadedName", "")) != name:
        raise DeviceBusy(
            f"le rig chargé est {rigs.get('loadedName')!r}, attendu {name!r}"
        )
    return new_id


def set_program_change(transport: DeviceWriteTransport, program_change: int) -> None:
    """Assign a MIDI Program Change to the loaded rig and commit it.

    A PUT alone is not persisted for this property — it reverts on the next rig
    load — so ``saveRig`` follows unconditionally. ``dirty`` does not flag it,
    which is why there is no point checking.

    Raises:
        WriteRefused: ``program_change`` is outside 0..127.
    """
    if not 0 <= program_change <= 127:
        raise WriteRefused(f"Program Change hors 0..127 : {program_change}")
    transport.set_properties("/Evil/API/Rigs", {"loadedProgMIDICC": program_change})
    transport.invoke("/Evil/API/Rigs", "saveRig", [])
