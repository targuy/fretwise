"""Build and compare reproducible manifests for partition-library migrations."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
from typing import TypedDict, cast


class ManifestEntry(TypedDict):
    """Integrity metadata for one regular file."""

    path: str
    size: int
    mtime_ns: int
    sha256: str


class Manifest(TypedDict):
    """Portable partition-library manifest."""

    schema: str
    root: str
    file_count: int
    byte_count: int
    entries: list[ManifestEntry]


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(root: Path, excluded_names: frozenset[str]) -> Manifest:
    """Hash all regular files below root, including hidden files."""
    resolved_root = root.resolve(strict=True)
    entries: list[ManifestEntry] = []
    for path in sorted(resolved_root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        relative = path.relative_to(resolved_root)
        if any(part in excluded_names for part in relative.parts):
            continue
        if path.is_symlink():
            raise ValueError(f"Symbolic link not supported: {relative.as_posix()}")
        if not path.is_file():
            continue
        stat = path.stat()
        entries.append(
            {
                "path": relative.as_posix(),
                "size": stat.st_size,
                "mtime_ns": stat.st_mtime_ns,
                "sha256": _sha256(path),
            }
        )
    return {
        "schema": "fretwise.partition-manifest.v1",
        "root": str(resolved_root),
        "file_count": len(entries),
        "byte_count": sum(entry["size"] for entry in entries),
        "entries": entries,
    }


def write_manifest(manifest: Manifest, output: Path) -> None:
    """Write manifest atomically."""
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(temporary, output)


def read_manifest(path: Path) -> Manifest:
    """Read a manifest previously produced by this utility."""
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("schema") != "fretwise.partition-manifest.v1":
        raise ValueError(f"Unsupported manifest: {path}")
    return cast(Manifest, raw)


def compare_manifests(source: Manifest, destination: Manifest) -> list[str]:
    """Return integrity differences, tolerating one second of timestamp rounding."""
    source_entries = {entry["path"]: entry for entry in source["entries"]}
    destination_entries = {entry["path"]: entry for entry in destination["entries"]}
    differences: list[str] = []
    for relative in sorted(source_entries.keys() | destination_entries.keys()):
        left = source_entries.get(relative)
        right = destination_entries.get(relative)
        if left is None:
            differences.append(f"extra destination file: {relative}")
            continue
        if right is None:
            differences.append(f"missing destination file: {relative}")
            continue
        if left["size"] != right["size"]:
            differences.append(f"size mismatch: {relative}")
        if left["sha256"] != right["sha256"]:
            differences.append(f"sha256 mismatch: {relative}")
        if abs(left["mtime_ns"] - right["mtime_ns"]) > 1_000_000_000:
            differences.append(f"mtime mismatch: {relative}")
    return differences


def main() -> int:
    """Run scan or compare command."""
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    scan_parser = subparsers.add_parser("scan")
    scan_parser.add_argument("root", type=Path)
    scan_parser.add_argument("output", type=Path)
    scan_parser.add_argument("--exclude-name", action="append", default=[])
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("source", type=Path)
    compare_parser.add_argument("destination", type=Path)
    args = parser.parse_args()

    if args.command == "scan":
        manifest = build_manifest(args.root, frozenset(args.exclude_name))
        write_manifest(manifest, args.output)
        print(
            json.dumps(
                {"file_count": manifest["file_count"], "byte_count": manifest["byte_count"]}
            )
        )
        return 0

    differences = compare_manifests(read_manifest(args.source), read_manifest(args.destination))
    if differences:
        for difference in differences[:100]:
            print(difference)
        print(f"FAILED: {len(differences)} difference(s)")
        return 1
    print("OK: manifests match (bytes, SHA-256, mtime <= 1 s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
