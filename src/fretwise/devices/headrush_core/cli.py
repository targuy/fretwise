"""Command-line entry points for the HeadRush Core read-only tools.

Thin wrappers live in ``scripts/device_probe.py`` and
``scripts/device_catalog_dump.py``; all behaviour is here, per the repository's
CLI rule.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from fretwise.devices.headrush_core.bindings import (
    BindingStore,
    default_store_path,
)
from fretwise.devices.headrush_core.catalog import (
    build_catalog,
    catalog_path,
    load_catalog,
    write_catalog,
)
from fretwise.devices.headrush_core.client import (
    HOST_ENV_VAR,
    CoreClient,
    CoreWriteClient,
    DeviceError,
    DeviceSnapshot,
)
from fretwise.devices.headrush_core.images import ImageCache, all_image_relpaths
from fretwise.devices.headrush_core.plan import PlanError, build_plan, load_binding
from fretwise.devices.headrush_core.prompt import PromptError, build_rig_prompt, parse_rig_response
from fretwise.devices.headrush_core.provision import (
    SANDBOX_NAME,
    provision_mode,
    provision_rig,
)
from fretwise.devices.headrush_core.pusher import (
    apply_plan,
    plan_token,
    summarize_state,
)
from fretwise.devices.headrush_core.snapshot import (
    capture_rig,
    default_snapshot_path,
    diff_snapshots,
    load_snapshot,
    write_snapshot,
)
from fretwise.gears.naming import gears_key

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _configure_stdout() -> None:
    """Make stdout tolerate non-ASCII on a legacy Windows code page.

    The default PowerShell console here is cp1252, which raises on characters
    like ``≥`` or a box-drawing glyph. Rig names come from the device and are
    free text, so a report must never die on one.
    """
    stream = getattr(sys, "stdout", None)
    reconfigure = getattr(stream, "reconfigure", None)
    if reconfigure is not None:
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (ValueError, OSError):  # already detached, or not a real console
            pass


def _add_host_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--host",
        default=None,
        help=f"device host or IP (default: ${HOST_ENV_VAR}, else headrushcore.local)",
    )


def _format_snapshot(snapshot: DeviceSnapshot) -> str:
    """Render a probe result as an aligned, human-readable report."""
    identity = snapshot.identity
    assigned = snapshot.assigned_program_changes
    general = snapshot.general_settings
    midi = snapshot.midi_settings
    channel = midi.get("Channel")
    channel_label = "Omni" if channel == 0 else str(channel)
    loaded_pc = snapshot.loaded_rig.program_change
    loaded_pc_label = "—" if loaded_pc is None else str(loaded_pc)

    lines = [
        f"{identity.device_name}  ({identity.product}, firmware {identity.app_version})",
        "",
        f"  rig chargé      : {snapshot.loaded_rig.name!r}",
        f"  rig id          : {snapshot.loaded_rig.rig_id}",
        f"  MIDI PROG       : {loaded_pc_label}",
        f"  CPU             : {snapshot.cpu_percent:.0f} %",
        f"  rigs stockés    : {len(snapshot.rigs)}",
        f"  PC assignés     : {len(assigned)}/128"
        + (f"  ({', '.join(str(pc) for pc in assigned[:12])}…)" if assigned else "  (aucun)"),
        "",
        "  MIDI :",
        f"    canal              : {channel_label}",
        f"    reçoit Prog Change : {midi.get('ReceiveProgramChange')}",
        f"    reçoit MIDI Clock  : {midi.get('MBCIn')}",
        f"    MIDI Thru          : {midi.get('MIDIThrough')}",
        "",
        "  Réglages tactiles (sans effet sur le chemin API, cf. doc §2.8) :",
        f"    AutoAmpCab         : {general.get('AutoAmpCab')}",
        f"    AutoAssignments    : {general.get('AutoAssignments')}",
        "",
        "  Chaîne du rig chargé :",
    ]
    for slot in snapshot.chain:
        marker = "   " if slot.is_empty else " > "
        cc = 74 + slot.slot
        lines.append(f"  {marker} slot {slot.slot:>2}  CC{cc:<3}  {slot.module_name}")

    warnings: list[str] = []
    if channel == 0:
        warnings.append(
            "canal MIDI en Omni : le Core obéit aux PC/CC de n'importe quel appareil"
        )
    # AutoAmpCab / AutoAssignments are deliberately NOT warned about: measured on
    # hardware, they govern the touchscreen flow only. Three API chain edits left
    # `Module1..10` and `FootSwitchText1..10` untouched and added no cab. See
    # docs/headrush_core.md §2.8 — an earlier version of this design wrongly
    # required them to be off.
    if warnings:
        lines.append("")
        lines.extend(f"  /!\\ {warning}" for warning in warnings)
    return "\n".join(lines)


def probe_main(argv: list[str] | None = None) -> int:
    """Print a read-only report of the device's current state.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        Process exit code.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_probe",
        description="Inventaire lecture seule d'un HeadRush Core sur le réseau local.",
    )
    _add_host_argument(parser)
    parser.add_argument("--json", action="store_true", help="sortie JSON brute")
    parser.add_argument(
        "--rigs", action="store_true", help="lister les rigs stockés au lieu du rapport"
    )
    args = parser.parse_args(argv)

    client = CoreClient(args.host)
    try:
        snapshot = client.snapshot()
    except DeviceError as exc:
        print(f"erreur : {exc}")
        return 1

    if args.rigs:
        for index, rig in enumerate(snapshot.rigs, start=1):
            print(f"{index:>4}  {rig.name}")
        return 0
    if args.json:
        print(
            json.dumps(
                {
                    "appVersion": snapshot.identity.app_version,
                    "deviceName": snapshot.identity.device_name,
                    "product": snapshot.identity.product,
                    "loadedRig": {
                        "id": snapshot.loaded_rig.rig_id,
                        "name": snapshot.loaded_rig.name,
                        "programChange": snapshot.loaded_rig.program_change,
                    },
                    "rigCount": len(snapshot.rigs),
                    "cpuPercent": round(snapshot.cpu_percent, 1),
                    "assignedProgramChanges": list(snapshot.assigned_program_changes),
                    "midi": snapshot.midi_settings,
                    "chain": [
                        {"slot": s.slot, "module": s.module_name, "cc": 74 + s.slot}
                        for s in snapshot.chain
                    ],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
        return 0

    print(_format_snapshot(snapshot))
    return 0


def catalog_main(argv: list[str] | None = None) -> int:
    """Probe the device and write its versioned catalog artifact.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        Process exit code.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_catalog_dump",
        description="Génère le catalogue complet du HeadRush Core depuis l'appareil.",
    )
    _add_host_argument(parser)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=_REPO_ROOT / "data",
        help="racine data/ du dépôt (défaut : celle du dépôt courant)",
    )
    parser.add_argument("--out", type=Path, default=None, help="chemin de sortie explicite")
    parser.add_argument(
        "--no-categories",
        action="store_true",
        help="ne pas résoudre catégorie → blocs (évite 21 appels de méthode)",
    )
    args = parser.parse_args(argv)

    client = CoreClient(args.host, timeout=120.0)
    try:
        catalog = build_catalog(client, with_categories=not args.no_categories)
    except DeviceError as exc:
        print(f"erreur : {exc}")
        return 1

    destination = args.out or catalog_path(args.data_root, catalog)
    write_catalog(catalog, destination)

    enum_params = sum(1 for b in catalog.blocks for p in b.params if p.is_enum)
    unsafe = sum(1 for b in catalog.blocks for p in b.params if not p.is_writable_safely)
    print(f"catalogue écrit : {destination}")
    print(f"  firmware       : {catalog.app_version}  ({catalog.product})")
    print(f"  contractHash   : {catalog.contract_hash[:16]}…")
    print(f"  module types   : {len(catalog.module_types)}")
    print(f"  catégories     : {len(catalog.categories)}")
    print(f"  blocs          : {len(catalog.blocks)}")
    print(f"  paramètres     : {sum(len(b.params) for b in catalog.blocks)}")
    print(f"  énumérations   : {enum_params}")
    print(f"  non écrivables : {unsafe}  (readOnly ou normalizeAlgo=3 DelayRatio)")
    return 0


def backup_main(argv: list[str] | None = None) -> int:
    """Snapshot the loaded rig, or diff two previously written snapshots.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        Process exit code. ``1`` on device error, ``2`` when a diff found
        differences (so it composes in a shell).
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_backup",
        description="Sauvegarde lecture seule du rig chargé, ou diff de deux sauvegardes.",
    )
    _add_host_argument(parser)
    parser.add_argument(
        "--data-root",
        type=Path,
        default=_REPO_ROOT / "data",
        help="racine data/ du dépôt (défaut : celle du dépôt courant)",
    )
    parser.add_argument("--out", type=Path, default=None, help="chemin de sortie explicite")
    parser.add_argument(
        "--diff",
        nargs=2,
        type=Path,
        metavar=("AVANT", "APRÈS"),
        help="comparer deux sauvegardes au lieu d'en prendre une",
    )
    args = parser.parse_args(argv)

    if args.diff:
        before, after = (load_snapshot(path) for path in args.diff)
        changes = diff_snapshots(before, after)
        if not changes:
            print("identique — aucune différence")
            return 0
        print(f"{len(changes)} différence(s) :")
        for change in changes:
            print(f"  {change}")
        return 2

    client = CoreClient(args.host, timeout=60.0)
    try:
        snapshot = capture_rig(client)
    except DeviceError as exc:
        print(f"erreur : {exc}")
        return 1

    destination = args.out or default_snapshot_path(args.data_root, snapshot)
    write_snapshot(snapshot, destination)

    params = sum(len(values) for values in snapshot.blocks.values())
    print(f"sauvegarde écrite : {destination}")
    print(f"  rig            : {snapshot.rig_name!r}  ({snapshot.rig_id})")
    print(f"  firmware       : {snapshot.identity.app_version}")
    print(f"  slots occupés  : {len(snapshot.occupied_slots)}/14")
    print(f"  blocs capturés : {len(snapshot.blocks)}")
    print(f"  paramètres     : {params}")
    print(f"  CPU            : {snapshot.cpu_percent:.0f} %")
    if snapshot.unresolved_modules:
        print(f"  /!\ modules non résolus : {', '.join(snapshot.unresolved_modules)}")
    return 0


def plan_main(argv: list[str] | None = None) -> int:
    """Build and print a write plan from a binding document, without touching the device.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        ``0`` when the plan is applicable, ``2`` when it carries errors.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_plan",
        description="Construit hors ligne le plan d'écriture d'un rig, sans toucher l'appareil.",
    )
    parser.add_argument("binding", type=Path, help="document fretwise.device.binding.v1")
    parser.add_argument(
        "--catalog",
        type=Path,
        default=None,
        help="catalogue à utiliser (défaut : le plus récent sous data/devices/headrush-core)",
    )
    parser.add_argument("--json", action="store_true", help="émettre le plan en JSON")
    args = parser.parse_args(argv)

    catalog_file = args.catalog
    if catalog_file is None:
        folder = _REPO_ROOT / "data" / "devices" / "headrush-core" / "catalog"
        candidates = sorted(folder.glob("*.json"))
        if not candidates:
            print(f"erreur : aucun catalogue dans {folder} — lancer device_catalog_dump.py")
            return 1
        catalog_file = candidates[-1]

    catalog = load_catalog(catalog_file)
    try:
        binding = load_binding(args.binding)
    except (PlanError, OSError, ValueError) as exc:
        print(f"erreur : {exc}")
        return 1

    plan = build_plan(binding, catalog)
    if args.json:
        print(
            json.dumps(
                {
                    "rig": plan.rig_name,
                    "programChange": plan.program_change,
                    "appVersion": plan.app_version,
                    "applicable": plan.is_applicable,
                    "chain": [
                        {"slot": p.slot, "module": p.module, "cc": p.bypass_cc}
                        for p in plan.placements
                    ],
                    "steps": [
                        {"kind": s.kind, "path": s.path, "method": s.method, "payload": s.payload}
                        for s in plan.steps
                    ],
                    "warnings": plan.warnings,
                    "errors": plan.errors,
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(plan.render())
    return 0 if plan.is_applicable else 2


def push_main(argv: list[str] | None = None) -> int:
    """Apply a binding to the device. Simulates unless every lock is opened.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        ``0`` on success, ``1`` on a device or gate error, ``2`` when a read-back
        mismatch was found.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_push",
        description=(
            "Applique un rig sur le HeadRush Core. SIMULE par defaut : l'ecriture "
            "exige la variable d'environnement, --confirm, et --apply."
        ),
    )
    parser.add_argument("binding", type=Path, help="document fretwise.device.binding.v1")
    _add_host_argument(parser)
    parser.add_argument("--catalog", type=Path, default=None, help="catalogue a utiliser")
    parser.add_argument("--apply", action="store_true", help="ecrire reellement (verrou 3/3)")
    parser.add_argument("--confirm", action="store_true", help="confirmation explicite (2/3)")
    parser.add_argument("--token", default=None, help="jeton du plan relu (verrou anti-course)")
    parser.add_argument("--save", action="store_true", help="appeler saveRig apres verification")
    args = parser.parse_args(argv)

    catalog_file = args.catalog
    if catalog_file is None:
        folder = _REPO_ROOT / "data" / "devices" / "headrush-core" / "catalog"
        candidates = sorted(folder.glob("*.json"))
        if not candidates:
            print(f"erreur : aucun catalogue dans {folder}")
            return 1
        catalog_file = candidates[-1]

    catalog = load_catalog(catalog_file)
    try:
        plan = build_plan(load_binding(args.binding), catalog)
    except (PlanError, OSError, ValueError) as exc:
        print(f"erreur : {exc}")
        return 1

    if not plan.is_applicable:
        print(plan.render())
        return 2

    client = CoreWriteClient(args.host, timeout=30.0)
    try:
        before = summarize_state(client)
        report = apply_plan(
            plan,
            catalog,
            client,
            dry_run=not args.apply,
            confirm=args.confirm,
            confirm_token=args.token,
            save=args.save,
        )
    except DeviceError as exc:
        print(f"refuse : {exc}")
        return 1

    print(report.render())
    print()
    print(f"  jeton du plan : {plan_token(plan)}")
    if not args.apply:
        print("  (simulation — relancer avec --apply --confirm pour ecrire)")
    else:
        print()
        print(f"  avant : {before}")
        print(f"  apres : {summarize_state(client)}")
    return 0 if report.ok else 2


def prompt_main(argv: list[str] | None = None) -> int:
    """Emit an LLM prompt for a song, or ingest the response pasted back.

    FretWise calls no provider: the prompt goes to whatever LLM the user already
    has open, and the JSON comes back through ``--ingest``.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        ``0`` on success, ``1`` on error, ``2`` when a pasted response is refused.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_prompt",
        description=(
            "Genere le prompt LLM d'un rig HeadRush Core, ou valide la reponse collee. "
            "Aucun appel API : le prompt est contraint par le catalogue reel de l'appareil."
        ),
    )
    parser.add_argument("artist", help="artiste")
    parser.add_argument("title", help="titre")
    parser.add_argument("--catalog", type=Path, default=None, help="catalogue a utiliser")
    parser.add_argument(
        "--ingest",
        type=Path,
        default=None,
        metavar="FICHIER",
        help="valider la reponse collee (fichier, ou - pour l'entree standard)",
    )
    parser.add_argument("--out", type=Path, default=None, help="ou ecrire le binding valide")
    parser.add_argument("--guidance", default="", help="consigne libre ajoutee au prompt")
    parser.add_argument(
        "--existing", type=Path, default=None, help="binding a corriger plutot qu'a recreer"
    )
    args = parser.parse_args(argv)

    catalog_file = args.catalog
    if catalog_file is None:
        folder = _REPO_ROOT / "data" / "devices" / "headrush-core" / "catalog"
        candidates = sorted(folder.glob("*.json"))
        if not candidates:
            print(f"erreur : aucun catalogue dans {folder} — lancer device_catalog_dump.py")
            return 1
        catalog_file = candidates[-1]
    catalog = load_catalog(catalog_file)

    if args.ingest is None:
        existing = None
        if args.existing is not None:
            existing = json.loads(args.existing.read_text(encoding="utf-8"))
        print(
            build_rig_prompt(
                args.artist, args.title, catalog, existing=existing, guidance=args.guidance
            )
        )
        return 0

    raw = sys.stdin.read() if str(args.ingest) == "-" else args.ingest.read_text(encoding="utf-8")
    try:
        binding, warnings = parse_rig_response(
            raw, catalog, artist=args.artist, title=args.title
        )
    except PromptError as exc:
        print(f"refuse : {exc}")
        return 2

    destination = args.out
    if destination is None:
        key = gears_key(args.artist, args.title)
        destination = _REPO_ROOT / "data" / "devices" / "headrush-core" / "rigs" / f"{key}.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(binding, indent=1, ensure_ascii=False) + chr(10), encoding="utf-8"
    )
    print(f"binding valide ecrit : {destination}")
    print(f"  rig    : {binding.get('rig', {}).get('name')}")
    print(f"  blocs  : {len(binding.get('blocks', []))}")
    for w in warnings:
        print(f"  note   : {w}")
    print()
    print("  etape suivante :")
    print(f"    pixi run python scripts/device_plan.py {destination}")
    return 0


def provision_main(argv: list[str] | None = None) -> int:
    """Push a binding and make it a named rig in the library.

    Creates on first run (sandbox -> ``saveRigAs``), updates in place afterwards
    (load the song's GUID -> mutate -> ``saveRig``). The distinction matters:
    ``saveRigAs`` mints a new GUID every time, so using it to update would leave a
    duplicate rig on the device at each regeneration.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        ``0`` on success, ``1`` on a device or gate error, ``2`` on a read-back
        mismatch or a refused plan.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_provision",
        description=(
            "Ecrit un binding sur l'appareil et le promeut en rig nomme. "
            "SIMULE par defaut : --apply --confirm pour ecrire."
        ),
    )
    parser.add_argument("binding", type=Path, help="document fretwise.device.binding.v1")
    _add_host_argument(parser)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument("--data-root", type=Path, default=_REPO_ROOT / "data")
    parser.add_argument("--apply", action="store_true", help="ecrire reellement")
    parser.add_argument("--confirm", action="store_true", help="confirmation explicite")
    parser.add_argument("--pc", type=int, default=None, help="Program Change a assigner")
    parser.add_argument("--colour", type=int, default=-1, help="couleur du rig sur l'ecran")
    args = parser.parse_args(argv)

    catalog_file = args.catalog
    if catalog_file is None:
        folder = _REPO_ROOT / "data" / "devices" / "headrush-core" / "catalog"
        found = sorted(folder.glob("*.json"))
        if not found:
            print(f"erreur : aucun catalogue dans {folder}")
            return 1
        catalog_file = found[-1]
    catalog = load_catalog(catalog_file)

    try:
        document = load_binding(args.binding)
    except (PlanError, OSError, ValueError) as exc:
        print(f"erreur : {exc}")
        return 1
    plan = build_plan(document, catalog)
    if not plan.is_applicable:
        print(plan.render())
        return 2

    song = document.get("song") or {}
    artist = str(song.get("artist") or "")
    title = str(song.get("title") or "")
    if not artist and not title:
        print("erreur : le binding n'a pas de bloc 'song' (artist/title)")
        return 1

    store = BindingStore.load(default_store_path(args.data_root))
    known = store.get(artist, title)
    mode = provision_mode(document, known, args.pc)
    labels = {
        "create": "creation (depuis " + SANDBOX_NAME + ")",
        "update": "mise a jour",
        "unchanged": "inchange",
        "program_change": "Program Change seul",
    }

    print(f"{labels[mode].upper()} — {artist} — {title}")
    print(f"  rig cible : {plan.rig_name}")
    if known:
        print(f"  rig existant : {known.rig_id} ({known.rig_name})")
    if mode == "unchanged":
        print("  binding inchange depuis la derniere ecriture — rien a faire")
        return 0
    if not args.apply:
        print(plan.render())
        print()
        print("  (simulation — relancer avec --apply --confirm)")
        return 0

    client = CoreWriteClient(args.host, timeout=30.0)
    try:
        result = provision_rig(
            document,
            catalog,
            client,
            store,
            known=known,
            confirm=args.confirm,
            program_change=args.pc,
            colour=args.colour,
        )
    except DeviceError as exc:
        print(f"refuse : {exc}")
        return 1

    if result.report is not None:
        print(result.report.render())
    if not result.ok:
        return 2
    print()
    print(f"  rig      : {result.rig_name}")
    print(f"  GUID     : {result.rig_id}")
    print(f"  MIDI PROG: {result.program_change if result.program_change is not None else '—'}")
    print(f"  table    : {store.path}")
    return 0


def images_main(argv: list[str] | None = None) -> int:
    """Download every block picture the Core serves into the local cache. Read-only.

    Optional: the web apps fetch pictures on first use anyway. Prefetching makes
    them available while the device is switched off.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        ``0`` on success, ``1`` when the device cannot be reached.
    """
    _configure_stdout()
    parser = argparse.ArgumentParser(
        prog="device_images",
        description=(
            "Recupere les images des blocs (pedales, amplis, baffles) servies par le "
            "HeadRush Core, dans un cache local. Lecture seule."
        ),
    )
    _add_host_argument(parser)
    parser.add_argument("--catalog", type=Path, default=None)
    parser.add_argument(
        "--out",
        type=Path,
        default=_REPO_ROOT / "data" / "devices" / "headrush-core" / "images",
        help="dossier du cache (defaut : celui de l'app en local)",
    )
    args = parser.parse_args(argv)

    catalog_file = args.catalog
    if catalog_file is None:
        folder = _REPO_ROOT / "data" / "devices" / "headrush-core" / "catalog"
        found = sorted(folder.glob("*.json"))
        if not found:
            print(f"erreur : aucun catalogue dans {folder}")
            return 1
        catalog_file = found[-1]
    catalog = load_catalog(catalog_file)

    client = CoreClient(args.host, timeout=15.0)
    cache = ImageCache(args.out)
    relpaths = all_image_relpaths(catalog)
    cached = fetched = missing = 0
    for relpath in relpaths:
        if cache.get(relpath) is not None:
            cached += 1
            continue
        if cache.fetch(relpath, client.file) is not None:
            fetched += 1
        elif cache.offline:
            print(f"erreur : {client.host} injoignable — {fetched} images recuperees avant")
            return 1
        else:
            missing += 1
    print(f"{len(relpaths)} images attendues — {fetched} recuperees, {cached} deja en cache, "
          f"{missing} absentes de l'appareil")
    print(f"  cache : {args.out}")
    return 0
