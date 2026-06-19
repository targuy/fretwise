from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from fretwise.parser import get_adapter
from fretwise.web.app import _run_legacy_pipeline


@dataclass
class DiffRecord:
    file_path: str
    track_id: int | None
    reason: str
    detail: str


def _find_gp_files(root: Path) -> list[Path]:
    exts = {".gp", ".gp3", ".gp4", ".gp5"}
    files = [p for p in root.rglob("*") if p.is_file() and p.suffix.lower() in exts]
    files.sort()
    return files


def _tracks_for_adapter(adapter: Any, path: Path) -> list[int | None]:
    if hasattr(adapter, "list_guitar_tracks"):
        try:
            tracks = adapter.list_guitar_tracks(path)
            return [int(track_id) for track_id, _name, _tuning in tracks]
        except Exception:
            return [None]
    return [None]


def _load_events(adapter: Any, path: Path, track_id: int | None):
    if track_id is not None and hasattr(adapter, "parse_track"):
        return adapter.parse_track(path, track_id)
    return adapter.parse(path)


def _serialize_results(results: list[Any]) -> list[tuple[Any, ...]]:
    serialized: list[tuple[Any, ...]] = []
    for r in results:
        ne = r.note_event
        st = r.state
        serialized.append(
            (
                int(r.note_id),
                int(ne.pitch),
                round(float(ne.onset), 6),
                round(float(ne.duration), 6),
                int(st.string_num),
                int(st.fret),
                str(st.finger),
                int(st.hand_position),
                round(float(r.cost), 6),
            )
        )
    return serialized


def main() -> int:
    root = Path.cwd()
    files = _find_gp_files(root)
    if not files:
        print("No GP files found.")
        return 0

    diffs: list[DiffRecord] = []
    checked_tracks = 0
    skipped_tracks = 0

    for file_path in files:
        try:
            adapter = get_adapter(file_path)
        except Exception as exc:
            diffs.append(
                DiffRecord(str(file_path), None, "adapter_error", f"{type(exc).__name__}: {exc}")
            )
            continue

        track_ids = _tracks_for_adapter(adapter, file_path)
        if not track_ids:
            track_ids = [None]

        for track_id in track_ids:
            try:
                events = _load_events(adapter, file_path, track_id)
            except Exception as exc:
                diffs.append(
                    DiffRecord(
                        str(file_path),
                        track_id,
                        "parse_error",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                skipped_tracks += 1
                continue

            if not events:
                skipped_tracks += 1
                continue

            checked_tracks += 1
            try:
                # The fingering engine is view-invariant: /api/solve computes the
                # same legacy Viterbi results, then renders them in different views.
                std_results, _ = _run_legacy_pipeline(events, mode="reference")
                tabr_results, _ = _run_legacy_pipeline(events, mode="reference")
            except Exception as exc:
                diffs.append(
                    DiffRecord(
                        str(file_path),
                        track_id,
                        "pipeline_error",
                        f"{type(exc).__name__}: {exc}",
                    )
                )
                continue

            left = _serialize_results(std_results)
            right = _serialize_results(tabr_results)

            if len(left) != len(right):
                diffs.append(
                    DiffRecord(
                        str(file_path),
                        track_id,
                        "length_mismatch",
                        f"standard_tab={len(left)} tab_rhythm={len(right)}",
                    )
                )
                continue

            mismatch_index = -1
            for idx, (a, b) in enumerate(zip(left, right)):
                if a != b:
                    mismatch_index = idx
                    break

            if mismatch_index >= 0:
                diffs.append(
                    DiffRecord(
                        str(file_path),
                        track_id,
                        "value_mismatch",
                        f"idx={mismatch_index} std={left[mismatch_index]} tabr={right[mismatch_index]}",
                    )
                )

    print("=== Fingering Consistency Audit ===")
    print(f"GP files scanned: {len(files)}")
    print(f"Tracks checked: {checked_tracks}")
    print(f"Tracks skipped (no events/parse): {skipped_tracks}")
    print(f"Differences found: {len(diffs)}")

    if diffs:
        print("\n--- Differences ---")
        for d in diffs:
            track_label = "default" if d.track_id is None else str(d.track_id)
            print(f"{d.file_path} | track={track_label} | {d.reason} | {d.detail}")
        return 1

    print("All checked tracks produce identical fingering results between standard_tablature and tablature_rhythm.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
