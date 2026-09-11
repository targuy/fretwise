"""HeadRush Studio — a standalone app to design and set up HeadRush Core rigs.

FretWise's main web app does a great deal besides rigs (scores, fingerings,
playback, a library of thousands of songs). The Studio is the HeadRush part on
its own: pick or type a song, have your LLM design the rig from a prompt built
off the device's own catalog, check it slot by slot, and create it on the Core.

It runs on the machine that sits on the same LAN as the instrument, listens on
``127.0.0.1`` only, and has no login — so it guards itself differently from the
NAS deployment:

* every request must name a loopback host (or one passed with ``--allow-host``),
  which defeats DNS rebinding;
* a state-changing request carrying an ``Origin`` header must come from one of
  those hosts, which stops another web page in the same browser from posting to
  it (the plan token already makes a blind push impossible; this closes the rest).

The routes are FretWise's own device routes (:mod:`fretwise.web.device_routes`),
and the settings are the same ``~/.fretwise/config.json`` keys, so a rig designed
here shows up in FretWise and the other way round.
"""

from __future__ import annotations

import argparse
import threading
import webbrowser
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint

from fretwise.web import device_routes
from fretwise.web import settings as _settings

_STATIC = Path(__file__).resolve().parent / "static"

#: The rig view module shared with FretWise's Rig panel.
_SHARED_RIG_VIEW = Path(device_routes.__file__).resolve().parent / "static" / "js" / "headrush.js"

#: Names by which the Studio may always be reached.
LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

DEFAULT_PORT = 8765

_UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})
_WILDCARD_BINDS = frozenset({"0.0.0.0", "::"})
_NO_CACHE = {"Cache-Control": "no-store"}


def _hostname(value: str) -> str:
    """Return the host of a ``Host`` header or an ``Origin`` URL, lowercased, no port."""
    value = value.strip().lower()
    if "://" in value:
        value = value.split("://", 1)[1]
    value = value.split("/", 1)[0]
    if value.startswith("["):  # [::1]:8765
        return value[1:].split("]", 1)[0]
    if value.count(":") == 1:  # name:port; a bare IPv6 literal has several colons
        return value.rsplit(":", 1)[0]
    return value


def _local_operator(app: FastAPI) -> None:
    """Admin guard for the device routes: the Studio has one local operator.

    Reachability is what is restricted instead — see the module docstring.
    """
    del app


def create_studio_app(*, allowed_hosts: set[str] | frozenset[str] | None = None) -> FastAPI:
    """Build the Studio application.

    Args:
        allowed_hosts: Host names accepted besides the loopback ones — only needed
            when the Studio is deliberately exposed with ``--host 0.0.0.0``.

    Returns:
        The FastAPI application.
    """
    allowed = LOOPBACK_HOSTS | frozenset(h.lower() for h in (allowed_hosts or ()))
    app = FastAPI(title="HeadRush Studio", docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def local_only(request: Request, call_next: RequestResponseEndpoint) -> Response:
        """Refuse requests addressed to a foreign host, or posted from a foreign page."""
        if _hostname(request.headers.get("host", "")) not in allowed:
            return JSONResponse({"detail": "hôte non autorisé"}, status_code=403)
        origin = request.headers.get("origin")
        if (
            request.method in _UNSAFE_METHODS
            and origin is not None
            and _hostname(origin) not in allowed
        ):
            return JSONResponse({"detail": "origine non autorisée"}, status_code=403)
        return await call_next(request)

    device_routes.register_device_routes(app, _local_operator)

    @app.get("/api/studio/settings")
    async def get_settings() -> JSONResponse:
        """Return the Core address and write opt-in, and which ones the environment pins."""
        locked = sorted(
            set(_settings.environment_overrides()) & {"headrush_host", "headrush_allow_write"}
        )
        return JSONResponse({**device_routes.device_settings(), "locked": locked})

    @app.post("/api/studio/settings")
    async def update_settings(request: Request) -> JSONResponse:
        """Save the Core address and/or the write opt-in.

        Body: ``{headrush_host?: str, headrush_allow_write?: bool}``. Only these two
        keys are accepted — the Studio has no business changing FretWise's other
        settings.
        """
        try:
            body: Any = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body") from None
        if not isinstance(body, dict):
            raise HTTPException(400, "Invalid JSON body")
        updates: dict[str, Any] = {}
        if "headrush_host" in body:
            host = str(body["headrush_host"] or "").strip()
            if not device_routes.is_valid_host(host):
                raise HTTPException(
                    400,
                    {
                        "code": "invalid_device_host",
                        "detail": "adresse invalide : une IP ou un nom, port optionnel",
                    },
                )
            updates["headrush_host"] = host
        if "headrush_allow_write" in body:
            if not isinstance(body["headrush_allow_write"], bool):
                raise HTTPException(400, "headrush_allow_write doit être un booléen")
            updates["headrush_allow_write"] = body["headrush_allow_write"]
        if not updates:
            raise HTTPException(400, "rien à enregistrer")
        locked = set(updates) & set(_settings.environment_overrides())
        if locked:
            raise HTTPException(
                409, {"code": "setting_managed_by_environment", "settings": sorted(locked)}
            )
        _settings.save(updates)
        return JSONResponse(device_routes.device_settings())

    @app.get("/shared/headrush.js", include_in_schema=False)
    async def shared_rig_view() -> FileResponse:
        """Serve the rig view module shared with FretWise's Rig panel."""
        return FileResponse(_SHARED_RIG_VIEW, media_type="text/javascript", headers=_NO_CACHE)

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        """Serve the Studio page."""
        return FileResponse(_STATIC / "index.html", headers=_NO_CACHE)

    app.mount("/static", StaticFiles(directory=_STATIC), name="static")
    return app


def main(argv: list[str] | None = None) -> int:
    """Run the Studio and open it in the browser.

    Args:
        argv: Command-line arguments, excluding the program name.

    Returns:
        Process exit code.
    """
    parser = argparse.ArgumentParser(
        prog="headrush_studio",
        description=(
            "HeadRush Studio : conception et envoi des rigs HeadRush Core, "
            "en local sur ce poste."
        ),
    )
    parser.add_argument(
        "--host", default="127.0.0.1", help="interface d'écoute (défaut : ce poste seulement)"
    )
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="port (défaut : 8765)")
    parser.add_argument(
        "--allow-host",
        action="append",
        default=[],
        metavar="NOM",
        help="nom ou IP supplémentaire par lequel ouvrir l'app (avec --host 0.0.0.0)",
    )
    parser.add_argument("--no-browser", action="store_true", help="ne pas ouvrir le navigateur")
    args = parser.parse_args(argv)

    import uvicorn

    extra = set(args.allow_host)
    if args.host not in _WILDCARD_BINDS:
        extra.add(_hostname(args.host))
    exposed = args.host in _WILDCARD_BINDS or _hostname(args.host) not in LOOPBACK_HOSTS
    if exposed:
        print(
            "ATTENTION : HeadRush Studio n'a pas d'authentification. Toute machine qui "
            "atteint ce port peut écrire sur le HeadRush si l'écriture est autorisée."
        )
    shown = "127.0.0.1" if args.host in _WILDCARD_BINDS else args.host
    url = f"http://{shown}:{args.port}/"
    print(f"HeadRush Studio : {url}   (Ctrl+C pour arrêter)")
    if not args.no_browser:
        threading.Timer(1.2, webbrowser.open, args=(url,)).start()
    uvicorn.run(
        create_studio_app(allowed_hosts=extra),
        host=args.host,
        port=args.port,
        log_level="warning",
    )
    return 0


__all__ = ["DEFAULT_PORT", "LOOPBACK_HOSTS", "create_studio_app", "main"]
