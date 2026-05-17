"""FastAPI application — serves the FretWise tab viewer."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

from . import settings as _settings
from .songs_index import enrich_file_info, load_index

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_bytes
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.core.notation_mode import is_valid_mode as _is_valid_notation_mode
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
                      Defaults to the configured partitions_dir from settings.
    """
    app = FastAPI(title="FretWise", version="0.4.0")

    # Prevent browser from caching JS/CSS during development
    @app.middleware("http")
    async def _no_cache_static(request: Request, call_next: Any) -> Any:
        response = await call_next(request)
        path = request.url.path
        if path.startswith("/static/") and path.endswith((".js", ".css", ".html")):
            response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            response.headers["Pragma"] = "no-cache"
            response.headers["Expires"] = "0"
        return response

    if fixtures_dir is None:
        cfg = _settings.load()
        fixtures_dir = Path(cfg.get("partitions_dir", str(Path(__file__).parents[3] / "partitions")))

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
    async def list_files() -> JSONResponse:
        """List available score files, enriched with songs_index metadata."""
        cfg = _settings.load()
        # Re-read fixtures_dir from settings in case it was updated at runtime
        fixtures: Path = app.state.fixtures_dir
        if not fixtures.exists():
            return JSONResponse([])

        songs = load_index(cfg.get("index_path", ""))

        supported = {
            ".gp3", ".gp4", ".gp5", ".gp",
            ".xml", ".mxl", ".musicxml",
            ".mid", ".midi",
        }
        files = []
        for f in sorted(fixtures.iterdir()):
            if f.suffix.lower() in supported and f.is_file():
                info: dict[str, Any] = {
                    "name": f.name,
                    "stem": f.stem,
                    "format": f.suffix.lstrip(".").upper(),
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
                mode=view_mode.value,
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

    @app.get("/api/download/{filename}")
    async def download_file(filename: str) -> Response:
        """Download the original score file."""
        filepath = _resolve_file(app, filename)
        try:
            content = filepath.read_bytes()
        except OSError as exc:
            raise HTTPException(500, f"Could not read file: {exc}")
        safe_name = Path(filename).name
        suffix = filepath.suffix.lower()
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
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        sf_dir.mkdir(parents=True, exist_ok=True)

        fname = Path(file.filename or "upload.sf2").name
        if not fname.lower().endswith((".sf2", ".sf3", ".dls")):
            raise HTTPException(400, "Only .sf2, .sf3, and .dls files are accepted")

        dest = sf_dir / fname
        try:
            content = await file.read()
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
        cfg = _settings.load()
        sf_dir = Path(cfg.get("soundfonts_dir", "data/sounds"))
        if not sf_dir.is_absolute():
            sf_dir = Path(__file__).parents[3] / sf_dir

        filepath = sf_dir / sf_name
        if not filepath.exists():
            raise HTTPException(404, f"Soundfont not found: {sf_name}")

        _settings.save({"active_soundfont": str(filepath)})
        return JSONResponse({"status": "activated", "name": sf_name})

    @app.get("/api/settings")
    async def get_settings() -> JSONResponse:
        """Get current user settings."""
        return JSONResponse(_settings.load())

    @app.post("/api/settings")
    async def update_settings(request: Request) -> JSONResponse:
        """Update user settings. Partial update supported."""
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
        return JSONResponse(updated)

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
    if _is_valid_notation_mode(normalized):
        return RepresentationMode(normalized)
    raise HTTPException(400, f"Unknown representation_mode: {value!r}")


_CHORD_FINGER_CLASSIFIER: object | None = None
_CHORD_FINGER_CLASSIFIER_LOADED: bool = False


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


def _run_legacy_pipeline(
    events: list[NoteEvent], *, rule_preferences: RulePreferences | None = None
) -> tuple[list[FingeringResult], dict[str, int]]:
    weights = CostWeights.performance()
    generator = StateGenerator()
    cost_fn = CostFunction(weights=weights, rule_preferences=rule_preferences)
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    return run_pipeline(
        events, generator, optimizer, pattern_matcher=matcher,
        chord_finger_classifier=_get_chord_finger_classifier(),
    )


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
