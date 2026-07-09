"""Producer side of the gears pipeline, ported from the SongsGears project.

This package generates per-song GP-180 rig sheets (``songsgear.fretwise.rig.v1``
verbose records and ``songsgear.fretwise.gear.v2`` compact sheets) that the
consumer side (:mod:`fretwise.gears.adapter` and the web front office) renders.

Layout:

* stdlib-only library modules (``llm``, ``schema``, ``models``, ``skills`` …)
  mirroring ``songs_gears`` with imports rewritten to this package;
* :mod:`fretwise.gears.production.tools` — argparse batch tools (economic
  production batch, export/normalize/validate/compact);
* ``data/`` — packaged skill briefs, JSON schema and example config. The skills
  directory can be overridden with the ``FRETWISE_GEARS_SKILLS_DIR`` env var and
  the target gears directory with ``FRETWISE_GEARS_DIR``.

Canonical filenames come from :mod:`fretwise.gears.naming` (the consumer copy is
the reference); the original SongsGears sources stay untouched.
"""
