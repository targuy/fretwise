"""Tests for the on-demand fingering lifecycle in the web app.

Covers the three behaviours added when fingering generation became explicit:

1. Embedded ``<LeftFingering>`` in a GP file is read back (so a partition that
   already carries fingers shows them on open, without re-running Viterbi).
2. ``/api/files`` flags such files as having (non-current) fingerings.
3. ``/api/library/cleanup`` strips legacy ``_fingered`` suffixes and moves
   duplicates to ``.trash`` (recoverable), preferring the cleaner-named file.
"""
from __future__ import annotations

import io
import zipfile
from pathlib import Path
from typing import Any

from fretwise.export.gp_writer import GPIF_CONTENT_NAME
from fretwise.web.app import (
    _gp_has_embedded_fingering,
    _read_embedded_gp_fingerings,
    create_app,
)

_GPIF_WITH_FINGERS = """<?xml version="1.0" encoding="UTF-8"?>
<GPIF><Score><Notes>
  <Note id="0"><LeftFingering>I</LeftFingering>
    <Properties><Property name="Fret"><Fret>5</Fret></Property></Properties></Note>
  <Note id="1"><LeftFingering>A</LeftFingering>
    <Properties><Property name="Fret"><Fret>7</Fret></Property></Properties></Note>
  <Note id="2">
    <Properties><Property name="Fret"><Fret>0</Fret></Property></Properties></Note>
</Notes></Score></GPIF>
"""

_GPIF_NO_FINGERS = """<?xml version="1.0" encoding="UTF-8"?>
<GPIF><Score><Notes>
  <Note id="0"><Properties><Property name="Fret"><Fret>5</Fret></Property></Properties></Note>
</Notes></Score></GPIF>
"""


def _write_gp(path: Path, xml: str) -> None:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(GPIF_CONTENT_NAME, xml.encode("utf-8"))
    path.write_bytes(buf.getvalue())


def _route_endpoint(app: Any, path: str) -> Any:
    for route in app.routes:
        if getattr(route, "path", None) == path:
            return route.endpoint
    raise AssertionError(f"Route not found: {path}")


def test_read_embedded_gp_fingerings_round_trip(tmp_path: Path) -> None:
    gp = tmp_path / "song.gp"
    _write_gp(gp, _GPIF_WITH_FINGERS)
    assert _gp_has_embedded_fingering(gp) is True
    embedded = _read_embedded_gp_fingerings(gp)
    # Open-string note (id=2, no LeftFingering) is absent; fretted ones present.
    assert embedded == {"0": "I", "1": "A"}


def test_embedded_reader_handles_missing_and_plain_files(tmp_path: Path) -> None:
    plain = tmp_path / "plain.gp"
    _write_gp(plain, _GPIF_NO_FINGERS)
    assert _gp_has_embedded_fingering(plain) is False
    assert _read_embedded_gp_fingerings(plain) == {}
    # A non-GP / non-zip file never raises.
    junk = tmp_path / "note.txt"
    junk.write_text("not a zip")
    assert _gp_has_embedded_fingering(junk) is False
    assert _read_embedded_gp_fingerings(junk) == {}


def test_files_endpoint_flags_embedded_fingerings(tmp_path: Path) -> None:
    _write_gp(tmp_path / "with.gp", _GPIF_WITH_FINGERS)
    _write_gp(tmp_path / "without.gp", _GPIF_NO_FINGERS)
    app = create_app(tmp_path)
    import asyncio

    endpoint = _route_endpoint(app, "/api/files")
    resp = asyncio.run(endpoint())
    import json

    files = {f["name"]: f for f in json.loads(bytes(resp.body))}
    assert files["with.gp"]["has_fingering"] is True
    # Embedded-only → present but version unknown → not current.
    assert files["with.gp"]["fingering_is_current"] is False
    assert files["without.gp"]["has_fingering"] is False


def test_cleanup_strips_fingered_and_trashes_duplicates(tmp_path: Path) -> None:
    # Legacy output + its plain source both present → fingered copy wins.
    _write_gp(tmp_path / "song.gp", _GPIF_NO_FINGERS)
    _write_gp(tmp_path / "song_fingered.gp", _GPIF_WITH_FINGERS)
    app = create_app(tmp_path)

    endpoint = _route_endpoint(app, "/api/library/cleanup")
    report = endpoint()

    # song_fingered.gp → song.gp (the plain loser went to .trash first).
    assert any(r["to"] == "song.gp" for r in report["renamed"])
    assert (tmp_path / "song.gp").exists()
    assert not (tmp_path / "song_fingered.gp").exists()
    trash = tmp_path / ".trash"
    assert trash.exists() and any(trash.iterdir())
    # The surviving song.gp carries the embedded fingerings.
    assert _gp_has_embedded_fingering(tmp_path / "song.gp") is True
