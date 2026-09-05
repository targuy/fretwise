"""ONNX Runtime session policy for deterministic CPU inference."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol, cast


class OnnxNode(Protocol):
    """Named ONNX graph input or output."""

    name: str


class OnnxSession(Protocol):
    """Minimal session surface consumed by FretWise predictors."""

    def get_inputs(self) -> list[OnnxNode]: ...

    def get_outputs(self) -> list[OnnxNode]: ...

    def get_providers(self) -> list[str]: ...

    # ONNX Runtime deliberately returns heterogeneous NumPy tensors whose
    # concrete generic shapes cannot be expressed by its public Python API.
    def run(self, output_names: object, input_feed: object) -> list[Any]: ...


def create_cpu_session(model_path: str | Path) -> OnnxSession:
    """Create one sequential ONNX session pinned to CPUExecutionProvider."""
    import onnxruntime as ort

    options = ort.SessionOptions()
    options.execution_mode = ort.ExecutionMode.ORT_SEQUENTIAL
    options.inter_op_num_threads = 1
    raw_threads = os.environ.get("FRETWISE_ONNX_THREADS", "1").strip()
    try:
        intra_threads = int(raw_threads)
    except ValueError as exc:
        raise ValueError("FRETWISE_ONNX_THREADS must be a positive integer") from exc
    if intra_threads < 1:
        raise ValueError("FRETWISE_ONNX_THREADS must be a positive integer")
    options.intra_op_num_threads = intra_threads
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    if session.get_providers() != ["CPUExecutionProvider"]:
        raise RuntimeError("ONNX session did not activate CPUExecutionProvider exclusively")
    return cast(OnnxSession, session)
