"""FretWise dataset & training pipeline — port of the GuitarDataSet library.

This package is the training-side counterpart of ``fretwise.ml`` (inference):
parsers for fingered scores, the training feature extractors (source of truth
for the feature vectors the deployed ONNX models were trained on), dataset
schema/exporters, biomechanical validation, and the build/train/export/eval
pipeline modules.

Ported from ``D:\\DocumentsBenoit\\pythonProject\\GuitarDataSet`` (sources
left intact). Mapping:

- ``GuitarDataSet/config.py``       -> :mod:`fretwise.dataset.config`
  (absolute paths replaced by ``FRETWISE_DATASET_ROOT`` /
  ``FRETWISE_HANDOFF_DIR`` environment variables)
- ``src/parsers/``                  -> :mod:`fretwise.dataset.parsers`
- ``src/features/``                 -> :mod:`fretwise.dataset.features`
- ``src/exporters/``                -> :mod:`fretwise.dataset.exporters`
- ``src/dataset/``                  -> :mod:`fretwise.dataset.data_schema`
  (renamed: ``fretwise.dataset.dataset`` would have been ambiguous)
- ``src/converters/``               -> :mod:`fretwise.dataset.converters`
- ``src/inference/``                -> :mod:`fretwise.dataset.inference`
- ``src/processors/``               -> :mod:`fretwise.dataset.processors`
- ``src/scrapers/``                 -> :mod:`fretwise.dataset.scrapers`
- ``scripts/`` (selected)           -> :mod:`fretwise.dataset.pipeline`
  (thin CLI wrappers live in ``scripts/dataset_*.py`` at the repo root)

The bulky training data (``data/raw``, ``data/processed`` ``.npy``/``.json``
dumps) stays in the GuitarDataSet tree. Heavy ML training dependencies are
optional — see :mod:`fretwise.dataset._mldeps`.
"""
