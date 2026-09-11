"""Web routes for the multi-effects unit FretWise drives.

Registered from :func:`fretwise.web.app.create_app` rather than living in
``app.py``, which is already 195 KB.

What is exposed: listing the units FretWise knows, building the copy-paste LLM
prompt for a song, validating the JSON the user pastes back, storing the
validated rig, and reading it back laid out slot by slot for the Rig panel. All
of it works from the catalog artifact shipped in the image, so none of it needs
network access to the instrument.

Driving the hardware is deliberately **not** exposed. The Core's local API has no
authentication, so a route that proxied writes would turn a FretWise instance into
an open door onto someone's amplifier. Pushing a stored rig stays in
``scripts/device_provision.py``, which runs on the machine that owns the
instrument and carries its own confirmation gates.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from fretwise.devices.headrush_core.bindings import BindingStore
from fretwise.devices.headrush_core.catalog import Catalog, load_catalog
from fretwise.devices.headrush_core.plan import build_plan
from fretwise.devices.headrush_core.prompt import (
    PromptError,
    build_rig_prompt,
    parse_rig_response,
)
from fretwise.gears.naming import gears_key
from fretwise.web.settings import GEAR_DEVICES

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
            }
            for placement in plan.placements
        ],
    }


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
            this module free of a circular import. No route here needs it today —
            storing a rig is gated like the GP-180 "validate and save" flow, i.e.
            by authentication alone — but a future route that mutates server-wide
            state must use it.
    """
    del require_admin  # accepted for the signature; see the docstring

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
            }
        )

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
            song = binding.setdefault("song", {})
            if isinstance(song, dict):
                song.setdefault("artist", artist)
                song.setdefault("title", title)
            # Keyed by the song open in the UI, not by whatever the model wrote,
            # so the Rig panel finds it again under the same score.
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
