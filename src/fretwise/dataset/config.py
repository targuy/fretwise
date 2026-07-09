"""Configuration for the FretWise dataset / training package.

Port of ``GuitarDataSet/config.py``. The bulky raw/processed training data
stays in the GuitarDataSet working tree — it is NOT copied into this repo.
Locations are resolved through environment variables:

- ``FRETWISE_DATASET_ROOT``: root of the GuitarDataSet data factory
  (default: ``D:\\DocumentsBenoit\\pythonProject\\GuitarDataSet``).
- ``FRETWISE_HANDOFF_DIR``: shared handoff directory between GuitarDataSet
  and FretWise (default:
  ``D:\\DocumentsBenoit\\pythonProject\\handoff-FretWise-GuitarDataset``).
  Replaces the hardcoded, machine-specific paths of the original pipeline
  scripts.

Deployed model artifacts consumed by ``fretwise.ml`` live in this repo at
``data/models`` (:data:`MODELS_DIR`, computed relative to this file).
"""
from __future__ import annotations

import os
from pathlib import Path

#: Root of the GuitarDataSet data factory (training data stays there).
DATASET_ROOT = Path(
    os.environ.get(
        "FRETWISE_DATASET_ROOT",
        r"D:\DocumentsBenoit\pythonProject\GuitarDataSet",
    )
)

#: Handoff directory shared with GuitarDataSet (specs, calibrations, bundles).
HANDOFF_DIR = Path(
    os.environ.get(
        "FRETWISE_HANDOFF_DIR",
        r"D:\DocumentsBenoit\pythonProject\handoff-FretWise-GuitarDataset",
    )
)

#: FretWise repo root (…/src/fretwise/dataset/config.py -> repo).
REPO_ROOT = Path(__file__).resolve().parents[3]

#: Deployment target for trained model bundles consumed by ``fretwise.ml``.
MODELS_DIR = REPO_ROOT / "data" / "models"

# Legacy alias: GuitarDataSet's config.ROOT_DIR pointed at the factory root.
ROOT_DIR = DATASET_ROOT

DATA_DIR = DATASET_ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
DATASETS_DIR = DATA_DIR / "datasets"

GP_RAW_DIR = RAW_DIR / "gp_files"
CHORDS_RAW_DIR = RAW_DIR / "chords"
MUSICXML_RAW_DIR = RAW_DIR / "musicxml"

GP_EXTENSIONS = {".gp3", ".gp4", ".gp5", ".gpx", ".gp"}

STANDARD_TUNING = [64, 59, 55, 50, 45, 40]  # E4 B3 G3 D3 A2 E2 (MIDI)

FINGER_NAMES = {0: "none", 1: "index", 2: "middle", 3: "ring", 4: "pinky", 5: "thumb"}

MAX_FRET_SPAN = 5
NUM_STRINGS = 6
NUM_FRETS = 24

REQUEST_DELAY = 1.0
USER_AGENT = "GuitarDataSet/1.0 (research project)"
