"""FastAPI application — serves the FretWise tab viewer."""

from __future__ import annotations

import re
import tempfile
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_bytes
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.export import render_pdf_tab
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
    core_pdf_conformance_report,
    legacy_shadow_pdf_conformance_report,
)
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"


def create_app(fixtures_dir: Path | None = None) -> FastAPI:
    """Create and configure the FastAPI application.

    Args:
        fixtures_dir: Directory containing GP/MusicXML/MIDI files.
                      Defaults to tests/fixtures/.
    """
    app = FastAPI(title="FretWise", version="0.1.0")

    # Prevent browser from caching JS/CSS during development
    @app.middleware("http")
    async def _no_cache_static(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") and (path.endswith(".js") or path.endswith(".css")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    if fixtures_dir is None:
        # Default to project's test fixtures
        fixtures_dir = Path(__file__).parents[3] / "tests" / "fixtures"

    # Mount static files
    app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    # Store config
    app.state.fixtures_dir = fixtures_dir

    _register_routes(app)
    return app


def _register_routes(app: FastAPI) -> None:
    """Register all API and page routes."""

    @app.get("/", response_class=HTMLResponse)
    async def index() -> HTMLResponse:
        """Serve the main single-page app."""
        html_path = _STATIC_DIR / "index.html"
        return HTMLResponse(content=html_path.read_text(encoding="utf-8"))

    @app.get("/api/files")
    async def list_files() -> list[dict[str, str]]:
        """List available score files."""
        fixtures: Path = app.state.fixtures_dir
        if not fixtures.exists():
            return []

        supported = {
            ".gp3", ".gp4", ".gp5", ".gp",
            ".xml", ".mxl", ".musicxml",
            ".mid", ".midi",
        }
        files = []
        for f in sorted(fixtures.iterdir()):
            if f.suffix.lower() in supported and f.is_file():
                files.append({
                    "name": f.name,
                    "stem": f.stem,
                    "format": f.suffix.lstrip(".").upper(),
                })
        return files

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

    @app.get("/api/solve/{filename}")
    async def solve_file(
        filename: str,
        track_id: int | None = Query(None),
        mode: str = Query("reference"),
        representation_mode: str = Query("standard_tablature"),
    ) -> dict[str, Any]:
        """Run the full pipeline and return results as JSON."""
        filepath = _resolve_file(app, filename)
        modes = _solve_modes()
        if mode not in modes:
            raise HTTPException(400, f"Unknown mode: {mode}")
        view_mode = _parse_representation_mode(representation_mode)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)

        if not events:
            raise HTTPException(404, "No notes found in file")

        results, stats = _run_legacy_pipeline(events, mode=mode)
        core_result = _run_core_pipeline_for_events(
            filepath,
            adapter,
            events,
            representation_mode=view_mode,
        )

        # Extract metadata from adapter
        track_name: str = getattr(adapter, "track_name", "") or ""
        section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})
        chord_diagrams: list[ChordDiagram] = list(
            getattr(adapter, "chord_diagrams", []) or []
        )
        chord_markers: dict[str, str] = dict(
            getattr(adapter, "chord_markers", {}) or {}
        )

        # Parse artist/title from filename
        auto_title, auto_artist = _infer_title_artist(filepath)

        # Determine tempo and time signature
        tempo = events[0].tempo if events else 120.0
        beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0))

        return {
            "title": auto_title,
            "artist": auto_artist,
            "track_name": track_name,
            "mode": mode,
            "representation_mode": view_mode.value,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "section_markers": section_markers,
            "chord_diagrams": [_serialize_chord_diagram(cd) for cd in chord_diagrams],
            "chord_markers": chord_markers,
            "core_svg": core_result.svg,
            "core_conformance_issues": len(core_result.conformance_issues),
            "stats": stats,
            "results": [_serialize_result(r) for r in results],
        }

    @app.get("/api/export/pdf/{filename}")
    async def export_pdf(
        filename: str,
        track_id: int | None = Query(None),
        mode: str = Query("reference"),
        engine: str = Query("legacy"),
        representation_mode: str = Query("standard_tablature"),
    ) -> Response:
        """Render and download a PDF using legacy or notation-core engine."""
        filepath = _resolve_file(app, filename)
        modes = _solve_modes()
        if mode not in modes:
            raise HTTPException(400, f"Unknown mode: {mode}")
        if engine not in {"legacy", "core"}:
            raise HTTPException(400, f"Unknown engine: {engine}")
        view_mode = _parse_representation_mode(representation_mode)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)
        if not events:
            raise HTTPException(404, "No notes found in file")

        if engine == "core":
            pdf_bytes, conformance_issues = _render_core_pdf_payload(
                filepath,
                adapter,
                events,
                representation_mode=view_mode,
            )
            conformance_report = core_pdf_conformance_report(conformance_issues)
        else:
            pdf_bytes, conformance_issues, shadow_failed = _render_legacy_pdf_payload(
                filepath,
                adapter,
                events,
                mode=mode,
                representation_mode=view_mode,
            )
            conformance_report = legacy_shadow_pdf_conformance_report(
                conformance_issues,
                shadow_failed=shadow_failed,
            )

        auto_title, auto_artist = _infer_title_artist(filepath)
        filename_base = auto_title if not auto_artist else f"{auto_artist} - {auto_title}"
        safe_name = _safe_pdf_filename(filename_base)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Pdf-Engine": engine,
                "X-Fretwise-Conformance-Issues": str(conformance_report.issue_count),
                "X-Fretwise-Conformance-Report": conformance_report.to_header_value(),
            },
        )

    @app.post("/api/upload")
    async def upload_file(file: UploadFile = File(...)) -> dict[str, str]:
        """Upload a score file to the fixtures directory."""
        safe_name = Path(file.filename or "upload").name
        if not safe_name:
            raise HTTPException(400, "Invalid filename")
        supported = {".gp3", ".gp4", ".gp5", ".gp", ".xml", ".mxl", ".musicxml", ".mid", ".midi"}
        if Path(safe_name).suffix.lower() not in supported:
            raise HTTPException(400, f"Unsupported file type: {Path(safe_name).suffix}")
        dest: Path = app.state.fixtures_dir / safe_name
        content = await file.read()
        dest.write_bytes(content)
        return {"name": safe_name, "status": "ok"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _resolve_file(app: FastAPI, filename: str) -> Path:
    """Resolve a filename to a safe path within fixtures_dir."""
    # Sanitize: only allow the filename component
    safe_name = Path(filename).name
    filepath = app.state.fixtures_dir / safe_name
    if not filepath.exists():
        raise HTTPException(404, f"File not found: {safe_name}")
    # Prevent path traversal
    try:
        filepath.resolve().relative_to(app.state.fixtures_dir.resolve())
    except ValueError:
        raise HTTPException(403, "Access denied")
    return filepath


def _solve_modes() -> dict[str, Any]:
    return {
        "reference": CostWeights.reference,
        "performance": CostWeights.performance,
        "musical": CostWeights.musical,
        "learning": CostWeights.learning,
    }


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
    try:
        return RepresentationMode(normalized)
    except ValueError as exc:
        raise HTTPException(400, f"Unknown representation_mode: {value}") from exc


def _run_legacy_pipeline(
    events: list[NoteEvent], *, mode: str
) -> tuple[list[FingeringResult], dict[str, int]]:
    weights = _solve_modes()[mode]()
    generator = StateGenerator()
    cost_fn = CostFunction(weights=weights)
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline(events, generator, optimizer, pattern_matcher=matcher)


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


def _render_legacy_pdf_payload(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
    *,
    mode: str,
    representation_mode: RepresentationMode,
) -> tuple[bytes, int, bool]:
    results, _stats = _run_legacy_pipeline(events, mode=mode)
    track_name: str = getattr(adapter, "track_name", "") or ""
    section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})
    chord_diagrams: list[ChordDiagram] = list(getattr(adapter, "chord_diagrams", []) or [])
    beats_per_measure = float(getattr(adapter, "beats_per_measure", 4.0) or 4.0)
    title, artist = _infer_title_artist(filepath)

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        temp_path = Path(tmp.name)
    try:
        render_pdf_tab(
            results,
            temp_path,
            title=title,
            artist=artist,
            beats_per_measure=beats_per_measure,
            instrument=track_name,
            mode_label=f"{mode} mode",
            section_markers=section_markers or None,
            chord_diagrams=chord_diagrams or None,
        )
        conformance_issues, shadow_failed = _shadow_core_conformance_outcome(
            filepath,
            adapter,
            events,
            representation_mode=representation_mode,
        )
        return temp_path.read_bytes(), conformance_issues, shadow_failed
    finally:
        temp_path.unlink(missing_ok=True)


def _safe_pdf_filename(label: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._ -]+", "_", label).strip()
    if not safe:
        safe = "fretwise-export"
    if not safe.lower().endswith(".pdf"):
        safe += ".pdf"
    return safe


def _shadow_core_conformance_outcome(
    filepath: Path,
    adapter: Any,
    events: list[NoteEvent],
    *,
    representation_mode: RepresentationMode,
) -> tuple[int, bool]:
    """Run core pipeline in shadow mode for legacy export diagnostics."""
    try:
        core_result = _run_core_pipeline_for_events(
            filepath,
            adapter,
            events,
            representation_mode=representation_mode,
        )
    except Exception:
        # Legacy PDF export must remain non-blocking while core integration hardens.
        return 0, True
    return len(core_result.conformance_issues), False


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
        has_anacrusis=bool(getattr(adapter, "has_anacrusis", False)),
        section_markers=section_markers,
        chord_markers=chord_markers,
        chord_diagrams=chord_diagrams,
    )
    return run_core_pipeline_from_raw(
        raw_score,
        representation_mode=representation_mode,
    )


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
        "string": st.string_num,
        "fret": st.fret,
        "finger": str(st.finger),
        "hand_position": st.hand_position,
        "cost": r.cost,
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
