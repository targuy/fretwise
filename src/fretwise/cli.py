"""Command-line interface for FretWise.

Usage:
    fretwise parse song.gp5
    fretwise solve song.gp5
    fretwise finger song.gp
    fretwise solve song.gp5 --mode performance --output song_fingered.pdf
    fretwise solve song.gp5 --mode learning --output song_fingered.txt
    fretwise info song.gp5
    fretwise formats
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

import click

from fretwise.core import run_core_pipeline_from_raw
from fretwise.core.backends import render_scene_to_pdf_file
from fretwise.core.graphics import RepresentationMode
from fretwise.core.ingest import legacy_parse_to_raw_score
from fretwise.export import (
    render_ascii_tab,
    render_combined_pdf,
    render_pdf_tab,
    render_staff_pdf,
    render_text_report,
)
from fretwise.export.gp_writer import fingerings_by_source_id, write_gp_with_fingerings
from fretwise.generator import StateGenerator
from fretwise.models import FingeringResult
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.patterns import PatternMatcher
from fretwise.pdf_conformance import (
    core_pdf_conformance_report,
    legacy_shadow_pdf_conformance_report,
)
from fretwise.pipeline import PipelineResult, run_pipeline_with_guard_report
from fretwise.scoring import CostFunction, CostWeights


def _load_chord_finger_classifier() -> object | None:
    """Load the optional ChordFingerClassifier (Phase 2 ONNX model) if present.

    Returns None silently when the model file or onnxruntime are not available,
    so the CLI keeps working with the rule-based pipeline.
    """
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[2] / "data" / "models"
    model_path = model_dir / "finger_classifier.onnx"
    spec_path = model_dir / "finger_classifier_spec.json"
    if not model_path.exists():
        return None
    try:
        from fretwise.ml import LearnedChordFingerClassifier
        return LearnedChordFingerClassifier(
            str(model_path),
            str(spec_path) if spec_path.exists() else None,
        )
    except (ImportError, FileNotFoundError, AssertionError):
        return None


def _print_audit_summary(
    events: list,
    results: list,
    adapter: object,
    player_cost_model: object | None,
) -> None:
    """Print per-movement audit verdict to stderr (verbose mode).

    Never raises — audit failure is logged but doesn't break the solve.
    """
    try:
        from fretwise.audit import audit_score
        section_markers = dict(getattr(adapter, "section_markers", {}) or {})
        report = audit_score(
            events, results,
            section_markers=section_markers or None,
            ml_cost_model=player_cost_model,
        )
    except Exception as exc:
        click.echo(f"Audit failed: {exc}", err=True)
        return

    bad_count = sum(1 for m in report.movements if m.verdict == "bad")
    suspect_count = sum(1 for m in report.movements if m.verdict == "suspect")
    ml_note = " (ML signal: on)" if report.ml_signal_available else " (ML signal: off)"
    click.echo(
        f"Audit: overall={report.overall}  "
        f"|  {len(report.movements)} movement(s)  "
        f"|  bad={bad_count} suspect={suspect_count}{ml_note}",
        err=True,
    )
    for m in report.movements:
        if m.verdict == "clean":
            continue  # only print non-clean movements (signal-to-noise)
        reasons = ",".join(m.reasons) or "-"
        click.echo(
            f"  - mvt {m.span.measure_start}-{m.span.measure_end} "
            f"({m.span.name}, {m.span.source}): "
            f"{m.verdict}  reasons=[{reasons}]  notes={m.note_count}",
            err=True,
        )


def _load_player_cost_model() -> object | None:
    """Load the optional PlayerCostModel (Phase 3 ONNX transition cost).

    Same defensive pattern as ``_load_chord_finger_classifier``. Only
    contributes when the active CostWeights preset has ``gamma > 0``
    (performance / learning modes).
    """
    from pathlib import Path
    model_dir = Path(__file__).resolve().parents[2] / "data" / "models"
    model_path = model_dir / "transition_cost_v3.onnx"
    spec_path = model_dir / "transition_cost_v3_spec.json"
    if not model_path.exists():
        return None
    try:
        from fretwise.ml import LearnedPlayerCost
        return LearnedPlayerCost(
            str(model_path),
            str(spec_path) if spec_path.exists() else None,
        )
    except (ImportError, FileNotFoundError, AssertionError):
        return None


def _guarded_pipeline_result(
    events: list[Any],
    mode: str,
) -> tuple[PipelineResult, object | None]:
    weights = _MODES[mode]()
    player_cost_model = _load_player_cost_model() if weights.gamma > 0 else None
    cost_fn = CostFunction(weights=weights, player_cost_model=player_cost_model)
    optimizer = ViterbiOptimizer(cost_fn)
    matcher = PatternMatcher()
    payload = run_pipeline_with_guard_report(
        events,
        StateGenerator(),
        optimizer,
        pattern_matcher=matcher,
        chord_finger_classifier=_load_chord_finger_classifier(),
    )
    return payload, player_cost_model


def _format_guard_measures(payload: PipelineResult) -> str:
    measures = sorted(payload.biomechanical_report.by_measure())
    if not measures:
        return "-"
    shown = ",".join(str(measure) for measure in measures[:20])
    if len(measures) > 20:
        shown += f",...(+{len(measures) - 20})"
    return shown


def _write_guarded_gp_file(
    source: Path,
    output: Path,
    payload: PipelineResult,
    *,
    quiet: bool,
) -> None:
    if source.suffix.lower() != ".gp":
        click.echo(
            "Error: GP regeneration only supports Guitar Pro 7/8 (.gp) files.",
            err=True,
        )
        sys.exit(1)
    if payload.biomechanical_report.fatal_count:
        click.echo(
            "Error: biomechanical guard failed before GP export: "
            f"{payload.biomechanical_report.fatal_count} fatal violation(s), "
            f"measures={_format_guard_measures(payload)}",
            err=True,
        )
        sys.exit(1)

    mapping = fingerings_by_source_id(payload.results)
    try:
        gp_bytes = write_gp_with_fingerings(source, mapping)
    except ValueError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    output.write_bytes(gp_bytes)
    if not quiet:
        click.echo(
            f"GP written to '{output}' "
            f"({len(mapping)} annotated note(s), "
            f"fatal={payload.biomechanical_report.fatal_count}, "
            f"high={payload.biomechanical_report.high_count})."
        )

_MODES = {
    "reference": CostWeights.reference,
    "performance": CostWeights.performance,
    "musical": CostWeights.musical,
    "learning": CostWeights.learning,
}

_OUTPUT_FORMATS = ("json", "txt", "pdf", "staff", "combined", "gp")

_SUPPORTED_INPUT = {
    ".gp3": "GuitarPro 3",
    ".gp4": "GuitarPro 4",
    ".gp5": "GuitarPro 5",
    ".gp": "GuitarPro 7/8 (GPIF)",
    ".xml": "MusicXML",
    ".mxl": "MusicXML (compressed)",
    ".musicxml": "MusicXML",
    ".mid": "MIDI",
    ".midi": "MIDI",
}

_SUPPORTED_OUTPUT = {
    "json": "Full note-by-note JSON (all alternatives, costs, fingerings)",
    "txt": "ASCII tablature + text report (plain text, UTF-8)",
    "pdf": "Professional A4 PDF tablature with LH finger annotations",
    "staff": "Standard music notation (treble clef) PDF",
    "combined": "Standard notation + tab stacked PDF",
    "gp": "Guitar Pro 7/8 GPIF with LeftFingering annotations",
}


@click.group()
@click.version_option()
def main() -> None:
    """FretWise - Guitar Fingering Optimization System.

    Computes ergonomically optimal left-hand fingerings for guitar tablature
    using a Viterbi shortest-path algorithm over a biomechanical cost function.

    \b
    Quick start:
      fretwise info song.gp5          # inspect tracks and metadata
      fretwise parse song.gp5         # list all notes with candidate states
      fretwise solve song.gp5         # print JSON fingerings to stdout
      fretwise solve song.gp5 -o out.pdf   # export PDF tablature
    fretwise finger song.gp         # write song_fingered.gp
      fretwise formats                # list supported file formats
    """


# ---------------------------------------------------------------------------
# parse
# ---------------------------------------------------------------------------


@main.command(
    epilog=(
        "\b\nExamples:\n"
        "  fretwise parse song.gp5\n"
        "  fretwise parse song.gp5 --verbose\n"
        "  fretwise parse song.gp5 --limit 50\n"
        "  fretwise parse song.gp5 -v -l 20 --quiet\n"
    )
)
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--verbose", "-v", is_flag=True, help="Show all fields per note.")
@click.option(
    "--limit",
    "-l",
    type=int,
    default=0,
    metavar="N",
    help="Print only the first N notes (0 = all).",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress the header line (useful for piping or scripting).",
)
def parse(file: Path, verbose: bool, limit: int, quiet: bool) -> None:
    """Parse FILE and display the note sequence with candidate states.

    FILE may be GuitarPro (.gp3/.gp4/.gp5/.gp), MusicXML (.xml/.mxl), or MIDI (.mid).
    """
    try:
        adapter = get_adapter(file)
    except UnsupportedFormatError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    generator = StateGenerator()

    try:
        events = adapter.parse(file)
    except UnsupportedFormatError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    except ParseError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not events:
        click.echo("No notes found.")
        return

    if not quiet:
        track_name: str = getattr(adapter, "track_name", "") or ""
        track_info = f"  track: {track_name}" if track_name else ""
        click.echo(f"Parsed {len(events)} note(s) from '{file.name}'.{track_info}\n")

    displayed = events if limit <= 0 else events[:limit]
    for i, event in enumerate(displayed):
        states = generator.states_for(event)
        if verbose:
            click.echo(
                f"[{i:04d}] pitch={event.pitch:3d}  onset={event.onset:.3f}b  "
                f"dur={event.duration:.3f}b  tempo={event.tempo:.0f}bpm  "
                f"art={event.articulation.value}  "
                f"str={event.string_hint}  fret={event.fret_hint}  "
                f"states={len(states)}"
            )
        else:
            click.echo(
                f"[{i:04d}] pitch={event.pitch:3d}  onset={event.onset:.2f}  "
                f"str={event.string_hint}  fret={event.fret_hint}  "
                f"states={len(states)}"
            )

    if limit > 0 and len(events) > limit:
        click.echo(f"\n... {len(events) - limit} more note(s) not shown (use --limit 0 for all).")


# ---------------------------------------------------------------------------
# solve
# ---------------------------------------------------------------------------


@main.command(
    epilog=(
        "\b\nExamples:\n"
        "  fretwise solve song.gp5                           # JSON to stdout\n"
        "  fretwise solve song.gp5 -o out.pdf                # PDF tablature\n"
        "  fretwise solve song.gp5 -o out.txt                # ASCII tab + report\n"
        "  fretwise solve song.gp5 -o out.json               # JSON file\n"
        "  fretwise solve song.gp5 -f pdf -o out.tab         # force PDF format\n"
        "  fretwise solve song.gp5 --mode performance -o fingered.pdf\n"
        "  fretwise solve song.gp5 --title 'My Song' --artist 'Artist'\n"
        "  fretwise solve song.gp5 --measures-per-system 4 -o out.pdf\n"
        "  fretwise solve song.gp5 --beats-per-measure 3 -o out.pdf\n"
    )
)
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--mode",
    type=click.Choice(list(_MODES.keys())),
    default="reference",
    show_default=True,
    help="Weighting mode for the cost function. See 'fretwise formats' for details.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help=(
        "Output file path. Format is inferred from the extension unless "
        "--format is given. Omit to print JSON to stdout."
    ),
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(list(_OUTPUT_FORMATS)),
    default=None,
    help=(
        "Force output format, overriding the file extension. "
        "Choices: json, txt, pdf, staff, combined, gp."
    ),
)
@click.option(
    "--title",
    default=None,
    metavar="TEXT",
    help="Song title for PDF/report header (default: parsed from filename).",
)
@click.option(
    "--artist",
    default=None,
    metavar="TEXT",
    help="Artist/composer name for PDF/report header (default: parsed from filename).",
)
@click.option(
    "--measures-per-system",
    "--mps",
    "measures_per_system",
    type=int,
    default=None,
    metavar="N",
    help="PDF: number of measures per system row (default: auto from note density).",
)
@click.option(
    "--beats-per-measure",
    "--bpm-ts",
    "beats_per_measure",
    type=float,
    default=4.0,
    show_default=True,
    metavar="N",
    help="Time signature numerator used for bar lines and PDF layout (e.g. 3 for 3/4).",
)
@click.option(
    "--pdf-engine",
    type=click.Choice(["legacy", "core"]),
    default="legacy",
    show_default=True,
    help="PDF only: legacy renderer or notation-core RenderScene backend.",
)
@click.option(
    "--representation-mode",
    type=click.Choice([mode.value for mode in RepresentationMode]),
    default=RepresentationMode.STANDARD_TAB.value,
    show_default=True,
    help=(
        "Core notation view mode for PDF/shadow checks: "
        "standard, standard_tablature, tablature_rhythm, tablature."
    ),
)
@click.option("--verbose", "-v", is_flag=True, help="Print per-note cost summary to stderr.")
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress progress messages (useful for scripting; errors still go to stderr).",
)
def solve(
    file: Path,
    mode: str,
    output: Path | None,
    fmt: str | None,
    title: str | None,
    artist: str | None,
    measures_per_system: int | None,
    beats_per_measure: float,
    pdf_engine: str,
    representation_mode: str,
    verbose: bool,
    quiet: bool,
) -> None:
    """Compute optimised fingerings for FILE and output a tablature.

    FILE may be GuitarPro (.gp3/.gp4/.gp5/.gp), MusicXML (.xml/.mxl), or MIDI (.mid).

    \b
    Output formats:
      (none / stdout)  - JSON
      .json            - full note-by-note JSON (fingering + alternatives + cost)
      .txt             - ASCII tablature + text report (plain text)
      .pdf             - A4 PDF tablature with LH finger annotations
            .gp              - Guitar Pro 7/8 file annotated with LeftFingering

    Use --format / -f to override the format inferred from the output extension.
    Use --format staff or --format combined with a .pdf output path
    for standard notation or combined staff+tab PDFs.
    """
    try:
        adapter = get_adapter(file)
    except UnsupportedFormatError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        events = adapter.parse(file)
    except (UnsupportedFormatError, ParseError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not events:
        click.echo("No notes found.")
        return

    payload, player_cost_model = _guarded_pipeline_result(events, mode)
    results = payload.results
    stats = payload.stats
    if not results:
        click.echo("No valid fingering states could be generated.", err=True)
        sys.exit(1)

    if verbose:
        total_cost = sum(r.cost for r in results)
        click.echo(
            f"Parsed {stats['parsed']} notes  |  {len(results)} results  "
            f"|  total cost = {total_cost:.2f}",
            err=True,
        )
        _print_audit_summary(events, results, adapter, player_cost_model)

    # --- resolve output format -----------------------------------------------
    if output is None and fmt is None:
        _print_json(results)
        return

    # Determine the effective format
    if fmt is not None:
        effective_fmt = fmt
    elif output is not None:
        effective_fmt = output.suffix.lstrip(".").lower()
        if effective_fmt not in _OUTPUT_FORMATS:
            click.echo(
                f"Error: Cannot infer format from extension '{output.suffix}'. "
                f"Use --format ({', '.join(_OUTPUT_FORMATS)}) or rename the file.",
                err=True,
            )
            sys.exit(1)
    else:
        effective_fmt = "json"

    # --- resolve metadata ----------------------------------------------------
    track_name: str = getattr(adapter, "track_name", "") or ""
    section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})

    clean_stem = re.sub(r"-\d{2}-\d{2}-\d{4}$", "", file.stem).strip()
    parts = clean_stem.split("-", 1)
    auto_title = parts[1].strip() if len(parts) == 2 else clean_stem
    auto_artist = parts[0].strip() if len(parts) == 2 else ""

    pdf_title = title if title is not None else auto_title
    pdf_artist = artist if artist is not None else auto_artist
    resolved_representation_mode = RepresentationMode(representation_mode)

    # --- write output --------------------------------------------------------
    if output is None:
        # Format forced via --format, no output path: write to stdout where possible
        if effective_fmt == "json":
            _print_json(results)
        elif effective_fmt == "txt":
            hdr = f"{file.stem}  [{mode} mode]"
            click.echo(render_text_report(results, title=hdr))
            click.echo()
            click.echo(render_ascii_tab(results, title=hdr))
        else:
            click.echo(
                f"Error: --format {effective_fmt} requires an --output path "
                f"(PDF cannot be written to stdout).",
                err=True,
            )
            sys.exit(1)
        return

    if effective_fmt == "json":
        output.write_text(_results_to_json(results), encoding="utf-8")
        if not quiet:
            click.echo(f"JSON written to '{output}'.")

    elif effective_fmt == "txt":
        hdr = f"{pdf_title}  [{mode} mode]"
        report = render_text_report(results, title=hdr)
        tab = render_ascii_tab(results, title=hdr)
        output.write_text(report + "\n\n" + tab, encoding="utf-8")
        if not quiet:
            click.echo(f"Text report + ASCII tab written to '{output}'.")

    elif effective_fmt == "pdf":
        if pdf_engine == "core":
            core_result = _run_core_pipeline_for_events(
                file,
                adapter,
                events,
                representation_mode=resolved_representation_mode,
            )
            render_scene_to_pdf_file(core_result.render_scene, output)
            report = core_pdf_conformance_report(len(core_result.conformance_issues))
            if report.issue_count > 0 and not quiet:
                click.echo(
                    f"Core PDF conformance issues: {report.issue_count}",
                    err=True,
                )
        else:
            chord_diagrams = list(getattr(adapter, "chord_diagrams", []) or [])
            render_pdf_tab(
                results,
                output,
                title=pdf_title,
                artist=pdf_artist,
                beats_per_measure=beats_per_measure,
                instrument=track_name,
                mode_label=f"{mode} mode",
                section_markers=section_markers or None,
                measures_per_system=measures_per_system,
                chord_diagrams=chord_diagrams or None,
            )
            shadow_issues, shadow_failed = _shadow_core_conformance_outcome(
                file,
                adapter,
                events,
                representation_mode=resolved_representation_mode,
            )
            report = legacy_shadow_pdf_conformance_report(
                shadow_issues,
                shadow_failed=shadow_failed,
            )
            if report.shadow_failed and not quiet:
                click.echo(
                    "Legacy PDF shadow core conformance unavailable.",
                    err=True,
                )
            elif report.issue_count > 0 and not quiet:
                click.echo(
                    f"Legacy PDF shadow core conformance issues: {report.issue_count}",
                    err=True,
                )
        if not quiet:
            click.echo(f"PDF written to '{output}'.")

    elif effective_fmt == "staff":
        render_staff_pdf(
            results,
            output,
            title=pdf_title,
            artist=pdf_artist,
            beats_per_measure=beats_per_measure,
            instrument=track_name,
            mode_label=f"{mode} mode",
            section_markers=section_markers or None,
            measures_per_system=measures_per_system,
        )
        if not quiet:
            click.echo(f"Staff PDF written to '{output}'.")

    elif effective_fmt == "combined":
        chord_diagrams = list(getattr(adapter, "chord_diagrams", []) or [])
        render_combined_pdf(
            results,
            output,
            title=pdf_title,
            artist=pdf_artist,
            beats_per_measure=beats_per_measure,
            instrument=track_name,
            mode_label=f"{mode} mode",
            section_markers=section_markers or None,
            measures_per_system=measures_per_system,
            chord_diagrams=chord_diagrams or None,
        )
        if not quiet:
            click.echo(f"Combined PDF written to '{output}'.")

    elif effective_fmt == "gp":
        _write_guarded_gp_file(file, output, payload, quiet=quiet)

    else:
        click.echo(f"Error: Unsupported format '{effective_fmt}'.", err=True)
        sys.exit(1)


# ---------------------------------------------------------------------------
# finger
# ---------------------------------------------------------------------------


@main.command(
    epilog=(
        "\b\nExamples:\n"
        "  fretwise finger song.gp\n"
        "  fretwise finger song.gp -o song_checked.gp\n"
        "  fretwise finger song.gp --mode learning\n"
    )
)
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output .gp path (default: FILE stem suffixed with _fingered).",
)
@click.option(
    "--mode",
    type=click.Choice(list(_MODES.keys())),
    default="performance",
    show_default=True,
    help="Weighting mode for the cost function.",
)
@click.option(
    "--quiet",
    "-q",
    is_flag=True,
    help="Suppress success messages; errors still go to stderr.",
)
def finger(file: Path, output: Path | None, mode: str, quiet: bool) -> None:
    """Regenerate one Guitar Pro 7/8 file with left-hand fingerings."""
    if file.suffix.lower() != ".gp":
        click.echo(
            "Error: 'finger' only supports Guitar Pro 7/8 (.gp) files.",
            err=True,
        )
        sys.exit(1)

    try:
        adapter = get_adapter(file)
        events = adapter.parse(file)
    except (UnsupportedFormatError, ParseError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not events:
        click.echo("No notes found.")
        return

    payload, _player_cost_model = _guarded_pipeline_result(events, mode)
    if not payload.results:
        click.echo("No valid fingering states could be generated.", err=True)
        sys.exit(1)

    output_path = output or file.with_name(f"{file.stem}_fingered{file.suffix}")
    _write_guarded_gp_file(file, output_path, payload, quiet=quiet)


# ---------------------------------------------------------------------------
# info
# ---------------------------------------------------------------------------


@main.command(
    epilog=(
        "\b\nExamples:\n"
        "  fretwise info song.gp5\n"
        "  fretwise info song.gp\n"
    )
)
@click.argument("file", type=click.Path(exists=True, path_type=Path))
def info(file: Path) -> None:
    """Display metadata for FILE without computing fingerings.

    Shows track name, note count, tempo range, estimated duration,
    and section markers.  Useful for inspecting a file before solving.

    FILE may be GuitarPro (.gp3/.gp4/.gp5/.gp), MusicXML (.xml/.mxl), or MIDI (.mid).
    """
    try:
        adapter = get_adapter(file)
    except UnsupportedFormatError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    try:
        events = adapter.parse(file)
    except (UnsupportedFormatError, ParseError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    track_name: str = getattr(adapter, "track_name", "") or "(unknown)"
    section_markers: dict[int, str] = dict(getattr(adapter, "section_markers", {}) or {})

    click.echo(f"File    : {file.name}")
    click.echo(f"Format  : {_SUPPORTED_INPUT.get(file.suffix.lower(), file.suffix)}")
    click.echo(f"Track   : {track_name}")

    if not events:
        click.echo("Notes   : 0  (no playable notes found)")
        return

    tempos = sorted({round(e.tempo) for e in events})
    tempo_str = (
        f"{tempos[0]} BPM"
        if len(tempos) == 1
        else f"{tempos[0]}-{tempos[-1]} BPM  ({len(tempos)} changes)"
    )

    # Estimate duration in seconds using last note's onset + duration
    last = max(events, key=lambda e: e.onset + e.duration)
    duration_beats = last.onset + last.duration
    duration_sec = duration_beats / last.tempo * 60.0 if last.tempo > 0 else 0.0
    duration_str = f"{int(duration_sec // 60)}m {int(duration_sec % 60):02d}s"

    # Pitch range
    pitches = [e.pitch for e in events]
    lo_note = _midi_to_note(min(pitches))
    hi_note = _midi_to_note(max(pitches))

    click.echo(f"Notes   : {len(events)}")
    click.echo(f"Tempo   : {tempo_str}")
    click.echo(f"Duration: ~{duration_str}  ({duration_beats:.1f} beats)")
    click.echo(f"Pitch   : {lo_note} to {hi_note}  (MIDI {min(pitches)}-{max(pitches)})")

    if section_markers:
        click.echo(f"Sections: {len(section_markers)}")
        for measure, name in sorted(section_markers.items()):
            click.echo(f"  m{measure:03d}  {name}")
    else:
        click.echo("Sections: (none)")


# ---------------------------------------------------------------------------
# formats
# ---------------------------------------------------------------------------


@main.command()
def formats() -> None:
    """List all supported input and output file formats."""
    click.echo("Input formats (score files):")
    for ext, desc in _SUPPORTED_INPUT.items():
        click.echo(f"  {ext:<8}  {desc}")

    click.echo()
    click.echo("Output formats (--output / --format):")
    for fmt, desc in _SUPPORTED_OUTPUT.items():
        click.echo(f"  {fmt:<8}  {desc}")

    click.echo()
    click.echo("Weighting modes (--mode):  [mech / musical / player / pedagogical]")
    click.echo("  reference    1.0 / 1.0 / 0.0 / 0.0    benchmark / neutral")
    click.echo("  performance  1.0 / 0.5 / 2.0 / 0.0    concert / studio comfort")
    click.echo("  musical      1.0 / 2.0 / 1.0 / 0.0    phrasing / legato focus")
    click.echo("  learning     1.0 / 0.5 / 1.0 / 1.5    pedagogical / technique")


# ---------------------------------------------------------------------------
# web
# ---------------------------------------------------------------------------


@main.command()
@click.option(
    "--port", "-p", default=8080, show_default=True,
    help="Port to serve the web interface on.",
)
@click.option(
    "--dir", "-d", "fixtures_dir", default="partitions",
    type=click.Path(file_okay=False),
    help="Directory containing score files to browse (default: ./partitions).",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
def web(port: int, fixtures_dir: str, host: str) -> None:
    """Launch the interactive Songsterr-style web tab viewer.

    \b
    Opens a browser-based interface for viewing and playing guitar tablature.
    Supports all input formats (GP, MusicXML, MIDI).

    \b
    Example:
      fretwise web --dir ./partitions --port 8080
    """
    try:
        import uvicorn  # type: ignore[import-untyped]
    except ImportError:
        click.echo("Error: uvicorn is required.  pip install uvicorn[standard]", err=True)
        raise SystemExit(1)

    from fretwise.web.app import create_app

    app = create_app(
        Path(fixtures_dir).resolve(),
        allowed_hosts=_web_allowed_hosts(host),
    )
    click.echo(f"FretWise web -> http://{host}:{port}")
    click.echo(f"Score directory: {Path(fixtures_dir).resolve()}")
    click.echo("Press Ctrl+C to stop.\n")
    uvicorn.run(app, host=host, port=port, log_level="warning")


@main.command()
@click.option(
    "--port", "-p", default=8080, show_default=True,
    help="Port to serve the web interface on.",
)
@click.option(
    "--dir", "-d", "fixtures_dir", default="partitions",
    type=click.Path(file_okay=False),
    help="Directory containing score files to browse (default: ./partitions).",
)
@click.option("--host", default="127.0.0.1", show_default=True, help="Bind address.")
def gui(port: int, fixtures_dir: str, host: str) -> None:
    """Launch the web GUI and open it in the default browser.

    \b
    Starts the FretWise web server and immediately opens the interface
    in your default browser.  Equivalent to 'fretwise web' + browser open.

    \b
    Example:
      fretwise gui
      fretwise gui --port 9090 --dir ./partitions
    """
    try:
        import uvicorn  # type: ignore[import-untyped]
    except ImportError:
        click.echo("Error: uvicorn is required.  pip install uvicorn[standard]", err=True)
        raise SystemExit(1)

    import threading
    import webbrowser

    from fretwise.web.app import create_app

    url = f"http://{host}:{port}"
    app = create_app(
        Path(fixtures_dir).resolve(),
        allowed_hosts=_web_allowed_hosts(host),
    )
    click.echo(f"FretWise GUI -> {url}")
    click.echo(f"Score directory: {Path(fixtures_dir).resolve()}")
    click.echo("Press Ctrl+C to stop.\n")

    threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host=host, port=port, log_level="warning")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _web_allowed_hosts(host: str) -> list[str] | None:
    """Compute the Host-header allowlist for the web server.

    Loopback binds keep the secure loopback-only default. A concrete bind
    address is added to the allowlist so the server stays reachable. Binding
    to ``0.0.0.0`` exposes the (unauthenticated) API on every interface, so we
    warn and defer to ``FRETWISE_ALLOWED_HOSTS`` (returning ``None`` lets
    ``create_app`` read that env var) rather than silently trusting all hosts.
    """
    loopback = {"127.0.0.1", "localhost", "::1", ""}
    if host in loopback:
        return None  # create_app applies the loopback-only default / env var
    if host == "0.0.0.0":  # noqa: S104 - user explicitly opted into all interfaces
        click.echo(
            "Warning: binding to 0.0.0.0 exposes the unauthenticated API on all "
            "interfaces. Set FRETWISE_ALLOWED_HOSTS to the hostname(s) clients "
            "use (or '*' to disable the Host-header guard).",
            err=True,
        )
        return None
    return ["localhost", "127.0.0.1", "[::1]", "testserver", host]


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def _midi_to_note(midi: int) -> str:
    """Convert a MIDI pitch number to a human-readable note name (e.g. 64 → 'E4')."""
    return f"{_NOTE_NAMES[midi % 12]}{midi // 12 - 1}"


def _infer_source_format(path: Path) -> str:
    """Infer source format key from file extension."""
    suffix = path.suffix.lower().lstrip(".")
    if suffix == "mxl":
        return "musicxml"
    if suffix == "xml":
        return "musicxml"
    if suffix == "gp":
        return "gpif"
    return suffix


def _shadow_core_conformance_outcome(
    path: Path,
    adapter: Any,
    events: list[Any],
    *,
    representation_mode: RepresentationMode,
) -> tuple[int, bool]:
    """Run core pipeline in shadow mode for legacy PDF diagnostics."""
    try:
        core_result = _run_core_pipeline_for_events(
            path,
            adapter,
            events,
            representation_mode=representation_mode,
        )
    except Exception:
        return 0, True
    return len(core_result.conformance_issues), False


def _run_core_pipeline_for_events(
    path: Path,
    adapter: Any,
    events: list[Any],
    *,
    representation_mode: RepresentationMode,
) -> Any:
    source_beats_per_measure = float(
        getattr(adapter, "beats_per_measure", 4.0) or 4.0
    )
    raw_score = legacy_parse_to_raw_score(
        path,
        source_format=_infer_source_format(path),
        events=events,
        track_name=getattr(adapter, "track_name", "") or "",
        beats_per_measure=source_beats_per_measure,
        time_denominator=int(getattr(adapter, "time_denominator", 4) or 4),
        key_signature_fifths=int(getattr(adapter, "key_signature_fifths", 0) or 0),
        has_anacrusis=bool(getattr(adapter, "has_anacrusis", False)),
        section_markers=dict(getattr(adapter, "section_markers", {}) or {}),
        chord_markers=dict(getattr(adapter, "chord_markers", {}) or {}),
        chord_diagrams=list(getattr(adapter, "chord_diagrams", []) or []),
        measure_time_signatures=dict(getattr(adapter, "measure_time_signatures", {}) or {}),
    )
    return run_core_pipeline_from_raw(
        raw_score,
        representation_mode=representation_mode,
    )


def _results_to_json(results: list[FingeringResult]) -> str:
    """Serialize a list of FingeringResult to a JSON string."""
    data = [
        {
            "note_id": r.note_id,
            "pitch": r.note_event.pitch,
            "onset": r.note_event.onset,
            "duration": r.note_event.duration,
            "tempo": r.note_event.tempo,
            "articulation": r.note_event.articulation.value,
            "string": r.state.string_num,
            "fret": r.state.fret,
            "finger": r.state.finger.value,
            "hand_position": r.state.hand_position,
            "cost": round(r.cost, 4),
            "alternatives": [
                {
                    "string": alt.string_num,
                    "fret": alt.fret,
                    "finger": alt.finger.value,
                    "hand_position": alt.hand_position,
                    "cost": round(c, 4),
                }
                for alt, c in r.alternatives
            ],
        }
        for r in results
    ]
    return json.dumps(data, indent=2)


def _print_json(results: list[FingeringResult]) -> None:
    click.echo(_results_to_json(results))


if __name__ == "__main__":
    main()
