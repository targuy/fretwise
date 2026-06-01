"""FastAPI application — serves the FretWise tab viewer."""

from __future__ import annotations

import os
import re
import threading
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from fretwise.audit import audit_score
from fretwise.auth.accounts import LocalAccountStore
from fretwise.auth.config import load_auth_config
from fretwise.auth.resolver import StorageNotConfigured, resolve_user_storage
from fretwise.auth.secrets import UserSecretsStore
from fretwise.auth.users import UserStore
from fretwise.auth.web import current_request_user, setup_auth
from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_bytes
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.notation_mode import is_valid_mode as _is_valid_notation_mode
from fretwise.export.gp_writer import (
    fingerings_by_source_id,
    write_gp_with_fingerings,
)
from fretwise.export.pdf_tab import render_pdf_tab
from fretwise.generator import StateGenerator
from fretwise.models import (
    ChordDiagram,
    FingeringResult,
    NoteEvent,
)
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.patterns import PatternMatcher
from fretwise.pdf_conformance import (
    legacy_shadow_pdf_conformance_report,
)
from fretwise.pipeline import PipelineResult, run_pipeline, run_pipeline_with_guard_report
from fretwise.scoring import CostFunction, CostWeights, RulePreferences
from fretwise.storage import (
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
from .songs_index import enrich_file_info, load_index

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
_MAX_SCORE_UPLOAD_BYTES = 50 * 1024 * 1024          # 50 MiB — score files are small
_MAX_SOUNDFONT_UPLOAD_BYTES = 512 * 1024 * 1024     # 512 MiB — SF2 banks can be large

# Hostnames accepted by the Host-header guard (DNS-rebinding protection).
# Loopback-only by default; override with FRETWISE_ALLOWED_HOSTS (comma list,
# ``*`` to disable) when intentionally exposing the server on a LAN.
_DEFAULT_ALLOWED_HOSTS: tuple[str, ...] = (
    "localhost", "127.0.0.1", "[::1]", "testserver",
)


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
        return response

    cfg = _settings.load()
    if fixtures_dir is None:
        fixtures_dir = Path(cfg.get("partitions_dir", str(Path(__file__).parents[3] / "partitions")))

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
    """Enable OIDC auth + per-user storage when configured.

    Fail-closed: if an OIDC provider is configured but initialisation fails
    (missing ``[auth]`` extra, no ``FRETWISE_SECRET_KEY``, …) we refuse to start
    rather than silently degrading to the single-user mode, which would serve
    the local partitions library with **no authentication at all**.
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
        cfg = _settings.load()
        storage: StorageBackend = _current_storage(app)
        songs = load_index(cfg.get("index_path", ""))

        try:
            objects = storage.list_scores()
        except StorageError as exc:
            raise HTTPException(502, f"Storage error: {exc}")

        files = []
        for obj in objects:
            info: dict[str, Any] = {
                "name": obj.name,
                "stem": obj.stem,
                "format": obj.format,
            }
            info = enrich_file_info(info, songs)
            files.append(info)
        return JSONResponse(files)

    @app.get("/api/tracks/{filename}")
    async def list_tracks(filename: str) -> list[dict[str, Any]]:
        """List guitar tracks in a file."""
        filepath = _resolve_file(app, filename)

        try:
            adapter = get_adapter(filepath)
        except UnsupportedFormatError as exc:
            raise HTTPException(400, str(exc))

        tracks = []
        if hasattr(adapter, "list_guitar_tracks"):
            raw_tracks = adapter.list_guitar_tracks(filepath)
            for track_id, name, tuning in raw_tracks:
                tracks.append({
                    "id": track_id,
                    "name": name,
                    "tuning": tuning,
                })
        else:
            # MusicXML/MIDI: single-track
            tracks.append({"id": 0, "name": "Guitar", "tuning": [40, 45, 50, 55, 59, 64]})

        return tracks

    @app.get("/api/notes/{filename}")
    async def get_notes(
        filename: str,
        track_id: int | None = Query(None),
        same_finger_motion_penalty: bool = Query(True),
        infer_implicit_legato: bool = Query(True),
    ) -> dict[str, Any]:
        """Return Viterbi-fingered notes for a track (audio-only, no rendering).

        Lighter than /api/solve: skips the core rendering pipeline entirely.
        Used by the multi-track audio mixer to load secondary track note data.
        """
        filepath = _resolve_file(app, filename)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        rule_preferences = RulePreferences(
            same_finger_motion_penalty=same_finger_motion_penalty,
            infer_implicit_legato=infer_implicit_legato,
        )
        results, _ = _run_legacy_pipeline(
            events,
            rule_preferences=rule_preferences,
        )
        track_name: str = getattr(adapter, "track_name", "") or ""
        midi_program: int = getattr(adapter, "midi_program", -1)
        tempo = events[0].tempo if events else 120.0
        beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0))

        return {
            "track_name": track_name,
            "midi_program": midi_program,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "results": [_serialize_result(r) for r in results],
        }

    @app.get("/api/solve/{filename}")
    def solve_file(
        filename: str,
        track_id: int | None = Query(None),
        representation_mode: str = Query("standard_tablature"),
        same_finger_motion_penalty: bool = Query(True),
        infer_implicit_legato: bool = Query(True),
    ) -> dict[str, Any]:
        """Run the full pipeline and return results as JSON.

        Sync def so FastAPI runs each request in its thread pool — concurrent
        solve requests (e.g. the frontend prefetch fanning out N tracks ×
        M modes) actually execute in parallel instead of serialising on the
        single asyncio event loop.
        """
        filepath = _resolve_file(app, filename)
        cache_key = _solve_cache_key(
            filepath, track_id, representation_mode,
            same_finger_motion_penalty, infer_implicit_legato,
        )
        cached = _solve_cache_get(cache_key)
        if cached is not None:
            return cached
        view_mode = _parse_representation_mode(representation_mode)

        # Step 1 — legacy pipeline + adapter metadata + audit. This is the
        # expensive piece (~2s on AC/DC) and it's *mode-independent*, so we
        # cache it by (file, track, prefs) only. Subsequent view changes on
        # the same file/track hit this cache and only re-run the core/SVG
        # render (~90ms).
        base_key = _legacy_cache_key(
            filepath, track_id,
            same_finger_motion_penalty, infer_implicit_legato,
        )
        base = _legacy_cache_get(base_key)
        if base is None:
            adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
            if not events:
                raise HTTPException(404, "No notes found in file")
            rule_preferences = RulePreferences(
                same_finger_motion_penalty=same_finger_motion_penalty,
                infer_implicit_legato=infer_implicit_legato,
            )
            results, stats = _run_legacy_pipeline(
                events, rule_preferences=rule_preferences,
            )
            section_markers: dict[int, str] = dict(
                getattr(adapter, "section_markers", {}) or {}
            )
            base = {
                "adapter": adapter,
                "events": events,
                "results": results,
                "stats": stats,
                "track_name": getattr(adapter, "track_name", "") or "",
                "midi_program": getattr(adapter, "midi_program", -1),
                "section_markers": section_markers,
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
                "serialized_results": [_serialize_result(r) for r in results],
                "audit": _safe_audit(events, results, section_markers),
            }
            _legacy_cache_put(base_key, base)

        # Step 2 — mode-dependent core/SVG render. Cheap (~90ms) so we run
        # it every time the per-mode response cache misses.
        core_result = _run_core_pipeline_for_events(
            filepath, base["adapter"], base["events"],
            representation_mode=view_mode,
        )

        # Parse artist/title from filename (cheap, redo each time).
        auto_title, auto_artist = _infer_title_artist(filepath)

        payload: dict[str, Any] = {
            "title": auto_title,
            "artist": auto_artist,
            "track_name": base["track_name"],
            "midi_program": base["midi_program"],
            "mode": "performance",
            "representation_mode": view_mode.value,
            "tempo": base["tempo"],
            "beats_per_measure": base["beats_per_measure"],
            "section_markers": base["section_markers"],
            "chord_diagrams": base["chord_diagrams"],
            "chord_markers": base["chord_markers"],
            "core_svg": core_result.svg,
            "core_conformance_issues": len(core_result.conformance_issues),
            "measure_regions": _extract_measure_regions(
                getattr(core_result, "render_scene", None),
                getattr(core_result, "canonical_score", None),
                mode=view_mode.value,
            ),
            "stats": base["stats"],
            "results": base["serialized_results"],
            "audit": base["audit"],
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
    ) -> Response:
        """Recompute fingerings for every GP 7/8 file in the fixtures dir.

        Multiprocessing pool — each worker carries its own parser + ONNX
        session, so on a multi-core machine the wall-clock is roughly
        ``serial_time / min(workers, cpu_count)`` minus a one-shot worker
        warm-up (~1 s per worker).

        Skip-on-resume — when ``force=false`` (the default), a source file
        whose ``<stem>_fingered.gp`` already exists *and* is newer than the
        source is skipped. Pass ``?force=true`` to re-process everything.

        Streams one JSON line per processed file via text/plain so the
        frontend can show live progress without a separate polling loop.
        """
        _require_admin(app)
        import json as _json
        import os as _os
        from concurrent.futures import ProcessPoolExecutor, as_completed

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
        all_files = sorted(fixtures_dir.glob("*.gp"))
        sources = [f for f in all_files if not f.stem.endswith("_fingered")]

        # Skip files already fingered (unless force=true).
        to_process: list[Path] = []
        pre_skipped: list[Path] = []
        for f in sources:
            out_path = f.with_name(f"{f.stem}_fingered{f.suffix}")
            if not force and out_path.exists():
                try:
                    if out_path.stat().st_mtime >= f.stat().st_mtime:
                        pre_skipped.append(f)
                        continue
                except OSError:
                    pass
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
                    with ProcessPoolExecutor(max_workers=n_workers) as pool:
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
            raise HTTPException(
                409,
                "Biomechanical guard failed before GP export: "
                f"{guard['fatal']} fatal violation(s), measures={guard['measures']}",
            )

        mapping = fingerings_by_source_id(payload.results)
        try:
            gp_bytes = write_gp_with_fingerings(filepath, mapping)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

        out_name = f"{filepath.stem}_fingered{filepath.suffix}"
        safe_name = re.sub(r"[^a-zA-Z0-9._ -]+", "_", out_name).strip()
        return Response(
            content=gp_bytes,
            media_type="application/octet-stream",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Annotated-Notes": str(len(mapping)),
                "X-Fretwise-Biomechanical-Fatal": str(guard["fatal"]),
                "X-Fretwise-Biomechanical-High": str(guard["high"]),
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
    async def get_soundfont() -> Response:
        """Stream the bundled SF2 soundfont file for in-browser synthesis."""
        # Project root is 4 levels up from this file (src/fretwise/web/app.py)
        sf2_path = Path(__file__).parent.parent.parent.parent / "data" / "sounds" / "Shan SGM-Pro 11.SF2"
        if not sf2_path.exists():
            raise HTTPException(404, "Soundfont file not found")
        return Response(
            content=sf2_path.read_bytes(),
            media_type="application/octet-stream",
            headers={"Cache-Control": "public, max-age=86400"},
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
        """Get full metadata for a specific song from the index."""
        cfg = _settings.load()
        songs = load_index(cfg.get("index_path", ""))
        stem = Path(filename).stem
        info = songs.get(filename) or songs.get(stem) or {}
        if not info:
            raise HTTPException(404, f"No metadata found for '{filename}'")
        return JSONResponse(info)


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

# In-memory LRU cache for /api/solve responses. Keyed by (file, mtime, params)
# so it auto-invalidates when the source file is edited. Bounded entry count
# keeps total memory predictable (each response ~ 200-500 KB SVG + results).
from collections import OrderedDict as _OrderedDict  # noqa: E402

_SOLVE_CACHE: _OrderedDict[tuple, dict[str, Any]] = _OrderedDict()
# 128 entries ≈ 64–128 MB max (4 modes × ~32 tracks). Bumped from 32 so that
# the background prefetch (frontend fires N × M solves on file open) doesn't
# evict its own freshly-stored entries.
_SOLVE_CACHE_MAX = 128

# Legacy-results cache, layer below _SOLVE_CACHE. Keyed by (file, mtime,
# track, prefs) — crucially NOT by representation_mode, since the Viterbi
# pipeline output is mode-independent. Profiled cold solve = 2.0s in
# the legacy pipeline + 0.09s in the core/SVG render, so changing the
# view (= same legacy results, different SVG) becomes a 100ms operation
# instead of a 2s one. The per-mode _SOLVE_CACHE stays on top to keep
# repeat-click hits at ~50ms (no SVG re-build, no JSON re-serialise).
_LEGACY_CACHE: _OrderedDict[tuple, dict[str, Any]] = _OrderedDict()
_LEGACY_CACHE_MAX = 32


def _solve_cache_key(
    filepath: Path,
    track_id: int | None,
    representation_mode: str,
    same_finger_motion_penalty: bool,
    infer_implicit_legato: bool,
) -> tuple:
    try:
        mtime = filepath.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (
        str(filepath),
        mtime,
        track_id,
        representation_mode,
        bool(same_finger_motion_penalty),
        bool(infer_implicit_legato),
    )


def _solve_cache_get(key: tuple) -> dict[str, Any] | None:
    payload = _SOLVE_CACHE.get(key)
    if payload is None:
        return None
    _SOLVE_CACHE.move_to_end(key)  # LRU touch
    return payload


def _solve_cache_put(key: tuple, payload: dict[str, Any]) -> None:
    _SOLVE_CACHE[key] = payload
    _SOLVE_CACHE.move_to_end(key)
    while len(_SOLVE_CACHE) > _SOLVE_CACHE_MAX:
        _SOLVE_CACHE.popitem(last=False)


def _solve_cache_clear() -> None:
    """Public-by-convention helper used by tests."""
    _SOLVE_CACHE.clear()
    _LEGACY_CACHE.clear()


def _legacy_cache_key(
    filepath: Path,
    track_id: int | None,
    same_finger_motion_penalty: bool,
    infer_implicit_legato: bool,
) -> tuple:
    """Cache key for the legacy pipeline output (mode-independent)."""
    try:
        mtime = filepath.stat().st_mtime_ns
    except OSError:
        mtime = 0
    return (
        str(filepath),
        mtime,
        track_id,
        bool(same_finger_motion_penalty),
        bool(infer_implicit_legato),
    )


def _legacy_cache_get(key: tuple) -> dict[str, Any] | None:
    entry = _LEGACY_CACHE.get(key)
    if entry is None:
        return None
    _LEGACY_CACHE.move_to_end(key)
    return entry


def _legacy_cache_put(key: tuple, entry: dict[str, Any]) -> None:
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


def _run_legacy_pipeline(
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None
) -> tuple[list[FingeringResult], dict[str, int]]:
    weights = CostWeights.performance()
    generator = StateGenerator()
    player_cost_model = _get_player_cost_model() if weights.gamma > 0 else None
    cost_fn = CostFunction(
        weights=weights,
        rule_preferences=rule_preferences,
        player_cost_model=player_cost_model,
    )
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline(
        events, generator, optimizer, pattern_matcher=matcher,
        chord_finger_classifier=_get_chord_finger_classifier(),
    )


def _run_legacy_pipeline_with_guard(
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None
) -> PipelineResult:
    weights = CostWeights.performance()
    generator = StateGenerator()
    player_cost_model = _get_player_cost_model() if weights.gamma > 0 else None
    cost_fn = CostFunction(
        weights=weights,
        rule_preferences=rule_preferences,
        player_cost_model=player_cost_model,
    )
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline_with_guard_report(
        events, generator, optimizer, pattern_matcher=matcher,
        chord_finger_classifier=_get_chord_finger_classifier(),
    )


def _guard_summary(payload: PipelineResult) -> dict[str, Any]:
    measures = sorted(payload.biomechanical_report.by_measure().keys())
    return {
        "fatal": payload.biomechanical_report.fatal_count,
        "high": payload.biomechanical_report.high_count,
        "measures": measures[:20],
        "measure_count": len(measures),
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


def _infer_title_artist(filepath: Path) -> tuple[str, str]:
    clean_stem = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", filepath.stem).strip()
    parts = clean_stem.split("-", 1)
    auto_artist = parts[0].strip() if len(parts) == 2 else ""
    auto_title = parts[1].strip() if len(parts) == 2 else clean_stem
    return auto_title, auto_artist


def _infer_source_format(path: Path) -> str:
    suffix = path.suffix.lower().lstrip(".")
    if suffix in {"xml", "mxl"}:
        return "musicxml"
    if suffix == "gp":
        return "gpif"
    return suffix


def _process_single_gp(path_str: str) -> dict[str, Any]:
    """Worker — full pipeline for one GP file, returns a JSON-safe status dict.

    Runs in a separate process (ProcessPoolExecutor target), so it must be
    self-contained: import everything it needs locally and never touch
    module-level FastAPI state. Each worker pays a one-shot warm-up
    (parser + ONNX session) on its first call, then amortises across
    every subsequent file it handles.
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
        events = adapter.parse(p)
        if not events:
            return {
                "file": p.name, "status": "skip", "reason": "no notes",
            }
        weights = CostWeights.performance()
        player_cost_model = _get_player_cost_model() if weights.gamma > 0 else None
        cost_fn = CostFunction(weights=weights, player_cost_model=player_cost_model)
        t0 = _time.monotonic()
        payload = run_pipeline_with_guard_report(
            events, StateGenerator(), ViterbiOptimizer(cost_fn),
            pattern_matcher=PatternMatcher(),
            chord_finger_classifier=_get_chord_finger_classifier(),
        )
        if payload.biomechanical_report.fatal_count:
            return {
                "file": p.name,
                "status": "error",
                "error": "biomechanical guard failed",
                "guard": _guard_summary(payload),
            }
        results = payload.results
        elapsed_s = round(_time.monotonic() - t0, 2)
        mapping = fingerings_by_source_id(results)
        gp_bytes = write_gp_with_fingerings(p, mapping)
        out = p.with_name(f"{p.stem}_fingered{p.suffix}")
        out.write_bytes(gp_bytes)
        return {
            "file": p.name, "status": "ok",
            "annotated": len(mapping), "out": out.name,
            "elapsed_s": elapsed_s,
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
) -> tuple[bytes, int]:
    core_result = _run_core_pipeline_for_events(
        filepath,
        adapter,
        events,
        representation_mode=representation_mode,
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
    )


def _extract_measure_regions(
    render_scene: Any,
    canonical_score: Any,
    mode: str = "standard_tablature",
) -> list[dict[str, Any]]:
    """Compute per-measure {measure_idx, x, y0, y1, width} regions for SVG cursor."""
    try:
        from fretwise.core.layout import canonical_to_page_layout  # lazy import

        page_layout = canonical_to_page_layout(canonical_score, mode=mode)

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
        "muted": ne.muted,
        "palm_muted": ne.palm_muted,
        "tapping": ne.tapping,
        "accent": ne.accent,
        "accent_strong": ne.accent_strong,
        "tremolo_picking": ne.tremolo_picking,
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
