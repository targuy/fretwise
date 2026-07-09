"""Tests for the ``fretwise.dataset`` port of the GuitarDataSet library.

Three layers:

1. **Smoke imports** — every ported submodule must import without the
   optional ML training dependencies (xgboost / onnxmltools / bs4 are NOT
   installed in the default pixi env; heavy deps are lazily guarded through
   ``fretwise.dataset._mldeps``).
2. **Feature parity** (the binding contract) — the ported *training*
   extractor ``fretwise.dataset.features.phrase_window_features`` and the
   production *inference* extractor ``fretwise.ml.phrase_window`` must
   produce identical 74-dim vectors. Verified three ways: identical feature
   name ordering, bit-parity (1e-6) on every ``expected_features`` case of
   the shipped v1/v2 calibration JSONs, and cross-parity on synthetic
   windows (padding, open strings, legato, repeated positions).
3. **Biomechanical validator** — span/duplicate-finger rejections.
"""
from __future__ import annotations

import importlib
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
MODELS = REPO_ROOT / "data" / "models"

ATOL = 1e-6

PORTED_MODULES = [
    "fretwise.dataset",
    "fretwise.dataset.config",
    "fretwise.dataset._mldeps",
    "fretwise.dataset.parsers",
    "fretwise.dataset.parsers.base",
    "fretwise.dataset.parsers.guitarpro",
    "fretwise.dataset.parsers.musicxml",
    "fretwise.dataset.parsers.midi",
    "fretwise.dataset.parsers.ascii_tab",
    "fretwise.dataset.parsers.chord_db",
    "fretwise.dataset.features.chord_features",
    "fretwise.dataset.features.phrase_window_features",
    "fretwise.dataset.features.transition_v4_features",
    "fretwise.dataset.exporters.fretwise",
    "fretwise.dataset.exporters.jsonl",
    "fretwise.dataset.exporters.parquet",
    "fretwise.dataset.exporters.dadagp_tokens",
    "fretwise.dataset.data_schema.schema",
    "fretwise.dataset.data_schema.unify",
    "fretwise.dataset.data_schema.caged_patterns",
    "fretwise.dataset.converters.unified_to_fingered",
    "fretwise.dataset.inference.finger_classifier",
    "fretwise.dataset.processors.validator",
    "fretwise.dataset.scrapers.chord_scraper",
    "fretwise.dataset.pipeline.build_chord_dataset",
    "fretwise.dataset.pipeline.build_transition_features",
    "fretwise.dataset.pipeline.build_phrase_window_dataset",
    "fretwise.dataset.pipeline.build_sequential_training_set",
    "fretwise.dataset.pipeline.build_calibration_examples",
    "fretwise.dataset.pipeline.build_spec_json",
    "fretwise.dataset.pipeline.build_transition_spec_json",
    "fretwise.dataset.pipeline.train_finger_classifier",
    "fretwise.dataset.pipeline.train_transition_cost_v3",
    "fretwise.dataset.pipeline.train_phrase_window_v1",
    "fretwise.dataset.pipeline.export_transition_onnx",
    "fretwise.dataset.pipeline.evaluate_fretwise",
    "fretwise.dataset.pipeline.eval_phrase_window_v1",
    "fretwise.dataset.pipeline.eval_pinky_demotion",
    "fretwise.dataset.pipeline.validate_fingering_quality",
]


# ---------------------------------------------------------------------------
# 1. Smoke imports (must work without xgboost / onnxmltools / bs4)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("module", PORTED_MODULES)
def test_ported_module_imports(module: str) -> None:
    importlib.import_module(module)


def test_missing_ml_dep_raises_clear_error_on_use_only() -> None:
    from fretwise.dataset._mldeps import MissingDependency, optional_import

    stub = optional_import("definitely_not_installed_xyz")
    assert isinstance(stub, MissingDependency)  # importing never raises
    with pytest.raises(ImportError, match="training pipeline"):
        stub.DMatrix  # noqa: B018 - attribute access is the trigger
    with pytest.raises(ImportError, match="training pipeline"):
        stub()


def test_pipeline_modules_expose_main() -> None:
    for module in PORTED_MODULES:
        if ".pipeline." in module:
            assert callable(getattr(importlib.import_module(module), "main"))


def test_config_paths_are_env_overridable(monkeypatch: pytest.MonkeyPatch) -> None:
    import fretwise.dataset.config as cfg

    monkeypatch.setenv("FRETWISE_DATASET_ROOT", r"C:\elsewhere\gds")
    monkeypatch.setenv("FRETWISE_HANDOFF_DIR", r"C:\elsewhere\handoff")
    fresh = importlib.reload(cfg)
    try:
        assert fresh.DATASET_ROOT == Path(r"C:\elsewhere\gds")
        assert fresh.PROCESSED_DIR == Path(r"C:\elsewhere\gds") / "data" / "processed"
        assert fresh.HANDOFF_DIR == Path(r"C:\elsewhere\handoff")
        assert fresh.MODELS_DIR == REPO_ROOT / "data" / "models"
    finally:
        monkeypatch.undo()
        importlib.reload(cfg)


# ---------------------------------------------------------------------------
# 2. Feature parity: training extractor (port) vs inference extractor (ml)
# ---------------------------------------------------------------------------


def _training_features():
    from fretwise.dataset.features import phrase_window_features as gds

    return gds


def _ml_features():
    from fretwise.ml import phrase_window as ml

    return ml


def _to_phrase_notes(raw: list[dict]):
    """Calibration ``input_notes`` dicts -> inference PhraseNotes (0-based)."""
    ml = _ml_features()
    return [
        ml.PhraseNote(
            string=n["string"],
            fret=n["fret"],
            pitch=n.get("midi", n.get("pitch", 0)),
            onset=n["onset"],
            duration=n["duration"],
            is_chord_member=bool(n.get("is_chord_member")),
            has_legato=any(
                t in ("hammer_on", "pull_off", "slide")
                for t in (n.get("techniques") or [])
            ),
        )
        for n in raw
    ]


def test_feature_names_identical_and_74() -> None:
    gds = _training_features()
    ml = _ml_features()
    train_names = gds.feature_names(gds.WINDOW_SIZE)
    infer_names = ml.phrase_window_feature_names(ml.WINDOW_SIZE)
    assert len(train_names) == 74
    assert tuple(train_names) == tuple(infer_names)


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_training_extractor_reproduces_calibration_vectors(version: str) -> None:
    """The PORTED training extractor reproduces the shipped calibration
    ``expected_features`` (which were generated by the original
    ``src/features/phrase_window_features.py``) to 1e-6."""
    gds = _training_features()
    path = MODELS / f"phrase_window_fingering_{version}_calibration.json"
    if not path.exists():
        pytest.skip(f"calibration file missing: {path}")
    calibration = json.loads(path.read_text(encoding="utf-8"))
    names = gds.feature_names(gds.WINDOW_SIZE)
    for ex in calibration["examples"]:
        fv = gds.build_window_feature_vector(
            ex["input_notes"], ex["candidate_anchor"], gds.WINDOW_SIZE
        )
        assert set(fv.keys()) == set(names), ex["case_id"]
        expected = ex.get("expected_features") or ex.get("expected_features_partial")
        for key, value in expected.items():
            assert abs(fv[key] - value) <= ATOL, (
                f"{ex['case_id']}::{key} got {fv[key]} expected {value}"
            )


@pytest.mark.parametrize("version", ["v1", "v2"])
def test_training_and_inference_extractors_agree_on_calibration(version: str) -> None:
    """Full 74-dim cross-parity: ported training module vs fretwise.ml."""
    gds = _training_features()
    ml = _ml_features()
    path = MODELS / f"phrase_window_fingering_{version}_calibration.json"
    if not path.exists():
        pytest.skip(f"calibration file missing: {path}")
    calibration = json.loads(path.read_text(encoding="utf-8"))
    for ex in calibration["examples"]:
        train_fv = gds.build_window_feature_vector(
            ex["input_notes"], ex["candidate_anchor"], gds.WINDOW_SIZE
        )
        infer_fv = ml.build_window_feature_vector(
            _to_phrase_notes(ex["input_notes"]), ex["candidate_anchor"], ml.WINDOW_SIZE
        )
        assert set(train_fv.keys()) == set(infer_fv.keys()), ex["case_id"]
        for key, value in train_fv.items():
            assert abs(infer_fv[key] - value) <= ATOL, (
                f"{ex['case_id']}::{key} training={value} inference={infer_fv[key]}"
            )


SYNTHETIC_WINDOWS: list[tuple[str, list[dict]]] = [
    (
        "short_window_with_open_and_legato",
        [
            {"string": 0, "fret": 0, "midi": 64, "onset": 0.0, "duration": 0.5},
            {
                "string": 2, "fret": 5, "midi": 60, "onset": 0.5, "duration": 1.0,
                "techniques": ["hammer_on"],
            },
            {"string": 2, "fret": 7, "midi": 62, "onset": 1.5, "duration": 0.25},
        ],
    ),
    (
        "repeated_positions_and_chord_member",
        [
            {"string": 1, "fret": 7, "midi": 66, "onset": 0.0, "duration": 1.0},
            {"string": 1, "fret": 7, "midi": 66, "onset": 1.0, "duration": 1.0,
             "is_chord_member": True},
            {"string": 1, "fret": 5, "midi": 64, "onset": 2.0, "duration": 1.0},
            {"string": 3, "fret": 5, "midi": 55, "onset": 3.0, "duration": 0.5},
            {"string": 1, "fret": 7, "midi": 66, "onset": 3.5, "duration": 1.0},
        ],
    ),
    (
        "all_open_window",
        [
            {"string": 0, "fret": 0, "midi": 64, "onset": 0.0, "duration": 1.0},
            {"string": 1, "fret": 0, "midi": 59, "onset": 1.0, "duration": 1.0},
            {"string": 2, "fret": 0, "midi": 55, "onset": 2.0, "duration": 1.0},
        ],
    ),
]


@pytest.mark.parametrize(
    "notes", [w for _, w in SYNTHETIC_WINDOWS], ids=[n for n, _ in SYNTHETIC_WINDOWS]
)
def test_synthetic_window_parity_across_all_candidate_anchors(notes: list[dict]) -> None:
    gds = _training_features()
    ml = _ml_features()
    phrase_notes = _to_phrase_notes(notes)

    train_anchors = gds.candidate_anchors(notes)
    infer_anchors = ml.candidate_anchors(phrase_notes)
    assert train_anchors == infer_anchors

    for anchor in train_anchors:
        train_fv = gds.build_window_feature_vector(notes, anchor, gds.WINDOW_SIZE)
        infer_fv = ml.build_window_feature_vector(phrase_notes, anchor, ml.WINDOW_SIZE)
        assert set(train_fv.keys()) == set(infer_fv.keys())
        for key, value in train_fv.items():
            assert abs(infer_fv[key] - value) <= ATOL, (
                f"anchor {anchor}::{key} training={value} inference={infer_fv[key]}"
            )


# ---------------------------------------------------------------------------
# 3. Biomechanical validator (fretwise.dataset.processors.validator)
# ---------------------------------------------------------------------------


def _chord(strings, fingers, *, is_barre=False):
    from fretwise.dataset.data_schema.schema import FingeredChord

    return FingeredChord(
        name="test", strings=strings, fingers=fingers, is_barre=is_barre
    )


def test_validator_rejects_fret_span_over_five() -> None:
    from fretwise.dataset.data_schema.schema import Finger
    from fretwise.dataset.processors.validator import validate_chord

    chord = _chord(
        [1, None, None, None, 8, None],
        [Finger.INDEX, None, None, None, Finger.PINKY, None],
    )
    issues = validate_chord(chord)
    assert any(i.startswith("fret_span_too_large") for i in issues)


def test_validator_rejects_duplicate_finger_on_different_frets() -> None:
    from fretwise.dataset.data_schema.schema import Finger
    from fretwise.dataset.processors.validator import validate_chord

    chord = _chord(
        [2, 4, None, None, None, None],
        [Finger.MIDDLE, Finger.MIDDLE, None, None, None, None],
    )
    issues = validate_chord(chord)
    assert any("finger_MIDDLE_on_multiple_frets" in i for i in issues)


def test_validator_accepts_valid_open_chord_and_index_barre() -> None:
    from fretwise.dataset.data_schema.schema import Finger
    from fretwise.dataset.processors.validator import validate_chord

    # E major open shape: 0-2-2-1-0-0 with ring/middle/index.
    e_major = _chord(
        [0, 2, 2, 1, 0, 0],
        [None, Finger.RING, Finger.MIDDLE, Finger.INDEX, None, None],
    )
    assert validate_chord(e_major) == []

    # F major barre: index on fret 1 across strings is exempt when is_barre.
    f_barre = _chord(
        [1, 3, 3, 2, 1, 1],
        [Finger.INDEX, Finger.RING, Finger.PINKY, Finger.MIDDLE,
         Finger.INDEX, Finger.INDEX],
        is_barre=True,
    )
    assert validate_chord(f_barre) == []


def test_validator_transition_same_finger_different_position() -> None:
    from fretwise.dataset.data_schema.schema import Finger, FingeredNote
    from fretwise.dataset.processors.validator import validate_transition

    prev = FingeredNote(string=1, fret=5, finger=Finger.RING, midi_pitch=69, duration=1.0)
    curr = FingeredNote(string=2, fret=7, finger=Finger.RING, midi_pitch=66, duration=1.0)
    issues = validate_transition(prev, curr)
    assert any(i.startswith("same_finger_different_position") for i in issues)
