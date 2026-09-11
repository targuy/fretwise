"""Web routes for the multi-effects unit FretWise drives.

Registered from :func:`fretwise.web.app.create_app` rather than living in
``app.py``, which is already 195 KB.

What is exposed: listing the units FretWise knows, building the copy-paste LLM
prompt for a song, validating the JSON the user pastes back, storing the
validated rig, reading it back laid out slot by slot for the Rig panel, and —
behind an admin check and an explicit opt-in — creating or updating that rig on
the instrument itself.

The Core's local API has no authentication, so the write route is fenced on the
FretWise side: ``headrush_allow_write`` must be switched on in the settings (off by
default), the caller must be an admin, every push is a preview followed by a
confirmed apply carrying the previewed plan token, and the applier only ever
writes into rigs named ``#FW - …``. The device address is a setting validated as a
bare host, so the server cannot be pointed at an arbitrary URL.
"""

from __future__ import annotations

import json
import re
import threading
import urllib.parse
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from fretwise.devices.headrush_core.bindings import BindingStore
from fretwise.devices.headrush_core.catalog import Catalog, load_catalog
from fretwise.devices.headrush_core.client import (
    CoreClient,
    CoreWriteClient,
    DeviceError,
    DeviceWriteTransport,
)
from fretwise.devices.headrush_core.images import ImageCache, image_relpath, image_variant
from fretwise.devices.headrush_core.plan import GENERATED_PREFIX, build_plan
from fretwise.devices.headrush_core.prompt import (
    PromptError,
    build_rig_prompt,
    parse_rig_response,
)
from fretwise.devices.headrush_core.provision import (
    SANDBOX_NAME,
    find_known,
    load_rig,
    provision_mode,
    provision_rig,
    suggest_program_change,
)
from fretwise.devices.headrush_core.pusher import (
    DeviceBusy,
    WriteRefused,
    plan_token,
    write_allowed,
)
from fretwise.gears.naming import gears_key
from fretwise.web.settings import DEFAULT_HEADRUSH_HOST, GEAR_DEVICES

#: Repository (or image) root: ``src/fretwise/web/device_routes.py`` -> root.
_ROOT = Path(__file__).resolve().parents[3]

#: Device data shipped with the code: catalog, and rigs committed to the repo.
_BUNDLED_DIR = _ROOT / "data" / "devices" / "headrush-core"

#: Where ``device_catalog_dump.py`` writes, and where the image finds it.
_CATALOG_DIR = _BUNDLED_DIR / "catalog"

_catalog_cache: dict[str, Catalog] = {}


def _load_headrush_catalog() -> Catalog:
    """Return the newest catalog artifact, cached.

    Raises:
        HTTPException: No catalog has been generated yet — the device has never
            been probed from this machine.
    """
    candidates = sorted(_CATALOG_DIR.glob("*.json"))
    if not candidates:
        raise HTTPException(
            503,
            {
                "code": "no_device_catalog",
                "detail": (
                    "Aucun catalogue HeadRush Core. Lancer "
                    "`scripts/device_catalog_dump.py` avec l'appareil allumé."
                ),
            },
        )
    newest = candidates[-1]
    key = f"{newest}:{newest.stat().st_mtime_ns}"
    if key not in _catalog_cache:
        _catalog_cache.clear()
        _catalog_cache[key] = load_catalog(newest)
    return _catalog_cache[key]


def _store_dir() -> Path:
    """Return where rigs validated from the UI are written.

    In production the image is rebuilt on every release, so anything written
    under ``/app/data`` would vanish at the next deploy. The one persistent
    volume the web service has for this kind of data is the gears directory
    (``FRETWISE_GEARS_DIR``, ``/data/gears`` on the NAS). Rigs go in a
    ``_devices/`` subfolder of it, which the GP-180 sheet index never sees
    because it only globs ``*.json`` at the top level. Without a configured
    gears directory (local development) they go next to the catalog, where the
    command-line tools look for them.
    """
    from fretwise.web import settings as _settings

    configured = str(_settings.get("gears_dir") or "").strip()
    if configured and Path(configured).is_dir():
        return Path(configured) / "_devices" / "headrush-core"
    return _BUNDLED_DIR


def _rig_file(artist: str, title: str) -> Path:
    """Return the store path for one song's rig, keyed like every gears file.

    ``gears_key`` slugifies both halves, so the result is always a plain file
    name — no separator or ``..`` can reach the path from the request.
    """
    return _store_dir() / "rigs" / f"{gears_key(artist, title)}.json"


def _read_rig(artist: str, title: str) -> tuple[dict[str, Any] | None, str]:
    """Return ``(binding, source)`` for a song: the store first, then the image."""
    key = gears_key(artist, title)
    for source, base in (("store", _store_dir()), ("image", _BUNDLED_DIR)):
        path = base / "rigs" / f"{key}.json"
        if not path.is_file():
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(document, dict):
            return document, source
    return None, ""


def _provisioned(artist: str, title: str) -> dict[str, Any] | None:
    """Return the device-side record for a song, when it has been pushed.

    Written by ``scripts/device_provision.py`` on the machine that owns the
    instrument; the web service only reads it.
    """
    seen: set[Path] = set()
    for base in (_store_dir(), _BUNDLED_DIR):
        path = base / "bindings.json"
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        try:
            entry = BindingStore.load(path).get(artist, title)
        except (OSError, ValueError):
            continue
        if entry is not None:
            return {
                "rigId": entry.rig_id,
                "rigName": entry.rig_name,
                "programChange": entry.program_change,
                "updatedAt": entry.updated_at,
            }
    return None


_image_caches: dict[Path, ImageCache] = {}


def _image_cache() -> ImageCache:
    """Return the block-picture cache, next to the rig store (persistent in prod)."""
    directory = _store_dir() / "images"
    if directory not in _image_caches:
        _image_caches[directory] = ImageCache(directory)
    return _image_caches[directory]


def _image_url(module: str, params: dict[str, Any]) -> str:
    """Return the app URL of a block's picture (amp and cab pictures follow the model)."""
    query = {"module": module}
    variant = image_variant(module, params)
    if variant:
        query["variant"] = variant
    return "/api/devices/headrush/block-image?" + urllib.parse.urlencode(query)


def _rig_view(binding: dict[str, Any], catalog: Catalog) -> dict[str, Any]:
    """Lay a binding out the way the device will: one entry per slot, with its CC."""
    plan = build_plan(binding, catalog)
    params_by_module: dict[str, dict[str, Any]] = {}
    why_by_module: dict[str, str] = {}
    for block in binding.get("blocks") or []:
        if not isinstance(block, dict):
            continue
        module = str(block.get("module", ""))
        params = block.get("params")
        params_by_module[module] = params if isinstance(params, dict) else {}
        why_by_module[module] = str(block.get("why") or "")
    tone = binding.get("tone")
    sources = binding.get("sources")
    return {
        "rig": plan.rig_name,
        "applicable": plan.is_applicable,
        "errors": list(plan.errors),
        "warnings": list(plan.warnings),
        "confidence": binding.get("confidence"),
        "tone": tone if isinstance(tone, dict) else None,
        "sources": sources if isinstance(sources, list) else [],
        "blocks": [
            {
                "slot": placement.slot,
                "cc": placement.bypass_cc,
                "module": placement.module,
                "category": placement.category,
                "params": params_by_module.get(placement.module, {}),
                "why": why_by_module.get(placement.module, ""),
                "image": _image_url(placement.module, params_by_module.get(placement.module, {})),
            }
            for placement in plan.placements
        ],
    }


#: A host name or IP literal, optionally with a port — nothing that could carry a
#: path, a scheme or credentials into the URL the server builds.
_HOST_RE = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9.-]{0,251}[A-Za-z0-9])?(?::\d{1,5})?$")

#: One write at a time: the device has no transaction, and two interleaved
#: provisioning runs would each read back the other's writes.
_push_lock = threading.Lock()

def make_read_client(host: str) -> CoreClient:
    """Return a read-only client; replaced in tests by an in-memory fake."""
    return CoreClient(host, timeout=5.0)


def make_write_client(host: str) -> DeviceWriteTransport:
    """Return a write-capable client; replaced in tests by an in-memory fake."""
    return CoreWriteClient(host, timeout=30.0)


def _configured_host() -> str:
    """Return the Core's address from the settings, falling back to the default.

    An empty value (a config file written before the setting had a default)
    falls back too, rather than meaning "no device".
    """
    from fretwise.web import settings as _settings

    return str(_settings.get("headrush_host") or "").strip() or DEFAULT_HEADRUSH_HOST


def _core_host() -> str:
    """Return the configured address, refusing anything that is not a bare host."""
    host = _configured_host()
    if not _HOST_RE.match(host):
        raise HTTPException(
            400,
            {
                "code": "invalid_device_host",
                "detail": f"adresse HeadRush invalide : {host!r} "
                "(attendu : IP ou nom, port optionnel)",
            },
        )
    return host


def _write_enabled() -> bool:
    """Return whether this installation may write to the Core (lock 1)."""
    from fretwise.web import settings as _settings

    return write_allowed(bool(_settings.get("headrush_allow_write")))


def is_valid_host(host: str) -> bool:
    """Return True for a bare host name or IP literal, optionally with a port."""
    return bool(_HOST_RE.match(host))


def device_settings() -> dict[str, Any]:
    """Return the Core address and the write opt-in, as a settings UI shows them."""
    from fretwise.web import settings as _settings

    return {
        "host": _configured_host(),
        "writeEnabled": _write_enabled(),
        "allowWriteSetting": bool(_settings.get("headrush_allow_write")),
        "sandbox": SANDBOX_NAME,
    }


async def _json_body(request: Request) -> dict[str, Any]:
    """Return a request's JSON object body, or raise 400."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Invalid JSON body") from None
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid JSON body")
    return body


def _binding_stores() -> list[BindingStore]:
    """Return the song tables to consult: the persistent one first, then the image's."""
    stores: list[BindingStore] = []
    seen: set[Path] = set()
    for base in (_store_dir(), _BUNDLED_DIR):
        path = base / "bindings.json"
        if path in seen:
            continue
        seen.add(path)
        try:
            stores.append(BindingStore.load(path))
        except (OSError, ValueError):
            continue
    return stores


def _read_device(host: str, catalog: Catalog) -> dict[str, Any]:
    """Read what a push depends on from the device. Never raises."""
    try:
        client = make_read_client(host)
        gui = client.properties("/Evil/Gui")
        rigs = client.properties("/Evil/API/Rigs")
        dialog = client.properties("/Evil/API/RigSaveDialog")
    except DeviceError as exc:
        return {"reachable": False, "detail": str(exc)}
    names = [str(n) for n in (rigs.get("AllRigNames") or [])]
    app_version = str(gui.get("AppVersion", ""))
    available = rigs.get("availableProgMIDICC") or []
    return {
        "reachable": True,
        "appVersion": app_version,
        "deviceName": str(gui.get("DeviceName", "")),
        "firmwareMatches": app_version == catalog.app_version,
        "loadedRig": str(rigs.get("loadedName", "")),
        "loadedDirty": bool(rigs.get("dirty")),
        "saveDialogOpen": bool(dialog.get("displayDialog")),
        "sandboxPresent": SANDBOX_NAME in names,
        "rigCount": len(names),
        "availableProgramChanges": [int(pc) for pc in available if isinstance(pc, int)],
    }


def _song_document(binding: dict[str, Any], artist: str, title: str) -> dict[str, Any]:
    """Return the binding keyed by the song open in the UI.

    The song table is looked up with the UI's artist and title; a model that
    spelled the artist differently in ``song`` would otherwise record the rig
    under a key the Rig panel never asks for.
    """
    song = dict(binding.get("song") or {})
    song.update({"artist": artist, "title": title})
    return {**binding, "song": song}


def _program_change(raw: Any) -> int | None:
    """Parse the optional Program Change of a push request."""
    if raw is None or raw == "":
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        raise HTTPException(400, "programChange doit être un entier 0..127") from None
    if not 0 <= value <= 127:
        raise HTTPException(400, "programChange doit être un entier 0..127")
    return value


def list_stored_rigs() -> list[dict[str, Any]]:
    """Return every song with a stored rig — the persistent store first, then the image.

    Files whose name starts with ``_`` (``_exemple.json``) are documentation, not
    songs, and are skipped.
    """
    found: dict[str, dict[str, Any]] = {}
    for source, base in (("store", _store_dir()), ("image", _BUNDLED_DIR)):
        for path in sorted((base / "rigs").glob("*.json")):
            if path.name.startswith("_") or path.stem in found:
                continue
            try:
                document = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if not isinstance(document, dict):
                continue
            song = document.get("song") or {}
            artist = str(song.get("artist") or "")
            title = str(song.get("title") or "")
            if not artist and not title:
                continue
            found[path.stem] = {
                "key": path.stem,
                "artist": artist,
                "title": title,
                "rig": str((document.get("rig") or {}).get("name") or ""),
                "blocks": len(document.get("blocks") or []),
                "source": source,
                "provisioned": _provisioned(artist, title),
            }
    return sorted(found.values(), key=lambda r: (r["artist"].lower(), r["title"].lower()))


def _provision_command(artist: str, title: str) -> str:
    """Return the command that pushes a stored rig from the instrument's machine."""
    return (
        "pixi run python scripts/device_provision.py "
        f"data/devices/headrush-core/rigs/{gears_key(artist, title)}.json "
        "--apply --confirm --pc <numero>"
    )


def register_device_routes(app: FastAPI, require_admin: Any) -> None:
    """Mount the device routes on ``app``.

    Args:
        app: The FastAPI application.
        require_admin: ``app.py``'s guard, passed in rather than imported to keep
            this module free of a circular import. Storing a rig is gated by
            authentication alone, like the GP-180 "validate and save" flow;
            writing to the instrument is admin-only.
    """

    @app.get("/api/devices")
    async def list_devices() -> JSONResponse:
        """List the units FretWise can drive, and which one is selected.

        The two are not interchangeable — the GP-180 is reached by MIDI Program
        Change from this machine, the Core only over HTTP — so the UI uses this
        to show one set of controls rather than both.
        """
        from fretwise.web import settings as _settings

        active = str(_settings.get("gear_device") or "valeton_gp180")
        catalogued = _CATALOG_DIR.exists() and any(_CATALOG_DIR.glob("*.json"))
        return JSONResponse(
            {
                "active": active,
                "devices": [
                    {
                        "id": device_id,
                        **info,
                        "catalogAvailable": catalogued if device_id == "headrush_core" else None,
                    }
                    for device_id, info in GEAR_DEVICES.items()
                ],
                "headrush": {
                    "host": _configured_host(),
                    "writeEnabled": _write_enabled(),
                    "sandbox": SANDBOX_NAME,
                },
            }
        )

    @app.get("/api/devices/headrush/catalog")
    async def headrush_catalog_summary() -> JSONResponse:
        """Summarise the catalog the prompt is built from."""
        catalog = _load_headrush_catalog()
        amp = catalog.block("Amp")
        amp_type = amp.param("Type") if amp else None
        return JSONResponse(
            {
                "appVersion": catalog.app_version,
                "product": catalog.product,
                "deviceName": catalog.device_name,
                "contractHash": catalog.contract_hash,
                "moduleTypes": len(catalog.module_types),
                "blocks": len(catalog.blocks),
                "ampModels": len(amp_type.options) if amp_type else 0,
                "categories": list(catalog.categories),
            }
        )

    @app.get("/api/devices/headrush/prompt")
    async def headrush_prompt(artist: str, title: str, guidance: str = "") -> Response:
        """Serve the copy-paste prompt for one song.

        FretWise calls no LLM provider: this is the text the user pastes into
        whatever model they already have open. It is generated from the device's
        own catalog, so every block name and enumeration label in it is real.
        """
        if not artist.strip() and not title.strip():
            raise HTTPException(400, "artist ou title requis")
        catalog = _load_headrush_catalog()
        existing, _ = _read_rig(artist, title)
        text = build_rig_prompt(artist, title, catalog, existing=existing, guidance=guidance)
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'inline; filename="fretwise-headrush-prompt.md"',
                "X-FretWise-Device": "headrush_core",
                "X-FretWise-App-Version": catalog.app_version,
                "X-FretWise-Prompt-Mode": "verify" if existing else "create",
                "Cache-Control": "no-store",
            },
        )

    @app.get("/api/devices/headrush/rig")
    async def headrush_rig(artist: str = "", title: str = "") -> JSONResponse:
        """Return the HeadRush rig stored for a song, laid out slot by slot.

        ``binding`` is null when no rig has been validated for this song yet — the
        Rig panel then invites the user to create one. ``provisioned`` says
        whether the rig has actually been pushed to the instrument.
        """
        if not artist.strip() and not title.strip():
            raise HTTPException(400, "artist ou title requis")
        binding, source = _read_rig(artist, title)
        view = _rig_view(binding, _load_headrush_catalog()) if binding else None
        return JSONResponse(
            {
                "artist": artist,
                "title": title,
                "key": gears_key(artist, title),
                "binding": binding,
                "source": source or None,
                "view": view,
                "provisioned": _provisioned(artist, title),
                "provisionCommand": _provision_command(artist, title),
                "push": {"host": _configured_host(), "writeEnabled": _write_enabled()},
            }
        )

    @app.get("/api/devices/headrush/status")
    async def headrush_status() -> JSONResponse:
        """Read the Core's state: reachable, firmware, loaded rig, pending dialog.

        Read-only. Used by the settings' "test the connection" button and before
        a push, so problems are named before anything is written.
        """
        host = _core_host()
        device = await run_in_threadpool(_read_device, host, _load_headrush_catalog())
        return JSONResponse(
            {"host": host, "writeEnabled": _write_enabled(), "sandbox": SANDBOX_NAME, **device}
        )

    @app.post("/api/devices/headrush/push")
    async def headrush_push(request: Request) -> JSONResponse:
        """Create or update a song's rig on the Core, from its stored binding.

        Two calls. Without ``apply`` it is a preview: the plan, whether it will
        create or update, the device's current state, a suggested Program Change
        and the plan token. With ``"apply": true, "confirm": true, "token": ...``
        it writes — only if the installation allows writes, only for an admin,
        and only if the stored rig still matches the token that was previewed.

        Body: ``{artist, title, apply?, confirm?, token?, programChange?}``.
        """
        require_admin(app)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid JSON body")
        artist = str(body.get("artist") or "")
        title = str(body.get("title") or "")
        if not artist.strip() and not title.strip():
            raise HTTPException(400, "artist ou title requis")
        stored, _ = _read_rig(artist, title)
        if stored is None:
            raise HTTPException(
                404, {"code": "no_rig", "detail": "aucun rig HeadRush enregistré pour ce morceau"}
            )
        catalog = _load_headrush_catalog()
        document = _song_document(stored, artist, title)
        plan = build_plan(document, catalog)
        program_change = _program_change(body.get("programChange"))
        stores = _binding_stores()
        known = find_known(stores, artist, title)
        host = _core_host()
        enabled = _write_enabled()

        if not body.get("apply"):
            device = await run_in_threadpool(_read_device, host, catalog)
            assigned: set[int] = set()
            for store in stores:
                assigned |= store.assigned_program_changes()
            if known is not None and known.program_change is not None:
                suggested: int | None = known.program_change
            else:
                available = device.get("availableProgramChanges") if device["reachable"] else None
                suggested = suggest_program_change(assigned, available)
            return JSONResponse(
                {
                    "mode": provision_mode(document, known, program_change),
                    "rig": plan.rig_name,
                    "applicable": plan.is_applicable,
                    "errors": list(plan.errors),
                    "warnings": list(plan.warnings),
                    "steps": [step.describe for step in plan.steps],
                    "token": plan_token(plan),
                    "known": (
                        {
                            "rigId": known.rig_id,
                            "rigName": known.rig_name,
                            "programChange": known.program_change,
                        }
                        if known
                        else None
                    ),
                    "suggestedProgramChange": suggested,
                    "host": host,
                    "writeEnabled": enabled,
                    "sandbox": SANDBOX_NAME,
                    "device": device,
                }
            )

        if not enabled:
            raise HTTPException(
                409,
                {
                    "code": "write_disabled",
                    "detail": "écriture désactivée : cocher « Autoriser l’écriture » "
                    "dans Préférences › Pédalier",
                },
            )
        token = str(body.get("token") or "")
        if not body.get("confirm") or not token:
            raise HTTPException(400, "confirm et token (issu de l'aperçu) sont requis")
        if not _push_lock.acquire(blocking=False):
            raise HTTPException(
                409, {"code": "device_busy", "detail": "un envoi est déjà en cours"}
            )
        try:
            write_store = BindingStore.load(_store_dir() / "bindings.json")
            result = await run_in_threadpool(
                lambda: provision_rig(
                    document,
                    catalog,
                    make_write_client(host),
                    write_store,
                    known=known,
                    confirm=True,
                    confirm_token=token,
                    program_change=program_change,
                    write_enabled=enabled,
                )
            )
        except (WriteRefused, DeviceBusy) as exc:
            code = "write_refused" if isinstance(exc, WriteRefused) else "device_busy"
            raise HTTPException(409, {"code": code, "detail": str(exc)}) from exc
        except DeviceError as exc:
            raise HTTPException(
                502, {"code": "device_unreachable", "detail": f"{host} : {exc}"}
            ) from exc
        except (OSError, ValueError) as exc:
            raise HTTPException(500, f"table des rigs illisible : {exc}") from exc
        finally:
            _push_lock.release()
        return JSONResponse(result.to_json())

    @app.get("/api/devices/headrush/block-image")
    async def headrush_block_image(module: str, variant: str = "") -> Response:
        """Serve a block's picture: from the cache, else fetched once from the Core.

        ``module`` and ``variant`` are checked against the catalog before any URL
        is built. 404 when the picture is neither cached nor obtainable — the UI
        then simply shows the text.
        """
        catalog = _load_headrush_catalog()
        try:
            relpath = image_relpath(catalog, module, variant)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        cache = _image_cache()
        path = cache.get(relpath)
        if path is None:
            host = _core_host()
            path = await run_in_threadpool(
                cache.fetch, relpath, lambda url_path: make_read_client(host).file(url_path)
            )
        if path is None:
            raise HTTPException(404, "image indisponible (appareil injoignable ou sans image)")
        return FileResponse(
            path, media_type="image/webp", headers={"Cache-Control": "private, max-age=604800"}
        )

    @app.get("/api/devices/headrush/rigs")
    async def headrush_rigs() -> JSONResponse:
        """List every song with a stored HeadRush rig, and whether it is on the Core."""
        return JSONResponse({"rigs": list_stored_rigs()})

    @app.get("/api/devices/headrush/device")
    async def headrush_device() -> JSONResponse:
        """List the rigs stored on the Core, marking the ones FretWise made. Read-only."""
        host = _core_host()
        catalog = _load_headrush_catalog()

        def read() -> dict[str, Any]:
            status = _read_device(host, catalog)
            if not status["reachable"]:
                return status
            try:
                rigs = make_read_client(host).properties("/Evil/API/Rigs")
            except DeviceError as exc:
                return {"reachable": False, "detail": str(exc)}
            by_rig_id: dict[str, Any] = {}
            for store in reversed(_binding_stores()):  # the persistent table wins
                for stored_entry in store.entries.values():
                    by_rig_id[stored_entry.rig_id] = stored_entry
            loaded = str(rigs.get("loadedID", ""))
            listing: list[dict[str, Any]] = []
            ids = [str(i) for i in rigs.get("AllRigIds") or []]
            names = [str(n) for n in rigs.get("AllRigNames") or []]
            for rig_id, name in zip(ids, names):
                entry = by_rig_id.get(rig_id)
                listing.append(
                    {
                        "id": rig_id,
                        "name": name,
                        "loaded": rig_id == loaded,
                        "generated": name.startswith(GENERATED_PREFIX),
                        "song": (
                            {
                                "artist": entry.artist,
                                "title": entry.title,
                                "programChange": entry.program_change,
                            }
                            if entry
                            else None
                        ),
                    }
                )
            return {**status, "rigs": listing}

        device = await run_in_threadpool(read)
        return JSONResponse(
            {"host": host, "writeEnabled": _write_enabled(), "sandbox": SANDBOX_NAME, **device}
        )

    @app.post("/api/devices/headrush/load")
    async def headrush_load(request: Request) -> JSONResponse:
        """Load a rig on the Core, to audition it. Body: ``{rigId}``.

        Changes what the instrument is playing, so it is admin-only and subject
        to the write opt-in. Refused while a save dialog is open or the loaded rig
        has unsaved changes: the load would either discard them or be silently
        blocked behind the dialog. Nothing is saved.
        """
        require_admin(app)
        body = await _json_body(request)
        rig_id = str(body.get("rigId") or "")
        if not rig_id:
            raise HTTPException(400, "rigId requis")
        if not _write_enabled():
            raise HTTPException(
                409,
                {
                    "code": "write_disabled",
                    "detail": "écriture désactivée : l'autoriser dans les réglages",
                },
            )
        host = _core_host()

        def run() -> dict[str, Any]:
            client = make_write_client(host)
            rigs = client.properties("/Evil/API/Rigs")
            if rig_id not in [str(i) for i in rigs.get("AllRigIds") or []]:
                raise WriteRefused(f"rig {rig_id} inconnu de l'appareil")
            if client.properties("/Evil/API/RigSaveDialog").get("displayDialog"):
                raise WriteRefused(
                    "un dialogue de sauvegarde est ouvert sur l'appareil : Save ou Discard d'abord"
                )
            if rigs.get("dirty") and str(rigs.get("loadedID", "")) != rig_id:
                raise WriteRefused(
                    f"le rig chargé (« {rigs.get('loadedName')} ») a des modifications non "
                    "sauvegardées : Save ou Discard sur l'appareil d'abord"
                )
            load_rig(client, rig_id, wait_s=2.0)
            after = client.properties("/Evil/API/Rigs")
            return {
                "loadedId": str(after.get("loadedID", "")),
                "loadedName": str(after.get("loadedName", "")),
            }

        if not _push_lock.acquire(blocking=False):
            raise HTTPException(
                409, {"code": "device_busy", "detail": "une écriture est déjà en cours"}
            )
        try:
            result = await run_in_threadpool(run)
        except (WriteRefused, DeviceBusy) as exc:
            code = "write_refused" if isinstance(exc, WriteRefused) else "device_busy"
            raise HTTPException(409, {"code": code, "detail": str(exc)}) from exc
        except DeviceError as exc:
            raise HTTPException(
                502, {"code": "device_unreachable", "detail": f"{host} : {exc}"}
            ) from exc
        finally:
            _push_lock.release()
        return JSONResponse(result)

    @app.post("/api/devices/headrush/ingest")
    async def headrush_ingest(request: Request) -> JSONResponse:
        """Validate the JSON pasted back from the user's LLM, and store it.

        Returns the usable binding, or 422 with the reasons the device would have
        refused it. With ``"save": true`` the validated binding is written to the
        persistent rig store, so the Rig panel shows it from then on — the same
        contract as the GP-180 "validate and save" flow. Nothing is written to
        the instrument here.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid JSON body")
        raw = body.get("response")
        if not isinstance(raw, (str, dict)) or not raw:
            raise HTTPException(400, "champ 'response' requis (texte collé ou objet)")
        artist = str(body.get("artist") or "")
        title = str(body.get("title") or "")

        catalog = _load_headrush_catalog()
        try:
            binding, warnings = parse_rig_response(raw, catalog, artist=artist, title=title)
        except PromptError as exc:
            return JSONResponse(
                status_code=422,
                content={"code": "rig_refused", "detail": str(exc)},
            )

        saved: str | None = None
        if body.get("save"):
            if not artist.strip() and not title.strip():
                raise HTTPException(400, "artist ou title requis pour enregistrer")
            # Keyed by the song open in the UI, not by whatever the model wrote,
            # so the Rig panel and the song lists find it again under the same key.
            binding = _song_document(binding, artist, title)
            target = _rig_file(artist, title)
            try:
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(
                    json.dumps(binding, indent=1, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            except OSError as exc:
                raise HTTPException(500, f"écriture du rig impossible : {exc}") from exc
            saved = target.name

        return JSONResponse(
            {
                "binding": binding,
                "warnings": warnings,
                "rig": binding.get("rig", {}).get("name"),
                "blocks": len(binding.get("blocks", [])),
                "suggestedFilename": _suggested_filename(binding),
                "saved": saved,
                "view": _rig_view(binding, catalog),
            }
        )


def _suggested_filename(binding: dict[str, Any]) -> str:
    """Return the canonical on-disk name for a binding, from the song key."""
    song = binding.get("song") or {}
    artist = str(song.get("artist") or "")
    title = str(song.get("title") or "")
    if artist or title:
        return f"{gears_key(artist, title)}.json"
    name = str((binding.get("rig") or {}).get("name") or "rig")
    return f"{name.replace('#FW - ', '').strip().replace(' ', '_')}.json"


def catalog_is_available() -> bool:
    """Return True when a HeadRush catalog artifact exists on this machine."""
    return _CATALOG_DIR.exists() and bool(list(_CATALOG_DIR.glob("*.json")))


__all__ = ["catalog_is_available", "register_device_routes"]
