"""Web routes for the multi-effects unit FretWise drives.

Registered from :func:`fretwise.web.app.create_app` rather than living in
``app.py``, which is already 195 KB.

Only the **device-independent** half is exposed here: listing the units FretWise
knows, building the copy-paste LLM prompt for a song, and validating the JSON the
user pastes back. All three work from the catalog artifact shipped in the image,
so they need no network access to the instrument.

Driving the hardware is deliberately **not** exposed. The Core's local API has no
authentication, so a route that proxied writes would turn a FretWise instance into
an open door onto someone's amplifier. Writing stays in
``scripts/device_push.py``, which runs on the machine that owns the instrument and
carries its own confirmation gates.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, Response

from fretwise.devices.headrush_core.catalog import Catalog, load_catalog
from fretwise.devices.headrush_core.prompt import (
    PromptError,
    build_rig_prompt,
    parse_rig_response,
)
from fretwise.web.settings import GEAR_DEVICES

#: Repository (or image) root: ``src/fretwise/web/device_routes.py`` -> root.
_ROOT = Path(__file__).resolve().parents[3]

#: Where ``device_catalog_dump.py`` writes, and where the image finds it.
_CATALOG_DIR = _ROOT / "data" / "devices" / "headrush-core" / "catalog"

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


def register_device_routes(app: FastAPI, require_admin: Any) -> None:
    """Mount the device routes on ``app``.

    Args:
        app: The FastAPI application.
        require_admin: ``app.py``'s guard, passed in rather than imported to keep
            this module free of a circular import.
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
        text = build_rig_prompt(artist, title, catalog, guidance=guidance)
        return Response(
            content=text,
            media_type="text/markdown; charset=utf-8",
            headers={
                "Content-Disposition": 'inline; filename="fretwise-headrush-prompt.md"',
                "X-FretWise-Device": "headrush_core",
                "X-FretWise-App-Version": catalog.app_version,
                "Cache-Control": "no-store",
            },
        )

    @app.post("/api/devices/headrush/ingest")
    async def headrush_ingest(request: Request) -> JSONResponse:
        """Validate the JSON pasted back from the user's LLM.

        Returns the usable binding, or 422 with the reasons the device would have
        refused it. Nothing is written to the instrument here.
        """
        require_admin(app)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body") from None
        raw = body.get("response")
        if not isinstance(raw, (str, dict)) or not raw:
            raise HTTPException(400, "champ 'response' requis (texte collé ou objet)")

        catalog = _load_headrush_catalog()
        try:
            binding, warnings = parse_rig_response(
                raw,
                catalog,
                artist=str(body.get("artist") or ""),
                title=str(body.get("title") or ""),
            )
        except PromptError as exc:
            return JSONResponse(
                status_code=422,
                content={"code": "rig_refused", "detail": str(exc)},
            )
        return JSONResponse(
            {
                "binding": binding,
                "warnings": warnings,
                "rig": binding.get("rig", {}).get("name"),
                "blocks": len(binding.get("blocks", [])),
                "suggestedFilename": _suggested_filename(binding),
            }
        )


def _suggested_filename(binding: dict[str, Any]) -> str:
    """Return the canonical on-disk name for a binding, from the song key."""
    from fretwise.gears.naming import gears_key

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
