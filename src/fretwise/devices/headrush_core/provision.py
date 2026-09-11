"""Turn a stored binding into a named rig on the instrument — create or update.

Shared by ``scripts/device_provision.py`` and the web app's "send to the
HeadRush" button, so both follow exactly the same sequence and the same gates.

**Create** (the song has no rig on the device yet):

1. load the sandbox rig ``#FW - SCRATCH`` — a rig the user made once by hand,
   whose saved state is never touched;
2. write the chain and parameters into it (live, unsaved);
3. read everything back;
4. ``saveRigAs`` under the song's name, which mints a **new** GUID and leaves the
   sandbox as it was on flash;
5. optionally assign a Program Change, then record the GUID in the song table.

**Update** (the song table already maps it to a GUID): load that GUID, write,
read back, ``saveRig``. Never ``saveRigAs`` — that would pile up a duplicate on
every regeneration.

Every lock of :mod:`fretwise.devices.headrush_core.pusher` still applies, and the
cheap ones are checked **before** the first rig load, so a refused push leaves the
instrument exactly as it was.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any

from fretwise.devices.headrush_core.bindings import BindingStore, RigBinding, binding_hash
from fretwise.devices.headrush_core.catalog import Catalog
from fretwise.devices.headrush_core.client import DeviceWriteTransport
from fretwise.devices.headrush_core.plan import GENERATED_PREFIX, Plan, build_plan
from fretwise.devices.headrush_core.pusher import (
    ApplyReport,
    DeviceBusy,
    WriteRefused,
    apply_plan,
    plan_token,
    promote_loaded_rig,
    set_program_change,
    write_allowed,
)

#: The hand-made rig every creation starts from. Its saved state is never written.
SANDBOX_NAME = GENERATED_PREFIX + "SCRATCH"

#: Program Changes kept for the sandbox and tests (docs/headrush_core.md §4.2).
RESERVED_PROGRAM_CHANGES = frozenset(range(112, 128))


@dataclass
class ProvisionResult:
    """What a provisioning run did."""

    mode: str  # "create" | "update" | "unchanged" | "program_change"
    rig_id: str
    rig_name: str
    program_change: int | None
    report: ApplyReport | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        """Return True when nothing was left unverified."""
        return self.report is None or self.report.ok

    def to_json(self) -> dict[str, Any]:
        """Return the result as a JSON-serializable dict."""
        report = self.report
        return {
            "mode": self.mode,
            "ok": self.ok,
            "rigId": self.rig_id,
            "rigName": self.rig_name,
            "programChange": self.program_change,
            "applied": list(report.applied) if report else [],
            "verified": len(report.verified) if report else 0,
            "mismatches": list(report.mismatches) if report else [],
            "saved": bool(report.saved) if report else False,
            "notes": list(self.notes),
        }


def find_known(stores: Sequence[BindingStore], artist: str, title: str) -> RigBinding | None:
    """Return the first entry any of ``stores`` holds for a song."""
    for store in stores:
        entry = store.get(artist, title)
        if entry is not None:
            return entry
    return None


def provision_mode(
    document: dict[str, Any], known: RigBinding | None, program_change: int | None
) -> str:
    """Return what :func:`provision_rig` would do, without touching anything."""
    if known is None:
        return "create"
    if known.binding_hash == binding_hash(document):
        if program_change is not None and program_change != known.program_change:
            return "program_change"
        return "unchanged"
    return "update"


def suggest_program_change(
    assigned: set[int], available: Sequence[int] | None = None
) -> int | None:
    """Return the lowest Program Change free on both sides, outside the reserved range.

    Args:
        assigned: Program Changes the song table already hands out.
        available: Program Changes the device reports as unassigned
            (``availableProgMIDICC``); ``None`` when the device was not read.
    """
    pool = range(128) if available is None else sorted(int(pc) for pc in available)
    for pc in pool:
        if pc not in assigned and pc not in RESERVED_PROGRAM_CHANGES:
            return pc
    return None


def _find_rig_id(transport: DeviceWriteTransport, name: str) -> str | None:
    """Return the GUID of the first rig called ``name`` on the device."""
    rigs = transport.properties("/Evil/API/Rigs")
    ids = rigs.get("AllRigIds") or []
    names = rigs.get("AllRigNames") or []
    for rig_id, rig_name in zip(ids, names):
        if str(rig_name) == name:
            return str(rig_id)
    return None


def _load_rig(transport: DeviceWriteTransport, rig_id: str, *, wait_s: float) -> None:
    """Make ``rig_id`` the loaded rig, or raise."""
    if str(transport.properties("/Evil/API/Rigs").get("loadedID", "")) == rig_id:
        return
    transport.invoke("/Evil/API/Rigs", "loadRigConfirm", [rig_id, ""])
    time.sleep(wait_s)
    loaded = str(transport.properties("/Evil/API/Rigs").get("loadedID", ""))
    if loaded != rig_id:
        raise DeviceBusy(
            f"le rig {rig_id} n'a pas été chargé — un rig modifié non sauvegardé "
            "bloque probablement le chargement : Save ou Discard sur l'appareil, puis relancer"
        )


def provision_rig(
    document: dict[str, Any],
    catalog: Catalog,
    transport: DeviceWriteTransport,
    store: BindingStore,
    *,
    known: RigBinding | None,
    confirm: bool,
    confirm_token: str | None = None,
    program_change: int | None = None,
    colour: int = -1,
    write_enabled: bool | None = None,
    sandbox_name: str = SANDBOX_NAME,
    settle_s: float = 1.2,
    load_wait_s: float = 3.0,
) -> ProvisionResult:
    """Write a binding to the device as a named rig and record it in ``store``.

    Args:
        document: A ``fretwise.device.binding.v1`` document with a ``song`` block.
        catalog: Catalog of the target firmware.
        transport: Write-capable transport.
        store: Song table the result is recorded in (and saved).
        known: The song's existing entry, from ``store`` or any other table.
        confirm: Lock 2.
        confirm_token: Lock 3 — :func:`plan_token` of the plan the user reviewed.
        program_change: Program Change to assign, or ``None`` to leave it.
        colour: Rig colour on the screen, ``-1`` to keep the sandbox's.
        write_enabled: Lock 1 as an installation setting.
        sandbox_name: Rig a creation starts from.
        settle_s: Pause after each chain edit.
        load_wait_s: Pause after a rig load.

    Raises:
        WriteRefused: A gate refused; nothing was written.
        DeviceBusy: The device did not do what was asked; state uncertain.
        DeviceError: The device could not be reached or answered oddly.
    """
    song = document.get("song") or {}
    artist = str(song.get("artist") or "")
    title = str(song.get("title") or "")
    if not artist and not title:
        raise WriteRefused("le binding n'a pas de bloc 'song' (artist/title)")
    if program_change is not None and not 0 <= program_change <= 127:
        raise WriteRefused(f"Program Change hors 0..127 : {program_change}")

    plan: Plan = build_plan(document, catalog)
    if not plan.is_applicable:
        raise WriteRefused("le plan porte des erreurs : " + " · ".join(plan.errors))
    # The cheap locks first: a refusal here must leave the loaded rig untouched.
    if not write_allowed(write_enabled):
        raise WriteRefused("écriture désactivée sur cette installation — verrou 1/3")
    if not confirm:
        raise WriteRefused("confirmation absente — verrou 2/3")
    if confirm_token is not None and confirm_token != plan_token(plan):
        raise WriteRefused("le rig a changé depuis l'aperçu — verrou 3/3, relancer l'aperçu")
    if transport.properties("/Evil/API/RigSaveDialog").get("displayDialog"):
        raise WriteRefused(
            "un dialogue de sauvegarde est ouvert sur l'appareil : Save ou Discard, puis relancer"
        )

    digest = binding_hash(document)
    mode = provision_mode(document, known, program_change)

    if known is not None and mode in ("unchanged", "program_change"):
        if mode == "program_change" and program_change is not None:
            _load_rig(transport, known.rig_id, wait_s=load_wait_s)
            set_program_change(transport, program_change)
            store.record(
                artist, title,
                rig_id=known.rig_id, rig_name=known.rig_name, binding_hash=digest,
                app_version=catalog.app_version, program_change=program_change,
            )
            store.save()
        return ProvisionResult(
            mode=mode,
            rig_id=known.rig_id,
            rig_name=known.rig_name,
            program_change=program_change if program_change is not None
            else known.program_change,
            notes=["rig identique à la dernière écriture : rien réécrit"]
            if mode == "unchanged" else [],
        )

    if known is not None:
        target = known.rig_id
    else:
        found = _find_rig_id(transport, sandbox_name)
        if found is None:
            raise WriteRefused(
                f"aucun rig {sandbox_name!r} sur l'appareil. En créer un vide à la main "
                "(il sert de modèle, jamais modifié), puis relancer"
            )
        target = found
    _load_rig(transport, target, wait_s=load_wait_s)

    report = apply_plan(
        plan,
        catalog,
        transport,
        dry_run=False,
        confirm=True,
        confirm_token=confirm_token,
        save=known is not None,
        settle_s=settle_s,
        write_enabled=write_enabled,
    )
    if not report.ok:
        # Created rigs are never promoted half-verified; the sandbox stays unsaved.
        return ProvisionResult(
            mode=mode,
            rig_id=known.rig_id if known else "",
            rig_name=plan.rig_name,
            program_change=None,
            report=report,
            notes=["écarts à la relecture : rien n'a été sauvegardé"],
        )

    rig_id = known.rig_id if known else promote_loaded_rig(
        transport, plan.rig_name, colour=colour, wait_s=load_wait_s
    )
    if program_change is not None:
        set_program_change(transport, program_change)
    entry = store.record(
        artist,
        title,
        rig_id=rig_id,
        rig_name=plan.rig_name,
        binding_hash=digest,
        app_version=catalog.app_version,
        program_change=program_change,
    )
    store.save()
    return ProvisionResult(
        mode=mode,
        rig_id=rig_id,
        rig_name=entry.rig_name,
        program_change=entry.program_change,
        report=report,
    )


__all__ = [
    "RESERVED_PROGRAM_CHANGES",
    "SANDBOX_NAME",
    "ProvisionResult",
    "find_known",
    "provision_mode",
    "provision_rig",
    "suggest_program_change",
]
