"""FastAPI application — serves the FretWise tab viewer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, Response
from fastapi.staticfiles import StaticFiles

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_bytes
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
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
from fretwise.pdf_conformance import core_pdf_conformance_report
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights, RulePreferences

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
    async def solve_file(
        filename: str,
        track_id: int | None = Query(None),
        representation_mode: str = Query("standard_tablature"),
        same_finger_motion_penalty: bool = Query(True),
        infer_implicit_legato: bool = Query(True),
    ) -> dict[str, Any]:
        """Run the full pipeline and return results as JSON."""
        filepath = _resolve_file(app, filename)
        view_mode = _parse_representation_mode(representation_mode)

        adapter, events = _load_adapter_and_events(filepath, track_id=track_id)

        if not events:
            raise HTTPException(404, "No notes found in file")

        rule_preferences = RulePreferences(
            same_finger_motion_penalty=same_finger_motion_penalty,
            infer_implicit_legato=infer_implicit_legato,
        )
        results, stats = _run_legacy_pipeline(
            events,
            rule_preferences=rule_preferences,
        )
        core_result = _run_core_pipeline_for_events(
            filepath,
            adapter,
            events,
            representation_mode=view_mode,
        )

        # Extract metadata from adapter
        track_name: str = getattr(adapter, "track_name", "") or ""
        midi_program: int = getattr(adapter, "midi_program", -1)
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
            "midi_program": midi_program,
            "mode": "performance",
            "representation_mode": view_mode.value,
            "tempo": tempo,
            "beats_per_measure": beats_per_measure,
            "section_markers": section_markers,
            "chord_diagrams": [_serialize_chord_diagram(cd) for cd in chord_diagrams],
            "chord_markers": chord_markers,
            "core_svg": core_result.svg,
            "core_conformance_issues": len(core_result.conformance_issues),
            "measure_regions": _extract_measure_regions(
                getattr(core_result, "render_scene", None),
                getattr(core_result, "canonical_score", None),
            ),
            "stats": stats,
            "results": [_serialize_result(r) for r in results],
        }

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

        pdf_bytes, conformance_issues = _render_core_pdf_payload(
            filepath,
            adapter,
            events,
            representation_mode=view_mode,
        )
        conformance_report = core_pdf_conformance_report(conformance_issues)

        auto_title, auto_artist = _infer_title_artist(filepath)
        filename_base = auto_title if not auto_artist else f"{auto_artist} - {auto_title}"
        safe_name = _safe_pdf_filename(filename_base)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={
                "Content-Disposition": f'attachment; filename="{safe_name}"',
                "X-Fretwise-Pdf-Engine": "core",
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
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None
) -> tuple[list[FingeringResult], dict[str, int]]:
    weights = CostWeights.performance()
    generator = StateGenerator()
    cost_fn = CostFunction(weights=weights, rule_preferences=rule_preferences)
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
        has_anacrusis=bool(getattr(adapter, "has_anacrusis", False)),
        section_markers=section_markers,
        chord_markers=chord_markers,
        chord_diagrams=chord_diagrams,
    )
    return run_core_pipeline_from_raw(
        raw_score,
        representation_mode=representation_mode,
    )


def _extract_measure_regions(
    render_scene: Any,
    canonical_score: Any,
) -> list[dict[str, Any]]:
    """Compute per-measure {measure_idx, x, y0, y1, width} regions for SVG cursor."""
    try:
        from fretwise.core.layout import canonical_to_page_layout  # lazy import

        page_layout = canonical_to_page_layout(canonical_score)

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
