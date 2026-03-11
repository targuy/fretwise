"""Command-line interface for FretWise (Sprint 1 — parse command).

Usage:
    fretwise parse song.gp5
    fretwise solve song.gp5
    fretwise solve song.gp5 --mode performance --output song_fingered.gp5

Sprint 1 scope: ``parse`` command only.  ``solve`` and ``export`` are
scaffolded here and will be implemented in Sprint 3.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click

from fretwise.generator import StateGenerator
from fretwise.models import FingeringResult
from fretwise.optimizer import ViterbiOptimizer
from fretwise.parser import get_adapter
from fretwise.parser.base import ParseError, UnsupportedFormatError
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

_MODES = {
    "reference": CostWeights.reference,
    "performance": CostWeights.performance,
    "musical": CostWeights.musical,
    "learning": CostWeights.learning,
}


@click.group()
@click.version_option()
def main() -> None:
    """FretWise — Guitar Fingering Optimization System."""


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option("--verbose", "-v", is_flag=True, help="Show all fields per note.")
def parse(file: Path, verbose: bool) -> None:
    """Parse FILE and display the note sequence with candidate states.

    FILE must be a GuitarPro file (.gp3, .gp4, .gp5, .gp).
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

    click.echo(f"Parsed {len(events)} note(s) from '{file.name}'.\n")

    for i, event in enumerate(events):
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


@main.command()
@click.argument("file", type=click.Path(exists=True, path_type=Path))
@click.option(
    "--mode",
    type=click.Choice(list(_MODES.keys())),
    default="reference",
    show_default=True,
    help="Weighting mode for the cost function.",
)
@click.option(
    "--output",
    "-o",
    type=click.Path(path_type=Path),
    default=None,
    help="Output file path (.gp5 or .json). Defaults to stdout JSON.",
)
@click.option("--verbose", "-v", is_flag=True, help="Print per-note cost details.")
def solve(file: Path, mode: str, output: Path | None, verbose: bool) -> None:
    """Compute optimised fingerings for FILE and output a tablature.

    FILE must be a GuitarPro file (.gp3, .gp4, .gp5, .gp).
    """
    try:
        adapter = get_adapter(file)
    except UnsupportedFormatError as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)
    generator = StateGenerator()
    weights = _MODES[mode]()
    cost_fn = CostFunction(weights=weights)
    optimizer = ViterbiOptimizer(cost_fn)

    try:
        events = adapter.parse(file)
    except (UnsupportedFormatError, ParseError) as exc:
        click.echo(f"Error: {exc}", err=True)
        sys.exit(1)

    if not events:
        click.echo("No notes found.")
        return

    results, stats = run_pipeline(events, generator, optimizer)
    if not results:
        click.echo("No valid fingering states could be generated.", err=True)
        sys.exit(1)

    if output is None:
        _print_json(results)
    elif output.suffix.lower() == ".json":
        output.write_text(_results_to_json(results), encoding="utf-8")
        click.echo(f"JSON written to '{output}'.")
    else:
        click.echo(
            f"Output format '{output.suffix}' not yet supported in Sprint 1. "
            "Use .json or omit --output for stdout.",
            err=True,
        )
        sys.exit(1)

    if verbose:
        total_cost = sum(r.cost for r in results)
        click.echo(f"\nTotal cost: {total_cost:.2f}  |  Notes: {len(results)}", err=True)


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
