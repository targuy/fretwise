"""Compare stored fingerings between two partition directories.

Defaults to comparing files whose stem contains ``_fingered`` and that are
common to ``partitions/`` and ``partitions save/``. For GP 7/8 files, the script reads
``Content/score.gpif`` directly and compares ``LeftFingering`` annotations.

Usage:
    python scripts/compare_partition_fingerings.py
    python scripts/compare_partition_fingerings.py --left partitions --right "partitions save"
"""

from __future__ import annotations

import argparse
import sys
import zipfile
from dataclasses import dataclass
from itertools import zip_longest
from pathlib import Path
from xml.etree import ElementTree as ET


SUPPORTED_SUFFIXES = {".gp", ".gp3", ".gp4", ".gp5"}
GPIF_SCORE_PATH = "Content/score.gpif"


@dataclass(frozen=True)
class FingeredNote:
    """A note occurrence with its stored left-hand fingering annotation."""

    measure: int
    track_index: int
    track_name: str
    voice_index: int
    beat_index: int
    note_index: int
    note_id: str
    string: int | None
    fret: int | None
    finger: str | None


@dataclass(frozen=True)
class ScoreFingerings:
    """Extracted fingering sequence for one score file."""

    path: Path
    notes: list[FingeredNote]
    annotated_count: int


@dataclass(frozen=True)
class PairComparison:
    """Comparison result for one pair of files."""

    key: str
    left: ScoreFingerings
    right: ScoreFingerings
    identical: bool
    different_measures: list[int]
    structure_mismatch_measures: list[int]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Find common fingered Guitar Pro files in two directories and "
            "compare their stored left-hand fingerings."
        )
    )
    parser.add_argument("--left", type=Path, default=Path("partitions"))
    parser.add_argument("--right", type=Path, default=Path("partitions save"))
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compare all supported GP files, not only files ending with _fingered.",
    )
    args = parser.parse_args()

    if not args.left.exists():
        print(f"Left directory not found: {args.left}", file=sys.stderr)
        return 2
    if not args.right.exists():
        print(f"Right directory not found: {args.right}", file=sys.stderr)
        return 2

    left_files = _scan_files(args.left, only_fingered=not args.all)
    right_files = _scan_files(args.right, only_fingered=not args.all)
    common_keys = sorted(set(left_files) & set(right_files))

    print("=== Partitions communes avec doigtes ===")
    print(f"Dossier gauche : {args.left} ({len(left_files)} fichier(s) candidat(s))")
    print(f"Dossier droit  : {args.right} ({len(right_files)} fichier(s) candidat(s))")
    print(f"Communes       : {len(common_keys)}")

    if not common_keys:
        return 0

    for idx, key in enumerate(common_keys, start=1):
        print(f"  {idx:>3}. {key}")

    print("\n=== Comparaison des doigtes ===")
    comparisons: list[PairComparison] = []
    errors = 0

    for key in common_keys:
        left_path = left_files[key]
        right_path = right_files[key]
        try:
            comparison = compare_pair(key, left_path, right_path)
        except Exception as exc:  # noqa: BLE001 - report every file, keep the audit running.
            errors += 1
            print(f"[ERREUR] {key}: {exc}")
            continue
        comparisons.append(comparison)
        print(_format_comparison(comparison))

    identical_count = sum(1 for item in comparisons if item.identical)
    different_count = len(comparisons) - identical_count

    print("\n=== Resume ===")
    print(f"Paires comparees : {len(comparisons)}")
    print(f"Identiques       : {identical_count}")
    print(f"Differentes      : {different_count}")
    print(f"Erreurs          : {errors}")

    return 1 if errors else 0


def _scan_files(root: Path, *, only_fingered: bool) -> dict[str, Path]:
    files: dict[str, Path] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in SUPPORTED_SUFFIXES:
            continue
        if only_fingered and "_fingered" not in path.stem.lower():
            continue
        key = _song_key(path)
        current = files.get(key)
        if current is None or _prefer_path(path, current):
            files[key] = path
    return files


def _song_key(path: Path) -> str:
    stem = path.stem
    marker_index = stem.lower().find("_fingered")
    if marker_index >= 0:
        stem = stem[:marker_index]
    return " ".join(stem.casefold().split())


def _prefer_path(candidate: Path, current: Path) -> bool:
    if candidate.suffix.lower() == ".gp" and current.suffix.lower() != ".gp":
        return True
    return str(candidate).casefold() < str(current).casefold()


def compare_pair(key: str, left_path: Path, right_path: Path) -> PairComparison:
    left = extract_fingerings(left_path)
    right = extract_fingerings(right_path)
    different_measures: set[int] = set()
    structure_mismatch_measures: set[int] = set()

    for left_note, right_note in zip_longest(left.notes, right.notes):
        if left_note is None:
            if right_note is not None:
                structure_mismatch_measures.add(right_note.measure)
            continue
        if right_note is None:
            structure_mismatch_measures.add(left_note.measure)
            continue
        if _structure_key(left_note) != _structure_key(right_note):
            structure_mismatch_measures.update({left_note.measure, right_note.measure})
        if left_note.finger != right_note.finger:
            different_measures.update({left_note.measure, right_note.measure})

    identical = not different_measures and not structure_mismatch_measures
    return PairComparison(
        key=key,
        left=left,
        right=right,
        identical=identical,
        different_measures=sorted(different_measures),
        structure_mismatch_measures=sorted(structure_mismatch_measures),
    )


def extract_fingerings(path: Path) -> ScoreFingerings:
    if path.suffix.lower() == ".gp":
        notes = _extract_gpif_fingerings(path)
    else:
        notes = _extract_pyguitarpro_fingerings(path)
    annotated_count = sum(1 for note in notes if note.finger is not None)
    return ScoreFingerings(path=path, notes=notes, annotated_count=annotated_count)


def _extract_gpif_fingerings(path: Path) -> list[FingeredNote]:
    if not zipfile.is_zipfile(path):
        raise ValueError("not a GPIF zip archive")
    with zipfile.ZipFile(path) as archive:
        try:
            with archive.open(GPIF_SCORE_PATH) as score_file:
                root = ET.parse(score_file).getroot()
        except KeyError as exc:
            raise ValueError(f"missing {GPIF_SCORE_PATH}") from exc

    bars = {bar.get("id"): bar for bar in root.findall("Bars/Bar")}
    voices = {voice.get("id"): voice for voice in root.findall("Voices/Voice")}
    beats = {beat.get("id"): beat for beat in root.findall("Beats/Beat")}
    notes_by_id = {note.get("id"): note for note in root.findall("Notes/Note")}
    track_names = [track.findtext("Name", "").strip() for track in root.findall("Tracks/Track")]

    out: list[FingeredNote] = []
    note_index = 0

    for measure_index, masterbar in enumerate(root.findall("MasterBars/MasterBar"), start=1):
        bar_ids = (masterbar.findtext("Bars") or "").split()
        for track_index, bar_id in enumerate(bar_ids):
            bar = bars.get(bar_id)
            if bar is None:
                continue
            track_name = track_names[track_index] if track_index < len(track_names) else ""
            voice_ids = (bar.findtext("Voices") or "").split()
            for voice_index, voice_id in enumerate(voice_ids):
                if voice_id == "-1":
                    continue
                voice = voices.get(voice_id)
                if voice is None:
                    continue
                for beat_index, beat_id in enumerate((voice.findtext("Beats") or "").split()):
                    beat = beats.get(beat_id)
                    if beat is None:
                        continue
                    for note_id in (beat.findtext("Notes") or "").split():
                        note = notes_by_id.get(note_id)
                        if note is None:
                            continue
                        note_index += 1
                        string, fret = _gpif_string_and_fret(note)
                        out.append(
                            FingeredNote(
                                measure=measure_index,
                                track_index=track_index,
                                track_name=track_name,
                                voice_index=voice_index,
                                beat_index=beat_index,
                                note_index=note_index,
                                note_id=note_id,
                                string=string,
                                fret=fret,
                                finger=_normalize_finger(_gpif_left_fingering(note)),
                            )
                        )
    return out


def _gpif_string_and_fret(note: ET.Element) -> tuple[int | None, int | None]:
    props = {prop.get("name", ""): prop for prop in note.findall("Properties/Property")}
    string = _read_int_property(props.get("String"), "String")
    fret = _read_int_property(props.get("Fret"), "Fret")
    return string, fret


def _read_int_property(prop: ET.Element | None, child_name: str) -> int | None:
    if prop is None:
        return None
    text = prop.findtext(child_name)
    if text is None:
        return None
    try:
        return int(float(text))
    except ValueError:
        return None


def _gpif_left_fingering(note: ET.Element) -> str | None:
    direct = note.findtext("LeftFingering")
    if direct:
        return direct
    for prop in note.findall("Properties/Property"):
        if prop.get("name") != "LeftFingering":
            continue
        return prop.findtext("Value") or prop.text
    return None


def _extract_pyguitarpro_fingerings(path: Path) -> list[FingeredNote]:
    try:
        import guitarpro  # type: ignore[import-untyped]
    except ImportError as exc:
        raise ValueError("PyGuitarPro is required for GP3/GP4/GP5 files") from exc

    song = guitarpro.parse(str(path))
    out: list[FingeredNote] = []
    note_index = 0
    for track_index, track in enumerate(song.tracks):
        track_name = getattr(track, "name", "") or ""
        for measure_index, measure in enumerate(track.measures, start=1):
            for voice_index, voice in enumerate(measure.voices):
                for beat_index, beat in enumerate(voice.beats):
                    for note in beat.notes:
                        note_index += 1
                        effect = getattr(note, "effect", None)
                        finger = (
                            getattr(effect, "leftHandFinger", None)
                            if effect is not None else None
                        )
                        if finger is None:
                            finger = getattr(note, "leftHandFinger", None)
                        out.append(
                            FingeredNote(
                                measure=measure_index,
                                track_index=track_index,
                                track_name=track_name,
                                voice_index=voice_index,
                                beat_index=beat_index,
                                note_index=note_index,
                                note_id=str(note_index),
                                string=getattr(note, "string", None),
                                fret=getattr(note, "value", None),
                                finger=_normalize_finger(finger),
                            )
                        )
    return out


def _normalize_finger(value: object) -> str | None:
    if value is None:
        return None
    if hasattr(value, "name"):
        value = getattr(value, "name")
    elif hasattr(value, "value"):
        value = getattr(value, "value")
    text = str(value).strip()
    if not text or text in {"-1", "0", "none", "None"}:
        return None
    text = text.split(".")[-1].strip().upper()
    aliases = {
        "THUMB": "P",
        "OPEN": "P",
        "INDEX": "I",
        "MIDDLE": "M",
        "RING": "A",
        "PINKY": "C",
        "LITTLE": "C",
        "1": "I",
        "2": "M",
        "3": "A",
        "4": "C",
    }
    return aliases.get(text, text)


def _structure_key(note: FingeredNote) -> tuple[int, int, int, int, int | None, int | None]:
    return (
        note.track_index,
        note.measure,
        note.voice_index,
        note.beat_index,
        note.string,
        note.fret,
    )


def _format_comparison(comparison: PairComparison) -> str:
    left_name = comparison.left.path.name
    right_name = comparison.right.path.name
    note_counts = f"notes {len(comparison.left.notes)}/{len(comparison.right.notes)}"
    fingering_counts = (
        f"doigtes {comparison.left.annotated_count}/{comparison.right.annotated_count}"
    )
    if comparison.identical:
        return f"[OK] {comparison.key}: identiques ({note_counts}, {fingering_counts})"

    measures = _format_measure_list(comparison.different_measures)
    struct = _format_measure_list(comparison.structure_mismatch_measures)
    details = [f"differents mesures {measures}" if measures else "doigtes identiques"]
    if comparison.structure_mismatch_measures:
        details.append(f"structure differente mesures {struct}")
    return (
        f"[DIFF] {comparison.key}: {'; '.join(details)} "
        f"({note_counts}, {fingering_counts})\n"
        f"       gauche: {left_name}\n"
        f"       droit : {right_name}"
    )


def _format_measure_list(measures: list[int]) -> str:
    if not measures:
        return "-"
    ranges: list[str] = []
    start = previous = measures[0]
    for measure in measures[1:]:
        if measure == previous + 1:
            previous = measure
            continue
        ranges.append(str(start) if start == previous else f"{start}-{previous}")
        start = previous = measure
    ranges.append(str(start) if start == previous else f"{start}-{previous}")
    return ", ".join(ranges)


if __name__ == "__main__":
    raise SystemExit(main())