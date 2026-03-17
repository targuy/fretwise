"""Notation-core refactoring package.

This package hosts the future layered architecture:
ingest -> normalize -> complete -> validate -> decision -> canonical ->
layout -> graphics -> scene -> backends.
"""

from fretwise.core.pipeline import CorePipelineResult, run_core_pipeline_from_raw

__all__ = [
    "CorePipelineResult",
    "run_core_pipeline_from_raw",
]
