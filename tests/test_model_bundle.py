"""Integrity and CPU-provider contract for production fingering models."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from fretwise.ml.runtime import create_cpu_session
from fretwise.model_bundle import ModelBundleError, require_model_bundle, validate_model_bundle
from fretwise.web.app import create_app


def test_repository_production_bundle_passes_full_integrity_check() -> None:
    status = validate_model_bundle(verify_hashes=True)

    assert status.available is True
    assert status.version == "fingering-production-2026-08-20"
    assert status.errors == ()


def test_model_bundle_rejects_same_size_tampering(tmp_path: Path) -> None:
    asset = tmp_path / "model.onnx"
    asset.write_bytes(b"trusted")
    manifest = {
        "version": "test-v1",
        "files": [
            {
                "name": asset.name,
                "size": asset.stat().st_size,
                "sha256": hashlib.sha256(asset.read_bytes()).hexdigest(),
            }
        ],
    }
    (tmp_path / "runtime_bundle.json").write_text(json.dumps(manifest), encoding="utf-8")
    assert validate_model_bundle(tmp_path).available is True

    asset.write_bytes(b"changed")

    status = validate_model_bundle(tmp_path)
    assert status.available is False
    assert status.errors == ("sha256 mismatch: model.onnx",)


def test_required_bundle_fails_closed_when_manifest_is_missing(tmp_path: Path) -> None:
    with pytest.raises(ModelBundleError, match="Invalid fingering model bundle"):
        require_model_bundle(tmp_path)


def test_production_session_uses_cpu_provider_exclusively() -> None:
    model_path = Path("data/models/finger_classifier.onnx")

    session = create_cpu_session(model_path)

    assert session.get_providers() == ["CPUExecutionProvider"]


def test_private_model_image_copies_exact_production_onnx_set() -> None:
    manifest = json.loads(Path("data/models/runtime_bundle.json").read_text(encoding="utf-8"))
    expected = {entry["name"] for entry in manifest["files"] if entry["name"].endswith(".onnx")}
    dockerfile = Path("docker/models.Dockerfile").read_text(encoding="utf-8")
    copied = {
        line.split()[1].removeprefix("data/models/")
        for line in dockerfile.splitlines()
        if line.startswith("COPY data/models/") and ".onnx " in line
    }

    assert copied == expected
    assert not any("_v1_" in name for name in copied)


def test_strict_web_startup_rejects_missing_model_bundle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRETWISE_MODEL_DIR", str(tmp_path / "missing"))
    monkeypatch.setenv("FRETWISE_REQUIRE_ML_MODELS", "1")

    with pytest.raises(ModelBundleError, match="Invalid fingering model bundle"):
        create_app(fixtures_dir=tmp_path, runtime_profile="server")
