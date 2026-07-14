"""FastAPI application — serves the FretWise tab viewer."""

from __future__ import annotations

import asyncio
import json as _json
import os
import re
import shutil
import threading
from collections.abc import Mapping
from datetime import date as _date
from pathlib import Path
from typing import Any

from fastapi import Body, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fretwise.audit import audit_score
from fretwise.auth.accounts import LocalAccountStore
from fretwise.auth.config import load_auth_config
from fretwise.auth.resolver import StorageNotConfigured, resolve_user_storage
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore
from fretwise.auth.web import current_request_user, setup_auth
from fretwise.biomechanics import NON_ACTIONABLE_CODES
from fretwise.config import config as _fw_config
from fretwise.control_surface import (
    build_gp180_control_surface_catalog,
    find_gp180_control_surface_action,
    profile_id_for_surface_action,
)
from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_bytes
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.notation_mode import is_valid_mode as _is_valid_notation_mode
from fretwise.export.gp_writer import (
    GPIF_CONTENT_NAME,
    fingerings_by_source_id,
    write_gp_with_fingerings,
)
from fretwise.export.musicxml_writer import render_musicxml, render_musicxml_multi
from fretwise.export.pdf_tab import render_pdf_tab
from fretwise.gears import (
    build_gear_creation_prompt,
    build_gear_verification_prompt,
    gears_key_from_filename,
    song_output_to_view,
    validate_gear_v2,
)
from fretwise.gears.naming import gears_filename as _gears_filename
from fretwise.gears.naming import gears_key as _gears_key
from fretwise.generator import StateGenerator
from fretwise.models import (
    ChordDiagram,
    Finger,
    FingeringResult,
    FingeringState,
    NoteEvent,
)
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.parser.gpif_adapter import (
    KIND_GUITAR,
    classify_kind_for_program,
)
from fretwise.patterns import PatternMatcher
from fretwise.pdf_conformance import (
    legacy_shadow_pdf_conformance_report,
)
from fretwise.pipeline import PipelineResult, run_pipeline, run_pipeline_with_guard_report
from fretwise.playback import build_performance
from fretwise.rig import (
    build_rig_index,
    default_rig_path,
    find_rig,
    find_rigs_dir,
    parse_rig,
    partition_has_rig,
    rig_view_to_markdown,
)
from fretwise.rig_bank import (
    RigBank,
    RigBankError,
    RigBinding,
    RigModule,
    RigProfile,
    RigResolution,
    list_midi_output_names,
    load_rig_bank,
    rig_bank_path,
    save_rig_bank,
    send_profile_program_change,
)
from fretwise.rig_generation import RigGenerationError, SongRigGenerationService
from fretwise.rig_pipeline import JsonFactsProvider, generate_grounded_rig
from fretwise.scoring import CostFunction, CostWeights, RulePreferences
from fretwise.storage import (
    CATALOG_NAME,
    SUPPORTED_SCORE_EXTS,
    StorageBackend,
    StorageError,
    StorageNotFoundError,
    StorageValidationError,
    build_backend,
    safe_score_name,
)
from fretwise.storage.local import LocalStorageBackend

from . import settings as _settings
from .songs_index import (
    METADATA_PROMPT,
    enrich_file_info,
    load_index,
    load_index_from_text,
    merge_catalog,
    parse_filename_metadata,
)

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"

# Score formats the web app is allowed to read, parse and serve. Every
# file-serving / parsing route is confined to this allowlist so that a
# mis-pointed ``partitions_dir`` (see ``update_settings``) can never be used
# to read arbitrary files such as ``id_rsa`` or ``/etc/passwd``. Single source
# of truth lives in :mod:`fretwise.storage`.
_SUPPORTED_SCORE_EXTS: frozenset[str] = SUPPORTED_SCORE_EXTS

# Soundfont formats accepted by the upload/activate/delete endpoints.
_SUPPORTED_SOUNDFONT_EXTS: frozenset[str] = frozenset({".sf2", ".sf3", ".dls"})

# Upload size ceilings (bytes). Uploads are streamed and rejected with HTTP 413
# once the limit is exceeded, so a single request can never exhaust memory.
# Sourced from config (web.max_score_upload_bytes / web.max_soundfont_upload_bytes).
_MAX_SCORE_UPLOAD_BYTES = int(_fw_config().web.max_score_upload_bytes)          # 50 MiB
_MAX_SOUNDFONT_UPLOAD_BYTES = int(_fw_config().web.max_soundfont_upload_bytes)  # 512 MiB

# Hostnames accepted by the Host-header guard (DNS-rebinding protection).
# Loopback-only by default; override with FRETWISE_ALLOWED_HOSTS (comma list,
# ``*`` to disable) when intentionally exposing the server on a LAN.
# Sourced from config (web.default_allowed_hosts).
_DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = tuple(_fw_config().web.default_allowed_hosts)


def _resolve_allowed_hosts(allowed_hosts: list[str] | None) -> list[str]:
    """Build the TrustedHost allowlist from arg → env → loopback default."""
    if allowed_hosts:
        return list(allowed_hosts)
    env = os.environ.get("FRETWISE_ALLOWED_HOSTS", "").strip()
    if env:
        return [h.strip() for h in env.split(",") if h.strip()]
    return list(_DEFAULT_ALLOWED_HOSTS)


def create_app(
    fixtures_dir: Path | None = None,
    *,
    allowed_hosts: list[str] | None = None,
) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        fixtures_dir: Directory containing GP/MusicXML/MIDI files.
                      Defaults to the configured partitions_dir from settings.
        allowed_hosts: Host header allowlist for the DNS-rebinding guard.
                       Defaults to loopback only (overridable via the
                       ``FRETWISE_ALLOWED_HOSTS`` environment variable).
    """
    app = FastAPI(title="FretWise", version="0.4.0")

    # Reject requests whose Host header is not in the allowlist. Without this a
    # malicious web page could use DNS rebinding to reach the loopback server
    # and drive its (unauthenticated) settings/upload/download endpoints.
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=_resolve_allowed_hosts(allowed_hosts),
    )

    # Cache-busting for dev assets + baseline hardening headers.
    @app.middleware("http")
    async def _security_and_cache_headers(request: Request, call_next: Any) -> Any:
        # CSRF guard for state-mutating API endpoints.
        # Strategy (defence-in-depth alongside TrustedHostMiddleware):
        #  1. Sec-Fetch-Site (Fetch Metadata, Chrome 76+/Firefox 90+/Edge 79+):
        #     can't be forged by a cross-origin web page.  Allow same-origin and
        #     "none" (user-initiated direct navigation, extensions, native clients).
        #  2. Origin header fallback for older browsers: must match the Host.
        #  3. No Sec-Fetch-Site AND no Origin: programmatic caller (curl, pixi,
        #     API scripts) — allowed without a token so the CLI stays usable.
        if (
            request.method in ("POST", "PUT", "DELETE", "PATCH")
            and request.url.path.startswith("/api/")
        ):
            sec_fetch_site = request.headers.get("sec-fetch-site")
            origin = request.headers.get("origin")
            if sec_fetch_site is not None:
                if sec_fetch_site not in ("same-origin", "none"):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF: cross-site request rejected"},
                    )
            elif origin is not None:
                from urllib.parse import urlparse
                host = request.headers.get("host", "")
                if urlparse(origin).netloc != host:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "CSRF: origin mismatch"},
                    )

        response = await call_next(request)
        # Defensive headers applied to every response.
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        # SAMEORIGIN (not DENY): still blocks other sites from framing us
        # (clickjacking), but allows our own same-origin iframe — the floating
        # hand-fretting visualisation panel loads /static/hand_viz.html in one.
        response.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        path = request.url.path
        if path.startswith("/static/") and path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        elif path.startswith("/api/"):
            # API responses are live state (e.g. /api/files fingering badges that
            # change after a save). Never let the browser serve a stale cached
            # body — otherwise the library icon does not refresh on return.
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    cfg = _settings.load()
    if fixtures_dir is None:
        fixtures_dir = Path(
            cfg.get("partitions_dir", str(Path(__file__).parents[3] / "partitions"))
        )

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Store config
    app.state.fixtures_dir = fixtures_dir
    app.state._batch_cancel = threading.Event()
    app.state._batch_running = False
    # Pluggable partitions storage (local by default; S3 / WebDAV / GDrive when
    # configured). A misconfigured cloud backend must not take the whole server
    # down, so we fall back to local and surface the error via /api/storage.
    _set_storage_backend(app, cfg, fixtures_dir)

    # Multi-user mode (opt-in). When OIDC is configured, each request is served
    # from the logged-in user's own cloud storage; the server hosts no shared
    # partition library. When not configured, the app stays single-user.
    app.state.multiuser = False
    app.state.auth_error = None
    _setup_multiuser(app)

    _register_routes(app)
    return app


def _setup_multiuser(app: FastAPI) -> None:
    """Enable password / OIDC auth + per-user storage when configured.

    Fail-closed: if auth is configured (an OIDC provider, a local admin, or
    ``FRETWISE_AUTH_ENABLED``) but initialisation fails (missing ``[auth]``
    extra, no ``FRETWISE_SECRET_KEY``, …) we refuse to start rather than silently
    degrading to single-user mode, which would serve the local partitions
    library with **no authentication at all**.
    """
    auth_cfg = load_auth_config()
    if not auth_cfg.enabled:
        return
    try:
        user_store = UserStore(auth_cfg.data_dir)
        secrets_store = UserSecretsStore(auth_cfg.data_dir)
        account_store = LocalAccountStore(auth_cfg.data_dir)
        setup_auth(app, auth_cfg, user_store, secrets_store, account_store)
        app.state.user_store = user_store
        app.state.secrets_store = secrets_store
        app.state.account_store = account_store
        app.state.cache_root = auth_cfg.cache_root
        app.state.multiuser = True
    except Exception as exc:  # noqa: BLE001 - re-raised below as a clear setup error
        raise RuntimeError(
            "Multi-user authentication is configured but could not be "
            f"initialised: {exc}. Refusing to start without auth. Install the "
            "auth extra (pip install 'fretwise[auth]') and set FRETWISE_SECRET_KEY, "
            "or unset FRETWISE_AUTH_ENABLED and the OIDC variables to run single-user."
        ) from exc


def _set_storage_backend(app: FastAPI, cfg: dict[str, Any], local_root: Path) -> None:
    """Build the configured storage backend, falling back to local on error."""
    try:
        app.state.storage = build_backend(cfg, local_root=local_root)
        app.state.storage_error = None
    except StorageError as exc:
        app.state.storage = LocalStorageBackend(local_root)
        app.state.storage_error = str(exc)


def _register_routes(app: FastAPI) -> None:
    """Register all API and page routes."""

    @app.get("/")
    async def index() -> Response:
        """Serve the main single-page app (redirect to login if unauthenticated)."""
        if getattr(app.state, "multiuser", False) and current_request_user() is None:
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url="/login", status_code=303)
        html_path = _STATIC_DIR / "index.html"
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    @app.get("/api/files")
    async def list_files() -> JSONResponse:
        """List available score files, enriched with songs_index metadata.

        Works against whichever storage backend is active (local directory or a
        configured cloud store).
        """
        storage: StorageBackend = _current_storage(app)
        songs = _load_catalog(app)
        # Scan the rigs directory ONCE into an in-memory fingerprint set for O(1)
        # per-file has-rig checks (a per-file find_rig() would rescan the whole
        # rigs dir for every score without an exact match — slow on big libraries).
        rig_index = build_rig_index(find_rigs_dir(app.state.fixtures_dir))

        try:
            objects = storage.list_scores()
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        local_root: Path | None = storage.local_root
        files = []
        for obj in objects:
            info: dict[str, Any] = {
                "name": obj.name,
                "stem": obj.stem,
                "format": obj.format,
                "has_rig": partition_has_rig(obj.name, rig_index),
            }
            info = enrich_file_info(info, songs)
            # Fingering sidecar status (local storage + .gp files only; skip
            # _fingered.gp variants — those are outputs, not source files).
            has_fingering = False
            fingering_is_current = False
            if (
                local_root is not None
                and obj.name.endswith(".gp")
                and not obj.stem.endswith("_fingered")
            ):
                src = local_root / obj.name
                meta = _read_fingering_meta(src)
                if meta is not None:
                    has_fingering = True
                    fingering_is_current = _fingering_meta_is_current(meta, src)
                elif _gp_has_embedded_fingering(src):
                    # Fingerings embedded in the file but no sidecar — present,
                    # but version unknown (flagged not-current so the UI shows
                    # the "obsolète/à vérifier" marker).
                    has_fingering = True
                    fingering_is_current = False
            info["has_fingering"] = has_fingering
            info["fingering_is_current"] = fingering_is_current
            files.append(info)
        return JSONResponse(files)

    @app.get("/api/files/stream")
    async def stream_files() -> StreamingResponse:
        """Stream score files as NDJSON (one JSON object per line) as they are scanned.

        Allows the client to populate the library progressively without waiting for
        the full directory scan to complete.
        """
        storage: StorageBackend = _current_storage(app)
        songs = _load_catalog(app)
        rig_index = build_rig_index(find_rigs_dir(app.state.fixtures_dir))

        try:
            objects = list(storage.list_scores())
        except StorageError as exc:
            message = str(exc)
            async def _err() -> Any:
                yield _json.dumps({"error": message}) + "\n"
            return StreamingResponse(_err(), media_type="application/x-ndjson")

        local_root: Path | None = storage.local_root

        async def _generate() -> Any:
            for obj in objects:
                info: dict[str, Any] = {
                    "name": obj.name,
                    "stem": obj.stem,
                    "format": obj.format,
                    "has_rig": partition_has_rig(obj.name, rig_index),
                }
                info = enrich_file_info(info, songs)
                has_fingering = False
                fingering_is_current = False
                if (
                    local_root is not None
                    and obj.name.endswith(".gp")
                    and not obj.stem.endswith("_fingered")
                ):
                    src = local_root / obj.name
                    meta = _read_fingering_meta(src)
                    if meta is not None:
                        has_fingering = True
                        fingering_is_current = _fingering_meta_is_current(meta, src)
                    elif _gp_has_embedded_fingering(src):
                        has_fingering = True
                        fingering_is_current = False
                info["has_fingering"] = has_fingering
                info["fingering_is_current"] = fingering_is_current
                yield _json.dumps(info) + "\n"
                await asyncio.sleep(0)  # yield control between files

        return StreamingResponse(_generate(), media_type="application/x-ndjson")

    @app.get("/api/rig/{filename}")
    async def get_rig(filename: str) -> JSONResponse:
        """Return Valeton GP-180 rig data for a score file (404 if none).

        A "new format" gears sheet (``data/gears/<artist__title>.json`` in the
        shared SongsGears schema) takes precedence over the legacy ``.md`` sheet,
        so dropping a JSON in supersedes the old curated data for that song.
        """
        view = _gears_view_for(filename)
        if view is not None:
            return JSONResponse(view)
        rigs_dir = find_rigs_dir(app.state.fixtures_dir)
        if not rigs_dir:
            raise HTTPException(404, "No rigs directory found")
        rig_path = find_rig(filename, rigs_dir)
        if not rig_path:
            raise HTTPException(404, f"No rig found for {filename!r}")
        content = rig_path.read_text(encoding="utf-8")
        return JSONResponse(parse_rig(content))

    @app.get("/api/rig-bank")
    async def get_rig_bank() -> JSONResponse:
        """Return the structured GP-180 bank used for MIDI activation."""
        path = _rig_bank_json_path(app)
        try:
            bank = load_rig_bank(path)
        except (OSError, _json.JSONDecodeError, RigBankError) as exc:
            raise HTTPException(500, f"Invalid rig bank: {exc}")
        return JSONResponse(bank.to_json())

    @app.post("/api/rig-bank/profile")
    async def upsert_rig_profile(request: Request) -> JSONResponse:
        """Add or replace one actionable GP-180 profile in ``rig_bank.json``."""
        try:
            body = await request.json()
            profile = RigProfile.from_json(body)
            path = _rig_bank_json_path(app)
            bank = load_rig_bank(path).with_profile(profile)
            save_rig_bank(path, bank)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"profile": profile.to_json(), "bank": bank.to_json()})

    @app.post("/api/rig-bank/binding")
    async def upsert_rig_binding(request: Request) -> JSONResponse:
        """Bind a GP-180 profile to a song, artist, or genre."""
        try:
            body = await request.json()
            binding = RigBinding.from_json(body)
            path = _rig_bank_json_path(app)
            bank = load_rig_bank(path).with_binding(binding)
            save_rig_bank(path, bank)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse({"binding": binding.to_json(), "bank": bank.to_json()})

    @app.post("/api/rig-bank/resolve")
    async def resolve_rig_profile(request: Request) -> JSONResponse:
        """Resolve the profile for a song/artist/genre/profile selection."""
        try:
            body = await request.json()
            resolution = _resolve_rig_bank_request(app, body)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        if resolution is None:
            raise HTTPException(404, "No matching rig profile")
        return JSONResponse(resolution.to_json())

    @app.post("/api/rig-bank/recommend")
    async def recommend_rig_profile(request: Request) -> JSONResponse:
        """Recommend the nearest GP-180 profile and explain the match."""
        try:
            body = await request.json()
            bank, context = _rig_bank_context_from_request(app, body)
            target_modules = _target_rig_modules_from_request(body)
            if not target_modules:
                filename = _body_text(body, "filename")
                if filename:
                    target_modules = _target_rig_modules_from_view(_gears_view_for(filename))
            recommendation = bank.recommend(**context, target_modules=target_modules)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        if recommendation is None:
            raise HTTPException(404, "No GP-180 profile available")
        payload = recommendation.to_json()
        payload["context"] = {**context, "active_module_count": len(target_modules)}
        return JSONResponse(payload)

    @app.get("/api/rig-bank/midi-outputs")
    async def get_rig_midi_outputs() -> JSONResponse:
        """List mido output ports that could drive the GP-180."""
        try:
            outputs = list_midi_output_names()
        except RigBankError as exc:
            raise HTTPException(500, str(exc))
        return JSONResponse({"outputs": outputs})

    @app.post("/api/rig-bank/activate")
    async def activate_rig_profile(request: Request) -> JSONResponse:
        """Resolve and optionally send MIDI Program Change for a GP-180 profile.

        Body accepts ``profile_id`` or ``filename``/``song``/``artist``/``genre``.
        ``dry_run`` defaults to true so the UI can preview bytes safely.
        """
        try:
            body = await request.json()
            resolution = _resolve_rig_bank_request(app, body)
            if resolution is None:
                raise RigBankError("No matching rig profile")
            dry_run = bool(body.get("dry_run", True))
            messages = resolution.profile.midi_bytes()
            if not dry_run:
                port_name = str(body.get("port_name") or "").strip() or None
                messages = send_profile_program_change(resolution.profile, port_name)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        payload = resolution.to_json()
        payload["dry_run"] = dry_run
        payload["sent"] = not dry_run
        payload["midi"] = [list(message) for message in messages]
        return JSONResponse(payload)

    @app.get("/api/control-surface/gp180")
    async def get_gp180_control_surface_catalog() -> JSONResponse:
        """Return GP-180 actions/layouts for Loupedeck CT/S or other surfaces."""

        try:
            bank = load_rig_bank(_rig_bank_json_path(app))
            catalog = build_gp180_control_surface_catalog(bank)
        except (OSError, _json.JSONDecodeError, RigBankError) as exc:
            raise HTTPException(500, f"Invalid GP-180 control-surface catalog: {exc}")
        return JSONResponse(catalog)

    @app.post("/api/control-surface/gp180/action")
    async def execute_gp180_control_surface_action(request: Request) -> JSONResponse:
        """Execute one ready GP-180 control-surface action.

        Body: ``{"action_id": str, "port_name"?: str, "dry_run"?: bool}``.
        ``dry_run`` defaults to false for hardware-surface usage.
        """

        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise RigBankError("control-surface request body must be an object")
            action_id = str(body.get("action_id") or "").strip()
            if not action_id:
                raise RigBankError("action_id is required")
            bank = load_rig_bank(_rig_bank_json_path(app))
            catalog = build_gp180_control_surface_catalog(bank)
            action = find_gp180_control_surface_action(catalog, action_id)
            if action is None:
                raise RigBankError(f"unknown GP-180 control-surface action: {action_id}")
            if action.get("status") != "ready":
                raise RigBankError(f"GP-180 action is not MIDI-ready yet: {action_id}")
            if action.get("kind") == "recommend_context":
                resolution = _resolve_rig_bank_request(app, body)
                if resolution is None:
                    raise RigBankError("No matching rig profile")
                profile = resolution.profile
                source = resolution.source
            else:
                profile_id = profile_id_for_surface_action(action, bank)
                if profile_id is None:
                    raise RigBankError(f"action has no activatable profile: {action_id}")
                profile = bank.get_profile(profile_id)
                if profile is None:
                    raise RigBankError(f"unknown rig profile id: {profile_id}")
                source = "explicit"
            dry_run = bool(body.get("dry_run", False))
            messages = profile.midi_bytes()
            if not dry_run:
                port_name = str(body.get("port_name") or "").strip() or None
                messages = send_profile_program_change(profile, port_name)
        except (_json.JSONDecodeError, RigBankError, OSError, TypeError) as exc:
            raise HTTPException(400, str(exc))
        return JSONResponse(
            {
                "action_id": action_id,
                "source": source,
                "dry_run": dry_run,
                "sent": not dry_run,
                "profile": profile.to_json(),
                "midi": [list(message) for message in messages],
            }
        )

    @app.post("/api/rig/generate")
    async def generate_rig(request: Request) -> JSONResponse:
        """Generate a GP-180 rig via the local AI wrapper (tools/codex_song_rig.py).

        Body: ``{"artist": str, "title": str, "genre"?: str, "target_guitar"?: str,
        "refresh"?: bool}``. Returns the wrapper's raw JSON object on success.

        The wrapper is launched as a child process (never a shell) and is slow
        I/O, so the blocking call is offloaded to a worker thread to keep the
        event loop responsive. On failure a 502 is returned with the child
        stderr in the detail — the frontend keeps the previously shown rig.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")

        artist = str(body.get("artist") or "").strip()
        title = str(body.get("title") or "").strip()
        if not artist or not title:
            raise HTTPException(400, "Both 'artist' and 'title' are required")
        genre = str(body.get("genre") or "").strip() or None
        target_guitar = str(body.get("target_guitar") or "").strip() or None
        refresh = bool(body.get("refresh"))

        cfg = _settings.load()
        service = SongRigGenerationService(
            python_exe=cfg.get("rig_ai_python") or None,
            tools_dir=cfg.get("rig_ai_tools_dir") or None,
            provider=cfg.get("rig_ai_provider") or None,
            timeout=cfg.get("rig_ai_timeout") or None,
        )
        # Grounded pipeline: look up verified facts for this song; when present the
        # prompt is grounded and the hard facts are written deterministically, then
        # the rig is validated against the GP-180 palette. Songs without facts are
        # still generated but flagged ``grounded=False`` and graded down (never an
        # inflated "A"). Falls back to plain generation if the facts DB is absent.
        facts = None
        facts_db = Path(cfg.get("rig_facts_db") or "") if cfg.get("rig_facts_db") else \
            Path(__file__).resolve().parents[3] / "data" / "song_facts.json"
        try:
            if facts_db.is_file():
                facts = JsonFactsProvider(facts_db).get_facts(artist, title)
        except (OSError, ValueError):
            facts = None
        try:
            res = await asyncio.to_thread(
                generate_grounded_rig,
                service,
                artist,
                title,
                facts=facts,
                genre=genre,
                target_guitar=target_guitar,
                refresh=refresh,
            )
        except RigGenerationError as exc:
            detail = str(exc)
            if exc.stderr:
                detail = f"{detail}\n{exc.stderr.strip()}"
            raise HTTPException(502, detail)
        # Unified view shape (same as /api/rig) plus grounding metadata so the UI
        # can badge the rig as ancré / non-ancré and surface device validation flags.
        return JSONResponse(res.view)

    @app.post("/api/rig/save")
    async def save_rig(request: Request) -> JSONResponse:
        """Persist a generated rig as the song's GP-180 ``.md`` sheet.

        Body: ``{"filename": <score name>, "rig": <generated view object>}``.
        Replaces the existing sheet (backing up the *original* once, as
        ``<name>.md.bak``, never clobbering that first backup on later saves) or
        creates a new one at the canonical path. Returns the saved/backup names.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        filename = str(body.get("filename") or "").strip()
        rig = body.get("rig")
        if not filename or not isinstance(rig, dict):
            raise HTTPException(400, "Both 'filename' and 'rig' (object) are required")

        rigs_dir = find_rigs_dir(app.state.fixtures_dir)
        if not rigs_dir:
            raise HTTPException(404, "No rigs directory found")

        target = find_rig(filename, rigs_dir) or default_rig_path(filename, rigs_dir)
        backup_name: str | None = None
        if target.is_file():
            backup = target.with_name(target.name + ".bak")
            # Preserve the very first (curated) version; don't overwrite it on
            # repeated saves of AI-generated rigs.
            if not backup.exists():
                shutil.copy2(target, backup)
                backup_name = backup.name
        else:
            target.parent.mkdir(parents=True, exist_ok=True)

        md = rig_view_to_markdown(rig, date=_date.today().strftime("%m-%d-%Y"))
        target.write_text(md, encoding="utf-8")
        return JSONResponse({"saved": target.name, "backup": backup_name})

    @app.get("/api/gears/{filename}/prompt")
    async def get_gear_verification_prompt(filename: str) -> Response:
        """Serve a copy-paste prompt for an external LLM to (re-)verify a gear sheet.

        Grounds the prompt in the song's existing ``gear.v2``/rig JSON when one
        exists (so the LLM double-checks/corrects it rather than starting from
        scratch), falling back to the song catalog / filename for artist+title
        when no sheet exists yet.
        """
        existing = _gears_raw_doc_for(filename)
        existing_song = existing.get("song") if isinstance(existing, dict) else None
        existing_song = existing_song if isinstance(existing_song, dict) else {}
        artist = str(existing_song.get("artist") or (existing or {}).get("artist") or "").strip()
        title = str(existing_song.get("title") or "").strip()
        if not artist or not title:
            catalog = _load_catalog(app)
            stem = Path(filename).stem
            info = dict(catalog.get(filename) or catalog.get(stem) or {})
            if not info:
                info = parse_filename_metadata(filename)
            artist = artist or str(info.get("artist") or "")
            title = title or str(info.get("title") or "")

        if existing:
            prompt = build_gear_verification_prompt(artist, title, existing=existing)
            prompt_mode = "verify"
        else:
            prompt = build_gear_creation_prompt(artist, title)
            prompt_mode = "create"
        return Response(
            content=prompt,
            media_type="text/markdown",
            headers={
                "Content-Disposition": 'inline; filename="fretwise-gear-prompt.md"',
                "X-FretWise-Gear-Prompt-Mode": prompt_mode,
            },
        )

    @app.post("/api/gears/{filename}/save")
    async def save_gear_sheet(filename: str, request: Request) -> JSONResponse:
        """Validate a pasted ``gear.v2`` JSON and write it to ``data/gears/``.

        Body: ``{"gear": {...}}`` — the JSON an external LLM returned for the
        ``/api/gears/{filename}/prompt`` prompt. Overwrites the song's existing
        sheet in place when one is already tracked for this score (matched the
        same way ``GET /api/rig/{filename}`` resolves it); otherwise creates a
        new file at the canonical ``<artist>__<title>.json`` path. Returns the
        refreshed view so the frontend can re-render without a second fetch.
        """
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")
        gear = body.get("gear") if isinstance(body, dict) else None
        if not isinstance(gear, dict):
            raise HTTPException(400, "'gear' (object) is required")

        result = validate_gear_v2(gear)
        if not result["ok"]:
            raise HTTPException(400, "Invalid gear.v2 document: " + "; ".join(result["errors"]))

        song = gear.get("song") if isinstance(gear.get("song"), dict) else {}
        artist = str(song.get("artist") or "").strip()
        title = str(song.get("title") or "").strip()

        target = _gears_resolve_path(filename) or (_gears_root() / _gears_filename(artist, title))
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(_json.dumps(gear, ensure_ascii=False, indent=2), encoding="utf-8")

        return JSONResponse({
            "saved": target.name,
            "warnings": result["warnings"],
            "view": song_output_to_view(gear),
        })

    @app.get("/api/rig-image/{image_name}")
    async def get_rig_image(image_name: str) -> Response:
        """Serve a rig illustration (pedal or guitar) from data/pedals/ or data/guitars/."""
        if "/" in image_name or "\\" in image_name or ".." in image_name:
            raise HTTPException(400, "Invalid image name")
        project_root = Path(__file__).resolve().parents[3]
        fallback_root = app.state.fixtures_dir.parent
        img_path: Path | None = None
        for sub in ("pedals", "guitars"):
            for root in (project_root / "data", fallback_root / "data"):
                candidate = root / sub / image_name
                if candidate.is_file():
                    img_path = candidate
                    break
            if img_path is not None:
                break
        if img_path is None:
            raise HTTPException(404, f"Image {image_name!r} not found")
        content = img_path.read_bytes()
        name_lower = image_name.lower()
        if name_lower.endswith((".jpg", ".jpeg")):
            media_type = "image/jpeg"
        else:
            media_type = "image/png"
        return Response(content=content, media_type=media_type)

    @app.get("/api/tracks/{filename}")
    async def list_tracks(filename: str) -> list[dict[str, Any]]:
        """List every track in a file with its instrument ``kind``.

        Response: a JSON array (one object per track, in score order) with::

            {
              "id":     int,           # track id to pass to /api/solve & /api/notes
              "name":   str,           # display name
              "tuning": list[int],     # open-string MIDI pitches ([] if none)
              "kind":   str            # "guitar"|"bass"|"drums"|"vocal"|"other"
            }

        All tracks are returned (vocals/bass/drums included), not only guitars.
        The frontend uses ``kind`` to decide rendering: only ``"guitar"`` tracks
        get the fingering optimizer (see /api/solve ``fingered`` flag); the rest
        render as standard-notation staves.
        """
        filepath = _resolve_file(app, filename)

        try:
            adapter = get_adapter(filepath)
        except UnsupportedFormatError as exc:
            raise HTTPException(400, str(exc))

        tracks = []
        if hasattr(adapter, "list_all_tracks"):
            # GP 7/8: full multitrack listing with per-track kind.
            for track_id, name, tuning, kind in adapter.list_all_tracks(filepath):
                tracks.append({
                    "id": track_id,
                    "name": name,
                    "tuning": tuning,
                    "kind": kind,
                })
        elif hasattr(adapter, "list_guitar_tracks"):
            # Adapters that only expose guitar tracks (treat them as guitars).
            for track_id, name, tuning in adapter.list_guitar_tracks(filepath):
                tracks.append({
                    "id": track_id,
                    "name": name,
                    "tuning": tuning,
                    "kind": KIND_GUITAR,
                })
        else:
            # MusicXML/MIDI: single-track, assumed guitar.
            tracks.append({
                "id": 0,
                "name": "Guitar",
                "tuning": [40, 45, 50, 55, 59, 64],
                "kind": KIND_GUITAR,
            })

        return tracks

    @app.get("/api/notes/{filename}")
    async def get_notes(
        filename: str,
        track_id: int | None = Query(None),
        same_finger_motion_penalty: bool = Query(True),
        infer_implicit_legato: bool = Query(True),
    ) -> dict[str, Any]:
        """Return notes for a track (audio-only, no rendering).

        Lighter than /api/solve: skips the core rendering pipeline entirely.
        Used by the multi-track audio mixer to load secondary track note data.

        Guitar tracks are Viterbi-fingered (``fingered: true``); non-guitar
        tracks (vocals/bass/drums/other) are returned staff-only with null
        string/fret/finger fields (``fingered: false``). Response includes the
        track ``kind`` and ``fingered`` flag.
        """
        filepath = _resolve_file(app, filename)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        kind = _track_kind(adapter, filepath, track_id)
        fingered = kind == KIND_GUITAR
        if fingered:
            rule_preferences = RulePreferences(
                same_finger_motion_penalty=same_finger_motion_penalty,
                infer_implicit_legato=infer_implicit_legato,
            )
            results, _ = _run_legacy_pipeline(
                events,
                rule_preferences=rule_preferences,
            )
            serialized_results = [_serialize_result(r) for r in results]
        else:
            serialized_results = [
                _serialize_staff_note(ev, i + 1) for i, ev in enumerate(events)
            ]
        track_name: str = getattr(adapter, "track_name", "") or ""
        midi_program: int = getattr(adapter, "midi_program", -1)
        tempo = events[0].tempo if events else 120.0
        beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0))
        build_performance(serialized_results, default_tempo=tempo)

        return {
            "track_name": track_name,
            "midi_program": midi_program,
            "kind": kind,
            "fingered": fingered,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "measure_beats": _measure_beats_array(adapter, events),
            "measure_tempos": _measure_tempo_array(adapter, events),
            "results": serialized_results,
        }

    @app.get("/api/solve/{filename}")
    def solve_file(
        filename: str,
        track_id: int | None = Query(None),
        representation_mode: str = Query("standard_tablature"),
        same_finger_motion_penalty: bool = Query(True),
        infer_implicit_legato: bool = Query(True),
        svg_width: int | None = Query(None, ge=400, le=5000),
    ) -> dict[str, Any]:
        """Render a track and return saved fingerings (no on-demand Viterbi).

        Fingerings are served from the sidecar written by POST /api/save/gp.
        When no sidecar exists (or it is stale), the track renders without
        finger annotations and the response carries ``has_saved_fingering: false``
        so the frontend can highlight the "Insert fingerings" button.

        To compute fingerings call POST /api/save/gp/{filename} first — that
        runs the full Viterbi + phrase-window pipeline and writes the sidecar.

        Sync def so FastAPI runs each request in its thread pool — concurrent
        solve requests (e.g. the frontend prefetch fanning out N tracks × M
        modes) actually execute in parallel instead of serialising on the event
        loop thread.
        """
        filepath = _resolve_file(app, filename)
        cache_key = _solve_cache_key(
            filepath, track_id, representation_mode,
            same_finger_motion_penalty, infer_implicit_legato,
            svg_width,
        )
        cached = _solve_cache_get(cache_key)
        if cached is not None:
            return cached
        view_mode = _parse_representation_mode(representation_mode)

        # Step 1 — parse (adapter + events + metadata). Cached by (file, mtime,
        # track) since it's mode- and prefs-independent. The old Viterbi step
        # that lived here has moved to POST /api/save/gp.
        base_key = _legacy_cache_key(filepath, track_id)
        base = _legacy_cache_get(base_key)
        if base is None:
            adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
            if not events:
                raise HTTPException(404, "No notes found in file")
            kind = _track_kind(adapter, filepath, track_id)
            fingered = kind == KIND_GUITAR
            base = {
                "adapter": adapter,
                "events": events,
                "kind": kind,
                "fingered": fingered,
                "track_name": getattr(adapter, "track_name", "") or "",
                "midi_program": getattr(adapter, "midi_program", -1),
                "section_markers": dict(
                    getattr(adapter, "section_markers", {}) or {}
                ),
                "chord_diagrams": [
                    _serialize_chord_diagram(cd)
                    for cd in list(getattr(adapter, "chord_diagrams", []) or [])
                ],
                "chord_markers": dict(
                    getattr(adapter, "chord_markers", {}) or {}
                ),
                "tempo": events[0].tempo if events else 120.0,
                "beats_per_measure": float(
                    getattr(adapter, "beats_per_measure", 4.0)
                ),
                "measure_beats": _measure_beats_array(adapter, events),
                "measure_tempos": _measure_tempo_array(adapter, events),
            }
            _legacy_cache_put(base_key, base)

        # Step 2 — load fingerings from sidecar (or return empty for guitar
        # tracks that have not been fingered yet, and staff-only for others).
        has_saved_fingering = False
        fingering_is_current = False
        fingering_algo_version: str | None = None
        meta: dict[str, Any] | None = None
        if base["fingered"] and filepath.suffix.lower() == ".gp":
            meta = _read_fingering_meta(filepath)
            if meta is not None:
                has_saved_fingering = True
                fingering_is_current = _fingering_meta_is_current(meta, filepath)
                fingering_algo_version = meta.get("algo_version")

        audit: dict[str, Any] = {}
        if base["fingered"] and fingering_is_current:
            # Happy path: serve pre-computed fingerings + audit from sidecar.
            # Per-track (bug #3): a multi-guitar song caches one entry per track
            # under data["tracks"][str(track_id)]. Prefer the exact track entry;
            # else serve the top-level "primary" (the most-recently-saved track,
            # recorded in meta["track_id"], OR a legacy single-track sidecar with
            # no track_id); else this track simply has not been fingered yet.
            import json as _json
            data_path = _fingering_data_path(filepath)
            try:
                data = _json.loads(data_path.read_text(encoding="utf-8"))
                tracks = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
                tkey = str(track_id) if track_id is not None else None
                primary_tid = meta.get("track_id") if meta else None
                if tkey is not None and tkey in tracks:
                    serialized_results = tracks[tkey].get("results", [])
                    audit = tracks[tkey].get("audit") or {}
                elif primary_tid == track_id or (
                    # Sidecar written before per-track support (primary_tid=None)
                    # is only served for the default single-track case (no
                    # explicit track requested, or track 0/None).
                    primary_tid is None and (track_id is None or track_id == 0)
                ):
                    serialized_results = data.get("results", [])
                    audit = data.get("audit") or {}
                else:
                    # Another track was fingered, not this one.
                    serialized_results = []
                    has_saved_fingering = False
            except Exception:
                serialized_results = []
                has_saved_fingering = False
                fingering_is_current = False
            stats: dict[str, Any] = {
                "parsed": len(base["events"]),
                "fingered": len(serialized_results),
                "from_sidecar": True,
            }
        elif base["fingered"]:
            # No current sidecar. Fall back to fingerings embedded in the GP
            # file itself (LeftFingering) so a partition that already carries
            # fingers shows them on open. Embedded data has no algo version, so
            # it's flagged not-current (the UI invites a recompute to verify).
            embedded = (
                _read_embedded_gp_fingerings(filepath)
                if filepath.suffix.lower() == ".gp"
                else {}
            )
            if embedded:
                emb_results = _embedded_results_from_events(
                    base["events"], embedded,
                )
                serialized_results = [_serialize_result(r) for r in emb_results]
                has_saved_fingering = True
                fingering_is_current = False
                if fingering_algo_version is None:
                    fingering_algo_version = "embedded"
                stats = {
                    "parsed": len(base["events"]),
                    "fingered": len(embedded),
                    "from_embedded": True,
                }
            else:
                # Guitar track with no fingers anywhere — tablature only.
                serialized_results = []
                stats = {"parsed": len(base["events"]), "fingered": 0}
            audit = {}
        else:
            # Non-guitar track (vocals/bass/drums): staff-only, no fingerings.
            serialized_results = [
                _serialize_staff_note(ev, i + 1)
                for i, ev in enumerate(base["events"])
            ]
            stats = {"parsed": len(base["events"]), "fingered": 0}
            audit = {}

        # Step 3 — mode-dependent core/SVG render. Cheap (~90ms). Guitar tracks
        # always render as tablature (regardless of sidecar presence); non-guitar
        # tracks are forced to standard notation.
        render_mode = view_mode if base["fingered"] else RepresentationMode.STANDARD
        # The notation/SVG render can raise on a malformed/edge-case passage
        # (e.g. an impossible chord voicing hitting a glyph registry KeyError).
        # Never let that blank the WHOLE tab — degrade to no-SVG so the canvas
        # tab (which renders from `results`) still shows, and surface the error.
        core_svg = ""
        core_conformance = 0
        measure_regions: list[Any] = []
        render_error: str | None = None
        _page_width: float | None = float(svg_width) if isinstance(svg_width, int) else None
        try:
            core_result = _run_core_pipeline_for_events(
                filepath, base["adapter"], base["events"],
                representation_mode=render_mode,
                track_kind=base.get("kind", "guitar"),
                page_width=_page_width,
            )
            core_svg = core_result.svg
            core_conformance = len(core_result.conformance_issues)
            measure_regions = _extract_measure_regions(
                getattr(core_result, "render_scene", None),
                getattr(core_result, "canonical_score", None),
                mode=render_mode.value,
                page_width=_page_width,
            )
        except Exception as exc:  # noqa: BLE001 — degrade, never abort the tab
            import logging as _logging
            _logging.getLogger("fretwise.web").exception(
                "core render failed for %s (track %s)", filepath.name, track_id
            )
            render_error = str(exc)

        auto_title, auto_artist = _infer_title_artist(filepath)

        serialized_results = _annotate_serialized_review_status(
            serialized_results, audit,
        )
        build_performance(serialized_results, default_tempo=base["tempo"])

        payload: dict[str, Any] = {
            "title": auto_title,
            "artist": auto_artist,
            "track_name": base["track_name"],
            "midi_program": base["midi_program"],
            "kind": base["kind"],
            # fingered: True = guitar track that should show tablature + finger UI.
            # has_saved_fingering: True = a sidecar exists and was loaded.
            # fingering_is_current: True = algo_version matches + source unchanged.
            "fingered": base["fingered"],
            "has_saved_fingering": has_saved_fingering,
            "fingering_is_current": fingering_is_current,
            "fingering_algo_version": fingering_algo_version,
            "mode": "performance",
            "representation_mode": render_mode.value,
            "tempo": base["tempo"],
            "beats_per_measure": base["beats_per_measure"],
            "measure_beats": base.get("measure_beats", []),
            "measure_tempos": base.get("measure_tempos", []),
            "section_markers": base["section_markers"],
            "chord_diagrams": base["chord_diagrams"],
            "chord_markers": base["chord_markers"],
            "core_svg": core_svg,
            "core_conformance_issues": core_conformance,
            "measure_regions": measure_regions,
            "stats": stats,
            "results": serialized_results,
            "audit": audit,
            "render_error": render_error,
        }
        _solve_cache_put(cache_key, payload)
        return payload

    @app.get("/api/export/pdf/{filename}")
    async def export_pdf(
        filename: str,
        track_id: int | None = Query(None),
        representation_mode: str = Query("standard_tablature"),
    ) -> Response:
        """Render and download a PDF using the notation-core engine."""
        filepath = _resolve_file(app, filename)
        view_mode = _parse_representation_mode(representation_mode)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        # Legacy renderer for PDF export — restores LH finger annotations
        # missing from core/backends/pdf.py (Phase 4 refactor regression).
        # Conformance is computed in shadow against the core engine so we
        # still track new-architecture parity.
        pdf_bytes = _render_legacy_pdf_payload(filepath, adapter, events)
        shadow_issues, shadow_failed = _shadow_core_conformance_outcome(
            filepath, adapter, events, representation_mode=view_mode,
        )
        conformance_report = legacy_shadow_pdf_conformance_report(
            shadow_issues, shadow_failed=shadow_failed,
        )

        auto_title, auto_artist = _infer_title_artist(filepath)
        filename_base = auto_title if not auto_artist else f"{auto_artist} - {auto_title}"
        safe_name = _safe_pdf_filename(filename_base)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Pdf-Engine": "legacy",
                "X-Fretwise-Conformance-Issues": str(conformance_report.issue_count),
                "X-Fretwise-Conformance-Report": conformance_report.to_header_value(),
            },
        )

    @app.delete("/api/library/refresh-fingerings")
    def cancel_refresh_fingerings() -> dict[str, bool]:
        """Signal a running refresh-fingerings batch to stop gracefully."""
        _require_admin(app)
        app.state._batch_cancel.set()
        return {"cancelled": True}

    @app.post("/api/library/refresh-fingerings")
    def refresh_library_fingerings(
        workers: int | None = Query(
            None, ge=1, le=8,
            description=(
                "Number of parallel worker processes "
                "(default = min(cpu_count, 4))."
            ),
        ),
        force: bool = Query(
            False,
            description=(
                "If false (default), skip files whose _fingered.gp already "
                "exists and is newer than the source."
            ),
        ),
        body: dict[str, Any] | None = Body(None),
    ) -> Response:
        """Recompute fingerings for the selected (or every) GP 7/8 file.

        Thread pool — the workers run *in this process* and share the already
        loaded ONNX sessions (no per-worker warm-up). This deliberately replaces
        the old ``ProcessPoolExecutor``: on Windows, spawning worker processes
        from inside the running server re-imported the entry point and hung the
        whole request (the UI froze on "calcul en cours" and never returned).
        onnxruntime inference is thread-safe and each task builds its own
        StateGenerator/ViterbiOptimizer, so concurrent tasks are safe; the GIL
        serialises the pure-Python Viterbi step but ML/IO overlap, and progress
        streams continuously so the UI never blocks.

        Skip-on-resume — when ``force=false`` (the default), a source file
        whose sidecar is already current is skipped. Pass ``?force=true`` to
        re-process everything.

        Streams one JSON line per processed file via text/plain so the
        frontend can show live progress without a separate polling loop.
        """
        _require_admin(app)
        import json as _json
        import os as _os
        from concurrent.futures import ThreadPoolExecutor, as_completed

        from fastapi.responses import StreamingResponse

        # The in-place multiprocessing batch only works on a local directory
        # (workers glob + read + write files by path). Cloud backends report a
        # clear error rather than silently no-op'ing.
        storage: StorageBackend = _current_storage(app)
        if not storage.supports_batch_refresh or storage.local_root is None:
            raise HTTPException(
                400,
                "Batch fingering refresh is only supported on local storage "
                f"(active backend: {storage.name}).",
            )

        # Refuse to start a second batch on top of a running one — two pools
        # would contend for CPU and double-write the same _fingered.gp outputs.
        if app.state._batch_running:  # type: ignore[attr-defined]
            raise HTTPException(409, "A refresh batch is already running")

        fixtures_dir: Path = storage.local_root

        # Optional explicit selection (from the library multi-select). When a
        # ``files`` list is given, process ONLY those (validated + resolved under
        # the library root) instead of globbing the whole directory — so the
        # checkbox batch targets exactly what the user picked.
        selected = body.get("files") if isinstance(body, dict) else None
        if selected:
            seen: set[Path] = set()
            sources: list[Path] = []
            for name in selected:
                if not isinstance(name, str):
                    continue
                try:
                    p = _resolve_file(app, name)
                except HTTPException:
                    continue  # skip names that don't resolve under the library
                if (
                    p.suffix.lower() == ".gp"
                    and not p.stem.endswith("_fingered")
                    and p not in seen
                ):
                    seen.add(p)
                    sources.append(p)
            sources.sort()
        else:
            all_files = sorted(fixtures_dir.glob("*.gp"))
            sources = [f for f in all_files if not f.stem.endswith("_fingered")]

        # Skip files whose sidecar is already current (unless force=true).
        to_process: list[Path] = []
        pre_skipped: list[Path] = []
        for f in sources:
            if not force:
                meta = _read_fingering_meta(f)
                if meta is not None and _fingering_meta_is_current(meta, f):
                    pre_skipped.append(f)
                    continue
            to_process.append(f)

        n_workers = workers if workers is not None else min(_os.cpu_count() or 4, 4)
        app.state._batch_cancel.clear()
        app.state._batch_running = True

        def _emit() -> Any:
            yield _json.dumps({
                "event": "start",
                "total_files": len(sources),
                "to_process": len(to_process),
                "pre_skipped": len(pre_skipped),
                "workers": n_workers,
            }) + "\n"
            for f in pre_skipped:
                yield _json.dumps({
                    "file": f.name, "status": "skip",
                    "reason": "already fingered",
                }) + "\n"
            ok = err = skipped = 0
            elapsed_times: list[float] = []
            try:
                if to_process:
                    # Warm the shared ONNX singletons once in this thread before
                    # fanning out, so worker threads hit a populated cache (no
                    # first-call load race, no per-task warm-up).
                    _get_player_cost_model()
                    _get_chord_finger_classifier()
                    _get_phrase_window_fingerer()
                    with ThreadPoolExecutor(max_workers=n_workers) as pool:
                        futures = {
                            pool.submit(_process_single_gp, str(f)): f
                            for f in to_process
                        }
                        for fut in as_completed(futures):
                            if app.state._batch_cancel.is_set():
                                pool.shutdown(cancel_futures=True, wait=False)
                                yield _json.dumps({
                                    "event": "cancelled",
                                    "ok": ok, "errors": err, "skipped": skipped,
                                }) + "\n"
                                return
                            result = fut.result()
                            if result["status"] == "ok":
                                ok += 1
                                if "elapsed_s" in result:
                                    elapsed_times.append(result["elapsed_s"])
                            elif result["status"] == "error":
                                err += 1
                            else:
                                skipped += 1
                            done = ok + err + skipped
                            avg_s = (
                                sum(elapsed_times) / len(elapsed_times)
                                if elapsed_times else None
                            )
                            remaining = len(to_process) - done
                            eta_s = (
                                round(avg_s * remaining / n_workers)
                                if avg_s and remaining > 0 else None
                            )
                            result["done"] = done
                            result["total"] = len(to_process)
                            if avg_s is not None:
                                result["avg_s"] = round(avg_s, 2)
                            if eta_s is not None:
                                result["eta_s"] = eta_s
                            yield _json.dumps(result) + "\n"
                yield _json.dumps({
                    "event": "done",
                    "ok": ok, "errors": err, "skipped": skipped,
                    "pre_skipped": len(pre_skipped),
                    "avg_s": (
                        round(sum(elapsed_times) / len(elapsed_times), 2)
                        if elapsed_times else None
                    ),
                }) + "\n"
            finally:
                app.state._batch_running = False

        return StreamingResponse(_emit(), media_type="text/plain")

    @app.post("/api/library/cleanup")
    def cleanup_library() -> dict[str, Any]:
        """Normalise the library after a fingering batch.

        Two passes, both moving losers to a ``.trash`` subfolder (recoverable):

        1. **Rename** any legacy ``<stem>_fingered.gp`` to ``<stem>.gp`` (the
           in-place save model no longer creates these). The fingered copy wins
           on collision: the plain-named file it would overwrite is trashed
           first. Sidecars travel with their file.
        2. **De-duplicate** files that resolve to the same (title, artist): keep
           one canonical member, trashing the rest — preferring to trash members
           whose filename contains ``_`` (e.g. ``Artist_Title`` vs the cleaner
           ``Artist - Title``).

        Returns a report listing every rename and trashed file. Local storage
        only; admin-guarded.
        """
        _require_admin(app)
        storage: StorageBackend = _current_storage(app)
        root: Path | None = storage.local_root
        if root is None:
            raise HTTPException(
                400,
                "Library cleanup is only supported on local storage "
                f"(active backend: {storage.name}).",
            )

        trash = root / ".trash"
        renamed: list[dict[str, str]] = []
        trashed: list[str] = []
        errors: list[str] = []

        def _sidecars(p: Path) -> list[Path]:
            return [_fingering_meta_path(p), _fingering_data_path(p)]

        def _to_trash(p: Path) -> None:
            """Move *p* (and its sidecars) into .trash, de-clobbering by suffix."""
            try:
                trash.mkdir(exist_ok=True)
                for src in [p, *_sidecars(p)]:
                    if not src.exists():
                        continue
                    dest = trash / src.name
                    n = 1
                    while dest.exists():
                        dest = trash / f"{src.stem}.{n}{src.suffix}"
                        n += 1
                    src.rename(dest)
                trashed.append(p.name)
            except OSError as exc:
                errors.append(f"trash {p.name}: {exc}")

        def _rename(src: Path, dst: Path) -> None:
            """Rename *src* → *dst* and carry its sidecars along."""
            try:
                src.rename(dst)
                for src_side, dst_side in (
                    (_fingering_meta_path(src), _fingering_meta_path(dst)),
                    (_fingering_data_path(src), _fingering_data_path(dst)),
                ):
                    if src_side.exists():
                        src_side.rename(dst_side)
                renamed.append({"from": src.name, "to": dst.name})
            except OSError as exc:
                errors.append(f"rename {src.name}: {exc}")

        # Pass 1 — strip "_fingered" suffix (fingered copy wins on collision).
        for f in sorted(root.glob("*_fingered.gp")):
            target = f.with_name(f"{f.stem[: -len('_fingered')]}{f.suffix}")
            if target.exists():
                _to_trash(target)          # plain-named loser → trash
            _rename(f, target)

        # Pass 2 — de-duplicate by (title, artist). Prefer the member without
        # an underscore in its name; trash the rest.
        groups: dict[tuple[str, str], list[Path]] = {}
        for f in sorted(root.glob("*.gp")):
            if f.stem.endswith("_fingered"):
                continue
            title, artist = _infer_title_artist(f)
            groups.setdefault(
                (title.strip().lower(), (artist or "").strip().lower()), []
            ).append(f)

        for members in groups.values():
            if len(members) < 2:
                continue
            # Keep the best-named member: no underscore preferred, then shortest.
            keeper = sorted(
                members, key=lambda p: ("_" in p.stem, len(p.name), p.name)
            )[0]
            for m in members:
                if m != keeper:
                    _to_trash(m)

        # Any rename/trash invalidates cached parses keyed by path+mtime.
        _solve_cache_clear()  # clears both the solve and the legacy parse cache

        return {
            "renamed": renamed,
            "trashed": trashed,
            "errors": errors,
            "renamed_count": len(renamed),
            "trashed_count": len(trashed),
        }

    @app.get("/api/export/gp/{filename}")
    def export_gp(
        filename: str,
        track_id: int | None = Query(None),
    ) -> Response:
        """Export the loaded GP file with computed LH fingerings injected.

        Only GP 7/8 (GPIF zip) is supported — older GP3/4/5 binary formats
        have no LeftFingering attribute round-trip and PyGuitarPro doesn't
        write them. The output filename is suffixed with ``_fingered``.
        """
        filepath = _resolve_file(app, filename)
        if filepath.suffix.lower() != ".gp":
            raise HTTPException(
                400, "GP export only supports Guitar Pro 7/8 (.gp) files",
            )

        _, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        payload = _run_legacy_pipeline_with_guard(events)
        if not payload.results:
            raise HTTPException(500, "Pipeline returned no fingering results")

        guard = _guard_summary(payload)
        if payload.biomechanical_report.fatal_count:
            measures = guard["fatal_measures"]
            shown = ", ".join(str(m) for m in measures)
            more = guard["fatal_measure_count"] - len(measures)
            if more > 0:
                shown += f", +{more}"
            raise HTTPException(
                409,
                f"Export GP bloqué : le doigté calculé contient {guard['fatal']} "
                f"position(s) injouable(s), dans {guard['fatal_measure_count']} "
                f"mesure(s) (mesures {shown}). Ces positions ne peuvent pas être "
                "écrites telles quelles dans un fichier Guitar Pro. Revois ces "
                "mesures dans l'audit, ou ajuste le profil / les préférences, puis "
                "réessaie. (Astuce : l'export MusicXML ou PDF reste possible pour "
                "inspecter le rendu.)",
            )

        mapping = fingerings_by_source_id(payload.results)
        merged_mapping = _merged_gp_fingering_mapping(filepath, mapping)
        try:
            gp_bytes = write_gp_with_fingerings(filepath, merged_mapping)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        out_name = f"{filepath.stem}_fingered{filepath.suffix}"
        safe_name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", out_name).strip()
        return Response(
            content=gp_bytes,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Annotated-Notes": str(len(merged_mapping)),
                "X-Fretwise-Biomechanical-Fatal": str(guard["fatal"]),
                "X-Fretwise-Biomechanical-High": str(guard["high"]),
            },
        )

    @app.post("/api/save/gp/{filename}")
    def save_gp(
        filename: str,
        track_id: int | None = Query(None),
    ) -> dict[str, object]:
        """Compute LH fingerings and write ``{stem}_fingered.gp`` into the storage backend.

        Identical pipeline to the GP export but the result is saved server-side
        instead of returned as a download.  Works with both local and cloud
        storage backends (uses ``storage.write_bytes``).
        """
        filepath = _resolve_file(app, filename)
        if filepath.suffix.lower() != ".gp":
            raise HTTPException(
                400, "Save GP only supports Guitar Pro 7/8 (.gp) files",
            )

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        payload = _run_legacy_pipeline_with_guard(events)
        if not payload.results:
            raise HTTPException(500, "Pipeline returned no fingering results")

        guard = _guard_summary(payload)
        # We DON'T hard-block (409) when the computed fingering contains
        # biomechanically impossible positions. The whole point of the optimizer
        # is to still produce a best-effort path; rejecting the entire save left
        # the user with no tab at all. Instead we save fingerings for the whole
        # track and flag the impossible passages in the audit (persisted to the
        # sidecar) and the "Doigtés à revoir" panel — so the rest of the tab
        # renders with fingering and the bad measures are surfaced, not hidden.

        mapping = fingerings_by_source_id(payload.results)
        merged_mapping = _merged_gp_fingering_mapping(filepath, mapping)
        out_name = filepath.name
        storage: StorageBackend = _current_storage(app)
        # Write the fingerings back into the original file (in place) — no
        # "_fingered" suffix, no duplicate. write_gp_with_fingerings has already
        # read the source fully into memory, so overwriting it here is safe and
        # idempotent (LeftFingering injection strips any prior annotation first).
        #
        # Bug #6: an impossible position can make the GP-file embedding raise
        # ValueError. We must NOT abort the whole save in that case — that left
        # the user with no sidecar, so the viewer rendered no fingering at all
        # ("the doigtés action blocks the tab"). Instead we skip only the in-file
        # GP annotation, still persist the sidecar (the viewer renders fingering
        # from it), and let the audit + "Doigtés à revoir" surface the unplayable
        # passage. The audit below flags it FIRST (biomechanical FATAL → "bad").
        gp_embed_error: str | None = None
        try:
            gp_bytes = write_gp_with_fingerings(filepath, merged_mapping)
            storage.write_bytes(out_name, gp_bytes)
        except ValueError as exc:
            gp_embed_error = str(exc)
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        # Compute the audit on the freshly-computed results — it flags the
        # impossible passages (biomechanical FATAL → verdict "bad") FIRST — and
        # persist it in the sidecar so /api/solve serves a real audit banner
        # without re-running Viterbi. Done after the overwrite so source_mtime
        # matches the freshly-written file (when the embed succeeded).
        section_markers = dict(getattr(adapter, "section_markers", {}) or {})
        audit = _safe_audit(events, payload.results, section_markers)
        sidecar_ok = _write_fingering_sidecar(
            filepath,
            payload.results,
            audit=audit,
            track_id=track_id,
        )
        _solve_cache_clear()

        return {
            "saved": out_name,
            "annotated_notes": len(merged_mapping),
            "track_annotated_notes": len(mapping),
            "unexportable_notes": _count_unexportable_gp_fingerings(payload.results),
            "biomechanical_high": guard["high"],
            "biomechanical_fatal": guard["fatal"],
            "fatal_measures": guard["fatal_measures"],
            "fatal_measure_count": guard["fatal_measure_count"],
            "algo_version": FINGERING_ALGO_VERSION,
            # When true, the fingering is saved in the sidecar (viewer + audit +
            # review all work) but could not be embedded into the .gp file; the
            # offending passages are flagged in the audit / "Doigtés à revoir".
            "gp_embed_skipped": gp_embed_error is not None,
            "gp_embed_error": gp_embed_error,
            # False when the sidecar could not be written (disk full, read-only
            # path, etc.).  The GP file itself may still be saved, but /api/solve
            # will re-run Viterbi on next open instead of using the cache.
            "sidecar_saved": sidecar_ok,
        }

    @app.get("/api/export/musicxml/{filename}")
    def export_musicxml(
        filename: str,
        track_id: int | None = Query(None),
        scope: str = Query("current"),
    ) -> Response:
        """Export the computed fingerings as a MusicXML score (.musicxml).

        Works for every supported input format (GP, MusicXML, MIDI). The file
        carries standard notation plus per-note tablature (string/fret) and the
        optimized left-hand fingering, so it opens in MuseScore, Finale, Dorico
        or Guitar Pro for visual verification. Unlike the GP export this is a
        view/verification format, so it is not blocked by the biomechanical
        guard — any violations are reported via response headers instead.

        Query params:
            track_id: Track to export when ``scope=current`` (default track if
                omitted). Ignored when ``scope=all``.
            scope: ``current`` (default) exports the single selected track as a
                one-part score — behaviour identical to before this param
                existed. ``all`` exports every track of the song into one
                multi-part score: guitar tracks run the fingering optimizer;
                vocals/bass/drums/other are rendered staff-only. The download
                filename gets an ``_all`` suffix.
        """
        filepath = _resolve_file(app, filename)
        if scope == "all":
            return _export_musicxml_all(filepath)
        if scope not in ("current", ""):
            raise HTTPException(400, f"Unknown scope: {scope!r}")

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        payload = _run_legacy_pipeline_with_guard(events)
        if not payload.results:
            raise HTTPException(500, "Pipeline returned no fingering results")

        title, artist = _infer_title_artist(filepath)
        track_name = getattr(adapter, "track_name", "") or ""
        xml = render_musicxml(
            payload.results, title=title, artist=artist, instrument=track_name,
            time_denominator=int(getattr(adapter, "time_denominator", 4) or 4),
        )

        guard = _guard_summary(payload)
        out_name = f"{filepath.stem}.musicxml"
        safe_name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", out_name).strip()
        return Response(
            content=xml.encode("utf-8"),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Note-Count": str(len(payload.results)),
                "X-Fretwise-Biomechanical-Fatal": str(guard["fatal"]),
                "X-Fretwise-Biomechanical-High": str(guard["high"]),
            },
        )

    def _export_musicxml_all(filepath: Path) -> Response:
        """Export every track of a song into one multi-part MusicXML score.

        Iterates :meth:`list_all_tracks`, running the fingering optimizer for
        guitar tracks and emitting staff-only notes for the rest, then renders a
        single multi-part document. Adapters without ``list_all_tracks`` (single
        track MusicXML/MIDI, guitar-only GP fallback) degrade to a one-part
        export covering the default track.
        """
        adapter, _ = _load_adapter_and_events(filepath)
        title, artist = _infer_title_artist(filepath)

        # Enumerate tracks. Adapters that can't list tracks expose just their
        # default (guitar) track via track_id=None.
        listed: list[tuple[int | None, str, str]] = []
        if hasattr(adapter, "list_all_tracks"):
            try:
                for tid, name, _tuning, kind in adapter.list_all_tracks(filepath):
                    listed.append((tid, name, kind))
            except (ParseError, UnsupportedFormatError):
                listed = []
        if not listed:
            listed = [(None, getattr(adapter, "track_name", "") or "", KIND_GUITAR)]

        parts: list[dict[str, Any]] = []
        total_notes = 0
        fatal = 0
        high = 0
        for track_id, name, kind in listed:
            _, events = _load_adapter_and_events(filepath, track_id=track_id)
            if not events:
                continue
            beats = float(getattr(adapter, "beats_per_measure", 4.0) or 4.0)
            denom = int(getattr(adapter, "time_denominator", 4) or 4)
            if kind == KIND_GUITAR:
                payload = _run_legacy_pipeline_with_guard(events)
                results = payload.results or _staff_only_results(events)
                guard = _guard_summary(payload)
                fatal += guard["fatal"]
                high += guard["high"]
            else:
                results = _staff_only_results(events)
            total_notes += len(results)
            parts.append(
                {
                    "name": name,
                    "kind": kind,
                    "results": results,
                    "beats_per_measure": beats,
                    "time_denominator": denom,
                }
            )

        if not parts:
            raise HTTPException(404, "No notes found in file")

        xml = render_musicxml_multi(parts, title=title, artist=artist)
        out_name = f"{filepath.stem}_all.musicxml"
        safe_name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", out_name).strip()
        return Response(
            content=xml.encode("utf-8"),
            media_type="application/xml",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Note-Count": str(total_notes),
                "X-Fretwise-Part-Count": str(len(parts)),
                "X-Fretwise-Biomechanical-Fatal": str(fatal),
                "X-Fretwise-Biomechanical-High": str(high),
            },
        )

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)) -> dict[str, str]:
        """Upload a score file into the active storage backend."""
        storage: StorageBackend = _current_storage(app)
        try:
            safe_name = safe_score_name(file.filename or "upload")
        except StorageValidationError as exc:
            raise HTTPException(400, str(exc))
        content = await _read_upload_limited(file, _MAX_SCORE_UPLOAD_BYTES)
        try:
            storage.write_bytes(safe_name, content)
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")
        return {"name": safe_name, "status": "ok"}

    @app.get("/api/download/{filename}")
    async def download_file(filename: str) -> Response:
        """Download the original score file from the active storage backend."""
        storage: StorageBackend = _current_storage(app)
        try:
            safe_name = safe_score_name(filename)
        except StorageValidationError as exc:
            raise HTTPException(400, str(exc))
        try:
            content = storage.read_bytes(safe_name)
        except StorageNotFoundError:
            raise HTTPException(404, f"File not found: {safe_name}")
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")
        suffix = Path(safe_name).suffix.lower()
        media_types = {
            ".gp3": "application/octet-stream",
            ".gp4": "application/octet-stream",
            ".gp5": "application/octet-stream",
            ".gp": "application/octet-stream",
            ".xml": "application/xml",
            ".mxl": "application/zip",
            ".musicxml": "application/xml",
            ".mid": "audio/midi",
            ".midi": "audio/midi",
        }
        media_type = media_types.get(suffix, "application/octet-stream")
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
        )

    @app.get("/api/soundfont")
    async def get_soundfont(name: str | None = None) -> Response:
        """Stream a soundfont for in-browser (SpessaSynth) synthesis.

        Resolution order:
          1. explicit ``?name=`` (confined to the soundfonts dir) — content is
             identified by the URL, so it is cached immutably for a year;
          2. the configured ``active_soundfont`` (the one the Settings UI sets);
          3. the first soundfont found in the soundfonts directory.

        Streamed via ``FileResponse`` (sendfile + HTTP Range + auto ETag/304)
        rather than ``read_bytes()`` — a 400+ MB SF2/SF3 must never be read whole
        into server memory per request. The default (active) response is marked
        ``no-cache`` so the browser revalidates and picks up a soundfont change;
        the cheap conditional 304 keeps that fast.
        """
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        sf_path: Path | None = None
        cache_control = "no-cache"

        if name:
            candidate = sf_dir / Path(name).name  # strip any directory component
            try:
                candidate.resolve().relative_to(sf_dir.resolve())
            except ValueError:
                raise HTTPException(403, "Path traversal not allowed")
            if not candidate.exists():
                raise HTTPException(404, f"Soundfont not found: {name}")
            sf_path = candidate
            # URL pins the content → safe to cache forever.
            cache_control = "public, max-age=31536000, immutable"

        if sf_path is None:
            active = cfg.get("active_soundfont", "")
            if active:
                active_path = Path(active)
                if not active_path.is_absolute():
                    active_path = sf_dir / active_path.name
                if active_path.exists():
                    sf_path = active_path

        if sf_path is None and sf_dir.exists():
            sf_path = _prefer_gm_bank([
                p for p in sorted(sf_dir.iterdir())
                if p.suffix.lower() in {".sf2", ".sf3", ".dls"}
            ])

        if sf_path is None or not sf_path.exists():
            raise HTTPException(404, "No soundfont available")

        # Caching: when the caller did not pin a specific ?name=, redirect to the
        # versioned, immutable URL of the resolved active soundfont. The browser
        # then caches the (large) bytes for a year and re-downloads ONLY when the
        # active soundfont — or its on-disk mtime — changes (the ``v`` query bumps
        # the cache key). The redirect itself is ``no-store`` so switching the
        # active soundfont in Settings is picked up on the very next load.
        if not name:
            from urllib.parse import quote

            from fastapi.responses import RedirectResponse
            version = int(sf_path.stat().st_mtime)
            target = f"/api/soundfont?name={quote(sf_path.name)}&v={version}"
            return RedirectResponse(
                target, status_code=307, headers={"Cache-Control": "no-store"}
            )

        return FileResponse(
            sf_path,
            media_type="application/octet-stream",
            headers={"Cache-Control": cache_control},
        )

    @app.get("/api/soundfont/instruments")
    async def list_gm_instruments() -> JSONResponse:
        """Return the 128 General MIDI instrument names organized by category."""
        GM_INSTRUMENTS = [
            # Piano (0-7)
            {"id": 0, "name": "Acoustic Grand Piano", "category": "Piano"},
            {"id": 1, "name": "Bright Acoustic Piano", "category": "Piano"},
            {"id": 2, "name": "Electric Grand Piano", "category": "Piano"},
            {"id": 3, "name": "Honky-tonk Piano", "category": "Piano"},
            {"id": 4, "name": "Electric Piano 1", "category": "Piano"},
            {"id": 5, "name": "Electric Piano 2", "category": "Piano"},
            {"id": 6, "name": "Harpsichord", "category": "Piano"},
            {"id": 7, "name": "Clavi", "category": "Piano"},
            # Chromatic Perc (8-15)
            {"id": 8, "name": "Celesta", "category": "Chromatic Perc"},
            {"id": 9, "name": "Glockenspiel", "category": "Chromatic Perc"},
            {"id": 10, "name": "Music Box", "category": "Chromatic Perc"},
            {"id": 11, "name": "Vibraphone", "category": "Chromatic Perc"},
            {"id": 12, "name": "Marimba", "category": "Chromatic Perc"},
            {"id": 13, "name": "Xylophone", "category": "Chromatic Perc"},
            {"id": 14, "name": "Tubular Bells", "category": "Chromatic Perc"},
            {"id": 15, "name": "Dulcimer", "category": "Chromatic Perc"},
            # Organ (16-23)
            {"id": 16, "name": "Drawbar Organ", "category": "Organ"},
            {"id": 17, "name": "Percussive Organ", "category": "Organ"},
            {"id": 18, "name": "Rock Organ", "category": "Organ"},
            {"id": 19, "name": "Church Organ", "category": "Organ"},
            {"id": 20, "name": "Reed Organ", "category": "Organ"},
            {"id": 21, "name": "Accordion", "category": "Organ"},
            {"id": 22, "name": "Harmonica", "category": "Organ"},
            {"id": 23, "name": "Tango Accordion", "category": "Organ"},
            # Guitar (24-31)
            {"id": 24, "name": "Acoustic Guitar (nylon)", "category": "Guitar"},
            {"id": 25, "name": "Acoustic Guitar (steel)", "category": "Guitar"},
            {"id": 26, "name": "Electric Guitar (jazz)", "category": "Guitar"},
            {"id": 27, "name": "Electric Guitar (clean)", "category": "Guitar"},
            {"id": 28, "name": "Electric Guitar (muted)", "category": "Guitar"},
            {"id": 29, "name": "Overdriven Guitar", "category": "Guitar"},
            {"id": 30, "name": "Distortion Guitar", "category": "Guitar"},
            {"id": 31, "name": "Guitar harmonics", "category": "Guitar"},
            # Bass (32-39)
            {"id": 32, "name": "Acoustic Bass", "category": "Bass"},
            {"id": 33, "name": "Electric Bass (finger)", "category": "Bass"},
            {"id": 34, "name": "Electric Bass (pick)", "category": "Bass"},
            {"id": 35, "name": "Fretless Bass", "category": "Bass"},
            {"id": 36, "name": "Slap Bass 1", "category": "Bass"},
            {"id": 37, "name": "Slap Bass 2", "category": "Bass"},
            {"id": 38, "name": "Synth Bass 1", "category": "Bass"},
            {"id": 39, "name": "Synth Bass 2", "category": "Bass"},
            # Strings (40-47)
            {"id": 40, "name": "Violin", "category": "Strings"},
            {"id": 41, "name": "Viola", "category": "Strings"},
            {"id": 42, "name": "Cello", "category": "Strings"},
            {"id": 43, "name": "Contrabass", "category": "Strings"},
            {"id": 44, "name": "Tremolo Strings", "category": "Strings"},
            {"id": 45, "name": "Pizzicato Strings", "category": "Strings"},
            {"id": 46, "name": "Orchestral Harp", "category": "Strings"},
            {"id": 47, "name": "Timpani", "category": "Strings"},
            # Ensemble (48-55)
            {"id": 48, "name": "String Ensemble 1", "category": "Ensemble"},
            {"id": 49, "name": "String Ensemble 2", "category": "Ensemble"},
            {"id": 50, "name": "Synth Strings 1", "category": "Ensemble"},
            {"id": 51, "name": "Synth Strings 2", "category": "Ensemble"},
            {"id": 52, "name": "Choir Aahs", "category": "Ensemble"},
            {"id": 53, "name": "Voice Oohs", "category": "Ensemble"},
            {"id": 54, "name": "Synth Voice", "category": "Ensemble"},
            {"id": 55, "name": "Orchestra Hit", "category": "Ensemble"},
            # Brass (56-63)
            {"id": 56, "name": "Trumpet", "category": "Brass"},
            {"id": 57, "name": "Trombone", "category": "Brass"},
            {"id": 58, "name": "Tuba", "category": "Brass"},
            {"id": 59, "name": "Muted Trumpet", "category": "Brass"},
            {"id": 60, "name": "French Horn", "category": "Brass"},
            {"id": 61, "name": "Brass Section", "category": "Brass"},
            {"id": 62, "name": "Synth Brass 1", "category": "Brass"},
            {"id": 63, "name": "Synth Brass 2", "category": "Brass"},
            # Reed (64-71)
            {"id": 64, "name": "Soprano Sax", "category": "Reed"},
            {"id": 65, "name": "Alto Sax", "category": "Reed"},
            {"id": 66, "name": "Tenor Sax", "category": "Reed"},
            {"id": 67, "name": "Baritone Sax", "category": "Reed"},
            {"id": 68, "name": "Oboe", "category": "Reed"},
            {"id": 69, "name": "English Horn", "category": "Reed"},
            {"id": 70, "name": "Bassoon", "category": "Reed"},
            {"id": 71, "name": "Clarinet", "category": "Reed"},
            # Pipe (72-79)
            {"id": 72, "name": "Piccolo", "category": "Pipe"},
            {"id": 73, "name": "Flute", "category": "Pipe"},
            {"id": 74, "name": "Recorder", "category": "Pipe"},
            {"id": 75, "name": "Pan Flute", "category": "Pipe"},
            {"id": 76, "name": "Blown Bottle", "category": "Pipe"},
            {"id": 77, "name": "Shakuhachi", "category": "Pipe"},
            {"id": 78, "name": "Whistle", "category": "Pipe"},
            {"id": 79, "name": "Ocarina", "category": "Pipe"},
            # Synth Lead (80-87)
            {"id": 80, "name": "Lead 1 (square)", "category": "Synth Lead"},
            {"id": 81, "name": "Lead 2 (sawtooth)", "category": "Synth Lead"},
            {"id": 82, "name": "Lead 3 (calliope)", "category": "Synth Lead"},
            {"id": 83, "name": "Lead 4 (chiff)", "category": "Synth Lead"},
            {"id": 84, "name": "Lead 5 (charang)", "category": "Synth Lead"},
            {"id": 85, "name": "Lead 6 (voice)", "category": "Synth Lead"},
            {"id": 86, "name": "Lead 7 (fifths)", "category": "Synth Lead"},
            {"id": 87, "name": "Lead 8 (bass + lead)", "category": "Synth Lead"},
            # Synth Pad (88-95)
            {"id": 88, "name": "Pad 1 (new age)", "category": "Synth Pad"},
            {"id": 89, "name": "Pad 2 (warm)", "category": "Synth Pad"},
            {"id": 90, "name": "Pad 3 (polysynth)", "category": "Synth Pad"},
            {"id": 91, "name": "Pad 4 (choir)", "category": "Synth Pad"},
            {"id": 92, "name": "Pad 5 (bowed)", "category": "Synth Pad"},
            {"id": 93, "name": "Pad 6 (metallic)", "category": "Synth Pad"},
            {"id": 94, "name": "Pad 7 (halo)", "category": "Synth Pad"},
            {"id": 95, "name": "Pad 8 (sweep)", "category": "Synth Pad"},
            # Synth Effects (96-103)
            {"id": 96, "name": "FX 1 (rain)", "category": "Synth FX"},
            {"id": 97, "name": "FX 2 (soundtrack)", "category": "Synth FX"},
            {"id": 98, "name": "FX 3 (crystal)", "category": "Synth FX"},
            {"id": 99, "name": "FX 4 (atmosphere)", "category": "Synth FX"},
            {"id": 100, "name": "FX 5 (brightness)", "category": "Synth FX"},
            {"id": 101, "name": "FX 6 (goblins)", "category": "Synth FX"},
            {"id": 102, "name": "FX 7 (echoes)", "category": "Synth FX"},
            {"id": 103, "name": "FX 8 (sci-fi)", "category": "Synth FX"},
            # Ethnic (104-111)
            {"id": 104, "name": "Sitar", "category": "Ethnic"},
            {"id": 105, "name": "Banjo", "category": "Ethnic"},
            {"id": 106, "name": "Shamisen", "category": "Ethnic"},
            {"id": 107, "name": "Koto", "category": "Ethnic"},
            {"id": 108, "name": "Kalimba", "category": "Ethnic"},
            {"id": 109, "name": "Bag pipe", "category": "Ethnic"},
            {"id": 110, "name": "Fiddle", "category": "Ethnic"},
            {"id": 111, "name": "Shanai", "category": "Ethnic"},
            # Percussive (112-119)
            {"id": 112, "name": "Tinkle Bell", "category": "Percussive"},
            {"id": 113, "name": "Agogo", "category": "Percussive"},
            {"id": 114, "name": "Steel Drums", "category": "Percussive"},
            {"id": 115, "name": "Woodblock", "category": "Percussive"},
            {"id": 116, "name": "Taiko Drum", "category": "Percussive"},
            {"id": 117, "name": "Melodic Tom", "category": "Percussive"},
            {"id": 118, "name": "Synth Drum", "category": "Percussive"},
            {"id": 119, "name": "Reverse Cymbal", "category": "Percussive"},
            # Sound Effects (120-127)
            {"id": 120, "name": "Guitar Fret Noise", "category": "Sound FX"},
            {"id": 121, "name": "Breath Noise", "category": "Sound FX"},
            {"id": 122, "name": "Seashore", "category": "Sound FX"},
            {"id": 123, "name": "Bird Tweet", "category": "Sound FX"},
            {"id": 124, "name": "Telephone Ring", "category": "Sound FX"},
            {"id": 125, "name": "Helicopter", "category": "Sound FX"},
            {"id": 126, "name": "Applause", "category": "Sound FX"},
            {"id": 127, "name": "Gunshot", "category": "Sound FX"},
        ]
        return JSONResponse(GM_INSTRUMENTS)

    @app.get("/api/soundfonts")
    async def list_soundfonts() -> JSONResponse:
        """List all available soundfonts."""
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        result = []
        if sf_dir.exists():
            for p in sorted(sf_dir.iterdir()):
                if p.suffix.lower() in {".sf2", ".sf3", ".dls"}:
                    result.append({
                        "name": p.name,
                        "size_mb": round(p.stat().st_size / 1_048_576, 1),
                        "active": p.name == Path(cfg.get("active_soundfont", "")).name,
                        "path": str(p),
                    })
        return JSONResponse(result)

    @app.delete("/api/soundfonts/{sf_name}")
    async def delete_soundfont(sf_name: str) -> JSONResponse:
        """Delete a soundfont file."""
        _require_admin(app)
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        filepath = sf_dir / sf_name
        try:
            filepath.resolve().relative_to(sf_dir.resolve())
        except ValueError:
            raise HTTPException(403, "Path traversal not allowed")

        if not filepath.exists():
            raise HTTPException(404, f"Soundfont not found: {sf_name}")

        try:
            filepath.unlink()
        except OSError as exc:
            raise HTTPException(500, f"Could not delete file: {exc}")

        return JSONResponse({"status": "deleted", "name": sf_name})

    @app.post("/api/soundfonts/upload")
    async def upload_soundfont(file: UploadFile) -> JSONResponse:
        """Upload a new soundfont file."""
        _require_admin(app)
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        sf_dir.mkdir(parents=True, exist_ok=True)

        fname = Path(file.filename or "upload.sf2").name
        if Path(fname).suffix.lower() not in _SUPPORTED_SOUNDFONT_EXTS:
            raise HTTPException(400, "Only .sf2, .sf3, and .dls files are accepted")

        dest = sf_dir / fname
        # Confine the destination to the soundfonts directory.
        try:
            dest.resolve().relative_to(sf_dir.resolve())
        except ValueError:
            raise HTTPException(403, "Path traversal not allowed")
        content = await _read_upload_limited(file, _MAX_SOUNDFONT_UPLOAD_BYTES)
        try:
            dest.write_bytes(content)
        except OSError as exc:
            raise HTTPException(500, f"Failed to save file: {exc}")

        return JSONResponse({
            "status": "uploaded",
            "name": fname,
            "size_mb": round(len(content) / 1_048_576, 1),
        })

    @app.post("/api/soundfonts/{sf_name}/activate")
    async def activate_soundfont(sf_name: str) -> JSONResponse:
        """Set a soundfont as the active one for new songs."""
        _require_admin(app)
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        filepath = sf_dir / sf_name
        # Same traversal guard as delete_soundfont — never activate (and later
        # serve) a path outside the soundfonts directory.
        try:
            filepath.resolve().relative_to(sf_dir.resolve())
        except ValueError:
            raise HTTPException(403, "Path traversal not allowed")
        if not filepath.exists():
            raise HTTPException(404, f"Soundfont not found: {sf_name}")

        _settings.save({"active_soundfont": str(filepath)})
        return JSONResponse({"status": "activated", "name": sf_name})

    @app.get("/api/settings")
    async def get_settings() -> JSONResponse:
        """Get current server settings (admin-only in multi-user mode).

        These are server-global settings that also expose filesystem paths, so
        in multi-user mode they are restricted to admins.
        """
        _require_admin(app)
        cfg = _settings.load()
        # Always reflect the runtime-active directory (may differ from config.json
        # when the server was launched with --dir).
        cfg["partitions_dir"] = str(app.state.fixtures_dir)  # type: ignore[attr-defined]
        return JSONResponse(cfg)

    @app.post("/api/settings")
    async def update_settings(request: Request) -> JSONResponse:
        """Update server settings (admin-only in multi-user mode). Partial update.

        Changing the storage backend or its configuration rebuilds the active
        backend in place (falling back to local if the new config is invalid).
        Credentials are never accepted here — they live in the env / secrets
        file (see fretwise.storage.credentials).
        """
        _require_admin(app)
        try:
            body = await request.json()
        except Exception:
            raise HTTPException(400, "Invalid JSON body")

        if "partitions_dir" in body:
            p = Path(body["partitions_dir"])
            if not p.exists():
                raise HTTPException(400, f"Directory not found: {body['partitions_dir']}")
            app.state.fixtures_dir = p

        updated = _settings.save(body)

        # Rebuild the storage backend when anything storage-related changed.
        storage_keys = {
            "partitions_dir", "storage_backend", "storage_cache_dir",
            "storage_s3", "storage_webdav", "storage_gdrive",
        }
        if storage_keys & set(body):
            _set_storage_backend(app, updated, app.state.fixtures_dir)

        return JSONResponse(updated)

    @app.get("/api/storage")
    async def storage_status() -> JSONResponse:
        """Report the active storage backend and its health.

        In multi-user mode this reflects the logged-in user's own backend, and
        reports ``configured: false`` (rather than erroring) when they have not
        connected storage yet.
        """
        try:
            storage = _current_storage(app)
        except HTTPException as exc:
            if exc.status_code == 409:  # storage not configured for this user
                return JSONResponse({"configured": False, "backend": None})
            raise
        return JSONResponse({
            "configured": True,
            "backend": storage.name,
            "supports_batch_refresh": storage.supports_batch_refresh,
            "local_root": str(storage.local_root) if storage.local_root else None,
            "error": getattr(app.state, "storage_error", None),
        })

    @app.get("/api/song-info/{filename}")
    async def get_song_info(filename: str) -> JSONResponse:
        """Get full metadata for a specific song from the index and gears sheet."""
        songs = _load_catalog(app)
        stem = Path(filename).stem
        info = dict(songs.get(filename) or songs.get(stem) or {})
        gear_info = _gears_song_info_for(filename)
        for key, value in gear_info.items():
            if value is not None and str(value).strip() and not str(info.get(key, "")).strip():
                info[key] = value
        if not info:
            raise HTTPException(404, f"No metadata found for '{filename}'")
        return JSONResponse(info)

    @app.get("/api/songs/export-list")
    async def export_song_list(download: int = Query(0)) -> JSONResponse:
        """Export the user's scores as a JSON list for LLM metadata enrichment.

        Returns ``{"songs": [{"filename", "title", "artist"}], "count": N}`` —
        one entry per score in the user's storage, with ``title``/``artist``
        derived from the filename. ``?download=1`` adds a
        ``Content-Disposition`` attachment header so the browser saves it as
        ``fretwise-songs.json``.
        """
        storage: StorageBackend = _current_storage(app)
        try:
            objects = storage.list_scores()
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        songs = []
        for obj in objects:
            parsed = parse_filename_metadata(obj.name)
            songs.append({
                "filename": obj.name,
                "title": parsed.get("title", ""),
                "artist": parsed.get("artist", ""),
            })

        headers = {}
        if download:
            headers["Content-Disposition"] = (
                'attachment; filename="fretwise-songs.json"'
            )
        return JSONResponse({"songs": songs, "count": len(songs)}, headers=headers)

    @app.get("/api/songs/prompt")
    async def get_metadata_prompt() -> Response:
        """Serve the LLM prompt used to enrich song metadata (Markdown download)."""
        return Response(
            content=METADATA_PROMPT,
            media_type="text/markdown",
            headers={
                "Content-Disposition": 'attachment; filename="fretwise-metadata-prompt.md"',
            },
        )

    @app.post("/api/songs/import")
    async def import_song_metadata(request: Request) -> JSONResponse:
        """Merge LLM-produced metadata into the user's ``songs.tsv`` catalog.

        Accepts either a top-level JSON array or ``{"songs": [...]}`` of objects
        with keys ``filename`` (required), ``title``, ``artist``, ``album``,
        ``genre``, ``year``, ``notes`` (extra keys are ignored). Rows are upserted
        by ``filename`` into the catalog, which is persisted to storage.

        Returns ``{"updated": N, "added": A, "total": M}``.
        """
        try:
            payload = await request.json()
        except Exception as exc:  # noqa: BLE001 - any decode error -> 400
            raise HTTPException(400, f"Invalid JSON body: {exc}")

        if isinstance(payload, dict) and "songs" in payload:
            payload = payload["songs"]
        if not isinstance(payload, list):
            raise HTTPException(400, "Body must be a JSON array (or {\"songs\": [...]})")
        incoming = [item for item in payload if isinstance(item, dict)]

        storage: StorageBackend = _current_storage(app)
        try:
            existing = storage.read_bytes(CATALOG_NAME).decode("utf-8-sig")
        except StorageNotFoundError:
            existing = ""
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        text, updated, added = merge_catalog(existing, incoming)
        try:
            storage.write_bytes(CATALOG_NAME, text.encode("utf-8"))
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        # load_index_from_text indexes by filename AND stem; count unique rows.
        total = len({
            row.get("filename") for row in load_index_from_text(text).values()
        })
        return JSONResponse({"updated": updated, "added": added, "total": total})

    # -- Fingering review & continuous improvement ----------------------------

    @app.get("/api/review/{filename}")
    def review_file(
        filename: str, track_id: int | None = Query(None)
    ) -> dict[str, Any]:
        """List impossible / suspect / high-cost fingerings, ranked by severity."""
        from fretwise.review import Severity, flag_fingerings

        filepath = _resolve_file(app, filename)
        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")
        if _track_kind(adapter, filepath, track_id) != KIND_GUITAR:
            return {"available": False, "reason": "not a guitar track",
                    "items": [], "counts": {}}
        payload = _run_legacy_pipeline_with_guard(
            events, rule_preferences=RulePreferences(),
            feedback=_song_feedback(app, filepath),
        )
        report = flag_fingerings(
            payload.results, biomech_report=payload.biomechanical_report,
        )
        items = report.items
        counts = report.counts
        # When the whole-piece audit is "clean", a long list of HIGH_COST notes
        # contradicts the "all OK" banner and is just noise. Suppress cost-only
        # items in that case; always keep IMPOSSIBLE / SUSPECT (biomechanical)
        # items, which are real playability problems regardless of the verdict.
        try:
            section_markers = dict(getattr(adapter, "section_markers", {}) or {})
            audit_report = audit_score(
                events, payload.results,
                section_markers=section_markers or None,
                ml_cost_model=_get_player_cost_model(),
            )
            if audit_report.overall == "clean":
                items = [it for it in items if it.severity != Severity.HIGH_COST]
                from collections import Counter as _Counter
                counts = dict(_Counter(str(it.severity) for it in items))
        except Exception:  # noqa: BLE001 — gating is best-effort, never fatal
            pass
        return {
            "available": True,
            "filename": filename,
            "track_id": track_id,
            "counts": counts,
            "truncated": report.truncated,
            "items": [_serialize_review_item(it) for it in items],
        }

    @app.get("/api/review/{filename}/alternatives")
    def review_alternatives_endpoint(
        filename: str,
        measure_index: int = Query(...),
        track_id: int | None = Query(None),
    ) -> dict[str, Any]:
        """Return up to N distinct, playable fingerings for a measure."""
        from fretwise.review import measure_alternatives

        filepath = _resolve_file(app, filename)
        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")
        payload = _run_legacy_pipeline_with_guard(
            events, rule_preferences=RulePreferences(),
            feedback=_song_feedback(app, filepath),
        )
        alts = measure_alternatives(
            events, payload.results, measure_index,
            player_cost_model=_get_player_cost_model(),
            chord_finger_classifier=_get_chord_finger_classifier(),
        )
        requested = int(_fw_config().review.alternatives.count)
        # Tempo + open-string tuning let the frontend build a hand-visualisation
        # payload for each fingering (the compact tab notation alone is hard to
        # read). Tuning is derived from the source hints (handles dropped/capo'd
        # tunings), falling back to standard 6-string.
        tuning = [40, 45, 50, 55, 59, 64]
        seen_strings: dict[int, int] = {}
        for e in events:
            if (
                e.string_hint is not None and e.fret_hint is not None
                and 1 <= e.string_hint <= len(tuning)
                and e.string_hint not in seen_strings
            ):
                seen_strings[e.string_hint] = e.pitch - e.fret_hint
        for s, open_pitch in seen_strings.items():
            tuning[s - 1] = open_pitch
        return {
            "filename": filename,
            "measure_index": measure_index,
            "requested": requested,
            "incomplete": len(alts) < requested,
            "tempo": events[0].tempo if events else 120.0,
            "tuning": tuning,
            "alternatives": [_serialize_alternative(a) for a in alts],
        }

    @app.post("/api/review/{filename}/choice")
    async def review_choice(
        filename: str, request: Request, track_id: int | None = Query(None),
    ) -> JSONResponse:
        """Persist a user's preferred fingering and re-bias future solves.

        Saves a per-song sidecar entry and one retrain-ready corpus line, then
        clears the solve caches so the next solve reflects the choice.
        """
        import hashlib
        from datetime import UTC, datetime

        from fretwise.review import (
            FeedbackRecord,
            append_corpus,
            save_choice,
        )

        try:
            body = await request.json()
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"Invalid JSON body: {exc}")
        if not isinstance(body, dict):
            raise HTTPException(400, "Body must be a JSON object")

        chosen = body.get("chosen") or []
        rejected = body.get("rejected") or []
        if not isinstance(chosen, list) or not chosen:
            raise HTTPException(400, "Body must include a non-empty 'chosen' list")

        filepath = _resolve_file(app, filename)
        user = current_request_user()
        user_id = getattr(user, "email", None) or getattr(user, "id", None) or "local"

        # Best-effort features from an unbiased baseline solve (for retraining).
        features_chosen: dict[str, float] = {}
        features_rejected: dict[str, float] = {}
        song_hash = ""
        try:
            _, events = _load_adapter_and_events(filepath, track_id=track_id)
            results, _ = _run_legacy_pipeline(events, rule_preferences=RulePreferences())
            if chosen and isinstance(chosen[0], dict) and "note_id" in chosen[0]:
                features_chosen = _features_for(results, int(chosen[0]["note_id"]))
            if rejected and isinstance(rejected[0], dict) and "note_id" in rejected[0]:
                features_rejected = _features_for(results, int(rejected[0]["note_id"]))
            song_hash = "sha1:" + hashlib.sha1(filepath.read_bytes()).hexdigest()[:16]
        except Exception:  # noqa: BLE001 — provenance/features are best-effort
            pass

        record = FeedbackRecord(
            song_stem=filepath.stem,
            measure_index=int(body.get("measure_index", 0)),
            onset=float(body.get("onset", 0.0)),
            severity=str(body.get("severity", "")),
            chosen=chosen,
            rejected=rejected if isinstance(rejected, list) else [],
            created_at=datetime.now(UTC).isoformat(),
            user_id=str(user_id),
            song_hash=song_hash,
            track_id=track_id,
            reasons=body.get("reasons") or [],
            context=body.get("context") or {},
            alternatives_offered=body.get("alternatives_offered") or [],
            features_chosen=features_chosen,
            features_rejected=features_rejected,
        )
        base_dir = _feedback_base_dir(app, filepath)
        try:
            save_choice(base_dir, record)
            append_corpus(base_dir, record)
        except OSError as exc:
            raise HTTPException(500, f"Could not persist feedback: {exc}")

        _solve_cache_clear()  # next solve picks up the new lock/bias
        return JSONResponse({"saved": True, "stem": filepath.stem})


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _require_admin(app: FastAPI) -> None:
    """Guard server-global operations.

    Single-user mode: no-op (the operator is the only user). Multi-user mode:
    require an authenticated **admin** (``FRETWISE_ADMIN_EMAILS``). Regular users
    must not be able to mutate server-wide settings, soundfonts, or the local
    library batch.
    """
    if not getattr(app.state, "multiuser", False):
        return
    user = current_request_user()
    if user is None:
        raise HTTPException(401, "Authentication required")
    if not user.is_admin:
        raise HTTPException(403, "Admin privileges required")


def _current_storage(app: FastAPI) -> StorageBackend:
    """Return the storage backend serving the current request.

    Single-user mode: the process-wide backend (``app.state.storage``).
    Multi-user mode: the logged-in user's *own* cloud backend, resolved fresh
    from their (non-secret) config + decrypted credentials — never shared with
    other users, and never the on-server local backend.
    """
    if not getattr(app.state, "multiuser", False):
        return app.state.storage
    user = current_request_user()
    if user is None:
        raise HTTPException(401, "Authentication required")
    credentials = app.state.secrets_store.get(user.id)
    try:
        return resolve_user_storage(
            user, credentials,
            cache_root=app.state.cache_root,
            local_root=app.state.fixtures_dir,  # admin-only server-local library
        )
    except StorageNotConfigured as exc:
        raise HTTPException(409, str(exc))
    except StorageError as exc:
        raise HTTPException(400, f"Storage error: {exc}")


def _feedback_base_dir(app: FastAPI, filepath: Path) -> Path:
    """Resolve the ``.fretwise_feedback`` directory for the current request.

    Prefers the active storage backend's local root; falls back to the score's
    own parent directory (covers cloud backends without a local root).
    """
    from fretwise.review import feedback_dir

    try:
        root = _current_storage(app).local_root
    except HTTPException:
        root = None
    return feedback_dir(root if root is not None else filepath.parent)


def _song_feedback(app: FastAPI, filepath: Path) -> object | None:
    """Load recorded feedback for a song, or ``None`` when re-bias is disabled.

    Returns a truthy :class:`fretwise.review.SongFeedback` only when the review
    bias feature is enabled and at least one choice exists, so callers can treat
    ``None`` as "no re-bias".
    """
    from fretwise.config import config as _config
    from fretwise.review import load_song_feedback

    if not bool(_config().review.bias.enabled):
        return None
    fb = load_song_feedback(_feedback_base_dir(app, filepath), filepath.stem)
    return fb if fb else None


_FINGER_MODEL_INDEX: dict[str, int] = {
    "open": 0, "index": 1, "middle": 2, "ring": 3, "pinky": 4,
}


def _serialize_review_item(item: Any) -> dict[str, Any]:
    """Serialize a :class:`fretwise.review.ReviewItem` for the API."""
    return {
        "item_id": item.item_id,
        "measure_index": item.measure_index,
        "onset": item.onset,
        "note_ids": item.note_ids,
        "severity": item.severity.value,
        "score": item.score,
        "reasons": item.reasons,
        "current": item.current,
    }


def _serialize_alternative(alt: Any) -> dict[str, Any]:
    """Serialize a :class:`fretwise.review.MeasureAlternative` for the API."""
    return {
        "variant_id": alt.variant_id,
        "is_current": alt.is_current,
        "fingerings": alt.fingerings,
        "cost": alt.cost,
        "label": alt.label,
        "playable": alt.playable,
    }


def _features_for(results: list[FingeringResult], note_id: int) -> dict[str, float]:
    """Best-effort transition features for ``note_id`` (retrain-ready, may be empty).

    Finds the note's in-voice predecessor and extracts the same 26 features used
    by the learned transition-cost model, so feedback rows can be replayed for
    offline retraining. Returns ``{}`` when the note or a predecessor is missing.
    """
    try:
        from fretwise.ml import extract_transition_features

        by_id = {r.note_id: r for r in results}
        cur = by_id.get(note_id)
        if cur is None:
            return {}
        voice = cur.note_event.voice_hint or 0
        prev: FingeringResult | None = None
        for r in sorted(results, key=lambda x: x.note_event.onset):
            if (r.note_event.voice_hint or 0) != voice:
                continue
            if r.note_event.onset >= cur.note_event.onset:
                break
            prev = r
        if prev is None:
            return {}
        return extract_transition_features(
            prev_string_model=prev.state.string_num - 1,
            prev_fret=prev.state.fret,
            prev_finger_model=_FINGER_MODEL_INDEX.get(prev.state.finger.value, 0),
            curr_string_model=cur.state.string_num - 1,
            curr_fret=cur.state.fret,
            prev_midi=prev.note_event.pitch,
            curr_midi=cur.note_event.pitch,
        )
    except Exception:  # pragma: no cover — features are best-effort
        return {}


def _load_catalog(app: FastAPI) -> dict[str, dict[str, Any]]:
    """Load the song-metadata catalog for the current request.

    Multi-user mode: read ``songs.tsv`` from the logged-in user's own storage
    backend, falling back to the ``index_path`` setting if the user has no
    catalog yet (or storage is not configured/unavailable). Single-user mode:
    read the configured ``index_path`` file directly.
    """
    if getattr(app.state, "multiuser", False):
        try:
            storage = _current_storage(app)
            data = storage.read_bytes(CATALOG_NAME)
            return load_index_from_text(data.decode("utf-8-sig"))
        except (StorageNotFoundError, HTTPException, StorageError, UnicodeError):
            pass  # fall through to the configured local index_path
    return load_index(_settings.load().get("index_path", ""))


def _rig_bank_json_path(app: FastAPI) -> Path:
    """Return the structured GP-180 bank path for the current local library."""

    rigs_dir = find_rigs_dir(app.state.fixtures_dir)
    if rigs_dir is None:
        rigs_dir = app.state.fixtures_dir / "rigs"
    return rig_bank_path(rigs_dir)


def _gears_root() -> Path:
    """Return the flat ``data/gears`` directory holding new-format rig sheets.

    Honours a ``gears_dir`` setting so the library can be relocated (and tests can
    point at a temp dir); defaults to ``<repo>/data/gears``.
    """

    configured = (_settings.load().get("gears_dir") or "").strip()
    if configured:
        path = Path(configured)
        # An explicitly configured directory is honoured as-is (even when empty):
        # the user/library chose it. Only fall back to the bundled sheets when the
        # configured path is missing or not a directory (mis-configuration).
        if path.is_dir():
            return path
    return Path(__file__).resolve().parents[3] / "data" / "gears"


def _gears_canonical_key(stem: str) -> str:
    """Canonicalize a gears filename stem to the shared ``artist__title`` key.

    Tolerates either naming style — kebab (``ac-dc__highway-to-hell``) or the
    SongsGear export's underscored Title Case (``AC_DC__Highway_To_Hell``) — by
    splitting on ``__`` and re-slugifying each half.
    """

    if "__" in stem:
        artist, title = stem.split("__", 1)
        return _gears_key(artist, title)
    return _gears_key("", stem)


def _gears_index(root: Path) -> dict[str, Path]:
    """Map canonical ``artist__title`` keys to gears files in ``root``.

    Built per request (cheap for the expected catalog sizes); the first file
    wins on a key collision so a clean name beats a malformed duplicate.
    """

    index: dict[str, Path] = {}
    for path in sorted(root.glob("*.json")):
        index.setdefault(_gears_canonical_key(path.stem), path)
    return index


def _gears_resolve_path(filename: str) -> Path | None:
    """Resolve a score filename to its gears sheet path, or None if absent.

    Resolves by the canonical ``artist__title`` key (naming-style agnostic);
    falls back to a title-slug-only match so a song whose score file omits the
    artist still resolves when exactly one sheet matches.
    """

    root = _gears_root()
    if not root.is_dir():
        return None
    key = gears_key_from_filename(filename)
    index = _gears_index(root)
    candidate = index.get(key)
    if candidate is None:
        title_slug = key.split("__", 1)[-1]
        matches = [p for k, p in index.items() if title_slug and k.split("__", 1)[-1] == title_slug]
        if len(matches) != 1:
            return None
        candidate = matches[0]
    return candidate


def _gears_raw_doc_for(filename: str) -> dict | None:
    """Load the raw JSON gears document for a score filename, or None if absent."""

    candidate = _gears_resolve_path(filename)
    if candidate is None:
        return None
    try:
        return _json.loads(candidate.read_text(encoding="utf-8"))
    except (OSError, _json.JSONDecodeError):
        return None


def _gears_view_for(filename: str) -> dict | None:
    """Load the new-format gears sheet for a score filename, or None if absent."""

    doc = _gears_raw_doc_for(filename)
    if doc is None:
        return None
    return song_output_to_view(doc)


def _gears_song_info_for(filename: str) -> dict[str, Any]:
    """Build song-info metadata from the renderable gears sheet, when present."""

    view = _gears_view_for(filename)
    if view is None:
        return {}
    research = view.get("original_gear_research")
    research = research if isinstance(research, dict) else {}
    return {
        "title": view.get("song"),
        "artist": view.get("artist"),
        "album": view.get("album"),
        "genre": view.get("genre"),
        "year": view.get("year"),
        "guitarists": research.get("guitarist"),
        "original_guitar": (
            research.get("guitar_model")
            or research.get("guitar_type")
            or view.get("guitare_originale")
        ),
        "guitar_type": research.get("guitar_type"),
        "gear_confidence": research.get("confidence") or view.get("confidence"),
        "target_tone": view.get("comments"),
        "rig_grade": view.get("fiabilite"),
    }


def _resolve_rig_bank_request(
    app: FastAPI,
    body: Mapping[str, object],
) -> RigResolution | None:
    """Resolve a rig-bank request using explicit fields plus file metadata."""

    bank, context = _rig_bank_context_from_request(app, body)
    return bank.resolve(**context)


def _rig_bank_context_from_request(
    app: FastAPI,
    body: Mapping[str, object],
) -> tuple[RigBank, dict[str, str | None]]:
    """Load the rig bank and build song/artist/genre/profile context."""

    if not isinstance(body, dict):
        raise RigBankError("rig-bank request body must be an object")

    path = _rig_bank_json_path(app)
    bank = load_rig_bank(path)

    filename = _body_text(body, "filename")
    explicit_song = _body_text(body, "song") or _body_text(body, "title")
    explicit_artist = _body_text(body, "artist")
    explicit_genre = _body_text(body, "genre")
    song = explicit_song
    artist = explicit_artist
    genre = explicit_genre
    profile_id = _body_text(body, "profile_id")

    if filename:
        meta = parse_filename_metadata(filename)
        song = song or meta.get("title", "")
        artist = artist or meta.get("artist", "")
        catalog = _load_catalog(app)
        catalog_row = catalog.get(filename) or catalog.get(Path(filename).stem)
        if catalog_row:
            catalog_title = str(catalog_row.get("title") or "").strip()
            catalog_artist = str(catalog_row.get("artist") or "").strip()
            catalog_genre = str(catalog_row.get("genre") or "").strip()
            song = explicit_song or catalog_title or song
            artist = explicit_artist or catalog_artist or artist
            genre = explicit_genre or catalog_genre or genre

    return bank, {
        "song": song or None,
        "artist": artist or None,
        "genre": genre or None,
        "profile_id": profile_id or None,
    }


def _body_text(body: Mapping[str, object], key: str) -> str:
    raw = body.get(key)
    if raw is None:
        return ""
    return str(raw).strip()


def _target_rig_modules_from_request(body: Mapping[str, object]) -> tuple[RigModule, ...]:
    """Parse optional active rig modules supplied by the recommendation client."""

    raw_modules = body.get("rig_modules")
    if raw_modules is None:
        return ()
    if not isinstance(raw_modules, list):
        raise RigBankError("rig_modules must be a list")
    modules: list[RigModule] = []
    for item in raw_modules:
        if not isinstance(item, dict):
            raise RigBankError("each rig_modules item must be an object")
        modules.append(RigModule.from_json(item))
    return tuple(modules)


def _target_rig_modules_from_view(view: Mapping[str, object] | None) -> tuple[RigModule, ...]:
    """Extract active module/model pairs from a rendered AI gear sheet."""

    if not isinstance(view, dict):
        return ()
    settings = view.get("reglages")
    if not isinstance(settings, dict):
        return ()
    modules: list[RigModule] = []
    for module_name, raw_setting in settings.items():
        if not isinstance(raw_setting, dict) or raw_setting.get("active") is not True:
            continue
        model = str(raw_setting.get("preset") or "").strip()
        if model:
            modules.append(RigModule(module=str(module_name), model=model))
    return tuple(modules)


def _resolve_file(app: FastAPI, filename: str) -> Path:
    """Resolve a filename to a readable local score path via the storage backend.

    Guards (all enforced by the storage layer):
      1. The name is reduced to a basename with a supported score extension —
         no traversal, no absolute paths, no arbitrary file types.
      2. The object must exist in the active store.
      3. For cloud backends the object is downloaded into a local cache and the
         cached path is returned, so parsers (which need a real file) work
         transparently. For the local backend the real path is returned.
    """
    storage: StorageBackend = _current_storage(app)
    try:
        safe_name = safe_score_name(filename)
    except StorageValidationError as exc:
        raise HTTPException(400, str(exc))
    if not storage.exists(safe_name):
        raise HTTPException(404, f"File not found: {safe_name}")
    try:
        return storage.ensure_local(safe_name)
    except StorageNotFoundError:
        raise HTTPException(404, f"File not found: {safe_name}")
    except StorageError as exc:
        raise HTTPException(502, f"Storage error: {exc}")


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """Read an upload into memory, aborting with HTTP 413 past *max_bytes*.

    Streams the body in chunks so an oversized (or maliciously huge) upload is
    rejected before it can exhaust process memory.
    """
    chunks: list[bytes] = []
    total = 0
    while True:
        chunk = await file.read(1024 * 1024)
        if not chunk:
            break
        total += len(chunk)
        if total > max_bytes:
            raise HTTPException(
                413,
                f"File too large (limit {max_bytes // (1024 * 1024)} MiB)",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _load_adapter_and_events(
    filepath: Path,
    *,
    track_id: int | None = None,
) -> tuple[Any, list[NoteEvent]]:
    try:
        adapter = get_adapter(filepath)
    except UnsupportedFormatError as exc:
        raise HTTPException(400, str(exc))

    try:
        if track_id is not None and hasattr(adapter, "parse_track"):
            events = adapter.parse_track(filepath, track_id)
        else:
            events = adapter.parse(filepath)
    except (ParseError, UnsupportedFormatError) as exc:
        raise HTTPException(400, str(exc))
    return adapter, events


def _measure_beats_array(adapter: Any, events: list[NoteEvent]) -> list[float]:
    """Per-measure length in quarter-note beats, 0-based (index i = measure i+1).

    Built from ``adapter.measure_time_signatures`` ({1-based measure → (num, den)}),
    carrying the last seen signature forward for measures that don't restate it.
    Returns ``[]`` when the adapter exposes no per-measure signatures
    (MusicXML/MIDI), so the player keeps its uniform ``beats_per_measure`` fallback.

    Why this exists: the multi-track player reconstructs each measure's start as
    ``floor(onset / beats_per_measure) * beats_per_measure`` from a single scalar.
    That drifts after any meter change or short (pickup) bar — desyncing the
    cursor from the audio and the tracks from one another. Shipping the true
    per-measure beat counts lets the player place every measure exactly.
    """
    mts = getattr(adapter, "measure_time_signatures", None) or {}
    if not mts:
        return []
    default = float(getattr(adapter, "beats_per_measure", 4.0) or 4.0)
    max_measure = max(mts.keys())
    if events:
        max_measure = max(max_measure, max((e.measure_index or 0) for e in events))
    out: list[float] = []
    last = default
    for measure in range(1, max_measure + 1):
        ts = mts.get(measure)
        if ts:
            numerator, denominator = ts
            if numerator > 0 and denominator > 0:
                last = numerator * 4.0 / denominator
        out.append(last)
    return out


_GM_BANK_HINT = re.compile(
    r"general|(?:^|[^a-z])gm(?:[^a-z]|$)|sgm|fluid|arachno|timbres|musescore",
    re.IGNORECASE,
)


def _prefer_gm_bank(banks: list[Path]) -> Path | None:
    """Pick the default soundfont, preferring a General MIDI bank.

    Falling back to the alphabetically-first file picks a non-GM bank (e.g. a
    "…Guitar Samples Collection" or an arcade pack) that lacks GM programs for
    bass/drums/keys — the browser synth then collapses every track onto preset 0
    (often DRUMS), so tabs sound wrong regardless of which soundfont the user
    later tries. A GM-looking filename ("general", "gm", "sgm", "fluid",
    "arachno", …) is the safe default; otherwise keep the first available.

    Args:
        banks: Candidate soundfont paths (already filtered to sf2/sf3/dls),
               ideally pre-sorted for a deterministic fallback.

    Returns:
        The preferred bank, or ``None`` when the list is empty.
    """
    for bank in banks:
        if _GM_BANK_HINT.search(bank.stem):
            return bank
    return banks[0] if banks else None


def _measure_tempo_array(adapter: Any, events: list[NoteEvent]) -> list[float]:
    """Per-measure tempo in BPM, 0-based (index i = measure i+1).

    Built from the per-note ``tempo`` carried by every :class:`NoteEvent`, taking
    the tempo in force at the start of each measure and carrying the last seen
    value forward across rest bars. Returns ``[]`` when no per-note tempo is
    available, so the player keeps its single scalar ``tempo`` fallback.

    Why this exists: the player used to reconstruct the whole timeline from one
    scalar tempo (``events[0].tempo``). Any mid-song tempo change (a
    ritardando, a faster chorus) then desynced the cursor and the audio from the
    real music — the dominant cause of the tracks drifting apart on songs that
    change tempo. Shipping the real per-measure tempo lets the player place every
    measure at its true wall-clock time.
    """
    if not events:
        return []
    by_measure: dict[int, float] = {}
    for ev in events:
        mi = ev.measure_index or 0
        tempo = float(getattr(ev, "tempo", 0.0) or 0.0)
        if mi <= 0 or tempo <= 0:
            continue
        # First event of the measure wins (tempo in force at the downbeat).
        if mi not in by_measure:
            by_measure[mi] = tempo
    if not by_measure:
        return []
    max_measure = max(by_measure.keys())
    default = float(getattr(events[0], "tempo", 120.0) or 120.0)
    out: list[float] = []
    last = default
    for measure in range(1, max_measure + 1):
        if measure in by_measure:
            last = by_measure[measure]
        out.append(last)
    return out


def _track_kind(adapter: Any, filepath: Path, track_id: int | None) -> str:
    """Return the instrument kind of a track ("guitar"/"bass"/"drums"/…).

    Only adapters that expose ``list_all_tracks`` (GP 7/8) carry true
    multi-instrument information; for everything else (MusicXML/MIDI single
    track, the guitar-only GP fallback) the track is implicitly a guitar — so
    the fingering optimizer runs exactly as it did before this feature.

    Resolution order:

    1. ``adapter.list_all_tracks(filepath)`` matched by ``track_id`` — the
       authoritative per-track kind. When ``track_id`` is ``None`` the adapter
       picked its own default track (always a guitar), so use guitar.
    2. ``classify_kind_for_program`` from the adapter's captured
       ``midi_program`` + ``track_name`` — a fallback used only if the listing
       could not be re-read (e.g. a transient parse error).
    3. :data:`KIND_GUITAR` — preserves the legacy guitar-only behaviour.

    Args:
        adapter: The format adapter returned by :func:`get_adapter`.
        filepath: Source score path.
        track_id: Requested track id, or ``None`` for the adapter's default.

    Returns:
        The track-kind string (never empty).
    """
    if not hasattr(adapter, "list_all_tracks"):
        return KIND_GUITAR  # non-GP / guitar-only adapters → always fingered
    if track_id is None:
        return KIND_GUITAR  # adapter's default selection is always a guitar
    try:
        for tid, _name, _tuning, kind in adapter.list_all_tracks(filepath):
            if tid == track_id:
                return str(kind)
    except (ParseError, UnsupportedFormatError):
        # Could not re-read the listing — fall back to program/name heuristics.
        midi_program = int(getattr(adapter, "midi_program", -1) or -1)
        track_name = getattr(adapter, "track_name", "") or ""
        return classify_kind_for_program(midi_program, track_name)
    return KIND_GUITAR  # unknown track id → safest default (fingered)


def _parse_representation_mode(value: str | None) -> RepresentationMode:
    """Parse a notation view mode from user input."""
    normalized = re.sub(r"[^a-z0-9]+", "_", (value or "").strip().lower()).strip("_")
    alias_map = {
        "": RepresentationMode.STANDARD_TAB,
        "tab": RepresentationMode.TAB,
        "tablature": RepresentationMode.TAB,
        "staff": RepresentationMode.STANDARD,
        "standard": RepresentationMode.STANDARD,
        "notation": RepresentationMode.STANDARD,
        "standard_tab": RepresentationMode.STANDARD_TAB,
        "standard_tablature": RepresentationMode.STANDARD_TAB,
        "hybrid": RepresentationMode.STANDARD_TAB,
        "mixed": RepresentationMode.STANDARD_TAB,
        "tab_rhythm": RepresentationMode.TAB_RHYTHM,
        "tablature_rhythm": RepresentationMode.TAB_RHYTHM,
        "tab_and_rhythm": RepresentationMode.TAB_RHYTHM,
        "tablature_and_rhythm": RepresentationMode.TAB_RHYTHM,
    }
    if normalized in alias_map:
        return alias_map[normalized]
    if _is_valid_notation_mode(normalized):
        return RepresentationMode(normalized)
    raise HTTPException(400, f"Unknown representation_mode: {value!r}")


_CHORD_FINGER_CLASSIFIER: object | None = None
_CHORD_FINGER_CLASSIFIER_LOADED: bool = False
_PLAYER_COST_MODEL: object | None = None
_PLAYER_COST_MODEL_LOADED: bool = False
_PHRASE_WINDOW_FINGERER: object | None = None
_PHRASE_WINDOW_FINGERER_LOADED: bool = False

# Current fingering algorithm version — bump this when the pipeline changes
# significantly enough that existing saved fingerings should be recalculated.
# "2.1" = preserve source-tab notes with no valid generated state as red review items.
FINGERING_ALGO_VERSION = "2.1"

# In-memory LRU cache for /api/solve responses. Keyed by (file, mtime, params)
# so it auto-invalidates when the source file is edited. Bounded entry count
# keeps total memory predictable (each response ~ 200-500 KB SVG + results).
from collections import OrderedDict as _OrderedDict  # noqa: E402

# Guards both LRU caches. /api/solve is a sync def, so concurrent requests (the
# frontend prefetch fans out many at once) run on different thread-pool threads
# and mutate these OrderedDicts in parallel — without a lock, a move_to_end /
# popitem race raises "OrderedDict mutated during iteration" or KeyError.
_CACHE_LOCK = threading.Lock()

_SOLVE_CACHE: _OrderedDict[tuple, dict[str, Any]] = _OrderedDict()
# 128 entries ≈ 64–128 MB max (4 modes × ~32 tracks). Bumped from 32 so that
# the background prefetch (frontend fires N × M solves on file open) doesn't
# evict its own freshly-stored entries.
_SOLVE_CACHE_MAX = int(_fw_config().web.solve_cache_max_entries)

# Legacy-results cache, layer below _SOLVE_CACHE. Keyed by (file, mtime,
# track, prefs) — crucially NOT by representation_mode, since the Viterbi
# pipeline output is mode-independent. Profiled cold solve = 2.0s in
# the legacy pipeline + 0.09s in the core/SVG render, so changing the
# view (= same legacy results, different SVG) becomes a 100ms operation
# instead of a 2s one. The per-mode _SOLVE_CACHE stays on top to keep
# repeat-click hits at ~50ms (no SVG re-build, no JSON re-serialise).
_LEGACY_CACHE: _OrderedDict[tuple, dict[str, Any]] = _OrderedDict()
_LEGACY_CACHE_MAX = int(_fw_config().web.legacy_cache_max_entries)


def _solve_cache_key(
    filepath: Path,
    track_id: int | None,
    representation_mode: str,
    same_finger_motion_penalty: bool,
    infer_implicit_legato: bool,
    svg_width: int | None = None,
) -> tuple:
    try:
        mtime = filepath.stat().st_mtime_ns
    except OSError:
        mtime = 0
    # Include the metadata sidecar mtime so the cache auto-invalidates when
    # the user inserts fingerings (writes a new _fingering.json next to the source).
    try:
        sidecar_mtime = _fingering_meta_path(filepath).stat().st_mtime_ns
    except OSError:
        sidecar_mtime = 0
    return (
        str(filepath),
        mtime,
        sidecar_mtime,
        track_id,
        representation_mode,
        bool(same_finger_motion_penalty),
        bool(infer_implicit_legato),
        svg_width,  # None = use default page_width from config
    )


def _solve_cache_get(key: tuple) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        payload = _SOLVE_CACHE.get(key)
        if payload is None:
            return None
        _SOLVE_CACHE.move_to_end(key)  # LRU touch
        return payload


def _solve_cache_put(key: tuple, payload: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _SOLVE_CACHE[key] = payload
        _SOLVE_CACHE.move_to_end(key)
        while len(_SOLVE_CACHE) > _SOLVE_CACHE_MAX:
            _SOLVE_CACHE.popitem(last=False)


def _solve_cache_clear() -> None:
    """Public-by-convention helper used by tests."""
    with _CACHE_LOCK:
        _SOLVE_CACHE.clear()
        _LEGACY_CACHE.clear()


def _legacy_cache_key(
    filepath: Path,
    track_id: int | None,
) -> tuple:
    """Cache key for the parse-only (adapter + events + metadata) layer.

    Prefs (same_finger_motion_penalty, infer_implicit_legato) are omitted here
    because /api/solve no longer runs Viterbi — fingerings come from the sidecar.
    Prefs still affect export endpoints that call _run_legacy_pipeline directly.
    """
    try:
        mtime = filepath.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (str(filepath), mtime, track_id)


def _legacy_cache_get(key: tuple) -> dict[str, Any] | None:
    with _CACHE_LOCK:
        entry = _LEGACY_CACHE.get(key)
        if entry is None:
            return None
        _LEGACY_CACHE.move_to_end(key)
        return entry


def _legacy_cache_put(key: tuple, entry: dict[str, Any]) -> None:
    with _CACHE_LOCK:
        _LEGACY_CACHE[key] = entry
        _LEGACY_CACHE.move_to_end(key)
        while len(_LEGACY_CACHE) > _LEGACY_CACHE_MAX:
            _LEGACY_CACHE.popitem(last=False)


def _get_chord_finger_classifier() -> object | None:
    """Lazy-load the optional ChordFingerClassifier (Phase 2 ONNX model).

    Loaded once per process; returns None when the model file or
    ``onnxruntime`` are not available so the web app keeps serving with the
    rule-based pipeline.
    """
    global _CHORD_FINGER_CLASSIFIER, _CHORD_FINGER_CLASSIFIER_LOADED
    if _CHORD_FINGER_CLASSIFIER_LOADED:
        return _CHORD_FINGER_CLASSIFIER
    _CHORD_FINGER_CLASSIFIER_LOADED = True
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[3] / "data" / "models"
    model_path = model_dir / "finger_classifier.onnx"
    spec_path = model_dir / "finger_classifier_spec.json"
    if not model_path.exists():
        return None
    try:
        from fretwise.ml import LearnedChordFingerClassifier
        _CHORD_FINGER_CLASSIFIER = LearnedChordFingerClassifier(
            str(model_path),
            str(spec_path) if spec_path.exists() else None,
        )
    except (ImportError, FileNotFoundError, AssertionError):
        _CHORD_FINGER_CLASSIFIER = None
    return _CHORD_FINGER_CLASSIFIER


def _get_player_cost_model() -> object | None:
    """Lazy-load the optional PlayerCostModel (Phase 3 ONNX transition cost).

    Same defensive pattern as ``_get_chord_finger_classifier``. Only takes
    effect when CostWeights has ``gamma > 0`` (the web app uses
    ``performance`` mode by default → γ=2.0 → model active).
    """
    global _PLAYER_COST_MODEL, _PLAYER_COST_MODEL_LOADED
    if _PLAYER_COST_MODEL_LOADED:
        return _PLAYER_COST_MODEL
    _PLAYER_COST_MODEL_LOADED = True
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[3] / "data" / "models"
    model_path = model_dir / "transition_cost_v3.onnx"
    spec_path = model_dir / "transition_cost_v3_spec.json"
    if not model_path.exists():
        return None
    try:
        from fretwise.ml import LearnedPlayerCost
        _PLAYER_COST_MODEL = LearnedPlayerCost(
            str(model_path),
            str(spec_path) if spec_path.exists() else None,
        )
    except (ImportError, FileNotFoundError, AssertionError):
        _PLAYER_COST_MODEL = None
    return _PLAYER_COST_MODEL


def _get_phrase_window_fingerer() -> object | None:
    """Lazy-load the production phrase_window_v2 melodic fingerer (GDS-026 #63).

    Same defensive pattern as ``_get_chord_finger_classifier``: loaded once
    per process, returns None when the bundle or ``onnxruntime`` are
    unavailable so the web app keeps serving rule-only fingerings.
    """
    global _PHRASE_WINDOW_FINGERER, _PHRASE_WINDOW_FINGERER_LOADED
    if _PHRASE_WINDOW_FINGERER_LOADED:
        return _PHRASE_WINDOW_FINGERER
    _PHRASE_WINDOW_FINGERER_LOADED = True
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[3] / "data" / "models"
    manifest_path = model_dir / "phrase_window_fingering_v2_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        from fretwise.ml import LearnedPhraseWindowFingerer
        _PHRASE_WINDOW_FINGERER = LearnedPhraseWindowFingerer.from_model_dir(
            model_dir, version="v2",
        )
    except (ImportError, FileNotFoundError, AssertionError, KeyError):
        _PHRASE_WINDOW_FINGERER = None
    return _PHRASE_WINDOW_FINGERER


def _biased_generator_and_cost(
    rule_preferences: RulePreferences | None,
    feedback: object | None,
) -> tuple[StateGenerator, CostFunction]:
    """Build the generator + cost function, applying feedback re-bias if any.

    With feedback present: corrected notes are hard-locked to the chosen
    fingering (exact), and a :class:`FeedbackBiasedPlayerCost` softly biases
    similar passages (when γ > 0). Without feedback this is identical to the
    default performance-mode setup.
    """
    weights = CostWeights.performance()
    base_pcm = _get_player_cost_model() if weights.gamma > 0 else None
    generator: StateGenerator = StateGenerator()
    player_cost_model: object | None = base_pcm
    if feedback:
        from fretwise.ml import FixedPlayerCost
        from fretwise.review import ConstrainedStateGenerator, FeedbackBiasedPlayerCost
        generator = ConstrainedStateGenerator(StateGenerator(), feedback.locks())  # type: ignore[attr-defined]
        if weights.gamma > 0:
            player_cost_model = FeedbackBiasedPlayerCost(base_pcm or FixedPlayerCost(), feedback)  # type: ignore[arg-type]
    cost_fn = CostFunction(
        weights=weights,
        rule_preferences=rule_preferences,
        player_cost_model=player_cost_model,
    )
    return generator, cost_fn


def _run_legacy_pipeline(
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None,
    feedback: object | None = None,
) -> tuple[list[FingeringResult], dict[str, int]]:
    generator, cost_fn = _biased_generator_and_cost(rule_preferences, feedback)
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline(
        events, generator, optimizer, pattern_matcher=matcher,
        chord_finger_classifier=_get_chord_finger_classifier(),
        phrase_window_fingerer=_get_phrase_window_fingerer(),
    )


def _run_legacy_pipeline_with_guard(
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None,
    feedback: object | None = None,
) -> PipelineResult:
    generator, cost_fn = _biased_generator_and_cost(rule_preferences, feedback)
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline_with_guard_report(
        events, generator, optimizer, pattern_matcher=matcher,
        chord_finger_classifier=_get_chord_finger_classifier(),
        phrase_window_fingerer=_get_phrase_window_fingerer(),
    )


def _guard_summary(payload: PipelineResult) -> dict[str, Any]:
    from fretwise.biomechanics import BiomechanicalSeverity

    report = payload.biomechanical_report
    measures = sorted(report.by_measure().keys())
    fatal_measures = sorted(
        {
            v.measure_index
            for v in report.violations
            if v.severity == BiomechanicalSeverity.FATAL and v.measure_index is not None
        }
    )
    return {
        "fatal": report.fatal_count,
        "high": report.high_count,
        "measures": measures[:20],
        "measure_count": len(measures),
        # Measures that specifically carry a FATAL violation — what blocks GP
        # export. Distinct from ``measures`` (every severity).
        "fatal_measures": fatal_measures[:20],
        "fatal_measure_count": len(fatal_measures),
    }


def _safe_audit(
    events: list[NoteEvent],
    results: list[FingeringResult],
    section_markers: dict[int, str] | None,
) -> dict[str, Any]:
    """Compute the audit and serialize it. Never raises.

    Falls back to ``{"available": False, "error": "..."}`` if anything goes
    wrong (broken model, edge case events, etc.) so the solve endpoint stays
    responsive even when the audit logic has a bug.
    """
    import dataclasses

    try:
        report = audit_score(
            events,
            results,
            section_markers=section_markers or None,
            ml_cost_model=_get_player_cost_model(),
        )
        payload = dataclasses.asdict(report)
        payload["available"] = True
        return payload
    except Exception as exc:  # pragma: no cover — defensive
        return {"available": False, "error": str(exc)}


def _annotate_serialized_review_status(
    rows: list[dict[str, Any]],
    audit: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    """Attach note-level review severity from the serialized audit payload.

    Applies the same ``NON_ACTIONABLE_CODES`` filter as the review panel
    (:func:`fretwise.review.flag_fingerings`) and the audit verdict cascade
    (:func:`fretwise.audit.audit_score`) so the per-note highlight never
    disagrees with them about what counts as an actionable violation.
    """
    if not rows:
        return rows

    severity_by_note: dict[int, str] = {}
    report = audit.get("biomechanical_report") if isinstance(audit, dict) else None
    violations = report.get("violations") if isinstance(report, dict) else None
    if isinstance(violations, list):
        for violation in violations:
            if not isinstance(violation, dict):
                continue
            if violation.get("code") in NON_ACTIONABLE_CODES:
                continue
            severity = str(violation.get("severity") or "").lower()
            if severity == "fatal":
                review = "impossible"
            elif severity == "high":
                review = "suspect"
            else:
                continue
            rank = 2 if review == "impossible" else 1
            for note_id in violation.get("note_ids") or ():
                try:
                    key = int(note_id)
                except (TypeError, ValueError):
                    continue
                previous = severity_by_note.get(key)
                if previous != "impossible" or rank > 1:
                    severity_by_note[key] = review

    annotated: list[dict[str, Any]] = []
    for row in rows:
        try:
            note_id = int(row.get("note_id"))  # type: ignore[union-attr]
        except (AttributeError, TypeError, ValueError):
            annotated.append(row)
            continue
        item = dict(row)
        item["review_severity"] = severity_by_note.get(
            note_id, item.get("review_severity", "ok"),
        )
        annotated.append(item)
    return annotated


def _infer_title_artist(filepath: Path) -> tuple[str, str]:
    """Parse ``(title, artist)`` from a filename like ``Artist - Title - MM-DD-YYYY``.

    Delegates to the shared filename parser so the displayed title is stripped of
    the trailing date and the artist/title split is consistent with the library.
    """
    meta = parse_filename_metadata(filepath.name)
    return meta.get("title", filepath.stem), meta.get("artist", "")


def _infer_source_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"xml", "mxl"}:
        return "musicxml"
    if suffix == "gp":
        return "gpif"
    return suffix


def _process_single_gp(path_str: str) -> dict[str, Any]:
    """Worker — full fingering pipeline for one GP file (ThreadPoolExecutor target).

    Runs in a worker THREAD inside the server process, so it shares the
    already-loaded ONNX singletons (no per-worker warm-up) and is immune to the
    Windows process-spawn hang the old ProcessPoolExecutor hit. It builds its own
    fresh StateGenerator/ViterbiOptimizer per call (no shared mutable state) and
    only *reads* the model singletons (onnxruntime inference is thread-safe), so
    concurrent calls are safe.

    Computes ALL guitar tracks in the file and saves per-track sidecars so that
    the viewer shows the correct fingering for every guitar track (not just the
    first one). The GP embed merges all tracks' mappings in a single write.

    Bug #6/#7: a file with biomechanically impossible positions is NOT rejected.
    The sidecar (plus an audit that flags the bad passage) is still written, so
    the file renders with fingering in the viewer and the issue surfaces in the
    audit / "Doigtés à revoir" instead of the file silently failing to compute.
    """
    from pathlib import Path as _P

    p = _P(path_str)
    try:
        import time as _time

        from fretwise.generator import StateGenerator
        from fretwise.optimizer import ViterbiOptimizer
        from fretwise.parser import get_adapter
        from fretwise.patterns import PatternMatcher
        from fretwise.pipeline import run_pipeline_with_guard_report
        from fretwise.scoring import CostFunction, CostWeights

        adapter = get_adapter(p)

        # Discover guitar tracks. GP files expose list_all_tracks (all
        # instruments) or list_guitar_tracks; fall back to default single parse.
        guitar_tracks: list[tuple[int | None, str]] = []
        if hasattr(adapter, "list_all_tracks"):
            for tid, name, _tuning, kind in adapter.list_all_tracks(p):
                if kind == KIND_GUITAR:
                    guitar_tracks.append((tid, name))
        elif hasattr(adapter, "list_guitar_tracks"):
            for tid, name, _tuning in adapter.list_guitar_tracks(p):
                guitar_tracks.append((tid, name))
        if not guitar_tracks:
            # Single-track or no kind info — treat the default parse as guitar.
            guitar_tracks = [(None, "Guitar")]

        weights = CostWeights.performance()
        player_cost_model = _get_player_cost_model() if weights.gamma > 0 else None

        t0 = _time.monotonic()
        total_annotated = 0
        total_fatal = 0
        merged_mapping: dict = {}
        sidecar_ok = True

        for track_id, _track_name in guitar_tracks:
            try:
                if track_id is not None and hasattr(adapter, "parse_track"):
                    events = adapter.parse_track(p, track_id)
                else:
                    events = adapter.parse(p)
            except Exception:
                continue
            if not events:
                continue

            cost_fn = CostFunction(weights=weights, player_cost_model=player_cost_model)
            payload = run_pipeline_with_guard_report(
                events, StateGenerator(), ViterbiOptimizer(cost_fn),
                pattern_matcher=PatternMatcher(),
                chord_finger_classifier=_get_chord_finger_classifier(),
                phrase_window_fingerer=_get_phrase_window_fingerer(),
            )
            results = payload.results
            if not results:
                continue

            total_fatal += payload.biomechanical_report.fatal_count
            mapping = fingerings_by_source_id(results)
            merged_mapping.update(mapping)
            total_annotated += len(mapping)

            section_markers = dict(getattr(adapter, "section_markers", {}) or {})
            audit = _safe_audit(events, results, section_markers)
            if not _write_fingering_sidecar(p, results, audit=audit, track_id=track_id):
                sidecar_ok = False

        if not total_annotated:
            return {"file": p.name, "status": "error", "error": "no fingering results"}

        elapsed_s = round(_time.monotonic() - t0, 2)

        # Embed all tracks' fingerings into the .gp in one pass (each
        # write_gp_with_fingerings call strips then re-injects, so we merge
        # all mappings first to avoid overwriting earlier tracks' annotations).
        try:
            gp_bytes = write_gp_with_fingerings(p, merged_mapping)
            p.write_bytes(gp_bytes)
            _refresh_fingering_meta_source_mtime(p)
        except ValueError:
            pass

        _solve_cache_clear()
        return {
            "file": p.name, "status": "ok",
            "annotated": total_annotated, "out": p.name,
            "elapsed_s": elapsed_s,
            "fatal": total_fatal,
            "sidecar_saved": sidecar_ok,
        }
    except Exception as exc:  # noqa: BLE001 — never break the pool
        return {"file": p.name, "status": "error", "error": str(exc)}


def _render_legacy_pdf_payload(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
) -> bytes:
    """Render the PDF via the legacy renderer (export/pdf_tab.py).

    The new core/backends/pdf.py renderer lost LH finger annotations
    during the Phase 4 refactor. Until those are ported, the web export
    routes through the legacy renderer (same as the CLI ``-f pdf`` path)
    so the user sees the fingerings they see on screen.
    """
    import tempfile

    results, _stats = _run_legacy_pipeline(events)
    if not results:
        raise HTTPException(500, "Pipeline returned no fingering results")

    auto_title, auto_artist = _infer_title_artist(filepath)
    track_name = getattr(adapter, "track_name", "") or ""
    beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0) or 4.0)
    section_markers = dict(getattr(adapter, "section_markers", {}) or {})
    chord_diagrams = list(getattr(adapter, "chord_diagrams", []) or [])

    with tempfile.NamedTemporaryFile(
        suffix=".pdf", delete=False,
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        render_pdf_tab(
            results,
            tmp_path,
            title=auto_title,
            artist=auto_artist,
            beats_per_measure=beats_per_measure,
            instrument=track_name,
            mode_label="performance mode",
            section_markers=section_markers or None,
            chord_diagrams=chord_diagrams or None,
        )
        return tmp_path.read_bytes()
    finally:
        try:
            tmp_path.unlink()
        except OSError:
            pass


def _shadow_core_conformance_outcome(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
    *,
    representation_mode: RepresentationMode,
) -> tuple[int, bool]:
    """Run the core pipeline in shadow mode to report conformance issues.

    Mirrors ``fretwise.cli._shadow_core_conformance_outcome``; the legacy
    PDF route uses this to surface architectural drift via response
    headers without blocking the export.
    """
    try:
        core_result = _run_core_pipeline_for_events(
            filepath, adapter, events,
            representation_mode=representation_mode,
        )
    except Exception:
        return 0, True
    return len(core_result.conformance_issues), False


def _render_core_pdf_payload(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
    *,
    representation_mode: RepresentationMode,
    track_kind: str = "guitar",
) -> tuple[bytes, int]:
    core_result = _run_core_pipeline_for_events(
        filepath,
        adapter,
        events,
        representation_mode=representation_mode,
        track_kind=track_kind,
    )
    return render_scene_to_pdf_bytes(core_result.render_scene), len(core_result.conformance_issues)


def _safe_pdf_filename(label: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._ -]+", "_", label).strip()
    if not safe:
        safe = "fretwise-export"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    return safe


def _run_core_pipeline_for_events(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
    *,
    representation_mode: RepresentationMode,
    track_kind: str = "guitar",
    page_width: float | None = None,
) -> Any:
    track_name: str = getattr(adapter, "track_name", "") or ""
    source_beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0) or 4.0)
    section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})
    chord_markers: dict[str, str] = dict(getattr(adapter, "chord_markers", {}) or {})
    chord_diagrams: list[ChordDiagram] = list(getattr(adapter, "chord_diagrams", []) or [])
    raw_score = legacy_parse_to_raw_score(
        filepath,
        source_format=_infer_source_format(filepath),
        events=events,
        track_name=track_name,
        beats_per_measure=source_beats_per_measure,
        time_denominator=int(getattr(adapter, "time_denominator", 4) or 4),
        key_signature_fifths=int(getattr(adapter, "key_signature_fifths", 0) or 0),
        has_anacrusis=bool(getattr(adapter, "has_anacrusis", False)),
        section_markers=section_markers,
        chord_markers=chord_markers,
        chord_diagrams=chord_diagrams,
        measure_time_signatures=dict(getattr(adapter, "measure_time_signatures", {}) or {}),
    )
    return run_core_pipeline_from_raw(
        raw_score,
        representation_mode=representation_mode,
        track_kind=track_kind,
        page_width=page_width,
    )


def _extract_measure_regions(
    render_scene: Any,
    canonical_score: Any,
    mode: str = "standard_tablature",
    page_width: float | None = None,
) -> list[dict[str, Any]]:
    """Compute per-measure {measure_idx, x, y0, y1, width} regions for SVG cursor."""
    try:
        from fretwise.core.layout import canonical_to_page_layout  # lazy import

        page_layout = canonical_to_page_layout(canonical_score, mode=mode, page_width=page_width)

        # Collect y-bounds per system from barline recipes in the render scene
        pages = render_scene.document_scene.pages if render_scene else []
        sys_y_bounds: list[tuple[float, float]] = []
        for sys_scene in (pages[0].systems if pages else []):
            y0: float | None = None
            y1: float | None = None
            for staff in sys_scene.staves[:1]:
                for layer in staff.layer_groups:
                    for recipe in layer.recipe_instances:
                        if recipe.recipe_id == "barline":
                            by0 = float(recipe.params.get("y0", 0.0))
                            by1 = float(recipe.params.get("y1", 0.0))
                            if y0 is None or by0 < y0:
                                y0 = by0
                            if y1 is None or by1 > y1:
                                y1 = by1
            sys_y_bounds.append((y0 or 0.0, y1 or 100.0))

        regions: list[dict[str, Any]] = []
        measure_idx = 0
        for si, sys_layout in enumerate(page_layout.systems):
            y0_sys, y1_sys = sys_y_bounds[si] if si < len(sys_y_bounds) else (0.0, 100.0)
            for stf_layout in sys_layout.staves[:1]:
                for ml in stf_layout.measure_layouts:
                    regions.append({
                        "measure_idx": measure_idx,
                        "x": ml.x,
                        "y0": y0_sys,
                        "y1": y1_sys,
                        "width": ml.width,
                    })
                    measure_idx += 1
        return regions
    except Exception:
        return []


def _serialize_result(r: FingeringResult) -> dict[str, Any]:
    """Serialize a FingeringResult to a JSON-friendly dict."""
    ne = r.note_event
    st = r.state
    return {
        "note_id": r.note_id,
        "source_note_id": ne.source_note_id,
        "pitch": ne.pitch,
        "onset": ne.onset,
        "duration": ne.duration,
        "tempo": ne.tempo,
        "articulation": str(ne.articulation),
        "dynamic": str(ne.dynamic),
        "voice_hint": ne.voice_hint,
        "string": st.string_num,
        "fret": st.fret,
        "finger": str(st.finger),
        "hand_position": st.hand_position,
        "cost": r.cost,
        "measure_index": ne.measure_index,
        "review_severity": "ok",
        "gp_fingering_export_status": _gp_fingering_export_status(r),
        # Sedentary fingers annotation (see docs/finger_placement_strategy.md).
        # getattr for backward compat with legacy mocks that predate the field.
        "planted_fingers": {
            k: list(v) for k, v in getattr(r, "planted_fingers", {}).items()
        },
        # Notation fields
        "let_ring": ne.let_ring,
        "bend_value": ne.bend_value,
        "bend_type": ne.bend_type,
        "slide_type": ne.slide_type,
        "vibrato_wide": ne.vibrato_wide,
        "harmonic_type": ne.harmonic_type,
        "harmonic_fret": ne.harmonic_fret,
        "harmonic_resultant_pitch": ne.harmonic_resultant_pitch,
        "muted": ne.muted,
        "palm_muted": ne.palm_muted,
        "tapping": ne.tapping,
        "accent": ne.accent,
        "accent_strong": ne.accent_strong,
        "tremolo_picking": ne.tremolo_picking,
        "ghost": ne.ghost,
        "staccato": ne.staccato,
        "strum_direction": ne.strum_direction,
        "slap": ne.slap,
        "pop": ne.pop,
        "rasgueado": ne.rasgueado,
        "golpe": ne.golpe,
        "tuplet_actual": ne.tuplet_actual,
        "tuplet_normal": ne.tuplet_normal,
    }


# ── Embedded GP fingering reader ──────────────────────────────────────────────
# GP 7/8 files store the left-hand finger directly on each note as
# <LeftFingering>X</LeftFingering> (Spanish convention P/I/M/A/C). When a file
# already carries these (imported, hand-annotated, or saved by FretWise) we can
# display them on open without re-running Viterbi — even if no sidecar exists.

_GPIF_LETTER_TO_FINGER: dict[str, Finger] = {
    "P": Finger.OPEN,
    "I": Finger.INDEX,
    "M": Finger.MIDDLE,
    "A": Finger.RING,
    "C": Finger.PINKY,
}
_FINGER_VALUE_TO_GPIF_LETTER: dict[str, str] = {
    str(finger): letter for letter, finger in _GPIF_LETTER_TO_FINGER.items()
}
_EMBEDDED_NOTE_RE = re.compile(r'<Note id="(\d+)">(.*?)</Note>', re.DOTALL)
_EMBEDDED_LF_RE = re.compile(r"<LeftFingering>([^<]*)</LeftFingering>")


def _gp_has_embedded_fingering(filepath: Path) -> bool:
    """Fast presence check: does the GP file carry any LeftFingering element?

    Cheaper than :func:`_read_embedded_gp_fingerings` (substring scan, no
    regex/parse) so :func:`list_files` can flag pre-fingered files across a
    large library without a measurable hit. Never raises.
    """
    import zipfile

    if filepath.suffix.lower() != ".gp":
        return False
    try:
        if not zipfile.is_zipfile(filepath):
            return False
        with zipfile.ZipFile(filepath, "r") as z:
            if GPIF_CONTENT_NAME not in z.namelist():
                return False
            return b"<LeftFingering>" in z.read(GPIF_CONTENT_NAME)
    except Exception:  # noqa: BLE001
        return False


def _read_embedded_gp_fingerings(filepath: Path) -> dict[str, str]:
    """Return ``{source_note_id → gpif_letter}`` for embedded LeftFingering.

    Empty dict when the file is not a GP archive, has no GPIF content, or
    carries no LeftFingering elements. Never raises.
    """
    import zipfile

    if filepath.suffix.lower() != ".gp":
        return {}
    try:
        if not zipfile.is_zipfile(filepath):
            return {}
        with zipfile.ZipFile(filepath, "r") as z:
            if GPIF_CONTENT_NAME not in z.namelist():
                return {}
            xml = z.read(GPIF_CONTENT_NAME).decode("utf-8")
    except Exception:  # noqa: BLE001
        return {}
    out: dict[str, str] = {}
    for m in _EMBEDDED_NOTE_RE.finditer(xml):
        lf = _EMBEDDED_LF_RE.search(m.group(2))
        if lf and lf.group(1).strip():
            out[m.group(1)] = lf.group(1).strip()
    return out


def _embedded_results_from_events(
    events: list[NoteEvent],
    embedded: dict[str, str],
) -> list[FingeringResult]:
    """Build FingeringResults from parsed events + embedded finger letters.

    Uses each event's ``string_hint``/``fret_hint`` (the corde/fret from the
    source tab) and the embedded ``LeftFingering`` keyed by ``source_note_id``.
    Open strings (fret 0) and notes without an embedded letter get ``OPEN``.
    """
    results: list[FingeringResult] = []
    for i, ev in enumerate(events):
        fret = ev.fret_hint if ev.fret_hint is not None else 0
        string_num = ev.string_hint if ev.string_hint is not None else 0
        letter = embedded.get(ev.source_note_id) if ev.source_note_id else None
        if fret == 0 or letter is None:
            finger = Finger.OPEN
        else:
            finger = _GPIF_LETTER_TO_FINGER.get(letter, Finger.INDEX)
        state = FingeringState(
            string_num=string_num,
            fret=fret,
            finger=finger,
            hand_position=max(1, fret),
        )
        results.append(
            FingeringResult(note_id=i + 1, note_event=ev, state=state, cost=0.0)
        )
    return results


def _gp_fingering_export_status(result: FingeringResult) -> str:
    """Classify whether a computed fingering can be written back to GPIF."""
    if result.state.fret == 0 or str(result.state.finger) == str(Finger.OPEN):
        return "not_needed"
    if result.note_event.source_note_id:
        return "exportable"
    return "missing_source_note_id"


def _count_unexportable_gp_fingerings(results: list[FingeringResult]) -> int:
    """Count fretted computed fingerings that cannot be mapped to a GPIF note id."""
    return sum(
        1 for result in results
        if _gp_fingering_export_status(result) == "missing_source_note_id"
    )


def _serialized_fingerings_by_source_id(results: object) -> dict[str, str]:
    """Return GPIF fingering letters from serialized sidecar result rows."""
    if not isinstance(results, list):
        return {}
    out: dict[str, str] = {}
    for row in results:
        if not isinstance(row, dict):
            continue
        source_note_id = row.get("source_note_id")
        if not source_note_id:
            continue
        try:
            fret = int(row.get("fret") or 0)
        except (TypeError, ValueError):
            fret = 0
        if fret == 0:
            continue
        letter = _FINGER_VALUE_TO_GPIF_LETTER.get(str(row.get("finger") or ""))
        if letter is not None:
            out[str(source_note_id)] = letter
    return out


def _current_sidecar_fingering_mapping(filepath: Path) -> dict[str, str]:
    """Read current sidecar fingerings as ``{source_note_id: gpif_letter}``."""
    import json as _json

    meta = _read_fingering_meta(filepath)
    if meta is None or not _fingering_meta_is_current(meta, filepath):
        return {}
    try:
        data = _json.loads(_fingering_data_path(filepath).read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}
    out = _serialized_fingerings_by_source_id(data.get("results"))
    tracks = data.get("tracks") if isinstance(data.get("tracks"), dict) else {}
    for entry in tracks.values():
        if isinstance(entry, dict):
            out.update(_serialized_fingerings_by_source_id(entry.get("results")))
    return out


def _merged_gp_fingering_mapping(
    filepath: Path,
    current_mapping: Mapping[str, str],
) -> dict[str, str]:
    """Merge existing GP/sidecar annotations with the newly computed track.

    ``write_gp_with_fingerings`` strips all ``LeftFingering`` elements before
    injecting the supplied map. Saving one track therefore has to carry forward
    the other tracks' existing annotations, otherwise a later save erases an
    earlier one.
    """
    merged: dict[str, str] = {}
    merged.update(_read_embedded_gp_fingerings(filepath))
    merged.update(_current_sidecar_fingering_mapping(filepath))
    merged.update({str(k): str(v) for k, v in current_mapping.items()})
    return merged


# ── Fingering sidecar helpers ─────────────────────────────────────────────────
# Two files live next to the source score (local storage only):
#   <stem>_fingering.json      — tiny header: algo_version + source_mtime
#   <stem>_fingering_data.json — full serialised results array
# Written by /api/save/gp and the batch refresh worker. Read by /api/solve and
# /api/files. Keeping the header tiny lets /api/files scan large libraries
# without loading the full result arrays.

def _fingering_meta_path(filepath: Path) -> Path:
    return filepath.with_name(f"{filepath.stem}_fingering.json")


def _fingering_data_path(filepath: Path) -> Path:
    return filepath.with_name(f"{filepath.stem}_fingering_data.json")


def _read_fingering_meta(filepath: Path) -> dict[str, Any] | None:
    import json as _json
    p = _fingering_meta_path(filepath)
    if not p.exists():
        return None
    try:
        return _json.loads(p.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return None


def _fingering_meta_is_current(meta: dict[str, Any], filepath: Path) -> bool:
    """True when the sidecar version matches the current algo and the source file is unchanged."""
    if meta.get("algo_version") != FINGERING_ALGO_VERSION:
        return False
    try:
        stored = meta.get("source_mtime")
        if stored is not None and abs(float(stored) - filepath.stat().st_mtime) > 1.0:
            return False
    except OSError:
        return False
    return True


def _write_fingering_sidecar(
    filepath: Path,
    results: list[FingeringResult],
    audit: dict[str, Any] | None = None,
    track_id: int | None = None,
) -> bool:
    """Write both sidecar files next to *filepath* (best-effort, never raises).

    Returns ``True`` when both files were written successfully, ``False`` on any
    I/O error (disk full, read-only path, etc.).  Callers should surface this to
    the API response so the UI can warn the user when the cache is stale.

    The optional ``audit`` (a serialized AuditReport) is stored alongside the
    results so /api/solve can serve a real audit banner without re-running the
    pipeline — the Viterbi step that produced it already lives in save_gp.

    Per-track aware (bug #3): the data sidecar keeps one entry per guitar track
    under ``tracks[str(track_id)]`` so a multi-guitar song can cache *every*
    track's fingering at once. The top-level ``results``/``audit`` mirror the
    most recently saved track (the "primary"), and ``meta["track_id"]`` records
    which track that is — both for backward compatibility with old single-track
    sidecars and so /api/solve can serve the primary without a tracks lookup.
    Existing tracks are preserved on each save (read-merge-write).
    """
    import datetime
    import json as _json
    try:
        serialized = [_serialize_result(r) for r in results]
        source_mtime = filepath.stat().st_mtime
        meta = {
            "algo_version": FINGERING_ALGO_VERSION,
            "model": "phrase_window_v2",
            "created_at": datetime.datetime.now(datetime.UTC).isoformat(),
            "source_mtime": source_mtime,
            "track_id": track_id,
        }
        _fingering_meta_path(filepath).write_text(
            _json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
        # Merge into any existing data sidecar so OTHER tracks survive this save.
        existing: dict[str, Any] = {}
        try:
            existing = _json.loads(
                _fingering_data_path(filepath).read_text(encoding="utf-8")
            )
        except Exception:  # noqa: BLE001
            existing = {}
        tracks: dict[str, Any] = (
            existing.get("tracks") if isinstance(existing.get("tracks"), dict) else {}
        )
        entry: dict[str, Any] = {"results": serialized}
        if audit is not None:
            entry["audit"] = audit
        if track_id is not None:
            tracks[str(track_id)] = entry
        data: dict[str, Any] = {"results": serialized, "tracks": tracks}
        if audit is not None:
            data["audit"] = audit
        _fingering_data_path(filepath).write_text(
            _json.dumps(data, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        return False
    return True


def _refresh_fingering_meta_source_mtime(filepath: Path) -> bool:
    """Refresh sidecar ``source_mtime`` after an in-place GP rewrite."""
    import datetime
    import json as _json

    try:
        meta = _read_fingering_meta(filepath) or {}
        meta["algo_version"] = meta.get("algo_version") or FINGERING_ALGO_VERSION
        meta["model"] = meta.get("model") or "phrase_window_v2"
        meta["created_at"] = meta.get("created_at") or datetime.datetime.now(
            datetime.UTC
        ).isoformat()
        meta["source_mtime"] = filepath.stat().st_mtime
        _fingering_meta_path(filepath).write_text(
            _json.dumps(meta, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:  # noqa: BLE001
        return False
    return True


def _staff_only_results(events: list[NoteEvent]) -> list[FingeringResult]:
    """Wrap NoteEvents as un-fingered FingeringResults for staff-only export.

    Non-guitar tracks (vocals/bass/drums/other) do not run the Viterbi
    optimizer, but the MusicXML writer consumes ``FingeringResult`` objects. We
    pair each event with a placeholder :class:`FingeringState`; the multi-part
    renderer renders these kinds staff-only and never reads the placeholder
    string/fret/finger (no ``<technical>`` block is emitted).

    Args:
        events: Parsed note events for one track.

    Returns:
        A FingeringResult per event, in input order.
    """
    placeholder = FingeringState(
        string_num=0, fret=0, finger=Finger.OPEN, hand_position=1,
    )
    return [
        FingeringResult(note_id=i, note_event=ev, state=placeholder, cost=0.0)
        for i, ev in enumerate(events)
    ]


def _serialize_staff_note(ne: NoteEvent, note_id: int) -> dict[str, Any]:
    """Serialize a NoteEvent as a staff-only (un-fingered) note.

    Same JSON shape as :func:`_serialize_result` so the frontend can consume
    both interchangeably, but the fingering fields (``string``, ``fret``,
    ``finger``, ``hand_position``, ``cost``, ``planted_fingers``) are ``null``/
    empty because non-guitar tracks (vocals, bass, drums, …) do not run the
    Viterbi optimizer. Standard-notation fields (pitch, rhythm, dynamics,
    articulations) are preserved for staff rendering.

    Args:
        ne: The parsed note event.
        note_id: 1-based sequential id (matches the fingered-path numbering).

    Returns:
        A JSON-friendly dict with ``string``/``fret``/``finger`` set to ``None``.
    """
    return {
        "note_id": note_id,
        "source_note_id": ne.source_note_id,
        "pitch": ne.pitch,
        "onset": ne.onset,
        "duration": ne.duration,
        "tempo": ne.tempo,
        "articulation": str(ne.articulation),
        "dynamic": str(ne.dynamic),
        "voice_hint": ne.voice_hint,
        # Fingering fields are null: no optimizer ran for this (non-guitar) track.
        "string": None,
        "fret": None,
        "finger": None,
        "hand_position": None,
        "cost": None,
        "measure_index": ne.measure_index,
        "review_severity": "ok",
        "planted_fingers": {},
        "gp_fingering_export_status": "not_applicable",
        # Notation fields (kept for standard-notation rendering).
        "let_ring": ne.let_ring,
        "bend_value": ne.bend_value,
        "bend_type": ne.bend_type,
        "slide_type": ne.slide_type,
        "vibrato_wide": ne.vibrato_wide,
        "harmonic_type": ne.harmonic_type,
        "harmonic_fret": ne.harmonic_fret,
        "harmonic_resultant_pitch": ne.harmonic_resultant_pitch,
        "muted": ne.muted,
        "palm_muted": ne.palm_muted,
        "tapping": ne.tapping,
        "accent": ne.accent,
        "accent_strong": ne.accent_strong,
        "tremolo_picking": ne.tremolo_picking,
        "ghost": ne.ghost,
        "staccato": ne.staccato,
        "strum_direction": ne.strum_direction,
        "slap": ne.slap,
        "pop": ne.pop,
        "rasgueado": ne.rasgueado,
        "golpe": ne.golpe,
        "tuplet_actual": ne.tuplet_actual,
        "tuplet_normal": ne.tuplet_normal,
    }


def _serialize_chord_diagram(cd: ChordDiagram) -> dict[str, Any]:
    """Serialize a ChordDiagram to JSON."""
    return {
        "name": cd.name,
        "frets": cd.frets,
        "string_count": cd.string_count,
        "base_fret": cd.base_fret,
        "fingers": cd.fingers,
    }


# Module-level instance for uvicorn / ASGI servers.
app = create_app()
