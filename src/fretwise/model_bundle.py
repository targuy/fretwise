"""Validated runtime bundle for CPU-based fingering inference."""

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

_MANIFEST_NAME = "runtime_bundle.json"


class ModelBundleError(RuntimeError):
    """Raised when required runtime models are missing or invalid."""


@dataclass(frozen=True)
class ModelBundleStatus:
    """Validation result for one runtime model bundle."""

    available: bool
    version: str
    model_dir: Path
    errors: tuple[str, ...]

    def to_json(self) -> dict[str, object]:
        """Return public runtime status without exposing filesystem paths."""
        return {
            "available": self.available,
            "version": self.version,
            "engine": "onnxruntime-cpu" if self.available else "rules",
        }


def resolve_model_dir(model_dir: str | Path | None = None) -> Path:
    """Resolve model directory from argument, environment, or repository layout."""
    if model_dir is not None:
        return Path(model_dir)
    configured = os.environ.get("FRETWISE_MODEL_DIR", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[2] / "data" / "models"


def model_bundle_required() -> bool:
    """Return whether startup must fail when production models are unavailable."""
    value = os.environ.get("FRETWISE_REQUIRE_ML_MODELS", "").strip().lower()
    return value in {"1", "true", "yes", "on"}


def validate_model_bundle(
    model_dir: str | Path | None = None,
    *,
    verify_hashes: bool = True,
) -> ModelBundleStatus:
    """Validate runtime assets against tracked sizes and SHA-256 digests."""
    directory = resolve_model_dir(model_dir)
    manifest_path = directory / _MANIFEST_NAME
    errors: list[str] = []
    version = "unknown"
    if importlib.util.find_spec("onnxruntime") is None:
        errors.append("onnxruntime is not installed")
    try:
        raw: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ModelBundleStatus(False, version, directory, (f"invalid manifest: {exc}",))
    if not isinstance(raw, dict):
        return ModelBundleStatus(False, version, directory, ("manifest must be an object",))
    raw_version = raw.get("version")
    if isinstance(raw_version, str) and raw_version:
        version = raw_version
    else:
        errors.append("manifest version is missing")
    files = raw.get("files")
    if not isinstance(files, list) or not files:
        errors.append("manifest files list is missing")
        return ModelBundleStatus(False, version, directory, tuple(errors))
    for entry in files:
        if not isinstance(entry, dict):
            errors.append("invalid file entry")
            continue
        name = entry.get("name")
        digest = entry.get("sha256")
        size = entry.get("size")
        if (
            not isinstance(name, str)
            or Path(name).name != name
            or not isinstance(digest, str)
            or len(digest) != 64
            or not isinstance(size, int)
            or size < 1
        ):
            errors.append("invalid file metadata")
            continue
        path = directory / name
        try:
            actual_size = path.stat().st_size
        except OSError:
            errors.append(f"missing model asset: {name}")
            continue
        if actual_size != size:
            errors.append(f"size mismatch: {name}")
            continue
        if verify_hashes:
            actual_digest = hashlib.sha256(path.read_bytes()).hexdigest()
            if actual_digest != digest:
                errors.append(f"sha256 mismatch: {name}")
    return ModelBundleStatus(not errors, version, directory, tuple(errors))


def require_model_bundle(model_dir: str | Path | None = None) -> ModelBundleStatus:
    """Validate required production models or fail before serving requests."""
    status = validate_model_bundle(model_dir, verify_hashes=True)
    if not status.available:
        raise ModelBundleError("Invalid fingering model bundle: " + "; ".join(status.errors))
    return status


def main(argv: Sequence[str] | None = None) -> int:
    """Validate a model directory for release packaging."""
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("model_dir", nargs="?", help="directory containing production models")
    args = parser.parse_args(argv)
    status = validate_model_bundle(args.model_dir, verify_hashes=True)
    print(json.dumps(status.to_json(), sort_keys=True))
    if not status.available:
        for error in status.errors:
            print(error, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised as deployment command
    raise SystemExit(main())
