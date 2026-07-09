"""Training pipeline entry points (ported from ``GuitarDataSet/scripts/``).

Each module exposes a ``main()`` and is runnable via the thin wrappers in
``scripts/dataset_*.py`` (or ``python -m fretwise.dataset.pipeline.<name>``).

Dataset builders:
    build_chord_dataset, build_transition_features,
    build_phrase_window_dataset, build_sequential_training_set,
    build_calibration_examples, build_spec_json, build_transition_spec_json
Training:
    train_finger_classifier, train_transition_cost_v3, train_phrase_window_v1
Export:
    export_transition_onnx (from GuitarDataSet's
    ``export_transition_model_onnx.py``, the parameterized v3 version)
Evaluation / validation:
    evaluate_fretwise, eval_phrase_window_v1, eval_pinky_demotion,
    validate_fingering_quality

Inputs/outputs stay in ``FRETWISE_DATASET_ROOT`` (processed data) and
``FRETWISE_HANDOFF_DIR`` (specs, calibrations, ONNX bundles); deployment into
this repo's ``data/models`` remains a manual, reviewed copy.
"""
