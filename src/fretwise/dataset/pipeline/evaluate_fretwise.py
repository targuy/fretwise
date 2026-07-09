"""Evaluate FretWise fingering predictions against ground truth annotations.

Runs FretWise's Viterbi pipeline on annotated data and compares its
chosen (string, fret, finger) to ground truth. This is Phase 1 of the
ML integration plan.

Usage:
    python scripts/evaluate_fretwise.py                          # all processed sequences
    python scripts/evaluate_fretwise.py --source chords          # chord voicings only
    python scripts/evaluate_fretwise.py --source gp --limit 50   # first 50 GP sequences
    python scripts/evaluate_fretwise.py --gp-file path/to/song.gp5  # single file
    python scripts/evaluate_fretwise.py --weights performance    # non-default cost weights
    python scripts/evaluate_fretwise.py --no-hints               # full Viterbi (no string/fret hints)

Requires fretwise to be importable (set FRETWISE_SRC or PYTHONPATH).
"""
import argparse
import json
import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from fretwise.dataset.config import PROCESSED_DIR
from fretwise.dataset.converters.unified_to_fingered import unified_record_to_sequences
from fretwise.dataset.data_schema.schema import (
    Finger,
    FingeredChord,
    FingeredNote,
    NoteSequence,
)
from fretwise.dataset.parsers.guitarpro import parse as parse_gp
from fretwise.generator import StateGenerator
from fretwise.models import Finger as FWFinger
from fretwise.models import NoteEvent
from fretwise.optimizer import ViterbiOptimizer
from fretwise.pipeline import run_pipeline
from fretwise.scoring import CostFunction, CostWeights

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


DS_FINGER_TO_FW = {
    Finger.INDEX: FWFinger.INDEX,
    Finger.MIDDLE: FWFinger.MIDDLE,
    Finger.RING: FWFinger.RING,
    Finger.PINKY: FWFinger.PINKY,
}

FW_FINGER_TO_DS = {
    FWFinger.OPEN: Finger.NONE,
    FWFinger.INDEX: Finger.INDEX,
    FWFinger.MIDDLE: Finger.MIDDLE,
    FWFinger.RING: Finger.RING,
    FWFinger.PINKY: Finger.PINKY,
}


@dataclass
class EvalMetrics:
    total_notes: int = 0
    gt_fingered: int = 0
    finger_match: int = 0
    finger_mismatch: int = 0
    string_match: int = 0
    fret_match: int = 0
    position_exact: int = 0
    confusion: dict = field(default_factory=lambda: defaultdict(Counter))
    fret_errors: list = field(default_factory=list)
    per_source: dict = field(default_factory=lambda: defaultdict(lambda: {
        "total": 0, "fingered": 0, "match": 0,
    }))
    use_hints: bool = True

    @property
    def finger_accuracy(self) -> float:
        if self.gt_fingered == 0:
            return 0.0
        return self.finger_match / self.gt_fingered

    @property
    def position_accuracy(self) -> float:
        if self.gt_fingered == 0:
            return 0.0
        return self.position_exact / self.gt_fingered

    def summary(self) -> str:
        mode = "finger-only (string/fret hints given)" if self.use_hints else "full Viterbi (no hints)"
        lines = [
            f"{'='*60}",
            "FretWise Evaluation Results",
            f"{'='*60}",
            f"Mode:                        {mode}",
            f"Total notes evaluated:       {self.total_notes:,}",
            f"Notes with GT fingering:     {self.gt_fingered:,}",
            "  (open strings excluded from finger comparison)",
            "",
            f"Finger accuracy:             {self.finger_accuracy:.1%} ({self.finger_match}/{self.gt_fingered})",
        ]
        if not self.use_hints:
            lines.extend([
                f"String accuracy:             {self.string_match / self.gt_fingered:.1%} ({self.string_match}/{self.gt_fingered})" if self.gt_fingered else "",
                f"Fret accuracy:               {self.fret_match / self.gt_fingered:.1%} ({self.fret_match}/{self.gt_fingered})" if self.gt_fingered else "",
            ])
        lines.extend([
            f"Position exact match:        {self.position_accuracy:.1%} ({self.position_exact}/{self.gt_fingered})",
            "  (string + fret + finger all correct)",
            "",
        ])
        if self.confusion:
            lines.append("Confusion matrix (GT -> FretWise):")
            all_fingers = sorted(set(
                list(self.confusion.keys()) +
                [f for row in self.confusion.values() for f in row.keys()]
            ))
            header = "  GT\\FW    " + "".join(f"{f:>8}" for f in all_fingers)
            lines.append(header)
            for gt_f in all_fingers:
                row_counts = self.confusion.get(gt_f, {})
                row_str = f"  {gt_f:<9}" + "".join(
                    f"{row_counts.get(fw_f, 0):>8}" for fw_f in all_fingers
                )
                lines.append(row_str)
            lines.append("")

        if self.per_source:
            lines.append("Per-source breakdown:")
            for src, s in sorted(self.per_source.items()):
                acc = s["match"] / s["fingered"] if s["fingered"] > 0 else 0
                lines.append(
                    f"  {src:20s}  notes={s['total']:>6,}  "
                    f"fingered={s['fingered']:>6,}  accuracy={acc:.1%}"
                )
            lines.append("")

        return "\n".join(lines)


def sequence_to_noteevents(seq: NoteSequence, *, use_hints: bool = True) -> list[NoteEvent]:
    """Convert a NoteSequence to a list of FretWise NoteEvents.

    With use_hints=True, passes string/fret as hints (finger-only eval).
    With use_hints=False, FretWise must choose position itself (full eval).
    """
    events = []
    onset = 0.0
    for note in seq.notes:
        if note.is_rest:
            onset += note.duration
            continue
        events.append(NoteEvent(
            pitch=note.midi_pitch,
            onset=round(onset, 6),
            duration=round(note.duration, 6),
            tempo=float(seq.tempo),
            string_hint=note.string if use_hints else None,
            fret_hint=note.fret if use_hints else None,
        ))
        onset += note.duration
    return events


def chord_to_noteevents(chord: FingeredChord, *, use_hints: bool = True) -> list[NoteEvent]:
    """Convert a FingeredChord to simultaneous NoteEvents."""
    from fretwise.dataset.config import STANDARD_TUNING
    events = []
    for i, (fret, finger) in enumerate(zip(chord.strings, chord.fingers)):
        if fret is None:
            continue
        string_num = i + 1
        pitch = STANDARD_TUNING[i] + fret
        events.append(NoteEvent(
            pitch=pitch,
            onset=0.0,
            duration=1.0,
            tempo=120.0,
            string_hint=string_num if use_hints else None,
            fret_hint=fret if use_hints else None,
        ))
    return events


def evaluate_sequence(
    seq: NoteSequence,
    generator: StateGenerator,
    optimizer: ViterbiOptimizer,
    metrics: EvalMetrics,
    source_label: str = "",
    use_hints: bool = True,
):
    """Run FretWise on one sequence, compare to ground truth."""
    events = sequence_to_noteevents(seq, use_hints=use_hints)
    if len(events) < 2:
        return

    try:
        results, stats = run_pipeline(events, generator, optimizer)
    except Exception as e:
        logger.debug("Pipeline error on %s: %s", seq.source_file, e)
        return

    playable_notes = [n for n in seq.notes if not n.is_rest]
    if len(results) != len(playable_notes):
        logger.debug(
            "Result count mismatch: %d results vs %d notes (%s)",
            len(results), len(playable_notes), seq.source_file,
        )
        min_len = min(len(results), len(playable_notes))
        results = results[:min_len]
        playable_notes = playable_notes[:min_len]

    for gt_note, result in zip(playable_notes, results):
        metrics.total_notes += 1
        src = source_label or seq.source_type or "unknown"
        metrics.per_source[src]["total"] += 1

        if gt_note.finger == Finger.NONE or gt_note.fret == 0:
            continue

        metrics.gt_fingered += 1
        metrics.per_source[src]["fingered"] += 1

        fw_state = result.state
        fw_finger_ds = FW_FINGER_TO_DS.get(fw_state.finger, Finger.NONE)

        gt_finger_name = gt_note.finger.name
        fw_finger_name = fw_state.finger.name
        metrics.confusion[gt_finger_name][fw_finger_name] += 1

        finger_ok = (fw_finger_ds == gt_note.finger)
        string_ok = (fw_state.string_num == gt_note.string)
        fret_ok = (fw_state.fret == gt_note.fret)

        if finger_ok:
            metrics.finger_match += 1
            metrics.per_source[src]["match"] += 1
        else:
            metrics.finger_mismatch += 1

        if string_ok:
            metrics.string_match += 1
        if fret_ok:
            metrics.fret_match += 1

        if finger_ok and string_ok and fret_ok:
            metrics.position_exact += 1


def evaluate_chord(
    chord: FingeredChord,
    generator: StateGenerator,
    optimizer: ViterbiOptimizer,
    metrics: EvalMetrics,
    use_hints: bool = True,
):
    """Run FretWise on a chord voicing, compare per-string finger."""
    events = chord_to_noteevents(chord, use_hints=use_hints)
    if len(events) < 2:
        return

    try:
        results, stats = run_pipeline(events, generator, optimizer)
    except Exception as e:
        logger.debug("Pipeline error on chord %s: %s", chord.name, e)
        return

    gt_notes = []
    for i, (fret, finger) in enumerate(zip(chord.strings, chord.fingers)):
        if fret is None or finger is None:
            continue
        gt_notes.append((i + 1, fret, finger))

    if len(results) != len(gt_notes):
        min_len = min(len(results), len(gt_notes))
        results = results[:min_len]
        gt_notes = gt_notes[:min_len]

    for (gt_string, gt_fret, gt_finger), result in zip(gt_notes, results):
        metrics.total_notes += 1
        metrics.per_source["chords"]["total"] += 1

        if gt_finger == Finger.NONE or gt_fret == 0:
            continue

        metrics.gt_fingered += 1
        metrics.per_source["chords"]["fingered"] += 1

        fw_state = result.state
        fw_finger_ds = FW_FINGER_TO_DS.get(fw_state.finger, Finger.NONE)

        gt_finger_name = gt_finger.name
        fw_finger_name = fw_state.finger.name
        metrics.confusion[gt_finger_name][fw_finger_name] += 1

        finger_ok = (fw_finger_ds == gt_finger)
        string_ok = (fw_state.string_num == gt_string)
        fret_ok = (fw_state.fret == gt_fret)

        if finger_ok:
            metrics.finger_match += 1
            metrics.per_source["chords"]["match"] += 1
        else:
            metrics.finger_mismatch += 1

        if string_ok:
            metrics.string_match += 1
        if fret_ok:
            metrics.fret_match += 1

        if finger_ok and string_ok and fret_ok:
            metrics.position_exact += 1


def load_sequences(source_filter: str | None = None) -> list[NoteSequence]:
    """Load saved NoteSequences from processed data."""
    sequences = []
    patterns = {
        "chords": ["chord_*.json"],
        "gp": ["gp_fingered_sequences.json", "gp7_all_sequences.json"],
        "musicxml": ["musicxml_fingered_sequences.json"],
        "caged": ["caged_patterns.json"],
    }

    if source_filter:
        files_to_check = patterns.get(source_filter, [])
    else:
        files_to_check = [p for pats in patterns.values() for p in pats]

    for pattern in files_to_check:
        for path in PROCESSED_DIR.glob(pattern):
            try:
                with open(path, encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    for item in data:
                        notes = []
                        for nd in item.get("notes", []):
                            notes.append(FingeredNote(
                                string=nd["string"],
                                fret=nd["fret"],
                                finger=Finger(nd["finger"]),
                                midi_pitch=nd["midi_pitch"],
                                duration=nd["duration"],
                                technique=nd.get("technique", 0),
                                is_rest=nd.get("is_rest", False),
                            ))
                        if notes:
                            sequences.append(NoteSequence(
                                notes=notes,
                                tempo=item.get("tempo", 120),
                                tuning=item.get("tuning", [64, 59, 55, 50, 45, 40]),
                                source_file=item.get("source_file", str(path)),
                                source_type=item.get("source_type", path.stem),
                            ))
                logger.info("Loaded %s: %d sequences", path.name, len(sequences))
            except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
                logger.warning("Could not load %s: %s", path, e)

    return sequences


def load_chords() -> list[FingeredChord]:
    """Load chord voicings from processed data."""
    chords = []
    for path in [PROCESSED_DIR / "chord_dataset.json"]:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                for item in data:
                    fingers = []
                    for fv in item.get("fingers", []):
                        if fv is None:
                            fingers.append(None)
                        else:
                            fingers.append(Finger(fv))
                    chords.append(FingeredChord(
                        name=item.get("name", ""),
                        strings=item.get("strings", []),
                        fingers=fingers,
                        position=item.get("position", 0),
                        is_barre=item.get("is_barre", False),
                        source=item.get("source", ""),
                    ))
            logger.info("Loaded %s: %d chords", path.name, len(chords))
        except (json.JSONDecodeError, KeyError, FileNotFoundError) as e:
            logger.warning("Could not load %s: %s", path, e)
    return chords


def parse_and_evaluate_gp(
    filepath: Path,
    generator: StateGenerator,
    optimizer: ViterbiOptimizer,
    metrics: EvalMetrics,
    use_hints: bool = True,
):
    """Parse a GP file, convert to sequences, evaluate."""
    record = parse_gp(filepath)
    sequences = unified_record_to_sequences(record)
    fingered = [s for s in sequences if s.has_fingering]
    if not fingered:
        logger.info("No fingered sequences in %s", filepath.name)
        return
    for seq in fingered:
        evaluate_sequence(seq, generator, optimizer, metrics,
                          source_label="guitarpro", use_hints=use_hints)


def main():
    parser = argparse.ArgumentParser(description="Evaluate FretWise vs ground truth")
    parser.add_argument("--source", choices=["chords", "gp", "musicxml", "caged"],
                        help="Filter by data source type")
    parser.add_argument("--gp-file", type=Path, help="Evaluate a single GP file")
    parser.add_argument("--limit", type=int, help="Max sequences to evaluate")
    parser.add_argument("--weights", choices=["reference", "performance", "musical", "learning"],
                        default="reference", help="FretWise cost weight preset")
    parser.add_argument("--no-hints", action="store_true",
                        help="Don't pass string/fret hints; let FretWise choose position")
    parser.add_argument("--output", type=Path, help="Save results to JSON file")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    weight_factories = {
        "reference": CostWeights.reference,
        "performance": CostWeights.performance,
        "musical": CostWeights.musical,
        "learning": CostWeights.learning,
    }
    weights = weight_factories[args.weights]()
    cost_fn = CostFunction(weights=weights)
    generator = StateGenerator()
    optimizer = ViterbiOptimizer(cost_fn)

    use_hints = not args.no_hints
    metrics = EvalMetrics(use_hints=use_hints)

    if args.gp_file:
        logger.info("Evaluating single file: %s", args.gp_file)
        parse_and_evaluate_gp(args.gp_file, generator, optimizer, metrics,
                              use_hints=use_hints)
    else:
        if args.source == "chords" or args.source is None:
            chords = load_chords()
            limit = args.limit or len(chords)
            for chord in chords[:limit]:
                evaluate_chord(chord, generator, optimizer, metrics,
                               use_hints=use_hints)

        if args.source != "chords":
            sequences = load_sequences(args.source)
            fingered = [s for s in sequences if s.has_fingering]
            limit = args.limit or len(fingered)
            logger.info(
                "Evaluating %d/%d fingered sequences...",
                min(limit, len(fingered)), len(fingered),
            )
            for seq in fingered[:limit]:
                evaluate_sequence(seq, generator, optimizer, metrics,
                                  use_hints=use_hints)

    print(metrics.summary())

    if args.output:
        result = {
            "mode": "finger_only" if use_hints else "full_viterbi",
            "weights": args.weights,
            "total_notes": metrics.total_notes,
            "gt_fingered": metrics.gt_fingered,
            "finger_match": metrics.finger_match,
            "finger_accuracy": round(metrics.finger_accuracy, 4),
            "position_exact": metrics.position_exact,
            "position_accuracy": round(metrics.position_accuracy, 4),
            "confusion": {
                gt: dict(fw_counts)
                for gt, fw_counts in metrics.confusion.items()
            },
            "per_source": {
                src: dict(s) for src, s in metrics.per_source.items()
            },
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=2)
        print(f"\nResults saved to {args.output}")


if __name__ == "__main__":
    main()
